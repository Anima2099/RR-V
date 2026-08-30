from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ABOUT_PAGE_PATH = ROOT / "ui" / "pages" / "about_page.py"


class AppUpdateStartupContractTests(unittest.TestCase):
    def test_auto_update_check_has_no_persistent_time_throttle(self) -> None:
        source = ABOUT_PAGE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)

        method = None
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or node.name != "AboutPage":
                continue
            method = next(
                (
                    item
                    for item in node.body
                    if isinstance(item, ast.FunctionDef)
                    and item.name == "start_auto_update_check"
                ),
                None,
            )
            break

        self.assertIsNotNone(method)
        snippet = ast.get_source_segment(source, method) or ""
        self.assertIn("self._begin_update_check(notify=notify)", snippet)
        self.assertNotIn("_LAST_AUTO_UPDATE_CHECK_KEY", source)
        self.assertNotIn("_AUTO_UPDATE_CHECK_INTERVAL_SECONDS", source)


if __name__ == "__main__":
    unittest.main()
