from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.url_list_io import (
    extract_urls,
    format_source_url_list,
    is_probable_collection_url,
    merge_urls,
    read_text_file,
)


class UrlListIoTests(unittest.TestCase):
    def test_extract_urls_keeps_order_removes_case_insensitive_duplicates(self) -> None:
        text = (
            "첫째 https://Example.com/video), "
            "중복 https://example.com/video "
            "둘째 https://example.org/watch?v=2!"
        )
        self.assertEqual(
            extract_urls(text),
            ["https://Example.com/video", "https://example.org/watch?v=2"],
        )

    def test_youtube_watch_url_is_single_video(self) -> None:
        self.assertFalse(
            is_probable_collection_url("https://www.youtube.com/watch?v=abc123")
        )

    def test_youtube_watch_with_list_is_collection(self) -> None:
        self.assertTrue(
            is_probable_collection_url(
                "https://www.youtube.com/watch?v=abc123&list=PL123"
            )
        )

    def test_youtube_shorts_url_is_single_video(self) -> None:
        self.assertFalse(
            is_probable_collection_url("https://www.youtube.com/shorts/abc123")
        )

    def test_youtube_channel_url_is_collection(self) -> None:
        self.assertTrue(
            is_probable_collection_url("https://www.youtube.com/@example/videos")
        )

    def test_generic_playlist_path_is_collection(self) -> None:
        self.assertTrue(
            is_probable_collection_url("https://example.com/playlists/favorites")
        )

    def test_merge_urls_preserves_order_and_counts_duplicates(self) -> None:
        merged, duplicate_count = merge_urls(
            ["https://a.example/1", "https://b.example/2"],
            [" https://A.example/1 ", "https://c.example/3"],
        )
        self.assertEqual(
            merged,
            ["https://a.example/1", "https://b.example/2", "https://c.example/3"],
        )
        self.assertEqual(duplicate_count, 1)

    def test_format_source_url_list_removes_duplicates(self) -> None:
        text = format_source_url_list(
            ["https://a.example/1", "https://A.example/1", "https://b.example/2"]
        )
        self.assertIn("총 2개", text)
        self.assertEqual(text.count("https://a.example/1"), 1)
        self.assertIn("https://b.example/2", text)

    def test_read_text_file_supports_cp949(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "urls.txt"
            expected = "한글 테스트 https://example.com"
            path.write_bytes(expected.encode("cp949"))
            self.assertEqual(read_text_file(path), expected)


if __name__ == "__main__":
    unittest.main()
