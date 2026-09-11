from __future__ import annotations

import ast
from pathlib import Path
import unittest

from core.download_task import DownloadStatus, DownloadTask


ROOT = Path(__file__).resolve().parents[1]


class ChapterDownloadUiContractTests(unittest.TestCase):
    def test_main_window_uses_chapter_aware_download_page(self) -> None:
        source = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
        self.assertIn(
            "from ui.pages.download_page_chapters import DownloadPage",
            source,
        )

    def test_preview_exposes_per_video_chapter_split_option(self) -> None:
        path = ROOT / "ui" / "widgets" / "chapter_preview_panel.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))

        self.assertIn('QCheckBox("챕터별 파일 저장")', source)
        self.assertIn('options["split_chapters"]', source)
        self.assertIn("preferences.split_chapters", source)
        self.assertIn("self._sync_chapter_controls()", source)
        self.assertIn(
            "self.split_chapters_checkbox.setEnabled(not audio_only)",
            source,
        )
        self.assertIn(
            "self.delete_original_after_split_checkbox.setEnabled(",
            source,
        )
        self.assertIn("챕터별 저장", source)

    def test_preview_choice_is_carried_to_new_download_task(self) -> None:
        path = ROOT / "ui" / "pages" / "download_page_chapters.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))

        self.assertIn("options = self.preview_panel.selected_options()", source)
        self.assertIn('options.get("split_chapters", False)', source)
        self.assertIn('options.get("delete_original_after_split", False)', source)
        self.assertIn("created.split_chapters = bool", source)
        self.assertIn("created.delete_original_after_split = bool", source)
        self.assertIn("preferences.split_chapters and not task.audio_only", source)
        self.assertIn("self._schedule_queue_save()", source)

    def test_video_card_meta_shows_chapter_split_intent_only_when_enabled(self) -> None:
        enabled = DownloadTask(
            task_id="one",
            title="sample",
            url="https://example.invalid/video",
            status=DownloadStatus.QUEUED,
            split_chapters=True,
        )
        disabled = DownloadTask(
            task_id="two",
            title="sample",
            url="https://example.invalid/video2",
            status=DownloadStatus.QUEUED,
            split_chapters=False,
        )

        self.assertIn("챕터별 저장", enabled.meta_text)
        self.assertNotIn("챕터별 저장", disabled.meta_text)

    def test_audio_only_card_never_claims_chapter_split(self) -> None:
        task = DownloadTask(
            task_id="audio",
            title="sample",
            url="https://example.invalid/audio",
            status=DownloadStatus.QUEUED,
            audio_only=True,
            split_chapters=True,
        )

        self.assertNotIn("챕터별 저장", task.meta_text)


if __name__ == "__main__":
    unittest.main()
