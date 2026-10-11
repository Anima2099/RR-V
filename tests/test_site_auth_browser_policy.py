from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from services.site_auth_common import (
    SUPPORTED_LOGIN_BROWSER_KEYS,
    detect_chromium_browsers,
)


ROOT = Path(__file__).resolve().parents[1]


class SiteAuthBrowserPolicyTests(unittest.TestCase):
    def test_supported_site_login_browsers_are_chrome_and_edge_only(self) -> None:
        self.assertEqual(
            SUPPORTED_LOGIN_BROWSER_KEYS,
            frozenset({"chrome", "edge"}),
        )

        with patch.object(Path, "is_file", return_value=True):
            browsers = detect_chromium_browsers()

        self.assertEqual(
            {browser.key for browser in browsers},
            {"chrome", "edge"},
        )
        self.assertEqual(
            {browser.label for browser in browsers},
            {"Google Chrome", "Microsoft Edge"},
        )

    def test_site_auth_messages_do_not_advertise_unsupported_browsers(self) -> None:
        for relative_path in (
            "services/youtube_auth_service.py",
            "services/instagram_auth_service.py",
            "services/tiktok_auth_service.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            with self.subTest(path=relative_path):
                self.assertIn(
                    "Google Chrome 또는 Microsoft Edge를 찾지 못했습니다.",
                    source,
                )
                self.assertNotIn("Vivaldi", source)
                self.assertNotIn("Brave", source)

        settings_source = (
            ROOT / "ui" / "pages" / "settings_page.py"
        ).read_text(encoding="utf-8")
        for method_name in (
            "def _start_youtube_login",
            "def _start_instagram_login",
            "def _start_tiktok_login",
        ):
            start = settings_source.index(method_name)
            end = settings_source.find("\n    def ", start + len(method_name))
            block = settings_source[start:end if end >= 0 else None]
            with self.subTest(method=method_name):
                self.assertIn(
                    "Google Chrome 또는 Microsoft Edge를 찾지 못했습니다.",
                    block,
                )
                self.assertNotIn("Vivaldi", block)
                self.assertNotIn("Brave", block)

    def test_public_docs_match_site_auth_browser_policy(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        checklist = (ROOT / "PACKAGING_CHECKLIST.txt").read_text(encoding="utf-8")

        self.assertIn(
            "지원되는 로그인 브라우저는 **Google Chrome · Microsoft Edge**입니다.",
            readme,
        )
        self.assertIn(
            "사이트 인증 브라우저: **Google Chrome · Microsoft Edge**",
            readme,
        )
        self.assertNotIn(
            "Microsoft Edge · Vivaldi · Brave 인증 브라우저 지원",
            readme,
        )
        self.assertIn(
            "인증 관리 offers installed Chrome / Edge browsers only",
            checklist,
        )


if __name__ == "__main__":
    unittest.main()
