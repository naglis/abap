import argparse
import collections
import datetime
import logging
import mimetypes
import operator
import os
import random
import re
import subprocess
import time
import urllib.parse
import xml.dom.minidom
import xml.etree.cElementTree as ET

import attr
import mutagen
import yaml
import tornado.ioloop
import tornado.web


first_of = operator.itemgetter(0)
second_of = operator.itemgetter(1)
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
    return "{%s}%s" % (namespace, elem)


def format_duration(seconds: int) -> str:
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return '{:02.0f}:{:02.0f}:{:02.0f}'.format(hours, minutes, seconds)


def switch_ext(filename: str, new_ext: str) -> str:
    return '{0}.{new_ext}'.format(
        *os.path.splitext(filename),
        new_ext=new_ext,
    )


TAGS_KEYS = [
    'artist',
    'album',
    'title',
    'narrator',
    'duration',
    'channels',
    'sample_rate',
]
Tags = collections.namedtuple('Tags', TAGS_KEYS)


@attr.s
class AudioFile(object):
    sequence = attr.ib()
    path = attr.ib()
    artist = attr.ib()
    title = attr.ib()
    narrator = attr.ib()
    duration = attr.ib()
    size = attr.ib()

    @property
    def mimetype(self):
        return first_of(mimetypes.guess_type(self.path))

    @property
    def ext(self):
        return second_of(os.path.splitext(self.path)).lstrip('.')


@attr.s
class ImageFile(object):
    path = attr.ib()
    image_type = attr.ib()

    @property
    def mimetype(self):
        return first_of(mimetypes.guess_type(self.path))

    @property
    def ext(self):
        return second_of(os.path.splitext(self.path)).lstrip('.')


@attr.s
class Audiobook(object):
    path = attr.ib()
    authors = attr.ib()
    narrators = attr.ib()
    title = attr.ib()
    audio_files = attr.ib()
    image_files = attr.ib()
    id = attr.ib()

    @property
    def duration(self) -> int:
        return sum(i.duration for i in self.audio_files)

    @classmethod
    def from_dict(cls, d):
        audio_files = [AudioFile(**a) for a in d.pop('audio_files', [])]
        image_files = [ImageFile(**i) for i in d.pop('image_files', [])]
        d['audio_files'] = audio_files
        d['image_files'] = image_files
        return cls(**d)

    def audiofile_by_sequence(self, sequence):
        for audio_file in self.audio_files:
            if audio_file.sequence == sequence:
                return audio_file

    @property
    def cover(self):
        for image in self.image_files:
            if image.image_type == 'cover':
                return image

    @property
    def fanart(self):
        for image in self.image_files:
            if image.image_type == 'fanart':
                return image


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
        narrator=None,
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

    items, authors, albums = (
        [], collections.OrderedDict(), collections.OrderedDict(),
    )
    for idx, item_path in enumerate(audio_files, start=1):
        abs_path = os.path.join(args.directory, item_path)
        tags = get_tags(abs_path)
        author = tags.artist if tags.artist else 'Unknown artist'
        item = AudioFile(
            path=item_path,
            artist=author,
            title=tags.title,
            narrator='',
            duration=tags.duration,
            size=os.path.getsize(abs_path),
            sequence=idx,
        )
        if tags.album:
            albums[tags.album] = True
        authors[author] = True
        items.append(item)

    album = first_of(list(albums.keys())) if albums else 'Unknown album'

    image_files = []
    if covers:
        image_files.append(
            ImageFile(
                path=first_of(covers),
                image_type='cover',
            )
        )

    if fanarts:
        image_files.append(
            ImageFile(
                path=first_of(fanarts),
                image_type='fanart',
            )
        )

    id = args.id or str(random.randint(0, 2 << 63))

    audiobook_path = os.path.relpath(
        args.directory, os.path.dirname(args.output))
    book = Audiobook(
        id=id,
        path=audiobook_path,
        authors=list(authors.keys()),
        narrators=[],
        title=album,
        audio_files=items,
        image_files=image_files,
    )

    with open(args.output, 'w') as f:
        f.write(yaml.dump(
            attr.asdict(book),
            indent=2,
            default_flow_style=False,
            explicit_start=True
        ))


def do_transcode(args):
    data = yaml.load(args.abook_file)
    book = Audiobook.from_dict(data)

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

        LOG.info(
            'Transcoding: {0.path} to: {1}...'.format(af, output_filename)
        )
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
        narrators = book.narrators or []
        if af.narrator:
            narrators = [af.narrator]

        for narrator in narrators:
            opusenc_args.extend([
                '--comment',
                'narrator=%s' % narrator,
            ])

        if cover_filename:
            opusenc_args.extend([
                '--picture',
                '3||Front Cover||%s' % cover_filename,
            ])
        opusenc = subprocess.Popen(opusenc_args, stdin=lame.stdout)
        lame.stdout.close()
        opusenc.communicate()


