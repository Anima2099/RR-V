from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_PAGE_PATH = ROOT / "ui" / "pages" / "download_page.py"


def _download_page_method_source(method_name: str) -> str:
    source = DOWNLOAD_PAGE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(DOWNLOAD_PAGE_PATH))
    page_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DownloadPage"
    )
    method = next(
        node
        for node in page_class.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )
    return ast.get_source_segment(source, method) or ""


class QuickAddContractTests(unittest.TestCase):
    def test_manual_quick_add_queues_and_analyzes_without_auto_start(self) -> None:
        source = _download_page_method_source("_quick_add_url")

        self.assertIn("_create_quick_placeholder", source)
        self.assertIn("self._quick_queue.append", source)
        self.assertIn("self._start_next_quick_request()", source)
        self.assertNotIn("_external_auto_download_task_ids", source)
        self.assertNotIn("_arm_browser_auto_download_queue", source)
        self.assertNotIn("_start_task(", source)

    def test_external_auto_download_requires_explicit_auto_download_flag(self) -> None:
        source = _download_page_method_source("enqueue_external_urls")

        self.assertIn("if auto_download:", source)
        self.assertIn(
            "self._external_auto_download_task_ids.add(task.task_id)",
            source,
        )
        self.assertIn(
            "QTimer.singleShot(0, self._start_next_quick_request)",
            source,
        )

    def test_completed_quick_task_only_auto_starts_marked_requests(self) -> None:
        source = _download_page_method_source("_complete_quick_task")

        self.assertIn(
            "auto_download = task.task_id in self._external_auto_download_task_ids",
            source,
        )
        self.assertIn("if auto_download:", source)
        self.assertIn("self._arm_browser_auto_download_queue()", source)

    def test_preview_now_download_uses_direct_start_path(self) -> None:
        source = _download_page_method_source("_create_task_from_preview")

        self.assertIn("if start_immediately:", source)
        self.assertIn("self._start_task(task.task_id)", source)
        self.assertIn('"preview_add.click_handler"', source)

    def test_main_uses_canonical_window_and_no_quick_add_refinement_files(self) -> None:
        main_source = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("from ui.main_window import MainWindow", main_source)
        self.assertNotIn("main_window_refined", main_source)
        self.assertFalse((ROOT / "ui" / "main_window_refined.py").exists())
        self.assertFalse(
            (ROOT / "ui" / "pages" / "download_page_refined.py").exists()
        )


if __name__ == "__main__":
    unittest.main()
