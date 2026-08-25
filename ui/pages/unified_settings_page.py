from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.theme import active_theme_mode, load_theme_preference
from ui.pages.community_settings_page import CommunitySettingsPage


class UnifiedSettingsPage(CommunitySettingsPage):
    """일반 탭의 저장 동작을 하나의 고정 버튼으로 정리한다."""

    def _create_general_tab(self):  # type: ignore[no-untyped-def]
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(6)

        scroll = self._create_scroll_page(
            [
                self._create_theme_card(),
                self._create_download_folder_card(),
                self._create_file_collision_card(),
                self._create_queue_restore_card(),
                self._create_windows_behavior_card(),
                self._create_notification_card(),
            ]
        )
        page_layout.addWidget(scroll, 1)

        save_bar = QFrame()
        save_bar.setObjectName("settingsSaveBar")
        save_layout = QHBoxLayout(save_bar)
        save_layout.setContentsMargins(10, 5, 10, 5)
        save_layout.setSpacing(10)

        self.general_tab_save_status = QLabel("")
        self.general_tab_save_status.setObjectName("settingsSavedStatus")
        self.general_tab_save_status.setWordWrap(True)

        save_button = QPushButton("변경사항 저장")
        save_button.setObjectName("primaryButton")
        save_button.setFixedHeight(36)
        save_button.setMinimumWidth(132)
        save_button.clicked.connect(self._save_general_tab_changes)

        save_layout.addWidget(self.general_tab_save_status, 1)
        save_layout.addWidget(save_button)
        page_layout.addWidget(save_bar, 0)
        return page

    @staticmethod
    def _hide_card_button(card: QFrame, text: str) -> None:
        for button in card.findChildren(QPushButton):
            if button.text() == text:
                button.hide()

    def _create_theme_card(self) -> QFrame:
        card = super()._create_theme_card()
        self._hide_card_button(card, "테마 설정 저장")
        if hasattr(self, "theme_save_status"):
            self.theme_save_status.hide()
        return card

    def _create_windows_behavior_card(self) -> QFrame:
        card = super()._create_windows_behavior_card()
        self._hide_card_button(card, "Windows 설정 저장")
        if hasattr(self, "system_save_status"):
            self.system_save_status.hide()
        return card

    def _create_notification_card(self) -> QFrame:
        card = super()._create_notification_card()
        self._hide_card_button(card, "일반 설정 저장")
        if hasattr(self, "general_save_status"):
            self.general_save_status.hide()
        return card

    def _save_general_tab_changes(self) -> None:
        requested_start_with_windows = self.start_with_windows_checkbox.isChecked()

        # 검증을 마친 기존 저장 로직을 그대로 재사용한다. Windows 시작 프로그램
        # 등록 실패 같은 예외 안내도 기존 경로에서 동일하게 처리된다.
        self._save_theme_preference()
        self._save_system_preferences()
        self._save_general_preferences()

        theme_restart_needed = load_theme_preference() != active_theme_mode()
        startup_changed = (
            requested_start_with_windows
            != self._general_preferences.start_with_windows
        )

        if startup_changed:
            message = "✓ 다른 변경사항은 저장되었습니다. Windows 자동 실행 설정은 적용되지 않았습니다."
        elif theme_restart_needed:
            message = "✓ 변경사항 저장됨 · 화면 테마는 RR-V 재시작 후 적용됩니다."
        else:
            message = "✓ 변경사항이 저장되었습니다."

        self.general_tab_save_status.setText(message)
        QTimer.singleShot(
            3200,
            lambda: self.general_tab_save_status.setText(""),
        )
