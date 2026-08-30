from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.app_update import (
    UPDATE_CHANNEL_BETA,
    UPDATE_CHANNEL_STABLE,
    _display_version,
    _release_channel,
    _select_latest_release,
    _version_tuple,
    check_app_update,
    normalize_update_channel,
    update_channel_label,
)


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


class AppUpdateChannelTests(unittest.TestCase):
    @staticmethod
    def _release(
        tag: str,
        *,
        prerelease: bool,
        draft: bool = False,
        url: str | None = None,
    ) -> dict[str, object]:
        return {
            "tag_name": tag,
            "prerelease": prerelease,
            "draft": draft,
            "html_url": url or f"https://example.test/{tag}",
        }

    def test_channel_labels_are_korean(self) -> None:
        self.assertEqual(update_channel_label(UPDATE_CHANNEL_STABLE), "정식")
        self.assertEqual(update_channel_label(UPDATE_CHANNEL_BETA), "베타")

    def test_normalize_update_channel_uses_requested_fallback(self) -> None:
        self.assertEqual(
            normalize_update_channel("unknown", UPDATE_CHANNEL_BETA),
            UPDATE_CHANNEL_BETA,
        )

    def test_release_channel_uses_github_prerelease_flag(self) -> None:
        release = self._release("v1.3.0", prerelease=True)
        self.assertEqual(_release_channel(release), UPDATE_CHANNEL_BETA)

    def test_release_channel_treats_beta_tag_as_beta_even_if_flag_is_wrong(self) -> None:
        release = self._release("v1.3.0-community-beta", prerelease=False)
        self.assertEqual(_release_channel(release), UPDATE_CHANNEL_BETA)

    def test_stable_channel_ignores_prerelease(self) -> None:
        payload = [
            self._release("v1.4.0-community-beta", prerelease=True),
            self._release("v1.3.0", prerelease=False),
        ]
        selected = _select_latest_release(payload, UPDATE_CHANNEL_STABLE)
        self.assertIsNotNone(selected)
        release, channel = selected or ({}, "")
        self.assertEqual(release.get("tag_name"), "v1.3.0")
        self.assertEqual(channel, UPDATE_CHANNEL_STABLE)

    def test_beta_channel_can_select_newer_prerelease(self) -> None:
        payload = [
            self._release("v1.4.0-community-beta", prerelease=True),
            self._release("v1.3.0", prerelease=False),
        ]
        selected = _select_latest_release(payload, UPDATE_CHANNEL_BETA)
        self.assertIsNotNone(selected)
        release, channel = selected or ({}, "")
        self.assertEqual(release.get("tag_name"), "v1.4.0-community-beta")
        self.assertEqual(channel, UPDATE_CHANNEL_BETA)

    def test_same_version_stable_release_wins_over_beta(self) -> None:
        payload = [
            self._release("v1.3.0-community-beta", prerelease=True),
            self._release("v1.3.0", prerelease=False),
        ]
        selected = _select_latest_release(payload, UPDATE_CHANNEL_BETA)
        self.assertIsNotNone(selected)
        release, channel = selected or ({}, "")
        self.assertEqual(release.get("tag_name"), "v1.3.0")
        self.assertEqual(channel, UPDATE_CHANNEL_STABLE)

    def test_draft_release_is_ignored(self) -> None:
        payload = [
            self._release("v9.9.9", prerelease=False, draft=True),
            self._release("v1.3.0", prerelease=False),
        ]
        selected = _select_latest_release(payload, UPDATE_CHANNEL_BETA)
        self.assertIsNotNone(selected)
        release, _channel = selected or ({}, "")
        self.assertEqual(release.get("tag_name"), "v1.3.0")

    @patch("app.app_update.fetch_https_bytes")
    def test_current_beta_can_update_to_same_version_stable(self, fetch) -> None:  # type: ignore[no-untyped-def]
        payload = [self._release("v1.3.0", prerelease=False)]
        fetch.return_value = json.dumps(payload).encode("utf-8")

        result = check_app_update(update_channel=UPDATE_CHANNEL_STABLE)

        self.assertTrue(result.update_available)
        self.assertEqual(result.latest_version, "1.3.0")
        self.assertEqual(result.latest_release_channel, UPDATE_CHANNEL_STABLE)
        self.assertIn("같은 번호의 정식 버전", result.message)

    @patch("app.app_update.fetch_https_bytes")
    def test_stable_channel_reports_no_release_when_only_beta_exists(self, fetch) -> None:  # type: ignore[no-untyped-def]
        payload = [self._release("v1.4.0-community-beta", prerelease=True)]
        fetch.return_value = json.dumps(payload).encode("utf-8")

        result = check_app_update(update_channel=UPDATE_CHANNEL_STABLE)

        self.assertFalse(result.update_available)
        self.assertEqual(result.latest_version, "릴리스 없음")
        self.assertIn("정식 릴리스가 없습니다", result.message)


if __name__ == "__main__":
    unittest.main()
