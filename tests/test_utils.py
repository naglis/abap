import pytest

from abap import utils


@pytest.mark.parametrize('input, expected', [
    ('Labas', 'labas'),
    ('labasą', 'labas'),
    ('ląbas', 'l_bas'),
])
def test_slugify(input, expected):
    assert utils.slugify(input) == expected


@pytest.mark.parametrize('input, error_cls, expected', [
    ('1:12', None, 72000),
    ('12', None, 12000),
    ('1:12:13', None, 4333000),
    ('1:12:13.123', None, 4333123),
    ('1:12:13,123', ValueError, None),
    ('1:1:12:13', ValueError, None),
    ('1:a:13', ValueError, None),
    ('a', ValueError, None),
    ('', None, 0),
    (None, None, 0),
    ('12.345', None, 12345),
    ('12.34567', None, 12346),
])
def test_parse_duration(input, error_cls, expected):
    if error_cls:
        with pytest.raises(error_cls):
            utils.parse_duration(input)
    else:
        assert utils.parse_duration(input) == expected


@pytest.mark.parametrize('input, expected', [
    ('en', True),
    ('en-US', True),
    ('en-cockney', True),
    ('i-navajo', True),
    ('x-klingon', True),
    ('Foo,bar', False),
])
def test_validate_lang_code(input, expected):
    assert utils.validate_lang_code(input) == expected
