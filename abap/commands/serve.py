import pathlib

import tornado.ioloop

from . import base
from abap import abook, app, const


class ServeCommand(base.AbapCommand):

    def get_parser(self, parser):
        parser.add_argument(
            'directory',
            type=pathlib.Path,
            help='Path to the directory which contains the audiofiles to '
                 'serve.If a manifest file exists in the directory, '
                 'it will be parsed, otherwise the directory will be scanned '
                 'for audio files.',
        )
        parser.add_argument('-p', '--port', type=int, default=8000)
        return parser

    def take_action(self, args):
        manifest_filename = args.directory / const.MANIFEST_FILENAME
        if manifest_filename.exists():
            with open(manifest_filename, 'r') as f:
                data = abook.load(f)
                abook_ = abook.Abook.from_dict(manifest_filename, data)
        else:
            abook_ = abook.abook_from_directory(args.directory)
        bapp = app.make_app(abook_)
        bapp.listen(args.port)
        tornado.ioloop.IOLoop.current().start()
