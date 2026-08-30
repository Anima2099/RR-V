from __future__ import annotations

import unittest

from app.component_updates import (
    _local_signature,
    _normalize_ytdlp_version,
    _release_tuple,
    normalize_ffmpeg_release_version,
)


class ComponentUpdateTests(unittest.TestCase):
    def test_normalize_ytdlp_version_extracts_date_version(self) -> None:
        self.assertEqual(
            _normalize_ytdlp_version("yt-dlp nightly@2026.08.30.123456"),
            "2026.08.30.123456",
        )

    def test_normalize_ffmpeg_release_version_extracts_version(self) -> None:
        self.assertEqual(
            normalize_ffmpeg_release_version("ffmpeg version 8.0.1-full_build"),
            "8.0.1",
        )

    def test_release_tuple_parses_two_part_version(self) -> None:
        self.assertEqual(_release_tuple("8.0"), (8, 0))

    def test_release_tuple_rejects_non_release_text(self) -> None:
        self.assertIsNone(_release_tuple("git-master-2026-08-30"))

    def test_local_signature_tracks_managed_components(self) -> None:
        installed = {
            "ytdlp": "2026.08.30",
            "ffmpeg": "8.0",
            "ffprobe": "8.0",
            "deno": "2.5.0",
        }
        self.assertEqual(
            _local_signature(installed),
            "2026.08.30|8.0|8.0",
        )


if __name__ == "__main__":
    unittest.main()
