import argparse
import collections
import configparser
import datetime
import logging
import mimetypes
import operator
import os
import re
import subprocess
import time
import urllib.parse
import xml.dom.minidom
import xml.etree.cElementTree as ET

import mutagen
import yaml
import tornado.ioloop
import tornado.web


first_of, second_of = map(operator.itemgetter, range(2))
by_sequence = operator.attrgetter('sequence')

RFC822 = '%a, %d %b %Y %H:%M:%S +0000'
ITUNES_NS = 'http://www.itunes.com/dtds/podcast-1.0.dtd'
ATOM_NS = 'http://www.w3.org/2005/Atom'

IMAGE_EXTENSIONS = ('jpg', 'jpeg', 'png')
AUDIO_EXTENSIONS = ('mp3', 'ogg', 'm4a', 'm4b', 'opus')
COVER_FILENAMES = (r'cover', r'folder', r'cover[\s_-]?art')
FANART_FILENAMES = (r'fan[\s_-]?art',)
IGNORE_FILENAME = b'.ausis_ignore'

# Our default time-to-live of RSS feeds (in minutes).
TTL = 60 * 24 * 365

LOG = logging.getLogger(__name__)

mimetypes.add_type('audio/x-m4b', '.m4b')


def ns(namespace: str, elem: str) -> str:
    '''Returns element name with namespace.'''
    return f'{{{namespace}}}{elem}'


def format_duration(seconds: int) -> str:
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02.0f}:{minutes:02.0f}:{seconds:02.0f}'


def switch_ext(filename: str, new_ext: str) -> str:
    return '{0}.{new_ext}'.format(
        *os.path.splitext(filename),
        new_ext=new_ext,
    )


class AudiobookBundleLoader(object):

    def load(self, fobj, source=None):
        cp = configparser.ConfigParser()
        cp.read_file(fobj, source=source)
        if not cp.has_section('bundle'):
            raise ValueError('Not a bundle')
        bundle_type = cp.get('bundle', 'type', fallback='other')
        extra = collections.OrderedDict(cp.items('bundle'))
        extra.pop('type', None)

        artifacts = []
        for p in cp.sections():
            if p == 'bundle':
                continue
            else:
                artifact_type = cp.get(p, 'type', fallback='other')
                aextra = collections.OrderedDict(cp.items(p))
                extra.pop('type', None)
                artifacts.append(Artifact(
                    p,
                    type=artifact_type,
                    extra=aextra,
                ))
        return Bundle(
            source,
            type=bundle_type,
            extra=extra,
            artifacts=artifacts,
        )


class AudiobookBundleDumper(object):

    def dump(self, fobj, bundle):
        cp = configparser.ConfigParser()
        cp.add_section('bundle')
        cp.set('bundle', 'type', bundle.type)
        for k, v in bundle.extra.items():
            cp.set('bundle', k, str(v))
        for a in bundle:
            cp.add_section(a.path)
            cp.set(a.path, 'type', a.type)
            for k, v in a.extra.items():
                cp.set(a.path, k, str(v))
        cp.write(fobj)


TAGS_KEYS = [
    'artist',
    'album',
    'title',
    'duration',
    'channels',
    'sample_rate',
]
Tags = collections.namedtuple('Tags', TAGS_KEYS)


class Artifact(object):

    def __init__(self, path, type='other', extra=None):
        self._path = path
        self._type = type
        self.extra = {} if extra is None else extra

    @property
    def path(self):
        return self._path

    @property
    def type(self):
        return self._type

    @property
    def mimetype(self):
        return first_of(mimetypes.guess_type(self.path))

    @property
    def ext(self):
        return second_of(os.path.splitext(self.path)).lstrip('.')


class Bundle(collections.abc.Sequence):

    def __init__(self, filename, artifacts=None, type='other', extra=None):
        self._filename = filename
        self._artifacts = [] if artifacts is None else artifacts
        self._type = type
        self.extra = {} if extra is None else extra

    def __getitem__(self, idx):
        return self._artifacts[idx]

    def __len__(self):
        return len(self._artifacts)

    @property
    def path(self):
        return os.path.dirname(self._filename)

    @property
    def slug(self):
        return first_of(os.path.splitext(os.path.basename(self._filename)))

    @property
    def type(self):
        return self._type


def single_item(tags):
    if isinstance(tags, list):
        return first_of(tags)
    else:
        return tags


def id3_getter(tag, tags):
    v = tags.get(tag)
    if v:
        return single_item(v.text)


