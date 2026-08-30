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

from app.component_updates import normalize_ffmpeg_release_version
from app.theme import active_theme_mode, load_theme_preference
from ui.pages.community_settings_page import CommunitySettingsPage


class UnifiedSettingsPage(CommunitySettingsPage):
    """일반 탭의 저장 동작을 하나의 고정 버튼으로 정리한다."""

    def __init__(self) -> None:
        # SettingsPage와 ThemeSettingsPage는 초기화 과정에서 도구 상태 갱신을
        # 요청하지만, 외부 EXE 실행과 WPC 무결성 검사는 창이 보인 뒤 시작되는
        # 백그라운드 구성요소 확인 결과를 재사용한다.
        self._initializing_settings_page = True
        super().__init__()
        self._initializing_settings_page = False

    def _refresh_tool_status(self) -> None:
        if getattr(self, "_initializing_settings_page", False):
            return
        super()._refresh_tool_status()

    def _apply_inspected_tool_statuses(self, raw_statuses: object) -> None:
        if not hasattr(self, "tool_status_labels"):
            return

        try:
            statuses = {
                str(getattr(status, "key", "")): status
                for status in tuple(raw_statuses or ())
                if str(getattr(status, "key", ""))
            }
        except TypeError:
            return
        if not statuses:
            return

        missing: set[str] = set()
        repair: set[str] = set()

        def apply_single(key: str, status: object | None) -> None:
            if status is None:
                self.tool_version_labels[key].setText("확인 불가")
                self._set_tool_visual(key, "error", "? 확인 실패")
                repair.add(key)
                return

            version = str(getattr(status, "version", "") or "확인 불가")
            self.tool_version_labels[key].setText(version)
            issue_kind = self._status_issue_kind(status)
            if issue_kind == "normal":
                self._set_tool_visual(key, "normal", "✓ 정상")
            elif issue_kind == "missing":
                self._set_tool_visual(key, "error", "✕ 설치 필요")
                missing.add(key)
            else:
                self._set_tool_visual(key, "error", "⚠ 복구 필요")
                repair.add(key)

        apply_single("ytdlp", statuses.get("ytdlp"))

        ffmpeg = statuses.get("ffmpeg")
        ffprobe = statuses.get("ffprobe")
        ffmpeg_available = bool(
            ffmpeg
            and getattr(ffmpeg, "available", False)
            and ffprobe
            and getattr(ffprobe, "available", False)
        )
        if ffmpeg_available and ffmpeg is not None and ffprobe is not None:
            ffmpeg_version = normalize_ffmpeg_release_version(
                str(getattr(ffmpeg, "version", ""))
            )
            ffprobe_version = normalize_ffmpeg_release_version(
                str(getattr(ffprobe, "version", ""))
            )
            if ffmpeg_version == ffprobe_version:
                version_text = ffmpeg_version
            else:
                version_text = f"ffmpeg {ffmpeg_version} / ffprobe {ffprobe_version}"
            self.tool_version_labels["ffmpeg"].setText(version_text)
            self._set_tool_visual("ffmpeg", "normal", "✓ 정상")
        else:
            ffmpeg_kind = self._status_issue_kind(ffmpeg)
            ffprobe_kind = self._status_issue_kind(ffprobe)
            both_missing = ffmpeg_kind == "missing" and ffprobe_kind == "missing"
            if both_missing:
                self.tool_version_labels["ffmpeg"].setText("없음")
                self._set_tool_visual("ffmpeg", "error", "✕ 설치 필요")
                missing.add("ffmpeg")
            else:
                ffmpeg_text = str(
                    getattr(ffmpeg, "version", "확인 불가") or "확인 불가"
                )
                ffprobe_text = str(
                    getattr(ffprobe, "version", "확인 불가") or "확인 불가"
                )
                self.tool_version_labels["ffmpeg"].setText(
                    f"ffmpeg {ffmpeg_text} / ffprobe {ffprobe_text}"
                )
                self._set_tool_visual("ffmpeg", "error", "⚠ 복구 필요")
                repair.add("ffmpeg")

        apply_single("deno", statuses.get("deno"))
        apply_single("pot", statuses.get("pot"))

        self._missing_runtime_keys = missing
        self._repair_runtime_keys = repair
        if missing and repair:
            self.latest_update_button.setText("설치 및 복구")
        elif missing:
            self.latest_update_button.setText("필수 구성요소 설치")
        elif repair:
            self.latest_update_button.setText("구성요소 복구")
        else:
            self.latest_update_button.setText("최신 상태로 맞추기")
        self.latest_update_button.setEnabled(True)

    def _component_check_done(self, result: object, notify: bool) -> None:
        # check_component_updates()가 백그라운드에서 이미 수행한 로컬 도구
        # 검사를 그대로 재사용한다. 여기서 inspect_tools()를 다시 호출하지 않는다.
        self._apply_inspected_tool_statuses(
            getattr(result, "installed_statuses", ())
        )
        super()._component_check_done(result, notify)

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

    def _set_tool_action_status(self, text: str) -> None:
        # Community Beta의 도구 탭 구성이 바뀌는 동안에도 백그라운드 진행
        # 신호가 UI 위젯 누락 때문에 예외를 만들지 않도록 방어한다.
        if hasattr(self, "tool_action_label"):
            self.tool_action_label.setText(text)

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
