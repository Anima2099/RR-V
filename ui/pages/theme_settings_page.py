from __future__ import annotations

import threading

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from app.component_updates import (
    ComponentUpdateCheckResult,
    FFMPEG_GYAN_PAGE,
    YTDLP_RELEASES_PAGE,
    check_component_updates,
)
from app.theme import (
    THEME_DARK,
    THEME_LIGHT,
    active_theme_mode,
    load_theme_preference,
    save_theme_preference,
)
from ui.dialogs.warm_dialogs import ask_warm_question, show_warm_message
from ui.pages.settings_page import SettingsPage
from ui.widgets.common import create_card


class ThemeSettingsPage(SettingsPage):
    """1.1.3 화면 테마와 구성요소 업데이트 확인을 기존 설정 페이지에 확장한다."""

    component_check_finished = Signal(object, bool)

    def __init__(self) -> None:
        super().__init__()
        self._component_check_running = False
        self.component_check_finished.connect(self._component_check_done)

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

    def _create_tools_tab(self):  # type: ignore[no-untyped-def]
        return self._create_scroll_page(
            [
                self._create_component_update_card(),
                self._create_runtime_tools_card(),
                self._create_logs_card(),
                self._create_diagnostics_card(),
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

    def _create_component_update_card(self) -> QFrame:
        card, layout = create_card()

        title = QLabel("구성요소 업데이트")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "RR-V 실행 후 백그라운드에서 yt-dlp Nightly와 Gyan Git Essentials FFmpeg의 "
            "최신 버전을 하루에 한 번 확인합니다. 확인에 실패해도 RR-V 사용에는 영향을 주지 않습니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        self.component_update_status = QLabel("아직 확인하지 않음")
        self.component_update_status.setObjectName("mutedText")
        self.component_update_status.setWordWrap(True)

        self.component_update_details = QLabel("")
        self.component_update_details.setObjectName("mutedText")
        self.component_update_details.setWordWrap(True)
        self.component_update_details.setTextInteractionFlags(
            self.component_update_details.textInteractionFlags()
        )

        self.component_check_button = QPushButton("지금 업데이트 확인")
        self.component_check_button.setObjectName("primaryButton")
        self.component_check_button.clicked.connect(
            lambda: self.start_component_update_check(force=True, notify=True)
        )

        self.ytdlp_release_button = QPushButton("yt-dlp 릴리스")
        self.ytdlp_release_button.setObjectName("secondaryButton")
        self.ytdlp_release_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(YTDLP_RELEASES_PAGE))
        )

        self.ffmpeg_release_button = QPushButton("Gyan FFmpeg")
        self.ffmpeg_release_button.setObjectName("secondaryButton")
        self.ffmpeg_release_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(FFMPEG_GYAN_PAGE))
        )

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(self.ytdlp_release_button)
        action_row.addWidget(self.ffmpeg_release_button)
        action_row.addStretch()
        action_row.addWidget(self.component_check_button)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(self.component_update_status)
        layout.addWidget(self.component_update_details)
        layout.addLayout(action_row)
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

    def start_component_update_check(
        self,
        *,
        force: bool = False,
        notify: bool = True,
    ) -> None:
        if self._component_check_running:
            return
        self._component_check_running = True
        if hasattr(self, "component_check_button"):
            self.component_check_button.setEnabled(False)
            self.component_update_status.setText("최신 버전 확인 중…")

        def run() -> None:
            try:
                result = check_component_updates(force=force)
            except Exception:
                # 업데이트 확인은 앱의 부가 기능이다. 예상하지 못한 네트워크/파싱
                # 오류가 나도 프로그램 본체로 예외가 전파되지 않게 한다.
                result = ComponentUpdateCheckResult(components=())
            self.component_check_finished.emit(result, notify)

        threading.Thread(target=run, daemon=True).start()

    def _component_check_done(
        self,
        result: ComponentUpdateCheckResult,
        notify: bool,
    ) -> None:
        self._component_check_running = False
        if hasattr(self, "component_check_button"):
            self.component_check_button.setEnabled(True)

        if result.skipped:
            return

        if not result.components:
            if hasattr(self, "component_update_status"):
                self.component_update_status.setText(
                    "업데이트 서버에 연결하지 못했습니다. RR-V는 정상적으로 사용할 수 있습니다."
                )
                self.component_update_details.setText("")
            return

        detail_lines: list[str] = []
        for component in result.components:
            if component.update_available is None:
                state = "확인 실패"
            elif component.update_available:
                state = "업데이트 있음"
            else:
                state = "최신"
            detail_lines.append(
                f"{component.label}: {state} · 현재 {component.current} · 최신 {component.latest}"
            )

        updates = result.updates
        failed_count = len(result.errors)
        if updates:
            status = f"업데이트 {len(updates)}개가 있습니다."
        elif failed_count:
            status = "확인 가능한 구성요소는 최신입니다. 일부 서버 확인은 실패했습니다."
        else:
            status = "✓ yt-dlp와 FFmpeg가 최신 상태입니다."

        if hasattr(self, "component_update_status"):
            self.component_update_status.setText(status)
            self.component_update_details.setText("\n".join(detail_lines))

        if not notify or not updates:
            return

        lines = ["새 구성요소 버전이 있습니다.", ""]
        for component in updates:
            lines.append(
                f"• {component.label}\n  현재 {component.current}\n  최신 {component.latest}"
            )
        lines.extend(
            [
                "",
                "설정의 '도구 및 리소스'에서 현재 버전을 확인하고 업데이트할 수 있습니다.",
            ]
        )
        open_tools = ask_warm_question(
            self,
            "RR-V 구성요소 업데이트",
            "\n".join(lines),
            yes_text="도구 및 리소스 열기",
            no_text="나중에",
        )
        if open_tools:
            self.show_settings_tab(self.TOOLS_TAB)

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
