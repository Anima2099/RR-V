"""Stage03 P3 mock tests; no Deno compilation, network or token requests."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

FILE = Path(__file__).parent / "manual" / "bgutil_compile_probe.py"
SPEC = importlib.util.spec_from_file_location("rrv_bgutil_compile_probe", FILE)
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROBE
SPEC.loader.exec_module(PROBE)


class FakeRunningProcess:
    def __init__(self):
        self.stopped = False
        self.terminated = False
        self.killed = False

    def poll(self):
        return 0 if self.stopped else None

    def terminate(self):
        self.terminated = True
        self.stopped = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True
        self.stopped = True


class CompileProbeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "bgutil-stage03-lean-experiment"
        self.target = self.root / "bgutil-stage03-compiled-bundled"
        self.deno = self.root / "deno.exe"
        self.deno.write_bytes(b"fake Deno")
        (self.source / "server" / "node_modules").mkdir(parents=True)
        (self.source / "server" / "src").mkdir()
        (self.source / "server" / "src" / "main.ts").write_text("export {}", encoding="utf-8")
        (self.source / "server" / "node_modules" / "source-keep.txt").write_text("unchanged")
        (self.source / PROBE.LEAN_MARKER).write_text(json.dumps({
            "schema": 1,
            "source_commit": PROBE.bgutil.SOURCE_COMMIT,
            "method": "prod-entrypoint-frozen",
        }), encoding="utf-8")
        self.patch_valid = patch.object(PROBE.bgutil, "_validate_external_home", return_value=True)
        self.patch_valid.start()
        self.addCleanup(self.patch_valid.stop)
        self.patch_space = patch.object(PROBE.shutil, "disk_usage", return_value=types.SimpleNamespace(free=10**10))
        self.patch_space.start()
        self.addCleanup(self.patch_space.stop)

    def fake_compile(self, command, **kwargs):
        self.assertIn("--bundle", command)
        self.assertIn("--cached-only", command)
        self.assertIn("--frozen-lockfile", command)
        self.assertIn("--node-modules-dir=manual", command)
        self.assertNotIn("--reload", command)
        self.assertNotIn("--allow-all", command)
        self.assertEqual(kwargs["stdin"], PROBE.subprocess.DEVNULL)
        self.assertEqual(kwargs["stdout"], PROBE.subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], PROBE.subprocess.DEVNULL)
        self.assertEqual(kwargs["cwd"], str(self.source / "server" / "node_modules"))
        self.assertEqual(kwargs["env"]["DENO_DIR"], str(self.source / "deno-cache"))
        output = Path(command[command.index("--output") + 1])
        self.assertEqual(output, self.target / PROBE.binary_name("bundled"))
        output.write_bytes(b"compiled candidate")
        return types.SimpleNamespace(returncode=0)

    def build_ok(self):
        with patch.object(PROBE.subprocess, "run", side_effect=self.fake_compile):
            return PROBE.build(self.source, self.target, self.deno, "bundled")

    def test_build_creates_isolated_verified_binary(self):
        self.assertEqual(self.build_ok(), "built")
        self.assertTrue(PROBE._looks_prepared(self.target, "bundled", hash_file=True))
        self.assertEqual((self.source / "server" / "node_modules" / "source-keep.txt").read_text(), "unchanged")
        self.assertEqual(json.loads((self.target / PROBE.MARKER_NAME).read_text())["variant"], "bundled")

    def test_already_built_does_not_compile_twice(self):
        self.assertEqual(self.build_ok(), "built")
        with patch.object(PROBE.subprocess, "run") as execute:
            self.assertEqual(PROBE.build(self.source, self.target, self.deno, "bundled"), "already-built")
            execute.assert_not_called()

    def test_existing_unverified_dir_is_not_overwritten(self):
        self.target.mkdir()
        (self.target / "user.txt").write_text("preserve")
        with patch.object(PROBE.subprocess, "run") as execute:
            status = PROBE.build(self.source, self.target, self.deno, "bundled")
        self.assertEqual(status, "target-exists-unverified")
        self.assertEqual((self.target / "user.txt").read_text(), "preserve")
        execute.assert_not_called()

    def test_invalid_lean_marker_prevents_build(self):
        (self.source / PROBE.LEAN_MARKER).write_text("{}")
        self.assertEqual(PROBE.build(self.source, self.target, self.deno, "bundled"), "lean-source-unverified")
        self.assertFalse(self.target.exists())

    def test_invalid_external_source_prevents_build(self):
        with patch.object(PROBE.bgutil, "_validate_external_home", return_value=False):
            self.assertEqual(PROBE.build(self.source, self.target, self.deno, "bundled"), "lean-source-unverified")
        self.assertFalse(self.target.exists())

    def test_missing_deno_is_rejected(self):
        self.assertEqual(PROBE.build(self.source, self.target, None, "bundled"), "deno-missing")
        self.assertFalse(self.target.exists())

    def test_failed_compile_removes_only_new_candidate(self):
        with patch.object(PROBE.subprocess, "run", return_value=types.SimpleNamespace(returncode=1)):
            status = PROBE.build(self.source, self.target, self.deno, "bundled")
        self.assertEqual(status, "compile-failed")
        self.assertFalse(self.target.exists())
        self.assertTrue((self.source / "server" / "src" / "main.ts").exists())

    def test_timeout_has_only_safe_status_and_cleans(self):
        err = subprocess.TimeoutExpired("PRIVATE_PATH", 360, output=b"SECRET")
        with patch.object(PROBE.subprocess, "run", side_effect=err):
            status = PROBE.build(self.source, self.target, self.deno, "bundled")
        self.assertEqual(status, "compile-timeout")
        self.assertNotIn("SECRET", status)
        self.assertFalse(self.target.exists())

    def test_source_target_overlap_is_rejected(self):
        self.assertEqual(PROBE.build(self.source, self.source, self.deno, "bundled"), "source-target-overlap")
        self.assertEqual(PROBE.build(self.source, self.source / "build", self.deno, "bundled"), "source-target-overlap")

    def test_insufficient_free_space_is_safe(self):
        with patch.object(PROBE.shutil, "disk_usage", return_value=types.SimpleNamespace(free=5)):
            self.assertEqual(PROBE.build(self.source, self.target, self.deno, "bundled"), "insufficient-free-space")
        self.assertFalse(self.target.exists())

    def test_extract_variant_is_explicit_only(self):
        basic = PROBE.compile_command(self.deno, self.target / "app.exe", "bundled")
        alternative = PROBE.compile_command(self.deno, self.target / "app.exe", "extracted")
        self.assertNotIn("--self-extracting", basic)
        self.assertIn("--self-extracting", alternative)
        self.assertEqual(basic[-1], "../src/main.ts")
        self.assertEqual(alternative[-1], "../src/main.ts")
        with self.assertRaises(ValueError):
            PROBE.compile_command(self.deno, self.target / "app.exe", "broken")

    def test_paths_do_not_refer_to_original_provider(self):
        src, dst = PROBE.paths_for(self.root, "bundled")
        self.assertEqual(src, self.root / "RR-V" / "diagnostics" / "bgutil-stage03-lean-experiment")
        self.assertEqual(dst, self.root / "RR-V" / "diagnostics" / "bgutil-stage03-compiled-bundled")
        self.assertNotIn("bgutil-stage03-external", str(src) + str(dst))

    def test_probe_does_not_hash_binary_before_timing(self):
        self.assertEqual(self.build_ok(), "built")
        fake = FakeRunningProcess()
        with patch.object(PROBE, "_compiled_marker", side_effect=AssertionError("would warm binary")):
            with patch.object(PROBE, "_allocate_port", return_value=50321):
                with patch.object(PROBE, "_ping", return_value=True):
                    with patch.object(PROBE.subprocess, "Popen", return_value=fake) as popen:
                        status, elapsed, calls = PROBE.probe(self.target, "bundled", timeout=1.0)
        self.assertEqual(status, "ready")
        self.assertGreaterEqual(elapsed, 0)
        self.assertEqual(calls, 1)
        self.assertTrue(fake.terminated)
        self.assertFalse(fake.killed)
        self.assertEqual(popen.call_args.kwargs["cwd"], str(self.target))
        self.assertEqual(popen.call_args.kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.DEVNULL)
        self.assertEqual(popen.call_args.args[0][-4:-2], ["--host", "127.0.0.1"])

    def test_probe_fails_cleanly_if_compiled_process_exits(self):
        self.assertEqual(self.build_ok(), "built")
        fake = FakeRunningProcess()
        fake.stopped = True
        with patch.object(PROBE, "_allocate_port", return_value=50321):
            with patch.object(PROBE.subprocess, "Popen", return_value=fake):
                status, ms, calls = PROBE.probe(self.target, "bundled", timeout=1)
        self.assertEqual(status, "compiled-exited-before-ready:code=0")
        self.assertEqual(calls, 0)

    def test_probe_returns_late_ready_without_real_waiting(self):
        self.assertEqual(self.build_ok(), "built")
        fake = FakeRunningProcess()
        with patch.object(PROBE, "PRODUCTION_FIRST_BUDGET_MS", -1):
            with patch.object(PROBE, "_allocate_port", return_value=50321):
                with patch.object(PROBE, "_ping", return_value=True):
                    with patch.object(PROBE.subprocess, "Popen", return_value=fake):
                        status, *_ = PROBE.probe(self.target, "bundled", timeout=1)
        self.assertEqual(status, "late-ready")
        self.assertTrue(fake.terminated)

    def test_hash_verification_catches_tampered_binary(self):
        self.assertEqual(self.build_ok(), "built")
        binary = self.target / PROBE.binary_name("bundled")
        binary.write_bytes(b"compiled candidatE")
        self.assertTrue(PROBE._looks_prepared(self.target, "bundled", hash_file=False))
        self.assertFalse(PROBE._looks_prepared(self.target, "bundled", hash_file=True))

    def test_probe_rejects_unavailable_local_port_without_launch(self):
        self.assertEqual(self.build_ok(), "built")
        with patch.object(PROBE, "_allocate_port", side_effect=OSError("SECRET")):
            with patch.object(PROBE.subprocess, "Popen") as popen:
                self.assertEqual(PROBE.probe(self.target, "bundled"), ("local-port-unavailable", 0, 0))
                popen.assert_not_called()

    def test_corrupt_marker_list_is_rejected(self):
        self.assertEqual(self.build_ok(), "built")
        (self.target / PROBE.MARKER_NAME).write_text("[]", encoding="utf-8")
        self.assertFalse(PROBE._looks_prepared(self.target, "bundled"))

    def test_probe_not_built_is_noop(self):
        with patch.object(PROBE.subprocess, "Popen") as popen:
            self.assertEqual(PROBE.probe(self.target, "bundled"), ("not-built-or-invalid", 0, 0))
            popen.assert_not_called()

    def test_proxy_configuration_is_not_honored_for_local_ping(self):
        class FakeReply:
            status = 200
            def read(self, _size):
                return json.dumps({"version": PROBE.bgutil.PROVIDER_VERSION}).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False
        class FakeOpener:
            def open(self, request, timeout):
                self.request = request
                self.timeout = timeout
                return FakeReply()
        op = FakeOpener()
        with patch.object(PROBE, "build_opener", return_value=op) as opener:
            self.assertTrue(PROBE._ping("http://127.0.0.1:50321"))
        self.assertEqual(opener.call_args.args[0].proxies, {})
        self.assertEqual(op.timeout, 0.4)
        self.assertEqual(op.request.full_url, "http://127.0.0.1:50321/ping")


if __name__ == "__main__":
    unittest.main()
