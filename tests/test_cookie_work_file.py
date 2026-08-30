from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import services.cookie_work_file as cookie_work_file


class CookieWorkFileTests(unittest.TestCase):
    def tearDown(self) -> None:
        work_dir = cookie_work_file._WORK_DIR
        if work_dir is not None:
            cookie_work_file._cleanup_directory(work_dir)
        cookie_work_file._WORK_DIR = None

    def test_prepare_cookie_work_copy_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "youtube-cookies.txt"
            original = "# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tFALSE\t0\ttest\tvalue\n"
            source.write_text(original, encoding="utf-8")

            with patch.object(cookie_work_file.tempfile, "gettempdir", return_value=temp_dir):
                copied = cookie_work_file.prepare_cookie_work_copy(source)

            self.assertNotEqual(copied, source)
            self.assertTrue(copied.is_file())
            self.assertEqual(copied.read_text(encoding="utf-8"), original)
            self.assertEqual(source.read_text(encoding="utf-8"), original)

    def test_prepare_cookie_work_copy_rejects_missing_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.txt"
            with self.assertRaises(FileNotFoundError):
                cookie_work_file.prepare_cookie_work_copy(missing)

    def test_prepare_work_directory_removes_stale_rrv_cookie_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            stale = root / "rrv-yt-dlp-cookie-999999-old"
            stale.mkdir()
            (stale / "cookie-old.txt").write_text("stale", encoding="utf-8")

            with patch.object(cookie_work_file.tempfile, "gettempdir", return_value=temp_dir):
                work_dir = cookie_work_file._prepare_work_directory()

            self.assertFalse(stale.exists())
            self.assertTrue(work_dir.is_dir())
            self.assertTrue(work_dir.name.startswith("rrv-yt-dlp-cookie-"))


if __name__ == "__main__":
    unittest.main()
