from __future__ import annotations

from pathlib import Path
import unittest

from core.download_task import (
    DownloadStatus,
    DownloadTask,
    remove_failed_tasks,
)


def _task(task_id: str, status: DownloadStatus) -> DownloadTask:
    return DownloadTask(
        task_id=task_id,
        title=task_id,
        url=f"https://example.com/{task_id}",
        status=status,
    )


class FailedTaskBulkRemoveTests(unittest.TestCase):
    def test_only_failed_tasks_are_removed(self) -> None:
        tasks = [
            _task("failed-1", DownloadStatus.FAILED),
            _task("analyzing", DownloadStatus.ANALYZING),
            _task("queued", DownloadStatus.QUEUED),
            _task("downloading", DownloadStatus.DOWNLOADING),
            _task("postprocessing", DownloadStatus.POSTPROCESSING),
            _task("completed", DownloadStatus.COMPLETED),
            _task("stopped", DownloadStatus.STOPPED),
            _task("failed-2", DownloadStatus.FAILED),
        ]

        remaining, removed_ids = remove_failed_tasks(tasks)

        self.assertEqual(removed_ids, ["failed-1", "failed-2"])
        self.assertEqual(
            [task.task_id for task in remaining],
            [
                "analyzing",
                "queued",
                "downloading",
                "postprocessing",
                "completed",
                "stopped",
            ],
        )

    def test_source_list_is_not_modified(self) -> None:
        tasks = [
            _task("failed", DownloadStatus.FAILED),
            _task("queued", DownloadStatus.QUEUED),
        ]
        original_ids = [task.task_id for task in tasks]

        remaining, removed_ids = remove_failed_tasks(tasks)

        self.assertEqual([task.task_id for task in tasks], original_ids)
        self.assertEqual(removed_ids, ["failed"])
        self.assertEqual([task.task_id for task in remaining], ["queued"])
        self.assertIsNot(remaining, tasks)

    def test_no_failures_returns_a_copy_and_no_removed_ids(self) -> None:
        tasks = [_task("queued", DownloadStatus.QUEUED)]

        remaining, removed_ids = remove_failed_tasks(tasks)

        self.assertEqual(removed_ids, [])
        self.assertEqual(remaining, tasks)
        self.assertIsNot(remaining, tasks)

    def test_runtime_ui_requires_confirmation_and_never_deletes_download_files(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (
            root / "ui" / "pages" / "download_page_chapters.py"
        ).read_text(encoding="utf-8")

        self.assertIn('QPushButton("실패 삭제")', source)
        self.assertIn('"실패 항목 삭제"', source)
        self.assertIn("실패한 항목 {failed_count}개를 목록에서 삭제할까요?", source)
        self.assertIn("다운로드된 파일은 삭제되지 않습니다.", source)
        self.assertIn("remove_failed_tasks(self.tasks)", source)
        self.assertIn("remove_task(task_id, emit_signals=False)", source)
        self.assertNotIn("unlink(", source[source.index("def _remove_failed_tasks"):source.index("def _refresh_list_state")])


if __name__ == "__main__":
    unittest.main()