import operator
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
    seconds, miliseconds = divmod(miliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02.0f}:{minutes:02.0f}:{seconds:02.0f}'


def parse_duration(ds: str) -> int:
    if not ds:
        return 0
    if '.' in ds:
        ms = int(ds[-3:])
        ds = ds[:-4]
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
    return (((h * 60) + m) * 60 + s) * 1000 + ms


def validate_lang_code(lang_code: str) -> bool:
    '''
    Based on: https://www.w3.org/TR/REC-html40/struct/dirlang.html#langcodes
    '''
    pattern = re.compile(r'^[A-Za-z]+(?:-[A-Za-z]+)*$')
    return pattern.match(lang_code) is not None


def slugify(s: str) -> str:
    return (''.join((c if c in alphanumeric else '_') for c in s)).strip('_')
