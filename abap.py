import abc
import argparse
import collections
import copy
import datetime
import itertools
import logging
import mimetypes
import operator
import pathlib
import string
import sys
import time
import typing
import urllib.parse
import xml.dom.minidom
import xml.etree.cElementTree as ET

import pkg_resources
import schema
import taglib
import tornado.web
import yaml


__version__ = '0.1.1a'
DEFAULT_XML_ENCODING = 'utf-8'
DEFAULT_PORT = 8000
RFC822 = '%a, %d %b %Y %H:%M:%S +0000'
ITUNES_NS = 'http://www.itunes.com/dtds/podcast-1.0.dtd'
PSC_NS = 'http://podlove.org/simple-chapters'
RSS_VERSION = '2.0'
PSC_VERSION = '1.2'
MANIFEST_FILENAME = 'abap.yaml'
ALPHANUMERIC = frozenset(string.ascii_letters + string.digits)
AUDIO_EXTENSIONS = (
    'm4a',
    'm4b',
    'mp3',
    'ogg',
    'opus',
)
IMAGE_EXTENSIONS = (
    'jpeg',
    'jpg',
    'png',
)
COVER_FILENAMES = (
    'cover',
    'cover_art',
    'folder',
)
EXPORTABLE_ABOOK_KEYS = (
    'authors',
    'title',
    'slug',
    'description',
    'categories',
    'explicit',
    'cover',
    'items',
)
EXPORTABLE_ITEM_KEYS = (
    'authors',
    'categories',
    'chapters',
    'description',
    'explicit',
    'path',
    'title',
)
LOG = logging.getLogger(__name__)

# Our default time-to-live of RSS feeds (in minutes).
TTL = 60 * 24 * 365


# Custom type hints
ScanResult = typing.Generator[typing.Tuple[str, pathlib.Path], None, None]
LabelFunction = typing.Callable[[str], bool]
ETGenerator = typing.Generator[ET.Element, None, None]


common_parser = argparse.ArgumentParser(add_help=False)
common_parser.add_argument(
    'directory',
    type=pathlib.Path,
    default='.',
)


def non_empty_string(s):
    return isinstance(s, str) and bool(s.strip())


def make_filename_matcher(
        filenames=None,
        extensions=None) -> typing.Callable[[pathlib.Path], bool]:
    extensions = {f'.{e.lower()}' for e in (extensions or [])}
    names = {n.lower() for n in (filenames or [])}

    def matcher(path: pathlib.Path) -> bool:
        ext_match = path.suffix.lower() in extensions if extensions else True
        fn_match = path.stem.lower() in names if names else True
        return fn_match and ext_match

    return matcher


def items_are_equal(a, b):
    return len(a) == len(b) and sorted(a) == sorted(b)


audio_matcher = make_filename_matcher(extensions=AUDIO_EXTENSIONS)
cover_matcher = make_filename_matcher(
    filenames=COVER_FILENAMES, extensions=IMAGE_EXTENSIONS)


def make_ns_getter(namespace: str) -> typing.Callable[[str], str]:

    format_string = '{%s}%%s' % namespace

    def getter(elem: str) -> str:
        '''Returns element name with namespace.'''
        return format_string % elem

    return getter


first, second = map(operator.itemgetter, range(2))
by_priority = operator.attrgetter('priority')
by_priority_and_path = operator.attrgetter('priority', 'file_path')
by_path = operator.itemgetter('path')
by_abook_key = collections.OrderedDict(
    zip(EXPORTABLE_ABOOK_KEYS, range(len(EXPORTABLE_ABOOK_KEYS)))).get
itunes = make_ns_getter(ITUNES_NS)
psc = make_ns_getter(PSC_NS)
mimetypes.add_type('audio/x-m4b', '.m4b')


def render_chapter(chapter: dict) -> ET.Element:
    return ET.Element(
        psc('chapter'),
        attrib={
            'title': chapter['name'],
            'start': format_duration(chapter['start']),
        },
    )


