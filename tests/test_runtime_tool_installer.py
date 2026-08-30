from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import app.runtime_tool_installer as runtime_tool_installer


class RuntimeToolInstallerTests(unittest.TestCase):
    @staticmethod
    def _pot_status(*, available: bool, version: str):
        return SimpleNamespace(key="pot", available=available, version=version)

    def test_ensure_wpc_runtime_skips_restore_when_integrity_is_healthy(self) -> None:
        healthy = self._pot_status(
            available=True,
            version="WPC 1.1.2 + nodriver",
        )
        with (
            patch.object(runtime_tool_installer, "inspect_tools", return_value=(healthy,)),
            patch.object(runtime_tool_installer, "restore_bundled_wpc_provider") as restore,
        ):
            ok, message = runtime_tool_installer.ensure_wpc_runtime()

        self.assertTrue(ok)
        self.assertIn("무결성 정상", message)
        restore.assert_not_called()

    def test_ensure_wpc_runtime_repairs_damaged_runtime_and_rechecks_integrity(self) -> None:
        damaged = self._pot_status(
            available=False,
            version="손상 또는 불완전",
        )
        healthy = self._pot_status(
            available=True,
            version="WPC 1.1.2 + nodriver",
        )
        with (
            patch.object(
                runtime_tool_installer,
                "inspect_tools",
                side_effect=((damaged,), (healthy,)),
            ),
            patch.object(
                runtime_tool_installer,
                "restore_bundled_wpc_provider",
                return_value=True,
            ) as restore,
        ):
            ok, message = runtime_tool_installer.ensure_wpc_runtime()

        self.assertTrue(ok)
        self.assertIn("SHA-256 확인 완료", message)
        restore.assert_called_once_with()

    def test_ensure_wpc_runtime_reports_restore_failure(self) -> None:
        damaged = self._pot_status(
            available=False,
            version="손상 또는 불완전",
        )
        with (
            patch.object(runtime_tool_installer, "inspect_tools", return_value=(damaged,)),
            patch.object(
                runtime_tool_installer,
                "restore_bundled_wpc_provider",
                return_value=False,
            ),
        ):
            ok, message = runtime_tool_installer.ensure_wpc_runtime()

        self.assertFalse(ok)
        self.assertIn("복구하지 못했습니다", message)

    def test_ensure_runtime_tools_includes_wpc_integrity_check(self) -> None:
        with (
            patch.object(runtime_tool_installer, "ensure_ytdlp", return_value=(True, "yt")) as ytdlp,
            patch.object(
                runtime_tool_installer,
                "update_ffmpeg_release",
                return_value=(True, "ff"),
            ) as ffmpeg,
            patch.object(runtime_tool_installer, "ensure_deno", return_value=(True, "deno")) as deno,
            patch.object(
                runtime_tool_installer,
                "ensure_wpc_runtime",
                return_value=(True, "wpc"),
            ) as wpc,
        ):
            ok, message = runtime_tool_installer.ensure_runtime_tools()

        self.assertTrue(ok)
        self.assertIn("✓ wpc", message)
        ytdlp.assert_called_once_with(None)
        ffmpeg.assert_called_once_with(None)
        deno.assert_called_once_with(None)
        wpc.assert_called_once_with(None)


if __name__ == "__main__":
    unittest.main()
