from __future__ import annotations

import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import (
    converter_log,
    performance_log,
    snapshot_log,
    subtitle_log,
    thumbnail_log,
)


LOG_CASES = (
    (
        converter_log,
        "initialize_converter_log",
        "write_converter_event",
        "_append",
        "CONVERSION_TEST",
    ),
    (
        snapshot_log,
        "initialize_snapshot_log",
        "write_snapshot_event",
        "_append",
        "SNAPSHOT_TEST",
    ),
    (
        subtitle_log,
        "initialize_subtitle_log",
        "write_subtitle_event",
        "_append",
        "SUBTITLE_TEST",
    ),
    (
        thumbnail_log,
        "initialize_thumbnail_log",
        "write_thumbnail_event",
        "_append",
        "THUMBNAIL_TEST",
    ),
)


class LogResilienceTests(unittest.TestCase):
    def test_media_event_logs_survive_console_encoding_failure(self) -> None:
        encoding_error = UnicodeEncodeError(
            "cp949",
            "제목 😀 日本語",
            3,
            4,
            "illegal multibyte sequence",
        )

        for module, init_name, write_name, append_name, event in LOG_CASES:
            with self.subTest(module=module.__name__):
                with (
                    patch.object(module, init_name),
                    patch("builtins.print", side_effect=encoding_error),
                    patch.object(module, append_name) as append,
                ):
                    getattr(module, write_name)(
                        event,
                        path="D:/영상/日本語 😀.mp4",
                    )

                append.assert_called_once()

    def test_media_log_file_failures_do_not_escape(self) -> None:
        for module, _init_name, _write_name, append_name, _event in LOG_CASES:
            with self.subTest(module=module.__name__):
                with (
                    patch.object(module, "_safe_console_print"),
                    patch.object(
                        module.Path,
                        "open",
                        side_effect=OSError("disk unavailable"),
                    ) as open_file,
                ):
                    getattr(module, append_name)(
                        Path("unavailable.log"),
                        "제목 😀 日本語\n",
                    )

                open_file.assert_called_once()

    def test_media_log_initialization_failures_do_not_escape(self) -> None:
        for module, init_name, _write_name, _append_name, _event in LOG_CASES:
            with self.subTest(module=module.__name__):
                original_initialized = module._INITIALIZED
                module._INITIALIZED = False
                try:
                    with (
                        patch.object(
                            module,
                            "ensure_runtime_directories",
                            side_effect=OSError("runtime directory unavailable"),
                        ),
                        patch.object(module, "_safe_console_print"),
                    ):
                        getattr(module, init_name)()
                finally:
                    module._INITIALIZED = original_initialized

    def test_startup_diagnostics_use_fail_soft_console_output(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "application.py"
        ).read_text(encoding="utf-8")

        self.assertIn("def _safe_console_print", source)
        app_tree = ast.parse(source)
        app_print_calls = [
            node
            for node in ast.walk(app_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ]
        self.assertEqual(len(app_print_calls), 1)
        self.assertIn(
            '_safe_console_print(f"RR-V performance log: {performance_log_path()}")',
            source,
        )
        self.assertIn(
            '_safe_console_print(f"RR-V download log: {download_log_path()}")',
            source,
        )

        main_source = (
            Path(__file__).resolve().parents[1] / "main.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def _safe_console_print", main_source)
        main_tree = ast.parse(main_source)
        main_print_calls = [
            node
            for node in ast.walk(main_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ]
        self.assertEqual(len(main_print_calls), 1)
        self.assertIn(
            "RR-V browser integration registration sync failed",
            main_source,
        )
        self.assertIn(
            "RR-V Windows startup registration sync failed",
            main_source,
        )

    def test_performance_log_is_fail_soft_for_console_and_file_errors(self) -> None:
        encoding_error = UnicodeEncodeError(
            "cp949",
            "성능 😀 日本語",
            3,
            4,
            "illegal multibyte sequence",
        )
        with (
            patch("app.performance_log.initialize_performance_log"),
            patch("builtins.print", side_effect=encoding_error),
            patch("app.performance_log._append_text") as append,
        ):
            performance_log.write_performance(
                "performance.test",
                12.5,
                path="D:/영상/日本語 😀.mp4",
            )
        append.assert_called_once()

        with (
            patch("app.performance_log._safe_console_print"),
            patch.object(
                performance_log.Path,
                "open",
                side_effect=OSError("disk unavailable"),
            ) as open_file,
        ):
            performance_log._append_text(
                Path("performance-unavailable.log"),
                "성능 로그\n",
            )
        open_file.assert_called_once()


if __name__ == "__main__":
    unittest.main()
