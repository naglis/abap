import collections
import operator
import typing
import xml.dom.minidom
import xml.etree.cElementTree as ET

from . import const

first, second = map(operator.itemgetter, range(2))

def items_are_equal(a: typing.Sequence, b: typing.Sequence) -> bool:
    return len(a) == len(b) and sorted(a) == sorted(b)


def first_or_default(mapping: typing.Mapping, key,
                     default: typing.Any = None) -> typing.Any:
    value = mapping.get(key)
    if isinstance(value, collections.abc.Sequence):
        try:
            return first(value)
        except IndexError:
            return default
    return default


def make_ns_getter(namespace: str) -> typing.Callable[[str], str]:

    format_string = '{%s}%%s' % namespace

    def getter(elem: str) -> str:
        '''Returns element name with namespace.'''
        return format_string % elem

    return getter


def pretty_print_xml(tree: ET.Element) -> bytes:
    return xml.dom.minidom.parseString(
        ET.tostring(tree, encoding=const.DEFAULT_XML_ENCODING),
    ).toprettyxml(encoding=const.DEFAULT_XML_ENCODING)


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


def format_duration(miliseconds: int) -> str:
    seconds, miliseconds = divmod(miliseconds, 1_000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02.0f}:{minutes:02.0f}:{seconds:02.0f}'
