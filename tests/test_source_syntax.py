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


if __name__ == "__main__":
    unittest.main()
