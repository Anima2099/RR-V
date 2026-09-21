from __future__ import annotations

from pathlib import Path
import re
import unittest

from app.constants import APP_DISPLAY_VERSION, APP_RELEASE_CHANNEL, APP_VERSION


class ReleaseVersionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.constants = (cls.root / "app" / "constants.py").read_text(encoding="utf-8")
        cls.version_info = (cls.root / "RR-V.version_info.txt").read_text(encoding="utf-8")
        cls.installer = (cls.root / "installer" / "RR-V.iss").read_text(encoding="utf-8")
        cls.release_builder = (cls.root / "BUILD_RELEASE.ps1").read_text(encoding="utf-8")
        cls.checklist = (cls.root / "PACKAGING_CHECKLIST.txt").read_text(encoding="utf-8")

    def test_runtime_display_version_and_release_channel_are_valid(self) -> None:
        self.assertEqual(APP_VERSION, APP_DISPLAY_VERSION)
        self.assertIn(APP_RELEASE_CHANNEL, {"beta", "stable"})
        self.assertRegex(
            self.constants,
            rf'(?m)^APP_VERSION\s*=\s*"{re.escape(APP_VERSION)}"$',
        )
        self.assertRegex(
            self.constants,
            rf'(?m)^APP_DISPLAY_VERSION\s*=\s*"{re.escape(APP_VERSION)}"$',
        )
        self.assertRegex(
            self.constants,
            rf'(?m)^APP_RELEASE_CHANNEL\s*=\s*"{re.escape(APP_RELEASE_CHANNEL)}"$',
        )

    def test_windows_exe_version_metadata_matches_app_version(self) -> None:
        parts = tuple(int(part) for part in APP_VERSION.split("."))
        self.assertEqual(len(parts), 3)
        version_tuple = f"({parts[0]}, {parts[1]}, {parts[2]}, 0)"
        self.assertIn(f"filevers={version_tuple}", self.version_info)
        self.assertIn(f"prodvers={version_tuple}", self.version_info)
        self.assertIn(
            f"StringStruct('FileVersion', '{APP_VERSION}')",
            self.version_info,
        )
        self.assertIn(
            f"StringStruct('ProductVersion', '{APP_VERSION}')",
            self.version_info,
        )

    def test_inno_installer_version_matches_app_version(self) -> None:
        self.assertRegex(
            self.installer,
            rf'(?m)^#define\s+MyAppVersion\s+"{re.escape(APP_VERSION)}"$',
        )
        self.assertIn("OutputBaseFilename=RR-V_Setup_{#MyAppVersion}", self.installer)

    def test_release_builder_reads_app_version_and_checks_version_info(self) -> None:
        self.assertIn('$ConstantsPath = Join-Path $Root "app\\constants.py"', self.release_builder)
        self.assertIn('$VersionInfoPath = Join-Path $Root "RR-V.version_info.txt"', self.release_builder)
        self.assertIn("$AppVersionMatch = [regex]::Match", self.release_builder)
        self.assertIn("RR-V.version_info.txt does not match APP_VERSION", self.release_builder)
        self.assertIn('"RR-V $AppVersion build license manifest"', self.release_builder)
        self.assertNotIn("RR-V 1.3.0 build license manifest", self.release_builder)

    def test_next_stable_release_checklist_is_prepared(self) -> None:
        first_line = self.checklist.splitlines()[0]
        self.assertEqual(first_line, "RR-V 1.5.0 Stable release checklist")
        self.assertIn("Release channel: stable", self.checklist)
        self.assertIn("Previous public release: 1.4.1 Community Beta", self.checklist)
        self.assertIn("Clean upgrade regression: 1.4.1 -> 1.5.0", self.checklist)
        self.assertIn("installer-output\\RR-V_Setup_1.5.0.exe", self.checklist)
        self.assertIn("GitHub Release prerelease flag: OFF", self.checklist)
        self.assertIn('A failed task shows "에러 로그 저장하기"', self.checklist)


if __name__ == "__main__":
    unittest.main()
