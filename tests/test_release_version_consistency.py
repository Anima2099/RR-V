from __future__ import annotations

import re
import unittest
from pathlib import Path

from app.constants import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]


class ReleaseVersionConsistencyTests(unittest.TestCase):
    def test_windows_version_info_matches_app_version(self) -> None:
        text = (ROOT / "RR-V.version_info.txt").read_text(encoding="utf-8")
        version_tuple = tuple(int(part) for part in APP_VERSION.split(".")) + (0,)
        self.assertIn(f"filevers={version_tuple}", text)
        self.assertIn(f"prodvers={version_tuple}", text)
        self.assertIn(f"StringStruct('FileVersion', '{APP_VERSION}')", text)
        self.assertIn(f"StringStruct('ProductVersion', '{APP_VERSION}')", text)

    def test_inno_installer_matches_app_version_and_filename_contract(self) -> None:
        text = (ROOT / "installer" / "RR-V.iss").read_text(encoding="utf-8")
        match = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', text)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), APP_VERSION)  # type: ignore[union-attr]
        self.assertIn("OutputBaseFilename=RR-V_Setup_{#MyAppVersion}", text)
        self.assertIn("UninstallDisplayName=RR-V {#MyAppVersion}", text)

    def test_installer_build_reads_app_version_instead_of_fixed_filename(self) -> None:
        text = (ROOT / "BUILD_INSTALLER.ps1").read_text(encoding="utf-8")
        self.assertIn("APP_VERSION", text)
        self.assertIn('"RR-V_Setup_" + $AppVersion + ".exe"', text)
        self.assertNotIn("RR-V_Setup_1.2.0.exe", text)


if __name__ == "__main__":
    unittest.main()
