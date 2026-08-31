from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.theme import THEME_DARK, active_theme_mode


class _WarmBaseDialog(QDialog):
    def __init__(
        self,
        title: str,
        message: str,
        parent: QWidget | None = None,
        *,
        minimum_width: int = 430,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("warmDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(minimum_width)
        self.setMaximumWidth(640)

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(22, 20, 22, 18)
        self.root_layout.setSpacing(12)

        title_label = QLabel(title)
        title_label.setObjectName("dialogTitle")
        title_label.setWordWrap(True)
        self.root_layout.addWidget(title_label)

        if message:
            message_label = QLabel(message)
            message_label.setObjectName("emptyDescription")
            message_label.setWordWrap(True)
            self.root_layout.addWidget(message_label)

    def _button_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch()
        return row


class WarmMessageDialog(_WarmBaseDialog):
    def __init__(
        self,
        title: str,
        message: str,
        parent: QWidget | None = None,
        *,
        button_text: str = "확인",
    ) -> None:
        super().__init__(title, message, parent)
        row = self._button_row()
        ok_button = QPushButton(button_text)
        ok_button.setObjectName("primaryButton")
        ok_button.clicked.connect(self.accept)
        row.addWidget(ok_button)
        self.root_layout.addSpacing(4)
        self.root_layout.addLayout(row)
        ok_button.setDefault(True)
        ok_button.setFocus()


class WarmQuestionDialog(_WarmBaseDialog):
    def __init__(
        self,
        title: str,
        message: str,
        parent: QWidget | None = None,
        *,
        yes_text: str = "예",
        no_text: str = "아니오",
    ) -> None:
        super().__init__(title, message, parent)
        row = self._button_row()

        yes_button = QPushButton(yes_text)
        yes_button.setObjectName("primaryButton")
        yes_button.clicked.connect(self.accept)

        no_button = QPushButton(no_text)
        no_button.setObjectName("secondaryButton")
        no_button.clicked.connect(self.reject)
        no_button.setDefault(True)

        row.addWidget(yes_button)
        row.addWidget(no_button)
        self.root_layout.addSpacing(4)
        self.root_layout.addLayout(row)
        no_button.setFocus()


class WarmTextInputDialog(_WarmBaseDialog):
    def __init__(
        self,
        title: str,
        label: str,
        initial: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, "", parent)

        label_widget = QLabel(label)
        label_widget.setObjectName("dialogStatusText")
        self.root_layout.addWidget(label_widget)

        self.input = QLineEdit(initial)
        self.input.setObjectName("dialogSearchInput")
        self.input.selectAll()
        self.input.returnPressed.connect(self.accept)
        self.root_layout.addWidget(self.input)

        row = self._button_row()
        ok_button = QPushButton("확인")
        ok_button.setObjectName("primaryButton")
        ok_button.clicked.connect(self.accept)
        ok_button.setDefault(True)

        cancel_button = QPushButton("취소")
        cancel_button.setObjectName("secondaryButton")
        cancel_button.clicked.connect(self.reject)

        row.addWidget(ok_button)
        row.addWidget(cancel_button)
        self.root_layout.addSpacing(4)
        self.root_layout.addLayout(row)
        self.input.setFocus()


class WarmChoiceDialog(_WarmBaseDialog):
    def __init__(
        self,
        title: str,
        label: str,
        items: Sequence[str],
        parent: QWidget | None = None,
        *,
        current_index: int = 0,
    ) -> None:
        super().__init__(title, "", parent)

        label_widget = QLabel(label)
        label_widget.setObjectName("dialogStatusText")
        self.root_layout.addWidget(label_widget)

        self.combo = QComboBox()
        self.combo.setObjectName("settingsComboBox")
        self.combo.addItems(list(items))
        if self.combo.count():
            self.combo.setCurrentIndex(max(0, min(current_index, self.combo.count() - 1)))
        self.root_layout.addWidget(self.combo)

        row = self._button_row()
        ok_button = QPushButton("확인")
        ok_button.setObjectName("primaryButton")
        ok_button.clicked.connect(self.accept)
        ok_button.setDefault(True)

        cancel_button = QPushButton("취소")
        cancel_button.setObjectName("secondaryButton")
        cancel_button.clicked.connect(self.reject)

        row.addWidget(ok_button)
        row.addWidget(cancel_button)
        self.root_layout.addSpacing(4)
        self.root_layout.addLayout(row)
        self.combo.setFocus()


class WarmReportDialog(_WarmBaseDialog):
    def __init__(
        self,
        title: str,
        report: str,
        parent: QWidget | None = None,
        *,
        message: str = "",
    ) -> None:
        super().__init__(title, message, parent, minimum_width=620)
        self.setMaximumWidth(920)
        self.resize(760, 560)

        report_view = QPlainTextEdit()
        report_view.setObjectName("diagnosticReportView")
        report_view.setReadOnly(True)
        report_view.setPlainText(report)
        report_view.setMinimumHeight(360)
        if active_theme_mode() == THEME_DARK:
            report_view.setStyleSheet(
                "QPlainTextEdit#diagnosticReportView {"
                "background-color: #252D29;"
                "color: #E2E7E3;"
                "border: 1px solid #46514B;"
                "border-radius: 8px;"
                "padding: 8px;"
                "selection-background-color: #7EA2B3;"
                "selection-color: #202723;"
                "}"
            )
        else:
            report_view.setStyleSheet(
                "QPlainTextEdit#diagnosticReportView {"
                "background-color: #FCF9F1;"
                "color: #34413C;"
                "border: 1px solid #C5C4BD;"
                "border-radius: 8px;"
                "padding: 8px;"
                "selection-background-color: #608598;"
                "selection-color: #FFFDF8;"
                "}"
            )
        self.root_layout.addWidget(report_view, 1)

        row = self._button_row()
        close_button = QPushButton("닫기")
        close_button.setObjectName("primaryButton")
        close_button.clicked.connect(self.accept)
        row.addWidget(close_button)
        self.root_layout.addLayout(row)
        close_button.setDefault(True)
        close_button.setFocus()


def show_warm_message(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    button_text: str = "확인",
) -> None:
    WarmMessageDialog(title, message, parent, button_text=button_text).exec()


def show_warm_report(
    parent: QWidget | None,
    title: str,
    report: str,
    *,
    message: str = "",
) -> None:
    WarmReportDialog(title, report, parent, message=message).exec()


def ask_warm_question(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    yes_text: str = "예",
    no_text: str = "아니오",
) -> bool:
    dialog = WarmQuestionDialog(
        title,
        message,
        parent,
        yes_text=yes_text,
        no_text=no_text,
    )
    return dialog.exec() == QDialog.DialogCode.Accepted


def prompt_warm_text(
    parent: QWidget | None,
    title: str,
    label: str,
    initial: str = "",
) -> tuple[str, bool]:
    dialog = WarmTextInputDialog(title, label, initial, parent)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return dialog.input.text(), accepted


def choose_warm_item(
    parent: QWidget | None,
    title: str,
    label: str,
    items: Sequence[str],
    *,
    current_index: int = 0,
) -> tuple[str, bool]:
    dialog = WarmChoiceDialog(
        title,
        label,
        items,
        parent,
        current_index=current_index,
    )
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return dialog.combo.currentText(), accepted
