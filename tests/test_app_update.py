from __future__ import annotations

import unittest

from app.app_update import _display_version, _version_tuple


class AppUpdateVersionTests(unittest.TestCase):
    def test_version_tuple_normalizes_short_versions(self) -> None:
        self.assertEqual(_version_tuple("1.2"), (1, 2, 0))

    def test_version_tuple_reads_prefixed_tag(self) -> None:
        self.assertEqual(_version_tuple("v1.2.3"), (1, 2, 3))

    def test_version_tuple_ignores_extra_numeric_segments(self) -> None:
        self.assertEqual(_version_tuple("1.2.3.4"), (1, 2, 3))

    def test_version_comparison_orders_release_numbers(self) -> None:
        self.assertGreater(_version_tuple("1.3.0"), _version_tuple("1.2.9"))

    def test_display_version_extracts_semver_from_tag(self) -> None:
        self.assertEqual(_display_version("v1.2.0-community-beta"), "1.2.0")


if __name__ == "__main__":
    unittest.main()
