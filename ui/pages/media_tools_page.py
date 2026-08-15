from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.tools.converter_page import ConverterPage
from ui.tools.snapshot_page import SnapshotPage
from ui.tools.subtitle_page import SubtitlePage
from ui.tools.thumbnail_page import ThumbnailPage


class MediaToolsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        title = QLabel("미디어 도구")
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "다운로드한 영상을 변환하거나 썸네일, 스냅샷, 자막을 관리합니다."
        )
        subtitle.setObjectName("bodyText")

        layout.addWidget(title)
        layout.addWidget(subtitle)

        tab_bar = QFrame()
        tab_bar.setObjectName("toolTabBar")

        tab_layout = QHBoxLayout(tab_bar)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(8)

        self.tab_button_group = QButtonGroup(self)
        self.tab_button_group.setExclusive(True)
        self.tab_buttons: list[QPushButton] = []

        tab_names = [
            "영상 변환",
            "썸네일",
            "스냅샷",
            "자막",
        ]

        for index, tab_name in enumerate(tab_names):
            button = QPushButton(tab_name)
            button.setObjectName("toolTabButton")
            button.setCheckable(True)
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            button.clicked.connect(
                lambda checked=False, page_index=index:
                self.show_tool_page(page_index)
            )

            self.tab_button_group.addButton(button, index)
            self.tab_buttons.append(button)
            tab_layout.addWidget(button, 1)

        layout.addWidget(tab_bar)

        content_card = QFrame()
        content_card.setObjectName("toolContentCard")

        content_layout = QVBoxLayout(content_card)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.tool_stack = QStackedWidget()
        self.tool_stack.setObjectName("toolStack")
        self.converter_page = ConverterPage()
        self.thumbnail_page = ThumbnailPage()
        self.tool_stack.addWidget(self.converter_page)
        self.tool_stack.addWidget(self.thumbnail_page)
        self.snapshot_page = SnapshotPage()
        self.tool_stack.addWidget(self.snapshot_page)
        self.subtitle_page = SubtitlePage()
        self.tool_stack.addWidget(self.subtitle_page)

        content_layout.addWidget(self.tool_stack)
        layout.addWidget(content_card, 1)

        self.show_tool_page(0)

    @property
    def has_active_operation(self) -> bool:
        return (
            self.converter_page.has_active_operation
            or self.thumbnail_page.has_active_operation
            or self.snapshot_page.has_active_operation
            or self.subtitle_page.has_active_operation
        )

    def shutdown(self) -> None:
        self.converter_page.shutdown()
        self.thumbnail_page.shutdown()
        self.snapshot_page.shutdown()
        self.subtitle_page.shutdown()

    def show_tool_page(self, index: int) -> None:
        if index < 0 or index >= self.tool_stack.count():
            index = 0

        self.tool_stack.setCurrentIndex(index)

        for button_index, button in enumerate(self.tab_buttons):
            button.setChecked(button_index == index)
