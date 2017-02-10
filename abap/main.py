import argparse
import collections
import logging
import mimetypes
import os
import pathlib
import subprocess

import tornado.ioloop

from abap import abook, app, scan, tagutils, utils

mimetypes.add_type('audio/x-m4b', '.m4b')

LOG = logging.getLogger(__name__)


def do_init(args):
    results = scan.labeled_scan(
        args.directory,
        {
            'audio': utils.audio_matcher,
            'cover': utils.cover_matcher,
            'fanart': utils.fanart_matcher,
            'image': utils.image_matcher,
        }
    )

    audio_files = sorted(results.get('audio', []))
    if not audio_files:
        raise SystemExit('No audio files found!')

    audiofiles, artifacts, authors, albums = (
        [], [], collections.OrderedDict(), collections.OrderedDict(),
    )
    for idx, item_path in enumerate(audio_files, start=1):
        abs_path = os.path.join(args.directory, item_path)
        tags = tagutils.get_tags(abs_path)
        author = tags.artist if tags.artist else 'Unknown artist'
        item = abook.Audiofile(
            item_path,
            author=author,
            title=tags.title,
            duration=abook.Duration(tags.duration),
        )
        if tags.album:
            albums[tags.album] = True
        authors[author] = True
        audiofiles.append(item)

    album = utils.first_of(list(albums.keys())) if albums else 'Unknown album'

    unique = set()
    for c in ('cover', 'fanart', 'image'):
        for result in results.get(c, []):
            if result in unique:
                continue
            artifacts.append(abook.Artifact(result, c, type=c))
            unique.add(result)

    bundle = abook.Abook(
        args.directory,
        list(authors.keys()),
        album,
        utils.slugify(album),
        audiofiles=audiofiles,
        artifacts=artifacts,
    )

    with open(os.path.join(args.directory, args.output), 'w') as f:
        abook.dump(bundle, f)


def do_transcode(args):
    data = abook.load(args.abook_file)
    book = abook.Abook.from_dict(
        os.path.abspath(args.abook_file.name), data)

    output_dir = pathlib.Path(os.path.abspath(args.output_dir))

    if not book.has_cover:
        cover_filename = None
    else:
        cover_filename = book.path / utils.first_of(book.covers).path

    for af in book:
        filename = book.path / af.path
        output_filename = (output_dir / af.path).with_suffix('.opus')
        tags = tagutils.get_tags(str(filename))
        LOG.info(f'Transcoding: {af.path} to: {output_filename}...')
        lame = subprocess.Popen([
            'lame',
            '--quiet',
            '--decode',
            '--mp3input',
            str(filename),
            '-'
        ], stdout=subprocess.PIPE)
        chapter_comments = []
        for i, chapter in enumerate(af.chapters):
            chapter_comments.extend([
                '--comment',
                f'CHAPTER{i:03d}={chapter.start:hh:mm:ss.ms}',
                '--comment',
                f'CHAPTER{i:03d}NAME={chapter.name}',
            ])
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
            af.author if af.author else ', '.join(book.authors),
            *chapter_comments,
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
                f'3||Front Cover||{cover_filename!s}',
            ])
        opusenc = subprocess.Popen(opusenc_args, stdin=lame.stdout)
        lame.stdout.close()
        opusenc.communicate()


def do_serve(args):
    d = abook.load(args.abook_file)
    bundle = abook.Abook.from_dict(
        os.path.abspath(args.abook_file.name), d)
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
