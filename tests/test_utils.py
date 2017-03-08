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
