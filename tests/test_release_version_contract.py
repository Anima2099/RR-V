from __future__ import annotations

from pathlib import Path
import re
import unittest


class ReleaseVersionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.constants = (cls.root / "app" / "constants.py").read_text(encoding="utf-8")
        cls.version_info = (cls.root / "RR-V.version_info.txt").read_text(encoding="utf-8")
        cls.installer = (cls.root / "installer" / "RR-V.iss").read_text(encoding="utf-8")
        cls.release_builder = (cls.root / "BUILD_RELEASE.ps1").read_text(encoding="utf-8")
        cls.checklist = (cls.root / "PACKAGING_CHECKLIST.txt").read_text(encoding="utf-8")

    def test_app_runtime_and_display_versions_are_1_4_0(self) -> None:
        self.assertRegex(self.constants, r'(?m)^APP_VERSION\s*=\s*"1\.4\.0"$')
        self.assertRegex(
            self.constants,
            r'(?m)^APP_DISPLAY_VERSION\s*=\s*"1\.4\.0"$',
        )
        self.assertRegex(
            self.constants,
            r'(?m)^APP_RELEASE_CHANNEL\s*=\s*"beta"$',
        )

    def test_windows_exe_version_metadata_matches_1_4_0(self) -> None:
        self.assertIn("filevers=(1, 4, 0, 0)", self.version_info)
        self.assertIn("prodvers=(1, 4, 0, 0)", self.version_info)
        self.assertIn("StringStruct('FileVersion', '1.4.0')", self.version_info)
        self.assertIn("StringStruct('ProductVersion', '1.4.0')", self.version_info)

    def test_inno_installer_version_matches_1_4_0(self) -> None:
        self.assertRegex(
            self.installer,
            r'(?m)^#define\s+MyAppVersion\s+"1\.4\.0"$',
        )
        self.assertIn("OutputBaseFilename=RR-V_Setup_{#MyAppVersion}", self.installer)

    def test_release_builder_reads_app_version_and_checks_version_info(self) -> None:
        self.assertIn('$ConstantsPath = Join-Path $Root "app\\constants.py"', self.release_builder)
        self.assertIn('$VersionInfoPath = Join-Path $Root "RR-V.version_info.txt"', self.release_builder)
        self.assertIn("$AppVersionMatch = [regex]::Match", self.release_builder)
        self.assertIn("RR-V.version_info.txt does not match APP_VERSION", self.release_builder)
        self.assertIn('"RR-V $AppVersion build license manifest"', self.release_builder)
        self.assertNotIn("RR-V 1.3.0 build license manifest", self.release_builder)

    def test_packaging_checklist_targets_1_4_0_upgrade(self) -> None:
        first_line = self.checklist.splitlines()[0]
        self.assertEqual(first_line, "RR-V 1.4.0 community beta release checklist")
        self.assertIn("Clean upgrade regression: 1.3.0 -> 1.4.0", self.checklist)
        self.assertIn("installer-output\\RR-V_Setup_1.4.0.exe", self.checklist)


if __name__ == "__main__":
    unittest.main()
