import unittest

from abap.abook import Duration


class TestDuration(unittest.TestCase):

    def test_from_string(self):
        test_cases = [
            ('00:00:01', 1_000),
            ('00:01:01', 61_000),
            ('00:01:01.001', 61_001),
        ]
        for s, expected in test_cases:
            with self.subTest(s=s, expected=expected):
                self.assertEqual(Duration.from_string(s).duration, expected)

    def test_format(self):
        test_cases = [
            (1, '{d:h:m:s}', '00:00:01'),
            (61, '{d:h:m:s}', '00:01:01'),
            (61, '{d:h:m:s.ms}', '00:01:01.000'),
        ]
        for duration, fmt, expected in test_cases:
            with self.subTest(duration=duration, fmt=fmt, expected=expected):
                self.assertEqual(fmt.format(d=Duration(duration)), expected)
