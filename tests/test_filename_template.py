from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.download_task import DownloadStatus, DownloadTask
from core.filename_template import (
    DEFAULT_FILENAME_TEMPLATE,
    filename_template_values,
    normalize_filename_template,
    render_filename_template,
    site_label,
    validate_filename_template,
)
from services.templated_download_service import YtDlpDownloadService


class FilenameTemplateTests(unittest.TestCase):
    def test_empty_template_normalizes_to_title_default(self) -> None:
        self.assertEqual(
            normalize_filename_template("   "),
            DEFAULT_FILENAME_TEMPLATE,
        )

    def test_render_replaces_supported_tokens(self) -> None:
        values = filename_template_values(
            title="영상 제목",
            uploader="채널 이름",
            video_id="abc123",
            extractor="Youtube",
        )
        rendered = render_filename_template(
            "[{채널명}] {제목} [{영상ID}] - {사이트}",
            values,
        )
        self.assertEqual(
            rendered,
            "[채널 이름] 영상 제목 [abc123] - YouTube",
        )

    def test_unknown_token_is_rejected(self) -> None:
        valid, message = validate_filename_template("{제목} {업로드날짜}")
        self.assertFalse(valid)
        self.assertIn("{업로드날짜}", message)

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
        with patch(
            "services.templated_download_service.load_general_preferences",
            return_value=SimpleNamespace(
                filename_template=DEFAULT_FILENAME_TEMPLATE
            ),
        ):
            rendered = YtDlpDownloadService._filename_title(task)
        self.assertEqual(rendered, "Video by sample [ABC123]")

    def test_custom_template_uses_task_metadata(self) -> None:
        task = DownloadTask(
            task_id="task-2",
            title="테스트 영상",
            url="https://www.youtube.com/watch?v=xyz987",
            status=DownloadStatus.QUEUED,
            video_id="xyz987",
            extractor="Youtube",
            uploader="테스트 채널",
        )
        with patch(
            "services.templated_download_service.load_general_preferences",
            return_value=SimpleNamespace(
                filename_template="[{채널명}] {제목} [{영상ID}]"
            ),
        ):
            rendered = YtDlpDownloadService._filename_title(task)
        self.assertEqual(
            rendered,
            "[테스트 채널] 테스트 영상 [xyz987]",
        )


if __name__ == "__main__":
    unittest.main()
