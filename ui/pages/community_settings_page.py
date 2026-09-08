from __future__ import annotations

import subprocess

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.component_updates import normalize_ffmpeg_release_version
from app.paths import (
    RRV_BROWSER_EXTENSION_DIR,
    RRV_LOGS_DIR,
    bootstrap_browser_extension,
)
from app.theme import active_theme_mode, load_theme_preference
from services.browser_integration_service import (
    BROWSER_SEND_AUTO_DOWNLOAD,
    BROWSER_SEND_QUEUE_ONLY,
    browser_integration_status,
    load_browser_send_behavior,
)
from services.site_auth_common import detect_chromium_browsers
from ui.dialogs.warm_dialogs import show_warm_message
from ui.pages.theme_settings_page import ThemeSettingsPage
from ui.widgets.common import create_card


class CommunitySettingsPage(ThemeSettingsPage):
    """Community Beta의 최종 사용자 중심 설정 화면."""

    _VISIBLE_TAB_ORDER = (
        (ThemeSettingsPage.GENERAL_TAB, "일반"),
        (ThemeSettingsPage.YOUTUBE_TAB, "사이트 인증"),
        (ThemeSettingsPage.INTEGRATION_TAB, "브라우저 확장"),
        (ThemeSettingsPage.TOOLS_TAB, "도구 및 리소스"),
        (ThemeSettingsPage.PRESET_TAB, "다운로드 프리셋"),
        (ThemeSettingsPage.BACKUP_TAB, "백업 및 복구"),
    )

    def __init__(self) -> None:
        # SettingsPage와 ThemeSettingsPage는 초기화 과정에서 도구 상태 갱신을
        # 요청하지만, 외부 EXE 실행과 WPC 무결성 검사는 창이 보인 뒤 시작되는
        # 백그라운드 구성요소 확인 결과를 재사용한다.
        self._initializing_settings_page = True
        super().__init__()
        self._remove_legacy_about_tab()
        self._initializing_settings_page = False

        for label in self.findChildren(QLabel):
            if label.text() == "RR-V의 기본 동작, 인증, 시스템 연동과 필수 구성요소를 관리합니다.":
                label.setText(
                    "RR-V의 기본 동작, 사이트 인증, 브라우저 확장과 필수 구성요소를 관리합니다."
                )
                break

    def _create_tab_bar(self) -> QFrame:
        tab_bar = QFrame()
        tab_bar.setObjectName("toolTabBar")

        tab_layout = QHBoxLayout(tab_bar)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(8)

        self.tab_button_group = QButtonGroup(self)
        self.tab_button_group.setExclusive(True)
        self.tab_buttons: list[QPushButton] = []

        for page_index, name in self._VISIBLE_TAB_ORDER:
            button = QPushButton(name)
            button.setObjectName("toolTabButton")
            button.setCheckable(True)
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            button.clicked.connect(
                lambda checked=False, target=page_index: self.show_settings_tab(target)
            )
            self.tab_button_group.addButton(button, page_index)
            self.tab_buttons.append(button)
            tab_layout.addWidget(button, 1)

        return tab_bar

    def show_settings_tab(self, index: int) -> None:
        if not hasattr(self, "settings_stack"):
            return
        if index < 0 or index >= self.settings_stack.count():
            index = self.GENERAL_TAB

        if index == self.PRESET_TAB and hasattr(self, "preset_combo"):
            self._load_preferences_into_controls()
        if index == self.YOUTUBE_TAB and hasattr(self, "youtube_auth_status_label"):
            self._refresh_youtube_auth_status()
            if hasattr(self, "instagram_auth_status_label"):
                self._refresh_instagram_auth_status()
            if hasattr(self, "tiktok_auth_status_label"):
                self._refresh_tiktok_auth_status()
        if index == self.INTEGRATION_TAB and hasattr(self, "browser_integration_status_label"):
            self._refresh_browser_integration_status()

        self.settings_stack.setCurrentIndex(index)
        for button in self.tab_buttons:
            button.setChecked(self.tab_button_group.id(button) == index)

        if index == self.GENERAL_TAB and hasattr(self, "theme_light_radio"):
            self._reload_theme_preferences_to_controls()
        elif index == self.TOOLS_TAB and hasattr(self, "tool_status_labels"):
            self._refresh_tool_status()
            if not getattr(self, "_tools_tab_checked_once", False):
                self._tools_tab_checked_once = True
                self.start_component_update_check(force=True, notify=False)

    def _create_integration_tab(self):  # type: ignore[no-untyped-def]
        return self._create_scroll_page([self._create_browser_integration_card()])

    def _create_tools_tab(self):  # type: ignore[no-untyped-def]
        return self._create_scroll_page(
            [
                self._create_tools_and_updates_card(),
                self._create_tool_diagnostics_card(),
                self._create_tool_guide_card(),
            ]
        )

    def _create_backup_tab(self):  # type: ignore[no-untyped-def]
        return self._create_scroll_page(
            [
                self._create_backup_card(),
                self._create_reset_card(),
                self._create_logs_and_diagnostics_card(),
            ]
        )

    def _create_tool_guide_card(self) -> QFrame:
        card, layout = create_card()

        title = QLabel("도구 안내")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "RR-V는 여러 전문 도구를 한 화면에서 연결해 사용합니다. 각 도구가 맡는 역할은 다음과 같습니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        items = (
            (
                "yt-dlp Nightly",
                "YouTube 등 지원 사이트의 영상 정보를 확인하고 실제 다운로드를 담당합니다.",
            ),
            (
                "FFmpeg / FFprobe",
                "영상과 음성을 합치고 변환하며, 파일의 코덱·트랙·메타데이터를 확인하는 미디어 처리 도구입니다.",
            ),
            (
                "Deno",
                "YouTube가 요구하는 JavaScript 처리를 실행해 영상 정보를 안정적으로 가져오도록 돕습니다.",
            ),
            (
                "YouTube 인증 런타임",
                "RR-V 전용 로그인 창과 YouTube의 추가 인증 처리를 지원합니다. 필요한 경우에만 동작합니다.",
            ),
        )

        layout.addWidget(title)
        layout.addWidget(description)
        for name, detail in items:
            item = QFrame()
            item.setObjectName("settingsOptionGroup")
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(14, 10, 14, 10)
            item_layout.setSpacing(4)

            name_label = QLabel(name)
            name_label.setObjectName("settingsGroupTitle")
            detail_label = QLabel(detail)
            detail_label.setObjectName("mutedText")
            detail_label.setWordWrap(True)

            item_layout.addWidget(name_label)
            item_layout.addWidget(detail_label)
            layout.addWidget(item)
        return card

    def _create_logs_and_diagnostics_card(self) -> QFrame:
        card, layout = create_card()

        title = QLabel("로그 및 진단")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "문제가 생겼을 때 작업 로그를 확인하거나 RR-V 버전·도구 상태를 한 번에 복사할 수 있습니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        path_label = QLabel(str(RRV_LOGS_DIR))
        path_label.setObjectName("mutedText")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setWordWrap(True)

        open_button = QPushButton("로그 폴더 열기")
        open_button.setObjectName("secondaryButton")
        open_button.clicked.connect(self._open_logs_folder)

        copy_button = QPushButton("진단 정보 복사")
        copy_button.setObjectName("secondaryButton")
        copy_button.clicked.connect(self._copy_diagnostics)

        self.diagnostic_status_label = QLabel("")
        self.diagnostic_status_label.setObjectName("mutedText")

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(open_button)
        row.addWidget(copy_button)
        row.addStretch()
        row.addWidget(self.diagnostic_status_label)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(path_label)
        layout.addLayout(row)
        return card

    def _create_browser_integration_card(self) -> QFrame:
        card, layout = create_card()

        title = QLabel("브라우저 확장 프로그램")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "Chrome 또는 Edge에서 현재 영상 페이지나 링크를 RR-V 다운로드 목록으로 바로 보낼 수 있습니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        status_row = QHBoxLayout()
        status_row.setSpacing(12)

        self.browser_integration_status_label = QLabel("")
        self.browser_integration_status_label.setObjectName("browserIntegrationStatus")
        self.browser_integration_status_label.setWordWrap(True)

        switch_label = QLabel("브라우저 연결")
        switch_label.setObjectName("settingsInlineLabel")

        self.browser_connection_switch = QToolButton()
        self.browser_connection_switch.setObjectName("browserConnectionSwitch")
        self.browser_connection_switch.setCheckable(True)
        self.browser_connection_switch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browser_connection_switch.toggled.connect(
            self._browser_connection_switch_toggled
        )

        status_row.addWidget(self.browser_integration_status_label, 1)
        status_row.addWidget(switch_label)
        status_row.addWidget(self.browser_connection_switch)

        helper = QLabel(
            "처음 사용하는 경우 아래 설치 순서를 따라 확장 프로그램을 불러온 뒤 브라우저 연결을 켜 주세요."
        )
        helper.setObjectName("mutedText")
        helper.setWordWrap(True)

        self.browser_guide_toggle = QPushButton()
        self.browser_guide_toggle.setObjectName("secondaryButton")
        self.browser_guide_toggle.clicked.connect(
            lambda: self._browser_guide_toggle_changed(
                not self.browser_guide_widget.isVisible()
            )
        )

        guide_toggle_row = QHBoxLayout()
        guide_toggle_row.addWidget(self.browser_guide_toggle)
        guide_toggle_row.addStretch()

        self.browser_guide_widget = QFrame()
        self.browser_guide_widget.setObjectName("browserGuideFrame")
        guide_layout = QVBoxLayout(self.browser_guide_widget)
        guide_layout.setContentsMargins(16, 14, 16, 14)
        guide_layout.setSpacing(10)

        guide_title = QLabel("확장 프로그램 설치 순서")
        guide_title.setObjectName("settingsSubTitle")
        guide_layout.addWidget(guide_title)

        step1 = QLabel("1. 브라우저의 확장 관리 화면을 엽니다.")
        step1.setObjectName("settingsGroupTitle")
        guide_layout.addWidget(step1)

        self._browser_extension_browsers = detect_chromium_browsers()
        browser_buttons = QHBoxLayout()
        browser_buttons.setSpacing(8)
        if self._browser_extension_browsers:
            for browser in self._browser_extension_browsers:
                button = QPushButton(f"{browser.label} 열기 + 관리 주소 복사")
                button.setObjectName("secondaryButton")
                button.clicked.connect(
                    lambda checked=False, key=browser.key: self._open_browser_extension_manager(key)
                )
                browser_buttons.addWidget(button)
            browser_buttons.addStretch()
        else:
            missing = QLabel("지원되는 Chrome 또는 Edge를 찾지 못했습니다.")
            missing.setObjectName("mutedText")
            browser_buttons.addWidget(missing)
        guide_layout.addLayout(browser_buttons)

        manager_hint = QLabel(
            "버튼을 누르면 브라우저를 열고 확장 관리 주소를 클립보드에 복사합니다. "
            "브라우저 주소창에 붙여넣고 Enter를 눌러 주세요."
        )
        manager_hint.setObjectName("mutedText")
        manager_hint.setWordWrap(True)
        guide_layout.addWidget(manager_hint)

        self.browser_manager_copy_status = QLabel("")
        self.browser_manager_copy_status.setObjectName("settingsSavedStatus")
        self.browser_manager_copy_status.setWordWrap(True)
        guide_layout.addWidget(self.browser_manager_copy_status)

        for text in (
            "2. 확장 관리 화면에서 '개발자 모드'를 켭니다.",
            "3. '압축 해제된 확장 프로그램을 로드'를 선택합니다.",
        ):
            label = QLabel(text)
            label.setObjectName("mutedText")
            label.setWordWrap(True)
            guide_layout.addWidget(label)

        step4 = QLabel("4. 폴더 선택 화면에서 아래 RR-V 확장 프로그램 경로를 선택합니다.")
        step4.setObjectName("mutedText")
        step4.setWordWrap(True)
        guide_layout.addWidget(step4)

        self.browser_extension_path_input = QLineEdit(str(RRV_BROWSER_EXTENSION_DIR))
        self.browser_extension_path_input.setObjectName("settingsPathInput")
        self.browser_extension_path_input.setReadOnly(True)

        copy_path_button = QPushButton("경로 복사")
        copy_path_button.setObjectName("secondaryButton")
        copy_path_button.clicked.connect(self._copy_browser_extension_path)

        open_folder_button = QPushButton("폴더 열기")
        open_folder_button.setObjectName("secondaryButton")
        open_folder_button.clicked.connect(self._open_browser_extension_folder)

        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        path_row.addWidget(self.browser_extension_path_input, 1)
        path_row.addWidget(copy_path_button)
        path_row.addWidget(open_folder_button)
        guide_layout.addLayout(path_row)

        self.browser_extension_copy_status = QLabel("")
        self.browser_extension_copy_status.setObjectName("settingsSavedStatus")
        guide_layout.addWidget(self.browser_extension_copy_status)

        for text in (
            "5. 확장 프로그램 목록에 'RR-V Browser Connector'가 표시되는지 확인합니다.",
            "6. RR-V로 돌아와 위쪽의 '브라우저 연결'을 ON으로 켭니다.",
            "7. 영상 페이지에서 RR-V 확장 아이콘을 누르거나, 영상 링크에서 마우스 오른쪽 버튼을 눌러 'RR-V로 링크 보내기'를 선택하면 다운로드 대기 목록에 추가됩니다.",
        ):
            label = QLabel(text)
            label.setObjectName("mutedText")
            label.setWordWrap(True)
            guide_layout.addWidget(label)

        update_note = QLabel(
            "RR-V 업데이트 뒤 확장 프로그램 내용이 바뀐 경우에는 브라우저 확장 관리 화면에서 'RR-V Browser Connector'를 새로고침해 주세요."
        )
        update_note.setObjectName("browserGuideNote")
        update_note.setWordWrap(True)
        guide_layout.addWidget(update_note)

        behavior_frame = QFrame()
        behavior_frame.setObjectName("settingsOptionGroup")
        behavior_layout = QVBoxLayout(behavior_frame)
        behavior_layout.setContentsMargins(14, 12, 14, 12)
        behavior_layout.setSpacing(5)

        behavior_title = QLabel("확장 프로그램으로 링크를 보냈을 때")
        behavior_title.setObjectName("settingsGroupTitle")

        self.browser_queue_only_radio = QRadioButton("대기열에 추가만")
        self.browser_queue_only_radio.setObjectName("settingsRadioButton")
        queue_only_description = QLabel(
            "기본 프리셋으로 영상 정보를 확인하고 다운로드 목록에만 추가합니다."
        )
        queue_only_description.setObjectName("mutedText")
        queue_only_description.setContentsMargins(24, 0, 0, 4)

        self.browser_auto_download_radio = QRadioButton("대기열에 추가 후 자동 다운로드")
        self.browser_auto_download_radio.setObjectName("settingsRadioButton")
        auto_download_description = QLabel(
            "영상 정보를 확인한 뒤 다운로드를 자동으로 시작합니다. 다른 작업이 진행 중이면 대기열에서 차례를 기다립니다."
        )
        auto_download_description.setObjectName("mutedText")
        auto_download_description.setWordWrap(True)
        auto_download_description.setContentsMargins(24, 0, 0, 0)

        behavior_apply_note = QLabel("선택 즉시 적용되며 다음 실행에도 유지됩니다.")
        behavior_apply_note.setObjectName("mutedText")
        behavior_apply_note.setWordWrap(True)

        self.browser_behavior_save_status = QLabel("")
        self.browser_behavior_save_status.setObjectName("settingsSavedStatus")

        behavior_feedback_row = QHBoxLayout()
        behavior_feedback_row.setContentsMargins(0, 5, 0, 0)
        behavior_feedback_row.setSpacing(12)
        behavior_feedback_row.addWidget(behavior_apply_note, 1)
        behavior_feedback_row.addWidget(self.browser_behavior_save_status)

        self.browser_behavior_save_timer = QTimer(self)
        self.browser_behavior_save_timer.setSingleShot(True)
        self.browser_behavior_save_timer.timeout.connect(
            lambda: self.browser_behavior_save_status.setText("")
        )

        self.browser_send_behavior_group = QButtonGroup(self)
        self.browser_send_behavior_group.setExclusive(True)
        self.browser_send_behavior_group.addButton(self.browser_queue_only_radio)
        self.browser_send_behavior_group.addButton(self.browser_auto_download_radio)

        behavior = load_browser_send_behavior()
        self.browser_queue_only_radio.setChecked(behavior != BROWSER_SEND_AUTO_DOWNLOAD)
        self.browser_auto_download_radio.setChecked(behavior == BROWSER_SEND_AUTO_DOWNLOAD)
        self.browser_queue_only_radio.toggled.connect(
            lambda checked: self._browser_send_behavior_changed(
                BROWSER_SEND_QUEUE_ONLY, checked
            )
        )
        self.browser_auto_download_radio.toggled.connect(
            lambda checked: self._browser_send_behavior_changed(
                BROWSER_SEND_AUTO_DOWNLOAD, checked
            )
        )

        behavior_layout.addWidget(behavior_title)
        behavior_layout.addWidget(self.browser_queue_only_radio)
        behavior_layout.addWidget(queue_only_description)
        behavior_layout.addWidget(self.browser_auto_download_radio)
        behavior_layout.addWidget(auto_download_description)
        behavior_layout.addLayout(behavior_feedback_row)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addLayout(status_row)
        layout.addWidget(helper)
        layout.addLayout(guide_toggle_row)
        layout.addWidget(self.browser_guide_widget)
        layout.addWidget(behavior_frame)

        self._refresh_browser_integration_status()
        guide_expanded = self._load_browser_guide_expanded()
        if not browser_integration_status().registered:
            guide_expanded = True
        self._toggle_browser_guide(guide_expanded)
        return card

    def _open_browser_extension_manager(self, browser_key: str) -> None:
        browser = next(
            (item for item in self._browser_extension_browsers if item.key == browser_key),
            None,
        )
        if browser is None:
            show_warm_message(
                self,
                "확장 관리 화면",
                "선택한 브라우저를 찾지 못했습니다.",
            )
            return

        target = "chrome://extensions/" if browser.key == "chrome" else "edge://extensions/"
        QApplication.clipboard().setText(target)

        try:
            subprocess.Popen([str(browser.path)])
        except OSError as error:
            self.browser_manager_copy_status.setText(
                f"{target} 복사됨 · {browser.label}는 직접 열어 주세요."
            )
            show_warm_message(
                self,
                "브라우저 열기",
                f"확장 관리 주소는 클립보드에 복사했습니다.\n"
                f"{browser.label}는 직접 열어 주소창에 붙여넣어 주세요.\n\n{error}",
            )
            return

        self.browser_manager_copy_status.setText(
            f"{target} 복사됨 · 주소창에 붙여넣고 Enter를 눌러 주세요."
        )
        QTimer.singleShot(
            3600,
            lambda: self.browser_manager_copy_status.setText(""),
        )

    def _copy_browser_extension_path(self) -> None:
        bootstrap_browser_extension()
        if not RRV_BROWSER_EXTENSION_DIR.is_dir():
            show_warm_message(
                self,
                "확장 프로그램 폴더",
                "RR-V 브라우저 확장 프로그램 폴더를 찾지 못했습니다.",
            )
            return

        path_text = str(RRV_BROWSER_EXTENSION_DIR.resolve())
        self.browser_extension_path_input.setText(path_text)
        QApplication.clipboard().setText(path_text)
        self.browser_extension_copy_status.setText("확장 프로그램 경로를 복사했습니다.")
        QTimer.singleShot(
            2200,
            lambda: self.browser_extension_copy_status.setText(""),
        )

    def _remove_legacy_about_tab(self) -> None:
        """사이드바의 독립 정보 페이지로 대체된 예전 설정 내부 정보 탭을 제거한다."""
        about_index = int(getattr(self, "ABOUT_TAB", -1))
        if about_index < 0:
            return

        if hasattr(self, "settings_stack") and about_index < self.settings_stack.count():
            about_page = self.settings_stack.widget(about_index)
            self.settings_stack.removeWidget(about_page)
            if about_page is not None:
                about_page.deleteLater()

        if hasattr(self, "tab_button_group"):
            about_button = self.tab_button_group.button(about_index)
            if about_button is not None:
                self.tab_button_group.removeButton(about_button)
                if hasattr(self, "tab_buttons") and about_button in self.tab_buttons:
                    self.tab_buttons.remove(about_button)
                about_button.deleteLater()

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
                self._set_tool_visual(key, "normal", "정상")
            elif issue_kind == "missing":
                self._set_tool_visual(key, "error", "설치 필요")
                missing.add(key)
            else:
                self._set_tool_visual(key, "error", "복구 필요")
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
            self._set_tool_visual("ffmpeg", "normal", "정상")
        else:
            ffmpeg_kind = self._status_issue_kind(ffmpeg)
            ffprobe_kind = self._status_issue_kind(ffprobe)
            both_missing = ffmpeg_kind == "missing" and ffprobe_kind == "missing"
            if both_missing:
                self.tool_version_labels["ffmpeg"].setText("없음")
                self._set_tool_visual("ffmpeg", "error", "설치 필요")
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
                self._set_tool_visual("ffmpeg", "error", "복구 필요")
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
            message = "다른 변경사항은 저장되었습니다. Windows 자동 실행 설정은 적용되지 않았습니다."
        elif theme_restart_needed:
            message = "변경사항 저장됨 · 화면 테마는 RR-V 재시작 후 적용됩니다."
        else:
            message = "변경사항이 저장되었습니다."

        self.general_tab_save_status.setText(message)
        QTimer.singleShot(
            3200,
            lambda: self.general_tab_save_status.setText(""),
        )
