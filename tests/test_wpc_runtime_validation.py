from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import paths
from app.wpc_runtime_validation import (
    repair_nodriver_network_encoding,
    validate_wpc_source_tree,
    wpc_critical_sources_valid,
)


class WpcRuntimeValidationTests(unittest.TestCase):
    @staticmethod
    def _runtime(root: Path, network_source: bytes = b"# JSON (+Inf)\nVALUE = 1\n") -> Path:
        plugin = root / "yt_dlp_plugins" / "extractor" / "getpot_wpc.py"
        plugin.parent.mkdir(parents=True)
        plugin.write_text("import sys\n", encoding="utf-8")
        init = root / "nodriver" / "__init__.py"
        init.parent.mkdir(parents=True)
        init.write_text("VERSION = '0.50.3'\n", encoding="utf-8")
        network = root / "nodriver" / "cdp" / "network.py"
        network.parent.mkdir(parents=True)
        network.write_bytes(network_source)
        return root

    def test_valid_source_is_unchanged_and_generates_no_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._runtime(Path(folder))
            before = (root / "nodriver/cdp/network.py").read_bytes()
            self.assertEqual(repair_nodriver_network_encoding(root), 0)
            self.assertEqual(validate_wpc_source_tree(root), 3)
            self.assertTrue(wpc_critical_sources_valid(root))
            self.assertEqual((root / "nodriver/cdp/network.py").read_bytes(), before)
            self.assertEqual(list(root.rglob("*.pyc")), [])

    def test_only_invalid_cp1252_plus_minus_in_comment_is_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            raw = b"# JSON (\xb1Inf)\n# UTF8: \xc2\xb1\nVALUE = 1\n"
            root = self._runtime(Path(folder), raw)
            self.assertFalse(wpc_critical_sources_valid(root))
            self.assertEqual(repair_nodriver_network_encoding(root), 1)
            self.assertEqual((root / "nodriver/cdp/network.py").read_bytes(), b"# JSON (\xc2\xb1Inf)\n# UTF8: \xc2\xb1\nVALUE = 1\n")
            self.assertEqual(validate_wpc_source_tree(root), 3)
            self.assertEqual(repair_nodriver_network_encoding(root), 0)

    def test_unknown_invalid_byte_is_rejected_without_rewriting_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            raw = b"# corrupt \xff\nVALUE = 1\n"
            root = self._runtime(Path(folder), raw)
            with self.assertRaisesRegex(ValueError, "Unexpected non-UTF-8"):
                repair_nodriver_network_encoding(root)
            self.assertEqual((root / "nodriver/cdp/network.py").read_bytes(), raw)

    def test_invalid_byte_outside_comment_is_not_auto_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            raw = b"VALUE = b'\xb1'\n"
            root = self._runtime(Path(folder), raw)
            with self.assertRaisesRegex(ValueError, "Unexpected non-UTF-8"):
                repair_nodriver_network_encoding(root)
            self.assertEqual((root / "nodriver/cdp/network.py").read_bytes(), raw)

    def test_other_python_syntax_errors_fail_validation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._runtime(Path(folder))
            (root / "some_module.py").write_text("def broken(:\n", encoding="utf-8")
            self.assertTrue(wpc_critical_sources_valid(root))
            with self.assertRaisesRegex(ValueError, "some_module.py"):
                validate_wpc_source_tree(root)

    def test_missing_network_source_is_not_reported_as_ready(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._runtime(Path(folder))
            (root / "nodriver/cdp/network.py").unlink()
            self.assertFalse(wpc_critical_sources_valid(root))
            with self.assertRaisesRegex(ValueError, "Missing WPC"):
                validate_wpc_source_tree(root)

    def test_build_marker_upgrade_copies_fixed_runtime_once(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundled = self._runtime(root / "bundled")
            installed = root / "installed"
            self._runtime(installed, b"# JSON (\xb1Inf)\n")
            marker = root / "marker"
            marker.write_text("\ufeff1.1.2\n", encoding="utf-8")
            provider = root / "provider"
            with (
                patch.object(paths, "BUNDLED_WPC_RUNTIME_DIR", bundled),
                patch.object(paths, "RRV_WPC_RUNTIME_DIR", installed),
                patch.object(paths, "RRV_WPC_PROVIDER_DIR", provider),
                patch.object(paths, "_WPC_PROVIDER_MARKER", marker),
                patch.object(paths.shutil, "copytree", wraps=paths.shutil.copytree) as copytree,
            ):
                self.assertTrue(paths.bootstrap_runtime_wpc_provider())
                self.assertTrue(wpc_critical_sources_valid(installed))
                self.assertEqual(marker.read_text(encoding="utf-8").strip(), paths.WPC_RUNTIME_BUILD_ID)
                copied_after_upgrade = copytree.call_count
                self.assertTrue(paths.bootstrap_runtime_wpc_provider())
                self.assertEqual(copytree.call_count, copied_after_upgrade)

    def test_damaged_bundle_is_not_copied_over_existing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundled = self._runtime(root / "bundled", b"# JSON (\xb1Inf)\n")
            installed = self._runtime(root / "installed")
            marker = root / "marker"
            marker.write_text("1.1.2\n", encoding="utf-8")
            with (
                patch.object(paths, "BUNDLED_WPC_RUNTIME_DIR", bundled),
                patch.object(paths, "RRV_WPC_RUNTIME_DIR", installed),
                patch.object(paths, "RRV_WPC_PROVIDER_DIR", root / "provider"),
                patch.object(paths, "_WPC_PROVIDER_MARKER", marker),
            ):
                self.assertFalse(paths.bootstrap_runtime_wpc_provider())
                self.assertTrue(wpc_critical_sources_valid(installed))


if __name__ == "__main__":
    unittest.main()
