from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import inspect

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.component_updates import ComponentUpdateCheckResult
from core.filename_template import (
    DEFAULT_FILENAME_TEMPLATE,
    FILENAME_TEMPLATE_TOKENS,
    filename_template_values,
    normalize_filename_template,
    render_filename_template,
    validate_filename_template,
)
from ui.pages.community_settings_page import CommunitySettingsPage as _CommunityLayer
from ui.pages.settings_page import SettingsPage as _BaseSettingsPage
from ui.pages.theme_settings_page import ThemeSettingsPage as _ThemeLayer
from ui.widgets.common import create_card


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

    def _create_general_tab(self):  # type: ignore[no-untyped-def]
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(6)

        scroll = self._create_scroll_page(
            [
                self._create_theme_card(),
                self._create_download_folder_card(),
                self._create_filename_template_card(),
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

    def _create_filename_template_card(self) -> QFrame:
        card, layout = create_card()

        title = QLabel("파일명 템플릿")
        title.setObjectName("sectionTitle")

        description = QLabel(
            "다운로드 파일의 이름 조합을 정합니다. 확장자는 RR-V가 자동으로 붙이고, "
            "기존 중복 파일 처리 규칙도 그대로 적용합니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        self.filename_template_input = QLineEdit(
            self._general_preferences.filename_template
        )
        self.filename_template_input.setObjectName("settingsPathInput")
        self.filename_template_input.setPlaceholderText(DEFAULT_FILENAME_TEMPLATE)
        self.filename_template_input.setMaxLength(180)
        self.filename_template_input.textChanged.connect(
            self._refresh_filename_template_preview
        )

        token_row = QHBoxLayout()
        token_row.setSpacing(8)
        for token in FILENAME_TEMPLATE_TOKENS:
            label = token[1:-1]
            if label == "영상ID":
                label = "영상 ID"
            button = QPushButton(f"+ {label}")
            button.setObjectName("secondaryButton")
            button.clicked.connect(
                lambda checked=False, value=token:
                self._insert_filename_template_token(value)
            )
            token_row.addWidget(button)

        reset_button = QPushButton("기본값")
        reset_button.setObjectName("secondaryButton")
        reset_button.clicked.connect(self._reset_filename_template)
        token_row.addStretch()
        token_row.addWidget(reset_button)

        helper = QLabel(
            "사용 가능: {제목} · {채널명} · {영상ID} · {사이트} "
            "예: [{채널명}] {제목} [{영상ID}]"
        )
        helper.setObjectName("mutedText")
        helper.setWordWrap(True)

        self.filename_template_preview = QLabel("")
        self.filename_template_preview.setObjectName("mutedText")
        self.filename_template_preview.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(self.filename_template_input)
        layout.addLayout(token_row)
        layout.addWidget(helper)
        layout.addWidget(self.filename_template_preview)

        self._refresh_filename_template_preview()
        return card

    def _insert_filename_template_token(self, token: str) -> None:
        input_widget = self.filename_template_input
        text = input_widget.text()
        position = input_widget.cursorPosition()
        input_widget.setText(text[:position] + token + text[position:])
        input_widget.setCursorPosition(position + len(token))
        input_widget.setFocus()

    def _reset_filename_template(self) -> None:
        self.filename_template_input.setText(DEFAULT_FILENAME_TEMPLATE)
        self.filename_template_input.setFocus()

    def _refresh_filename_template_preview(self) -> None:
        if not hasattr(self, "filename_template_preview"):
            return

        template = self.filename_template_input.text()
        valid, message = validate_filename_template(template)
        if not valid:
            self.filename_template_preview.setText(f"⚠ {message}")
            return

        sample_values = filename_template_values(
            title="샘플 영상 제목",
            uploader="샘플 채널",
            video_id="abc123",
            extractor="Youtube",
        )
        preview = render_filename_template(template, sample_values)
        self.filename_template_preview.setText(f"예시 파일명: {preview}.mp4")

    def _load_preferences_into_controls(self) -> None:
        _BaseSettingsPage._load_preferences_into_controls(self)
        if hasattr(self, "filename_template_input"):
            self.filename_template_input.setText(
                self._general_preferences.filename_template
            )
            self._refresh_filename_template_preview()

    def _save_general_tab_changes(self) -> None:
        template = normalize_filename_template(
            self.filename_template_input.text()
        )
        valid, message = validate_filename_template(template)
        if not valid:
            self.general_tab_save_status.setText(
                f"파일명 템플릿 확인 필요 · {message}"
            )
            self._refresh_filename_template_preview()
            return

        self.filename_template_input.setText(template)
        self._general_preferences = replace(
            self._general_preferences,
            filename_template=template,
        )
        _CommunityLayer._save_general_tab_changes(self)

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
        "_create_general_tab",
        "_load_preferences_into_controls",
        "_save_general_tab_changes",
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
        "_create_general_tab",
        "_load_preferences_into_controls",
        "_save_general_tab_changes",
    },
)

# 구버전 내부 import 호환. MainWindow의 기존 import도 동일한 최종 SettingsPage를 받는다.
UnifiedSettingsPage = SettingsPage

__all__ = ["SettingsPage", "UnifiedSettingsPage"]
