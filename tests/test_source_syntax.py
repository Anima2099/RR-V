from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (
    ROOT / "app",
    ROOT / "auth_helper",
    ROOT / "controllers",
    ROOT / "core",
    ROOT / "services",
    ROOT / "ui",
    ROOT / "workers",
)


class SourceSyntaxTests(unittest.TestCase):
    def test_all_python_sources_parse(self) -> None:
        paths = [ROOT / "main.py"]
        for source_root in SOURCE_ROOTS:
            paths.extend(sorted(source_root.rglob("*.py")))

        self.assertGreater(len(paths), 1)
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                source = path.read_text(encoding="utf-8")
                ast.parse(source, filename=str(path))

    def test_community_tools_tab_includes_tool_diagnostics_card(self) -> None:
        path = ROOT / "ui" / "pages" / "community_settings_page.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        community_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "CommunitySettingsPage"
        )
        tools_tab = next(
            node
            for node in community_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_create_tools_tab"
        )
        called_methods = {
            node.func.attr
            for node in ast.walk(tools_tab)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertIn("_create_tool_diagnostics_card", called_methods)

    def test_settings_entry_point_defers_startup_tool_refresh(self) -> None:
        path = ROOT / "ui" / "pages" / "unified_settings_page.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        settings_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "SettingsPage"
        )
        init_method = next(
            node
            for node in settings_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "__init__"
        )
        refresh_method = next(
            node
            for node in settings_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_refresh_tool_status"
        )

        init_attributes = {
            node.attr
            for node in ast.walk(init_method)
            if isinstance(node, ast.Attribute)
        }
        self.assertIn("_initializing_settings_page", init_attributes)
        self.assertNotIn("_startup_tool_refresh_seen", init_attributes)
        self.assertTrue(any(isinstance(node, ast.Return) for node in ast.walk(refresh_method)))
        self.assertTrue(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_refresh_tool_status"
                for node in ast.walk(refresh_method)
            )
        )

    def test_settings_entry_point_reuses_background_tool_snapshot(self) -> None:
        path = ROOT / "ui" / "pages" / "unified_settings_page.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        settings_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "SettingsPage"
        )
        done_method = next(
            node
            for node in settings_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_component_check_done"
        )
        called_methods = {
            node.func.attr
            for node in ast.walk(done_method)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        string_constants = {
            node.value
            for node in ast.walk(done_method)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertIn("_apply_inspected_tool_statuses", called_methods)
        self.assertIn("installed_statuses", string_constants)

    def test_unified_settings_aliases_final_settings_page(self) -> None:
        path = ROOT / "ui" / "pages" / "unified_settings_page.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        alias = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "UnifiedSettingsPage"
                for target in node.targets
            )
        )
        self.assertIsInstance(alias.value, ast.Name)
        self.assertEqual(alias.value.id, "SettingsPage")

    def test_media_tools_page_registers_remux_without_detailed_info_tab(self) -> None:
        path = ROOT / "ui" / "pages" / "media_tools_page.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        string_constants = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("Remux", string_constants)
        self.assertIn("RemuxPage", called_names)
        self.assertNotIn("상세 정보", string_constants)
        self.assertNotIn("MediaInfoPage", called_names)


if __name__ == "__main__":
    unittest.main()
