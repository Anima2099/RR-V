"""Safety and correctness tests for the manual token/fallback probe."""
from __future__ import annotations

import importlib.util
from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "rrv_bgutil_token_fallback_probe", HERE / "manual" / "bgutil_token_fallback_probe.py"
)
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = PROBE
SPEC.loader.exec_module(PROBE)


class TokenProbeTests(unittest.TestCase):
    def signals(self, **replacements):
        base = dict(
            bgutil_registered=True, wpc_registered=False,
            bgutil_requested=True, wpc_requested=False,
            bgutil_response=True, wpc_response=False,
            import_error=False, invalid_response=False, exit_code=0,
        )
        base.update(replacements)
        return PROBE.TokenSignals(**base)

    def test_valid_bgutil_response_is_confirmed(self):
        self.assertEqual(PROBE.classify("bgutil", self.signals()), "bgutil-token-confirmed")

    def test_token_attempt_alone_is_not_success(self):
        self.assertEqual(PROBE.classify("bgutil", self.signals(bgutil_response=False)),
                         "token-request-without-response")

    def test_no_request_is_not_success(self):
        self.assertEqual(PROBE.classify("bgutil", self.signals(bgutil_response=False, bgutil_requested=False)),
                         "no-token-request")

    def test_bad_video_exit_is_not_full_success(self):
        self.assertEqual(PROBE.classify("bgutil", self.signals(exit_code=1)),
                         "token-response-but-video-failed")

    def test_bgutil_mode_rejects_wpc(self):
        self.assertEqual(PROBE.classify("bgutil", self.signals(wpc_registered=True)),
                         "unexpected-wpc-registration")

    def test_fallback_requires_wpc_actual_token(self):
        self.assertEqual(PROBE.classify("fallback", self.signals(wpc_registered=True, bgutil_response=False,
                         wpc_requested=True, wpc_response=True)), "wpc-token-confirmed")
        self.assertEqual(PROBE.classify("fallback", self.signals(wpc_registered=True, bgutil_response=False,
                         wpc_requested=True, wpc_response=False)), "wpc-request-without-response")

    def test_rejects_invalid_provider_response(self):
        self.assertEqual(PROBE.classify("bgutil", self.signals(invalid_response=True)),
                         "invalid-provider-response")

    def test_fallback_rejects_unexpected_bgutil_success(self):
        self.assertEqual(PROBE.classify("fallback", self.signals(wpc_registered=True, wpc_response=True)),
                         "unexpected-bgutil-response")

    def test_trace_parser_does_not_return_tokens(self):
        token = "SUPER_SECRET_PO_TOKEN_VALUE_12345"
        trace = (
            '[debug] [youtube] [pot] PO Token Providers: bgutil:http-2.0.2 (external)\n'
            '[youtube] [pot:bgutil:http] Generating a gvs PO Token for mweb client via bgutil HTTP server\n'
            f'[debug] [youtube] [pot] PO Token response from "bgutil:http" provider: PoTokenResponse(po_token=\'{token}\')\n'
        )
        summary = PROBE.inspect_trace(trace, 0)
        self.assertTrue(summary.bgutil_response)
        self.assertTrue(summary.bgutil_requested)
        self.assertNotIn(token, repr(summary))
        self.assertNotIn(token, PROBE.classify("bgutil", summary))

    def test_default_main_never_prints_sensitive_token_or_launches_wpc(self):
        names = (
            "app", "app.bgutil_diagnostics", "app.paths", "services",
            "services.bgutil_http_service", "services.ytdlp_service",
        )
        stubs = {name: ModuleType(name) for name in names}
        records = []
        stubs["app.bgutil_diagnostics"].record_bgutil_diagnostic = (
            lambda *args, **kwargs: records.append((args, kwargs))
        )
        stubs["app.paths"].RRV_WPC_PROVIDER_DIR = Path("wpc-dir")
        stubs["app.paths"].find_executable = lambda name: Path("tools") / name
        stubs["app.paths"].wpc_provider_runtime_ready = lambda: self.fail("WPC should not be accessed")
        stubs["services.bgutil_http_service"].ENV_HOME = "RRV_BGUTIL_STAGE03_HOME"
        stubs["services.bgutil_http_service"]._validate_external_home = lambda path: True
        stubs["services.bgutil_http_service"].connect_bgutil_http = lambda deno: SimpleNamespace(
            base_url="http://127.0.0.1:12945",
        )
        stubs["services.bgutil_http_service"].shutdown_bgutil_http = lambda: None

        class FakeYtDlpService:
            @staticmethod
            def is_youtube_url(url):
                return url.startswith("https://www.youtube.com/watch?v=")

        stubs["services.ytdlp_service"].YtDlpService = FakeYtDlpService
        token = "SENSITIVE_FAKE_TOKEN_EXAMPLE_12345678"
        output = (
            "[debug] [youtube] [pot] PO Token Providers: bgutil:http-2.0.2 (external)\n"
            "[youtube] [pot:bgutil:http] Generating a gvs PO Token for mweb client via bgutil HTTP server\n"
            f'[debug] [youtube] [pot] PO Token response from "bgutil:http" provider: PoTokenResponse(po_token={token!r})\n'
        )
        buffer = StringIO()
        with (
            patch.dict(sys.modules, stubs),
            patch.dict(os.environ, {"RRV_BGUTIL_STAGE03_HOME": "/somewhere/stage03"}),
            patch.object(PROBE.subprocess, "run", return_value=SimpleNamespace(
                stdout="", stderr=output, returncode=0,
            )) as runner,
            redirect_stdout(buffer),
        ):
            code = PROBE.main([])
        self.assertEqual(code, 0)
        self.assertIn("Token issuance: CONFIRMED", buffer.getvalue())
        self.assertNotIn(token, buffer.getvalue())
        self.assertNotIn(token, repr(records))
        self.assertEqual(records[0][1]["status"], "bgutil-token-confirmed")
        self.assertTrue(runner.call_args.kwargs["capture_output"])
        self.assertEqual(runner.call_args.args[0].count("--plugin-dirs"), 1)

    def test_only_explicit_fallback_registers_wpc(self):
        base = (Path("yt-dlp.exe"), Path("deno.exe"), Path("stage03-home"),
                "http://127.0.0.1:13344", False, PROBE.DEFAULT_VIDEO)
        safe_cmd = PROBE._build_command(*base)
        self.assertEqual(safe_cmd.count("--plugin-dirs"), 1)
        self.assertIn("--no-cache-dir", safe_cmd)
        self.assertIn("--no-plugin-dirs", safe_cmd)
        self.assertIn("pot_trace=true", " ".join(safe_cmd))
        fallback_cmd = PROBE._build_command(*base[:4], True, base[5], Path("wpc-dir"))
        self.assertEqual(fallback_cmd.count("--plugin-dirs"), 2)
        self.assertIn("wpc-dir", fallback_cmd)


if __name__ == "__main__":
    unittest.main()
