from __future__ import annotations

import ast
from pathlib import Path
import unittest
from unittest.mock import patch

from app import download_log


ROOT = Path(__file__).resolve().parents[1]


class DownloadStabilityTests(unittest.TestCase):
    def test_download_event_survives_console_encoding_failure(self) -> None:
        encoding_error = UnicodeEncodeError(
            "cp949",
            "제목 😀 日本語",
            3,
            4,
            "illegal multibyte sequence",
        )

        with (
            patch("builtins.print", side_effect=encoding_error),
            patch("app.download_log._append") as append,
        ):
            download_log.write_download_event(
                "download.prepare_started",
                task_id="unicode-test",
                title="제목 😀 日本語",
            )

        append.assert_called_once()
        self.assertIn("제목 😀 日本語", append.call_args.args[1])

    def test_download_event_survives_file_log_failure(self) -> None:
        with (
            patch("app.download_log._safe_console_print"),
            patch("app.download_log._append", side_effect=OSError("disk unavailable")),
        ):
            download_log.write_download_event(
                "download.command_ready",
                task_id="file-log-test",
                title="파일 로그 실패도 다운로드를 막으면 안 됨",
            )

    def test_worker_failure_signal_is_after_fail_safe_logging(self) -> None:
        path = ROOT / "workers" / "download_worker.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        worker_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "DownloadWorker"
        )
        self.assertTrue(
            any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "_write_event_safely"
                for node in worker_class.body
            )
        )

        run_source = source[
            source.index("    def run(self) -> None:")
            :source.index("    @staticmethod", source.index("    def run(self) -> None:"))
        ]
        self.assertIn("self._write_event_safely(", run_source)
        self.assertIn("self.download_failed.emit(", run_source)
        self.assertLess(
            run_source.index("self._write_event_safely("),
            run_source.index("self.download_failed.emit("),
        )

    def test_prepare_diagnostics_cover_pre_process_gap(self) -> None:
        path = ROOT / "services" / "download_service.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))

        prepare = source.index('"download.prepare_started"')
        command_ready = source.index('"download.command_ready"')
        start_requested = source.index('"download.start_requested"')
        popen = source.index("process = subprocess.Popen(")
        process_started = source.index('"download.process_started"')

        self.assertLess(prepare, command_ready)
        self.assertLess(command_ready, start_requested)
        self.assertLess(start_requested, popen)
        self.assertLess(popen, process_started)

    def test_download_logger_catches_broad_environment_failures(self) -> None:
        path = ROOT / "app" / "download_log.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))

        self.assertIn("def _safe_console_print", source)
        self.assertIn("except Exception:", source)
        self.assertIn("except Exception as error:", source)


if __name__ == "__main__":
    unittest.main()
