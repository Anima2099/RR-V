from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from services import bgutil_http_service as bgutil


class FakeProcess:
    def __init__(self):
        self.started = True
        self.terminated = 0
        self.killed = 0
        self._poll = None

    def poll(self):
        return self._poll

    def terminate(self):
        self.terminated += 1
        self._poll = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed += 1
        self._poll = 0


class BgutilHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.server_dir = self.root / "server"
        self.server_dir.mkdir()
        (self.server_dir / "node_modules").mkdir()
        (self.server_dir / "src").mkdir()
        (self.server_dir / "src" / "main.ts").write_text("export {};", encoding="utf-8")
        (self.server_dir / "package.json").write_text(
            json.dumps({"version": bgutil.PROVIDER_VERSION, "license": "GPL-3.0-only"}), encoding="utf-8"
        )
        (self.root / "LICENSE").write_text("GPL", encoding="utf-8")
        self.plugins = self.root / "plugins" / "yt_dlp_plugins" / "extractor"
        self.plugins.mkdir(parents=True)
        with zipfile.ZipFile(self.root / "plugin.zip", "w") as z:
            for n in ("getpot_bgutil.py", "getpot_bgutil_http.py", "getpot_bgutil_script.py"):
                src = f"yt_dlp_plugins/extractor/{n}"
                data = f"# {n}\n".encode()
                z.writestr(src, data)
                (self.plugins / n).write_bytes(data)
        self.digest = hashlib.sha256((self.root / "plugin.zip").read_bytes()).hexdigest()
        (self.root / "rrv-stage03.json").write_text(json.dumps({
            "version": bgutil.PROVIDER_VERSION,
            "source_commit": bgutil.SOURCE_COMMIT,
            "plugin_sha256": self.digest,
        }), encoding="utf-8")
        self.hash_patch = patch.object(bgutil, "PLUGIN_SHA256", self.digest)
        self.hash_patch.start()
        self.addCleanup(self.hash_patch.stop)
        self.deno = self.root / "deno.exe"
        self.deno.write_bytes(b"fake exe")

    def test_pinned_external_install_accepts_exact_source_and_plugin(self):
        self.assertTrue(bgutil._validate_external_home(self.root))

    def test_detects_modified_plugin_files(self):
        (self.plugins / "getpot_bgutil_http.py").write_text("# altered", encoding="utf-8")
        self.assertFalse(bgutil._validate_external_home(self.root))

    def test_rejects_modified_zip_and_wrong_license(self):
        (self.root / "plugin.zip").write_bytes(b"tampered")
        self.assertFalse(bgutil._validate_external_home(self.root))

    def test_rejects_wrong_package_version(self):
        (self.server_dir / "package.json").write_text(
            json.dumps({"version": "1.0.0", "license": "GPL-3.0-only"}), encoding="utf-8"
        )
        self.assertFalse(bgutil._validate_external_home(self.root))

    def test_not_enabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(bgutil.connect_bgutil_http(self.deno))

    def test_server_starts_on_loopback_and_reuses_process(self):
        server = bgutil._BgUtilServer()
        fake = FakeProcess()
        with (patch.object(bgutil, "_free_loopback_port", return_value=12024),
              patch.object(bgutil, "_ping_local_provider", return_value=True) as ping,
              patch.object(bgutil.subprocess, "Popen", return_value=fake) as popen):
            conn = server.ensure(self.root, self.deno)
            self.assertIsNotNone(conn)
            self.assertEqual(conn.base_url, "http://127.0.0.1:12024")
            self.assertTrue(conn.plugin_dir.samefile(self.root))
            self.assertTrue((conn.plugin_dir / "plugin.zip").is_file())
            self.assertEqual(server.status(), "ready")
            self.assertEqual(server.ensure(self.root, self.deno), conn)
            self.assertEqual(popen.call_count, 1)
            self.assertEqual(popen.call_args[0][0][-4:], ["--host", "127.0.0.1", "--port", "12024"])
            self.assertTrue(ping.called)
            server.close()
        self.assertEqual(fake.terminated, 1)

    def test_failed_start_falls_back_and_throttles_retry(self):
        server = bgutil._BgUtilServer()
        fake = FakeProcess()
        fake._poll = 1
        with (patch.object(bgutil, "_free_loopback_port", return_value=12024),
              patch.object(bgutil, "_ping_local_provider", return_value=False),
              patch.object(bgutil.subprocess, "Popen", return_value=fake) as popen):
            self.assertIsNone(server.ensure(self.root, self.deno))
            self.assertIsNone(server.ensure(self.root, self.deno))
            self.assertEqual(popen.call_count, 1)
            self.assertEqual(server.status(), "retry-cooldown")
            server.close()

    def test_subprocess_launch_error_is_nonfatal(self):
        server = bgutil._BgUtilServer()
        with (patch.object(bgutil, "_free_loopback_port", return_value=12024),
              patch.object(bgutil.subprocess, "Popen", side_effect=OSError("no launch"))):
            self.assertIsNone(server.ensure(self.root, self.deno))
            self.assertEqual(server.status(), "deno-launch-failed:OSError")
            server.close()

    def test_invalid_external_installation_has_diagnostic(self):
        server = bgutil._BgUtilServer()
        (self.root / "rrv-stage03.json").unlink()
        self.assertIsNone(server.ensure(self.root, self.deno))
        self.assertEqual(server.status(), "invalid-external-installation")

    def test_missing_deno_has_diagnostic(self):
        server = bgutil._BgUtilServer()
        self.assertIsNone(server.ensure(self.root, self.root / "missing-deno.exe"))
        self.assertEqual(server.status(), "deno-executable-missing")

    def test_exited_server_reports_exit_code(self):
        server = bgutil._BgUtilServer()
        fake = FakeProcess()
        fake._poll = 27
        with (patch.object(bgutil, "_free_loopback_port", return_value=12024),
              patch.object(bgutil.subprocess, "Popen", return_value=fake)):
            self.assertIsNone(server.ensure(self.root, self.deno))
        self.assertEqual(server.status(), "deno-exited-before-ready:code=27")

    def test_status_does_not_leak_when_disabled(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(bgutil.bgutil_http_status(), "disabled")

    def test_explicit_env_connects_and_shutdown_is_idempotent(self):
        connection = bgutil.BgUtilConnection(self.root, "http://127.0.0.1:9999")
        with (patch.dict(os.environ, {bgutil.ENV_HOME: str(self.root)}),
              patch.object(bgutil._SERVER, "ensure", return_value=connection) as ensure):
            self.assertEqual(bgutil.connect_bgutil_http(self.deno), connection)
            ensure.assert_called_once()
            self.assertIsNone(bgutil.connect_bgutil_http(None))


if __name__ == "__main__":
    unittest.main()