def labeled_scan(path: pathlib.Path,
                 label_funcs: typing.Dict[str, LabelFunction]):
    return {
        k: list(map(second, g))
        for k, g in itertools.groupby(
            sorted(labeled_scan_iter(path, label_funcs), key=first), key=first,
        )
    }


def labeled_scan_iter(
        path: pathlib.Path,
        label_funcs: typing.Dict[str, LabelFunction]) -> ScanResult:
    for child in path.iterdir():
        if child.is_dir():
            yield from labeled_scan_iter(child, label_funcs)
        elif child.is_file():
            for label, func in label_funcs.items():
                if func(child):
                    yield label, child
        else:
            pass


def make_item_sorter(items):
    original_sequences = {
        item['path']: idx
        for idx, item in enumerate(sorted(items, key=by_path), start=1)
    }

    def key(item):
        return item.get('sequence', original_sequences[item['path']])

    return key


def slugify(s: str, replacement='_') -> str:
    r, prev = [], None
    for c in s:
        if c in ALPHANUMERIC:
            r.append(c)
            prev = c
        else:
            if prev == replacement:
                continue
            r.append(replacement)
            prev = replacement

    return ''.join(r).strip(replacement).lower()


def parse_duration(ds: str) -> int:
    if not ds:
        return 0
    ms_sep_pos = ds.rfind('.')
    if not ms_sep_pos == -1:
        ms = round(float(ds[ms_sep_pos:]) * 1_000)
        ds = ds[:ms_sep_pos]
    else:
        ms = 0
    n = ds.count(':')
    if n == 2:
        h, m, s = map(int, ds.split(':'))
    elif n == 1:
        h, m, s = 0, *map(int, ds.split(':'))
    elif n == 0:
        h, m, s = 0, 0, int(ds)
    else:
        raise ValueError('Unsupported format')
    return (((h * 60) + m) * 60 + s) * 1_000 + ms


def format_duration(miliseconds: int) -> str:
    seconds, miliseconds = divmod(miliseconds, 1_000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02.0f}:{minutes:02.0f}:{seconds:02.0f}'


# Schemas for validation of abook data loaded from YAML.
CHAPTER_SCHEMA = schema.Schema({
    'name': str,
    'start': schema.Use(parse_duration),
    schema.Optional('url'): str,  # TODO(naglis): validate URL.
})
ITEM_SCHEMA = schema.Schema({
    'path': non_empty_string,
    schema.Optional('authors'): [
        str,
    ],
    schema.Optional('sequence'): int,
    schema.Optional('explicit'): bool,
    schema.Optional('title'): str,
    schema.Optional('description'): str,
    schema.Optional('categories'): [
        str,
    ],
    schema.Optional('chapters'): [
        CHAPTER_SCHEMA,
    ],
})
ABOOK_SCHEMA = schema.Schema({
    schema.Optional('authors'): [
        str,
    ],
    schema.Optional('title'): str,
    schema.Optional('description'): str,
    schema.Optional('slug'): str,
    schema.Optional('categories'): [
        str,
    ],
    schema.Optional('explicit'): bool,
    schema.Optional('items'): [
        ITEM_SCHEMA,
    ],
    schema.Optional('cover'): str,
})


def multi(tags: dict, key: str):
    if key in tags:
        return [v for v in (tags.get(key) or [])]
    return []


