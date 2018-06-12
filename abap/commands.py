import abc
import argparse
import logging
import pathlib

import aiohttp.web
import yaml

from . import const, web
from .abook import Abook, prepare_for_export

LOG = logging.getLogger(__name__)


common_parser = argparse.ArgumentParser(add_help=False)
common_parser.add_argument(
    'directory',
    type=pathlib.Path,
    default='.',
)
common_parser.add_argument(
    '--ignore',
    type=pathlib.Path,
    help='files to ignore during scan',
    action='append',
    default=[],
)


class AbapCommand(metaclass=abc.ABCMeta):

    parent_parsers = []

    @abc.abstractmethod
    def init_parser(self, parser: argparse.ArgumentParser) -> None:
        '''Add arguments to the parser'''

    @abc.abstractmethod
    def take_action(self, args: argparse.Namespace) -> None:
        '''Command logic'''


class InitCommand(AbapCommand):
    '''initialize an abook for the audiobook in a given directory'''

    parent_parsers = [
        common_parser,
    ]

    def init_parser(self, parser):
        parser.add_argument(
            '-o', '--output',
            type=argparse.FileType(mode='w'),
            default='-',
        )

    def take_action(self, args: argparse.Namespace):
        ignore_files = {p.resolve(strict=True) for p in args.ignore}
        abook = Abook.from_directory(args.directory, ignore_files)
        d = prepare_for_export(args.directory, dict(abook))

        yaml.safe_dump(
            d,
            args.output,
            default_flow_style=False,
            indent=2,
            width=79,
            allow_unicode=True,
        )


class ServeCommand(AbapCommand):
    '''serve the RSS feed of the abook'''

    parent_parsers = [
        common_parser,
    ]

    def init_parser(self, parser):
        parser.add_argument(
            '-p', '--port',
            type=int,
            default=const.DEFAULT_PORT,
            help='listen on this port. Default: %(default)d',
        )

    def take_action(self, args):
        abook = Abook.from_directory(args.directory, args.ignore)
        abook.merge_manifest()
        LOG.info(f'Serving on port {args.port}')
        aiohttp.web.run_app(web.make_app(abook), port=args.port)
