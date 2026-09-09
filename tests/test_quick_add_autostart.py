from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class QuickAddAutostartContractTests(unittest.TestCase):
    def test_refined_quick_add_marks_auto_start_before_analysis(self) -> None:
        path = ROOT / "ui" / "pages" / "download_page_refined.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        page_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "DownloadPage"
        )
        method = next(
            node
            for node in page_class.body
            if isinstance(node, ast.FunctionDef) and node.name == "_quick_add_url"
        )

        auto_start_add = next(
            node
            for node in ast.walk(method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "_external_auto_download_task_ids"
        )
        analysis_start = next(
            node
            for node in ast.walk(method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_start_next_quick_request"
        )
        self.assertLess(auto_start_add.lineno, analysis_start.lineno)

    def test_refinement_does_not_override_batch_add(self) -> None:
        path = ROOT / "ui" / "pages" / "download_page_refined.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        page_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "DownloadPage"
        )
        methods = {
            node.name
            for node in page_class.body
            if isinstance(node, ast.FunctionDef)
        }
        self.assertIn("_quick_add_url", methods)
        self.assertNotIn("_open_batch_add_dialog", methods)

    def test_main_uses_refined_shell_without_temporary_diagnostics(self) -> None:
        main_path = ROOT / "main.py"
        source = main_path.read_text(encoding="utf-8")
        self.assertIn("from ui.main_window_refined import MainWindow", source)
        self.assertNotIn("download_diagnostics", source)
        self.assertFalse((ROOT / "app" / "download_diagnostics.py").exists())


if __name__ == "__main__":
    unittest.main()
