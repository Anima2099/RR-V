from __future__ import annotations

from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.filename_metadata_store import FilenameMetadata
from core.download_task import DownloadStatus, DownloadTask
from core.filename_template import (
    DEFAULT_FILENAME_TEMPLATE,
    FILENAME_TEMPLATE_TOKENS,
    codec_filename_label,
    detected_resolution_heights,
    duration_filename_label,
    filename_template_values,
    insert_filename_template_token,
    normalize_filename_template,
    normalize_upload_date,
    render_filename_template,
    resolution_filename_label,
    resolution_height_limit,
    site_label,
    validate_filename_template,
)
from services.templated_download_service import YtDlpDownloadService


ROOT = Path(__file__).resolve().parents[1]


class FilenameTemplateTests(unittest.TestCase):
    def test_empty_template_normalizes_to_title_default(self) -> None:
        self.assertEqual(
            normalize_filename_template("   "),
            DEFAULT_FILENAME_TEMPLATE,
        )

    def test_expanded_token_set_is_registered(self) -> None:
        self.assertEqual(
            set(FILENAME_TEMPLATE_TOKENS),
            {
                "{제목}",
                "{채널명}",
                "{영상ID}",
                "{사이트}",
                "{해상도}",
                "{업로드날짜}",
                "{업로드날짜6}",
                "{재생시간}",
                "{프리셋}",
                "{코덱}",
            },
        )

    def test_render_replaces_supported_tokens(self) -> None:
        values = filename_template_values(
            title="영상 제목",
            uploader="채널 이름",
            video_id="abc123",
            extractor="Youtube",
            resolution="1080p",
            available_resolutions=("1080p", "720p"),
            upload_date="20260909",
            duration_text="12분 34초",
            preset="4K 보관용",
            codec="H.264",
        )
        rendered = render_filename_template(
            "[{업로드날짜}] [{채널명}] {제목} [{영상ID}] "
            "[{사이트}] [{해상도}] [{재생시간}] [{프리셋}] [{코덱}] "
            "[{업로드날짜6}]",
            values,
        )
        self.assertEqual(
            rendered,
            "[20260909] [채널 이름] 영상 제목 [abc123] "
            "[YouTube] [1080p] [12m34s] [4K 보관용] [H264] [260909]",
        )

    def test_unknown_token_is_rejected(self) -> None:
        valid, message = validate_filename_template("{제목} {없는토큰}")
        self.assertFalse(valid)
        self.assertIn("{없는토큰}", message)

    def test_unbalanced_brace_is_rejected(self) -> None:
        valid, message = validate_filename_template("{제목")
        self.assertFalse(valid)
        self.assertIn("중괄호", message)

    def test_inserted_title_is_not_parsed_as_another_token(self) -> None:
        values = filename_template_values(
            title="문자 그대로 {채널명}",
            uploader="실제 채널",
            video_id="id1",
            extractor="Instagram",
        )
        self.assertEqual(
            render_filename_template("{제목}", values),
            "문자 그대로 {채널명}",
        )

    def test_auto_spacing_separates_sequential_token_buttons(self) -> None:
        text, cursor = insert_filename_template_token(
            "{제목}",
            len("{제목}"),
            "{채널명}",
            auto_spacing=True,
        )
        self.assertEqual(text, "{제목} {채널명}")
        self.assertEqual(cursor, len(text))

    def test_auto_spacing_respects_manual_separator(self) -> None:
        source = "[{제목}]_"
        text, _cursor = insert_filename_template_token(
            source,
            len(source),
            "{채널명}",
            auto_spacing=True,
        )
        self.assertEqual(text, "[{제목}]_{채널명}")

    def test_auto_spacing_handles_insertion_between_tokens(self) -> None:
        source = "{제목}{영상ID}"
        text, _cursor = insert_filename_template_token(
            source,
            len("{제목}"),
            "{채널명}",
            auto_spacing=True,
        )
        self.assertEqual(text, "{제목} {채널명} {영상ID}")

    def test_auto_spacing_can_be_disabled(self) -> None:
        text, _cursor = insert_filename_template_token(
            "{제목}",
            len("{제목}"),
            "{채널명}",
            auto_spacing=False,
        )
        self.assertEqual(text, "{제목}{채널명}")

    def test_upload_date_has_eight_and_six_digit_forms(self) -> None:
        self.assertEqual(normalize_upload_date("2026-09-09"), "20260909")
        values = filename_template_values(
            title="제목",
            uploader="채널",
            video_id="id",
            extractor="Youtube",
            upload_date="20260909",
        )
        self.assertEqual(values["업로드날짜"], "20260909")
        self.assertEqual(values["업로드날짜6"], "260909")

    def test_duration_filename_label_is_compact(self) -> None:
        self.assertEqual(duration_filename_label("1시간 02분 03초"), "1h02m03s")
        self.assertEqual(duration_filename_label("12분 34초"), "12m34s")
        self.assertEqual(duration_filename_label("45초"), "45s")

    def test_resolution_helpers_accept_detected_arbitrary_p_values(self) -> None:
        self.assertEqual(resolution_height_limit("360p"), 360)
        self.assertEqual(resolution_height_limit("4K (2160p)"), 2160)
        self.assertIsNone(resolution_height_limit("최고 화질"))
        self.assertEqual(
            detected_resolution_heights(("2160p", "1080p", "720p", "bad")),
            (2160, 1080, 720),
        )

    def test_resolution_label_uses_cached_detected_resolutions(self) -> None:
        self.assertEqual(
            resolution_filename_label(
                "최고 화질",
                available_resolutions=("2160p", "1080p", "720p"),
            ),
            "2160p",
        )
        self.assertEqual(
            resolution_filename_label(
                "1080p",
                available_resolutions=("2160p", "720p"),
            ),
            "720p",
        )

    def test_codec_label_is_filename_friendly_selected_preference(self) -> None:
        self.assertEqual(codec_filename_label("H.264"), "H264")
        self.assertEqual(codec_filename_label("AV1"), "AV1")
        self.assertEqual(codec_filename_label("VP9"), "VP9")

    def test_site_label_normalizes_common_extractors(self) -> None:
        self.assertEqual(site_label("Youtube"), "YouTube")
        self.assertEqual(site_label("Instagram:reel"), "Instagram")
        self.assertEqual(site_label("TikTok"), "TikTok")

    def test_default_template_preserves_instagram_reel_id_fallback(self) -> None:
        task = DownloadTask(
            task_id="task-1",
            title="Video by sample",
            url="https://www.instagram.com/reel/ABC123/",
            status=DownloadStatus.QUEUED,
            video_id="ABC123",
            extractor="Instagram",
            uploader="sample",
        )
        with (
            patch(
                "services.templated_download_service.load_general_preferences",
                return_value=SimpleNamespace(
                    filename_template=DEFAULT_FILENAME_TEMPLATE
                ),
            ),
            patch(
                "services.templated_download_service.load_filename_metadata",
                return_value=FilenameMetadata(),
            ),
        ):
            rendered = YtDlpDownloadService()._filename_title(task)
        self.assertEqual(rendered, "Video by sample [ABC123]")

    def test_explicit_video_id_token_avoids_instagram_id_duplication(self) -> None:
        task = DownloadTask(
            task_id="task-instagram",
            title="Video by sample",
            url="https://www.instagram.com/reel/ABC123/",
            status=DownloadStatus.QUEUED,
            video_id="ABC123",
            extractor="Instagram",
            uploader="sample",
        )
        with (
            patch(
                "services.templated_download_service.load_general_preferences",
                return_value=SimpleNamespace(
                    filename_template="{제목} {영상ID}"
                ),
            ),
            patch(
                "services.templated_download_service.load_filename_metadata",
                return_value=FilenameMetadata(),
            ),
        ):
            rendered = YtDlpDownloadService()._filename_title(task)
        self.assertEqual(rendered, "Video by sample ABC123")

    def test_advanced_tokens_use_cached_initial_analysis_metadata(self) -> None:
        task = DownloadTask(
            task_id="task-advanced",
            title="테스트 영상",
            url="https://www.youtube.com/watch?v=xyz987",
            status=DownloadStatus.QUEUED,
            video_id="xyz987",
            extractor="Youtube",
            uploader="테스트 채널",
            duration_text="12분 34초",
            preset="기본 다운로드",
            resolution="최고 화질",
            container="MP4",
            codec="AV1",
        )
        template = (
            "{제목} {채널명} {영상ID} {사이트} {해상도} "
            "{업로드날짜} {업로드날짜6} {재생시간} {프리셋} {코덱}"
        )
        with (
            patch(
                "services.templated_download_service.load_general_preferences",
                return_value=SimpleNamespace(filename_template=template),
            ),
            patch(
                "services.templated_download_service.load_filename_metadata",
                return_value=FilenameMetadata(
                    upload_date="20260909",
                    resolutions=("2160p", "1080p", "720p"),
                ),
            ),
        ):
            rendered = YtDlpDownloadService()._filename_title(task)

        self.assertEqual(
            rendered,
            "테스트 영상 테스트 채널 xyz987 YouTube 2160p "
            "20260909 260909 12m34s 기본 다운로드 AV1",
        )

    def test_filename_template_service_never_launches_external_probe(self) -> None:
        source = (
            ROOT / "services" / "templated_download_service.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("subprocess", source)
        self.assertNotIn("--simulate", source)
        self.assertNotIn("_probe_template_metadata", source)
        self.assertNotIn("_run_template_probe", source)

    def test_arbitrary_detected_resolution_is_enforced_in_format_selector(self) -> None:
        task = DownloadTask(
            task_id="task-360",
            title="360p 영상",
            url="https://www.youtube.com/watch?v=lowres",
            status=DownloadStatus.QUEUED,
            resolution="360p",
            container="MKV",
            codec="VP9",
        )
        selector = YtDlpDownloadService._format_selector(task)
        self.assertIn("[height<=360]", selector)


if __name__ == "__main__":
    unittest.main()
