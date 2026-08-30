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


if __name__ == "__main__":
    unittest.main()
