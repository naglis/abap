import argparse
import asyncio
import collections
import contextlib
import logging
import mimetypes
import os
import pathlib

import tornado.ioloop

from abap import abook, app, scan, tagutils, utils

mimetypes.add_type('audio/x-m4b', '.m4b')

LOG = logging.getLogger(__name__)


def do_init(args) -> None:
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


async def produce(queue: asyncio.Queue, abook: abook.Abook):
    for audiofile in abook:
        await queue.put((abook, audiofile))


async def transcode(queue: asyncio.Queue, args):
    output_dir = pathlib.Path(os.path.abspath(args.output_dir))

    while True:

        if queue.empty():
            break

        abook, audiofile = await queue.get()

        if not abook.has_cover:
            cover_filename = None
        else:
            cover_filename = abook.path / utils.first_of(abook.covers).path

        filename = abook.path / audiofile.path
        output_filename = (output_dir / audiofile.path).with_suffix('.opus')
        tags = tagutils.get_tags(str(filename))
        chapter_comments = []
        for i, chapter in enumerate(audiofile.chapters):
            chapter_comments.extend([
                '--comment',
                f'CHAPTER{i:03d}={chapter.start:hh:mm:ss.ms}',
                '--comment',
                f'CHAPTER{i:03d}NAME={chapter.name}',
            ])
        LOG.info(f'Transcoding: {audiofile.path} to: {output_filename}...')

        # Regular suprocess piping does not work in asyncio.
        # Use os.pipe() based on:
        # http://stackoverflow.com/a/36666420
        reader, writer = os.pipe()
        await asyncio.create_subprocess_exec(
            'lame',
            '--quiet',
            '--decode',
            '--mp3input',
            str(filename),
            '-',
            stdout=writer
        )
        os.close(writer)

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
            audiofile.author or ', '.join(abook.authors),
            *chapter_comments,
            '--album',
            abook.title,
            '--title',
            audiofile.title,
            '-',
            str(output_filename),
        ]
        if cover_filename:
            opusenc_args.extend([
                '--picture',
                f'3||Front Cover||{cover_filename!s}',
            ])
        opusenc = await asyncio.create_subprocess_exec(
            *opusenc_args,
            stdin=reader,
        )
        os.close(reader)
        await opusenc.communicate()
        queue.task_done()


def do_transcode(args) -> None:
    data = abook.load(args.abook_file)
    book = abook.Abook.from_dict(
        os.path.abspath(args.abook_file.name), data)

    with contextlib.closing(asyncio.get_event_loop()) as loop:
        queue = asyncio.Queue(args.parallel, loop=loop)
        loop.create_task(produce(queue, book))

        consumer_futures = []
        for idx in range(args.parallel):
            consumer_futures.append(loop.create_task(transcode(queue, args)))

        loop.run_until_complete(asyncio.gather(*consumer_futures, loop=loop))


def do_serve(args) -> None:
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
    transcode_parser.add_argument(
        '-p',
        '--parallel',
        default=os.cpu_count(),
        type=int,
        help='Number of parallel transcoding processes. Default: %(default)s',
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
