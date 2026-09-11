from __future__ import annotations

from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

from app.download_preferences import DownloadPreferences
from app.filename_metadata_store import FilenameMetadata
from app.preset_store import DownloadPreset
from app.queue_store import _task_from_dict
from core.download_task import DownloadStatus, DownloadTask
from services.templated_download_service import YtDlpDownloadService


class SponsorBlockChapterTests(unittest.TestCase):
    @staticmethod
    def _service() -> YtDlpDownloadService:
        service = object.__new__(YtDlpDownloadService)
        service.executable = Path("yt-dlp.exe")
        service.ffmpeg = Path("ffmpeg.exe")
        service.ffprobe = Path("ffprobe.exe")
        return service

    @staticmethod
    def _task(**changes: object) -> DownloadTask:
        values: dict[str, object] = {
            "task_id": "sponsor-test",
            "title": "SponsorBlock test",
            "url": "https://www.youtube.com/watch?v=abc123",
            "status": DownloadStatus.QUEUED,
            "video_id": "abc123",
            "extractor": "Youtube",
            "save_path": "C:/Temp",
            "sponsorblock_chapters": True,
        }
        values.update(changes)
        return DownloadTask(**values)  # type: ignore[arg-type]

    def test_audio_only_normalization_disables_sponsorblock_chapters(self) -> None:
        preferences = DownloadPreferences(
            sponsorblock_chapters=True,
            audio_only=True,
        ).normalized()
        self.assertFalse(preferences.sponsorblock_chapters)

    def test_preset_round_trip_preserves_setting_and_old_data_defaults_off(self) -> None:
        enabled = DownloadPreset.from_preferences(
            "SponsorBlock",
            DownloadPreferences(sponsorblock_chapters=True),
            preset_id="preset-1",
        )
        self.assertTrue(enabled.sponsorblock_chapters)
        self.assertTrue(enabled.to_preferences().sponsorblock_chapters)
        self.assertTrue(enabled.to_dict()["sponsorblock_chapters"])

        legacy = DownloadPreset.from_dict(
            {
                "id": "legacy-preset",
                "name": "Legacy",
            }
        )
        self.assertFalse(legacy.sponsorblock_chapters)

    def test_queue_restore_preserves_sponsorblock_intent(self) -> None:
        task = _task_from_dict(
            {
                "task_id": "queue-1",
                "url": "https://www.youtube.com/watch?v=abc123",
                "status": "queued",
                "sponsorblock_chapters": True,
            }
        )
        self.assertIsNotNone(task)
        assert task is not None
        self.assertTrue(task.sponsorblock_chapters)

    def test_youtube_command_marks_all_segments_as_chapters_without_removal(self) -> None:
        service = self._service()
        task = self._task(preserve_metadata=False)

        with patch(
            "services.download_service.YtDlpService.extend_runtime_and_auth_arguments"
        ):
            command = service._build_command(
                task,
                Path("C:/Temp"),
                "video",
                overwrite_existing=False,
            )

        self.assertEqual(command[-1], task.url)
        self.assertIn("--sponsorblock-mark", command)
        mark_index = command.index("--sponsorblock-mark")
        self.assertEqual(command[mark_index + 1], "all")
        self.assertIn("--embed-chapters", command)
        self.assertNotIn("--sponsorblock-remove", command)

    def test_sponsorblock_arguments_are_not_added_outside_youtube(self) -> None:
        service = self._service()
        task = self._task(
            url="https://vimeo.com/12345",
            extractor="Vimeo",
        )

        with patch(
            "services.download_service.YtDlpService.extend_runtime_and_auth_arguments"
        ):
            command = service._build_command(
                task,
                Path("C:/Temp"),
                "video",
                overwrite_existing=False,
            )

        self.assertNotIn("--sponsorblock-mark", command)
        self.assertNotIn("--sponsorblock-remove", command)

    def test_sponsorblock_arguments_are_not_added_to_audio_only(self) -> None:
        service = self._service()
        task = self._task(audio_only=True)

        with patch(
            "services.download_service.YtDlpService.extend_runtime_and_auth_arguments"
        ):
            command = service._build_command(
                task,
                Path("C:/Temp"),
                "audio",
                overwrite_existing=False,
            )

        self.assertNotIn("--sponsorblock-mark", command)

    def test_chapter_split_never_uses_synthetic_sponsorblock_chapters_as_source(self) -> None:
        service = self._service()
        service._chapter_probe_service = Mock()
        task = self._task(split_chapters=True)

        with patch(
            "services.templated_download_service.load_filename_metadata",
            return_value=FilenameMetadata(),
        ):
            media_info = service._media_info_for_chapter_split(
                task,
                Path("C:/Temp/video.mp4"),
                threading.Event(),
            )

        self.assertIsNotNone(media_info)
        assert media_info is not None
        self.assertEqual(media_info.chapters, ())
        service._chapter_probe_service.probe.assert_not_called()

    def test_runtime_ui_wiring_exposes_marking_not_removal(self) -> None:
        root = Path(__file__).resolve().parents[1]
        settings_source = (
            root / "ui" / "pages" / "chapter_settings_page.py"
        ).read_text(encoding="utf-8")
        preview_source = (
            root / "ui" / "widgets" / "chapter_preview_panel.py"
        ).read_text(encoding="utf-8")
        page_source = (
            root / "ui" / "pages" / "download_page_chapters.py"
        ).read_text(encoding="utf-8")

        self.assertIn("SponsorBlock 구간을 챕터로 표시", settings_source)
        self.assertIn("sponsorblock_chapters", preview_source)
        self.assertIn("desired_sponsorblock", page_source)
        self.assertNotIn("sponsorblock-remove", settings_source.casefold())
        self.assertNotIn("sponsorblock-remove", preview_source.casefold())


if __name__ == "__main__":
    unittest.main()