from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ui" / "pages" / "unified_settings_page.py"
RUNTIME_PAGE = ROOT / "ui" / "pages" / "chapter_settings_page.py"


def _class_method_source(path: Path, class_name: str, method_name: str) -> str:
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


class RuntimeDownloadSettingsSubtabTests(unittest.TestCase):
    def test_runtime_download_settings_has_two_exclusive_subtabs(self) -> None:
        method = _class_method_source(
            RUNTIME_PAGE,
            "UnifiedSettingsPage",
            "_create_preset_tab",
        )
        self.assertIn('("공통 설정", "다운로드 프리셋")', method)
        self.assertIn("QButtonGroup(self)", method)
        self.assertIn("setExclusive(True)", method)
        self.assertIn("QStackedWidget()", method)

    def test_common_subtab_card_order_matches_ui_contract(self) -> None:
        method = _class_method_source(
            RUNTIME_PAGE,
            "UnifiedSettingsPage",
            "_create_preset_tab",
        )
        calls = (
            "_create_download_folder_card()",
            "_create_quick_add_behavior_card()",
            "_create_file_collision_card()",
            "_create_filename_template_card()",
            "_create_download_common_save_bar()",
        )
        positions = [method.index(call) for call in calls]
        self.assertEqual(positions, sorted(positions))

    def test_preset_editor_is_isolated_on_second_subtab(self) -> None:
        method = _class_method_source(
            RUNTIME_PAGE,
            "UnifiedSettingsPage",
            "_create_preset_tab",
        )
        common_start = method.index("common_page =")
        preset_start = method.index("preset_page =")
        preset_card = method.index("_create_download_preferences_card()")
        self.assertLess(common_start, preset_start)
        self.assertGreater(preset_card, preset_start)

    def test_common_subtab_is_default_and_invalid_index_falls_back_to_it(self) -> None:
        create_method = _class_method_source(
            RUNTIME_PAGE,
            "UnifiedSettingsPage",
            "_create_preset_tab",
        )
        show_method = _class_method_source(
            RUNTIME_PAGE,
            "UnifiedSettingsPage",
            "_show_download_settings_subtab",
        )
        self.assertIn("download_settings_subtab_buttons[0].setChecked(True)", create_method)
        self.assertIn("download_settings_substack.setCurrentIndex(0)", create_method)
        self.assertIn("if index < 0 or index >= self.download_settings_substack.count():", show_method)
        self.assertIn("index = 0", show_method)
        self.assertIn("setCurrentIndex(index)", show_method)


if __name__ == "__main__":
    unittest.main()
