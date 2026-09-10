from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from app.app_update import (
    UPDATE_CHANNEL_BETA,
    check_app_update,
    release_notes_preview,
)


ROOT = Path(__file__).resolve().parents[1]
ABOUT_PAGE_PATH = ROOT / "ui" / "pages" / "about_page.py"
MAIN_WINDOW_PATH = ROOT / "ui" / "main_window.py"


class ReleaseNotesPreviewTests(unittest.TestCase):
    def test_preview_keeps_changes_and_removes_markdown_noise(self) -> None:
        body = """# RR-V 1.4.0 Community Beta

이번 버전은 **다운로드 경험**을 개선했습니다.

## 주요 변경사항
### 다운로드
- Remux 기능 추가
- [챕터 기능](https://example.test/chapter) 개선

## 설치
이 문장은 앱 미리보기에 나오면 안 됩니다.
"""

        preview = release_notes_preview(body)

        self.assertNotIn("# RR-V", preview)
        self.assertIn("이번 버전은 다운로드 경험을 개선했습니다.", preview)
        self.assertIn("주요 변경사항", preview)
        self.assertIn("• Remux 기능 추가", preview)
        self.assertIn("• 챕터 기능 개선", preview)
        self.assertNotIn("https://", preview)
        self.assertNotIn("이 문장은 앱 미리보기에 나오면 안 됩니다.", preview)

    def test_preview_is_bounded_for_legacy_long_release_body(self) -> None:
        body = "# RR-V 9.9.9\n\n" + "\n".join(
            f"- 변경사항 {index} " + ("내용 " * 20)
            for index in range(80)
        )

        preview = release_notes_preview(body, max_lines=7, max_chars=420)

        self.assertLessEqual(len(preview), 422)
        self.assertIn("• 변경사항 0", preview)
        self.assertTrue(preview.endswith("…"))

    def test_empty_release_body_is_harmless(self) -> None:
        self.assertEqual(release_notes_preview(None), "")
        self.assertEqual(release_notes_preview("   \n\n"), "")

    @patch("app.app_update.fetch_https_bytes")
    def test_update_result_carries_selected_release_notes(self, fetch) -> None:  # type: ignore[no-untyped-def]
        payload = [
            {
                "tag_name": "v1.4.0-community-beta",
                "prerelease": True,
                "draft": False,
                "html_url": "https://github.com/Anima2099/RR-V/releases/tag/v1.4.0-community-beta",
                "assets": [],
                "body": "# RR-V 1.4.0\n\n## 주요 변경사항\n- Release Notes 미리보기 추가",
            }
        ]
        fetch.return_value = json.dumps(payload).encode("utf-8")

        result = check_app_update(update_channel=UPDATE_CHANNEL_BETA)

        self.assertTrue(result.update_available)
        self.assertIn("Release Notes 미리보기 추가", result.release_notes)
        self.assertNotIn("# RR-V", result.release_notes)

    def test_about_page_only_shows_notes_for_available_update(self) -> None:
        source = ABOUT_PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn("self.release_notes_frame.setVisible(False)", source)
        self.assertIn("def _set_release_notes_preview", source)
        self.assertIn("result.release_notes if result.update_available else", source)
        self.assertIn("RR-V {version} 변경사항", source)

    def test_auto_update_prompt_contains_short_release_notes_preview(self) -> None:
        source = MAIN_WINDOW_PATH.read_text(encoding="utf-8")

        self.assertIn("release_notes_preview(", source)
        self.assertIn("max_lines=7", source)
        self.assertIn("max_chars=650", source)
        self.assertIn("이번 업데이트", source)
        self.assertIn("notes_detail", source)


if __name__ == "__main__":
    unittest.main()