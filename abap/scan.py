import typing
import pathlib
import itertools

import taglib

from . import const, utils

ScanResult = typing.Generator[typing.Tuple[str, pathlib.Path], None, None]
LabelFunction = typing.Callable[[pathlib.Path], bool]


def make_filename_matcher(
        filenames: typing.Optional[typing.Iterable[str]] = None,
        extensions: typing.Optional[typing.Iterable[str]] = None,
) -> LabelFunction:
    extensions = {f'.{e.lower()}' for e in (extensions or [])}
    names = {n.lower() for n in (filenames or [])}

    def matcher(path: pathlib.Path) -> bool:
        ext_match = path.suffix.lower() in extensions if extensions else True
        fn_match = path.stem.lower() in names if names else True
        return fn_match and ext_match

    return matcher

audio_matcher = make_filename_matcher(extensions=const.AUDIO_EXTENSIONS)
cover_matcher = make_filename_matcher(
    filenames=const.COVER_FILENAMES, extensions=const.IMAGE_EXTENSIONS)


def labeled_scan(path: pathlib.Path,
                 label_funcs: typing.Dict[str, LabelFunction]):
    return {
        k: list(map(utils.second, g))
        for k, g in itertools.groupby(
            sorted(labeled_scan_iter(path, label_funcs), key=utils.first),
            key=utils.first,
        )
    }


def labeled_scan_iter(
        path: pathlib.Path,
        label_funcs: typing.Dict[str, LabelFunction]) -> ScanResult:
    for child in path.iterdir():
        if child.is_dir():
            yield from labeled_scan_iter(child, label_funcs)
        elif child.is_file():
            for label, func in label_funcs.items():
                if func(child):
                    yield label, child
        else:
            pass


def multi(tags: dict, key: str):
    if key in tags:
        return [v for v in (tags.get(key) or [])]
    return []


def get_tags(file_path: pathlib.Path) -> dict:
    audiofile = taglib.File(str(file_path))
    tags = audiofile.tags

    # TODO(naglis): support loading of chapters from different file formats
    # (MP3, M4B, ...).
    chapters, start_chapter = [], None
    start_chapter = 0 if 'CHAPTER000' in tags else None
    start_chapter = (
        1 if start_chapter is None and 'CHAPTER001' in tags else None)

    if start_chapter is not None:
        for ch_no in range(start_chapter, 1000):
            start = utils.first(tags.get(f'CHAPTER{ch_no:03d}', [None]))
            name = utils.first(tags.get(f'CHAPTER{ch_no:03d}NAME', [None]))
            url = utils.first(tags.get(f'CHAPTER{ch_no:03d}URL', [None]))
            if not (start and name):
                break
            chapters.append({
                'name': name,
                'start': start,
                'url': url,
            })

    authors = multi(tags, 'ARTIST')
    result = {
        'album': utils.first_or_default(tags, 'ALBUM'),
        'title': utils.first_or_default(tags, 'TITLE') or file_path.stem,
        'categories': multi(tags, 'GENRE'),
        'description': utils.first_or_default(tags, 'GENRE', default=''),
        'duration': audiofile.length * 1000,
        'chapters': chapters,
    }
    if authors:
        result.update({
            'authors': authors,
        })
    return result
