"""Safety and command-contract tests for the standalone lean BgUtils experiment."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import sys

SCRIPT = Path(__file__).parent / "manual" / "bgutil_lean_prepare.py"
SPEC = importlib.util.spec_from_file_location("rrv_bgutil_lean_prepare", SCRIPT)
assert SPEC and SPEC.loader
PREP = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREP
SPEC.loader.exec_module(PREP)


class LeanPrepTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "original"
        self.candidate = self.root / "diagnostics" / "lean"
        self.deno = self.root / "deno.exe"
        self.deno.write_bytes(b"placeholder")
        (self.source / "server" / "src").mkdir(parents=True)
        (self.source / "server" / "src" / "main.ts").write_text("export {};", encoding="utf-8")
        (self.source / "server" / "node_modules").mkdir()
        (self.source / "server" / "node_modules" / "old-module").write_bytes(b"keep")
        (self.source / "plugins").mkdir()
        for name in ("LICENSE", "plugin.zip", "rrv-stage03.json"):
            (self.source / name).write_text(name, encoding="utf-8")
        self.validation = patch.object(
            PREP.bgutil, "_validate_external_home",
            side_effect=lambda path: (
                (path / "server" / "src" / "main.ts").exists()
                and (path / "server" / "node_modules").is_dir()
                and (path / "plugin.zip").exists()
            ),
        )
        self.validation.start()
        self.addCleanup(self.validation.stop)

    def simulated_install(self, command, **kwargs):
        self.assertEqual(command[1:], [
            "install", "--frozen", "--prod", "--node-modules-dir=auto",
            "--allow-scripts=npm:canvas", "--entrypoint", "src/main.ts",
        ])
        self.assertNotIn("--reload", command)
        self.assertEqual(kwargs["stdin"], PREP.subprocess.DEVNULL)
        self.assertEqual(kwargs["stdout"], PREP.subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], PREP.subprocess.DEVNULL)
        self.assertEqual(kwargs["env"]["DENO_NO_PROMPT"], "1")
        installation = Path(kwargs["cwd"]).parent
        self.assertEqual(kwargs["env"]["DENO_DIR"], str(installation / "deno-cache"))
        self.assertEqual(installation, self.candidate)
        self.assertNotEqual(installation, self.source)
        (installation / "server" / "node_modules").mkdir()
        return types.SimpleNamespace(returncode=0)

    def test_prepared_candidate_is_independent_and_original_preserved(self):
        with patch.object(PREP.subprocess, "run", side_effect=self.simulated_install):
            status = PREP.prepare(self.source, self.candidate, self.deno)
        self.assertEqual(status, "prepared")
        self.assertTrue(PREP.is_prepared(self.candidate))
        self.assertTrue((self.source / "server" / "node_modules" / "old-module").exists())
        self.assertFalse((self.candidate / "server" / "node_modules" / "old-module").exists())
        self.assertEqual(json.loads((self.candidate / PREP.MARKER).read_text())["method"],
                         "prod-entrypoint-frozen")
        self.assertFalse(list(self.candidate.parent.glob("rrv-lean-staging-*")))

    def test_existing_prepared_candidate_is_not_reinstalled(self):
        with patch.object(PREP.subprocess, "run", side_effect=self.simulated_install) as run:
            self.assertEqual(PREP.prepare(self.source, self.candidate, self.deno), "prepared")
            self.assertEqual(PREP.prepare(self.source, self.candidate, self.deno), "already-prepared")
        self.assertEqual(run.call_count, 1)

    def test_existing_unverified_candidate_is_never_overwritten(self):
        self.candidate.mkdir(parents=True)
        (self.candidate / "private.txt").write_text("preserve", encoding="utf-8")
        with patch.object(PREP.subprocess, "run") as run:
            result = PREP.prepare(self.source, self.candidate, self.deno)
        self.assertEqual(result, "target-exists-unverified")
        run.assert_not_called()
        self.assertEqual((self.candidate / "private.txt").read_text(), "preserve")

    def test_failed_install_keeps_original_and_leaves_no_candidate(self):
        with patch.object(PREP.subprocess, "run", return_value=types.SimpleNamespace(returncode=3)):
            result = PREP.prepare(self.source, self.candidate, self.deno)
        self.assertEqual(result, "deno-install-failed")
        self.assertFalse(self.candidate.exists())
        self.assertFalse(list(self.candidate.parent.glob("rrv-lean-staging-*")))
        self.assertTrue((self.source / "server" / "node_modules" / "old-module").exists())

    def test_timeout_does_not_leak_subprocess_output(self):
        err = PREP.subprocess.TimeoutExpired("SECRET-COMMAND", 300, output=b"SECRET-TOKEN")
        with patch.object(PREP.subprocess, "run", side_effect=err):
            status = PREP.prepare(self.source, self.candidate, self.deno)
        self.assertEqual(status, "deno-install-timeout")
        self.assertNotIn("SECRET", status)
        self.assertFalse(self.candidate.exists())

    def test_invalid_source_and_missing_deno_do_not_create_candidate(self):
        (self.source / "plugin.zip").unlink()
        self.assertEqual(PREP.prepare(self.source, self.candidate, self.deno), "source-invalid")
        (self.source / "plugin.zip").write_text("restored")
        self.assertEqual(PREP.prepare(self.source, self.candidate, None), "deno-missing")
        self.assertFalse(self.candidate.exists())

    def test_source_target_overlap_is_rejected(self):
        self.assertEqual(PREP.prepare(self.source, self.source, self.deno), "source-target-overlap")
        self.assertEqual(PREP.prepare(self.source, self.source / "child", self.deno), "source-target-overlap")

    def test_paths_are_fixed_under_localappdata(self):
        with patch.dict(PREP.os.environ, {PREP.bgutil.ENV_HOME: ""}):
            original, candidate = PREP.experiment_paths(self.root)
        self.assertEqual(original, self.root / "RR-V" / "bgutil-stage03-external")
        self.assertEqual(candidate, self.root / "RR-V" / "diagnostics" / PREP.TARGET_NAME)

    def test_missing_marker_never_counts_as_prepared(self):
        self.assertFalse(PREP.is_prepared(self.source))


if __name__ == "__main__":
    unittest.main()
