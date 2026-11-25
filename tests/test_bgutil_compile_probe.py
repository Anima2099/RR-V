"""Stage03 P3 mock tests; no Deno compilation, network or token requests."""
from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
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
    def __init__(self, stderr=b"", returncode=0):
        self.stopped = False
        self.terminated = False
        self.killed = False
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode

    def poll(self):
        return self.returncode if self.stopped else None

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
        (self.source / "deno-cache").mkdir()
        (self.source / "deno-cache" / "source-keep.txt").write_text("unchanged")
        self.cache = self.root / PROBE.BUNDLER_CACHE_NAME
        (self.cache / "deno-cache").mkdir(parents=True)
        (self.cache / PROBE.BUNDLER_MARKER).write_text(PROBE.bgutil.SOURCE_COMMIT, encoding="ascii")
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
        self.assertEqual(kwargs["stderr"], PROBE.subprocess.PIPE)
        self.assertEqual(kwargs["cwd"], str(self.source / "server" / "node_modules"))
        self.assertEqual(kwargs["env"]["DENO_DIR"], str(self.cache / "deno-cache"))
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

    def test_bundler_preparation_copies_cache_and_only_bundles_local_fixture(self):
        (self.cache / PROBE.BUNDLER_MARKER).unlink()
        (self.cache / "deno-cache").rmdir()
        self.cache.rmdir()

        def bundle(command, *, cwd, env, **kwargs):
            self.assertEqual(command, [str(self.deno), "bundle", "--no-config", "--no-lock",
                                       "--node-modules-dir=none", "main.ts"])
            self.assertEqual(env["DENO_DIR"], str(self.cache / "deno-cache"))
            self.assertEqual((cwd / "main.ts").read_text(), "export const ready = true;\n")
            cached = self.cache / "deno-cache" / "source-keep.txt"
            self.assertEqual(cached.read_text(), "unchanged")
            cached.write_text("only in P3")
            return subprocess.CompletedProcess(command, 0)

        with patch.object(PROBE.subprocess, "run", side_effect=bundle) as execute:
            self.assertEqual(PROBE.prepare_bundler(self.source, self.cache, self.deno), "prepared")
            self.assertEqual(PROBE.prepare_bundler(self.source, self.cache, self.deno), "already-prepared")
            execute.assert_called_once()
        self.assertEqual((self.source / "deno-cache" / "source-keep.txt").read_text(), "unchanged")
        self.assertEqual(self.build_ok(), "built")

    def test_bundler_failure_cleans_new_cache_and_masks_error(self):
        cache = self.root / "new-cache"
        failure = subprocess.CompletedProcess([], 1, stderr=b"failed to download https://secret.example/x")
        with patch.object(PROBE.subprocess, "run", return_value=failure):
            status = PROBE.prepare_bundler(self.source, cache, self.deno)
        self.assertEqual(status, "bundle-failed | exit_code=1 | reason=download-error")
        self.assertFalse(cache.exists())
        self.assertTrue((self.source / "deno-cache" / "source-keep.txt").is_file())

    def test_unprepared_cache_prevents_compile_and_is_not_overwritten(self):
        (self.cache / PROBE.BUNDLER_MARKER).unlink()
        with patch.object(PROBE.subprocess, "run") as execute:
            self.assertEqual(PROBE.build(self.source, self.target, self.deno, "bundled"), "bundler-not-prepared")
            self.assertEqual(PROBE.prepare_bundler(self.source, self.cache, self.deno), "cache-exists-unverified")
            execute.assert_not_called()
        self.assertTrue(self.cache.is_dir())
        self.assertFalse(self.target.exists())

    def test_failed_compile_removes_only_new_candidate(self):
        failure = subprocess.CompletedProcess([], 2, stderr=b"error: unexpected argument '--bundle' found")
        with patch.object(PROBE.subprocess, "run", return_value=failure):
            status = PROBE.build(self.source, self.target, self.deno, "bundled")
        self.assertEqual(status, "compile-failed | exit_code=2 | reason=unsupported-cli-option:--bundle")
        self.assertFalse(self.target.exists())
        self.assertTrue((self.source / "server" / "src" / "main.ts").exists())

    def test_build_cli_reports_exit_code_and_safe_reason_only(self):
        error = b"error: Specifier not found in cache: 'https://jsr.io/private/path?token=SECRET'\n"
        error += b"    at C:\\Users\\Private\\main.ts:1:1\n"
        failure = subprocess.CompletedProcess([], 1, stderr=error)
        output = io.StringIO()
        windows = types.SimpleNamespace(name="nt", environ={"LOCALAPPDATA": str(self.root)})
        with (
            patch.object(PROBE, "os", windows),
            patch.object(PROBE, "paths_for", return_value=(self.source, self.target)),
            patch.object(PROBE, "find_executable", return_value=self.deno),
            patch.object(PROBE.subprocess, "run", return_value=failure),
            redirect_stdout(output),
        ):
            self.assertEqual(PROBE.main(["--build"]), 1)
        self.assertEqual(output.getvalue().splitlines(), [
            "BGUTIL P3 BUILD: compile-failed | exit_code=1 | reason=dependency-cache-error"
            " | cache_ref=jsr.io | variant=bundled",
            "Original BgUtils and RR-V production runtime were not modified.",
        ])

    def test_cache_miss_reports_public_windows_bundler_package_without_version(self):
        stderr = (
            b"error: bundling failed\n"
            b"Caused by: Error getting response at https://private.example/token/SECRET: "
            b"An npm specifier not found in cache: \"@esbuild/win32-x64@0.25.5\", --cached-only is specified."
        )
        self.assertEqual(PROBE._cache_miss_reference(stderr, self.root / "missing.lock"), "npm:@esbuild/win32-x64")

    def test_cache_miss_only_identifies_packages_in_verified_public_lock(self):
        lockfile = self.root / "deno.lock"
        lock = b'{\n  "npm": {"@types/node@26.6.4": {}}\n}\n'
        lockfile.write_bytes(lock.replace(b"\n", b"\r\n"))
        known = b"error: npm package not found in cache: '@types/node@26.6.4/private'"
        private = b"error: npm package not found in cache: '@private/internal'"
        with patch.object(PROBE, "PUBLIC_LOCK_SHA256", hashlib.sha256(lock).hexdigest()):
            self.assertEqual(PROBE._cache_miss_reference(known, lockfile), "npm:@types/node")
            self.assertEqual(PROBE._cache_miss_reference(private, lockfile), "npm")
            lockfile.write_bytes(b'{"npm":{"@private/internal@1.0.0":{}}}')
            self.assertEqual(PROBE._cache_miss_reference(private, lockfile), "npm")
            self.assertEqual(PROBE._cache_miss_reference(known, lockfile), "npm")

    def test_cache_miss_hides_private_hosts_credentials_and_local_paths(self):
        for reference, expected in (
            (b"https://private.example/internal", "remote"),
            (b"https://jsr.io@private.example/internal", "remote"),
            (b"https://private:secret@jsr.io/internal", "remote"),
            (b"file:///C:/Users/Private/source.ts", "unavailable"),
            (b"C:\\Users\\Private\\main.ts", "unavailable"),
        ):
            with self.subTest(reference=reference):
                stderr = b"Specifier not found in cache: \"" + reference + b"\""
                self.assertEqual(PROBE._cache_miss_reference(stderr, self.root / "missing.lock"), expected)

    def test_compile_failure_uses_only_fixed_reasons(self):
        for stderr, expected in (
            (b"", "no-stderr"),
            (b"unexpected argument '--private-value' found", "unsupported-cli-option"),
            (b"The lockfile is out of date.", "lockfile-error"),
            (b"Access is denied. (os error 5)", "access-denied"),
            (b"Could not resolve './build/Release/canvas.node'", "native-addon-error"),
            (b"Failed to download https://example.invalid/", "download-error"),
            (b"Module not found 'file:///private/source.ts'", "module-resolution-error"),
            (b"unknown failure with private value \xff", "unclassified"),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(PROBE._compile_failure_reason(stderr), expected)

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
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.PIPE)
        self.assertEqual(popen.call_args.args[0][-4:-2], ["--host", "127.0.0.1"])

    def test_probe_fails_cleanly_if_compiled_process_exits(self):
        self.assertEqual(self.build_ok(), "built")
        fake = FakeRunningProcess()
        fake.stopped = True
        with patch.object(PROBE, "_allocate_port", return_value=50321):
            with patch.object(PROBE.subprocess, "Popen", return_value=fake):
                status, ms, calls = PROBE.probe(self.target, "bundled", timeout=1)
        self.assertEqual(status, "compiled-exited-before-ready:code=0 | reason=no-stderr")
        self.assertEqual(calls, 0)

    def test_probe_reports_only_safe_startup_reason(self):
        self.assertEqual(self.build_ok(), "built")
        # Split the error across reads and include more than the retained tail.
        stderr = b"x" * (32 * 1024 + 1020)
        stderr += b"ERR_DLOPEN_FAILED loading C:\\Users\\Private\\canvas.node\nhttps://private.example/?token=SECRET"
        fake = FakeRunningProcess(stderr, returncode=1)
        fake.stopped = True
        output = io.StringIO()
        windows = types.SimpleNamespace(name="nt", environ={"LOCALAPPDATA": str(self.root)})
        with (
            patch.object(PROBE, "os", windows),
            patch.object(PROBE, "paths_for", return_value=(self.source, self.target)),
            patch.object(PROBE, "_allocate_port", return_value=50321),
            patch.object(PROBE.subprocess, "Popen", return_value=fake),
            redirect_stdout(output),
        ):
            self.assertEqual(PROBE.main(["--probe"]), 1)
        status = output.getvalue().splitlines()[0]
        self.assertRegex(status, r"^BGUTIL P3 PROBE: compiled-exited-before-ready:code=1"
                                 r" \| reason=native-addon-error \| variant=bundled"
                                 r" \| elapsed_ms=\d+ \| ping_attempts=0$")
        self.assertTrue(fake.stderr.closed)

    def test_probe_classifies_known_startup_errors(self):
        for stderr, reason in (
            (b"Error: listen EADDRINUSE", "listen-error"),
            (b"NotCapable: Requires ffi access", "permission-error"),
            (b'Dynamic require of "path" is not supported', "module-format-error"),
            (b"Error: Cannot find module 'canvas'", "module-resolution-error"),
            (b"NotFound: The system cannot find the path specified. (os error 3)", "file-not-found"),
            (b"unknown error", "unclassified"),
        ):
            with self.subTest(reason=reason):
                self.assertEqual(PROBE._probe_failure_reason(stderr), reason)

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
