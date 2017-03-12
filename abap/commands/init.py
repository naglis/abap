import pathlib

from abap import abook, const
from abap.commands import AbapCommand


class InitCommand(AbapCommand):

    def get_parser(self, parser):
        parser.add_argument(
            'directory',
            type=pathlib.Path,
        )
        parser.add_argument(
            '-o',
            '--output',
            default=const.MANIFEST_FILENAME,
            help='abook output filename. Default: %(default)s',
        )
        parser.add_argument('--id')
        return parser

    def take_action(self, args):
        abook_ = abook.abook_from_directory(args.directory)
        with open(args.directory / args.output, 'w') as f:
            abook.dump(abook_, f)
