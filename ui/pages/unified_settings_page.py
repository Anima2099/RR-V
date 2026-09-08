from __future__ import annotations

from datetime import datetime
import inspect

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel

from app.component_updates import ComponentUpdateCheckResult
from ui.pages.community_settings_page import CommunitySettingsPage as _CommunityLayer
from ui.pages.settings_page import SettingsPage as _BaseSettingsPage
from ui.pages.theme_settings_page import ThemeSettingsPage as _ThemeLayer


class SettingsPage(_BaseSettingsPage):
    """RR-V 1.4의 최종 설정 화면 진입점.

    과거 버전별 SettingsPage 상속 사슬은 실행 경로에서 제거하고, 이미 검증된
    Theme/Community 구현은 내부 구현 공급자로만 재사용한다. 외부에서는 이
    SettingsPage 하나만 사용한다.
    """

    component_check_finished = Signal(object, bool)
    open_tools_requested = Signal()
    _VISIBLE_TAB_ORDER = _CommunityLayer._VISIBLE_TAB_ORDER

    def __init__(self) -> None:
        self._initializing_settings_page = True
        self._component_check_running = False
        self._last_component_result: ComponentUpdateCheckResult | None = None
        self._tools_tab_checked_once = False
        self._missing_runtime_keys: set[str] = set()
        self._repair_runtime_keys: set[str] = set()
        self._latest_tool_diagnostic_report = ""
        self._latest_tool_diagnostic_at: datetime | None = None
        self._load_latest_tool_diagnostic_report()

        _BaseSettingsPage.__init__(self)
        self.component_check_finished.connect(self._component_check_done)
        self._refresh_tool_diagnostic_card()

        for label in self.findChildren(QLabel):
            if label.text() == "RR-V의 기본 동작, 인증, 시스템 연동과 필수 구성요소를 관리합니다.":
                label.setText(
                    "RR-V의 기본 동작, 사이트 인증, 브라우저 확장과 필수 구성요소를 관리합니다."
                )
                break

        self._initializing_settings_page = False

    def _refresh_tool_status(self) -> None:
        if getattr(self, "_initializing_settings_page", False):
            return
        _ThemeLayer._refresh_tool_status(self)

    def _component_check_done(self, result: object, notify: bool) -> None:
        self._apply_inspected_tool_statuses(
            getattr(result, "installed_statuses", ())
        )
        _ThemeLayer._component_check_done(self, result, notify)

    def _create_theme_card(self) -> QFrame:
        card = _ThemeLayer._create_theme_card(self)
        self._hide_card_button(card, "테마 설정 저장")
        if hasattr(self, "theme_save_status"):
            self.theme_save_status.hide()
        return card

    def _create_windows_behavior_card(self) -> QFrame:
        card = _BaseSettingsPage._create_windows_behavior_card(self)
        self._hide_card_button(card, "Windows 설정 저장")
        if hasattr(self, "system_save_status"):
            self.system_save_status.hide()
        return card

    def _create_notification_card(self) -> QFrame:
        card = _BaseSettingsPage._create_notification_card(self)
        self._hide_card_button(card, "일반 설정 저장")
        if hasattr(self, "general_save_status"):
            self.general_save_status.hide()
        return card

    def _restore_from_backup(self) -> None:
        _BaseSettingsPage._restore_from_backup(self)
        self._reload_theme_preferences_to_controls()

    def _reset_selected_scope(self) -> None:
        _BaseSettingsPage._reset_selected_scope(self)
        self._reload_theme_preferences_to_controls()


def _copy_methods(source: type, *, excluded: set[str]) -> None:
    """super() 의존성이 없는 검증된 메서드만 최종 SettingsPage에 복사한다."""
    for name, value in source.__dict__.items():
        if name in excluded or name.startswith("__"):
            continue
        if inspect.isfunction(value) or isinstance(value, (staticmethod, classmethod)):
            setattr(SettingsPage, name, value)


_copy_methods(
    _ThemeLayer,
    excluded={
        "__init__",
        "show_settings_tab",
        "_refresh_tool_status",
        "_component_check_done",
        "_create_theme_card",
        "_restore_from_backup",
        "_reset_selected_scope",
    },
)
_copy_methods(
    _CommunityLayer,
    excluded={
        "__init__",
        "_refresh_tool_status",
        "_component_check_done",
        "_create_theme_card",
        "_create_windows_behavior_card",
        "_create_notification_card",
    },
)

# 구버전 내부 import 호환. MainWindow의 기존 import도 동일한 최종 SettingsPage를 받는다.
UnifiedSettingsPage = SettingsPage

__all__ = ["SettingsPage", "UnifiedSettingsPage"]
