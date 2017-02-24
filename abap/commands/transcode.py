import argparse
import asyncio
import contextlib
import logging
import os
import pathlib

from . import base
from abap import abook, utils, tagutils


LOG = logging.getLogger(__name__)


class TranscodeCommand(base.AbapCommand):

    def get_parser(self, parser):
        parser.add_argument(
            'abook_file',
            type=argparse.FileType('r'),
        )
        parser.add_argument(
            'output_dir',
            type=pathlib.Path,
            help='Path to the directory where transcoded files will be stored.',
        )
        parser.add_argument(
            '-b',
            '--bitrate',
            metavar='N.NNN',
            type=float,
            default=48.0,
            help='Target bitrate in kbit/sec (6-256/channel). '
                'Default: %(default)s',
        )
        parser.add_argument(
            '--max-delay',
            metavar='N',
            type=int,
            default=1000,
            help='Maximum container delay in milliseconds (0-1000). '
                'Default: %(default)s'
        )
        parser.add_argument(
            '-p',
            '--parallel',
            default=os.cpu_count(),
            type=int,
            help='Number of parallel transcoding processes. Default: %(default)s',
        )
        return parser

    @staticmethod
    async def produce(queue: asyncio.Queue, abook: abook.Abook):
        for audiofile in abook:
            await queue.put((abook, audiofile))

    @staticmethod
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

    def take_action(args) -> None:
        data = abook.load(args.abook_file)
        book = abook.Abook.from_dict(
            os.path.abspath(args.abook_file.name), data)

        with contextlib.closing(asyncio.get_event_loop()) as loop:
            queue = asyncio.Queue(args.parallel, loop=loop)
            loop.create_task(TranscodeCommand.produce(
                queue, book))

            consumer_futures = []
            for _ in range(args.parallel):
                consumer_futures.append(
                    loop.create_task(
                        TranscodeCommand.transcode(
                            queue, args)))

            loop.run_until_complete(
                asyncio.gather(*consumer_futures, loop=loop))
