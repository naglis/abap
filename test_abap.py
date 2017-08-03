import pathlib

import pytest

from abap import (
    Abook,
    __version__,
    format_duration,
    get_tags,
    main,
    merge,
    parse_duration,
    slugify,
)


@pytest.fixture
def here():
    return pathlib.Path(__file__).parent


@pytest.fixture
def test_data():
    return here() / 'test_data'


@pytest.mark.parametrize('test_input, expected', [
    ('foo+', 'foo'),
    ('+foo', 'foo'),
    ('foo++bar', 'foo_bar'),
    ('foo (bar)', 'foo_bar'),
    ('Foo bar 9', 'foo_bar_9'),
])
def test_slugify(test_input, expected):
    assert slugify(test_input) == expected


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


def test_get_tags(test_data):
    fn = test_data / 'empty.opus'
    tags = get_tags(fn)
    assert tags.get('title') == 'empty'
    assert tags.get('authors') == ['A', 'B']


def test_abook_from_directory(test_data):
    abook = Abook.from_directory(test_data)
    assert len(abook.get('items', [])) == 1
    assert abook.get('title') == 'Unknown title'


def test_main_version(capsys):
    try:
        main(argv=['--version'])
    except SystemExit:
        pass
    out, _ = capsys.readouterr()
    assert out.strip() == f'abap {__version__}'


def test_merge_unknown_items_not_added(test_data):
    abook = Abook.from_directory(test_data)
    filename = 'non_existent.opus'
    yaml_data = {'items': [{
        'path': filename,
    }]}
    abook.merge_manifest(yaml_data)
    assert filename not in set(
        map(lambda i: i['path'].name, abook.get('items', [])))
