import argparse
import logging
import mimetypes

import stevedore

mimetypes.add_type('audio/x-m4b', '.m4b')

LOG = logging.getLogger(__name__)


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
    manager = stevedore.extension.ExtensionManager('abap.command')
    for ext in manager:
        command = ext.plugin()
        p = subparsers.add_parser(ext.name)
        command.get_parser(p)
        p.set_defaults(func=command.take_action)

    args = parser.parse_args()

    logging.basicConfig(level=args.log_level)

    if hasattr(args, 'func'):
        return args.func(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
