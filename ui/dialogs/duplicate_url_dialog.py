from __future__ import annotations

from enum import StrEnum

from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.download_task import DownloadTask


class DuplicateChoice(StrEnum):
    FOCUS_EXISTING = "focus_existing"
    ADD_ANYWAY = "add_anyway"
    CANCEL = "cancel"


class DuplicateUrlDialog(QDialog):
    def __init__(
        self,
        existing_task: DownloadTask,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.choice = DuplicateChoice.CANCEL

        self.setObjectName("duplicateDialog")
        self.setWindowTitle("중복 영상")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.setMaximumWidth(620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel("이 영상은 이미 다운로드 목록에 있습니다.")
        title.setObjectName("dialogTitle")

        task_frame = QFrame()
        task_frame.setObjectName("dialogTaskFrame")
        task_layout = QVBoxLayout(task_frame)
        task_layout.setContentsMargins(14, 12, 14, 12)
        task_layout.setSpacing(7)

        task_title = QLabel(existing_task.title)
        task_title.setObjectName("dialogTaskTitle")
        task_title.setWordWrap(True)

        status = QLabel(f"현재 상태: {existing_task.status_label}")
        status.setObjectName("dialogStatusText")

        task_layout.addWidget(task_title)
        task_layout.addWidget(status)

        description = QLabel(
            "다른 화질이나 형식으로 다시 받을 목적이라면 "
            "그대로 한 번 더 추가할 수 있습니다."
        )
        description.setObjectName("emptyDescription")
        description.setWordWrap(True)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch()

        add_button = QPushButton("그래도 추가")
        add_button.setObjectName("primaryButton")
        add_button.clicked.connect(self._add_anyway)

        focus_button = QPushButton("기존 항목 보기")
        focus_button.setObjectName("secondaryButton")
        focus_button.clicked.connect(self._focus_existing)

        cancel_button = QPushButton("취소")
        cancel_button.setObjectName("smallSecondaryButton")
        cancel_button.clicked.connect(self.reject)

        button_row.addWidget(add_button)
        button_row.addWidget(focus_button)
        button_row.addWidget(cancel_button)

        layout.addWidget(title)
        layout.addWidget(task_frame)
        layout.addWidget(description)
        layout.addSpacing(4)
        layout.addLayout(button_row)

    def _focus_existing(self) -> None:
        self.choice = DuplicateChoice.FOCUS_EXISTING
        self.accept()

    def _add_anyway(self) -> None:
        self.choice = DuplicateChoice.ADD_ANYWAY
        self.accept()


def ask_duplicate_choice(
    existing_task: DownloadTask,
    parent: QWidget | None = None,
) -> DuplicateChoice:
    dialog = DuplicateUrlDialog(existing_task, parent)
    dialog.exec()
    return dialog.choice