class Abook(collections.abc.Mapping):

    def __init__(self, directory: pathlib.Path, d: dict) -> None:
        self.directory = directory
        self._d = d

    def __getitem__(self, idx):
        return self._d[idx]

    def __iter__(self):
        return iter(self._d)

    def __len__(self) -> int:
        return len(self._d)

    @property
    def manifest(self) -> pathlib.Path:
        return self.directory / MANIFEST_FILENAME

    @property
    def has_manifest(self) -> bool:
        return self.manifest.is_file()

    def merge_manifest(self, yaml_data=None):
        yaml_data = yaml_data or {}

        if not yaml_data:
            try:
                with open(self.manifest) as f:
                    yaml_data = yaml.load(f)
            except FileNotFoundError:
                pass

        if yaml_data:
            yaml_data = ABOOK_SCHEMA.validate(yaml_data)

        d = merge(self.directory, self._d, yaml_data)

        # Sort by sequence.
        items = d.get('items', [])
        d.update({
            'items': sorted(items, key=make_item_sorter(items)),
        })

        self._d = d

    @classmethod
    def from_directory(cls, directory: pathlib.Path):
        d = from_dir(directory)
        return cls(directory, d)


class XMLNamespace(typing.NamedTuple):
    prefix: str
    uri: str


class XMLRenderer(metaclass=abc.ABCMeta):

    def __init__(self, uri_func: typing.Callable = None) -> None:
        self.uri_func = uri_func

    def reverse_uri(self, handler: typing.Optional[str], *args, **kwargs):
        if callable(self.uri_func):
            return self.uri_func(handler, *args, **kwargs)
        else:
            return handler

    @property
    def namespaces(self) -> typing.List[XMLNamespace]:
        return []

    @abc.abstractmethod
    def render_channel(self, abook: Abook) -> ETGenerator:
        '''Yields XML nodes which are appended inside <channel>.'''

    @abc.abstractmethod
    def render_item(self, abook: Abook, item: dict,
                    sequence: int = 0) -> ETGenerator:
        '''Yields XML nodes which are appended inside an <item>.'''


class RSSRenderer(XMLRenderer):

    def render_channel(self, abook: Abook) -> ETGenerator:
        generator = ET.Element('generator')
        generator.text = f'abap/{__version__}'
        yield generator

        title = ET.Element('title')
        title.text = abook['title']
        yield title

        link = ET.Element('link')
        link.text = self.reverse_uri(None)
        yield link

        if abook.get('description'):
            desc = ET.Element('description')
            desc.text = abook['description']
            yield desc

        for category in abook.get('categories', []):
            elem = ET.Element('category')
            elem.text = category
            yield elem
        '''
        lang = ET.Element('language')
        lang.text = abook.lang
        yield lang

        if abook.has_manifest:
            pub_date = ET.Element('pubDate')
            pub_date.text = time.strftime(
                RFC822, abook.publication_date.timetuple(),
            )
            yield pub_date
        '''

        cover_url = self.reverse_uri('cover', abook['slug'])
        image = ET.Element('image')
        ET.SubElement(image, 'url').text = cover_url
        ET.SubElement(image, 'title').text = abook['title']
        ET.SubElement(image, 'link').text = self.reverse_uri(None)
        yield image

        if abook.has_manifest:
            dt = datetime.datetime.fromtimestamp(
                abook.manifest.stat().st_mtime)
        else:
            dt = datetime.datetime.now()
        build_date = ET.Element('lastBuildDate')
        build_date.text = time.strftime(RFC822, dt.timetuple())
        yield build_date

        ttl = ET.Element('ttl')
        ttl.text = str(TTL)
        yield ttl

    def render_item(self, abook: Abook, item: dict,
                    sequence: int = 0) -> ETGenerator:
        title = ET.Element('title')
        title.text = item['title']
        yield title

        guid = ET.Element('guid', attrib={'isPermaLink': 'false'})
        guid.text = str(sequence)
        yield guid

        # FIXME: this is a bit of a workaround in order to help sorting the
        # episodes in the podcast client.
        pub_date = ET.Element('pubDate')
        pub_date.text = time.strftime(
            RFC822,
            (datetime.datetime.now() -
                datetime.timedelta(minutes=sequence)).timetuple())
        yield pub_date

        '''
        if i.subtitle:
            ET.SubElement(
                channel, itunes('subtitle')).text = i.subtitle

        if i.summary:
            ET.SubElement(
                channel, itunes('summary')).text = i.summary
        '''

        yield ET.Element('enclosure', attrib={
            'type': item['mimetype'],
            'length': str(item['size']),
            'url': self.reverse_uri(
                'stream', abook['slug'], str(sequence),
                item['path'].suffix.lstrip('.')),
        })


