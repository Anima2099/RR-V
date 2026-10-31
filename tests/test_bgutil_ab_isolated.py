"""Offline tests for correlated, isolated Stage03.5 worker communication."""

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

RUN_ID = "0123456789abcdef0123456789abcdef"


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
    def setUp(self):
        patcher = patch.object(RUNNER.secrets, "token_hex", return_value=RUN_ID)
        patcher.start()
        self.addCleanup(patcher.stop)

    def hello(self, pid=27248, **overrides):
        data = dict(protocol=1, run_id=RUN_ID, worker_pid=pid)
        data.update(overrides)
        return RUNNER._HELLO + json.dumps(data, separators=(",", ":")) + "\n"

    def report(self, scenario="bgutil", trial=1, pid=27248,
               hello=True, **overrides):
        fields = dict(
            protocol=1, run_id=RUN_ID, worker_pid=pid,
            scenario=scenario, trial=trial,
            status="ok", setup_ms=12, extract_ms=95, total_ms=107,
            token_source="none", chrome_signal=False,
            bgutil_registered=(scenario == "bgutil"), wpc_registered=True,
        )
        fields.update(overrides)
        return ((self.hello(pid) if hello else "") + RUNNER._MAGIC
                + json.dumps(fields, separators=(",", ":")) + "\n")

    def test_plan_uses_both_opposite_orders_with_new_worker_for_every_step(self):
        self.assertEqual(RUNNER.plan(), [
            ("bgutil-first", "bgutil", 1), ("bgutil-first", "wpc", 1),
            ("wpc-first", "wpc", 2), ("wpc-first", "bgutil", 2),
        ])
        self.assertEqual(len(RUNNER.plan(4)), 8)
        with self.assertRaises(ValueError):
            RUNNER.plan(1)

    def test_parser_accepts_different_windows_venv_launcher_and_worker_pids(self):
        payload = RUNNER.parse_worker_report(self.report(pid=27248), "bgutil", 1, RUN_ID)
        self.assertEqual(payload["worker_pid"], 27248)
        self.assertNotEqual(payload["worker_pid"], 21180)

    def test_parser_discards_extra_output_instead_of_exposing_it(self):
        message = "SENSITIVE_TOKEN_FROM_UNRELATED_STDOUT"
        raw = message + "\n" + self.report() + message + "\n"
        self.assertIsNotNone(RUNNER.parse_worker_report(raw, "bgutil", 1, RUN_ID))
        self.assertNotIn(message, repr(RUNNER.parse_worker_report(raw, "bgutil", 1, RUN_ID)))

    def test_parser_rejects_duplicate_protocol_records(self):
        payload = self.report()
        self.assertIsNone(RUNNER.parse_worker_report(payload + payload, "bgutil", 1, RUN_ID))
        self.assertIsNone(RUNNER.parse_worker_report(self.report(hello=False), "bgutil", 1, RUN_ID))
        self.assertIsNone(RUNNER.parse_worker_report("user's cookie path", "bgutil", 1, RUN_ID))

    def test_parser_rejects_invalid_metadata(self):
        cases = [
            self.report(run_id="incorrect-run-id"),
            self.report(scenario="wpc"), self.report(trial=2),
            self.report(status="sensitive output/cookie.txt"),
            self.report(setup_ms=True), self.report(total_ms=20),
            self.report(token_source="SECRET_PO_TOKEN"),
            self.report(protocol=2), self.report(unexpected="some data"),
            self.report(worker_pid=0), self.report(worker_pid=True),
        ]
        cases += [
            self.hello(pid=27248, run_id="bad") + self.report(hello=False),
            self.hello(pid=3333) + self.report(hello=False),
        ]
        for raw in cases:
            with self.subTest(case=raw[-60:]):
                self.assertIsNone(RUNNER.parse_worker_report(raw, "bgutil", 1, RUN_ID))

    def test_parse_hello_can_be_used_from_timeout_partial_bytes(self):
        self.assertEqual(RUNNER.parse_worker_hello(self.hello().encode(), RUN_ID), 27248)
        self.assertEqual(RUNNER.parse_worker_hello(self.hello(), RUN_ID), 27248)
        self.assertEqual(RUNNER.parse_worker_hello(self.hello(), "f" * 32), 0)
        self.assertEqual(RUNNER.parse_worker_hello(self.hello() * 2, RUN_ID), 0)
        self.assertEqual(RUNNER.parse_worker_hello(b"invalid", RUN_ID), 0)
        self.assertEqual(RUNNER.parse_worker_hello(None, RUN_ID), 0)

    def test_parent_invokes_fresh_interpreter_and_captures_all_output(self):
        fake = FakeWorker(self.report(pid=27248), pid=21180)
        with patch.object(RUNNER.subprocess, "Popen", return_value=fake) as popen:
            actual = RUNNER.run_isolated("bgutil-first", "bgutil", 1, "https://www.youtube.com/watch?v=example")
        self.assertEqual(actual.status, "ok")
        self.assertEqual(actual.worker_pid, 27248)
        self.assertEqual(actual.launcher_pid, 21180)
        args = popen.call_args.args[0]
        self.assertEqual(args[0], sys.executable)
        self.assertIn("--_worker", args)
        self.assertIn("--_scenario", args)
        self.assertTrue(popen.call_args.kwargs["stdout"] == subprocess.PIPE)
        self.assertTrue(popen.call_args.kwargs["stderr"] == subprocess.PIPE)
        self.assertEqual(popen.call_args.kwargs["env"][RUNNER._RUN_ID_ENV], RUN_ID)
        self.assertEqual(fake.timeout_seen, 180)
        self.assertNotIn("SENSITIVE_OTHER_STDERR", repr(actual))

    def test_untrusted_protocol_output_is_never_displayed(self):
        fake = FakeWorker(self.report() + self.report() + "SENSITIVE_FAKE_PO_TOKEN\n")
        output = StringIO()
        with patch.object(RUNNER.subprocess, "Popen", return_value=fake), redirect_stdout(output):
            result = RUNNER.run_isolated("bgutil-first", "bgutil", 1, "https://www.youtube.com/watch?v=example")
        self.assertEqual(result.status, "worker-protocol-error")
        self.assertEqual(result.worker_pid, 0)
        self.assertEqual(result.launcher_pid, 18248)
        self.assertNotIn("SENSITIVE", output.getvalue())
        self.assertNotIn("SENSITIVE", repr(result))

    def test_timeout_kills_real_worker_after_venv_launcher_exits(self):
        fake = FakeWorker(self.report(), pid=21180)
        def bad_communicate(timeout=None):
            raise subprocess.TimeoutExpired("SECRET command", 180, output=self.hello(pid=27248).encode())
        fake.communicate = bad_communicate
        with (patch.object(RUNNER.subprocess, "Popen", return_value=fake),
              patch.object(RUNNER, "_kill_worker_tree") as kill):
            out = RUNNER.run_isolated("wpc-first", "wpc", 2, "https://www.youtube.com/watch?v=example")
        self.assertEqual(out.status, "worker-timeout")
        self.assertEqual(out.worker_pid, 27248)
        self.assertEqual(out.launcher_pid, 21180)
        kill.assert_called_once_with(fake, 27248)

    def test_timeout_without_hello_uses_safe_unknown_worker_pid(self):
        fake = FakeWorker("", pid=21180)
        def bad_communicate(timeout=None):
            raise subprocess.TimeoutExpired("SECRET", 180, output=b"SECRET_RAW_BYTES")
        fake.communicate = bad_communicate
        with (patch.object(RUNNER.subprocess, "Popen", return_value=fake),
              patch.object(RUNNER, "_kill_worker_tree") as kill):
            out = RUNNER.run_isolated("wpc-first", "wpc", 2, "https://www.youtube.com/watch?v=example")
        self.assertEqual(out.worker_pid, 0)
        kill.assert_called_once_with(fake, 0)
        self.assertNotIn("SECRET", repr(out))

    def test_windows_timeout_cleanup_targets_real_worker_even_if_launcher_exited(self):
        launcher = FakeWorker("", code=0, pid=21180)
        with (patch.object(RUNNER.os, "name", "nt"),
              patch.object(RUNNER.subprocess, "run") as taskkill):
            RUNNER._kill_worker_tree(launcher, 27248)
        taskkill.assert_called_once()
        self.assertEqual(
            taskkill.call_args.args[0],
            ["taskkill", "/PID", "27248", "/T", "/F"],
        )
        self.assertTrue(taskkill.call_args.kwargs["capture_output"])

    def test_failure_status_survives_windows_redirector_zero_exit(self):
        failure = FakeWorker(self.report(status="bgutil-startup-timeout", setup_ms=18000,
                                         extract_ms=0, total_ms=18000), code=0)
        with patch.object(RUNNER.subprocess, "Popen", return_value=failure):
            result = RUNNER.run_isolated("bgutil-first", "bgutil", 1, "https://www.youtube.com/watch?v=x")
        self.assertEqual(result.status, "bgutil-startup-timeout")
        self.assertEqual(result.worker_pid, 27248)
        mismatch = FakeWorker(self.report(), code=1)
        with patch.object(RUNNER.subprocess, "Popen", return_value=mismatch):
            result = RUNNER.run_isolated("bgutil-first", "bgutil", 1, "https://www.youtube.com/watch?v=x")
        self.assertEqual(result.status, "worker-exit-mismatch")

    def test_worker_sends_hello_then_safe_result_and_stops_server(self):
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
            patch.dict(os.environ, {RUNNER._RUN_ID_ENV: RUN_ID}),
            patch.object(RUNNER.BASE_BENCH, "run_trial", return_value=expected),
            redirect_stdout(output),
        ):
            code = RUNNER._worker_main("bgutil", 1, "https://www.youtube.com/watch?v=x")
        self.assertEqual(code, 0)
        self.assertEqual(stopped, [True])
        self.assertEqual(RUNNER.parse_worker_hello(output.getvalue(), RUN_ID), os.getpid())
        self.assertIsNotNone(RUNNER.parse_worker_report(output.getvalue(), "bgutil", 1, RUN_ID))
        self.assertEqual(output.getvalue().count("\n"), 2)

    def test_worker_requires_parent_correlation_id(self):
        with patch.dict(os.environ, {RUNNER._RUN_ID_ENV: "INVALID"}):
            output = StringIO()
            with redirect_stdout(output):
                result = RUNNER._worker_main("bgutil", 1, "https://www.youtube.com/watch?v=x")
        self.assertEqual(result, 2)
        self.assertEqual(output.getvalue(), "")

    def test_main_completes_both_orders_even_on_one_failure(self):
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
                                         2, 4, 6, 9, "none", False, scenario == "bgutil", True,
                                         10000 + len(steps))
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
        self.assertEqual([x[1]["launcher_pid"] for x in log], [10001, 10002, 10003, 10004])

    def test_summary_prints_actual_worker_and_launcher_pids(self):
        result = RUNNER._empty_result("wpc-first", "wpc", 2, "worker-timeout",
                                      worker_pid=330, launcher_pid=44, wall_ms=123)
        output = StringIO()
        with redirect_stdout(output):
            RUNNER.print_summary([result])
        self.assertIn("worker-timeout", output.getvalue())
        self.assertIn("Launcher", output.getvalue())
        self.assertNotIn("https://", output.getvalue())


if __name__ == "__main__":
    unittest.main()
