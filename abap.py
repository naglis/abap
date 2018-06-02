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
import sys
import time
import typing
import xml.dom.minidom
import xml.etree.cElementTree as ET

import pkg_resources
import yaml

import aiohttp.web
import multidict
import schema
import slugify
import taglib

__version__ = '0.1.1a'
DEFAULT_XML_ENCODING = 'utf-8'
DEFAULT_PORT = 8000
RFC822 = '%a, %d %b %Y %H:%M:%S +0000'
ITUNES_NS = 'http://www.itunes.com/dtds/podcast-1.0.dtd'
PSC_NS = 'http://podlove.org/simple-chapters'
RSS_VERSION = '2.0'
PSC_VERSION = '1.2'
MANIFEST_FILENAME = 'abap.yaml'
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
LabelFunction = typing.Callable[[pathlib.Path], bool]
ETGenerator = typing.Generator[ET.Element, None, None]


common_parser = argparse.ArgumentParser(add_help=False)
common_parser.add_argument(
    'directory',
    type=pathlib.Path,
    default='.',
)
common_parser.add_argument(
    '--ignore',
    type=pathlib.Path,
    help='files to ignore during scan',
    action='append',
    default=[],
)


def non_empty_string(s: typing.Any) -> bool:
    return isinstance(s, str) and bool(s.strip())


def make_filename_matcher(
        filenames: typing.Optional[typing.Iterable[str]] = None,
        extensions: typing.Optional[typing.Iterable[str]] = None,
) -> LabelFunction:
    extensions = {f'.{e.lower()}' for e in (extensions or [])}
    names = {n.lower() for n in (filenames or [])}

    def matcher(path: pathlib.Path) -> bool:
        ext_match = path.suffix.lower() in extensions if extensions else True
        fn_match = path.stem.lower() in names if names else True
        return fn_match and ext_match

    return matcher


def items_are_equal(a: typing.Sequence, b: typing.Sequence) -> bool:
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

    def merge_manifest(self, yaml_data=None) -> None:
        yaml_data = yaml_data or {}

        if not yaml_data:
            try:
                with open(self.manifest) as f:
                    yaml_data = yaml.load(f)
            except FileNotFoundError:
                pass

        if yaml_data:
            yaml_data = ABOOK_SCHEMA.validate(yaml_data)

        self._d = merge(self.directory, self._d, yaml_data)

    @classmethod
    def from_directory(
            cls, directory: pathlib.Path,
            ignore_files: typing.Optional[typing.Set[pathlib.Path]] = None):
        d = from_dir(directory, ignore_files or set())
        return cls(directory, d)


class XMLNamespace(typing.NamedTuple):
    prefix: str  # noqa: E701. See also: https://git.io/vS5GZ
    uri: str  # noqa


class XMLRenderer(metaclass=abc.ABCMeta):

    def __init__(self, uri_func: typing.Callable = None) -> None:
        self.uri_func = uri_func

    def reverse_uri(self, handler: typing.Optional[str], **kwargs):
        if callable(self.uri_func):
            return self.uri_func(handler, **kwargs)
        else:
            return handler

    def el(self, tag: str,
           text: typing.Optional[str] = None,
           **attrib: typing.Dict[str, str]) -> ET.Element:
        element = ET.Element(tag, attrib=attrib)
        element.text = text
        return element

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
        yield self.el('generator', f'abap/{__version__}')

        yield self.el('title', abook['title'])

        yield self.el('link', self.reverse_uri(None))

        if abook.get('description'):
            yield self.el('description', abook['description'])

        for category in abook.get('categories', []):
            yield self.el('category', category)
        '''
        yield self.el('language', abook.lang)

        if abook.has_manifest:
            yield self.el('pubDate', time.strftime(
                RFC822, abook.publication_date.timetuple()))
        '''

        cover_url = self.reverse_uri('cover', slug=abook['slug'])
        image = self.el('image')
        image.append(self.el('url', cover_url))
        image.append(self.el('title', abook['title']))
        image.append(self.el('link', self.reverse_uri(None)))
        yield image

        if abook.has_manifest:
            dt = datetime.datetime.fromtimestamp(
                abook.manifest.stat().st_mtime)
        else:
            dt = datetime.datetime.now()
        yield self.el('lastBuildDate', time.strftime(RFC822, dt.timetuple()))

        yield self.el('ttl', str(TTL))

    def render_item(self, abook: Abook, item: dict,
                    sequence: int = 0) -> ETGenerator:
        yield self.el('title', item['title'])

        yield self.el('guid', str(sequence), isPermaLink='false')

        # FIXME: this is a bit of a workaround in order to help sorting the
        # episodes in the podcast client.
        pub_date = time.strftime(
            RFC822,
            (datetime.datetime.now() -
                datetime.timedelta(minutes=sequence)).timetuple())
        yield self.el('pubDate', pub_date)

        '''
        if i.subtitle:
            ET.SubElement(
                channel, itunes('subtitle')).text = i.subtitle

        if i.summary:
            ET.SubElement(
                channel, itunes('summary')).text = i.summary
        '''

        yield self.el(
            'enclosure',
            type=item['mimetype'],
            length=str(item['size']),
            url=self.reverse_uri(
                'episode',
                slug=abook['slug'],
                sequence=str(sequence),
                ext=item['path'].suffix.lstrip('.'),
            ),
        )


