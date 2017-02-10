import unittest

from abap import utils
from abap.abook import Duration


class TestUtils(unittest.TestCase):

    def test_switch_ext(self):
        test_cases = [
            ('a.jpg', 'png', 'a.png'),
            ('/home/test/a.jpg', 'png', '/home/test/a.png'),
        ]
        for fn, new_ext, expected in test_cases:
            actual = utils.switch_ext(fn, new_ext)
            self.assertEqual(expected, actual)

    def test_parse_duration(self):
        test_cases = [
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
        ]
        for s, exc, expected in test_cases:
            if exc:
                with self.assertRaises(exc):
                    actual = utils.parse_duration(s)
            else:
                actual = utils.parse_duration(s)
                self.assertEqual(actual, expected)

    def test_validate_lang_code(self):
        test_cases = [
            ('en', True),
            ('en-US', True),
            ('en-cockney', True),
            ('i-navajo', True),
            ('x-klingon', True),
            ('Foo,bar', False),
        ]
        for lang_code, expected in test_cases:
            actual = utils.validate_lang_code(lang_code)
            self.assertEqual(actual, expected)


class TestDuration(unittest.TestCase):

    def test_from_string(self):
        test_cases = [
            ('00:00:01', 1000),
            ('00:01:01', 61000),
            ('00:01:01.001', 61001),
        ]
        for s, expected in test_cases:
            d = Duration.from_string(s)
            self.assertEqual(d.duration, expected)

    def test_format(self):
        test_cases = [
            (1, '{d:h:m:s}', '00:00:01'),
            (61, '{d:h:m:s}', '00:01:01'),
            (61, '{d:h:m:s.ms}', '00:01:01.000'),
        ]
        for duration, fmt, expected in test_cases:
            d = Duration(duration)
            self.assertEqual(fmt.format(d=d), expected)
