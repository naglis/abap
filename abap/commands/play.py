import abc
import argparse
import cmd
import collections
import csv
import logging
import operator
import pathlib
import threading

import blessings
import gi
gi.require_version('Gst', '1.0')  # NOQA

from gi.repository import GLib, GObject, Gst

from . import base
from abap import abook, const, utils


T = blessings.Terminal()
LOG = logging.getLogger()
STATE_CHANGE_TIMEOUT = Gst.SECOND * 4

PlayItem = collections.namedtuple('PlayItem', ['path', 'idx'])


class Receiver(metaclass=abc.ABCMeta):

    @abc.abstractmethod
    def receive(self, event, **kwargs):
        ''


class Pusher(object):

    def __init__(self):
        self._listeners = []

    def add_listener(self, listener):
        self._listeners.append(listener)

    def remove_listener(self, listener):
        if listener in self._listeners:
            self._listeners.remove(listener)

    def emit(self, event, **kwargs):
        LOG.debug(f'Emiting event: {event} with args: {kwargs} '
                  f'from class: {self.__class__.__name__}')
        for listener in self._listeners:
            listener.receive(event, **kwargs)


class Player(Pusher, Receiver):

    def __init__(self):
        super().__init__()
        self.bin = None
        self._current = None

    def init(self):
        LOG.debug('Initializing Player')
        self.bin = Gst.ElementFactory.make('playbin', 'player')

        # By default playbin will render video, so suppress it using a
        # fakesink.
        fakesink = Gst.ElementFactory.make('fakesink', 'fakesink')
        self.bin.set_property('video-sink', fakesink)

        # Disables all video/text decoding in the playbin.
        GST_PLAY_FLAG_VIDEO = 1 << 0
        GST_PLAY_FLAG_TEXT = 1 << 2
        flags = self.bin.get_property('flags')
        flags &= ~(GST_PLAY_FLAG_VIDEO | GST_PLAY_FLAG_TEXT)
        self.bin.set_property('flags', flags)

        self.bus = self.bin.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect('message', self.on_message)

    def deinit(self):
        if self.bin is not None:
            self.bus.remove_signal_watch()

    def prepare_for_play(self, item):
        self._current = item.idx
        self.bin.set_state(Gst.State.NULL)
        self.bin.set_property('uri', item.path)

    def seek(self, position, relative=False):
        current_pos = self.get_position()
        start_pos = current_pos if relative else 0
        new_pos = start_pos + position * Gst.SECOND
        self.bin.get_state(timeout=STATE_CHANGE_TIMEOUT)
        self.emit(
            'seeking', idx=self._current, from_position=current_pos,
            to_position=new_pos,
        )
        self.bin.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
            new_pos,
        )

    def play(self, item=None):
        if item is not None:
            self.prepare_for_play(item)
        self.bin.set_state(Gst.State.PLAYING)
        if item is not None:
            self.emit('started-playing', idx=item.idx)

    def pause(self):
        pos = self.get_position()
        self.bin.set_state(Gst.State.PAUSED)
        self.emit('playback-paused', position=pos, idx=self._current)

    def get_duration(self, seconds=False):
        return utils.second_of(self.bin.query_duration(Gst.Format.TIME)) / (
            Gst.SECOND if seconds else 1)

    def get_position(self, seconds=False):
        return utils.second_of(self.bin.query_position(Gst.Format.TIME)) / (
            Gst.SECOND if seconds else 1)

    def stop(self):
        pos = self.get_position()
        self.bin.set_state(Gst.State.NULL)
        self.emit('playback-stopped', position=pos, idx=self._current)

    def receive(self, event, **kwargs):
        if event == 'play':
            self.play(item=kwargs.get('item'))
        elif event == 'pause':
            self.pause()
        elif event == 'seek':
            self.seek(**kwargs)
        elif event == 'stop':
            self.stop()

    def on_message(self, bus, msg):
        if msg.type == Gst.MessageType.EOS:
            self.bin.set_state(Gst.State.NULL)
            self.emit('playback-finished')
        elif msg.type == Gst.MessageType.ERROR:
            self.bin.set_state(Gst.State.NULL)
            err, debug = msg.parse_error()
            LOG.error(f'Player error "{err}": {debug}')


