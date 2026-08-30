from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app.tool_manager as tool_manager


class ToolManagerIntegrityTests(unittest.TestCase):
    def test_version_for_rejects_nonzero_return_code(self) -> None:
        result = SimpleNamespace(returncode=1, stdout="2026.08.30\n", stderr="")
        with patch.object(tool_manager.subprocess, "run", return_value=result):
            self.assertEqual(
                tool_manager._version_for(Path("yt-dlp.exe"), ("--version",)),
                "실행 오류",
            )

    def test_version_for_accepts_successful_version_output(self) -> None:
        result = SimpleNamespace(returncode=0, stdout="2026.08.30.120000\n", stderr="")
        with patch.object(tool_manager.subprocess, "run", return_value=result):
            self.assertEqual(
                tool_manager._version_for(Path("yt-dlp.exe"), ("--version",)),
                "2026.08.30.120000",
            )

    def test_extract_named_sha256_finds_requested_asset(self) -> None:
        digest = "a" * 64
        text = f"{digest}  yt-dlp.exe\n{'b' * 64}  yt-dlp"
        self.assertEqual(
            tool_manager._extract_named_sha256(text, "yt-dlp.exe"),
            digest,
        )

    def test_extract_named_sha256_rejects_html_or_missing_asset(self) -> None:
        self.assertIsNone(
            tool_manager._extract_named_sha256(
                "<html><body>temporary error</body></html>",
                "yt-dlp.exe",
            )
        )

    def test_managed_tree_matches_detects_changed_runtime_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            installed = root / "installed"
            (source / "nodriver").mkdir(parents=True)
            (installed / "nodriver").mkdir(parents=True)
            (source / "nodriver" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
            (installed / "nodriver" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")

            self.assertTrue(tool_manager._managed_tree_matches(source, installed))

            (installed / "nodriver" / "__init__.py").write_text("VALUE = 2\n", encoding="utf-8")
            self.assertFalse(tool_manager._managed_tree_matches(source, installed))

    def test_managed_tree_ignores_generated_python_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            installed = root / "installed"
            source.mkdir()
            installed.mkdir()
            (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            (installed / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            cache = source / "__pycache__"
            cache.mkdir()
            (cache / "module.pyc").write_bytes(b"generated")

            self.assertTrue(tool_manager._managed_tree_matches(source, installed))

    def test_ffmpeg_pair_mismatch_marks_both_unavailable(self) -> None:
        statuses = [
            tool_manager.ToolStatus("ffmpeg", "FFmpeg", "ffmpeg.exe", True, "8.0.1", "ffmpeg.exe"),
            tool_manager.ToolStatus("ffprobe", "FFprobe", "ffprobe.exe", True, "7.1.1", "ffprobe.exe"),
        ]
        checked = tool_manager._ffmpeg_pair_consistent(statuses)
        self.assertFalse(checked[0].available)
        self.assertFalse(checked[1].available)
        self.assertIn("불일치", checked[0].version)
        self.assertIn("불일치", checked[1].version)

    def test_latest_ytdlp_identity_uses_github_asset_digest_when_available(self) -> None:
        digest = "c" * 64
        payload = {
            "tag_name": "2026.08.30.120000",
            "assets": [
                {
                    "name": "yt-dlp.exe",
                    "digest": f"sha256:{digest}",
                    "browser_download_url": "https://example.invalid/yt-dlp.exe",
                }
            ],
        }
        with patch.object(tool_manager, "_fetch_small_text", return_value=json.dumps(payload)):
            tag, actual = tool_manager._latest_ytdlp_nightly_identity()
        self.assertEqual(tag, "2026.08.30.120000")
        self.assertEqual(actual, digest)

    def test_latest_ytdlp_identity_falls_back_to_checksum_asset(self) -> None:
        digest = "d" * 64
        payload = {
            "tag_name": "2026.08.30.120000",
            "assets": [
                {
                    "name": "yt-dlp.exe",
                    "digest": None,
                    "browser_download_url": "https://example.invalid/yt-dlp.exe",
                },
                {
                    "name": "SHA2-256SUMS",
                    "browser_download_url": "https://example.invalid/SHA2-256SUMS",
                },
            ],
        }
        responses = [json.dumps(payload), f"{digest}  yt-dlp.exe\n"]
        with patch.object(tool_manager, "_fetch_small_text", side_effect=responses):
            tag, actual = tool_manager._latest_ytdlp_nightly_identity()
        self.assertEqual(tag, "2026.08.30.120000")
        self.assertEqual(actual, digest)

    def test_update_ytdlp_refuses_to_run_without_official_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "yt-dlp.exe"
            path.write_bytes(b"existing")
            with (
                patch.object(tool_manager, "find_executable", return_value=path),
                patch.object(
                    tool_manager,
                    "_latest_ytdlp_nightly_identity",
                    side_effect=ValueError("checksum unavailable"),
                ),
                patch.object(tool_manager.subprocess, "run") as run_mock,
            ):
                success, _message = tool_manager.update_ytdlp()
            self.assertFalse(success)
            run_mock.assert_not_called()

    def test_update_ytdlp_skips_updater_when_latest_hash_already_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "yt-dlp.exe"
            path.write_bytes(b"latest-binary")
            digest = hashlib.sha256(b"latest-binary").hexdigest()
            with (
                patch.object(tool_manager, "find_executable", return_value=path),
                patch.object(
                    tool_manager,
                    "_latest_ytdlp_nightly_identity",
                    return_value=("2026.08.30.120000", digest),
                ),
                patch.object(tool_manager, "_version_for", return_value="2026.08.30.120000"),
                patch.object(tool_manager.subprocess, "run") as run_mock,
            ):
                success, message = tool_manager.update_ytdlp()
            self.assertTrue(success)
            self.assertIn("SHA-256", message)
            run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
