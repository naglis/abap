import unittest

from abap import utils


class TestUtils(unittest.TestCase):

    def test_slugify(self):
        test_cases = [
            ('Labas', 'labas'),
            ('labasą', 'labas'),
            ('ląbas', 'l_bas'),
        ]
        for s, expected in test_cases:
            with self.subTest(s=s, expected=expected):
                actual = utils.slugify(s)
                self.assertEqual(actual, expected)

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
            ('12.345', None, 12345),
            ('12.34567', None, 12346),
        ]
        for s, exc, expected in test_cases:
            with self.subTest(s=s, exc=exc, expected=expected):
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
            with self.subTest(lang_code=lang_code, expected=expected):
                actual = utils.validate_lang_code(lang_code)
                self.assertEqual(actual, expected)
