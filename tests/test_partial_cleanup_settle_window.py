from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PartialCleanupSettleWindowContractTests(unittest.TestCase):
    def test_cleanup_keeps_scanning_after_an_earlier_delete_succeeds(self) -> None:
        path = ROOT / "ui" / "pages" / "download_page_chapters.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))

        method_start = source.index("    def _attempt_partial_cleanup(")
        method_end = source.index("    def _report_partial_cleanup(", method_start)
        method_source = source[method_start:method_end]

        self.assertIn("result = cleanup_partial_download_files(task)", method_source)
        self.assertIn("if can_retry:", method_source)
        self.assertIn("QTimer.singleShot(", method_source)
        self.assertNotIn("retry_needed =", method_source)
        self.assertNotIn("if retry_needed and can_retry:", method_source)


if __name__ == "__main__":
    unittest.main()
