import collections
import mimetypes
import pathlib

import attr

from abap import const, utils


def non_negative(instance, attribute, value):
    if not value >= 0:
        raise ValueError(f'{attribute.name} must be non-negative')


def lang_code(instance, attribute, value):
    if not utils.validate_lang_code(value):
        raise ValueError(f'{attribute.name} contains invalid language code')


def is_cover(artifact):
    return artifact.type == 'cover'


def is_fanart(artifact):
    return artifact.type == 'fanart'


@attr.attrs(str=False, frozen=True)
class Duration(object):
    duration = attr.attrib(
        convert=int,
        validator=non_negative,
    )

    def __str__(self):
        return utils.format_duration(self.duration)

    @classmethod
    def from_string(cls, s):
        return cls(utils.parse_duration(s))

    def _split(self):
        minutes, seconds = divmod(self.duration, 60)
        hours, minutes = divmod(minutes, 60)
        return hours, minutes, seconds

    def __format__(self, format):
        h, m, s = self._split()
        if format == 'h:m:s.ms':
            return f'{h:02d}:{m:02d}:{s:02d}.000'
        return f'{h:02d}:{m:02d}:{s:02d}'


@attr.attrs(frozen=True)
class Chapter(object):
    name = attr.attrib()
    start = attr.attrib()
    end = attr.attrib(default=Duration(0))

    @classmethod
    def from_dict(cls, d: dict):
        start = Duration.from_string(d['start'])
        end = Duration.from_string(d.get('end', '0'))
        return cls(d['name'], start, end)

    def as_dict(self) -> dict:
        return {
            'name': self.name,
            'start': str(self.start),
            'end': str(self.end),
        }


@attr.attrs
class Filelike(object):
    _path = attr.attrib(convert=pathlib.Path)
    _size = attr.attrib(init=False, default=None)

    def __repr__(self):
        return f'<{self.__class__.__name__}:{self.path}>'

    @property
    def path(self):
        return self._path

    @property
    def size(self):
        if self._size is None:
            self._size = self._path.stat().st_size
        return self._size

    @property
    def mimetype(self):
        return utils.first_of(mimetypes.guess_type(str(self.path)))

    @property
    def ext(self):
        return self._path.suffix.lstrip('.')

    def as_dict(self) -> dict:
        return {
            'path': str(self.path),
        }

    @classmethod
    def from_dict(cls, d: dict):
        return cls(d.get('path'))


@attr.attrs
class Artifact(Filelike):
    description = attr.attrib()
    type = attr.attrib(default='other')

    def as_dict(self) -> dict:
        d = super().as_dict()
        d.update({
            'description': self.description,
            'type': self.type,
        })
        return d

    @classmethod
    def from_dict(cls, d: dict):
        return cls(
            d.get('path'),
            d.get('description'),
            d.get('type'),
        )


@attr.attrs
class Audiofile(Filelike):
    author = attr.attrib()
    title = attr.attrib()
    duration = attr.attrib(default=0)
    explicit = attr.attrib(default=False)
    chapters = attr.attrib(default=attr.Factory(list), repr=False)

    @classmethod
    def from_dict(cls, d: dict):
        duration = Duration.from_string(d.get('duration', '0'))
        return cls(
            d.get('path'),
            d.get('author'),
            d.get('title'),
            duration=duration,
            chapters=[Chapter.from_dict(cd) for cd in d.get('chapters', [])],
        )

    def as_dict(self) -> dict:
        d = super().as_dict()
        d.update({
            'title': self.title,
            'author': self.author,
            'duration': str(self.duration),
            'explicit': self.explicit,
            'chapters': [c.as_dict() for c in self.chapters],
        })
        return d


@attr.attrs
class Abook(collections.abc.Sequence):
    VERSION = 1

    _filename = attr.attrib(convert=pathlib.Path)
    authors = attr.attrib()
    title = attr.attrib()
    slug = attr.attrib()
    description = attr.attrib(default=None)
    lang = attr.attrib(
        validator=lang_code,
        default=const.DEFAULT_LANG_CODE,
    )
    _audiofiles = attr.attrib(default=attr.Factory(list), repr=False)
    artifacts = attr.attrib(default=attr.Factory(list), repr=False)

    def __getitem__(self, idx):
        return self._audiofiles[idx]

    def __len__(self):
        return len(self._audiofiles)

    @property
    def path(self):
        return self._filename.parent

    @property
    def has_cover(self):
        return bool(self.covers)

    @property
    def covers(self):
        return [af for af in self.artifacts if is_cover(af)]

    @property
    def has_fanart(self):
        return bool(self.fanarts)

    @property
    def fanarts(self):
        return [af for af in self.artifacts if is_fanart(af)]

    @classmethod
    def from_dict(cls, filename, d):
        return cls(
            filename,
            d.get('authors', []),
            d.get('title'),
            d.get('slug'),
            description=d.get('description') or '',
            lang=d.get('lang', const.DEFAULT_LANG_CODE),
            audiofiles=[
                Audiofile.from_dict(ad) for ad in d.get('audiofiles', [])
            ],
            artifacts=[
                Artifact.from_dict(ad) for ad in d.get('artifacts', [])
            ],
        )

    def as_dict(self) -> dict:
        return {
            'version': Abook.VERSION,
            'authors': self.authors,
            'title': self.title,
            'slug': self.slug,
            'description': self.description or '',
            'lang': self.lang,
            'audiofiles': [
                af.as_dict() for af in self
            ],
            'artifacts': [
                af.as_dict() for af in self.artifacts
            ],
        }
