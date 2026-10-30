from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import bgutil_diagnostics as diagnostic


class BgutilDiagnosticsTests(unittest.TestCase):
    def test_records_only_enumerated_safe_status_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bgutil-stage03.log"
            with patch.object(diagnostic, "BGUTIL_DIAGNOSTIC_LOG_PATH", path):
                diagnostic.record_bgutil_diagnostic(
                    "youtube.providers", pid=123, mode="enabled", stage="analysis",
                    deno="found", bgutil="ready", wpc="available",
                    route="bgutil-and-wpc", url="https://secret.example/test",
                    token="sensitive-value", status="D:/private/location",
                )
            contents = path.read_text(encoding="utf-8")
            self.assertIn("event=youtube.providers", contents)
            self.assertIn("pid=123", contents)
            self.assertIn("route=bgutil-and-wpc", contents)
            self.assertIn("status=redacted", contents)
            self.assertNotIn("secret.example", contents)
            self.assertNotIn("sensitive-value", contents)
            self.assertNotIn("private/location", contents)

    def test_diagnostics_disabled_disk_does_not_raise(self):
        with patch.object(diagnostic.Path, "open", side_effect=OSError("/sensitive/path")):
            diagnostic.record_bgutil_diagnostic("server.failed", status="timeout")

    def test_status_value_cannot_include_newlines_or_paths(self):
        for value in ("hello\nworld", "C:\\private\\cookie.txt", "https://youtube.com/watch?v=id", "secret token"):
            with self.subTest(value=value):
                self.assertEqual(diagnostic._safe_atom(value), "redacted")

    def test_status_enum_with_exit_code_is_retained(self):
        self.assertEqual(diagnostic._safe_atom("deno-exited-before-ready:code=27"), "deno-exited-before-ready-code-27")
        self.assertEqual(diagnostic._safe_atom("server-ping-timeout"), "server-ping-timeout")

    def test_log_rotates_when_limit_exceeded(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bgutil-stage03.log"
            path.write_text("a" * 30, encoding="utf-8")
            with (patch.object(diagnostic, "BGUTIL_DIAGNOSTIC_LOG_PATH", path),
                  patch.object(diagnostic, "_LOG_LIMIT_BYTES", 10)):
                diagnostic.record_bgutil_diagnostic("app.primary", pid=22)
            self.assertTrue(path.with_suffix(".log.1").is_file())
            self.assertIn("event=app.primary", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