class ITunesRenderer(XMLRenderer):

    @property
    def namespaces(self) -> typing.List[XMLNamespace]:
        return [
            XMLNamespace('itunes', ITUNES_NS),
        ]

    def render_channel(self, abook: Abook) -> ETGenerator:
        author = ET.Element(itunes('author'))
        author.text = ', '.join(abook['authors'])
        yield author

        for category in abook.get('categories', []):
            category_elem = ET.Element(itunes('category'))
            category_elem.text = category
            yield category_elem

        cover_url = self.reverse_uri('cover', abook['slug'])
        image = ET.Element(itunes('image'), attrib={'href': cover_url})
        yield image

    def render_item(self, abook: Abook, item: dict,
                    sequence: int = 0) -> ETGenerator:
        duration = ET.Element(itunes('duration'))
        duration.text = format_duration(item['duration'])
        yield duration

        if 'explicit' in item:
            explicit = ET.Element(itunes('explicit'))
            explicit.text = 'Yes' if item['explicit'] else 'No'
            yield explicit


class PodloveChapterRenderer(XMLRenderer):

    @property
    def namespaces(self) -> typing.List[XMLNamespace]:
        return [
            XMLNamespace('psc', PSC_NS),
        ]

    def render_channel(self, abook: Abook) -> ETGenerator:
        return
        yield

    def render_item(self, abook: Abook, item: dict,
                    sequence: int = 0) -> ETGenerator:
        if item.get('chapters'):
            chapters = ET.Element(
                psc('chapters'),
                attrib={
                    'version': PSC_VERSION,
                },
            )
            for c in item.get('chapters', []):
                chapters.append(render_chapter(c))
            yield chapters


def merge(directory: pathlib.Path, data: typing.MutableMapping,
          yaml_data: typing.MutableMapping) -> typing.MutableMapping:

    result = copy.deepcopy(data)
    yaml_data = copy.deepcopy(yaml_data)

    def override(key):
        if key in yaml_data:
            result[key] = yaml_data[key]

    items_by_path = {}
    for item in result.get('items', []):
        items_by_path[item['path']] = item

    if ('title' in yaml_data and not
            yaml_data['title'] == data['title'] and
            'slug' not in yaml_data):
        result['slug'] = slugify(yaml_data['title'])

    for key in ('title', 'authors', 'categories', 'description', 'slug'):
        override(key)

    for item in yaml_data.get('items', []):
        item_path = directory / item['path']

        current_item = items_by_path.get(item_path)
        if current_item is None:
            LOG.warn(f'Unknown item: {item_path!s} in YAML data')
            continue

        overrides = {}
        for k in ('title', 'categories', 'description', 'chapters', 'sequence',
                  'explicit'):
            if k in item:
                overrides[k] = item[k]
        if overrides:
            current_item.update(overrides)

    return result


