"""Regression coverage for the Chrome-free stage03 registration probe."""

from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
from io import StringIO
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

from services.bgutil_http_service import BgUtilConnection, ENV_HOME


class BgutilStage03ProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parent / "manual" / "bgutil_stage03_probe.py"
        spec = importlib.util.spec_from_file_location("rrv_bgutil_stage03_probe_tests", path)
        assert spec is not None and spec.loader is not None
        cls.probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.probe)

    def setUp(self):
        self.log = StringIO()
        self.root = Path("C:/LocalAppData/RR-V/bgutil-stage03-external")
        self.conn = BgUtilConnection(self.root, "http://127.0.0.1:12345")
        self.video = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

    def _run_probe(self, fake_result, connection=True):
        def fake_extend(command, _url):
            # In the actual probe this is patched to False specifically to
            # avoid launching WPC's browser even if BgUtils is not used.
            self.assertFalse(self.probe.ytdlp_service.wpc_provider_runtime_ready())
            command.extend(["--no-plugin-dirs", "--plugin-dirs", str(self.root)])

        tools = {"yt-dlp.exe": Path("C:/tools/yt-dlp.exe"), "deno.exe": Path("C:/tools/deno.exe")}
        with (
            patch.dict(os.environ, {ENV_HOME: str(self.root)}),
            patch.object(sys, "argv", ["probe.py"]),
            patch.object(self.probe, "find_executable", side_effect=lambda name: tools.get(name)),
            patch.object(self.probe, "connect_bgutil_http", return_value=self.conn if connection else None),
            patch.object(self.probe, "bgutil_http_status", return_value="ready" if connection else "server-ping-timeout"),
            patch.object(self.probe, "shutdown_bgutil_http") as shutdown,
            patch.object(self.probe.ytdlp_service.YtDlpService, "extend_runtime_and_auth_arguments", side_effect=fake_extend),
            patch.object(self.probe.subprocess, "run", return_value=fake_result) as run,
            redirect_stdout(self.log),
        ):
            code = self.probe.main()
        shutdown.assert_called_once()
        return code, run

    def test_registration_succeeds_without_wpc_and_no_download(self):
        fake = SimpleNamespace(
            stdout="",
            stderr="[debug] [youtube] [pot] PO Token Providers: bgutil:http-2.0.2 (external)\n",
            returncode=0,
        )
        result, subprocess_call = self._run_probe(fake)
        self.assertEqual(result, 0)
        self.assertEqual(subprocess_call.call_count, 1)
        arguments = subprocess_call.call_args.args[0]
        self.assertEqual(arguments.count("--plugin-dirs"), 1)
        self.assertIn("--simulate", arguments)
        self.assertIn("--no-plugin-dirs", arguments)
        self.assertIn("WPC registered (must be False): False", self.log.getvalue())

    def test_http_server_failure_aborts_before_ytdlp(self):
        fake = SimpleNamespace(stdout="", stderr="", returncode=0)
        result, subprocess_call = self._run_probe(fake, connection=False)
        self.assertEqual(result, 1)
        subprocess_call.assert_not_called()
        self.assertIn("server-ping-timeout", self.log.getvalue())

    def test_accidental_wpc_registration_is_a_failure(self):
        fake = SimpleNamespace(
            stdout="",
            stderr="[debug] [youtube] [pot] PO Token Providers: bgutil:http-2.0.2 (external), wpc-1.1.2 (external)\n",
            returncode=0,
        )
        result, _ = self._run_probe(fake)
        self.assertEqual(result, 1)
        self.assertIn("plugin loading/isolation issue", self.log.getvalue())

    def test_bgutil_import_failure_is_not_hidden(self):
        fake = SimpleNamespace(
            stdout="",
            stderr="Error while importing module 'getpot_bgutil_http'\n",
            returncode=0,
        )
        result, _ = self._run_probe(fake)
        self.assertEqual(result, 1)
        self.assertIn("Plugin import error: True", self.log.getvalue())


if __name__ == "__main__":
    unittest.main()
