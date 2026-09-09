from __future__ import annotations

from pathlib import Path
import unittest

from app.download_preferences import DownloadPreferences
from app.preset_store import DownloadPreset
from core.local_media_info import MediaChapter, MediaFileInfo
from services.chapter_split_service import (
    build_chapter_split_command,
    chapter_output_filename,
    sanitize_chapter_title,
    valid_chapters,
)
from services.filename_metadata_ytdlp_service import _source_chapters


ROOT = Path(__file__).resolve().parents[1]


class ChapterSplitServiceTests(unittest.TestCase):
    def test_valid_chapters_filters_zero_length_entries(self) -> None:
        media_info = MediaFileInfo(
            path="sample.mkv",
            file_name="sample.mkv",
            size_bytes=1,
            chapters=(
                MediaChapter(0, 0.0, 10.0, "Intro"),
                MediaChapter(1, 10.0, 10.0, "Empty"),
                MediaChapter(2, 10.0, 25.5, "Main"),
            ),
        )

        chapters = valid_chapters(media_info)

        self.assertEqual([item.title for item in chapters], ["Intro", "Main"])

    def test_chapter_output_filename_uses_number_and_safe_title(self) -> None:
        chapter = MediaChapter(0, 0.0, 10.0, 'Intro: A/B?*')

        filename = chapter_output_filename(chapter, 1, 12, ".mkv")

        self.assertEqual(filename, "01 - Intro_ A_B__.mkv")

    def test_chapter_output_filename_uses_fallback_title(self) -> None:
        chapter = MediaChapter(0, 0.0, 10.0, "")

        filename = chapter_output_filename(chapter, 3, 12, "mp4")

        self.assertEqual(filename, "03 - 챕터 03.mp4")

    def test_sanitize_chapter_title_handles_windows_reserved_name(self) -> None:
        self.assertEqual(sanitize_chapter_title("CON"), "_CON")

    def test_build_command_keeps_streams_and_removes_original_chapter_table(self) -> None:
        chapter = MediaChapter(0, 12.5, 30.0, "Part")
        command = build_chapter_split_command(
            "ffmpeg.exe",
            "input.mkv",
            "output.mkv",
            chapter,
        )

        joined = " ".join(command)
        self.assertIn("-ss 12.500000", joined)
        self.assertIn("-t 17.500000", joined)
        self.assertIn("-map 0", joined)
        self.assertIn("-map_metadata 0", joined)
        self.assertIn("-map_chapters -1", joined)
        self.assertIn("-c copy", joined)
        self.assertIn("-avoid_negative_ts make_zero", joined)

    def test_source_chapters_fills_missing_end_from_next_start_and_duration(self) -> None:
        chapters = _source_chapters(
            {
                "duration": 30,
                "chapters": [
                    {"start_time": 0, "title": "Intro"},
                    {"start_time": 10, "title": "Main"},
                    {"start_time": 25, "title": "End"},
                ],
            }
        )

        self.assertEqual(
            chapters,
            (
                (0.0, 10.0, "Intro"),
                (10.0, 25.0, "Main"),
                (25.0, 30.0, "End"),
            ),
        )


class ChapterSplitPresetTests(unittest.TestCase):
    def test_audio_only_normalization_disables_chapter_split(self) -> None:
        preferences = DownloadPreferences(
            split_chapters=True,
            audio_only=True,
        ).normalized()

        self.assertFalse(preferences.split_chapters)

    def test_preset_round_trip_preserves_chapter_split_option(self) -> None:
        preset = DownloadPreset.from_preferences(
            "챕터 테스트",
            DownloadPreferences(split_chapters=True),
            preset_id="chapter-test",
        )
        payload = preset.to_dict()
        restored = DownloadPreset.from_dict(payload)

        self.assertTrue(payload["split_chapters"])
        self.assertTrue(restored.split_chapters)
        self.assertTrue(restored.to_preferences().split_chapters)


class ChapterSplitIntegrationContractTests(unittest.TestCase):
    def test_media_tools_does_not_expose_standalone_chapter_splitter(self) -> None:
        source = (ROOT / "ui" / "pages" / "media_tools_page.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("ChapterSplitPage", source)
        self.assertNotIn('"챕터 분할"', source)
        self.assertFalse((ROOT / "ui" / "tools" / "chapter_split_page.py").exists())
        self.assertFalse((ROOT / "workers" / "chapter_split_worker.py").exists())

    def test_settings_exposes_split_as_preset_option(self) -> None:
        source = (ROOT / "ui" / "pages" / "unified_settings_page.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("영상의 챕터를 각각 별도 파일로 저장", source)
        self.assertIn("preferences.split_chapters", source)
        self.assertIn("split_chapters=", source)

    def test_download_uses_internal_engine_after_normal_download(self) -> None:
        source = (ROOT / "services" / "templated_download_service.py").read_text(
            encoding="utf-8"
        )

        normal_download = source.index("result = super().download")
        split_call = source.index("self._chapter_split_service.split")
        self.assertLess(normal_download, split_call)
        self.assertIn("ChapterSplitService", source)
        self.assertIn('"download.chapter_split_completed"', source)
        self.assertNotIn('"--split-chapters"', source)

    def test_queue_store_persists_chapter_split_intent(self) -> None:
        source = (ROOT / "app" / "queue_store.py").read_text(encoding="utf-8")

        self.assertIn('split_chapters=bool(raw.get("split_chapters", False))', source)


if __name__ == "__main__":
    unittest.main()