from __future__ import annotations

import ast
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from services.bgutil_http_service import BgUtilConnection, ENV_HOME
from services import bgutil_http_service as bgutil
from services import ytdlp_service


class BgutilDiagnosticIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.deno = Path("C:/rrv/deno.exe")
        self.connection = BgUtilConnection(
            Path("C:/external/bgutil-stage03"), "http://127.0.0.1:12345",
        )
        cookie_patch = patch.object(
            ytdlp_service, "RRV_YOUTUBE_AUTH_COOKIE_PATH", Path("__missing_test_login_cookie__"),
        )
        cookie_patch.start()
        self.addCleanup(cookie_patch.stop)
        manual_patch = patch.object(ytdlp_service.YtDlpService, "_find_cookie_file", return_value=None)
        manual_patch.start()
        self.addCleanup(manual_patch.stop)

    def test_wpc_only_analysis_records_mode_disabled(self):
        command = ["yt-dlp.exe", "--dump-single-json"]
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(ytdlp_service, "find_executable", return_value=self.deno),
            patch.object(ytdlp_service, "wpc_provider_runtime_ready", return_value=True),
            patch.object(ytdlp_service, "record_bgutil_diagnostic") as write,
        ):
            ytdlp_service.YtDlpService.extend_runtime_and_auth_arguments(
                command, "https://www.youtube.com/watch?v=abc",
            )
        self.assertNotIn("--extractor-args", command)
        write.assert_called_once()
        kwargs = write.call_args.kwargs
        self.assertEqual(kwargs["mode"], "disabled")
        self.assertEqual(kwargs["stage"], "analysis")
        self.assertEqual(kwargs["bgutil"], "disabled")
        self.assertEqual(kwargs["route"], "wpc-only")

    def test_ready_bgutil_download_records_provider_selection(self):
        command = ["yt-dlp.exe", "--progress"]
        with (
            patch.dict(os.environ, {ENV_HOME: "C:/external"}),
            patch.object(ytdlp_service, "find_executable", return_value=self.deno),
            patch.object(ytdlp_service, "wpc_provider_runtime_ready", return_value=True),
            patch.object(bgutil, "connect_bgutil_http", return_value=self.connection),
            patch.object(bgutil, "bgutil_http_status", return_value="ready"),
            patch.object(ytdlp_service, "record_bgutil_diagnostic") as write,
        ):
            ytdlp_service.YtDlpService.extend_runtime_and_auth_arguments(
                command, "https://www.youtube.com/watch?v=abc",
            )
        kwargs = write.call_args.kwargs
        self.assertEqual(kwargs["mode"], "enabled")
        self.assertEqual(kwargs["stage"], "download")
        self.assertEqual(kwargs["deno"], "found")
        self.assertEqual(kwargs["bgutil"], "ready")
        self.assertEqual(kwargs["route"], "bgutil-and-wpc")
        self.assertTrue(any("bgutilhttp" in arg for arg in command))

    def test_failed_bgutil_falls_back_and_records_reason(self):
        command = ["yt-dlp.exe", "--dump-single-json"]
        with (
            patch.dict(os.environ, {ENV_HOME: "C:/external"}),
            patch.object(ytdlp_service, "find_executable", return_value=self.deno),
            patch.object(ytdlp_service, "wpc_provider_runtime_ready", return_value=True),
            patch.object(bgutil, "connect_bgutil_http", return_value=None),
            patch.object(bgutil, "bgutil_http_status", return_value="server-ping-timeout"),
            patch.object(ytdlp_service, "record_bgutil_diagnostic") as write,
        ):
            ytdlp_service.YtDlpService.extend_runtime_and_auth_arguments(
                command, "https://www.youtube.com/watch?v=abc",
            )
        kwargs = write.call_args.kwargs
        self.assertEqual(kwargs["mode"], "enabled")
        self.assertEqual(kwargs["bgutil"], "server-ping-timeout")
        self.assertEqual(kwargs["route"], "wpc-only")
        self.assertNotIn("--extractor-args", command)

    def test_non_youtube_does_not_write_provider_event(self):
        command = ["yt-dlp.exe"]
        with (
            patch.dict(os.environ, {ENV_HOME: "C:/external"}),
            patch.object(ytdlp_service, "record_bgutil_diagnostic") as write,
            patch.object(ytdlp_service, "find_executable") as find,
        ):
            ytdlp_service.YtDlpService.extend_runtime_and_auth_arguments(
                command, "https://example.invalid/video",
            )
        find.assert_not_called()
        write.assert_not_called()

    def test_connect_logs_server_pid_and_status_without_paths(self):
        with (
            patch.dict(os.environ, {ENV_HOME: "C:/external"}),
            patch.object(bgutil._SERVER, "ensure", return_value=self.connection),
            patch.object(bgutil._SERVER, "status", return_value="ready"),
            patch.object(bgutil._SERVER, "process_pid", return_value=4525),
            patch.object(bgutil, "record_bgutil_diagnostic") as write,
        ):
            self.assertEqual(bgutil.connect_bgutil_http(self.deno), self.connection)
        kwargs = write.call_args.kwargs
        self.assertEqual(kwargs["result"], "ready")
        self.assertEqual(kwargs["status"], "ready")
        self.assertEqual(kwargs["server_pid"], 4525)
        self.assertNotIn("C:/external", str(kwargs))

    def test_app_startup_and_forwarding_are_instrumented(self):
        source_path = Path(__file__).resolve().parents[1] / "main.py"
        root = ast.parse(source_path.read_text(encoding="utf-8"))
        events = [
            call.args[0].value for call in ast.walk(root)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "record_bgutil_diagnostic"
            and call.args and isinstance(call.args[0], ast.Constant)
        ]
        for event in ("app.launched", "app.primary", "app.forwarded", "app.closed"):
            self.assertIn(event, events)


if __name__ == "__main__":
    unittest.main()
