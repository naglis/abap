import pytest

from abap.abook import Duration


@pytest.mark.parametrize('input, expected', [
    ('00:00:01', 1_000),
    ('00:01:01', 61_000),
    ('00:01:01.001', 61_001),
])
def test_duration_from_string(input, expected):
    assert Duration.from_string(input).duration == expected


@pytest.mark.parametrize('input, fmt, expected', [
    (1, '{d:h:m:s}', '00:00:01'),
    (61, '{d:h:m:s}', '00:01:01'),
    (61, '{d:h:m:s.ms}', '00:01:01.000'),
])
def test_duration_format(input, fmt, expected):
    assert fmt.format(d=Duration(input)) == expected
