import pathlib

import pytest
import schema

from abap.abook import Abook, ITEM_SCHEMA, merge
from abap.render import RSSRenderer, build_rss
from abap.utils import format_duration, parse_duration
from abap.scan import get_tags
from abap.main import main
from abap import (
    __version__,
)


@pytest.fixture
def here():
    return pathlib.Path(__file__).parent


def test_dir(*parts):
    parts = ['test_data'] + list(parts)
    return pathlib.Path(__file__).parent.joinpath(*parts)


@pytest.fixture
def test_abook():
    return Abook.from_directory(test_dir())


@pytest.fixture
def fake_abook():
    fake_abook_data = {
        'title': 'Test Abook',
        'slug': 'test',
        'description': 'Fake desc',
        'authors': [
            'Jane Doe',
            'John Smith',
        ],
        'categories': [
            'CAT1',
        ],
        'items': [
            {
                'path': test_dir('empty.opus'),
                'title': 'Some title',
                'mimetype': 'audio/ogg',
                'size': 123,
            },
        ],
    }
    return Abook(test_dir(), fake_abook_data)


@pytest.mark.parametrize('input, error_cls, expected', [
    ('1:12', None, 72_000),
    ('12', None, 12_000),
    ('1:12:13', None, 4_333_000),
    ('1:12:13.123', None, 4_333_123),
    ('1:12:13,123', ValueError, None),
    ('1:1:12:13', ValueError, None),
    ('1:a:13', ValueError, None),
    ('a', ValueError, None),
    ('', None, 0),
    (None, None, 0),
    ('12.345', None, 12_345),
    ('12.34567', None, 12_346),
])
def test_parse_duration(input, error_cls, expected):
    if error_cls:
        with pytest.raises(error_cls):
            parse_duration(input)
    else:
        assert parse_duration(input) == expected


@pytest.mark.parametrize('test_input, expected', [
    (123, '00:00:00'),
    (1_234, '00:00:01'),
    (61_000, '00:01:01'),
    (3_661_000, '01:01:01'),
])
def test_format_duration(test_input, expected):
    assert format_duration(test_input) == expected


@pytest.mark.parametrize('data, yaml_data, expected', [
    ({'title': 'Foo'}, {'title': 'Bar'}, {'title': 'Bar'}),
    ({'title': 'Foo'}, {'title': 'Bar'}, {'slug': 'bar'}),
    ({'title': 'Foo', 'slug': 'foo'}, {'title': 'Bar'}, {'slug': 'bar'}),
])
def test_merge_yaml_overrides(data, yaml_data, expected, here):
    result = merge(here, data, yaml_data)
    for k, v in expected.items():
        assert result[k] == v


def test_get_tags():
    fn = test_dir('empty.opus')
    tags = get_tags(fn)
    assert tags.get('title') == 'empty'
    assert tags.get('authors') == ['A', 'B']


def test_abook_from_directory(test_abook):
    assert len(test_abook.get('items', [])) == 1
    assert test_abook.get('title') == 'Unknown title'


def test_main_version(capsys):
    try:
        main(argv=['--version'])
    except SystemExit:
        pass
    out, _ = capsys.readouterr()
    assert out.strip() == f'abap {__version__}'


def test_merge_unknown_items_not_added(test_abook):
    filename = 'non_existent.opus'
    yaml_data = {'items': [{
        'path': filename,
    }]}
    test_abook.merge_manifest(yaml_data)
    assert filename not in set(
        map(lambda i: i['path'].name, test_abook.get('items', [])))


@pytest.mark.parametrize('item_dict, is_valid', [
    ({'path': 'foo', 'authors': ['Foo']}, True),
    ({'path': ''}, False),
    ({'path': ' '}, False),
])
def test_abook_item_schema(item_dict, is_valid):
    try:
        ITEM_SCHEMA.validate(item_dict)
    except schema.SchemaError:
        if is_valid:
            pytest.fail('Valid data failed to validate')
    else:
        if not is_valid:
            pytest.fail('Invalid data was validated')


def test_rss_renderer(fake_abook):
    rss = build_rss(
        fake_abook.directory,
        fake_abook,
        renderers={
            'rss': RSSRenderer,
        },
    )
    items = rss.findall('./channel/item')
    assert len(items) == 1

    item = items[0]
    assert item.findtext('title') == 'Some title'
    assert item.findtext('guid') == '1'

    enclosure_attrs = item.find('enclosure').attrib
    assert enclosure_attrs['length'] == '123'
    assert enclosure_attrs['type'] == 'audio/ogg'
    assert enclosure_attrs['url'] == 'episode'