class PositionLogger(Receiver):

    def __init__(self, filename):
        super().__init__()
        LOG.debug(
            f'Initializing {self.__class__.__name__} on file: {filename}')
        self._filename = filename

    def receive(self, event, **kwargs):
        if event == 'log-position':
            slug, idx, position, type = operator.itemgetter(
                'slug', 'idx', 'position', 'type')(kwargs)
            with open(self._filename, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([slug, idx, type, position])
        else:
            LOG.error(
                f'{self.__class__.__name__} received unknown event: {event}'
            )

class Playlist(Pusher, Receiver):

    def __init__(self):
        super().__init__()
        self._idx = None

    @property
    def audiofiles(self):
        raise NotImplementedError()

    def get_play_item(self, audiofile) -> PlayItem:
        raise NotImplementedError()

    def __getitem__(self, idx):
        return self.audiofiles[idx]

    def __len__(self) -> int:
        return len(self.audiofiles)

    def receive(self, event, **kwargs):
        if event in ('playback-paused', 'playback-stopped'):
            kwargs.update({
                'slug': self._abook.slug,
                'type': event,
            })
            self.emit('log-position', **kwargs)
        else:
            LOG.info('Received event: %s', event)

    def play(self, idx):
        audiofile = self[idx]
        play_item = self.get_play_item(audiofile)
        self.emit('play', item=play_item)
        self._idx = idx

    def resume(self):
        if self._idx is not None:
            self.emit('play')

    def pause(self):
        self.emit('pause')

    def stop(self):
        self.emit('stop')

    def next(self):
        if self._idx is None:
            idx = 0
        else:
            idx = self._idx + 1

        if idx >= len(self._abook):
            LOG.info('Reached end of playlist')
            self.stop()
        else:
            self.play(idx)

    def seek(self, position, relative=False):
        LOG.debug(f'Seeking to: {position} (relative={relative})')
        self.emit('seek', position=position, relative=relative)


class AbookPlaylist(Playlist):

    def __init__(self, abook, *a, **kw):
        super().__init__(*a, **kw)
        self._abook = abook

    @property
    def audiofiles(self):
        return self._abook._audiofiles

    def get_play_item(self, audiofile):
        path = (self._abook.path / audiofile.path).resolve()
        idx = self._abook.index(audiofile)
        return PlayItem(
            path=f'file://{path}',
            idx=idx,
        )


class PlaylistPlayerCmd(cmd.Cmd):

    def __init__(self, player, playlist, *a, **kw):
        super().__init__(*a, **kw)
        self.player = player
        self.playlist = playlist


    # def preloop(self):
        # self.prompt = (f'{T.red}{self.audiobook.author}{T.normal} - '
                       # f'{T.green}{self.audiobook.title}{T.normal}> ')

    def do_ls(self, line):
        for idx, audiofile in enumerate(self.playlist, start=1):
            print(
                f'{T.yellow}{idx}{T.normal} / '
                f'{T.green}{audiofile.title}{T.normal} '
                f'({T.magenta}{audiofile.duration}'
                f'{T.normal})'
            )

    def do_bookmarks(self, line):
        current = self.queue.get_current_item().get()
        if not current:
            print('Not playing')
            return
        for bookmark in current.bookmarks:
            print(
                f'{bookmark.id} / '
                f'{utils.format_duration(bookmark.position)} - '
                f'{bookmark.bookmark_type}'
            )

    def do_info(self, line):
        print(f'''
Author: {self.audiobook.author}
Title: {self.audiobook.title}
Path: {self.audiobook.path}
Duration: {utils.format_duration(self.audiobook.duration)}
        ''')

    def do_seek(self, line):
        relative_seek, pos = utils.parse_pos(line)
        if pos is None:
            print('Invalid seek position')
            return
        self.playlist.seek(pos, relative=relative_seek)

    def do_resume(self, line):
        self.playlist.resume()

    def do_play(self, line):
        idx = 0
        line = line.strip()
        if line and line.isdigit():
            idx = int(line) - 1

        try:
            self.playlist[idx]
        except IndexError:
            print('Playlist empty or index out of bounds')
        else:
            self.playlist.play(idx)

    def do_status(self, line):
        current = self.playlist.get_current_item().get()
        position, duration = (
            self.queue.position.get(),
            self.queue.duration.get(),
        )
        progress = 100.0 * ((position or 0.0) / (duration or 1.0))
        if current is None:
            print('Not playing')
        else:
            print(
                f'Title: {current.title}\n'
                f'Position: {utils.format_duration(position)}'
                f'/{utils.format_duration(duration)} [{progress:0.2f}%]'
            )

    def do_pause(self, line):
        self.playlist.pause()

    def do_stop(self, line):
        '''Stop playlist playback.'''
        self.playlist.stop()

    def do_next(self, line):
        '''Play next item in the playlist.'''
        self.playlist.next()

    def do_previous(self, line):
        '''Play previous item in the playlist.'''
        self.playlist.previous()
    do_prev = do_previous  # Command alias.

    def do_EOF(self, line):
        return True
    do_q = do_quit = do_EOF  # Command aliases.


class PlayCommand(base.AbapCommand):

    def get_parser(self, parser):
        parser.add_argument(
            'directory',
            type=pathlib.Path,
            help='Path to the directory which contains the audiofiles to play.'
                 'If a manifest file exists in the directory, it will be '
                 'parsed, otherwise the directory will be scanned for audio '
                 'files.'
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

        LOG.debug('Initializing Gst')
        Gst.init(None)
        LOG.debug('Initializing GObject threads')
        GObject.threads_init()

        LOG.debug('Initializing GLib loop')
        glib_loop = GLib.MainLoop()
        glib_thread = threading.Thread(target=glib_loop.run, daemon=True)
        glib_thread.start()

        data_dir = utils.get_data_dir('abap')
        data_dir.mkdir(parents=True, exist_ok=True)
        logger = PositionLogger(data_dir / 'bookmarks')
        playlist = AbookPlaylist(abook_)
        player = Player()
        player.add_listener(playlist)
        playlist.add_listener(player)
        playlist.add_listener(logger)
        player.init()
        c = PlaylistPlayerCmd(player, playlist)
        c.cmdloop()

        player.stop()
        player.deinit()

        LOG.debug('Stopping GLib loop')
        glib_loop.quit()
        glib_thread.join()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    c = PlayCommand()
    c.get_parser(p)
    args = p.parse_args()
    c.take_action(args)

