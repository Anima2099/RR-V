from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ToolUpdateShutdownTests(unittest.TestCase):
    def test_settings_pages_track_tool_action_until_completion(self) -> None:
        base_path = ROOT / "ui" / "pages" / "settings_page.py"
        base_source = base_path.read_text(encoding="utf-8")
        ast.parse(base_source, filename=str(base_path))

        self.assertIn("self._tool_action_running = False", base_source)
        self.assertIn("def has_active_tool_action", base_source)
        self.assertIn("self._tool_action_running = True", base_source)
        self.assertIn("except Exception as error:", base_source)

        theme_path = ROOT / "ui" / "pages" / "theme_settings_page.py"
        theme_source = theme_path.read_text(encoding="utf-8")
        ast.parse(theme_source, filename=str(theme_path))

        latest = theme_source[
            theme_source.index("    def _start_latest_updates("):
            theme_source.index(
                "    def _tool_action_done(",
                theme_source.index("    def _start_latest_updates("),
            )
        ]
        self.assertIn("if self._tool_action_running:", latest)
        self.assertIn("self._tool_action_running = True", latest)
        self.assertIn("except Exception as error:", latest)

        done = theme_source[
            theme_source.index("    def _tool_action_done("):
            theme_source.index(
                "    def show_settings_tab(",
                theme_source.index("    def _tool_action_done("),
            )
        ]
        self.assertIn("self._tool_action_running = False", done)

    def test_main_window_blocks_real_exit_while_tool_action_is_active(self) -> None:
        path = ROOT / "ui" / "main_window.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))

        close_event = source[
            source.index("    def closeEvent("):
        ]
        active_check = close_event.index("has_active_tool_action")
        ignore = close_event.index("event.ignore()", active_check)
        shutdown = close_event.index("self.download_page.shutdown()")

        self.assertIn(
            'getattr(self.settings_page, "has_active_tool_action", False)',
            close_event,
        )
        self.assertIn('"도구 작업 중"', close_event)
        self.assertLess(active_check, ignore)
        self.assertLess(ignore, shutdown)


if __name__ == "__main__":
    unittest.main()
