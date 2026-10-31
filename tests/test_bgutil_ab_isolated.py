"""Offline safety, protocol and order tests for isolated Stage03.5 runner."""

from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location(
    "rrv_bgutil_ab_isolated", HERE / "manual" / "bgutil_ab_isolated.py",
)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)


class FakeWorker:
    def __init__(self, output, code=0, pid=18248):
        self.output = output
        self.returncode = code
        self.pid = pid
        self.timeout_seen = None
        self.killed = False

    def communicate(self, timeout=None):
        self.timeout_seen = timeout
        return self.output, "SENSITIVE_OTHER_STDERR"

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True


class IsolatedCompareTests(unittest.TestCase):
    def report(self, scenario="bgutil", trial=1, pid=18248, **overrides):
        fields = dict(
            protocol=1, worker_pid=pid, scenario=scenario, trial=trial,
            status="ok", setup_ms=12, extract_ms=95, total_ms=107,
            token_source="none", chrome_signal=False,
            bgutil_registered=(scenario == "bgutil"), wpc_registered=True,
        )
        fields.update(overrides)
        return RUNNER._MAGIC + json.dumps(fields, separators=(",", ":")) + "\n"

    def test_plan_uses_both_opposite_orders_with_new_worker_for_every_step(self):
        self.assertEqual(RUNNER.plan(), [
            ("bgutil-first", "bgutil", 1), ("bgutil-first", "wpc", 1),
            ("wpc-first", "wpc", 2), ("wpc-first", "bgutil", 2),
        ])
        self.assertEqual(len(RUNNER.plan(4)), 8)
        with self.assertRaises(ValueError):
            RUNNER.plan(1)

    def test_parser_accepts_only_safe_one_line_protocol(self):
        payload = RUNNER.parse_worker_report(self.report(), "bgutil", 1, 18248)
        self.assertEqual(payload["total_ms"], 107)
        self.assertIsNone(RUNNER.parse_worker_report(
            self.report() + "SECRET_TOKEN_PRIVATE\n", "bgutil", 1, 18248,
        ))
        self.assertIsNone(RUNNER.parse_worker_report("user's cookie path", "bgutil", 1, 18248))

    def test_parser_rejects_inconsistent_worker_identity_and_metadata(self):
        scenarios = [
            (self.report(pid=123), "bgutil", 1, 18248),
            (self.report(scenario="wpc"), "bgutil", 1, 18248),
            (self.report(trial=2), "bgutil", 1, 18248),
            (self.report(status="sensitive output/cookie.txt"), "bgutil", 1, 18248),
            (self.report(setup_ms=True), "bgutil", 1, 18248),
            (self.report(total_ms=20), "bgutil", 1, 18248),
            (self.report(token_source="SECRET_PO_TOKEN"), "bgutil", 1, 18248),
            (self.report(protocol=2), "bgutil", 1, 18248),
            (self.report(unexpected="some data"), "bgutil", 1, 18248),
        ]
        for raw, scenario, trial, pid in scenarios:
            with self.subTest(raw=raw[:80]):
                self.assertIsNone(RUNNER.parse_worker_report(raw, scenario, trial, pid))

    def test_parent_invokes_fresh_interpreter_and_captures_all_output(self):
        fake = FakeWorker(self.report())
        with patch.object(RUNNER.subprocess, "Popen", return_value=fake) as popen:
            actual = RUNNER.run_isolated("bgutil-first", "bgutil", 1, "https://www.youtube.com/watch?v=example")
        self.assertEqual(actual.status, "ok")
        self.assertEqual(actual.worker_pid, 18248)
        self.assertGreaterEqual(actual.wall_ms, 0)
        args = popen.call_args.args[0]
        self.assertEqual(args[0], sys.executable)
        self.assertIn("--_worker", args)
        self.assertIn("--_scenario", args)
        self.assertIn("bgutil", args)
        self.assertTrue(popen.call_args.kwargs["stdout"] == subprocess.PIPE)
        self.assertTrue(popen.call_args.kwargs["stderr"] == subprocess.PIPE)
        self.assertEqual(fake.timeout_seen, 180)
        self.assertNotIn("SENSITIVE_OTHER_STDERR", repr(actual))

    def test_child_protocol_corruption_is_safe_failure(self):
        fake = FakeWorker(self.report() + "SENSITIVE_FAKE_PO_TOKEN\n")
        output = StringIO()
        with patch.object(RUNNER.subprocess, "Popen", return_value=fake), redirect_stdout(output):
            actual = RUNNER.run_isolated("bgutil-first", "bgutil", 1, "https://www.youtube.com/watch?v=example")
        self.assertEqual(actual.status, "worker-protocol-error")
        self.assertNotIn("SENSITIVE", output.getvalue())
        self.assertNotIn("SENSITIVE", repr(actual))

    def test_timeout_kills_worker_tree_before_returning(self):
        fake = FakeWorker(self.report(), pid=18248)
        def bad_communicate(timeout=None):
            raise subprocess.TimeoutExpired("SECRET command", 180)
        fake.communicate = bad_communicate
        with (patch.object(RUNNER.subprocess, "Popen", return_value=fake),
              patch.object(RUNNER, "_kill_worker_tree") as kill):
            out = RUNNER.run_isolated("wpc-first", "wpc", 2, "https://www.youtube.com/watch?v=example")
        self.assertEqual(out.status, "worker-timeout")
        self.assertEqual(out.worker_pid, 18248)
        kill.assert_called_once_with(fake)

    def test_failed_child_status_is_retained_without_false_success(self):
        failure = FakeWorker(self.report(status="bgutil-startup-timeout", setup_ms=18000,
                                              extract_ms=0, total_ms=18000), code=1)
        with patch.object(RUNNER.subprocess, "Popen", return_value=failure):
            result = RUNNER.run_isolated("bgutil-first", "bgutil", 1, "https://www.youtube.com/watch?v=x")
        self.assertEqual(result.status, "bgutil-startup-timeout")
        mismatch = FakeWorker(self.report(), code=1)
        with patch.object(RUNNER.subprocess, "Popen", return_value=mismatch):
            result = RUNNER.run_isolated("bgutil-first", "bgutil", 1, "https://www.youtube.com/watch?v=x")
        self.assertEqual(result.status, "worker-exit-mismatch")

    def test_worker_returns_one_safe_json_line_then_stops_server(self):
        mock_paths = ModuleType("app.paths")
        mock_paths.find_executable = lambda name: Path("yt-dlp.exe")
        mock_service = ModuleType("services.bgutil_http_service")
        stopped = []
        mock_service.shutdown_bgutil_http = lambda: stopped.append(True)
        expected = RUNNER.BASE_BENCH.Trial(
            "bgutil", 1, "ok", 1, 7, 8, "bgutil", False, True, True,
        )
        output = StringIO()
        with (
            patch.dict(sys.modules, {
                "app.paths": mock_paths,
                "services.bgutil_http_service": mock_service,
            }),
            patch.object(RUNNER.BASE_BENCH, "run_trial", return_value=expected),
            redirect_stdout(output),
        ):
            code = RUNNER._worker_main("bgutil", 1, "https://www.youtube.com/watch?v=x")
        self.assertEqual(code, 0)
        self.assertEqual(stopped, [True])
        self.assertIsNotNone(RUNNER.parse_worker_report(output.getvalue(), "bgutil", 1, os.getpid()))
        self.assertEqual(output.getvalue().count("\n"), 1)

    def test_main_completes_both_order_groups_even_on_one_failure(self):
        mock_paths = ModuleType("app.paths")
        mock_paths.find_executable = lambda name: Path("fake.exe")
        mock_paths.wpc_provider_runtime_ready = lambda: True
        mock_diagnostics = ModuleType("app.bgutil_diagnostics")
        log = []
        mock_diagnostics.record_bgutil_diagnostic = lambda *a, **k: log.append((a, k))
        mock_bgutil = ModuleType("services.bgutil_http_service")
        mock_bgutil.ENV_HOME = "RRV_BGUTIL_STAGE03_HOME"
        mock_bgutil._validate_external_home = lambda _: True
        mock_ytdlp = ModuleType("services.ytdlp_service")
        mock_ytdlp.YtDlpService = SimpleNamespace(is_youtube_url=lambda url: True)
        steps = []
        def fake_trial(order, scenario, trial, video):
            steps.append((order, scenario, trial))
            status = "bgutil-startup-timeout" if scenario == "bgutil" and trial == 1 else "ok"
            return RUNNER.IsolatedResult(order, scenario, trial, 20000 + len(steps), status,
                                         2, 4, 6, 9, "none", False, scenario == "bgutil", True)
        out = StringIO()
        with (patch.dict(sys.modules, {
                "app.bgutil_diagnostics": mock_diagnostics,
                "app.paths": mock_paths,
                "services.bgutil_http_service": mock_bgutil,
                "services.ytdlp_service": mock_ytdlp,
            }),
            patch.dict(os.environ, {"RRV_BGUTIL_STAGE03_HOME": "/external"}),
            patch.object(RUNNER, "run_isolated", side_effect=fake_trial),
            redirect_stdout(out)):
            code = RUNNER.main([])
        self.assertEqual(code, 1)
        self.assertEqual(steps, RUNNER.plan())
        self.assertEqual(len(log), 4)
        self.assertIn("ISOLATED COMPARISON: NEEDS REVIEW", out.getvalue())
        self.assertEqual([x[1]["pid"] for x in log], [20001, 20002, 20003, 20004])

    def test_summary_prints_safe_values_only(self):
        result = RUNNER._empty_result("wpc-first", "wpc", 2, "worker-timeout",
                                      worker_pid=330, wall_ms=123)
        output = StringIO()
        with redirect_stdout(output):
            RUNNER.print_summary([result])
        self.assertIn("worker-timeout", output.getvalue())
        self.assertNotIn("https://", output.getvalue())


if __name__ == "__main__":
    unittest.main()
