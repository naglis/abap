import argparse
import logging
import mimetypes
import sys

import pkg_resources

from . import const, web, utils

LOG = logging.getLogger(__name__)


mimetypes.add_type('audio/x-m4b', '.m4b')


def get_parsers():
    parser = argparse.ArgumentParser(
        prog='abap',
        description='Audiobooks as podcasts',
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {const.ABAP_VERSION}',
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
