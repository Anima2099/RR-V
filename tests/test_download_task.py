from __future__ import annotations

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


class DownloadTaskTests(unittest.TestCase):
    def test_remove_failed_tasks_preserves_every_other_status(self) -> None:
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

    def test_remove_failed_tasks_leaves_source_list_unchanged(self) -> None:
        tasks = [_task("queued", DownloadStatus.QUEUED)]

        remaining, removed_ids = remove_failed_tasks(tasks)

        self.assertEqual(removed_ids, [])
        self.assertEqual(remaining, tasks)
        self.assertIsNot(remaining, tasks)


if __name__ == "__main__":
    unittest.main()