def from_dir(directory: pathlib.Path) -> dict:
    authors, albums, descriptions, categories = map(
        lambda i: collections.OrderedDict(), range(4))
    all_non_explicit = True
    items = []

    results = labeled_scan(
        directory, {
            'audio': audio_matcher,
            'cover': cover_matcher,
        },
    )
    for audio_file in sorted(results.get('audio', [])):
        item = {
            'authors': [
                'Unknown author',
            ],
            'title': audio_file.stem,
            'path': audio_file,
            'size': audio_file.stat().st_size,
            'mimetype': first(mimetypes.guess_type(str(audio_file))),
        }

        tags = get_tags(audio_file)
        item.update(tags)

        if tags.get('authors'):
            for a in tags.get('authors'):
                authors[a] = True
        if tags.get('album'):
            albums[tags['album']] = True
        if tags.get('description'):
            descriptions[tags['description']] = True
        if tags.get('categories'):
            categories[tuple(c for c in sorted(tags.get('categories')))] = True

        if tags.get('explicit') and all_non_explicit:
            all_non_explicit = False

        items.append(item)

    for item in items:
        item.pop('album', None)
        if not item.get('chapters'):
            item.pop('chapters', None)

        if len(descriptions) == 1 or not item.get('description'):
            item.pop('description', None)

        if len(categories) == 1 or not item.get('categories'):
            item.pop('categories', None)

        if all_non_explicit:
            item.pop('explicit', None)

    global_data = {
        'title': 'Unknown title',
        'authors': [
            'Unknown author',
        ],
        'categories': [
        ],
        'items': items,
    }

    if not all_non_explicit:
        global_data.update({
            'explicit': True,
        })

    if authors:
        global_data.update({
            'authors': list(authors),
        })

    if albums:
        if len(albums) > 1:
            LOG.warn('Multiple values for album title found. '
                     'Will use the first one')
        global_data.update({
            'title': first(list(albums.keys())),
        })

    if descriptions:
        if len(descriptions) > 1:
            LOG.warn('Multiple values for description found. '
                     'Will use the first one')
        global_data.update({
            'description': first(descriptions),
        })

    if categories:
        global_data.setdefault('categories', []).extend(sorted(list({
            c for cats in categories for c in cats})))

    covers = results.get('cover', [])
    if covers:
        global_data.update({
            'cover': first(covers),
        })

    global_data.update({
        'slug': slugify(global_data['title']),
    })

    return global_data


def first_or_empty_string(dict_: typing.Mapping, key) -> str:
    v = dict_.get(key)
    if isinstance(v, list):
        return first(v)
    return ''


def first_or_None(dict_: typing.Mapping, key) -> typing.Optional[str]:
    v = dict_.get(key)
    if isinstance(v, list):
        return first(v)
    return None


def get_tags(file_path: pathlib.Path) -> dict:
    audiofile = taglib.File(str(file_path))
    tags = audiofile.tags

    # TODO(naglis): support loading of chapters from different file formats
    # (MP3, M4B, ...).
    chapters, start_chapter = [], None
    start_chapter = 0 if 'CHAPTER000' in tags else None
    start_chapter = (
        1 if start_chapter is None and 'CHAPTER001' in tags else None)

    if start_chapter is not None:
        for ch_no in range(start_chapter, 1000):
            start = first(tags.get(f'CHAPTER{ch_no:03d}', [None]))
            name = first(tags.get(f'CHAPTER{ch_no:03d}NAME', [None]))
            url = first(tags.get(f'CHAPTER{ch_no:03d}URL', [None]))
            if not (start and name):
                break
            chapters.append({
                'name': name,
                'start': start,
                'url': url,
            })

    authors = multi(tags, 'ARTIST')
    result = {
        'album': first_or_None(tags, 'ALBUM'),
        'title': first_or_None(tags, 'TITLE') or file_path.stem,
        'categories': multi(tags, 'GENRE'),
        'description': first_or_empty_string(tags, 'GENRE'),
        'duration': audiofile.length * 1000,
        'chapters': chapters,
    }
    if authors:
        result.update({
            'authors': authors,
        })
    return result


def pretty_print_xml(tree: ET.Element) -> bytes:
    return xml.dom.minidom.parseString(
        ET.tostring(tree, encoding=DEFAULT_XML_ENCODING),
    ).toprettyxml(encoding=DEFAULT_XML_ENCODING)


def load_renderers(entry_point_name='abap.xml_renderer'):
    LOG.debug(f'Loading XML renderers from entry point: {entry_point_name}')

    renderers = collections.OrderedDict()
    for entry_point in pkg_resources.iter_entry_points(entry_point_name):
        LOG.debug(f'Loading XML renderer: {entry_point.name}')
        # FIXME: handle exceptions
        renderers[entry_point.name] = entry_point.load()

    return renderers


