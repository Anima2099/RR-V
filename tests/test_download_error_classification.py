from __future__ import annotations

import unittest

from services.download_service import YtDlpDownloadService


class DownloadErrorClassificationTests(unittest.TestCase):
    def test_subtitle_http_404_is_not_reported_as_network_failure(self) -> None:
        detail = (
            "ERROR: Unable to download video subtitles for 'ko': "
            "HTTP Error 404: Not Found"
        )
        message = YtDlpDownloadService._friendly_error(
            detail,
            "https://www.youtube.com/watch?v=XJzRgeX-bwo",
        )

        self.assertIn("자막 다운로드", message)
        self.assertNotIn("네트워크 문제", message)

    def test_other_subtitle_failures_remain_identifiable(self) -> None:
        for detail in (
            "ERROR: Unable to download subtitles for 'en': HTTP Error 429",
            "ERROR: Unable to download video subtitles for 'ko': HTTP Error 403",
            "ERROR: Unable to download video subtitles for 'ja': timed out",
        ):
            with self.subTest(detail=detail):
                self.assertIn(
                    "자막 다운로드",
                    YtDlpDownloadService._friendly_error(detail),
                )

    def test_generic_download_failure_is_not_assumed_network_related(self) -> None:
        message = YtDlpDownloadService._friendly_error(
            "ERROR: Unable to download video data: unsupported response"
        )

        self.assertNotIn("네트워크 문제", message)
        self.assertIn("상세 로그", message)

    def test_actual_network_timeout_keeps_network_message(self) -> None:
        message = YtDlpDownloadService._friendly_error(
            "ERROR: network timed out while reading data"
        )

        self.assertEqual(
            message,
            "네트워크 문제로 다운로드를 계속하지 못했습니다.",
        )


if __name__ == "__main__":
    unittest.main()
