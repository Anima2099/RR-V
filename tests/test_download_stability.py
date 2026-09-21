from __future__ import annotations

import ast
from pathlib import Path
import unittest
from unittest.mock import patch

from app import download_log
from core.download_task import (
    DownloadStatus,
    DownloadTask,
    is_orphaned_download_task,
)
from services.download_service import YtDlpDownloadService


ROOT = Path(__file__).resolve().parents[1]


def _task(status: DownloadStatus) -> DownloadTask:
    return DownloadTask(
        task_id="orphan-test",
        title="고립 감지 테스트",
        url="https://example.invalid/video",
        status=status,
    )


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
            patch("app.download_log.initialize_download_log"),
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
            patch("app.download_log.initialize_download_log"),
            patch("app.download_log._safe_console_print"),
            patch.object(download_log.Path, "open", side_effect=OSError("disk unavailable")) as open_file,
        ):
            download_log.write_download_event(
                "download.command_ready",
                task_id="file-log-test",
                title="파일 로그 실패도 다운로드를 막으면 안 됨",
            )

        open_file.assert_called_once()

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

    def test_orphan_guard_requires_both_runtime_layers_to_be_gone(self) -> None:
        for status in (
            DownloadStatus.DOWNLOADING,
            DownloadStatus.POSTPROCESSING,
        ):
            with self.subTest(status=status):
                task = _task(status)
                self.assertTrue(
                    is_orphaned_download_task(
                        task,
                        worker_running=False,
                        process_running=False,
                    )
                )
                self.assertFalse(
                    is_orphaned_download_task(
                        task,
                        worker_running=True,
                        process_running=False,
                    )
                )
                self.assertFalse(
                    is_orphaned_download_task(
                        task,
                        worker_running=False,
                        process_running=True,
                    )
                )

    def test_orphan_guard_ignores_terminal_and_queued_states(self) -> None:
        for status in (
            DownloadStatus.ANALYZING,
            DownloadStatus.QUEUED,
            DownloadStatus.COMPLETED,
            DownloadStatus.FAILED,
            DownloadStatus.STOPPED,
        ):
            with self.subTest(status=status):
                self.assertFalse(
                    is_orphaned_download_task(
                        _task(status),
                        worker_running=False,
                        process_running=False,
                    )
                )

    def test_process_state_check_is_conservative(self) -> None:
        service = YtDlpDownloadService()

        class FakeProcess:
            def __init__(self, result: int | None = None, fail: bool = False) -> None:
                self.result = result
                self.fail = fail

            def poll(self) -> int | None:
                if self.fail:
                    raise OSError("poll unavailable")
                return self.result

        service._process = FakeProcess(result=None)  # type: ignore[assignment]
        self.assertTrue(service.has_running_process)

        service._process = FakeProcess(result=0)  # type: ignore[assignment]
        self.assertFalse(service.has_running_process)

        service._process = FakeProcess(fail=True)  # type: ignore[assignment]
        self.assertTrue(service.has_running_process)

        service._process = None
        service._last_process = FakeProcess(result=None)  # type: ignore[assignment]
        self.assertTrue(service.has_running_process)

        service._last_process = FakeProcess(result=0)  # type: ignore[assignment]
        self.assertFalse(service.has_running_process)

        service._last_process = None
        self.assertFalse(service.has_running_process)

    def test_controller_reports_runtime_state_before_queue_continues(self) -> None:
        path = ROOT / "controllers" / "download_controller.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))

        finished = source[
            source.index("    def _download_worker_finished("):
        ]
        self.assertIn("worker.has_running_process", finished)
        self.assertIn("worker.cancel()", finished)
        self.assertIn("self.download_runtime_ended.emit(", finished)
        self.assertIn("self.download_finished.emit(", finished)
        self.assertLess(
            finished.index("self.download_runtime_ended.emit("),
            finished.index("self.download_finished.emit("),
        )

    def test_page_defers_orphan_verification_before_next_queue_item(self) -> None:
        path = ROOT / "ui" / "pages" / "download_page.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))

        runtime = source[
            source.index("    def _download_runtime_ended("):
            source.index("    def _download_finished(", source.index("    def _download_runtime_ended("))
        ]
        finished = source[
            source.index("    def _download_finished("):
            source.index(
                "    # ------------------------------------------------------------------",
                source.index("    def _download_finished("),
            )
        ]

        self.assertIn("QTimer.singleShot(", runtime)
        self.assertIn("_verify_download_runtime_ended", runtime)
        self.assertIn("is_orphaned_download_task(", runtime)
        self.assertIn("self._download_failed(", runtime)
        self.assertIn("download.orphaned_task_recovered", runtime)
        self.assertIn("QTimer.singleShot(120, self._start_next_queue_task)", finished)


    def test_download_logger_catches_broad_environment_failures(self) -> None:
        path = ROOT / "app" / "download_log.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))

        self.assertIn("def _safe_console_print", source)
        self.assertIn("except Exception:", source)
        self.assertIn("except Exception as error:", source)


if __name__ == "__main__":
    unittest.main()
