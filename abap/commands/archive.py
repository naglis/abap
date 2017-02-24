import logging
import pathlib
import zipfile

from . import base
from abap import abook, const


LOG = logging.getLogger()


class ZipCommand(base.AbapCommand):

    def get_parser(self, parser):
        parser.add_argument(
            'directory',
            type=pathlib.Path,
            help='Path to the directory which contains the audiofiles to zip.'
                'If a manifest file exists in the directory, it will be '
                'parsed, otherwise the directory will be scanned for audio files.'
        )
        parser.add_argument(
            'output',
            help='path to the ZIP archive',
        )
        parser.add_argument(
            '-M',
            '--no-manifest',
            help='Do not archive the manifest file',
            dest='manifest',
            action='store_false',
        )
        return parser

    def take_action(self, args):
        manifest_filename = args.directory / const.MANIFEST_FILENAME
        if manifest_filename.exists():
            with open(manifest_filename, 'r') as f:
                data = abook.load(f)
                abook_ = abook.Abook.from_dict(manifest_filename, data)
        else:
            abook_ = abook.abook_from_directory(args.directory)

        with zipfile.ZipFile(args.output, 'w', zipfile.ZIP_DEFLATED) as abook_zip:
            for af in abook_:
                LOG.info(f'Archiving audiofile: {af.path!s}')
                abook_zip.write(args.directory / af.path)

            for ar in abook_.artifacts:
                LOG.info(f'Archiving artifact: {ar.path!s}')
                abook_zip.write(args.directory / ar.path)

            if args.manifest and manifest_filename.exists():
                LOG.info(f'Archiving manifest file: {manifest_filename!s}')
                abook_zip.write(manifest_filename)
