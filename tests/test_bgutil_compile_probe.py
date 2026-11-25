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
    def __init__(self, stderr=b"", returncode=0, stdout=None):
        self.stopped = False
        self.terminated = False
        self.killed = False
        self.stderr = io.BytesIO(stderr)
        self.stdout = io.BytesIO(stdout) if stdout is not None else None
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

    def test_comparison_runs_unbundled_build_and_probe_in_one_report(self):
        _, target = PROBE.paths_for(self.root, "unbundled")
        self.assertNotEqual(target.name, self.target.name)
        target = self.root / target.name
        lock = {"specifiers": {"npm:jsdom@^29.1.1": "29.1.1_canvas@3.2.3", "npm:canvas@^3.2.3": "3.2.3"}}
        (self.source / "server" / "deno.lock").write_text(json.dumps(lock), encoding="utf-8")

        def execute(command, **kwargs):
            if command[0] == "git":
                return subprocess.CompletedProcess(command, 0, stdout=b"a" * 40 + b"\r\n")
            if command[1] == "--version":
                return subprocess.CompletedProcess(command, 0, stdout=b"deno 2.9.8\r\n")
            self.assertEqual(kwargs["env"]["DENO_DIR"], str(self.cache / "deno-cache"))
            binary = target / PROBE.binary_name("unbundled")
            bundled = PROBE.compile_command(self.deno, binary, "bundled")
            bundled.remove("--bundle")
            self.assertEqual(command, bundled)
            binary.write_bytes(b"candidate")
            return subprocess.CompletedProcess(command, 0, stdout=b"compiler output", stderr=b"compiler warning")

        fake = FakeRunningProcess(
            b'TypeError: failed\n    at file:///C:/Users/Private/AppData/module.js:10:5\n'
            b'Authorization: Bearer auth-secret\nCookie: sid=cookie-secret\n'
            b'{"password":"a \\"SECRET\\" value","authorization":"Bearer json-secret"}\n'
            b'https://user:url-secret@example.com/?access_token=query-secret',
            1, b"startup output",
        )
        fake.stopped = True
        windows = types.SimpleNamespace(name="nt", environ={"LOCALAPPDATA": str(self.root), "USERPROFILE": r"C:\Users\Private"})
        with (
            patch.object(PROBE, "os", windows),
            patch.object(PROBE, "paths_for", return_value=(self.source, target)) as paths,
            patch.object(PROBE, "find_executable", return_value=self.deno),
            patch.object(PROBE.subprocess, "run", side_effect=execute),
            patch.object(PROBE.subprocess, "Popen", return_value=fake),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(PROBE.main(["--compare"]), 1)
        paths.assert_called_once_with(self.root, "unbundled")
        (report,) = self.root.glob("bgutil-p3-compare-*.log")
        self.assertIn(report.name, output.getvalue())
        log = report.read_text(encoding="utf-8")
        for detail in ("jsdom=29.1.1", "canvas=3.2.3", "deno=2.9.8", "git_commit=" + "a" * 40,
                       "candidate_bytes=9", "compiler output", "compiler warning", "startup output",
                       "TypeError: failed", "AppData/module.js:10:5", "process exited before readiness"):
            self.assertIn(detail, log)
        for secret in ("Private", "auth-secret", "cookie-secret", "SECRET", "json-secret", "url-secret", "query-secret"):
            self.assertNotIn(secret, log)

    def test_comparison_reports_build_failure_without_starting_probe(self):
        target = self.root / "bgutil-stage03-compiled-unbundled"
        failure = subprocess.CompletedProcess([], 1, stdout=b"build progress", stderr=b"compiler broke")
        with (
            patch.object(PROBE, "_comparison_metadata", return_value="metadata\n"),
            patch.object(PROBE.subprocess, "run", return_value=failure),
            patch.object(PROBE.subprocess, "Popen") as popen,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(PROBE.compare_unbundled(self.source, target, self.deno), 1)
        popen.assert_not_called()
        (report,) = self.root.glob("bgutil-p3-compare-*.log")
        log = report.read_text(encoding="utf-8")
        self.assertIn("probe=skipped-build-failed", log)
        self.assertIn("compiler broke", log)
        self.assertIn("build progress", log)

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
                with patch.object(PROBE, "_ping_status", return_value="ready"):
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
        self.assertFalse(list(self.root.glob("bgutil-p3-probe-*.log")))

    def test_verbose_probe_keeps_detailed_output_local(self):
        self.assertEqual(self.build_ok(), "built")
        fake = FakeRunningProcess(b"TypeError: private error\n    at first stack frame\n", 1, b"startup output\n")
        output = io.StringIO()
        windows = types.SimpleNamespace(name="nt", environ={"LOCALAPPDATA": str(self.root)})

        def ping(_url):
            fake.stopped = True
            return "connection-refused"

        with (
            patch.object(PROBE, "os", windows),
            patch.object(PROBE, "paths_for", return_value=(self.source, self.target)),
            patch.object(PROBE, "_allocate_port", return_value=50321),
            patch.object(PROBE, "_ping_status", side_effect=ping),
            patch.object(PROBE.subprocess, "Popen", return_value=fake) as popen,
            redirect_stdout(output),
        ):
            self.assertEqual(PROBE.main(["--probe", "--verbose"]), 1)
        self.assertEqual(popen.call_args.kwargs["stdout"], subprocess.PIPE)
        (report,) = self.root.glob("bgutil-p3-probe-*.log")
        self.assertIn(report.name, output.getvalue())
        self.assertIn("reason=unclassified", output.getvalue())
        self.assertNotIn("private error", output.getvalue())
        log = report.read_text(encoding="utf-8")
        for detail in (
            "launch requested", "process launched", "ping 1 started", "ping 1: connection-refused",
            "first stdout bytes", "first stderr bytes", "process exited before readiness: code=1",
            "--- stdout", "startup output", "--- stderr", "TypeError: private error", "at first stack frame",
        ):
            self.assertIn(detail, log)

    def test_verbose_probe_limits_capture_and_counts_truncated_bytes(self):
        trace = PROBE._ProbeTrace()
        with patch.object(PROBE, "PROBE_LOG_STREAM_LIMIT", 8):
            trace.capture("stderr", b"123456")
            trace.capture("stderr", b"7890")
        log = trace.render("bundled", "compiled-timeout", 42, 1)
        self.assertIn("stderr (8 of 10 bytes captured)", log)
        self.assertIn("12345678\n", log)
        self.assertIn("stderr continuation (0 intervening bytes omitted) ---\n90", log)

    def test_live_token_check_uses_only_the_ready_bgutils_server(self):
        trace = ('[debug] PO Token Providers: bgutil:http-2.0.2\n'
                 '[pot:bgutil:http] Generating a gvs PO Token\n'
                 'PO Token response from "bgutil:http" provider: PoTokenResponse(po_token="secret")')
        ytdlp = self.root / "yt-dlp.exe"
        with patch.object(PROBE.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout=trace)) as run:
            result, signals = PROBE._verify_live_token(self.source, "http://127.0.0.1:50321", ytdlp, self.deno)
        self.assertEqual(result, "bgutil-token-confirmed")
        self.assertTrue(signals["bgutil_response"])
        self.assertFalse(signals["wpc_registered"])
        self.assertNotIn("secret", repr(signals))
        args = run.call_args.args[0]
        self.assertIn("--simulate", args)
        self.assertIn("--no-plugin-dirs", args)
        self.assertIn("youtubepot-bgutilhttp:base_url=http://127.0.0.1:50321", args)
        self.assertEqual(args.count("--plugin-dirs"), 1)

    def test_cold_check_times_readiness_before_token_and_tool_metadata(self):
        target = self.root / "bgutil-stage03-compiled-unbundled"
        target.mkdir()
        binary = target / PROBE.binary_name("unbundled")
        binary.write_bytes(b"candidate")
        (target / PROBE.MARKER_NAME).write_text(json.dumps(PROBE._compiled_marker("unbundled", binary)))
        for mode in ("compiled", "source"):
            with self.subTest(mode=mode):
                order = []
                clock = [0.0]
                fake = FakeRunningProcess()

                def token(_source, url, *_tools):
                    self.assertEqual(url, "http://127.0.0.1:50321")
                    self.assertFalse(fake.stopped)
                    clock[0] += 15
                    order.append("token")
                    return "bgutil-token-confirmed", {"bgutil_response": True}

                def metadata(*_args):
                    order.append("metadata")
                    self.assertTrue(fake.stopped)
                    return "tool_versions=fixed\n"

                with (
                    patch.object(PROBE, "_allocate_port", return_value=50321),
                    patch.object(PROBE, "_ping_status", return_value="ready"),
                    patch.object(PROBE, "_compiled_marker", side_effect=AssertionError("would pre-warm binary")),
                    patch.object(PROBE, "_verify_live_token", side_effect=token),
                    patch.object(PROBE, "_comparison_metadata", side_effect=metadata),
                    patch.object(PROBE.time, "monotonic", side_effect=lambda: clock[0]),
                    patch.object(PROBE.subprocess, "Popen", return_value=fake) as popen,
                    redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(PROBE.cold_check(self.source, target, mode, self.deno, self.deno), 0)
                self.assertEqual(order, ["token", "metadata"])
                command = popen.call_args.args[0]
                self.assertEqual(command[0], str(binary if mode == "compiled" else self.deno))
                if mode == "source":
                    self.assertEqual(popen.call_args.kwargs["env"]["DENO_DIR"], str(self.source / "deno-cache"))
                (report,) = self.root.glob(f"bgutil-p3-cold-{mode}-*.log")
                log = report.read_text(encoding="utf-8")
                self.assertIn("result=ready elapsed_ms=0", log)
                self.assertIn("+15000 ms yt-dlp token simulation finished", log)
                self.assertIn("token_elapsed_ms=15000", log)
                self.assertIn("token_bgutil_response=True", log)

    def test_cold_check_stops_recording_raw_output_before_live_token_request(self):
        trace = PROBE._ProbeTrace()
        trace.capture("stderr", b"startup only")
        fake = FakeRunningProcess()

        def token(_url):
            trace.capture("stderr", b"live-token-secret")
            self.assertFalse(fake.stopped)

        with (
            patch.object(PROBE, "_allocate_port", return_value=50321),
            patch.object(PROBE, "_ping_status", return_value="ready"),
            patch.object(PROBE.subprocess, "Popen", return_value=fake),
        ):
            status, elapsed, attempts = PROBE._probe_server([str(self.deno)], self.root, trace=trace, after_ready=token)
        log = trace.render("unbundled", status, elapsed, attempts)
        self.assertIn("startup only", log)
        self.assertNotIn("live-token-secret", log)

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
                with patch.object(PROBE, "_ping_status", return_value="ready"):
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
            self.assertEqual(PROBE._ping_status("http://127.0.0.1:50321"), "ready")
        self.assertEqual(opener.call_args.args[0].proxies, {})
        self.assertEqual(op.timeout, 0.4)
        self.assertEqual(op.request.full_url, "http://127.0.0.1:50321/ping")


if __name__ == "__main__":
    unittest.main()
