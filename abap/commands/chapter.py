import pathlib

from . import base
from abap import abook


def parse_audacity_chapters(fobj, ignore_end: bool = False):

    def convert_pos(pos: str) -> int:
        return int(float(pos) * 1_000)

    for line in fobj:
        start, end, name = line.strip().split('\t')
        start, end = map(
            abook.Duration.from_string, (start, '0' if ignore_end else end))
        yield abook.Chapter(name, start, end)


class ImportChaptersCommand(base.AbapCommand):

    def get_parser(self, parser):
        parser.add_argument(
            'manifest',
            type=pathlib.Path,
            help='Path to the abook manifest file.',
        )
        parser.add_argument(
            'chapter_file',
            type=pathlib.Path,
            help='Path to the Audacity chapter file.',
        )
        parser.add_argument(
            'idx',
            type=int,
            help='Index of the audiofile for which the chapters are imported.',
        )
        parser.add_argument(
            '--ignore-end',
            action='store_true',
            help='If set, chapter end position is ignored.',
        )
        return parser

    def take_action(self, args):
        with open(args.manifest, 'r') as f:
            data = abook.load(f)
            abook_ = abook.Abook.from_dict(args.manifest, data)
        try:
            audiofile = abook_[args.idx - 1]
        except IndexError:
            raise SystemExit(
                f'Audiofile with index: {args.idx} does not exist in abook: '
                f'{args.manifest}'
            )
        with open(args.chapter_file, 'r') as f:
            for c in parse_audacity_chapters(f, ignore_end=args.ignore_end):
                audiofile.chapters.append(c)

        with open(args.manifest, 'w') as f:
            abook.dump(abook_, f)
