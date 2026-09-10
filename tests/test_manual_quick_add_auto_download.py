from __future__ import annotations

import ast
from pathlib import Path
import unittest

from app.general_preferences import GeneralPreferences


ROOT = Path(__file__).resolve().parents[1]
GENERAL_PREFERENCES_PATH = ROOT / "app" / "general_preferences.py"
BASE_DOWNLOAD_PAGE_PATH = ROOT / "ui" / "pages" / "download_page.py"
RUNTIME_DOWNLOAD_PAGE_PATH = ROOT / "ui" / "pages" / "download_page_chapters.py"
RUNTIME_SETTINGS_PATH = ROOT / "ui" / "pages" / "chapter_settings_page.py"


def _method_source(path: Path, class_name: str, method_name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    page_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node
        for node in page_class.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )
    return ast.get_source_segment(source, method) or ""


class ManualQuickAddAutoDownloadTests(unittest.TestCase):
    def test_preference_is_opt_in_and_defaults_off(self) -> None:
        self.assertFalse(GeneralPreferences().quick_add_auto_download)

        source = GENERAL_PREFERENCES_PATH.read_text(encoding="utf-8")
        self.assertIn('"general/quick_add_auto_download"', source)
        self.assertIn("preferences.quick_add_auto_download", source)

    def test_download_settings_exposes_global_quick_add_option(self) -> None:
        source = RUNTIME_SETTINGS_PATH.read_text(encoding="utf-8")
        preset_tab = _method_source(
            RUNTIME_SETTINGS_PATH,
            "UnifiedSettingsPage",
            "_create_preset_tab",
        )
        save_method = _method_source(
            RUNTIME_SETTINGS_PATH,
            "UnifiedSettingsPage",
            "_save_download_settings",
        )

        self.assertIn("빠른 추가 후 자동으로 다운로드 시작", source)
        self.assertIn("_create_quick_add_behavior_card", preset_tab)
        self.assertIn("quick_add_auto_download", save_method)
        self.assertIn("save_general_preferences", save_method)

    def test_manual_quick_add_only_arms_auto_flow_when_setting_is_enabled(self) -> None:
        quick_add = _method_source(
            RUNTIME_DOWNLOAD_PAGE_PATH,
            "DownloadPage",
            "_quick_add_url",
        )
        placeholder = _method_source(
            RUNTIME_DOWNLOAD_PAGE_PATH,
            "DownloadPage",
            "_create_quick_placeholder",
        )

        self.assertIn("load_general_preferences().quick_add_auto_download", quick_add)
        self.assertIn("self._manual_quick_add_auto_requested", quick_add)
        self.assertIn("super()._quick_add_url()", quick_add)
        self.assertIn("finally:", quick_add)
        self.assertIn("if self._manual_quick_add_auto_requested:", placeholder)
        self.assertIn(
            "self._external_auto_download_task_ids.add(task.task_id)",
            placeholder,
        )

    def test_manual_option_reuses_proven_browser_auto_completion_path(self) -> None:
        completion = _method_source(
            BASE_DOWNLOAD_PAGE_PATH,
            "DownloadPage",
            "_complete_quick_task",
        )

        self.assertIn(
            "auto_download = task.task_id in self._external_auto_download_task_ids",
            completion,
        )
        self.assertIn("if auto_download:", completion)
        self.assertIn("self._arm_browser_auto_download_queue()", completion)

    def test_auto_flow_never_parallel_starts_an_active_download(self) -> None:
        arm = _method_source(
            BASE_DOWNLOAD_PAGE_PATH,
            "DownloadPage",
            "_arm_browser_auto_download_queue",
        )

        self.assertIn("if not self.controller.is_downloading:", arm)
        self.assertIn("self._start_next_queue_task", arm)
        self.assertNotIn("self._start_task(", arm)

    def test_auto_flow_preserves_existing_queue_order(self) -> None:
        next_queue = _method_source(
            BASE_DOWNLOAD_PAGE_PATH,
            "DownloadPage",
            "_start_next_queue_task",
        )
        next_task = _method_source(
            BASE_DOWNLOAD_PAGE_PATH,
            "DownloadPage",
            "_next_queued_task",
        )

        self.assertIn("self._next_queued_task()", next_queue)
        self.assertIn("for item in self.tasks", next_task)
        self.assertIn("item.status is DownloadStatus.QUEUED", next_task)
        self.assertNotIn("insert(0", next_queue)


if __name__ == "__main__":
    unittest.main()
