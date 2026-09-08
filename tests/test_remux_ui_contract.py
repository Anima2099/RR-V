from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ui" / "tools" / "remux_page_refined.py"


class RemuxUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = PAGE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, filename=str(PAGE))
        cls.page_class = next(
            node
            for node in cls.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "RemuxPage"
        )

    def _method(self, name: str) -> ast.FunctionDef:
        return next(
            node
            for node in self.page_class.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        )

    def test_target_card_does_not_select_radio_before_status_widgets_exist(self) -> None:
        method = self._method("_create_target_card")
        calls = [
            node.func.attr
            for node in ast.walk(method)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        self.assertNotIn("setChecked", calls)

    def test_audio_extensions_are_not_in_primary_media_filter(self) -> None:
        first_filter = self.source.split(";;", 1)[0].lower()
        for suffix in (".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus"):
            self.assertNotIn(suffix, first_filter)

    def test_audio_only_guard_uses_real_video_state(self) -> None:
        method = self._method("_refresh_target_state")
        attrs = {
            node.attr
            for node in ast.walk(method)
            if isinstance(node, ast.Attribute)
        }
        self.assertIn("has_video", attrs)

    def test_success_resets_input_state(self) -> None:
        method = self._method("_remux_done")
        called = {
            node.func.attr
            for node in ast.walk(method)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertIn("_reset_input_after_success", called)

    def test_compatibility_status_has_success_and_error_colors(self) -> None:
        method = self._method("_set_compatibility_status")
        values = {
            node.value
            for node in ast.walk(method)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertIn("success", values)
        self.assertIn("error", values)
        self.assertTrue(any("background-color" in value for value in values))


if __name__ == "__main__":
    unittest.main()
