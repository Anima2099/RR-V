from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.download_task import DownloadStatus, DownloadTask
from services.download_service import YtDlpDownloadService
from services.ytdlp_service import YtDlpService
from ui.dialogs.subtitle_selection_dialog import default_subtitle_selection


class YtDlpSubtitleFilterTests(unittest.TestCase):
    def test_non_caption_tracks_are_excluded_from_language_lists(self) -> None:
        info = {
            "subtitles": {
                "live_chat": [{"ext": "json"}],
                "COMMENTS": [{"ext": "json"}],
                "danmaku": [{"ext": "xml"}],
                "en": [{"ext": "vtt"}],
                "ja": [{"ext": "vtt"}],
            },
            "automatic_captions": {
                "ko": [{"ext": "vtt"}],
                "live-chat": [{"ext": "json"}],
            },
        }

        manual, automatic = YtDlpService._extract_subtitle_languages(info)

        self.assertEqual(manual, ("en", "ja"))
        self.assertEqual(automatic, ("ko",))

    def test_only_live_chat_does_not_become_manual_subtitle_fallback(self) -> None:
        info = {
            "subtitles": {
                "live_chat": [{"ext": "json"}],
            },
            "automatic_captions": {},
        }

        manual, automatic = YtDlpService._extract_subtitle_languages(info)
        selection = default_subtitle_selection(
            manual,
            automatic,
            preferred_bases=("ko",),
            allow_automatic=True,
        )

        self.assertEqual(manual, ())
        self.assertEqual(automatic, ())
        self.assertTrue(selection.is_empty)

    def test_command_stage_filters_legacy_non_caption_tracks(self) -> None:
        service = YtDlpDownloadService()
        service.executable = Path("yt-dlp.exe")
        service.ffmpeg = None

        with tempfile.TemporaryDirectory() as temp_dir:
            task = DownloadTask(
                task_id="legacy-live-chat",
                title="legacy subtitle task",
                url="https://example.invalid/video",
                status=DownloadStatus.QUEUED,
                save_path=temp_dir,
                subtitle_tracks=(
                    "manual:live_chat",
                    "manual:COMMENTS",
                    "auto:danmaku",
                    "manual:en",
                    "auto:ko",
                ),
            )
            with patch.object(
                YtDlpService,
                "extend_runtime_and_auth_arguments",
            ):
                command = service._build_command(
                    task,
                    Path(temp_dir),
                    "legacy-subtitle-test",
                    overwrite_existing=False,
                )

        sub_langs_index = command.index("--sub-langs")
        self.assertEqual(command[sub_langs_index + 1], "en,ko")
        self.assertNotIn("live_chat", command)
        self.assertNotIn("COMMENTS", command)
        self.assertNotIn("danmaku", command)

    def test_command_stage_does_not_enable_subtitles_for_only_live_chat(self) -> None:
        service = YtDlpDownloadService()
        service.executable = Path("yt-dlp.exe")
        service.ffmpeg = None

        with tempfile.TemporaryDirectory() as temp_dir:
            task = DownloadTask(
                task_id="legacy-live-chat-only",
                title="legacy live chat only",
                url="https://example.invalid/video",
                status=DownloadStatus.QUEUED,
                save_path=temp_dir,
                subtitle_tracks=("manual:live-chat",),
            )
            with patch.object(
                YtDlpService,
                "extend_runtime_and_auth_arguments",
            ):
                command = service._build_command(
                    task,
                    Path(temp_dir),
                    "legacy-live-chat-only",
                    overwrite_existing=False,
                )

        self.assertNotIn("--write-subs", command)
        self.assertNotIn("--write-auto-subs", command)
        self.assertNotIn("--sub-langs", command)

    def test_normal_language_codes_are_preserved(self) -> None:
        info = {
            "subtitles": {
                "zh-Hans": [{"ext": "vtt"}],
                "pt-BR": [{"ext": "vtt"}],
                "en-orig": [{"ext": "vtt"}],
            }
        }

        manual, automatic = YtDlpService._extract_subtitle_languages(info)

        self.assertEqual(manual, ("en-orig", "pt-BR", "zh-Hans"))
        self.assertEqual(automatic, ())


if __name__ == "__main__":
    unittest.main()
