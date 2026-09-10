from __future__ import annotations

import ast
from pathlib import Path
import tempfile
import unittest

from core.download_task import DownloadStatus, DownloadTask
from services.partial_download_cleanup import (
    cleanup_partial_download_files,
    find_partial_download_files,
)


ROOT = Path(__file__).resolve().parents[1]


class PartialDownloadCleanupTests(unittest.TestCase):
    def _task(self, directory: str) -> DownloadTask:
        return DownloadTask(
            task_id="partial-test",
            title="sample",
            url="https://example.invalid/video",
            status=DownloadStatus.STOPPED,
            save_path=directory,
            output_stem="sample video",
        )

    def test_finder_only_returns_matching_incomplete_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "sample video.f299.mp4.part",
                "sample video.f140.m4a.part",
                "sample video.mp4.ytdl",
                "sample video.mp4",
                "sample video.ko.srt",
                "other video.f299.mp4.part",
            ):
                (root / name).write_bytes(b"x")

            names = {path.name for path in find_partial_download_files(self._task(directory))}

            self.assertEqual(
                names,
                {
                    "sample video.f299.mp4.part",
                    "sample video.f140.m4a.part",
                    "sample video.mp4.ytdl",
                },
            )

    def test_cleanup_deletes_partials_but_keeps_completed_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            partial = root / "sample video.f299.mp4.part"
            complete = root / "sample video.mp4"
            subtitle = root / "sample video.ko.srt"
            partial.write_bytes(b"partial")
            complete.write_bytes(b"complete")
            subtitle.write_text("subtitle", encoding="utf-8")

            result = cleanup_partial_download_files(self._task(directory))

            self.assertEqual(result.deleted_count, 1)
            self.assertFalse(partial.exists())
            self.assertTrue(complete.exists())
            self.assertTrue(subtitle.exists())

    def test_empty_output_stem_never_scans_for_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            partial = root / "anything.mp4.part"
            partial.write_bytes(b"partial")
            task = self._task(directory)
            task.output_stem = ""

            self.assertEqual(find_partial_download_files(task), ())
            self.assertTrue(partial.exists())


class ChapterOriginalDeletionContractTests(unittest.TestCase):
    def test_card_meta_shows_original_delete_only_with_chapter_split(self) -> None:
        enabled = DownloadTask(
            task_id="one",
            title="sample",
            url="https://example.invalid/one",
            status=DownloadStatus.QUEUED,
            split_chapters=True,
            delete_original_after_split=True,
        )
        unsafe = DownloadTask(
            task_id="two",
            title="sample",
            url="https://example.invalid/two",
            status=DownloadStatus.QUEUED,
            split_chapters=False,
            delete_original_after_split=True,
        )

        self.assertIn("원본 삭제", enabled.meta_text)
        self.assertNotIn("원본 삭제", unsafe.meta_text)

    def test_queue_restore_persists_original_delete_intent(self) -> None:
        source = (ROOT / "app" / "queue_store.py").read_text(encoding="utf-8")
        self.assertIn('raw.get("delete_original_after_split", False)', source)

    def test_split_service_deletes_original_only_after_split_completes(self) -> None:
        path = ROOT / "services" / "templated_download_service.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))

        split_call = source.index("self._chapter_split_service.split")
        delete_call = source.index("output_path.unlink(missing_ok=True)")
        self.assertLess(split_call, delete_call)
        self.assertIn("download.chapter_original_deleted", source)
        self.assertIn("download.chapter_original_delete_failed", source)

    def test_preview_exposes_original_delete_as_dependent_option(self) -> None:
        path = ROOT / "ui" / "widgets" / "chapter_preview_panel.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))

        self.assertIn('QCheckBox(\n            "분할 성공 후 원본 삭제"', source)
        self.assertIn('options["delete_original_after_split"]', source)
        self.assertIn("self.delete_original_after_split_checkbox.setEnabled", source)

    def test_download_page_defers_active_partial_cleanup_until_worker_finishes(self) -> None:
        path = ROOT / "ui" / "pages" / "download_page_chapters.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))

        self.assertIn("_pending_partial_cleanup", source)
        self.assertIn("미완성 다운로드 파일 정리", source)
        self.assertIn("QTimer.singleShot", source)
        self.assertIn("cleanup_partial_download_files", source)


if __name__ == "__main__":
    unittest.main()
