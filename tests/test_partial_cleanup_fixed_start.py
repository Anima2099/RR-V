from __future__ import annotations

import ast
import os
from pathlib import Path
import tempfile
import unittest

from core.download_task import DownloadStatus, DownloadTask
from services.partial_download_cleanup import (
    cleanup_partial_download_files,
    partial_cleanup_scan_diagnostics,
)


ROOT = Path(__file__).resolve().parents[1]


class PartialCleanupFixedStartTests(unittest.TestCase):
    def test_webp_uses_fixed_download_start_not_moving_log_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            started_at = 1_700_000_000.0

            task = DownloadTask(
                task_id="fixed-start",
                title="sample",
                url="https://example.invalid/video",
                status=DownloadStatus.STOPPED,
                save_path=directory,
                output_stem="sample video",
                embed_thumbnail=True,
                downloaded_bytes=1024,
                download_started_at=started_at,
            )

            raw_log = root / "task.log"
            raw_log.write_text("RR-V yt-dlp task log", encoding="utf-8")
            os.utime(raw_log, (started_at + 30.0, started_at + 30.0))
            task.raw_log_path = str(raw_log)

            webp = root / "sample video.webp"
            webp.write_bytes(b"thumbnail")
            os.utime(webp, (started_at + 1.0, started_at + 1.0))

            result = cleanup_partial_download_files(task)

            self.assertIn(str(webp), result.deleted)
            self.assertFalse(webp.exists())

    def test_trimmed_webp_matches_same_download_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            started_at = 1_700_000_000.0
            full_stem = (
                "STALKER 2 GARBAGE All Artifacts Locations _ Natural Locations + Loot + "
                "Mission Artifacts #stalker2 Sagar Smith Gaming iwysD9zFvv8 YouTube 1080p "
                "202508"
            )
            trimmed_stem = (
                "STALKER 2 GARBAGE All Artifacts Locations _ Natural Locations + Loot + "
                "Mission Artifacts #stalker2 Sagar Smith Gaming iwysD9zFvv8 YouTube 1080p 20"
            )
            task = DownloadTask(
                task_id="trimmed-thumb",
                title="sample",
                url="https://example.invalid/video",
                status=DownloadStatus.STOPPED,
                save_path=directory,
                output_stem=full_stem,
                embed_thumbnail=True,
                downloaded_bytes=1024,
                download_started_at=started_at,
            )

            webp = root / f"{trimmed_stem}.webp"
            unrelated = root / "another recent thumbnail.webp"
            webp.write_bytes(b"thumbnail")
            unrelated.write_bytes(b"other")
            os.utime(webp, (started_at + 1.0, started_at + 1.0))
            os.utime(unrelated, (started_at + 1.0, started_at + 1.0))

            result = cleanup_partial_download_files(task)

            self.assertIn(str(webp), result.deleted)
            self.assertFalse(webp.exists())
            self.assertTrue(unrelated.exists())

    def test_trimmed_webp_diagnostics_report_session_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            started_at = 1_700_000_000.0
            task = DownloadTask(
                task_id="trimmed-thumb-diagnostic",
                title="sample",
                url="https://example.invalid/video",
                status=DownloadStatus.STOPPED,
                save_path=directory,
                output_stem=(
                    "STALKER 2 GARBAGE All Artifacts Locations Natural Locations Mission "
                    "Artifacts Sagar Smith Gaming YouTube 1080p 202508"
                ),
                embed_thumbnail=True,
                download_started_at=started_at,
            )
            webp = root / (
                "STALKER 2 GARBAGE All Artifacts Locations Natural Locations Mission "
                "Artifacts Sagar Smith Gaming YouTube 1080p 20.webp"
            )
            webp.write_bytes(b"thumbnail")
            os.utime(webp, (started_at + 1.0, started_at + 1.0))

            diagnostics = partial_cleanup_scan_diagnostics(task)
            joined = "\n".join(diagnostics)

            self.assertIn(webp.name, joined)
            self.assertIn("kind=thumb", joined)
            self.assertIn("candidate=1", joined)
            self.assertIn("eligible=1", joined)
            self.assertIn("session=1", joined)

    def test_download_controller_records_start_time_before_worker_runs(self) -> None:
        path = ROOT / "controllers" / "download_controller.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))

        stamp = source.index("task.download_started_at = time()")
        worker = source.index("worker = DownloadWorker(task)", stamp)
        start = source.index("worker.start()", worker)
        self.assertLess(stamp, worker)
        self.assertLess(worker, start)

    def test_queue_restore_and_cleanup_diagnostics_keep_start_time(self) -> None:
        queue_path = ROOT / "app" / "queue_store.py"
        queue_source = queue_path.read_text(encoding="utf-8")
        ast.parse(queue_source, filename=str(queue_path))
        self.assertIn('raw.get("download_started_at", 0.0)', queue_source)

        page_path = ROOT / "ui" / "pages" / "download_page_chapters.py"
        page_source = page_path.read_text(encoding="utf-8")
        ast.parse(page_source, filename=str(page_path))
        self.assertIn('"download.partial_cleanup_scan"', page_source)
        self.assertIn("partial_cleanup_scan_diagnostics", page_source)


if __name__ == "__main__":
    unittest.main()
