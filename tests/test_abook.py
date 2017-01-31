import unittest

from abook import switch_ext


class TestUtils(unittest.TestCase):

    def test_switch_ext(self):
        test_cases = [
            ('a.jpg', 'png', 'a.png'),
            ('/home/test/a.jpg', 'png', '/home/test/a.png'),
        ]
        for fn, new_ext, expected in test_cases:
            actual = switch_ext(fn, new_ext)
            self.assertEqual(expected, actual)