class AbookApplication(tornado.web.Application):

    def __init__(self, abook, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.abook = abook


class StreamHandler(tornado.web.StaticFileHandler):

    def get(self, book_id, sequence, ext):
        audiobook = self.application.abook
        if not audiobook.id == book_id:
            raise tornado.web.HTTPError(status_code=404)

        audio_file = audiobook.audiofile_by_sequence(int(sequence))
        self.set_header('Content-Type', audio_file.mimetype)
        if not audio_file:
            raise tornado.web.HTTPError(404)
        return super().get(audio_file.path)


class CoverHandler(tornado.web.StaticFileHandler):

    def get(self, book_id):
        audiobook = self.application.abook
        if not audiobook.id == book_id:
            raise tornado.web.HTTPError(status_code=404)

        cover = audiobook.cover
        if not cover:
            raise tornado.web.HTTPError(404)
        self.set_header('Content-Type', cover.mimetype)
        return super().get(cover.path)


class FanartHandler(tornado.web.StaticFileHandler):

    def get(self, book_id):
        audiobook = self.application.abook
        if not audiobook.id == book_id:
            raise tornado.web.HTTPError(status_code=404)

        fanart = audiobook.fanart
        if not fanart:
            raise tornado.web.HTTPError(404)
        self.set_header('Content-Type', fanart.mimetype)
        return super().get(fanart.path)


class RSSHandler(tornado.web.RequestHandler):

    def get(self, book_id):
        audiobook = self.application.abook
        if not audiobook.id == book_id:
            raise tornado.web.HTTPError(status_code=404)

        base_url = '{req.protocol}://{req.host}'.format(req=self.request)
        cover_url = urllib.parse.urljoin(
            base_url, self.reverse_url('cover', audiobook.id))
        fanart_url = urllib.parse.urljoin(
            base_url, self.reverse_url('fanart', audiobook.id))

        ET.register_namespace('itunes', ITUNES_NS)
        ET.register_namespace('atom', ATOM_NS)

        rss = ET.Element('rss', attrib={'version': '2.0'})
        channel = ET.SubElement(rss, 'channel')

        ET.SubElement(channel, 'title').text = audiobook.title
        ET.SubElement(channel, 'link').text = base_url
        # ET.SubElement(channel, 'description').text = audiobook.summary
        ET.SubElement(channel, 'language').text = 'en-us'
        ET.SubElement(channel, 'ttl').text = '%s' % TTL
        '''
        ET.SubElement(channel, 'lastBuildDate').text = time.strftime(
            RFC822, audiobook.pub_date.timetuple())
        '''
        ET.SubElement(channel, ns(ATOM_NS, 'icon')).text = cover_url
        ET.SubElement(channel, ns(ATOM_NS, 'logo')).text = fanart_url
        ET.SubElement(channel, ns(ITUNES_NS, 'author')).text = ', '.join(
            audiobook.authors)
        ET.SubElement(
            channel, ns(ITUNES_NS, 'image'), attrib={'href': cover_url})

        image = ET.SubElement(channel, 'image')
        ET.SubElement(image, 'url').text = cover_url
        ET.SubElement(image, 'title').text = audiobook.title
        ET.SubElement(image, 'link').text = base_url

        now = datetime.datetime.now()
        for i in sorted(audiobook.audio_files, key=by_sequence):
            item = ET.SubElement(channel, 'item')

            ET.SubElement(item, 'title').text = i.title
            ET.SubElement(
                item, 'guid', attrib={'isPermaLink': 'false'}
            ).text = '%s' % i.sequence
            ET.SubElement(item, 'pubDate').text = time.strftime(
                RFC822,
                (now - datetime.timedelta(seconds=i.sequence)).timetuple()
            )
            ET.SubElement(
                item, ns(ITUNES_NS, 'duration')).text = format_duration(
                    i.duration)
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
                'type': i.mimetype,
                'length': '%d' % i.size,
                'url': urllib.parse.urljoin(
                    base_url, self.reverse_url(
                        'stream', audiobook.id, '%s' % i.sequence, i.ext),
                ),
            })

        self.set_header('Content-Type', 'application/rss+xml; charset="utf-8"')
        self.write(xml.dom.minidom.parseString(
            ET.tostring(rss, encoding='utf-8')).toprettyxml(),
        )


def make_app(abook):
    return AbookApplication(abook, [
        tornado.web.URLSpec(
            r'/(?P<book_id>\d+)',
            RSSHandler,
            name='rss',
        ),
        tornado.web.URLSpec(
            r'''(?x)
            /(?P<book_id>\d+)/stream/
            (?P<sequence>\d+).(?P<ext>[A-Za-z0-9]{1,})''',
            StreamHandler,
            {'path': abook.path},
            name='stream',
        ),
        tornado.web.URLSpec(
            r'/(?P<book_id>\d+)/cover',
            CoverHandler,
            {'path': abook.path},
            name='cover',
        ),
        tornado.web.URLSpec(
            r'/(?P<book_id>\d+)/fanart',
            FanartHandler,
            {'path': abook.path},
            name='fanart',
        ),
    ])


def do_serve(args):
    data = yaml.load(args.abook_file)
    book = Audiobook.from_dict(data)
    app = make_app(book)
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
    init_parser.add_argument('output', help='abook output file path')
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
