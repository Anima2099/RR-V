from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
)

from app.theme import (
    THEME_DARK,
    THEME_LIGHT,
    active_theme_mode,
    load_theme_preference,
    save_theme_preference,
)
from ui.pages.settings_page import SettingsPage
from ui.widgets.common import create_card


class ThemeSettingsPage(SettingsPage):
    """기존 설정 페이지에 1.1.3 화면 테마 설정만 안전하게 확장한다."""

    def _create_general_tab(self):  # type: ignore[no-untyped-def]
        return self._create_scroll_page(
            [
                self._create_theme_card(),
                self._create_download_folder_card(),
                self._create_file_collision_card(),
                self._create_queue_restore_card(),
                self._create_notification_card(),
            ]
        )

    def _create_theme_card(self) -> QFrame:
        card, layout = create_card()

        title = QLabel("화면 테마")
        title.setObjectName("sectionTitle")

        description = QLabel(
            "RR-V의 화면 색상을 선택합니다. 변경 사항은 RR-V를 다시 실행하면 적용됩니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        self.theme_button_group = QButtonGroup(self)
        self.theme_button_group.setExclusive(True)

        self.theme_light_radio = QRadioButton("라이트 · Warm Sage")
        self.theme_light_radio.setObjectName("settingsRadioButton")
        self.theme_dark_radio = QRadioButton("다크 · Warm Sage Dark")
        self.theme_dark_radio.setObjectName("settingsRadioButton")
        self.theme_button_group.addButton(self.theme_light_radio)
        self.theme_button_group.addButton(self.theme_dark_radio)

        choice_row = QHBoxLayout()
        choice_row.setSpacing(22)
        choice_row.addWidget(self.theme_light_radio)
        choice_row.addWidget(self.theme_dark_radio)
        choice_row.addStretch()

        self.theme_save_status = QLabel("")
        self.theme_save_status.setObjectName("settingsSavedStatus")

        save_button = QPushButton("테마 설정 저장")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._save_theme_preference)

        save_row = QHBoxLayout()
        save_row.addWidget(self.theme_save_status)
        save_row.addStretch()
        save_row.addWidget(save_button)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addLayout(choice_row)
        layout.addLayout(save_row)

        self._reload_theme_preferences_to_controls()
        return card

    def _reload_theme_preferences_to_controls(self) -> None:
        if not hasattr(self, "theme_light_radio"):
            return
        is_dark = load_theme_preference() == THEME_DARK
        self.theme_dark_radio.setChecked(is_dark)
        self.theme_light_radio.setChecked(not is_dark)

    def _save_theme_preference(self) -> None:
        requested = THEME_DARK if self.theme_dark_radio.isChecked() else THEME_LIGHT
        saved = save_theme_preference(requested)
        if saved == active_theme_mode():
            message = "저장됨 · 현재 적용 중"
        else:
            message = "저장됨 · RR-V 재시작 후 적용"
        self.theme_save_status.setText(message)
        QTimer.singleShot(3200, lambda: self.theme_save_status.setText(""))

    def show_settings_tab(self, index: int) -> None:
        super().show_settings_tab(index)
        if index == self.GENERAL_TAB:
            self._reload_theme_preferences_to_controls()

    def _restore_from_backup(self) -> None:
        super()._restore_from_backup()
        self._reload_theme_preferences_to_controls()

    def _reset_selected_scope(self) -> None:
        super()._reset_selected_scope()
        self._reload_theme_preferences_to_controls()
