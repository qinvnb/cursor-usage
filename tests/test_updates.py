from __future__ import annotations

import unittest

from cursor_usage_app import updates


class VersionTests(unittest.TestCase):
    def test_parse_version(self) -> None:
        self.assertEqual(updates.parse_version("v1.2.3"), (1, 2, 3))
        self.assertGreater(updates.parse_version("1.10.0"), updates.parse_version("1.9.9"))
        self.assertEqual(updates.parse_version(""), (0,))


if __name__ == "__main__":
    unittest.main()
