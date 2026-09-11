from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import app.filename_metadata_store as metadata_store
from services.filename_metadata_ytdlp_service import YtDlpService


class FilenameMetadataStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self._original_path = metadata_store._METADATA_PATH
        metadata_store._METADATA_PATH = (
            Path(self._temporary_directory.name) / "filename_metadata.json"
        )
        metadata_store._CACHE = None

    def tearDown(self) -> None:
        metadata_store._METADATA_PATH = self._original_path
        metadata_store._CACHE = None

    def test_metadata_round_trip_does_not_store_raw_identity(self) -> None:
        identity = "youtube:secret-video-id"
        metadata_store.remember_filename_metadata(
            identity,
            upload_date="2026-09-09",
            resolutions=("1080p", "2160p", "1080p", "bad"),
            chapters=(
                (0, 10, "Intro"),
                (10, 25.5, "Main"),
            ),
        )

        loaded = metadata_store.load_filename_metadata(identity)
        self.assertEqual(loaded.upload_date, "20260909")
        self.assertEqual(loaded.resolutions, ("2160p", "1080p"))
        self.assertEqual(
            loaded.chapters,
            ((0.0, 10.0, "Intro"), (10.0, 25.5, "Main")),
        )

        raw = metadata_store._METADATA_PATH.read_text(encoding="utf-8")
        self.assertNotIn(identity, raw)
        self.assertNotIn("secret-video-id", raw)

    def test_corrupt_cache_is_treated_as_empty(self) -> None:
        metadata_store._METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        metadata_store._METADATA_PATH.write_text("{broken", encoding="utf-8")
        metadata_store._CACHE = None

        loaded = metadata_store.load_filename_metadata("youtube:abc")
        self.assertEqual(loaded.upload_date, "")
        self.assertEqual(loaded.resolutions, ())
        self.assertEqual(loaded.chapters, ())

    def test_initial_analysis_records_upload_date_resolutions_and_chapters(self) -> None:
        url = "https://www.youtube.com/watch?v=abc123"
        raw_info = {
            "id": "abc123",
            "title": "테스트 영상",
            "webpage_url": url,
            "extractor_key": "Youtube",
            "channel": "테스트 채널",
            "duration": 123,
            "upload_date": "20260909",
            "formats": [
                {"height": 1080},
                {"height": 2160},
                {"height": 720},
            ],
            "chapters": [
                {"start_time": 0, "end_time": 10, "title": "Intro"},
                {"start_time": 10, "end_time": 123, "title": "Main"},
            ],
        }

        with patch(
            "services.filename_metadata_ytdlp_service.remember_filename_metadata"
        ) as remember:
            media_info = YtDlpService._to_media_info(url, raw_info)

        self.assertEqual(media_info.resolutions, ("2160p", "1080p", "720p"))
        remember.assert_called_once_with(
            media_info.identity_key,
            upload_date="20260909",
            resolutions=("2160p", "1080p", "720p"),
            chapters=((0.0, 10.0, "Intro"), (10.0, 123.0, "Main")),
        )


if __name__ == "__main__":
    unittest.main()