def build_rss(directory: pathlib.Path,
              abook: typing.Mapping,
              reverse_url=lambda n, *a: n) -> ET.Element:
    # TODO(naglis): load from setuptools entry-points using stevedore.
    renderers = load_renderers()

    extensions = collections.OrderedDict([
        (n, cls(reverse_url)) for n, cls in renderers.items()
    ])

    for ext_name, ext in extensions.items():
        LOG.debug(f'Registering XML namespaces for renderer: {ext_name}')
        for ns in ext.namespaces:
            ET.register_namespace(ns.prefix, ns.uri)

    rss = ET.Element('rss', attrib={'version': RSS_VERSION})
    channel = ET.SubElement(rss, 'channel')

    for ext_name, ext in extensions.items():
        LOG.debug(f'Rendering channel elements with renderer: {ext_name}')
        for el in ext.render_channel(abook):
            channel.append(el)

    for idx, item in enumerate(abook.get('items', []), start=1):
        item_elem = ET.SubElement(channel, 'item')
        for ext_name, ext in extensions.items():
            LOG.debug(
                f'Rendering item #{idx} elements with renderer: {ext_name}')
            for elem in ext.render_item(abook, item, sequence=idx):
                item_elem.append(elem)

    return rss


class AbookHandler(tornado.web.RequestHandler):

    @property
    def abook(self) -> Abook:
        return self.application.abook

    def slug_exists(self, slug: str) -> bool:
        return self.abook.get('slug') == slug

    def assert_slug(self, slug: str):
        if not self.slug_exists(slug):
            raise tornado.web.HTTPError(status_code=400)


class StreamHandler(tornado.web.StaticFileHandler, AbookHandler):

    def head(self, slug: str, sequence: str, ext: str):
        return self.get(slug, sequence, ext, include_body=False)

    def get(self, slug: str, sequence: str, ext: str,
            include_body: bool = True):
        self.assert_slug(slug)

        try:
            item = self.abook.get('items', [])[int(sequence) - 1]
        except ValueError:
            raise tornado.web.HTTPError(status_code=400)
        except IndexError:
            raise tornado.web.HTTPError(status_code=404)

        self.set_header('Content-Type', item['mimetype'])
        return super().get(item['path'], include_body=include_body)


class CoverHandler(tornado.web.StaticFileHandler, AbookHandler):

    def slug_exists(self, slug):
        return super().slug_exists(slug) and self.abook.get('cover')

    def get(self, slug: str):
        self.assert_slug(slug)
        cover = self.abook.get('cover')
        self.set_header(
            'Content-Type', first(mimetypes.guess_type(str(cover))),
        )
        return super().get(cover)


class RSSHandler(AbookHandler):

    def get(self, slug: str):
        self.assert_slug(slug)

        self.set_header(
            'Content-Type',
            f'application/rss+xml; charset="{DEFAULT_XML_ENCODING}"',
        )

        def make_url_reverse(reverse_func, base_url):

            def url_reverse(endpoint, *args, **kwargs):
                if endpoint:
                    return urllib.parse.urljoin(
                        base_url, reverse_func(endpoint, *args, **kwargs))
                else:
                    return base_url

            return url_reverse

        base_url = f'{self.request.protocol}://{self.request.host}'
        reverse_func = make_url_reverse(self.reverse_url, base_url)

        self.write(
            pretty_print_xml(
                build_rss(
                    self.abook.directory,
                    self.abook,
                    reverse_url=reverse_func,
                ),
            ),
        )


def make_app(abook: Abook):
    app = tornado.web.Application([
        tornado.web.URLSpec(
            r'/(?P<slug>\w+)',
            RSSHandler,
            name='rss',
        ),
        tornado.web.URLSpec(
            r'/(?P<slug>\w+)/stream/(?P<sequence>\d+).(?P<ext>[\w]{1,})',
            StreamHandler,
            {'path': abook.directory},
            name='stream',
        ),
        tornado.web.URLSpec(
            r'/(?P<slug>\w+)/cover',
            CoverHandler,
            {'path': abook.directory},
            name='cover',
        ),
    ])
    app.abook = abook
    return app


