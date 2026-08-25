from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.constants import APP_VERSION, SIDEBAR_WIDTH


class Sidebar(QFrame):
    page_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()

        self.setObjectName("sidebar")
        self.setFixedWidth(SIDEBAR_WIDTH)

        self.nav_buttons: list[QPushButton] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 22, 16, 18)
        layout.setSpacing(8)

        logo = QLabel("RR-V")
        logo.setObjectName("appLogo")

        subtitle = QLabel("Video Downloader\n& Media Tools")
        subtitle.setObjectName("appSubtitle")

        layout.addWidget(logo)
        layout.addWidget(subtitle)
        layout.addSpacing(24)

        navigation_items = [
            ("다운로드", 0),
            ("미디어 도구", 1),
            ("설정", 2),
        ]

        for text, page_index in navigation_items:
            button = QPushButton(text)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda checked=False, index=page_index:
                self.page_requested.emit(index)
            )

            self.nav_buttons.append(button)
            layout.addWidget(button)

        layout.addStretch()

        info_button = QPushButton("프로그램 정보")
        info_button.setObjectName("navButton")
        info_button.setCheckable(True)
        info_button.setCursor(Qt.CursorShape.PointingHandCursor)
        info_button.clicked.connect(
            lambda checked=False: self.page_requested.emit(3)
        )
        self.nav_buttons.append(info_button)
        layout.addWidget(info_button)
        layout.addSpacing(2)

        version = QLabel(f"Version {APP_VERSION}")
        version.setObjectName("versionLabel")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(version)

    def set_current_page(self, index: int) -> None:
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)
