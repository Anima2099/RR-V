"""Offline tests for breadth, privacy and fallback of wide startup survey."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

SOURCE = Path(__file__).parent / "manual" / "bgutil_wide_survey.py"
SPEC = importlib.util.spec_from_file_location("rrv_bgutil_wide_survey", SOURCE)
assert SPEC is not None and SPEC.loader is not None
SURVEY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SURVEY
SPEC.loader.exec_module(SURVEY)


class WideSurveyTests(unittest.TestCase):
    def test_module_coverage_is_diverse(self):
        names = [n for n, _ in SURVEY.MODULES]
        for name in ("canvas", "jsdom", "youtubei", "express", "proxy-agent", "axios"):
            self.assertIn(name, names)
        self.assertEqual(len(names), len(set(names)))

    def test_stdout_never_exposed_and_only_marker_allows_success(self):
        program = "print('SECRET_TOKEN');print('" + SURVEY._MARKER + "')"
        stream = StringIO()
        with redirect_stdout(stream):
            r = SURVEY.subprocess_probe("runtime", [sys.executable, "-c", program], Path.cwd(), os.environ.copy())
        self.assertEqual(r.status, "ok")
        self.assertNotIn("SECRET", repr(r))
        self.assertEqual(stream.getvalue(), "")
        bad = SURVEY.subprocess_probe("runtime", [sys.executable, "-c", "print('no')"], Path.cwd(), os.environ.copy())
        self.assertEqual(bad.status, "failed")

    def test_subprocess_timeout_is_bounded(self):
        # A Windows venv python.exe can be a redirector; a genuine sleeping
        # Python child is not safe to kill by launcher PID alone in a unit test.
        class FakeProcess:
            returncode = None
            def __init__(self):
                self.killed = False
            def communicate(self, input=None, timeout=None):
                if not self.killed:
                    raise subprocess.TimeoutExpired("secret path", timeout, output=b"TOKEN")
                return "", ""
            def kill(self):
                self.killed = True
        fake = FakeProcess()
        with (
            patch.object(SURVEY.subprocess, "Popen", return_value=fake),
            patch.object(SURVEY, "windows_process_metrics", return_value=(-1, -1)),
        ):
            r = SURVEY.subprocess_probe("runtime", ["deno.exe"],
                                        Path.cwd(), os.environ.copy(), timeout=.15)
        self.assertEqual(r.status, "timeout")
        self.assertTrue(fake.killed)
        self.assertNotIn("TOKEN", repr(r))

    def test_launch_failure_does_not_leak_path(self):
        r = SURVEY.subprocess_probe("runtime", ["/nonexistent/RRV_PRIVATE_DIR/deno"],
                                    Path.cwd(), os.environ.copy())
        self.assertEqual(r.status, "launch-error")
        self.assertNotIn("RRV_PRIVATE_DIR", repr(r))

    def test_import_graph_uses_pinned_repo_module_and_cached_only(self):
        boot = types.SimpleNamespace(_deno_env=lambda _: {"DENO_DIR": "private"},
                                     _module_stdin=lambda _: "import 'secret_private_path';")
        with patch.object(SURVEY, "subprocess_probe", return_value=SURVEY.Result("graph", "ok", 11)) as call:
            SURVEY.deno_probe("graph", Path("deno.exe"), Path("home"), boot)
        cmd = call.call_args.args[1]
        self.assertIn("--cached-only", cmd)
        self.assertNotIn("secret_private_path", str(cmd))
        self.assertEqual(call.call_args.args[3]["DENO_DIR"], "private")
        self.assertIn("secret_private_path", call.call_args.args[4])

    def test_dependency_command_contains_only_hardcoded_module_spec(self):
        boot = types.SimpleNamespace(_deno_env=lambda _: {}, _module_stdin=lambda _: "")
        with patch.object(SURVEY, "subprocess_probe", return_value=SURVEY.Result("canvas", "ok", 22)) as call:
            SURVEY.deno_probe("canvas", Path("deno.exe"), Path("home"), boot)
        self.assertNotIn("canvas", str(call.call_args.args[1]))
        self.assertIn("npm:canvas@3.2.3", call.call_args.args[4])
        with self.assertRaises(ValueError):
            SURVEY.deno_probe("unknown", Path("deno.exe"), Path("home"), boot)

    def test_runtime_probe_does_not_import_bgutils(self):
        boot = types.SimpleNamespace(_deno_env=lambda _: {}, _module_stdin=lambda _: "")
        with patch.object(SURVEY, "subprocess_probe", return_value=SURVEY.Result("runtime", "ok", 2)) as call:
            SURVEY.deno_probe("runtime", Path("deno.exe"), Path("home"), boot)
        self.assertEqual(call.call_args.args[1][1], "eval")
        self.assertIsNone(call.call_args.kwargs.get("code"))

    def test_snapshot_uses_boolean_proxy_state_only(self):
        with patch.dict(os.environ, {"HTTP_PROXY": "http://private-user:password@internal"}, clear=True):
            info = SURVEY.passive_system()
        self.assertEqual(info["proxy"], "present")
        self.assertNotIn("password", repr(info))

    def test_storage_snapshot_reads_only_whitelisted_files(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / "server" / "src").mkdir(parents=True)
            (home / "server" / "node_modules").mkdir()
            (home / "deno-cache").mkdir()
            for name in ("main.ts", "session_manager.ts"):
                (home / "server" / "src" / name).write_text("SENSITIVE_CONTENT")
            (home / "server" / "package.json").write_text("{}")
            result = SURVEY.storage_snapshot(home)
        self.assertEqual(result["sampled_files"], 3)
        self.assertEqual(result["node_modules"], "present")
        self.assertNotIn("SENSITIVE_CONTENT", repr(result))
        self.assertNotIn(temp, repr(result))

    def test_defender_probe_is_read_only_and_no_raw_output(self):
        if os.name != "nt":
            self.assertEqual(SURVEY.defender_snapshot(), "not-windows")
        self.assertNotIn("SECRET", SURVEY.defender_snapshot())

    def test_windows_process_counters_fallback_elsewhere(self):
        if os.name != "nt":
            self.assertEqual(SURVEY.windows_process_metrics(object()), (-1, -1))

    def test_summary_detects_cold_penalty_without_causal_claim(self):
        rows = [SURVEY.Result("graph", "ok", 30992, 1000),
                SURVEY.Result("graph-repeat", "ok", 2750),
                SURVEY.Result("canvas", "ok", 100)]
        flags = SURVEY.summarize(rows, {}, {}, "enabled")
        self.assertIn("cold-graph-penalty-observed", flags)
        self.assertIn("cold-process-low-cpu-time", flags)
        self.assertFalse(any("defender" in x for x in flags))

    def test_summary_flags_cpu_dominated_and_module_outlier(self):
        rows = [SURVEY.Result("graph", "ok", 22000, 18000),
                SURVEY.Result("canvas", "ok", 11000),
                SURVEY.Result("server", "late-ready", 27000)]
        flags = SURVEY.summarize(rows, {"free_memory_pct": 8}, {"free_disk_gb": 1, "drive": "network"}, "disabled")
        for expected in ("cold-process-high-cpu-time", "warm-module-outlier:canvas",
                         "server-exceeds-production-budget", "low-memory-at-start",
                         "low-disk-space", "nonlocal-or-removable-installation"):
            self.assertIn(expected, flags)

    def test_module_failures_do_not_assert_entire_server_failure(self):
        rows = [SURVEY.Result("jsdom", "failed", 120)]
        flags = SURVEY.summarize(rows, {}, {}, "unavailable")
        self.assertIn("one-or-more-diagnostic-stages-failed", flags)

    @staticmethod
    def fake_modules():
        fake_paths = types.ModuleType("app.paths")
        fake_paths.find_executable = lambda _: Path("deno.exe")
        srv = types.ModuleType("services.bgutil_http_service")
        srv.ENV_HOME = "RRV_BGUTIL_STAGE03_HOME"
        srv._validate_external_home = lambda _: True
        pkg = types.ModuleType("services")
        pkg.bgutil_http_service = srv
        log = MagicMock()
        diag = types.ModuleType("app.bgutil_diagnostics")
        diag.record_bgutil_diagnostic = log
        return {"app.paths": fake_paths, "services": pkg,
                "services.bgutil_http_service": srv, "app.bgutil_diagnostics": diag}, log

    def test_main_runs_broad_categories_in_one_call(self):
        modules, log = self.fake_modules()
        boot = types.SimpleNamespace(run_server_stage=lambda *_args, **_kw: types.SimpleNamespace(
            result="ready", elapsed_ms=1200, announced_ms=1100, ping_ms=1200))
        seen = []
        def fake_deno(stage, *_args, **_kw):
            seen.append(stage)
            return SURVEY.Result(stage, "ok", 150)
        with (patch.dict(sys.modules, modules),
              patch.dict(os.environ, {"RRV_BGUTIL_STAGE03_HOME": "fake"}),
              patch.object(SURVEY, "_load_boot", return_value=boot),
              patch.object(SURVEY, "passive_system", return_value={"uptime_min": 10, "proxy": "absent", "free_memory_pct": 30}),
              patch.object(SURVEY, "storage_snapshot", return_value={"drive": "fixed", "deno_cache": "present", "node_modules": "present", "sample_read_ms": 1, "free_disk_gb": 100, "reparse_path": "absent"}),
              patch.object(SURVEY, "defender_snapshot", return_value="enabled"),
              patch.object(SURVEY, "mark_of_web", return_value="absent"),
              patch.object(SURVEY, "deno_probe", side_effect=fake_deno),
              redirect_stdout(StringIO()) as out):
            result = SURVEY.main(["--first", "graph"])
        self.assertEqual(result, 0)
        self.assertEqual(seen[:3], ["graph", "graph-repeat", "runtime"])
        self.assertIn("canvas", seen)
        self.assertEqual(log.call_count, 6 + len(SURVEY.MODULES))
        self.assertIn("WIDE SURVEY: COMPLETE", out.getvalue())

    def test_main_server_first_keeps_server_cold(self):
        modules, _ = self.fake_modules()
        records = []
        boot = types.SimpleNamespace(run_server_stage=lambda _srv, _home, _deno, stage, **_kw: (
            records.append(stage) or types.SimpleNamespace(result="ready", elapsed_ms=20, announced_ms=20, ping_ms=20)))
        with (patch.dict(sys.modules, modules),
              patch.dict(os.environ, {"RRV_BGUTIL_STAGE03_HOME": "fake"}),
              patch.object(SURVEY, "_load_boot", return_value=boot),
              patch.object(SURVEY, "passive_system", return_value={"uptime_min": 5, "proxy": "absent", "free_memory_pct": 60}),
              patch.object(SURVEY, "storage_snapshot", return_value={"drive": "fixed", "deno_cache": "present", "node_modules": "present", "sample_read_ms": 1, "free_disk_gb": 100, "reparse_path": "absent"}),
              patch.object(SURVEY, "defender_snapshot", return_value="unknown"),
              patch.object(SURVEY, "mark_of_web", return_value="absent"),
              patch.object(SURVEY, "deno_probe", side_effect=lambda stage, *_a, **_k: SURVEY.Result(stage, "ok", 2)),
              redirect_stdout(StringIO()) as out):
            code = SURVEY.main(["--first", "server"])
        self.assertEqual(code, 0)
        self.assertEqual(records, ["server", "server-repeat"])
        self.assertIn("Checking server...", out.getvalue().splitlines()[3])

    def test_main_requires_explicit_opt_in(self):
        modules, _ = self.fake_modules()
        with (patch.dict(sys.modules, modules),
              patch.dict(os.environ, {"RRV_BGUTIL_STAGE03_HOME": ""}),
              redirect_stdout(StringIO()) as stdout):
            code = SURVEY.main([])
        self.assertEqual(code, 2)
        self.assertIn("NOT RUN", stdout.getvalue())

    def test_main_does_not_log_private_exception(self):
        modules, _ = self.fake_modules()
        boot = types.SimpleNamespace(run_server_stage=lambda *_a, **_k: (_ for _ in ()).throw(OSError("PRIVATE USER PATH")))
        with (patch.dict(sys.modules, modules),
              patch.dict(os.environ, {"RRV_BGUTIL_STAGE03_HOME": "fake"}),
              patch.object(SURVEY, "_load_boot", return_value=boot),
              patch.object(SURVEY, "deno_probe", side_effect=lambda stage, *_a, **_k: SURVEY.Result(stage, "ok", 1)),
              patch.object(SURVEY, "passive_system", return_value={"uptime_min": -1, "proxy": "absent", "free_memory_pct": -1}),
              patch.object(SURVEY, "storage_snapshot", return_value={"drive": "unknown", "deno_cache": "missing", "node_modules": "missing", "sample_read_ms": 0, "free_disk_gb": -1, "reparse_path": "unknown"}),
              patch.object(SURVEY, "defender_snapshot", return_value="unknown"),
              patch.object(SURVEY, "mark_of_web", return_value="unknown"),
              redirect_stdout(StringIO()) as out):
            result = SURVEY.main([])
        self.assertEqual(result, 1)
        self.assertNotIn("PRIVATE", out.getvalue())


if __name__ == "__main__":
    unittest.main()
