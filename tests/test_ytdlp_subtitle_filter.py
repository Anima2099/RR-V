from __future__ import annotations

import unittest

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
