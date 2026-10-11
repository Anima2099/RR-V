from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.constants import (
    APP_DISPLAY_VERSION,
    SIDEBAR_COLLAPSED_WIDTH,
    SIDEBAR_WIDTH,
)


class Sidebar(QFrame):
    page_requested = Signal(int)
    collapsed_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()

        self.setObjectName("sidebar")
        self._collapsed = False
        self.setFixedWidth(SIDEBAR_WIDTH)

        self.nav_buttons: list[QPushButton] = []

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 16, 16, 18)
        self._layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)

        self.logo = QLabel("RR-V")
        self.logo.setObjectName("appLogo")

        self.toggle_button = QPushButton("◀")
        self.toggle_button.setObjectName("sidebarToggleButton")
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.setToolTip("사이드바 접기")
        self.toggle_button.setFixedSize(28, 28)
        self.toggle_button.clicked.connect(self.toggle_collapsed)

        header_row.addWidget(self.logo)
        header_row.addStretch()
        header_row.addWidget(self.toggle_button)
        self._layout.addLayout(header_row)

        self.subtitle = QLabel("Video Downloader\n& Media Tools")
        self.subtitle.setObjectName("appSubtitle")
        self._layout.addWidget(self.subtitle)
        self._layout.addSpacing(24)

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
            self._layout.addWidget(button)

        self._layout.addStretch()

        self.info_button = QPushButton("프로그램 정보")
        self.info_button.setObjectName("navButton")
        self.info_button.setCheckable(True)
        self.info_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.info_button.clicked.connect(
            lambda checked=False: self.page_requested.emit(3)
        )
        self.nav_buttons.append(self.info_button)
        self._layout.addWidget(self.info_button)
        self._layout.addSpacing(2)

        self.version = QLabel(f"Version {APP_DISPLAY_VERSION}")
        self.version.setObjectName("versionLabel")
        self.version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self.version)

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool, *, emit: bool = True) -> None:
        collapsed = bool(collapsed)
        changed = collapsed != self._collapsed
        self._collapsed = collapsed

        self.setFixedWidth(
            SIDEBAR_COLLAPSED_WIDTH if collapsed else SIDEBAR_WIDTH
        )
        self._layout.setContentsMargins(
            8 if collapsed else 16,
            16,
            8 if collapsed else 16,
            18,
        )

        self.logo.setVisible(not collapsed)
        self.subtitle.setVisible(not collapsed)
        for button in self.nav_buttons:
            button.setVisible(not collapsed)
        self.version.setVisible(not collapsed)

        self.toggle_button.setText("▶" if collapsed else "◀")
        self.toggle_button.setToolTip(
            "사이드바 펼치기" if collapsed else "사이드바 접기"
        )

        if changed and emit:
            self.collapsed_changed.emit(collapsed)

    def set_current_page(self, index: int) -> None:
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)