def get_tags(file_path):
    tags = mutagen.File(file_path)
    duration = int(tags.info.length)
    ftype = type(tags.info)
    if ftype == mutagen.oggvorbis.OggVorbisInfo:
        artist = single_item(tags.get('artist'))
        album = single_item(tags.get('album'))
        title = single_item(tags.get('title'))
        sample_rate = tags.info.sample_rate
    elif ftype == mutagen.mp3.MPEGInfo:
        artist = id3_getter('TPE1', tags)
        album = id3_getter('TALB', tags)
        title = id3_getter('TIT2', tags)
        sample_rate = tags.info.sample_rate
    elif ftype == mutagen.mp4.MP4Info:
        artist = single_item(tags.get(b'\xa9ART'))
        album = single_item(tags.get(b'\xa9alb'))
        title = single_item(tags.get(b'\xa9nam'))
        sample_rate = tags.info.sample_rate
    elif ftype == mutagen.oggopus.OggOpusInfo:
        artist = single_item(tags.get('artist'))
        album = single_item(tags.get('album'))
        title = single_item(tags.get('title'))
        sample_rate = None
    else:
        raise ValueError('Unknown file type')
    return Tags(
        artist=artist,
        album=album,
        title=title,
        duration=duration,
        channels=tags.info.channels,
        sample_rate=sample_rate,
    )


def make_regex_filename_matcher(filenames=None, extensions=None):
    if extensions is None:
        extensions = ('[a-z0-9]+',)
    if filenames is None:
        filenames = ('.+',)
    pattern = re.compile(r'(?i)^(%s)\.(%s)$' % (
        '|'.join(filenames), '|'.join(extensions)))

    def matcher(fn):
        return pattern.match(fn) is not None

    return matcher


audio_matcher = make_regex_filename_matcher(extensions=AUDIO_EXTENSIONS)
cover_matcher = make_regex_filename_matcher(
    filenames=COVER_FILENAMES, extensions=IMAGE_EXTENSIONS)
fanart_matcher = make_regex_filename_matcher(
    filenames=FANART_FILENAMES, extensions=IMAGE_EXTENSIONS)


def labeled_scan(path: str, label_funcs, path_join=os.path.join):
    results = collections.defaultdict(list)
    for subdir, dirs, files in os.walk(path):
        rel_dir = os.path.relpath(subdir, path)
        rel_dir = '' if rel_dir == '.' else rel_dir
        for fn in files:
            for label, func in label_funcs.items():
                if func(fn):
                    results[label].append(path_join(rel_dir, fn))

    return results


def do_init(args):
    results = labeled_scan(
        args.directory,
        {
            'audio': audio_matcher,
            'cover': cover_matcher,
            'fanart': fanart_matcher,
        }
    )

    audio_files = sorted(results.get('audio', []))
    if not audio_files:
        raise SystemExit('No audio files found!')

    covers = results.get('cover', [])
    fanarts = results.get('fanart', [])

    artifacts, authors, albums = (
        [], collections.OrderedDict(), collections.OrderedDict(),
    )
    for idx, item_path in enumerate(audio_files, start=1):
        abs_path = os.path.join(args.directory, item_path)
        tags = get_tags(abs_path)
        author = tags.artist if tags.artist else 'Unknown artist'
        item = Artifact(
            item_path,
            type='audio',
            extra=dict(
                artist=author,
                title=tags.title,
            ),
        )
        if tags.album:
            albums[tags.album] = True
        authors[author] = True
        artifacts.append(item)

    album = first_of(list(albums.keys())) if albums else 'Unknown album'

    if covers:
        artifacts.append(Artifact(first_of(covers), type='cover'))

    if fanarts:
        artifacts.append(Artifact(first_of(fanarts), type='fanart'))

    bundle = Bundle(
        args.directory,
        artifacts=artifacts,
        type='audiobook',
        extra=dict(
            authors=list(authors.keys()),
            title=album,
        ),
    )

    with open(os.path.join(args.directory, args.output), 'w') as f:
        dumper = AudiobookBundleDumper()
        dumper.dump(f, bundle)


