from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from app.support_report import build_download_problem_report
from core.download_task import DownloadStatus, DownloadTask


class SupportReportTests(unittest.TestCase):
    def test_failed_download_report_redacts_sensitive_values_and_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = Path(temp_dir) / "downloads"
            save_path.mkdir()
            raw_log = Path(temp_dir) / "task.log"
            raw_log.write_text(
                "\n".join(
                    [
                        "Authorization: Bearer TOP_SECRET_AUTH",
                        "Cookie: SID=TOP_SECRET_COOKIE",
                        "po_token=TOP_SECRET_PO",
                        f"output={save_path / 'video.mp4'}",
                        f"home={Path.home()}",
                        "normal diagnostic line",
                    ]
                ),
                encoding="utf-8",
            )

            task = DownloadTask(
                task_id="support-report",
                title="문제 보고 테스트",
                url=(
                    "https://www.youtube.com/watch?v=abc123"
                    "&pot=TOP_SECRET_URL&sig=TOP_SECRET_SIG"
                    "&token=TOP_SECRET_GENERIC"
                ),
                status=DownloadStatus.FAILED,
                extractor="youtube",
                video_id="abc123",
                save_path=str(save_path),
                raw_log_path=str(raw_log),
                phase_message="다운로드 실패",
                error_message="네트워크 오류",
                error_detail=(
                    "Authorization: Bearer TOP_SECRET_DETAIL\n"
                    "Cookie: SID=TOP_SECRET_DETAIL_COOKIE\n"
                    f"path={save_path / 'partial.mp4'}"
                ),
            )

            statuses = (
                SimpleNamespace(
                    label="yt-dlp Nightly",
                    available=True,
                    version="2026.09.21",
                ),
                SimpleNamespace(
                    label="FFmpeg",
                    available=True,
                    version="8.0",
                ),
            )
            with patch(
                "app.support_report.inspect_tools",
                return_value=statuses,
            ):
                report = build_download_problem_report(task)

        for secret in (
            "TOP_SECRET_AUTH",
            "TOP_SECRET_COOKIE",
            "TOP_SECRET_PO",
            "TOP_SECRET_URL",
            "TOP_SECRET_SIG",
            "TOP_SECRET_GENERIC",
            "TOP_SECRET_DETAIL",
            "TOP_SECRET_DETAIL_COOKIE",
        ):
            self.assertNotIn(secret, report)

        self.assertNotIn(str(save_path), report)
        self.assertNotIn(str(raw_log), report)
        self.assertNotIn(str(Path.home()), report)
        self.assertIn("<redacted>", report)
        self.assertIn("<save-path>", report)
        self.assertIn("=== RR-V 에러 로그 ===", report)
        self.assertIn("RR-V:", report)
        self.assertIn("yt-dlp Nightly: OK", report)
        self.assertIn("normal diagnostic line", report)

    def test_raw_log_tail_is_bounded_and_marks_omitted_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_log = Path(temp_dir) / "long-task.log"
            raw_log.write_text(
                "\n".join(f"line {index}" for index in range(180)),
                encoding="utf-8",
            )
            task = DownloadTask(
                task_id="long-report",
                title="긴 로그",
                url="https://example.invalid/video",
                status=DownloadStatus.FAILED,
                raw_log_path=str(raw_log),
                error_message="실패",
            )

            with patch("app.support_report.inspect_tools", return_value=()):
                report = build_download_problem_report(task)

        self.assertIn("[앞부분 60줄 생략]", report)
        self.assertNotIn("line 0\n", report)
        self.assertIn("line 179", report)

    def test_failed_card_and_page_are_wired_for_error_log_save(self) -> None:
        root = Path(__file__).resolve().parents[1]
        card_source = (
            root / "ui" / "widgets" / "download_task_card.py"
        ).read_text(encoding="utf-8")
        list_source = (
            root / "ui" / "widgets" / "download_task_list.py"
        ).read_text(encoding="utf-8")
        page_source = (
            root / "ui" / "pages" / "download_page.py"
        ).read_text(encoding="utf-8")
        settings_source = (
            root / "ui" / "pages" / "theme_settings_page.py"
        ).read_text(encoding="utf-8")

        self.assertIn("error_log_requested = Signal(str)", card_source)
        self.assertIn('QPushButton("에러 로그 저장하기")', card_source)
        self.assertIn(
            "self.task.status is DownloadStatus.FAILED",
            card_source,
        )
        self.assertIn("error_log_requested = Signal(str)", list_source)
        self.assertIn("card.error_log_requested.connect(", list_source)
        self.assertIn("build_download_problem_report", page_source)
        self.assertIn("def _save_error_log", page_source)
        self.assertIn("QFileDialog.getSaveFileName(", page_source)
        self.assertIn('default_name = f"RR-V_Error_{timestamp}.txt"', page_source)
        self.assertLess(
            page_source.index("QFileDialog.getSaveFileName("),
            page_source.index("report = build_download_problem_report(task)"),
        )
        self.assertIn('self.toast.show_message("에러 로그를 준비하는 중…")', page_source)
        self.assertIn('destination.write_text(report, encoding="utf-8")', page_source)
        self.assertNotIn("QApplication.clipboard().setText(report)", page_source)
        self.assertIn('self.toast.show_message("에러 로그를 저장했습니다.")', page_source)
        self.assertIn(
            "Chromium 브라우저 창이 잠시 열렸다가 자동으로 닫힐 수 있으며 정상",
            settings_source,
        )


if __name__ == "__main__":
    unittest.main()
