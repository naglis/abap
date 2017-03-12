import datetime
import operator
import os
import pathlib
import re
import string
import typing

from abap import const

first_of, second_of = map(operator.itemgetter, range(2))
by_sequence = operator.attrgetter('sequence')
alphanumeric = frozenset(string.ascii_letters + string.digits)


def make_regex_filename_matcher(
        filenames=None, extensions=None) -> typing.Callable[[str], bool]:
    if extensions is None:
        extensions = ('[a-z0-9]+',)
    if filenames is None:
        filenames = ('.+',)
    pattern = re.compile(r'(?i)^(%s)\.(%s)$' % (
        '|'.join(filenames), '|'.join(extensions)))

    def matcher(fn: str) -> bool:
        return pattern.match(fn) is not None

    return matcher


audio_matcher = make_regex_filename_matcher(extensions=const.AUDIO_EXTENSIONS)
image_matcher = make_regex_filename_matcher(extensions=const.IMAGE_EXTENSIONS)
cover_matcher = make_regex_filename_matcher(
    filenames=const.COVER_FILENAMES, extensions=const.IMAGE_EXTENSIONS)
fanart_matcher = make_regex_filename_matcher(
    filenames=const.FANART_FILENAMES, extensions=const.IMAGE_EXTENSIONS)


def make_ns_getter(namespace: str) -> typing.Callable[[str], str]:

    format_string = '{%s}%%s' % namespace

    def getter(elem: str) -> str:
        '''Returns element name with namespace.'''
        return format_string % elem

    return getter


def format_duration(miliseconds: int) -> str:
    seconds, miliseconds = divmod(miliseconds, 1_000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02.0f}:{minutes:02.0f}:{seconds:02.0f}'


def parse_duration(ds: str) -> int:
    if not ds:
        return 0
    ms_sep_pos = ds.rfind('.')
    if not ms_sep_pos == -1:
        ms = round(float(ds[ms_sep_pos:]) * 1_000)
        ds = ds[:ms_sep_pos]
    else:
        ms = 0
    n = ds.count(':')
    if n == 2:
        h, m, s = map(int, ds.split(':'))
    elif n == 1:
        h, m, s = 0, *map(int, ds.split(':'))
    elif n == 0:
        h, m, s = 0, 0, int(ds)
    else:
        raise ValueError('Unsupported format')
    return (((h * 60) + m) * 60 + s) * 1_000 + ms


def validate_lang_code(lang_code: str) -> bool:
    '''
    Based on: https://www.w3.org/TR/REC-html40/struct/dirlang.html#langcodes
    '''
    pattern = re.compile(r'^[A-Za-z]+(?:-[A-Za-z]+)*$')
    return pattern.match(lang_code) is not None


def slugify(s: str) -> str:
    return (''.join(
        (c if c in alphanumeric else '_') for c in s)).strip('_').lower()


def parse_pos(raw: str):
    """
    Parse position from given string.

    Arguments:
        raw     raw data that is parsed to a position.

    Returns:  Position of file in nanoseconds, or None
              if parsing failed.
    """

    # Take care of negative positions
    if raw.startswith(('-', '+')):
        rel = True
        sign = -1 if raw[0] == '-' else 1
        raw = raw[1:]
    else:
        sign = 1
        rel = False

    if set(raw) - const.POS_SYMBOLS:
        return None, None

    parts = raw.split(':')

    if '' in parts:
        return None, None

    h, m, s = 0, 0, 0
    if parts:
        s = int(parts[-1])
    if len(parts) >= 2:
        m = int(parts[-2])
    if len(parts) == 3:
        h = int(parts[-3])
    if len(parts) > 3:
        return None, None

    if h and m and s > 59:
        return None, None

    if not h and m and s > 59:
        return None, None

    if h and m > 59:
        return None, None

    pos = sign * ((h * 60 + m) * 60 + s)
    return rel, pos


def get_data_dir(app_name):
    default = pathlib.PosixPath('~/.local/share').expanduser()
    return pathlib.Path(os.getenv('XDG_DATA_DIR', default)) / app_name


def str_to_date(fmts):

    def converter(s):
        for fmt in fmts:
            try:
                return datetime.datetime.strptime(s, fmt)
            except ValueError:
                pass
        raise ValueError(f'Invalid date(time): {s}')
