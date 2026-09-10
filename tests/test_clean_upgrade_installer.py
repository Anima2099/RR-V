from __future__ import annotations

from pathlib import Path
import unittest


class CleanUpgradeInstallerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.installer = (root / "installer" / "RR-V.iss").read_text(encoding="utf-8")
        cls.builder = (root / "BUILD_INSTALLER.ps1").read_text(encoding="utf-8")

    def test_upgrade_reset_option_is_visible_only_for_existing_install(self) -> None:
        self.assertIn("CreateInputOptionPage", self.installer)
        self.assertIn("'RR-V 업데이트 옵션'", self.installer)
        self.assertIn("wpSelectDir", self.installer)
        self.assertIn(
            "설정, 로그인, 프리셋 및 다운로드 도구도 초기화",
            self.installer,
        )
        self.assertIn("UpgradeOptionsPage.Values[0] := False", self.installer)
        self.assertIn(
            "Result := not PreviousInstallDetected",
            self.installer,
        )

    def test_reset_is_opt_in_and_preserves_data_by_default(self) -> None:
        self.assertIn(
            "ResetUserDataOnUpgrade := PreviousInstallDetected and",
            self.installer,
        )
        self.assertIn("if ResetUserDataOnUpgrade then", self.installer)
        reset_gate = self.installer.index("if ResetUserDataOnUpgrade then")
        remove_user_data = self.installer.index("RemoveUserData;", reset_gate)
        self.assertLess(reset_gate, remove_user_data)

    def test_reset_removes_only_rrv_managed_data_and_registrations(self) -> None:
        self.assertIn(
            "DelTree(ExpandConstant('{localappdata}\\RR-V'), True, True, True)",
            self.installer,
        )
        self.assertIn(
            "DelTree(ExpandConstant('{userappdata}\\RR-V'), True, True, True)",
            self.installer,
        )
        self.assertIn("Software\\RR-V", self.installer)
        self.assertIn("NativeMessagingHosts\\com.rrv.browser_bridge", self.installer)
        self.assertNotIn("DelTree(ExpandConstant('{app}')", self.installer)
        self.assertNotIn("DelTree(ExpandConstant('{userdocs}')", self.installer)

    def test_clean_payload_is_armed_before_new_rrv_exe_is_installed(self) -> None:
        install_step = self.installer.index("if CurStep = ssInstall then")
        post_step = self.installer.index("if CurStep = ssPostInstall then")
        arm = self.installer.index("CleanPreviousAppPayload :=", install_step)
        old_exe_check = self.installer.index(
            "FileExists(ExpandConstant('{app}\\RR-V.exe'))",
            arm,
        )
        cleanup = self.installer.index("RemoveStaleApplicationPayload;", post_step)
        self.assertLess(install_step, arm)
        self.assertLess(arm, old_exe_check)
        self.assertLess(old_exe_check, post_step)
        self.assertLess(post_step, cleanup)

    def test_stale_cleaner_uses_manifest_and_preserves_uninstaller_files(self) -> None:
        self.assertIn("InstallManifestName = 'RRV_INSTALL_MANIFEST.txt'", self.installer)
        self.assertIn("LoadStringsFromFile(ManifestPath, Entries)", self.installer)
        self.assertIn("not ManifestContains(Entries, RelativePath)", self.installer)
        self.assertIn("not IsUninstallerArtifact(RelativePath)", self.installer)
        self.assertIn("Result := Pos('unins', LowerName) = 1", self.installer)

    def test_stale_cleaner_never_traverses_reparse_points(self) -> None:
        self.assertIn("FILE_ATTRIBUTE_REPARSE_POINT", self.installer)
        reparse = self.installer.index("FILE_ATTRIBUTE_REPARSE_POINT")
        recurse = self.installer.index("RemoveStalePayloadInDirectory(RootDir, FullPath", reparse)
        self.assertLess(reparse, recurse)

    def test_builder_generates_exact_install_payload_manifest(self) -> None:
        self.assertIn('$InstallManifestName = "RRV_INSTALL_MANIFEST.txt"', self.builder)
        self.assertIn("Get-ChildItem -Path $DistRoot -Recurse -File", self.builder)
        self.assertIn("$ManifestEntries += $InstallManifestName", self.builder)
        self.assertIn("[System.IO.File]::WriteAllLines", self.builder)
        self.assertIn('$ManifestEntries -contains "RR-V.exe"', self.builder)

    def test_installer_keeps_same_appid_for_upgrade_uninstall_log(self) -> None:
        self.assertIn(
            "AppId={{A9C3916B-6AA2-4FB8-9BCB-0D5DC6C5D8D4}",
            self.installer,
        )
        self.assertIn("UsePreviousAppDir=yes", self.installer)
        self.assertIn("UninstallDisplayName=RR-V {#MyAppVersion}", self.installer)


if __name__ == "__main__":
    unittest.main()
