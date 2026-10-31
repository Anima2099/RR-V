"""Offline guard tests for the equal-condition Stage03 A/B comparison."""
from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
from io import StringIO
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).parent / 'manual' / 'bgutil_ab_compare.py'
SPEC = importlib.util.spec_from_file_location('rrv_bgutil_ab_compare', SCRIPT)
assert SPEC and SPEC.loader
BENCH = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BENCH
SPEC.loader.exec_module(BENCH)


class BgutilABComparisonTests(unittest.TestCase):
    def test_order_is_balanced_for_two_trials(self):
        self.assertEqual(BENCH.sequence(2), [
            ('wpc', 1), ('bgutil', 1), ('bgutil', 2), ('wpc', 2),
        ])
        self.assertEqual(BENCH.sequence(1), [('wpc', 1), ('bgutil', 1)])

    def test_parse_bgutil_token_without_exposing_value(self):
        secret = 'SENSITIVE_TOKEN_321'
        raw = (
            '[debug] [youtube] [pot] PO Token Providers: bgutil:http-2.0.2 (external), wpc-1.1.2\n'
            f'[debug] [youtube] [pot] PO Token response from "bgutil:http" provider: PoTokenResponse(po_token={secret!r})\n'
        )
        out = BENCH.read_signals(raw)
        self.assertEqual(out, (True, True, 'bgutil', False, False))
        self.assertNotIn(secret, repr(out))

    def test_parse_wpc_browser_and_token_signal(self):
        raw = (
            '[debug] [youtube] [pot] PO Token Providers: wpc-1.1.2\n'
            'Launching youtube.com in browser to retrieve PO Token(s).\n'
            '[debug] [youtube] [pot] PO Token response from "wpc" provider: PoTokenResponse(po_token="hidden")\n'
        )
        self.assertEqual(BENCH.read_signals(raw), (False, True, 'wpc', True, False))

    def test_no_token_request_is_not_a_failure(self):
        raw = '[debug] [youtube] [pot] PO Token Providers: wpc-1.1.2\n'
        self.assertEqual(BENCH.read_signals(raw)[2], 'none')

    def test_plugin_error_flag(self):
        self.assertTrue(BENCH.read_signals('Error while importing module example')[4])

    def test_identical_command_except_for_real_provider_builder(self):
        fake_services = ModuleType('services')
        fake_ytdlp = ModuleType('services.ytdlp_service')
        fake_ytdlp.RRV_YOUTUBE_AUTH_COOKIE_PATH = Path('real_cookie_file')
        seen = []
        class FakeYtDlp:
            @staticmethod
            def extend_runtime_and_auth_arguments(command, url):
                enabled = bool(os.environ.get('RRV_BGUTIL_STAGE03_HOME'))
                seen.append(enabled)
                command.extend(['--no-plugin-dirs', '--plugin-dirs', 'wpc-dir'])
                if enabled:
                    command.extend([
                        '--plugin-dirs', 'bgutil-dir', '--extractor-args',
                        'youtubepot-bgutilhttp:base_url=http://127.0.0.1:12345',
                    ])
            @staticmethod
            def _find_cookie_file(url):
                return Path('sensitive')
        fake_ytdlp.YtDlpService = FakeYtDlp
        fake_services.ytdlp_service = fake_ytdlp
        with patch.dict(sys.modules, {'services': fake_services, 'services.ytdlp_service': fake_ytdlp}):
            wpc = BENCH._command(Path('yt-dlp.exe'), BENCH.DEFAULT_VIDEO, 'wpc', '/external')
            bgutil = BENCH._command(Path('yt-dlp.exe'), BENCH.DEFAULT_VIDEO, 'bgutil', '/external')
        self.assertEqual(seen, [False, True])
        self.assertEqual(wpc[0], bgutil[0])
        for flag in ('--simulate', '--ignore-config', '--no-cache-dir', '--verbose'):
            self.assertIn(flag, wpc)
            self.assertIn(flag, bgutil)
        self.assertIn('youtube:pot_trace=true', wpc)
        self.assertNotIn('player-client', ' '.join(wpc + bgutil))
        self.assertNotIn('--cookies', wpc + bgutil)
        self.assertEqual(wpc[-1], bgutil[-1])
        self.assertNotIn('youtubepot-bgutilhttp:base_url=', ' '.join(wpc))

    def test_run_trial_is_safe_and_redacts_raw_trace(self):
        secret = 'SUPER_SECRET_TOKEN_VALUE'
        raw = (
            '[debug] [youtube] [pot] PO Token Providers: wpc-1.1.2\n'
            f'[debug] [youtube] [pot] PO Token response from "wpc" provider: PoTokenResponse(po_token={secret!r})\n'
        )
        with (
            patch.object(BENCH, '_command', return_value=[
                'yt-dlp.exe', '--plugin-dirs', 'wpc-dir', '--no-cache-dir',
            ]),
            patch.object(BENCH.subprocess, 'run', return_value=SimpleNamespace(
                stdout='', stderr=raw, returncode=0,
            )) as run,
        ):
            out = BENCH.run_trial(Path('yt-dlp.exe'), BENCH.DEFAULT_VIDEO, 'wpc', 1, '/external')
        self.assertEqual(out.status, 'ok')
        self.assertEqual(out.token_source, 'wpc')
        self.assertNotIn(secret, repr(out))
        self.assertTrue(run.call_args.kwargs['capture_output'])

    def test_incorrect_registration_fails_closed(self):
        with (
            patch.object(BENCH, '_command', return_value=['yt-dlp.exe', '--plugin-dirs', 'wpc-dir']),
            patch.object(BENCH.subprocess, 'run', return_value=SimpleNamespace(
                stdout='', stderr='', returncode=0,
            )),
        ):
            out = BENCH.run_trial(Path('yt-dlp.exe'), BENCH.DEFAULT_VIDEO, 'wpc', 1, '/external')
        self.assertEqual(out.status, 'registration-mismatch')

    def test_bgutil_not_present_aborts_before_running(self):
        with (
            patch.object(BENCH, '_command', return_value=['yt-dlp.exe', '--plugin-dirs', 'wpc-dir']),
            patch.object(BENCH.subprocess, 'run') as run,
        ):
            out = BENCH.run_trial(Path('yt-dlp.exe'), BENCH.DEFAULT_VIDEO, 'bgutil', 1, '/external')
        self.assertEqual(out.status, 'provider-setup-mismatch')
        run.assert_not_called()

    def test_startup_timeout_gets_specific_safe_comparison_status(self):
        fake_pkg = ModuleType("services")
        fake_bgutil = ModuleType("services.bgutil_http_service")
        fake_bgutil.bgutil_http_status = lambda: "server-ping-timeout"
        with (
            patch.dict(sys.modules, {
                "services": fake_pkg,
                "services.bgutil_http_service": fake_bgutil,
            }),
            patch.object(BENCH, "_command", return_value=[
                "yt-dlp.exe", "--plugin-dirs", "wpc-dir",
            ]),
            patch.object(BENCH.subprocess, "run") as subprocess_run,
        ):
            result = BENCH.run_trial(
                Path("yt-dlp.exe"), BENCH.DEFAULT_VIDEO, "bgutil", 1, "/external",
            )
        self.assertEqual(result.status, "bgutil-startup-timeout")
        subprocess_run.assert_not_called()

    def test_summary_uses_only_safe_fields(self):
        output = StringIO()
        result = BENCH.Trial('bgutil', 1, 'ok', 10, 20, 30, 'bgutil', False, True, True)
        with redirect_stdout(output):
            BENCH.print_summary([result])
        self.assertIn('median total: 30 ms', output.getvalue())
        self.assertNotIn(BENCH.DEFAULT_VIDEO, output.getvalue())


if __name__ == '__main__':
    unittest.main()