class AbapCommand(metaclass=abc.ABCMeta):

    parent_parsers = []

    @abc.abstractmethod
    def init_parser(self, parser: argparse.ArgumentParser) -> None:
        '''Add arguments to the parser'''

    @abc.abstractmethod
    def take_action(self, args: argparse.Namespace) -> None:
        '''Command logic'''


def get_parsers():
    parser = argparse.ArgumentParser(
        prog='abap',
        description='Audiobooks as podcasts',
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {__version__}',
    )
    parser.add_argument(
        '--debug',
        action='store_const',
        const=logging.DEBUG,
        default=logging.INFO,
        dest='loglevel',
        help='output debugging messages',
    )

    subparsers = parser.add_subparsers(title='available commands')

    return parser, subparsers


def _prepare_for_export(directory: pathlib.Path, d: dict) -> dict:

    authors = set()

    def relative_path(path: pathlib.Path) -> str:
        return str(path.relative_to(directory))

    result = copy.deepcopy(d)
    for k in result:
        if k not in EXPORTABLE_ABOOK_KEYS:
            result.pop(k)

    if 'cover' in result:
        result['cover'] = relative_path(result['cover'])

    for item in result.get('items', []):
        for k in list(item.keys()):
            if k not in EXPORTABLE_ITEM_KEYS:
                item.pop(k)
                continue
        authors.update(item.get('authors', []))
        item['path'] = relative_path(item['path'])

    if items_are_equal(authors, result.get('authors', [])):
        for item in result.get('items', []):
            item.pop('authors', None)

    return {
        k: result[k] for k in sorted(result, key=by_abook_key)
    }


class InitCommand(AbapCommand):
    '''initialize an abook for the audiobook in a given directory'''

    parent_parsers = [
        common_parser,
    ]

    def init_parser(self, parser):
        parser.add_argument(
            '-o', '--output',
            type=argparse.FileType(mode='w'),
            default='-',
        )

    def take_action(self, args):
        abook = Abook.from_directory(args.directory)
        d = _prepare_for_export(args.directory, dict(abook))

        yaml.safe_dump(
            d,
            args.output,
            default_flow_style=False,
            indent=2,
            width=79,
            allow_unicode=True,
        )


class ServeCommand(AbapCommand):
    '''serve the RSS feed of the abook'''

    parent_parsers = [
        common_parser,
    ]

    def init_parser(self, parser):
        parser.add_argument(
            '-p', '--port',
            type=int,
            default=DEFAULT_PORT,
            help='listen on this port. Default: %(default)d',
        )

    def take_action(self, args):
        abook = Abook.from_directory(args.directory)
        abook.merge_manifest()
        app = make_app(abook)
        LOG.info(f'Serving on port {args.port}')
        app.listen(args.port)
        tornado.ioloop.IOLoop.current().start()


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    parser, subparsers = get_parsers()

    for entry_point in pkg_resources.iter_entry_points('abap.command'):
        LOG.debug(f'Loading abap command: {entry_point.name}')
        cmd_class = entry_point.load()
        cmd_parser = subparsers.add_parser(
            entry_point.name, parents=cmd_class.parent_parsers,
            help=cmd_class.__doc__,
        )
        cmd = cmd_class()
        cmd.init_parser(cmd_parser)
        cmd_parser.set_defaults(func=cmd.take_action)

    args = parser.parse_args(args=argv)
    logging.basicConfig(level=args.loglevel)

    try:
        return getattr(args, 'func', lambda *a: parser.print_help())(args)
    except KeyboardInterrupt:
        LOG.debug('Keyboard interrupt, exiting.')


if __name__ == '__main__':
    main()