def do_transcode(args):
    data = yaml.load(args.abook_file)
    # book = Audiobook.from_dict(data)

    cover_filename = None
    for image in book.image_files:
        if image.image_type == 'cover':
            cover_filename = os.path.join(
                book.path, image.path
            )

    for af in book.audio_files:
        filename = os.path.join(book.path, af.path)
        basename = os.path.basename(af.path)
        output_filename = os.path.join(
            args.output_dir,
            switch_ext(basename, 'opus'),
        )
        tags = get_tags(filename)

        LOG.info(f'Transcoding: {af.path} to: {output_filename}...')
        lame = subprocess.Popen([
            'lame',
            '--quiet',
            '--decode',
            '--mp3input',
            filename,
            '-'
        ], stdout=subprocess.PIPE)
        opusenc_args = [
            'opusenc',
            '--quiet',
            '--raw',
            '--raw-rate',
            str(tags.sample_rate),
            '--raw-chan',
            str(tags.channels),
            '--bitrate',
            str(args.bitrate),
            '--max-delay',
            str(args.max_delay),
            '--artist',
            af.artist if af.artist else ', '.join(book.authors),
            '--album',
            book.title,
            '--title',
            af.title,
            '-',
            output_filename,
        ]
        if cover_filename:
            opusenc_args.extend([
                '--picture',
                f'3||Front Cover||{cover_filename}',
            ])
        opusenc = subprocess.Popen(opusenc_args, stdin=lame.stdout)
        lame.stdout.close()
        opusenc.communicate()


