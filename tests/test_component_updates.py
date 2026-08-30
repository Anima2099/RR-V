from __future__ import annotations

import sys
from types import ModuleType
import unittest


# component_updates의 순수 버전 처리 로직만 검사한다.
# RR-V GUI 런타임(PySide6)이나 실제 외부 도구 설치 여부가 테스트 실행 환경에
# 영향을 주지 않도록, import 순간에 필요한 두 모듈만 가벼운 테스트 대역으로 둔다.
# 다른 테스트가 실제 app.tool_manager / app.settings_store를 import할 수 있도록
# component_updates import가 끝난 즉시 sys.modules를 원래 상태로 되돌린다.
_previous_settings_store = sys.modules.get("app.settings_store")
_previous_tool_manager = sys.modules.get("app.tool_manager")

_settings_store_stub = ModuleType("app.settings_store")
_settings_store_stub.get_settings = lambda: None
_tool_manager_stub = ModuleType("app.tool_manager")
_tool_manager_stub.inspect_tools = lambda: ()

sys.modules["app.settings_store"] = _settings_store_stub
sys.modules["app.tool_manager"] = _tool_manager_stub

try:
    from app.component_updates import (  # noqa: E402
        _local_signature,
        _normalize_ytdlp_version,
        _release_tuple,
        normalize_ffmpeg_release_version,
    )
finally:
    if _previous_settings_store is None:
        sys.modules.pop("app.settings_store", None)
    else:
        sys.modules["app.settings_store"] = _previous_settings_store

    if _previous_tool_manager is None:
        sys.modules.pop("app.tool_manager", None)
    else:
        sys.modules["app.tool_manager"] = _previous_tool_manager


class ComponentUpdateTests(unittest.TestCase):
    def test_normalize_ytdlp_version_extracts_date_version(self) -> None:
        self.assertEqual(
            _normalize_ytdlp_version("yt-dlp nightly@2026.08.30.123456"),
            "2026.08.30.123456",
        )

    def test_normalize_ffmpeg_release_version_extracts_version(self) -> None:
        self.assertEqual(
            normalize_ffmpeg_release_version("ffmpeg version 8.0.1-full_build"),
            "8.0.1",
        )

    def test_release_tuple_parses_two_part_version(self) -> None:
        self.assertEqual(_release_tuple("8.0"), (8, 0))

    def test_release_tuple_rejects_non_release_text(self) -> None:
        self.assertIsNone(_release_tuple("git-master-2026-08-30"))

    def test_local_signature_tracks_managed_components(self) -> None:
        installed = {
            "ytdlp": "2026.08.30",
            "ffmpeg": "8.0",
            "ffprobe": "8.0",
            "deno": "2.5.0",
        }
        self.assertEqual(
            _local_signature(installed),
            "2026.08.30|8.0|8.0",
        )


if __name__ == "__main__":
    unittest.main()
