from __future__ import annotations

import ast
from pathlib import Path
import unittest

from core.local_media_info import MediaChapter, MediaFileInfo
from services.chapter_split_service import (
    build_chapter_split_command,
    chapter_output_filename,
    sanitize_chapter_title,
    valid_chapters,
)


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


class ChapterSplitUiContractTests(unittest.TestCase):
    def test_media_tools_registers_chapter_split_page(self) -> None:
        path = ROOT / "ui" / "pages" / "media_tools_page.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        self.assertIn(
            "from ui.tools.chapter_split_page import ChapterSplitPage",
            source,
        )
        self.assertIn('"챕터 분할"', source)
        self.assertIn("self.chapter_split_page = ChapterSplitPage()", source)
        self.assertIn("self.tool_stack.addWidget(self.chapter_split_page)", source)
        self.assertIn("self.chapter_split_page.has_active_operation", source)
        self.assertIn("self.chapter_split_page.shutdown()", source)

        media_tools_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "MediaToolsPage"
        )
        self.assertIsNotNone(media_tools_class)


if __name__ == "__main__":
    unittest.main()
