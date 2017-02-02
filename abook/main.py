import argparse
import collections
import configparser
import logging
import mimetypes
import os
import pathlib
import subprocess

import yaml
import tornado.ioloop

from abook import app, scan, tagutils, utils

mimetypes.add_type('audio/x-m4b', '.m4b')

LOG = logging.getLogger(__name__)


def is_cover(artifact):
    return artifact.type == 'cover'


def is_fanart(artifact):
    return artifact.type == 'fanart'


class AudiobookAbookLoader(object):

    def load(self, fobj, source=None):
        cp = configparser.ConfigParser()
        cp.read_file(fobj, source=source)
        if not cp.has_section('bundle'):
            raise ValueError('Not a bundle')
        bundle_type = cp.get('bundle', 'type', fallback='other')
        extra = collections.OrderedDict(cp.items('bundle'))
        extra.pop('type', None)

        audiofiles = []
        for p in cp.sections():
            if p == 'bundle':
                continue
            else:
                artifact_type = cp.get(p, 'type', fallback='other')
                aextra = collections.OrderedDict(cp.items(p))
                extra.pop('type', None)
                audiofiles.append(Audiofile(
                    p,
                    type=artifact_type,
                    extra=aextra,
                ))
        return Abook(
            source,
            type=bundle_type,
            extra=extra,
            audiofiles=audiofiles,
        )


class AudiobookAbookDumper(object):

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


class Duration(collections.namedtuple('DurationBase', ['duration'])):

    def __str__(self):
        return utils.format_duration(self.duration)

    @classmethod
    def from_string(cls, s):
        return cls(utils.parse_duration(s))


class Filelike(object):

    def __init__(self, path):
        self._path = pathlib.Path(path)
        self._size = None

    def __repr__(self):
        return f'<{self.__class__.__name__}:{self.path}>'

    @property
    def path(self):
        return self._path

    @property
    def size(self):
        if self._size is None:
            self._size = self._path.stat().st_size
        return self._size

    @property
    def mimetype(self):
        return utils.first_of(mimetypes.guess_type(str(self.path)))

    @property
    def ext(self):
        return self._path.suffix.lstrip('.')

    def as_dict(self) -> dict:
        return {
            'path': str(self._path),
        }

    @classmethod
    def from_dict(cls, d: dict):
        return cls(d.get('path'))


class Artifact(Filelike):

    def __init__(self, path, description, type='other'):
        super().__init__(path)
        self.description = description
        self.type = type

    def as_dict(self) -> dict:
        d = super().as_dict()
        d.update({
            'description': self.description,
            'type': self.type,
        })
        return d

    @classmethod
    def from_dict(cls, d: dict):
        return cls(
            d.get('path'),
            d.get('description'),
            d.get('type'),
        )


class Audiofile(Filelike):

    def __init__(self, path, author, title, duration=Duration(0)):
        super().__init__(path)
        self.author = author
        self.title = title
        self.duration = duration

    @classmethod
    def from_dict(cls, d: dict):
        duration = Duration.from_string(d.get('duration', '0'))
        return cls(
            d.get('path'),
            d.get('author'),
            d.get('title'),
            duration=duration,
        )

    def as_dict(self) -> dict:
        d = super().as_dict()
        d.update({
            'title': self.title,
            'author': self.author,
            'duration': str(self.duration),
        })
        return d


class Abook(collections.abc.Sequence):
    VERSION = 1

    def __init__(self, filename, authors, title, audiofiles=None,
                 artifacts=None):
        self._filename = pathlib.Path(filename)
        self.authors = authors
        self.title = title
        self._audiofiles = [] if audiofiles is None else audiofiles
        self.artifacts = [] if artifacts is None else artifacts

    def __getitem__(self, idx):
        return self._audiofiles[idx]

    def __len__(self):
        return len(self._audiofiles)

    @property
    def path(self):
        return self._filename.parent

    @property
    def slug(self):
        return self._filename.stem

    @property
    def has_cover(self):
        return bool(self.covers)

    @property
    def covers(self):
        return [af for af in self.artifacts if is_cover(af)]

    @property
    def has_fanart(self):
        return bool(self.fanarts)

    @property
    def fanarts(self):
        return [af for af in self.artifacts if is_fanart(af)]

    @classmethod
    def from_dict(cls, filename, d):
        return cls(
            filename,
            d.get('authors', []),
            d.get('title'),
            audiofiles=[
                Audiofile.from_dict(ad) for ad in d.get('audiofiles', [])
            ],
            artifacts=[
                Artifact.from_dict(ad) for ad in d.get('artifacts', [])
            ],
        )

    def as_dict(self) -> dict:
        return {
            'version': Abook.VERSION,
            'title': self.title,
            'authors': self.authors,
            'audiofiles': [
                af.as_dict() for af in self
            ],
            'artifacts': [
                af.as_dict() for af in self.artifacts
            ],
        }


def do_init(args):
    results = scan.labeled_scan(
        args.directory,
        {
            'audio': utils.audio_matcher,
            'cover': utils.cover_matcher,
            'fanart': utils.fanart_matcher,
        }
    )

    audio_files = sorted(results.get('audio', []))
    if not audio_files:
        raise SystemExit('No audio files found!')

    covers = results.get('cover', [])
    fanarts = results.get('fanart', [])

    audiofiles, artifacts, authors, albums = (
        [], [], collections.OrderedDict(), collections.OrderedDict(),
    )
    for idx, item_path in enumerate(audio_files, start=1):
        abs_path = os.path.join(args.directory, item_path)
        tags = tagutils.get_tags(abs_path)
        author = tags.artist if tags.artist else 'Unknown artist'
        item = Audiofile(
            item_path,
            author=author,
            title=tags.title,
            duration=Duration(tags.duration),
        )
        if tags.album:
            albums[tags.album] = True
        authors[author] = True
        audiofiles.append(item)

    album = utils.first_of(list(albums.keys())) if albums else 'Unknown album'

    if covers:
        artifacts.append(Artifact(
            utils.first_of(covers),
            'Audiobook cover',
            type='cover',)
        )

    if fanarts:
        artifacts.append(
            Artifact(
                utils.first_of(fanarts),
                'Audiobook fanart',
                type='fanart',
            )
        )

    bundle = Abook(
        args.directory,
        list(authors.keys()),
        album,
        audiofiles=audiofiles,
        artifacts=artifacts,
    )

    with open(os.path.join(args.directory, args.output), 'w') as f:
        # dumper = AudiobookAbookDumper()
        yaml.dump(
            bundle.as_dict(), f, default_flow_style=False, indent=2, width=79)


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
            utils.switch_ext(basename, 'opus'),
        )
        tags = tag_utils.get_tags(filename)

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


def do_serve(args):
    # loader = AudiobookAbookLoader()
    d = yaml.load(args.abook_file)
    bundle = Abook.from_dict(
        os.path.abspath(args.abook_file.name), d)
    # bundle = loader.load(
        # args.abook_file,
        # source=os.path.abspath(args.abook_file.name),
    # )
    bapp = app.make_app(bundle)
    bapp.listen(args.port)
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
