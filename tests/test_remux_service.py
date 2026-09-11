from __future__ import annotations

import unittest

from core.local_media_info import (
    AudioTrackInfo,
    MediaChapter,
    MediaFileInfo,
    OtherTrackInfo,
    SubtitleTrackInfo,
    VideoTrackInfo,
)
from services.remux_service import (
    RemuxError,
    RemuxService,
    assess_remux_compatibility,
    build_remux_command,
)


def _media(
    name: str = "input.mkv",
    video: str = "h264",
    audio: str = "aac",
    subtitle: str = "",
    other: tuple[OtherTrackInfo, ...] = (),
    chapters: int = 0,
) -> MediaFileInfo:
    subtitle_tracks = (
        (SubtitleTrackInfo(index=2, codec_name=subtitle),)
        if subtitle
        else ()
    )
    chapter_items = tuple(
        MediaChapter(
            index=index,
            start_seconds=index * 10.0,
            end_seconds=(index + 1) * 10.0,
        )
        for index in range(chapters)
    )
    return MediaFileInfo(
        path=f"C:/temp/{name}",
        file_name=name,
        size_bytes=1000,
        duration_seconds=100.0,
        video_tracks=(
            (VideoTrackInfo(index=0, codec_name=video),)
            if video
            else ()
        ),
        audio_tracks=(
            (AudioTrackInfo(index=1, codec_name=audio),)
            if audio
            else ()
        ),
        subtitle_tracks=subtitle_tracks,
        other_tracks=other,
        chapters=chapter_items,
    )


class RemuxServiceTests(unittest.TestCase):
    def test_h264_aac_mkv_can_remux_to_mp4(self) -> None:
        result = assess_remux_compatibility(_media(), "mp4")
        self.assertTrue(result.supported)

    def test_srt_blocks_strict_mp4_remux(self) -> None:
        result = assess_remux_compatibility(_media(subtitle="subrip"), "mp4")
        self.assertFalse(result.supported)
        self.assertIn("자막", result.summary)

    def test_webm_vp9_opus_can_remux_to_mkv(self) -> None:
        result = assess_remux_compatibility(
            _media("input.webm", "vp9", "opus"),
            "mkv",
        )
        self.assertTrue(result.supported)

    def test_same_container_is_not_offered(self) -> None:
        result = assess_remux_compatibility(_media("input.mkv"), "mkv")
        self.assertFalse(result.supported)
        self.assertIn("이미 MKV", result.summary)

    def test_data_track_is_blocked(self) -> None:
        other = OtherTrackInfo(
            index=3,
            codec_type="data",
            codec_name="bin_data",
        )
        result = assess_remux_compatibility(_media(other=(other,)), "mkv")
        self.assertFalse(result.supported)

    def test_attachment_is_allowed_in_mkv(self) -> None:
        other = OtherTrackInfo(
            index=3,
            codec_type="attachment",
            codec_name="ttf",
        )
        result = assess_remux_compatibility(
            _media("input.mp4", other=(other,)),
            "mkv",
        )
        self.assertTrue(result.supported)

    def test_command_preserves_streams_metadata_and_chapters(self) -> None:
        command = build_remux_command("ffmpeg", "in.mkv", "out.mp4")
        self.assertEqual(command[command.index("-c") + 1], "copy")
        self.assertEqual(command[command.index("-map") + 1], "0")
        self.assertEqual(command[command.index("-map_metadata") + 1], "0")
        self.assertEqual(command[command.index("-map_chapters") + 1], "0")
        self.assertEqual(command[-1], "out.mp4")

    def test_result_verification_accepts_matching_streams(self) -> None:
        source = _media(chapters=2)
        output = MediaFileInfo(
            path="C:/temp/out.mp4",
            file_name="out.mp4",
            size_bytes=900,
            duration_seconds=100.4,
            video_tracks=source.video_tracks,
            audio_tracks=source.audio_tracks,
            chapters=source.chapters,
        )
        RemuxService._verify_output(source, output)

    def test_result_verification_rejects_missing_stream(self) -> None:
        source = _media()
        output = MediaFileInfo(
            path="C:/temp/out.mp4",
            file_name="out.mp4",
            size_bytes=900,
            duration_seconds=100.0,
            video_tracks=source.video_tracks,
        )
        with self.assertRaises(RemuxError):
            RemuxService._verify_output(source, output)


if __name__ == "__main__":
    unittest.main()
