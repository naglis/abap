import unittest

from abook import utils


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
            ('1:12', None, 72),
            ('12', None, 12),
            ('1:12:13', None, 4333),
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