class AbookApplication(tornado.web.Application):

    def __init__(self, bundle, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bundle = bundle


class StreamHandler(tornado.web.StaticFileHandler):

    def head(self, slug, sequence, ext):
        return self.get(slug, sequence, ext, include_body=False)

    def get(self, slug, sequence, ext, include_body=True):
        bundle = self.application.bundle
        if not bundle.slug == slug:
            raise tornado.web.HTTPError(status_code=404)

        try:
            artifact = bundle[int(sequence)]
        except IndexError:
            raise tornado.web.HTTPError(status_code=404)

        self.set_header('Content-Type', artifact.mimetype)
        return super().get(artifact.path, include_body=include_body)


class CoverHandler(tornado.web.StaticFileHandler):

    def get(self, slug):
        bundle = self.application.bundle
        if not bundle.slug == slug:
            raise tornado.web.HTTPError(status_code=404)

        covers = filter(lambda a: a.type == 'cover', bundle)
        if not covers:
            raise tornado.web.HTTPError(404)
        else:
            cover = first_of(covers)
        self.set_header('Content-Type', cover.mimetype)
        return super().get(cover.path)


class FanartHandler(tornado.web.StaticFileHandler):

    def get(self, slug):
        bundle = self.application.bundle
        if not bundle.slug == slug:
            raise tornado.web.HTTPError(status_code=404)

        fanarts = filter(lambda a: a.type == 'fanart', bundle)
        if not fanarts:
            raise tornado.web.HTTPError(404)
        else:
            fanart = first_of(fanarts)
        self.set_header('Content-Type', fanart.mimetype)
        return super().get(fanart.path)


class RSSHandler(tornado.web.RequestHandler):

    def get(self, slug):
        bundle = self.application.bundle
        if not bundle.slug == slug:
            raise tornado.web.HTTPError(status_code=404)
        base_url = f'{self.request.protocol}://{self.request.host}'
        cover_url = urllib.parse.urljoin(
            base_url, self.reverse_url('cover', bundle.path))
        fanart_url = urllib.parse.urljoin(
            base_url, self.reverse_url('fanart', bundle.path))

        ET.register_namespace('itunes', ITUNES_NS)
        ET.register_namespace('atom', ATOM_NS)

        rss = ET.Element('rss', attrib={'version': '2.0'})
        channel = ET.SubElement(rss, 'channel')

        ET.SubElement(channel, 'title').text = bundle.extra.get('title', '')
        ET.SubElement(channel, 'link').text = base_url
        # ET.SubElement(channel, 'description').text = audiobook.summary
        ET.SubElement(channel, 'language').text = 'en-us'
        ET.SubElement(channel, 'ttl').text = str(TTL)
        '''
        ET.SubElement(channel, 'lastBuildDate').text = time.strftime(
            RFC822, audiobook.pub_date.timetuple())
        '''
        ET.SubElement(channel, ns(ATOM_NS, 'icon')).text = cover_url
        ET.SubElement(channel, ns(ATOM_NS, 'logo')).text = fanart_url
        ET.SubElement(channel, ns(ITUNES_NS, 'author')).text = bundle.extra.get('authors', '')
        ET.SubElement(
            channel, ns(ITUNES_NS, 'image'), attrib={'href': cover_url})

        image = ET.SubElement(channel, 'image')
        ET.SubElement(image, 'url').text = cover_url
        ET.SubElement(image, 'title').text = bundle.extra.get('title', '')
        ET.SubElement(image, 'link').text = base_url

        now = datetime.datetime.now()
        for idx, a in enumerate(filter(lambda a: a.type == 'audio', bundle)):
            item = ET.SubElement(channel, 'item')

            ET.SubElement(item, 'title').text = a.extra.get('title', '')
            ET.SubElement(
                item, 'guid', attrib={'isPermaLink': 'false'}
            ).text = str(idx)
            ET.SubElement(item, 'pubDate').text = time.strftime(
                RFC822,
                (now - datetime.timedelta(seconds=idx)).timetuple()
            )
            # ET.SubElement(
                # item, ns(ITUNES_NS, 'duration')).text = format_duration(
                    # i.duration)
            '''
            ET.SubElement(item, ns(ITUNES_NS, 'explicit')).text = (
                'Yes' if i.explicit else 'No')

            if i.subtitle:
                ET.SubElement(
                    channel, ns(ITUNES_NS, 'subtitle')).text = i.subtitle

            if i.summary:
                ET.SubElement(
                    channel, ns(ITUNES_NS, 'summary')).text = i.summary
            '''

            ET.SubElement(item, 'enclosure', attrib={
                'type': a.mimetype,
                'length': str(
                    os.path.getsize(os.path.join(bundle.path, a.path))),
                'url': urllib.parse.urljoin(
                    base_url, self.reverse_url(
                        'stream', bundle.slug, str(idx), a.ext),
                ),
            })

        self.set_header('Content-Type', 'application/rss+xml; charset="utf-8"')
        self.write(xml.dom.minidom.parseString(
            ET.tostring(rss, encoding='utf-8')).toprettyxml(),
        )


def make_app(bundle):
    return AbookApplication(bundle, [
        tornado.web.URLSpec(r'/(?P<slug>\w+)', RSSHandler, name='rss'),
        tornado.web.URLSpec(
            r'/(?P<slug>\w+)/stream/(?P<sequence>\d+).(?P<ext>[\w]{1,})',
            StreamHandler,
            {'path': bundle.path},
            name='stream',
        ),
        tornado.web.URLSpec(
            r'/(?P<slug>\d+)/cover',
            CoverHandler,
            {'path': bundle.path},
            name='cover',
        ),
        tornado.web.URLSpec(
            r'/(?P<slug>\d+)/fanart',
            FanartHandler,
            {'path': bundle.path},
            name='fanart',
        ),
    ])


def do_serve(args):
    loader = AudiobookBundleLoader()
    bundle = loader.load(
        args.abook_file,
        source=os.path.abspath(args.abook_file.name),
    )
    app = make_app(bundle)
    app.listen(args.port)
    tornado.ioloop.IOLoop.current().start()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-d',
        '--debug',
        dest='log_level',
        action='store_const',
        const=logging.DEBUG,
        default=logging.INFO,
    )
    subparsers = parser.add_subparsers()

    init_parser = subparsers.add_parser('init')
    init_parser.add_argument('directory')
    init_parser.add_argument('output', help='abook output filename')
    init_parser.add_argument('--id')
    init_parser.set_defaults(func=do_init)

    serve_parser = subparsers.add_parser('serve')
    serve_parser.add_argument(
        'abook_file',
        type=argparse.FileType('r'),
    )
    serve_parser.add_argument('-p', '--port', type=int, default=8000)
    serve_parser.set_defaults(func=do_serve)

    transcode_parser = subparsers.add_parser('transcode')
    transcode_parser.add_argument(
        'abook_file',
        type=argparse.FileType('r'),
    )
    transcode_parser.add_argument('output_dir')
    transcode_parser.add_argument(
        '-b',
        '--bitrate',
        metavar='N.NNN',
        type=float,
        default=48.0,
        help='Target bitrate in kbit/sec (6-256/channel). '
             'Default: %(default)s',
    )
    transcode_parser.add_argument(
        '--max-delay',
        metavar='N',
        type=int,
        default=1000,
        help='Maximum container delay in milliseconds (0-1000). '
             'Default: %(default)s'
    )
    transcode_parser.set_defaults(func=do_transcode)

    args = parser.parse_args()

    logging.basicConfig(level=args.log_level)

    if hasattr(args, 'func'):
        return args.func(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
