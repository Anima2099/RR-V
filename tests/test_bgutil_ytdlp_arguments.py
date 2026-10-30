from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from services.bgutil_http_service import BgUtilConnection, ENV_HOME
from services import ytdlp_service


class BgutilYtdlpArgumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake_deno = Path("C:/RR-V/tools/deno.exe")
        self.fake_external = BgUtilConnection(
            Path("C:/LocalAppData/RR-V/bgutil-stage03-external/plugins"),
            "http://127.0.0.1:12345",
        )
        self.cookies = patch.object(
            ytdlp_service, "RRV_YOUTUBE_AUTH_COOKIE_PATH",
            Path("__rrv_stage03_no_saved_cookie__.txt"),
        )
        self.cookies.start()
        self.addCleanup(self.cookies.stop)
        self.manual_cookies = patch.object(
            ytdlp_service.YtDlpService, "_find_cookie_file", return_value=None
        )
        self.manual_cookies.start()
        self.addCleanup(self.manual_cookies.stop)

    def test_existing_wpc_arguments_are_unchanged_when_opt_in_disabled(self) -> None:
        cmd = ["yt-dlp.exe"]
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(ytdlp_service, "find_executable", return_value=self.fake_deno),
            patch.object(ytdlp_service, "wpc_provider_runtime_ready", return_value=True),
        ):
            ytdlp_service.YtDlpService.extend_runtime_and_auth_arguments(
                cmd, "https://www.youtube.com/watch?v=example"
            )
        self.assertEqual(cmd, [
            "yt-dlp.exe", "--js-runtimes", f"deno:{self.fake_deno}",
            "--no-plugin-dirs", "--plugin-dirs", str(ytdlp_service.RRV_WPC_PROVIDER_DIR),
        ])

    def test_opted_in_http_bgutil_is_registered_before_wpc(self) -> None:
        cmd = ["yt-dlp.exe"]
        with (
            patch.dict(os.environ, {ENV_HOME: "C:/external"}),
            patch.object(ytdlp_service, "find_executable", return_value=self.fake_deno),
            patch.object(ytdlp_service, "wpc_provider_runtime_ready", return_value=True),
            patch("services.bgutil_http_service.connect_bgutil_http", return_value=self.fake_external) as connect,
        ):
            ytdlp_service.YtDlpService.extend_runtime_and_auth_arguments(
                cmd, "https://www.youtube.com/watch?v=example"
            )
        self.assertEqual(cmd.count("--no-plugin-dirs"), 1)
        dirs = [cmd[i+1] for i, arg in enumerate(cmd[:-1]) if arg == "--plugin-dirs"]
        self.assertEqual(dirs, [str(self.fake_external.plugin_dir), str(ytdlp_service.RRV_WPC_PROVIDER_DIR)])
        self.assertIn("youtubepot-bgutilhttp:base_url=http://127.0.0.1:12345", cmd)
        connect.assert_called_once_with(self.fake_deno)

    def test_server_unavailable_uses_only_wpc_without_blocking(self) -> None:
        cmd = ["yt-dlp.exe"]
        with (
            patch.dict(os.environ, {ENV_HOME: "C:/external"}),
            patch.object(ytdlp_service, "find_executable", return_value=self.fake_deno),
            patch.object(ytdlp_service, "wpc_provider_runtime_ready", return_value=True),
            patch("services.bgutil_http_service.connect_bgutil_http", return_value=None),
        ):
            ytdlp_service.YtDlpService.extend_runtime_and_auth_arguments(
                cmd, "https://www.youtube.com/watch?v=example"
            )
        self.assertEqual(cmd.count("--plugin-dirs"), 1)
        self.assertIn(str(ytdlp_service.RRV_WPC_PROVIDER_DIR), cmd)
        self.assertNotIn("--extractor-args", cmd)

    def test_external_provider_can_work_without_wpc(self) -> None:
        cmd = ["yt-dlp.exe"]
        with (
            patch.dict(os.environ, {ENV_HOME: "C:/external"}),
            patch.object(ytdlp_service, "find_executable", return_value=self.fake_deno),
            patch.object(ytdlp_service, "wpc_provider_runtime_ready", return_value=False),
            patch("services.bgutil_http_service.connect_bgutil_http", return_value=self.fake_external),
        ):
            ytdlp_service.YtDlpService.extend_runtime_and_auth_arguments(
                cmd, "https://www.youtube.com/watch?v=example"
            )
        self.assertEqual(cmd.count("--plugin-dirs"), 1)
        self.assertIn(str(self.fake_external.plugin_dir), cmd)

    def test_non_youtube_does_not_start_external_provider(self) -> None:
        cmd = ["yt-dlp.exe"]
        with (
            patch.dict(os.environ, {ENV_HOME: "C:/external"}),
            patch.object(ytdlp_service, "find_executable") as find_tool,
            patch("services.bgutil_http_service.connect_bgutil_http") as connect,
        ):
            ytdlp_service.YtDlpService.extend_runtime_and_auth_arguments(
                cmd, "https://example.com/video"
            )
        connect.assert_not_called()
        find_tool.assert_not_called()
        self.assertNotIn("--plugin-dirs", cmd)


if __name__ == "__main__":
    unittest.main()
