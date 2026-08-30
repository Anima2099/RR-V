from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import app.runtime_tool_installer as runtime_tool_installer


class RuntimeToolInstallerTests(unittest.TestCase):
    @staticmethod
    def _status(key: str, *, available: bool, version: str):
        return SimpleNamespace(key=key, available=available, version=version)

    @classmethod
    def _pot_status(cls, *, available: bool, version: str):
        return cls._status("pot", available=available, version=version)

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

    def test_ensure_runtime_tools_includes_support_diagnostic_blocks(self) -> None:
        statuses = (
            self._status("ytdlp", available=True, version="2026.08.30"),
            self._status("ffmpeg", available=True, version="9.0.1"),
            self._status("ffprobe", available=True, version="9.0.1"),
            self._status("deno", available=True, version="deno 2.9.6"),
            self._pot_status(available=True, version="WPC 1.1.2 + nodriver"),
        )
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
            patch.object(runtime_tool_installer, "inspect_tools", return_value=statuses),
        ):
            ok, message = runtime_tool_installer.ensure_runtime_tools()

        self.assertTrue(ok)
        self.assertIn("[yt-dlp Nightly]", message)
        self.assertIn("[YouTube 인증 런타임]", message)
        self.assertIn("처리 결과: 성공", message)
        self.assertIn("최종 상태: 정상", message)
        self.assertIn("진단 코드: WPC_OK", message)
        ytdlp.assert_called_once_with(None)
        ffmpeg.assert_called_once_with(None)
        deno.assert_called_once_with(None)
        wpc.assert_called_once_with(None)

    def test_diagnostic_code_reports_ytdlp_hash_mismatch(self) -> None:
        code = runtime_tool_installer._diagnostic_code(
            "yt-dlp Nightly",
            False,
            "업데이트 후 SHA-256이 공식 릴리스와 일치하지 않습니다.",
        )
        self.assertEqual(code, "YTDLP_HASH_MISMATCH")

    def test_diagnostic_code_reports_wpc_restore_failure(self) -> None:
        code = runtime_tool_installer._diagnostic_code(
            "YouTube 인증 런타임",
            False,
            "YouTube 인증 런타임 검증본을 복구하지 못했습니다.",
        )
        self.assertEqual(code, "WPC_RESTORE_FAILED")

    def test_diagnostic_code_reports_successful_wpc_restore(self) -> None:
        code = runtime_tool_installer._diagnostic_code(
            "YouTube 인증 런타임",
            True,
            "WPC 1.1.2 검증본 복구 및 SHA-256 확인 완료",
        )
        self.assertEqual(code, "WPC_RESTORE_OK")

    def test_final_status_text_distinguishes_missing_and_repair(self) -> None:
        missing = self._status("ytdlp", available=False, version="없음")
        damaged = self._pot_status(available=False, version="손상 또는 불완전")

        self.assertEqual(
            runtime_tool_installer._final_status_text(
                "yt-dlp Nightly",
                {"ytdlp": missing},
            ),
            "설치 필요 · 파일 없음",
        )
        self.assertEqual(
            runtime_tool_installer._final_status_text(
                "YouTube 인증 런타임",
                {"pot": damaged},
            ),
            "복구 필요 · 손상 또는 불완전",
        )

    def test_format_diagnostic_block_keeps_multiline_detail_readable(self) -> None:
        healthy = self._status("deno", available=True, version="deno 2.9.6")
        block = runtime_tool_installer._format_diagnostic_block(
            "Deno",
            True,
            "Current Deno version: v2.9.6\nLooking up stable version",
            {"deno": healthy},
        )

        self.assertIn("검사/작업 상세:\n  Current Deno version", block)
        self.assertIn("\n  Looking up stable version", block)
        self.assertIn("진단 코드: DENO_OK", block)


if __name__ == "__main__":
    unittest.main()
