from __future__ import annotations

import unittest

from services.media_probe_service import parse_media_probe_payload


class MediaProbeParserTests(unittest.TestCase):
    def test_parses_tracks_chapters_and_hdr(self) -> None:
        payload = {
            "format": {
                "format_name": "matroska,webm",
                "format_long_name": "Matroska / WebM",
                "duration": "3723.500000",
                "size": "123",
                "bit_rate": "25000000",
                "start_time": "0.000000",
                "tags": {"title": "Concert", "encoder": "test"},
            },
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "codec_long_name": "H.265 / HEVC",
                    "profile": "Main 10",
                    "codec_tag_string": "[0][0][0][0]",
                    "width": 3840,
                    "height": 2160,
                    "avg_frame_rate": "60000/1001",
                    "r_frame_rate": "60000/1001",
                    "bit_rate": "18000000",
                    "pix_fmt": "yuv420p10le",
                    "color_space": "bt2020nc",
                    "color_transfer": "smpte2084",
                    "color_primaries": "bt2020",
                    "tags": {"language": "jpn", "title": "Main video"},
                    "disposition": {"default": 1, "attached_pic": 0},
                },
                {
                    "index": 1,
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "codec_long_name": "AAC",
                    "sample_rate": "48000",
                    "channels": 2,
                    "channel_layout": "stereo",
                    "bit_rate": "256000",
                    "sample_fmt": "fltp",
                    "tags": {"language": "jpn", "title": "Stereo"},
                    "disposition": {"default": 1},
                },
                {
                    "index": 2,
                    "codec_type": "audio",
                    "codec_name": "eac3",
                    "sample_rate": "48000",
                    "channels": 6,
                    "channel_layout": "5.1(side)",
                    "tags": {"language": "eng"},
                    "disposition": {"default": 0},
                },
                {
                    "index": 3,
                    "codec_type": "subtitle",
                    "codec_name": "subrip",
                    "tags": {"language": "kor", "title": "Korean"},
                    "disposition": {"default": 0, "forced": 1},
                },
                {
                    "index": 4,
                    "codec_type": "attachment",
                    "codec_name": "ttf",
                    "tags": {"filename": "font.ttf"},
                    "disposition": {"default": 0},
                },
            ],
            "chapters": [
                {
                    "id": 0,
                    "start_time": "0.000000",
                    "end_time": "180.250000",
                    "tags": {"title": "Opening"},
                },
                {
                    "id": 1,
                    "start_time": "180.250000",
                    "end_time": "3723.500000",
                    "tags": {"title": "Main"},
                },
            ],
        }

        info = parse_media_probe_payload(
            "D:/Videos/concert.mkv",
            payload,
            file_size_bytes=5_000_000_000,
        )

        self.assertEqual(info.file_name, "concert.mkv")
        self.assertEqual(info.format_names, ("matroska", "webm"))
        self.assertEqual(info.size_bytes, 5_000_000_000)
        self.assertAlmostEqual(info.duration_seconds or 0.0, 3723.5)
        self.assertEqual(info.bit_rate, 25_000_000)
        self.assertEqual(info.stream_count, 5)
        self.assertEqual(len(info.video_tracks), 1)
        self.assertEqual(len(info.audio_tracks), 2)
        self.assertEqual(len(info.subtitle_tracks), 1)
        self.assertEqual(len(info.other_tracks), 1)
        self.assertEqual(len(info.chapters), 2)

        video = info.primary_video
        self.assertIsNotNone(video)
        assert video is not None
        self.assertEqual(video.codec_name, "hevc")
        self.assertEqual(video.resolution_text, "3840×2160")
        self.assertAlmostEqual(video.frame_rate or 0.0, 59.94005994, places=5)
        self.assertEqual(video.dynamic_range, "HDR (PQ)")
        self.assertTrue(video.is_default)
        self.assertEqual(info.chapters[0].title, "Opening")
        self.assertEqual(info.metadata_value("TITLE"), "Concert")

    def test_primary_video_ignores_attached_cover_art(self) -> None:
        payload = {
            "format": {"duration": "12.0"},
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "mjpeg",
                    "width": 600,
                    "height": 600,
                    "disposition": {"attached_pic": 1},
                },
                {
                    "index": 1,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "24000/1001",
                    "disposition": {"attached_pic": 0},
                },
            ],
        }

        info = parse_media_probe_payload("movie.mp4", payload, file_size_bytes=1000)
        self.assertEqual(len(info.video_tracks), 2)
        self.assertEqual(info.primary_video.index if info.primary_video else None, 1)
        self.assertTrue(info.has_video)

    def test_cover_art_only_does_not_count_as_primary_video(self) -> None:
        payload = {
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "mjpeg",
                    "width": 800,
                    "height": 800,
                    "disposition": {"attached_pic": 1},
                },
                {
                    "index": 1,
                    "codec_type": "audio",
                    "codec_name": "flac",
                    "channels": 2,
                    "disposition": {"default": 1},
                },
            ]
        }

        info = parse_media_probe_payload("album.flac", payload, file_size_bytes=100)
        self.assertEqual(len(info.video_tracks), 1)
        self.assertIsNone(info.primary_video)
        self.assertFalse(info.has_video)
        self.assertTrue(info.has_audio)

    def test_audio_only_and_missing_numeric_values_are_safe(self) -> None:
        payload = {
            "format": {
                "format_name": "flac",
                "duration": "N/A",
                "size": "invalid",
                "bit_rate": "N/A",
            },
            "streams": [
                {
                    "index": "0",
                    "codec_type": "audio",
                    "codec_name": "flac",
                    "sample_rate": "48000",
                    "channels": "2",
                    "duration": "241.25",
                    "disposition": {"default": "1"},
                }
            ],
        }

        info = parse_media_probe_payload("song.flac", payload)
        self.assertFalse(info.has_video)
        self.assertTrue(info.has_audio)
        self.assertAlmostEqual(info.duration_seconds or 0.0, 241.25)
        self.assertEqual(info.size_bytes, 0)
        self.assertIsNone(info.bit_rate)
        self.assertEqual(info.audio_tracks[0].sample_rate, 48000)
        self.assertEqual(info.audio_tracks[0].channels, 2)
        self.assertTrue(info.audio_tracks[0].is_default)

    def test_detects_dolby_vision_rotation_and_hlg(self) -> None:
        payload = {
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 1080,
                    "height": 1920,
                    "side_data_list": [
                        {"side_data_type": "DOVI configuration record", "rotation": -90}
                    ],
                    "disposition": {},
                },
                {
                    "index": 1,
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 1920,
                    "height": 1080,
                    "color_transfer": "arib-std-b67",
                    "disposition": {},
                },
            ]
        }

        info = parse_media_probe_payload("hdr.mkv", payload, file_size_bytes=1)
        self.assertEqual(info.video_tracks[0].dynamic_range, "Dolby Vision")
        self.assertEqual(info.video_tracks[0].rotation_degrees, 270)
        self.assertEqual(info.video_tracks[0].resolution_text, "1920×1080")
        self.assertEqual(info.video_tracks[1].dynamic_range, "HDR (HLG)")


if __name__ == "__main__":
    unittest.main()
