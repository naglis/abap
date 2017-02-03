import operator
import os
import re

from abook import const

first_of, second_of = map(operator.itemgetter, range(2))
by_sequence = operator.attrgetter('sequence')


def make_regex_filename_matcher(filenames=None, extensions=None):
    if extensions is None:
        extensions = ('[a-z0-9]+',)
    if filenames is None:
        filenames = ('.+',)
    pattern = re.compile(r'(?i)^(%s)\.(%s)$' % (
        '|'.join(filenames), '|'.join(extensions)))

    def matcher(fn):
        return pattern.match(fn) is not None

    return matcher


audio_matcher = make_regex_filename_matcher(extensions=const.AUDIO_EXTENSIONS)
image_matcher = make_regex_filename_matcher(extensions=const.IMAGE_EXTENSIONS)
cover_matcher = make_regex_filename_matcher(
    filenames=const.COVER_FILENAMES, extensions=const.IMAGE_EXTENSIONS)
fanart_matcher = make_regex_filename_matcher(
    filenames=const.FANART_FILENAMES, extensions=const.IMAGE_EXTENSIONS)


def ns(namespace: str, elem: str) -> str:
    '''Returns element name with namespace.'''
    return f'{{{namespace}}}{elem}'


def format_duration(seconds: int) -> str:
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02.0f}:{minutes:02.0f}:{seconds:02.0f}'


def parse_duration(s: str) -> int:
    if not s:
        return 0
    n = s.count(':')
    if n == 2:
        h, m, s = map(int, s.split(':'))
    elif n == 1:
        h, m, s = 0, *map(int, s.split(':'))
    elif n == 0:
        h, m, s = 0, 0, int(s)
    else:
        raise ValueError('Unsupported format')
    return ((h * 60) + m) * 60 + s


def switch_ext(filename: str, new_ext: str) -> str:
    return '{0}.{new_ext}'.format(
        *os.path.splitext(filename),
        new_ext=new_ext,
    )
