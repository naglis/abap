import pathlib
import typing

import mutagen

from abap import utils


class Tags(typing.NamedTuple):
    artist: str
    album: str
    title: str
    duration: int
    channels: int
    sample_rate: typing.Optional[int]


def single_item(tags):
    if isinstance(tags, list):
        return utils.first_of(tags)
    else:
        return tags


def id3_getter(tag, tags):
    v = tags.get(tag)
    if v:
        return single_item(v.text)


def get_tags(file_path: pathlib.Path):
    tags = mutagen.File(str(file_path))
    duration = int(tags.info.length * 1_000)
    ftype = type(tags.info)
    if ftype == mutagen.oggvorbis.OggVorbisInfo:
        artist = single_item(tags.get('artist'))
        album = single_item(tags.get('album'))
        title = single_item(tags.get('title'))
        sample_rate = tags.info.sample_rate
    elif ftype == mutagen.mp3.MPEGInfo:
        artist = id3_getter('TPE1', tags)
        album = id3_getter('TALB', tags)
        title = id3_getter('TIT2', tags)
        sample_rate = tags.info.sample_rate
    elif ftype == mutagen.mp4.MP4Info:
        artist = single_item(tags.get(b'\xa9ART'))
        album = single_item(tags.get(b'\xa9alb'))
        title = single_item(tags.get(b'\xa9nam'))
        sample_rate = tags.info.sample_rate
    elif ftype == mutagen.oggopus.OggOpusInfo:
        artist = single_item(tags.get('artist'))
        album = single_item(tags.get('album'))
        title = single_item(tags.get('title'))
        sample_rate = None
    else:
        raise ValueError('Unknown file type')
    return Tags(
        artist=artist,
        album=album,
        title=title,
        duration=duration,
        channels=tags.info.channels,
        sample_rate=sample_rate,
    )
