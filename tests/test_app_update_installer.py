from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.app_update import AppInstallerAsset
from app.app_update_installer import (
    download_verified_installer,
    file_sha256,
    verify_installer_file,
)


class AppUpdateInstallerTests(unittest.TestCase):
    @staticmethod
    def _asset(content: bytes, *, size: int | None = None) -> AppInstallerAsset:
        return AppInstallerAsset(
            name="RR-V_Setup_1.4.0.exe",
            url=(
                "https://github.com/Anima2099/RR-V/releases/download/"
                "v1.4.0-community-beta/RR-V_Setup_1.4.0.exe"
            ),
            sha256=hashlib.sha256(content).hexdigest(),
            size=len(content) if size is None else size,
        )

    def test_file_sha256_matches_known_content(self) -> None:
        content = b"rr-v installer test"
        with TemporaryDirectory() as directory:
            path = Path(directory) / "installer.exe"
            path.write_bytes(content)
            self.assertEqual(file_sha256(path), hashlib.sha256(content).hexdigest())

    def test_verify_installer_file_accepts_matching_size_and_hash(self) -> None:
        content = b"verified installer"
        asset = self._asset(content)
        with TemporaryDirectory() as directory:
            path = Path(directory) / asset.name
            path.write_bytes(content)
            ok, message = verify_installer_file(path, asset)
        self.assertTrue(ok)
        self.assertIn("검증을 통과", message)

    def test_verify_installer_file_rejects_size_mismatch(self) -> None:
        content = b"installer"
        asset = self._asset(content, size=len(content) + 1)
        with TemporaryDirectory() as directory:
            path = Path(directory) / asset.name
            path.write_bytes(content)
            ok, message = verify_installer_file(path, asset)
        self.assertFalse(ok)
        self.assertIn("크기가", message)

    def test_verify_installer_file_rejects_hash_mismatch(self) -> None:
        content = b"installer"
        asset = AppInstallerAsset(
            name="RR-V_Setup_1.4.0.exe",
            url="https://github.com/Anima2099/RR-V/releases/download/v1.4.0/RR-V_Setup_1.4.0.exe",
            sha256="0" * 64,
            size=len(content),
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / asset.name
            path.write_bytes(content)
            ok, message = verify_installer_file(path, asset)
        self.assertFalse(ok)
        self.assertIn("SHA-256 검증에 실패", message)

    @patch("app.app_update_installer.download_https_file")
    def test_download_verified_installer_returns_verified_file(self, download) -> None:  # type: ignore[no-untyped-def]
        content = b"downloaded verified installer"
        asset = self._asset(content)

        def fake_download(_url, destination, **_kwargs):  # type: ignore[no-untyped-def]
            Path(destination).write_bytes(content)

        download.side_effect = fake_download
        with TemporaryDirectory() as directory:
            result = download_verified_installer(
                asset,
                destination_dir=Path(directory),
            )
            self.assertTrue(result.ok)
            self.assertIsNotNone(result.path)
            self.assertTrue(Path(result.path).is_file())  # type: ignore[arg-type]

    @patch("app.app_update_installer.download_https_file")
    def test_download_verified_installer_deletes_failed_hash(self, download) -> None:  # type: ignore[no-untyped-def]
        expected = b"expected installer"
        downloaded = b"tampered installer"
        asset = self._asset(expected, size=len(downloaded))

        def fake_download(_url, destination, **_kwargs):  # type: ignore[no-untyped-def]
            Path(destination).write_bytes(downloaded)

        download.side_effect = fake_download
        with TemporaryDirectory() as directory:
            result = download_verified_installer(
                asset,
                destination_dir=Path(directory),
            )
            self.assertFalse(result.ok)
            self.assertFalse((Path(directory) / asset.name).exists())


if __name__ == "__main__":
    unittest.main()
