from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from app.download_preferences import load_download_preferences
from ui.pages.download_page import DownloadPage as _BaseDownloadPage
from ui.widgets.chapter_preview_panel import PreviewPanel


class DownloadPage(_BaseDownloadPage):
    """기존 DownloadPage에 1.4 챕터 저장 UX만 얹는 얇은 통합층."""

    def _create_editor_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("영상 정보와 다운로드 설정")
        title.setObjectName("sectionTitle")

        back_button = QPushButton("목록으로 돌아가기")
        back_button.setObjectName("secondaryButton")
        back_button.clicked.connect(self._back_to_list)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(back_button)
        layout.addLayout(header)

        self.preview_panel = PreviewPanel()
        self.preview_panel.cancel_requested.connect(self._back_to_list)
        self.preview_panel.task_requested.connect(self._create_task_from_preview)

        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.preview_scroll.setWidget(self.preview_panel)
        layout.addWidget(self.preview_scroll, 1)
        return page

    def _create_quick_placeholder(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        task = super()._create_quick_placeholder(*args, **kwargs)
        try:
            preferences = load_download_preferences()
            task.split_chapters = bool(
                preferences.split_chapters and not task.audio_only
            )
            self.task_list.refresh_task(task.task_id)
        except Exception:
            # 빠른 추가 자체를 이 표시 옵션 때문에 실패시키지 않는다.
            pass
        return task

    def _complete_quick_task(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        task_id = self._active_quick_task_id
        super()._complete_quick_task(*args, **kwargs)

        task = self._task_by_id(task_id)
        if task is None:
            return
        try:
            preferences = load_download_preferences()
            task.split_chapters = bool(
                preferences.split_chapters and not task.audio_only
            )
            self.task_list.refresh_task(task.task_id)
            self._schedule_queue_save()
        except Exception:
            # 분석 성공 뒤 표시 보강이 실패해도 기존 빠른 추가 흐름은 유지한다.
            pass

    def _create_task_from_preview(self, start_immediately: bool) -> None:
        before_ids = {task.task_id for task in self.tasks}
        try:
            desired_split = bool(
                self.preview_panel.selected_options().get("split_chapters", False)
            )
        except Exception:
            desired_split = False

        super()._create_task_from_preview(start_immediately)

        created = next(
            (task for task in self.tasks if task.task_id not in before_ids),
            None,
        )
        if created is None:
            return

        created.split_chapters = bool(desired_split and not created.audio_only)
        self.task_list.refresh_task(created.task_id)
        self._schedule_queue_save()


__all__ = ["DownloadPage"]
