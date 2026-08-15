from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QWidget


class ToastMessage(QLabel):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toastMessage")
        self.setWordWrap(False)
        self.hide()

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_message(self, message: str, duration_ms: int = 1700) -> None:
        self.setText(message)
        self.adjustSize()
        self.reposition()
        self.raise_()
        self.show()
        self._hide_timer.start(duration_ms)

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return

        margin = 24
        x = max(margin, parent.width() - self.width() - margin)
        y = max(margin, parent.height() - self.height() - margin)
        self.move(x, y)
