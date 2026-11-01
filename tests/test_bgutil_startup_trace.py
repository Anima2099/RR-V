"""Offline unit tests for the bounded, privacy-safe startup diagnostic."""

from __future__ import annotations

import importlib.util
from io import StringIO
from contextlib import redirect_stdout
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

SOURCE = Path(__file__).parent / "manual" / "bgutil_startup_trace.py"
SPEC = importlib.util.spec_from_file_location("rrv_bgutil_startup_trace", SOURCE)
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROBE
SPEC.loader.exec_module(PROBE)


class FakeCollector:
    def __init__(self):
        self.kind = "no-output"

    def feed(self, chunk):
        if b"Started POT server" in chunk:
            self.kind = "server-announced"
        elif chunk:
            self.kind = "other-output"

    def snapshot(self):
        return self.kind, 0


class StartupProbeTests(unittest.TestCase):
    def test_output_capture_only_retains_fixed_categories(self):
        timeline = PROBE.StartupTimeline()
        collector = FakeCollector()
        secret = b"PRIVATE_TOKEN_EXAMPLE_ABC"
        timeline.observe_output(FakeCollector.feed, collector, b"Started POT server " + secret)
        self.assertEqual(timeline.output_kind, "server-announced")
        self.assertNotIn(secret.decode(), repr(vars(timeline)))
        self.assertNotIn(secret.decode(), repr(timeline.finish(1, "ready", True)))

    def test_invalid_tcp_target_not_probed(self):
        timeline = PROBE.StartupTimeline()
        with patch.object(PROBE.socket, "create_connection") as probe:
            self.assertFalse(timeline.observe_ping(lambda _: False, "https://example.com:443"))
        probe.assert_not_called()
        self.assertEqual(timeline.ping_attempts, 1)
        self.assertEqual(timeline.tcp_checks, 0)

    def test_valid_ping_records_tcp_and_http_milestones(self):
        timeline = PROBE.StartupTimeline()
        with patch.object(PROBE.socket, "create_connection") as probe:
            self.assertTrue(timeline.observe_ping(lambda _: True, "http://127.0.0.1:7777"))
        probe.assert_not_called()
        self.assertEqual(timeline.ping_attempts, 1)
        self.assertEqual(timeline.tcp_checks, 0)
        self.assertGreaterEqual(timeline.ping_ms, 0)

    def test_http_not_ready_but_local_tcp_accepts(self):
        clock = [1.0]
        timeline = PROBE.StartupTimeline(clock=lambda: clock[0])
        clock[0] = 1.7
        socket_mock = MagicMock()
        socket_mock.__enter__.return_value = socket_mock
        with patch.object(PROBE.socket, "create_connection", return_value=socket_mock) as connect:
            self.assertFalse(timeline.observe_ping(lambda _: False, "http://127.0.0.1:7777"))
        connect.assert_called_once()
        self.assertEqual(timeline.tcp_checks, 1)
        self.assertEqual(timeline.tcp_ms, 700)
        self.assertEqual(timeline.ping_ms, 0)

    def test_tcp_not_listening_yet_is_safe(self):
        timeline = PROBE.StartupTimeline()
        with patch.object(PROBE.socket, "create_connection", side_effect=ConnectionRefusedError("token")):
            self.assertFalse(timeline.observe_ping(lambda _: False, "http://127.0.0.1:7777"))
        self.assertEqual(timeline.tcp_ms, 0)
        self.assertEqual(timeline.ping_ms, 0)

    def test_ready_and_late_ready_are_distinct(self):
        clock = [0.0]
        timeline = PROBE.StartupTimeline(clock=lambda: clock[0])
        clock[0] = 17.5
        self.assertEqual(timeline.finish(1, "ready", True).result, "ready")
        clock[0] = 19.5
        self.assertEqual(timeline.finish(1, "ready", True).result, "late-ready")
        self.assertEqual(timeline.finish(1, "server-ping-timeout", False).result, "timeout")
        self.assertEqual(timeline.finish(1, "deno-exited-before-ready:code=3", False).result, "early-exit")
        self.assertEqual(timeline.finish(1, "probe-exception", False).result, "start-failed")

    def _fake_service(self, *, successful=True, advance=None):
        service = types.SimpleNamespace()
        service._START_TIMEOUT = 12.0
        service._COLD_START_GRACE = 6.0
        service._ping_local_provider = lambda url: True
        service._SafeDenoOutput = FakeCollector
        service.server_closed = 0
        service.reported_deadline = 0

        class FakeServer:
            def ensure(self, home, deno):
                service.reported_deadline = service._START_TIMEOUT
                assert service._COLD_START_GRACE == 0
                collector = service._SafeDenoOutput()
                collector.feed(b"Started POT server PRIVATE_TRACE_NEVER_LOG_THIS")
                assert service._ping_local_provider("http://127.0.0.1:7777")
                if advance is not None:
                    advance()
                return object() if successful else None

            def status(self):
                return "ready" if successful else "server-ping-timeout"

            def close(self):
                service.server_closed += 1

        service._BgUtilServer = FakeServer
        return service

    def test_run_once_uses_actual_service_and_restores_deadlines(self):
        svc = self._fake_service()
        res = PROBE.run_once(svc, Path("/fake/external"), Path("/fake/deno"), 1)
        self.assertEqual(res.result, "ready")
        self.assertEqual(svc.reported_deadline, 35)
        self.assertEqual(svc._START_TIMEOUT, 12)
        self.assertEqual(svc._COLD_START_GRACE, 6)
        self.assertEqual(svc.server_closed, 1)
        self.assertEqual(res.output_kind, "server-announced")
        self.assertEqual(res.ping_attempts, 1)

    def test_run_once_records_failure_without_crash(self):
        svc = self._fake_service(successful=False)
        res = PROBE.run_once(svc, Path("/fake/external"), Path("/fake/deno"), 2)
        self.assertEqual(res.result, "timeout")
        self.assertEqual(svc.server_closed, 1)

    def test_run_once_always_closes_on_private_exception(self):
        svc = self._fake_service()
        class BadServer:
            def ensure(self, home, deno):
                raise RuntimeError("SENSITIVE_PATH_OR_TOKEN")
            def close(self):
                svc.server_closed += 1
        svc._BgUtilServer = BadServer
        res = PROBE.run_once(svc, Path("/fake"), Path("/fake"), 1)
        self.assertEqual(res.status, "probe-exception")
        self.assertEqual(svc.server_closed, 1)
        self.assertNotIn("SENSITIVE", repr(res))

    def test_cleanup_exception_never_leaks_private_error(self):
        svc = self._fake_service()
        class BadClose:
            def ensure(self, home, deno):
                return object()
            def status(self):
                return "ready"
            def close(self):
                raise OSError("SECRET_TOKEN_OR_PATH")
        svc._BgUtilServer = BadClose
        res = PROBE.run_once(svc, Path("private"), Path("private"), 1)
        self.assertEqual(res.status, "cleanup-error")
        self.assertEqual(res.result, "start-failed")
        self.assertNotIn("SECRET", repr(res))

    def test_report_uses_privacy_safe_fields(self):
        result = PROBE.TraceResult(1, "late-ready", "ready", 19400, 18000,
                                   18399, 18500, 19000, 32, 31, 400,
                                   "server-announced")
        log = MagicMock()
        output = StringIO()
        with redirect_stdout(output):
            PROBE.report(result, log)
        self.assertIn("late-ready", output.getvalue())
        self.assertIn("19000", output.getvalue())
        self.assertNotIn("http://", output.getvalue())
        self.assertEqual(log.call_args.args[0], "bgutil.startup-probe")
        self.assertEqual(log.call_args.kwargs["announced_ms"], 18399)

    def test_baseline_js_runtime_only_records_fixed_status(self):
        fake_output = types.SimpleNamespace(returncode=0, stdout="RRV_DENO_BASELINE_OK\n")
        with patch.object(PROBE.subprocess, "run", return_value=fake_output) as run:
            status, duration = PROBE.run_deno_baseline(Path("deno"), Path("external"))
        self.assertEqual(status, "baseline-ready")
        self.assertGreaterEqual(duration, 0)
        self.assertEqual(run.call_args.args[0][1], "eval")
        self.assertEqual(run.call_args.kwargs["timeout"], 10)
        self.assertIn("DENO_DIR", run.call_args.kwargs["env"])

    def test_baseline_timeout_does_not_print_sensitive_output(self):
        error = PROBE.subprocess.TimeoutExpired("SENSITIVE_CMD", 10, output=b"SECRET")
        with patch.object(PROBE.subprocess, "run", side_effect=error):
            status, duration = PROBE.run_deno_baseline(Path("deno"), Path("external"))
        self.assertEqual(status, "baseline-timeout")
        self.assertNotIn("SENSITIVE", repr((status, duration)))

    def test_baseline_failure_and_launch_error(self):
        fake_output = types.SimpleNamespace(returncode=2, stdout="PRIVATE_PATH")
        with patch.object(PROBE.subprocess, "run", return_value=fake_output):
            self.assertEqual(PROBE.run_deno_baseline(Path("deno"), Path("external"))[0], "baseline-failed")
        with patch.object(PROBE.subprocess, "run", side_effect=OSError("SECRET")):
            self.assertEqual(PROBE.run_deno_baseline(Path("deno"), Path("external"))[0], "baseline-launch-error")

    def test_main_disabled_requires_opt_in(self):
        mock_paths = types.ModuleType("app.paths")
        mock_paths.find_executable = lambda _: Path("fake.exe")
        mock_diag = types.ModuleType("app.bgutil_diagnostics")
        mock_diag.record_bgutil_diagnostic = lambda *a, **kw: None
        mock_pkg = types.ModuleType("services")
        fake_service = types.ModuleType("services.bgutil_http_service")
        fake_service.ENV_HOME = "RRV_BGUTIL_STAGE03_HOME"
        mock_pkg.bgutil_http_service = fake_service
        with (
            patch.dict(sys.modules, {"app.paths": mock_paths, "app.bgutil_diagnostics": mock_diag,
                                     "services": mock_pkg, "services.bgutil_http_service": fake_service}),
            patch.dict(os.environ, {"RRV_BGUTIL_STAGE03_HOME": ""}),
        ):
            self.assertEqual(PROBE.main([]), 2)


if __name__ == "__main__":
    unittest.main()
