from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ui" / "pages" / "unified_settings_page.py"


class DownloadSettingsLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = PAGE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, filename=str(PAGE))
        cls.page_class = next(
            node
            for node in cls.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "SettingsPage"
        )

    def _method(self, name: str) -> ast.FunctionDef:
        return next(
            node
            for node in self.page_class.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        )

    @staticmethod
    def _called_attributes(method: ast.FunctionDef) -> set[str]:
        return {
            node.func.attr
            for node in ast.walk(method)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

    def test_visible_tab_renames_preset_section_to_download_settings(self) -> None:
        assignment = next(
            node
            for node in self.page_class.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "_VISIBLE_TAB_ORDER"
                for target in node.targets
            )
        )
        labels = {
            node.value
            for node in ast.walk(assignment)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertIn("다운로드 설정", labels)

    def test_general_tab_keeps_only_general_behavior_cards(self) -> None:
        calls = self._called_attributes(self._method("_create_general_tab"))
        for name in (
            "_create_theme_card",
            "_create_queue_restore_card",
            "_create_windows_behavior_card",
            "_create_notification_card",
        ):
            self.assertIn(name, calls)
        for name in (
            "_create_download_folder_card",
            "_create_filename_template_card",
            "_create_file_collision_card",
            "_create_download_preferences_card",
        ):
            self.assertNotIn(name, calls)

    def test_download_settings_collects_file_rules_and_presets(self) -> None:
        calls = self._called_attributes(self._method("_create_preset_tab"))
        for name in (
            "_create_download_folder_card",
            "_create_filename_template_card",
            "_create_file_collision_card",
            "_create_download_common_save_bar",
            "_create_download_preferences_card",
        ):
            self.assertIn(name, calls)

    def test_common_download_save_owns_file_setting_fields(self) -> None:
        method = self._method("_save_download_settings")
        keyword_names = {
            keyword.arg
            for node in ast.walk(method)
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if keyword.arg is not None
        }
        self.assertIn("default_download_folder", keyword_names)
        self.assertIn("filename_template", keyword_names)
        self.assertIn("filename_template_auto_spacing", keyword_names)
        self.assertIn("file_collision_mode", keyword_names)

    def test_filename_template_card_exposes_auto_spacing_and_date_guidance(self) -> None:
        method = self._method("_create_filename_template_card")
        strings = {
            node.value
            for node in ast.walk(method)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertIn("토큰 추가 시 자동으로 띄어쓰기", strings)
        self.assertTrue(
            any("업로드 날짜 8자리 예" in value for value in strings)
        )
        self.assertTrue(
            any("공백이나 -, _, [ ], ( )" in value for value in strings)
        )


if __name__ == "__main__":
    unittest.main()
