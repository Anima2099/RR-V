from __future__ import annotations

import ast
from pathlib import Path
import unittest

from app.constants import SIDEBAR_COLLAPSED_WIDTH, SIDEBAR_WIDTH


ROOT = Path(__file__).resolve().parents[1]
SIDEBAR_PATH = ROOT / "ui" / "sidebar.py"
MAIN_WINDOW_PATH = ROOT / "ui" / "main_window.py"
THEME_PATH = ROOT / "resources" / "themes" / "warm_sage.qss"


class SidebarCollapseTests(unittest.TestCase):
    def test_collapsed_width_is_narrower_than_expanded_sidebar(self) -> None:
        self.assertEqual(SIDEBAR_WIDTH, 178)
        self.assertEqual(SIDEBAR_COLLAPSED_WIDTH, 44)
        self.assertLess(SIDEBAR_COLLAPSED_WIDTH, SIDEBAR_WIDTH)

    def test_sidebar_has_explicit_collapse_toggle_and_visibility_contract(self) -> None:
        source = SIDEBAR_PATH.read_text(encoding="utf-8")
        ast.parse(source, filename=str(SIDEBAR_PATH))

        self.assertIn("collapsed_changed = Signal(bool)", source)
        self.assertIn('self.toggle_button = QPushButton("◀")', source)
        self.assertIn('self.toggle_button.setText("▶" if collapsed else "◀")', source)
        self.assertIn("SIDEBAR_COLLAPSED_WIDTH if collapsed else SIDEBAR_WIDTH", source)
        self.assertIn("self.logo.setVisible(not collapsed)", source)
        self.assertIn("self.subtitle.setVisible(not collapsed)", source)
        self.assertIn("button.setVisible(not collapsed)", source)
        self.assertIn("self.version.setVisible(not collapsed)", source)

    def test_main_window_restores_and_persists_sidebar_state(self) -> None:
        source = MAIN_WINDOW_PATH.read_text(encoding="utf-8")
        ast.parse(source, filename=str(MAIN_WINDOW_PATH))

        self.assertIn('"window/sidebar_collapsed"', source)
        self.assertIn("self.sidebar.collapsed_changed.connect(", source)
        self.assertIn("self._sidebar_collapsed_changed", source)
        self.assertIn("self.sidebar.set_collapsed(", source)
        self.assertIn("emit=False", source)
        self.assertIn("self.sidebar.is_collapsed", source)
        self.assertIn("self.settings.sync()", source)

    def test_sidebar_toggle_has_theme_style(self) -> None:
        source = THEME_PATH.read_text(encoding="utf-8")

        self.assertIn("QPushButton#sidebarToggleButton", source)
        self.assertIn("min-width: 28px;", source)
        self.assertIn("max-width: 28px;", source)
        self.assertIn("background-color: transparent;", source)
        self.assertIn("QPushButton#sidebarToggleButton:hover", source)


if __name__ == "__main__":
    unittest.main()