class ITunesRenderer(XMLRenderer):

    @property
    def namespaces(self) -> typing.List[XMLNamespace]:
        return [
            XMLNamespace('itunes', ITUNES_NS),
        ]

    def render_channel(self, abook: Abook) -> ETGenerator:
        yield self.el(itunes('author'), ', '.join(abook['authors']))

        for category in abook.get('categories', []):
            yield self.el(itunes('category'), category)

        yield self.el(
            itunes('image'),
            href=self.reverse_uri('cover', slug=abook['slug']))

    def render_item(self, abook: Abook, item: dict,
                    sequence: int = 0) -> ETGenerator:
        yield self.el(itunes('duration'), format_duration(item['duration']))

        if 'explicit' in item:
            yield self.el(
                itunes('explicit'), 'Yes' if item['explicit'] else 'No')


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
            chapters = self.el(
                psc('chapters'),
                version=PSC_VERSION,
            )
            for c in item.get('chapters', []):
                chapters.append(self.el(
                    psc('chapter'),
                    title=c['name'],
                    start=format_duration(c['start']),
                ))
            yield chapters


def merge(directory: pathlib.Path, data: typing.MutableMapping,
          yaml_data: typing.MutableMapping) -> typing.MutableMapping:

    result = copy.deepcopy(data)
    yaml_data = copy.deepcopy(yaml_data)
    yaml_items = collections.OrderedDict()

    def override(key):
        if key in yaml_data:
            result[key] = yaml_data[key]

    items_by_path = {}
    for item in result.get('items', []):
        items_by_path[item['path']] = item

    if ('title' in yaml_data and not
            yaml_data['title'] == data['title'] and
            'slug' not in yaml_data):
        result['slug'] = slugify.slugify(yaml_data['title'])

    for key in ('title', 'authors', 'categories', 'description', 'slug'):
        override(key)

    for idx, item in enumerate(yaml_data.get('items', [])):
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

        # Retain index for sorting purposes.
        yaml_items[item_path] = idx

    # Decide sorting order.
    if len(items_by_path) == len(yaml_items):
        LOG.debug(
            'Manifest contains all the items, items without sequence will be '
            'sorted by their order in the manifest')
        sequences = {p: i for i, p in enumerate(yaml_items, start=1)}
    else:
        LOG.debug('Items without sequence will be sorted by path')
        sequences = {
            p: i for i, p in enumerate(sorted(items_by_path), start=1)}

    def sort_key(item):
        return item.get('sequence', sequences[item['path']])

    result.update({
        'items': sorted(result.get('items', []), key=sort_key),
    })

    return result


def from_dir(directory: pathlib.Path, ignore_files) -> dict:
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
        if ignore_files and audio_file.resolve(strict=True) in ignore_files:
            continue
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
            'description': first(list(descriptions.keys())),
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
        'slug': slugify.slugify(global_data['title']),
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
              abook: Abook, reverse_url=lambda n, **kw: n,
              renderers: typing.Optional[typing.Mapping[
                  str, typing.Type[XMLRenderer]]]=None) -> ET.Element:
    renderers = renderers or load_renderers()

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


async def episode_handler(request):
    slug, sequence, ext = operator.itemgetter('slug', 'sequence', 'ext')(
        request.match_info)
    abook = request.app['abooks'].get(slug)
    if not abook:
        raise aiohttp.web.HTTPNotFound()

    try:
        item = abook.get('items', [])[int(sequence) - 1]
    except ValueError:
        raise aiohttp.web.HTTPBadRequest()
    except IndexError:
        raise aiohttp.web.HTTPNotFound()

    return aiohttp.web.FileResponse(
        item['path'],
        headers=multidict.MultiDict({
            'Content-Type': item['mimetype'],
        }),
    )


def make_url_reverse(request):
    app = request.app
    base_url = request.url.origin()

    def url_reverse(resource, **kwargs):
        if resource:
            return str(base_url.join(app.router[resource].url_for(**kwargs)))
        else:
            return str(base_url)

    return url_reverse


async def rss_feed_handler(request):
    slug = request.match_info['slug']
    abook = request.app['abooks'].get(slug)
    if not abook:
        raise aiohttp.web.HTTPNotFound()

    return aiohttp.web.Response(
        body=pretty_print_xml(build_rss(
            abook.directory,
            abook,
            reverse_url=make_url_reverse(request),
        )),
        headers=multidict.MultiDict({
            'Content-Type': (
                f'application/rss+xml; charset="{DEFAULT_XML_ENCODING}"'),
        }),
    )


async def cover_handler(request):
    slug = request.match_info['slug']
    abook = request.app['abooks'].get(slug)
    if not (abook and abook.get('cover')):
        raise aiohttp.web.HTTPNotFound()
    cover = abook.get('cover')
    return aiohttp.web.FileResponse(
        cover,
        headers=multidict.MultiDict({
            'Content-Type': first(mimetypes.guess_type(str(cover))),
        }),
    )


def make_app(abook: Abook):
    app = aiohttp.web.Application()
    # FIXME(naglis): Make slug and ext more strict.
    rss_feed = app.router.add_resource(
        '/abook/{slug}/feed/rss', name='rss_feed')
    rss_feed.add_route('GET', rss_feed_handler)

    episode = app.router.add_resource(
        '/abook/{slug}/episode/{sequence:\d+}.{ext}', name='episode',
    )
    episode.add_route('GET', episode_handler)

    cover = app.router.add_resource('/abook/{slug}/cover', name='cover')
    cover.add_route('GET', cover_handler)

    app['abooks'] = {
        abook['slug']: abook,
    }
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
        ignore_files = {p.resolve(strict=True) for p in args.ignore}
        abook = Abook.from_directory(args.directory, ignore_files)
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
        abook = Abook.from_directory(args.directory, args.ignore)
        abook.merge_manifest()
        app = make_app(abook)
        LOG.info(f'Serving on port {args.port}')
        aiohttp.web.run_app(app, port=args.port)


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
