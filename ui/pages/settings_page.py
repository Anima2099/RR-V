from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
import platform
import sys
import threading

from PySide6.QtCore import QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QToolButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.general_preferences import (
    FILE_COLLISION_NUMBERED,
    FILE_COLLISION_OVERWRITE,
    GeneralPreferences,
    load_general_preferences,
    save_general_preferences,
)
from app.constants import APP_VERSION
from app.paths import (
    RRV_BACKUPS_DIR,
    RRV_INSTAGRAM_AUTH_RESULT_PATH,
    RRV_TIKTOK_AUTH_RESULT_PATH,
    RRV_LOGS_DIR,
    RRV_TOOLS_DIR,
    RRV_YOUTUBE_AUTH_RESULT_PATH,
    RRV_BROWSER_EXTENSION_DIR,
    bootstrap_browser_extension,
    has_bundled_tools,
)
from app.settings_store import SETTINGS_PATH, get_settings
from app.settings_backup import (
    create_backup,
    latest_backup,
    reset_scope,
    restore_backup,
)
from app.tool_manager import inspect_tools, restore_packaged_tools, update_deno, update_ytdlp
from services.instagram_auth_service import (
    delete_instagram_auth,
    instagram_auth_status,
    instagram_auth_status_text,
    perform_instagram_login,
)
from services.tiktok_auth_service import (
    delete_tiktok_auth,
    perform_tiktok_login,
    tiktok_auth_status,
    tiktok_auth_status_text,
)
from services.youtube_auth_service import (
    detect_chromium_browsers,
    load_preferred_browser_key,
    perform_youtube_login,
    youtube_auth_status,
    youtube_auth_status_text,
)
from services.windows_startup_service import (
    WindowsStartupError,
    is_windows_startup_supported,
    set_windows_startup_enabled,
)
from services.browser_integration_service import (
    BROWSER_SEND_AUTO_DOWNLOAD,
    BROWSER_SEND_QUEUE_ONLY,
    BrowserIntegrationError,
    browser_integration_status,
    load_browser_send_behavior,
    register_browser_integration,
    save_browser_send_behavior,
    unregister_browser_integration,
)
from app.download_preferences import (
    AUDIO_FORMAT_CHOICES,
    AUDIO_QUALITY_CHOICES,
    CODEC_CHOICES,
    CONTAINER_CHOICES,
    RESOLUTION_CHOICES,
    DownloadPreferences,
)
from app.preset_store import (
    DownloadPreset,
    load_preset_library,
    save_preset_library,
)
from ui.dialogs.warm_dialogs import (
    ask_warm_question,
    choose_warm_item,
    prompt_warm_text,
    show_warm_message,
)
from ui.widgets.common import NoWheelComboBox, create_card


_MANUAL_COOKIE_EXPANDED_KEY = "window/settings_manual_cookie_expanded"
_BROWSER_EXTENSION_GUIDE_EXPANDED_KEY = "window/settings_browser_extension_guide_expanded"


class SettingsPage(QWidget):
    general_preferences_saved = Signal()
    tool_action_finished = Signal(bool, str)
    tool_action_status = Signal(str)
    youtube_login_status = Signal(str)
    youtube_login_finished = Signal(object)
    instagram_login_status = Signal(str)
    instagram_login_finished = Signal(object)
    tiktok_login_status = Signal(str)
    tiktok_login_finished = Signal(object)

    GENERAL_TAB = 0
    PRESET_TAB = 1
    YOUTUBE_TAB = 2
    INTEGRATION_TAB = 3
    TOOLS_TAB = 4
    BACKUP_TAB = 5

    def __init__(self) -> None:
        super().__init__()
        self._applying_preset = False
        self._general_preferences = load_general_preferences()
        self._preset_library = load_preset_library()

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(28, 24, 28, 24)
        outer_layout.setSpacing(18)

        title = QLabel("설정")
        title.setObjectName("pageTitle")

        subtitle = QLabel("RR-V의 기본 동작, 인증, 시스템 연동과 필수 구성요소를 관리합니다.")
        subtitle.setObjectName("bodyText")

        outer_layout.addWidget(title)
        outer_layout.addWidget(subtitle)
        outer_layout.addWidget(self._create_tab_bar())

        content_card = QFrame()
        content_card.setObjectName("toolContentCard")
        content_layout = QVBoxLayout(content_card)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.settings_stack = QStackedWidget()
        self.settings_stack.setObjectName("toolStack")
        self.settings_stack.addWidget(self._create_general_tab())
        self.settings_stack.addWidget(self._create_preset_tab())
        self.settings_stack.addWidget(self._create_youtube_tab())
        self.settings_stack.addWidget(self._create_integration_tab())
        self.settings_stack.addWidget(self._create_tools_tab())
        self.settings_stack.addWidget(self._create_backup_tab())

        content_layout.addWidget(self.settings_stack)
        outer_layout.addWidget(content_card, 1)

        self.tool_action_finished.connect(self._tool_action_done)
        self.tool_action_status.connect(self._set_tool_action_status)
        self.youtube_login_status.connect(self._set_youtube_login_status)
        self.youtube_login_finished.connect(self._youtube_login_done)
        self.instagram_login_status.connect(self._set_instagram_login_status)
        self.instagram_login_finished.connect(self._instagram_login_done)
        self.tiktok_login_status.connect(self._set_tiktok_login_status)
        self.tiktok_login_finished.connect(self._tiktok_login_done)
        self._load_preferences_into_controls()
        self._refresh_tool_status()
        self._refresh_backup_status()
        self.show_settings_tab(self.GENERAL_TAB)

    def _create_tab_bar(self) -> QFrame:
        tab_bar = QFrame()
        tab_bar.setObjectName("toolTabBar")

        tab_layout = QHBoxLayout(tab_bar)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(8)

        self.tab_button_group = QButtonGroup(self)
        self.tab_button_group.setExclusive(True)
        self.tab_buttons: list[QPushButton] = []

        for index, name in enumerate(
            (
                "일반",
                "다운로드 프리셋",
                "사이트 인증",
                "시스템 연동",
                "도구 및 리소스",
                "백업 및 복구",
            )
        ):
            button = QPushButton(name)
            button.setObjectName("toolTabButton")
            button.setCheckable(True)
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            button.clicked.connect(
                lambda checked=False, page_index=index:
                self.show_settings_tab(page_index)
            )
            self.tab_button_group.addButton(button, index)
            self.tab_buttons.append(button)
            tab_layout.addWidget(button, 1)

        return tab_bar

    def show_settings_tab(self, index: int) -> None:
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
        for button_index, button in enumerate(self.tab_buttons):
            button.setChecked(button_index == index)

    def _create_scroll_page(self, widgets: list[QWidget]) -> QScrollArea:
        scroll_area = QScrollArea()
        scroll_area.setObjectName("settingsTabScroll")
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 4, 20)
        content_layout.setSpacing(14)
        for widget in widgets:
            content_layout.addWidget(widget)
        content_layout.addStretch()
        scroll_area.setWidget(content)
        return scroll_area

    def _create_preset_tab(self) -> QScrollArea:
        return self._create_scroll_page(
            [self._create_download_preferences_card()]
        )

    def _create_general_tab(self) -> QScrollArea:
        return self._create_scroll_page(
            [
                self._create_download_folder_card(),
                self._create_file_collision_card(),
                self._create_queue_restore_card(),
                self._create_notification_card(),
            ]
        )

    def _create_youtube_tab(self) -> QScrollArea:
        return self._create_scroll_page(
            [
                self._create_cookie_folder_card(),
                self._create_instagram_auth_card(),
                self._create_tiktok_auth_card(),
            ]
        )

    def _create_integration_tab(self) -> QScrollArea:
        return self._create_scroll_page(
            [
                self._create_windows_behavior_card(),
                self._create_browser_integration_card(),
            ]
        )

    def _create_download_folder_card(self) -> QFrame:
        card, layout = create_card()

        title = QLabel("기본 다운로드 폴더")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "새로 추가하는 영상의 기본 저장 위치입니다. 이미 목록에 들어간 작업의 경로는 변경되지 않습니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        self.download_folder_input = QLineEdit(
            self._general_preferences.default_download_folder
        )
        self.download_folder_input.setObjectName("settingsPathInput")

        choose_button = QPushButton("폴더 선택")
        choose_button.setObjectName("secondaryButton")
        choose_button.clicked.connect(self._choose_download_folder)

        open_button = QPushButton("폴더 열기")
        open_button.setObjectName("secondaryButton")
        open_button.clicked.connect(self._open_download_folder)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.download_folder_input, 1)
        row.addWidget(choose_button)
        row.addWidget(open_button)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addLayout(row)
        return card

    def _create_cookie_folder_card(self) -> QFrame:
        card, layout = create_card()

        title = QLabel("YouTube 인증")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "YouTube는 전용 인증 창에서 로그인하면 RR-V가 인증 정보를 자동으로 저장해 사용합니다. "
            "대부분의 사용자는 별도 쿠키 폴더를 설정할 필요가 없습니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        youtube_label = QLabel("로그인 브라우저")
        youtube_label.setObjectName("settingsGroupTitle")

        self.youtube_browser_combo = NoWheelComboBox()
        self.youtube_browser_combo.setObjectName("settingsComboBox")
        self._youtube_browsers = detect_chromium_browsers()
        preferred_key = load_preferred_browser_key()
        for browser in self._youtube_browsers:
            self.youtube_browser_combo.addItem(browser.label, browser.key)

        if self._youtube_browsers:
            preferred_index = self.youtube_browser_combo.findData(preferred_key)
            self.youtube_browser_combo.setCurrentIndex(max(0, preferred_index))
        else:
            self.youtube_browser_combo.addItem("지원 브라우저를 찾지 못함", "")
            self.youtube_browser_combo.setEnabled(False)

        self.youtube_login_button = QPushButton("YouTube 로그인")
        self.youtube_login_button.setObjectName("primaryButton")
        self.youtube_login_button.setEnabled(bool(self._youtube_browsers))
        self.youtube_login_button.clicked.connect(self._start_youtube_login)

        youtube_row = QHBoxLayout()
        youtube_row.setSpacing(10)
        youtube_row.addWidget(youtube_label)
        youtube_row.addWidget(self.youtube_browser_combo, 1)
        youtube_row.addWidget(self.youtube_login_button)

        self.youtube_auth_status_label = QLabel("")
        self.youtube_auth_status_label.setObjectName("youtubeAuthStatus")
        self.youtube_auth_status_label.setWordWrap(True)

        self.youtube_auth_detail_label = QLabel("")
        self.youtube_auth_detail_label.setObjectName("mutedText")
        self.youtube_auth_detail_label.setWordWrap(True)

        youtube_hint = QLabel(
            "작은 전용 브라우저 창에서 YouTube의 [로그인]을 눌러 로그인하면 됩니다. "
            "로그인 완료를 감지하면 창을 즉시 숨기고 인증 정보를 저장합니다. "
            "RR-V는 Google 비밀번호를 직접 입력받거나 저장하지 않습니다."
        )
        youtube_hint.setObjectName("mutedText")
        youtube_hint.setWordWrap(True)

        self.manual_cookie_toggle = QPushButton("고급 설정 · 수동 쿠키 보기")
        self.manual_cookie_toggle.setObjectName("secondaryButton")
        self.manual_cookie_toggle.setCheckable(True)
        self.manual_cookie_toggle.toggled.connect(self._manual_cookie_toggle_changed)

        self.manual_cookie_widget = QFrame()
        self.manual_cookie_widget.setObjectName("settingsFormFrame")
        manual_layout = QVBoxLayout(self.manual_cookie_widget)
        manual_layout.setContentsMargins(14, 12, 14, 12)
        manual_layout.setSpacing(10)

        manual_title = QLabel("수동 쿠키 폴더 · 선택 사항")
        manual_title.setObjectName("settingsGroupTitle")
        manual_description = QLabel(
            "YouTube 전용 인증이 정상 작동하면 이 설정은 사용할 필요가 없습니다. "
            "YouTube 인증을 사용할 수 없는 경우의 보조 수단이나, 다른 사이트의 쿠키 파일을 직접 사용할 때만 지정하세요."
        )
        manual_description.setObjectName("mutedText")
        manual_description.setWordWrap(True)

        self.cookie_folder_input = QLineEdit(self._general_preferences.cookie_folder)
        self.cookie_folder_input.setObjectName("settingsPathInput")
        self.cookie_folder_input.setPlaceholderText("선택 사항 · 수동 쿠키 파일 폴더")

        choose_button = QPushButton("폴더 선택")
        choose_button.setObjectName("secondaryButton")
        choose_button.clicked.connect(self._choose_cookie_folder)

        open_button = QPushButton("폴더 열기")
        open_button.setObjectName("secondaryButton")
        open_button.clicked.connect(self._open_cookie_folder)

        clear_button = QPushButton("지우기")
        clear_button.setObjectName("secondaryButton")
        clear_button.clicked.connect(lambda: self.cookie_folder_input.clear())

        cookie_row = QHBoxLayout()
        cookie_row.setSpacing(10)
        cookie_row.addWidget(self.cookie_folder_input, 1)
        cookie_row.addWidget(choose_button)
        cookie_row.addWidget(open_button)
        cookie_row.addWidget(clear_button)

        cookie_hint = QLabel(
            "파일명 예: youtube.txt, instagram.txt, tiktok.txt, chzzk.txt, soop.txt, twitch.txt, cookies.txt · "
            "YouTube는 RR-V 전용 인증 정보가 없을 때만 이 폴더의 youtube.txt를 보조로 사용합니다."
        )
        cookie_hint.setObjectName("mutedText")
        cookie_hint.setWordWrap(True)

        self.youtube_cookie_save_status = QLabel("")
        self.youtube_cookie_save_status.setObjectName("settingsSavedStatus")

        save_cookie_button = QPushButton("수동 쿠키 설정 저장")
        save_cookie_button.setObjectName("primaryButton")
        save_cookie_button.clicked.connect(self._save_youtube_preferences)

        cookie_save_row = QHBoxLayout()
        cookie_save_row.addWidget(self.youtube_cookie_save_status)
        cookie_save_row.addStretch()
        cookie_save_row.addWidget(save_cookie_button)

        manual_layout.addWidget(manual_title)
        manual_layout.addWidget(manual_description)
        manual_layout.addLayout(cookie_row)
        manual_layout.addWidget(cookie_hint)
        manual_layout.addLayout(cookie_save_row)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addLayout(youtube_row)
        layout.addWidget(self.youtube_auth_status_label)
        layout.addWidget(self.youtube_auth_detail_label)
        layout.addWidget(youtube_hint)
        layout.addWidget(self.manual_cookie_toggle)
        layout.addWidget(self.manual_cookie_widget)

        show_manual = self._load_manual_cookie_expanded()
        self.manual_cookie_toggle.blockSignals(True)
        self.manual_cookie_toggle.setChecked(show_manual)
        self.manual_cookie_toggle.blockSignals(False)
        self._toggle_manual_cookie_section(show_manual)
        self._refresh_youtube_auth_status()
        return card

    def _create_instagram_auth_card(self) -> QFrame:
        card, layout = create_card()

        title = QLabel("Instagram 인증")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "공개 Reel은 로그인 없이 받을 수 있지만, 로그인이나 계정 확인이 필요한 콘텐츠는 "
            "Instagram 인증을 연결하면 접근 가능한 범위가 넓어질 수 있습니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        browser_label = QLabel("로그인 브라우저")
        browser_label.setObjectName("settingsGroupTitle")

        self.instagram_browser_combo = NoWheelComboBox()
        self.instagram_browser_combo.setObjectName("settingsComboBox")
        self._instagram_browsers = detect_chromium_browsers()
        preferred_key = load_preferred_browser_key()
        for browser in self._instagram_browsers:
            self.instagram_browser_combo.addItem(browser.label, browser.key)

        if self._instagram_browsers:
            preferred_index = self.instagram_browser_combo.findData(preferred_key)
            self.instagram_browser_combo.setCurrentIndex(max(0, preferred_index))
        else:
            self.instagram_browser_combo.addItem("지원 브라우저를 찾지 못함", "")
            self.instagram_browser_combo.setEnabled(False)

        self.instagram_login_button = QPushButton("Instagram 로그인")
        self.instagram_login_button.setObjectName("primaryButton")
        self.instagram_login_button.setEnabled(bool(self._instagram_browsers))
        self.instagram_login_button.clicked.connect(self._start_instagram_login)

        self.instagram_delete_button = QPushButton("인증 삭제")
        self.instagram_delete_button.setObjectName("secondaryButton")
        self.instagram_delete_button.clicked.connect(self._delete_instagram_auth)

        login_row = QHBoxLayout()
        login_row.setSpacing(10)
        login_row.addWidget(browser_label)
        login_row.addWidget(self.instagram_browser_combo, 1)
        login_row.addWidget(self.instagram_login_button)
        login_row.addWidget(self.instagram_delete_button)

        self.instagram_auth_status_label = QLabel("")
        self.instagram_auth_status_label.setObjectName("youtubeAuthStatus")
        self.instagram_auth_status_label.setWordWrap(True)

        self.instagram_auth_detail_label = QLabel("")
        self.instagram_auth_detail_label.setObjectName("mutedText")
        self.instagram_auth_detail_label.setWordWrap(True)

        hint = QLabel(
            "RR-V가 띄운 Instagram 로그인 화면에서 직접 로그인합니다. 비밀번호는 RR-V가 "
            "입력받거나 저장하지 않고, 로그인 완료 후 Instagram 세션 쿠키만 로컬에 저장합니다. "
            "인증을 연결해도 Instagram 또는 yt-dlp 자체의 일시적인 사이트 오류는 별개로 발생할 수 있습니다."
        )
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addLayout(login_row)
        layout.addWidget(self.instagram_auth_status_label)
        layout.addWidget(self.instagram_auth_detail_label)
        layout.addWidget(hint)

        self._refresh_instagram_auth_status()
        return card

    def _create_tiktok_auth_card(self) -> QFrame:
        card, layout = create_card()

        title = QLabel("TikTok 인증")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "공개 영상은 인증 없이 동작할 수 있지만, 민감하거나 연령 제한 등 로그인이 필요한 "
            "콘텐츠에서는 TikTok 인증을 사용할 수 있습니다. 현재 TikTok/yt-dlp의 일시적인 "
            "사이트 오류는 로그인 여부와 별개로 발생할 수 있습니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        browser_label = QLabel("로그인 브라우저")
        browser_label.setObjectName("settingsGroupTitle")

        self.tiktok_browser_combo = NoWheelComboBox()
        self.tiktok_browser_combo.setObjectName("settingsComboBox")
        self._tiktok_browsers = detect_chromium_browsers()
        preferred_key = load_preferred_browser_key()
        for browser in self._tiktok_browsers:
            self.tiktok_browser_combo.addItem(browser.label, browser.key)

        if self._tiktok_browsers:
            preferred_index = self.tiktok_browser_combo.findData(preferred_key)
            self.tiktok_browser_combo.setCurrentIndex(max(0, preferred_index))
        else:
            self.tiktok_browser_combo.addItem("지원 브라우저를 찾지 못함", "")
            self.tiktok_browser_combo.setEnabled(False)

        self.tiktok_login_button = QPushButton("TikTok 로그인")
        self.tiktok_login_button.setObjectName("primaryButton")
        self.tiktok_login_button.setEnabled(bool(self._tiktok_browsers))
        self.tiktok_login_button.clicked.connect(self._start_tiktok_login)

        self.tiktok_delete_button = QPushButton("인증 삭제")
        self.tiktok_delete_button.setObjectName("secondaryButton")
        self.tiktok_delete_button.clicked.connect(self._delete_tiktok_auth)

        login_row = QHBoxLayout()
        login_row.setSpacing(10)
        login_row.addWidget(browser_label)
        login_row.addWidget(self.tiktok_browser_combo, 1)
        login_row.addWidget(self.tiktok_login_button)
        login_row.addWidget(self.tiktok_delete_button)

        self.tiktok_auth_status_label = QLabel("")
        self.tiktok_auth_status_label.setObjectName("youtubeAuthStatus")
        self.tiktok_auth_status_label.setWordWrap(True)

        self.tiktok_auth_detail_label = QLabel("")
        self.tiktok_auth_detail_label.setObjectName("mutedText")
        self.tiktok_auth_detail_label.setWordWrap(True)

        hint = QLabel(
            "RR-V가 띄운 TikTok 로그인 화면에서 직접 로그인합니다. 비밀번호는 RR-V가 "
            "입력받거나 저장하지 않고, 로그인 완료 후 TikTok 세션 쿠키만 로컬에 저장합니다. "
            "현재 yt-dlp의 TikTok 추출 문제가 발생하는 영상은 인증 후에도 실패할 수 있습니다."
        )
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addLayout(login_row)
        layout.addWidget(self.tiktok_auth_status_label)
        layout.addWidget(self.tiktok_auth_detail_label)
        layout.addWidget(hint)

        self._refresh_tiktok_auth_status()
        return card

    def _create_file_collision_card(self) -> QFrame:
        card, layout = create_card()

        title = QLabel("동일한 파일명 처리")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "다운로드 폴더에 같은 이름의 파일이 이미 있을 때 처리 방법을 정합니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        self.numbered_file_radio = QRadioButton(
            "숫자를 붙여 새 파일로 저장"
        )
        self.numbered_file_radio.setObjectName("settingsRadioButton")
        numbered_description = QLabel(
            "예: 영상.mp4 → 영상 (2).mp4 → 영상 (3).mp4"
        )
        numbered_description.setObjectName("mutedText")
        numbered_description.setContentsMargins(24, 0, 0, 6)

        self.overwrite_file_radio = QRadioButton("기존 파일 덮어쓰기")
        self.overwrite_file_radio.setObjectName("settingsRadioButton")
        overwrite_description = QLabel(
            "같은 이름의 영상·자막·JPG 썸네일을 새 다운로드 결과로 교체합니다."
        )
        overwrite_description.setObjectName("mutedText")
        overwrite_description.setWordWrap(True)
        overwrite_description.setContentsMargins(24, 0, 0, 0)

        self.collision_button_group = QButtonGroup(self)
        self.collision_button_group.setExclusive(True)
        self.collision_button_group.addButton(
            self.numbered_file_radio,
            0,
        )
        self.collision_button_group.addButton(
            self.overwrite_file_radio,
            1,
        )

        if (
            self._general_preferences.file_collision_mode
            == FILE_COLLISION_OVERWRITE
        ):
            self.overwrite_file_radio.setChecked(True)
        else:
            self.numbered_file_radio.setChecked(True)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(self.numbered_file_radio)
        layout.addWidget(numbered_description)
        layout.addWidget(self.overwrite_file_radio)
        layout.addWidget(overwrite_description)
        return card

    def _create_queue_restore_card(self) -> QFrame:
        card, layout = create_card()

        title = QLabel("작업 목록과 종료")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "프로그램을 다시 열었을 때 이전 작업 목록을 복원하고, 다운로드 중 종료 동작을 정합니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        self.restore_queue_checkbox = QCheckBox(
            "프로그램 시작 시 이전 작업 목록 복원"
        )
        self.keep_completed_checkbox = QCheckBox(
            "복원할 때 완료된 항목도 유지"
        )
        self.confirm_close_checkbox = QCheckBox(
            "다운로드 중 창을 닫을 때 확인"
        )

        for checkbox in (
            self.restore_queue_checkbox,
            self.keep_completed_checkbox,
            self.confirm_close_checkbox,
        ):
            checkbox.setObjectName("settingsCheckbox")

        self.restore_queue_checkbox.setChecked(
            self._general_preferences.restore_queue_on_start
        )
        self.keep_completed_checkbox.setChecked(
            self._general_preferences.keep_completed_tasks
        )
        self.confirm_close_checkbox.setChecked(
            self._general_preferences.confirm_close_during_download
        )
        self.restore_queue_checkbox.toggled.connect(
            self.keep_completed_checkbox.setEnabled
        )
        self.keep_completed_checkbox.setEnabled(
            self.restore_queue_checkbox.isChecked()
        )

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(self.restore_queue_checkbox)
        layout.addWidget(self.keep_completed_checkbox)
        layout.addWidget(self.confirm_close_checkbox)
        return card

    def _create_windows_behavior_card(self) -> QFrame:
        card, layout = create_card()

        title = QLabel("Windows 실행")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "RR-V 창을 닫았을 때의 동작과 Windows 로그인 시 자동 실행 여부를 정합니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        self.minimize_to_tray_checkbox = QCheckBox(
            "창을 닫으면 시스템 트레이로 최소화"
        )
        self.minimize_to_tray_checkbox.setObjectName("settingsCheckbox")
        self.minimize_to_tray_checkbox.setChecked(
            self._general_preferences.minimize_to_tray_on_close
        )

        tray_description = QLabel(
            "X 버튼으로 창을 닫아도 다운로드와 외부 URL 수신을 계속합니다. "
            "트레이 아이콘을 더블클릭하면 RR-V를 다시 열 수 있습니다."
        )
        tray_description.setObjectName("mutedText")
        tray_description.setWordWrap(True)

        self.start_with_windows_checkbox = QCheckBox(
            "Windows 시작 시 RR-V 자동 실행"
        )
        self.start_with_windows_checkbox.setObjectName("settingsCheckbox")
        self.start_with_windows_checkbox.setChecked(
            self._general_preferences.start_with_windows
        )
        self.start_with_windows_checkbox.setEnabled(
            is_windows_startup_supported()
        )

        startup_description = QLabel(
            "두 옵션을 함께 사용하면 Windows 로그인 시 메인 창을 띄우지 않고 "
            "트레이에서 조용히 시작합니다."
        )
        startup_description.setObjectName("mutedText")
        startup_description.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(self.minimize_to_tray_checkbox)
        layout.addWidget(tray_description)
        self.system_save_status = QLabel("")
        self.system_save_status.setObjectName("settingsSavedStatus")

        system_save_button = QPushButton("Windows 설정 저장")
        system_save_button.setObjectName("primaryButton")
        system_save_button.clicked.connect(self._save_system_preferences)

        save_row = QHBoxLayout()
        save_row.addWidget(self.system_save_status)
        save_row.addStretch()
        save_row.addWidget(system_save_button)

        layout.addWidget(self.start_with_windows_checkbox)
        layout.addWidget(startup_description)
        layout.addLayout(save_row)
        return card

    def _create_browser_integration_card(self) -> QFrame:
        card, layout = create_card()

        title = QLabel("브라우저 확장 프로그램")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "Chrome/Edge/Vivaldi 등 Chromium 기반 브라우저에서 현재 페이지나 링크를 "
            "RR-V 다운로드 목록으로 바로 보냅니다."
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
            "처음 연결할 때는 확장 프로그램 폴더를 브라우저의 개발자 모드에서 불러온 뒤 "
            "브라우저 연결을 켜 주세요."
        )
        helper.setObjectName("mutedText")
        helper.setWordWrap(True)

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

        self.browser_auto_download_radio = QRadioButton(
            "대기열에 추가 후 자동 다운로드"
        )
        self.browser_auto_download_radio.setObjectName("settingsRadioButton")
        auto_download_description = QLabel(
            "영상 정보를 확인한 뒤 다운로드를 자동으로 시작합니다. "
            "다른 작업이 진행 중이면 대기열에서 차례를 기다립니다."
        )
        auto_download_description.setObjectName("mutedText")
        auto_download_description.setWordWrap(True)
        auto_download_description.setContentsMargins(24, 0, 0, 0)

        behavior_apply_note = QLabel(
            "선택 즉시 적용되며 다음 실행에도 유지됩니다."
        )
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
        self.browser_queue_only_radio.setChecked(
            behavior != BROWSER_SEND_AUTO_DOWNLOAD
        )
        self.browser_auto_download_radio.setChecked(
            behavior == BROWSER_SEND_AUTO_DOWNLOAD
        )
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

        extension_folder_button = QPushButton("확장 폴더 열기")
        extension_folder_button.setObjectName("primaryButton")
        extension_folder_button.clicked.connect(
            self._open_browser_extension_folder
        )

        self.browser_guide_toggle = QPushButton()
        self.browser_guide_toggle.setObjectName("secondaryButton")
        self.browser_guide_toggle.clicked.connect(
            lambda: self._browser_guide_toggle_changed(
                not self.browser_guide_widget.isVisible()
            )
        )

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        action_row.addWidget(extension_folder_button)
        action_row.addWidget(self.browser_guide_toggle)
        action_row.addStretch()

        self.browser_guide_widget = QFrame()
        self.browser_guide_widget.setObjectName("browserGuideFrame")
        guide_layout = QVBoxLayout(self.browser_guide_widget)
        guide_layout.setContentsMargins(16, 14, 16, 14)
        guide_layout.setSpacing(8)

        guide_title = QLabel("확장 프로그램 설치 순서")
        guide_title.setObjectName("settingsSubTitle")
        guide_layout.addWidget(guide_title)

        guide_lines = (
            "1. 위의 ‘확장 폴더 열기’를 눌러 RR-V 확장 프로그램 폴더를 엽니다.",
            "2. 브라우저의 확장 관리 화면을 엽니다.  Chrome: chrome://extensions  ·  Edge: edge://extensions  ·  Vivaldi: vivaldi://extensions",
            "3. ‘개발자 모드’를 켠 뒤 ‘압축해제된 확장 프로그램을 로드’를 선택합니다.",
            "4. 1번에서 연 RR-V 확장 폴더를 지정합니다.",
            "5. RR-V로 돌아와 오른쪽의 ‘브라우저 연결’을 ON으로 켭니다.",
            "6. 영상 페이지에서 RR-V 확장 아이콘을 눌러 선택한 전송 동작대로 처리되는지 확인합니다.",
        )
        for line in guide_lines:
            label = QLabel(line)
            label.setObjectName("mutedText")
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            guide_layout.addWidget(label)

        update_note = QLabel(
            "확장 프로그램 업데이트 후에는 브라우저의 확장 관리 화면에서 "
            "RR-V Browser Connector를 새로고침해 주세요."
        )
        update_note.setObjectName("browserGuideNote")
        update_note.setWordWrap(True)
        guide_layout.addWidget(update_note)

        guide_expanded = self._load_browser_guide_expanded()
        self._toggle_browser_guide(guide_expanded)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addLayout(status_row)
        layout.addWidget(helper)
        layout.addWidget(behavior_frame)
        layout.addLayout(action_row)
        layout.addWidget(self.browser_guide_widget)

        self._refresh_browser_integration_status()
        return card

    def _refresh_browser_integration_status(self) -> None:
        status = browser_integration_status()
        if not status.supported:
            text = "Windows에서만 브라우저 연결을 사용할 수 있습니다."
        elif status.registered:
            text = "브라우저 연결됨"
        elif status.host_executable is None:
            text = "RR-V.exe 빌드 후 브라우저 연결을 사용할 수 있습니다."
        else:
            text = "브라우저 연결 안 됨"
        self.browser_integration_status_label.setText(text)

        switch_enabled = status.supported and (
            status.registered or status.host_executable is not None
        )
        self.browser_connection_switch.blockSignals(True)
        self.browser_connection_switch.setChecked(status.registered)
        self.browser_connection_switch.setText("ON" if status.registered else "OFF")
        self.browser_connection_switch.setProperty(
            "connectionState", "on" if status.registered else "off"
        )
        self.browser_connection_switch.setEnabled(switch_enabled)
        self.browser_connection_switch.style().unpolish(self.browser_connection_switch)
        self.browser_connection_switch.style().polish(self.browser_connection_switch)
        self.browser_connection_switch.blockSignals(False)

    def _browser_connection_switch_toggled(self, enabled: bool) -> None:
        status = browser_integration_status()
        if enabled:
            if status.registered:
                self._refresh_browser_integration_status()
                return
            try:
                register_browser_integration()
            except BrowserIntegrationError as error:
                show_warm_message(
                    self,
                    "브라우저 연결 실패",
                    str(error),
                )
                self._refresh_browser_integration_status()
                return

            self._refresh_browser_integration_status()
            show_warm_message(
                self,
                "브라우저 연결 완료",
                "브라우저와 RR-V 연결을 켰습니다. 이제 확장 프로그램에서 현재 페이지나 링크를 RR-V로 보낼 수 있습니다.",
            )
            return

        if not status.registered:
            self._refresh_browser_integration_status()
            return

        confirmed = ask_warm_question(
            self,
            "브라우저 연결을 해제할까요?",
            "확장 프로그램은 삭제되지 않지만, 다시 연결할 때까지 브라우저에서 RR-V로 영상을 보낼 수 없습니다.",
            yes_text="연결 해제",
            no_text="취소",
        )
        if not confirmed:
            self._refresh_browser_integration_status()
            return

        try:
            unregister_browser_integration()
        except BrowserIntegrationError as error:
            show_warm_message(
                self,
                "브라우저 연결 해제 실패",
                str(error),
            )
            self._refresh_browser_integration_status()
            return

        self._refresh_browser_integration_status()

    def _browser_send_behavior_changed(
        self,
        behavior: str,
        checked: bool,
    ) -> None:
        if not checked:
            return
        save_browser_send_behavior(behavior)
        self.browser_behavior_save_status.setText("설정이 저장되었습니다.")
        self.browser_behavior_save_timer.start(1800)

    def _load_browser_guide_expanded(self) -> bool:
        settings = get_settings()
        value = settings.value(_BROWSER_EXTENSION_GUIDE_EXPANDED_KEY, False)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _browser_guide_toggle_changed(self, visible: bool) -> None:
        self._toggle_browser_guide(visible)
        settings = get_settings()
        settings.setValue(_BROWSER_EXTENSION_GUIDE_EXPANDED_KEY, bool(visible))
        settings.sync()

    def _toggle_browser_guide(self, visible: bool) -> None:
        if hasattr(self, "browser_guide_widget"):
            self.browser_guide_widget.setVisible(bool(visible))
        if hasattr(self, "browser_guide_toggle"):
            self.browser_guide_toggle.setText(
                "설치 방법 숨기기" if visible else "설치 방법 보기"
            )

    def _open_browser_extension_folder(self) -> None:
        # 사용자가 이 버튼을 누르면 현재 실행 중인 RR-V 번들의 확장 파일을
        # 다시 동기화한다. 업데이트 뒤 오래된 LocalAppData 복사본을 열지 않는다.
        bootstrap_browser_extension()
        if not RRV_BROWSER_EXTENSION_DIR.is_dir():
            show_warm_message(
                self,
                "확장 프로그램 폴더",
                "RR-V 브라우저 확장 프로그램 폴더를 찾지 못했습니다.",
            )
            return
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(RRV_BROWSER_EXTENSION_DIR.resolve()))
        )

    def _create_notification_card(self) -> QFrame:
        card, layout = create_card()

        header = QHBoxLayout()
        title = QLabel("알림")
        title.setObjectName("sectionTitle")
        self.general_save_status = QLabel("")
        self.general_save_status.setObjectName("settingsSavedStatus")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.general_save_status)

        self.notify_queue_checkbox = QCheckBox(
            "대기열 다운로드가 모두 끝나면 화면에 안내"
        )
        self.notify_queue_checkbox.setObjectName("settingsCheckbox")
        self.notify_queue_checkbox.setChecked(
            self._general_preferences.notify_queue_complete
        )

        self.notify_completion_sound_checkbox = QCheckBox(
            "작업 완료 시 소리로 알림"
        )
        self.notify_completion_sound_checkbox.setObjectName("settingsCheckbox")
        self.notify_completion_sound_checkbox.setChecked(
            self._general_preferences.notify_completion_sound
        )
        sound_description = QLabel(
            "다운로드 또는 미디어 작업이 오류 없이 완료되면 Windows 기본 알림음을 한 번 재생합니다."
        )
        sound_description.setObjectName("mutedText")
        sound_description.setWordWrap(True)

        save_button = QPushButton("일반 설정 저장")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._save_general_preferences)

        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(save_button)

        layout.addLayout(header)
        layout.addWidget(self.notify_queue_checkbox)
        layout.addWidget(self.notify_completion_sound_checkbox)
        layout.addWidget(sound_description)
        layout.addLayout(button_row)
        return card

    def _create_tools_tab(self) -> QScrollArea:
        return self._create_scroll_page(
            [
                self._create_runtime_tools_card(),
                self._create_logs_card(),
                self._create_diagnostics_card(),
            ]
        )

    def _create_runtime_tools_card(self) -> QFrame:
        card, layout = create_card()

        title = QLabel("실행 도구")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "다운로드와 미디어 작업에 필요한 도구입니다. RR-V는 아래 전용 폴더의 파일만 사용합니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        path_label = QLabel(str(RRV_TOOLS_DIR))
        path_label.setObjectName("mutedText")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setWordWrap(True)

        self.tool_status_labels: dict[str, QLabel] = {}
        self.tool_version_labels: dict[str, QLabel] = {}
        tool_grid = QGridLayout()
        tool_grid.setHorizontalSpacing(18)
        tool_grid.setVerticalSpacing(10)
        tool_grid.addWidget(self._tool_heading("도구"), 0, 0)
        tool_grid.addWidget(self._tool_heading("상태"), 0, 1)
        tool_grid.addWidget(self._tool_heading("버전"), 0, 2)
        tool_grid.setColumnStretch(0, 1)
        tool_grid.setColumnStretch(1, 1)
        tool_grid.setColumnStretch(2, 2)

        tool_pages = (
            ("ytdlp", "yt-dlp Nightly", "https://github.com/yt-dlp/yt-dlp-nightly-builds/releases"),
            ("ffmpeg", "FFmpeg", "https://ffmpeg.org/download.html"),
            ("ffprobe", "FFprobe", "https://ffmpeg.org/download.html"),
            ("deno", "Deno", "https://github.com/denoland/deno/releases"),
            ("pot", "YouTube 인증 런타임", "https://github.com/coletdjnz/yt-dlp-getpot-wpc"),
        )
        for row, (key, label, url) in enumerate(tool_pages, start=1):
            name_label = QPushButton(label)
            name_label.setObjectName("toolLinkButton")
            name_label.setFlat(True)
            name_label.setCursor(Qt.CursorShape.PointingHandCursor)
            name_font = name_label.font()
            name_font.setUnderline(True)
            name_label.setFont(name_font)
            name_label.setToolTip("공식 페이지 열기")
            name_label.clicked.connect(
                lambda _checked=False, target=url: QDesktopServices.openUrl(QUrl(target))
            )
            status_label = QLabel("확인 중…")
            status_label.setObjectName("mutedText")
            version_label = QLabel("")
            version_label.setObjectName("mutedText")
            version_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            tool_grid.addWidget(name_label, row, 0)
            tool_grid.addWidget(status_label, row, 1)
            tool_grid.addWidget(version_label, row, 2)
            self.tool_status_labels[key] = status_label
            self.tool_version_labels[key] = version_label

        self.tool_action_label = QLabel("")
        self.tool_action_label.setObjectName("mutedText")
        self.tool_action_label.setWordWrap(True)

        utility_row = QHBoxLayout()
        utility_row.setSpacing(8)
        open_button = QPushButton("도구 폴더 열기")
        open_button.setObjectName("secondaryButton")
        open_button.clicked.connect(self._open_tools_folder)

        refresh_button = QPushButton("상태 다시 확인")
        refresh_button.setObjectName("secondaryButton")
        refresh_button.clicked.connect(self._refresh_tool_status)

        utility_row.addWidget(open_button)
        utility_row.addWidget(refresh_button)
        utility_row.addStretch()

        update_row = QHBoxLayout()
        update_row.setSpacing(8)
        self.ytdlp_update_button = QPushButton("yt-dlp 업데이트")
        self.ytdlp_update_button.setObjectName("secondaryButton")
        self.ytdlp_update_button.clicked.connect(self._start_ytdlp_update)

        self.deno_update_button = QPushButton("Deno 업데이트")
        self.deno_update_button.setObjectName("secondaryButton")
        self.deno_update_button.clicked.connect(self._start_deno_update)

        self.restore_tools_button = QPushButton("도구 복구")
        self.restore_tools_button.setObjectName("secondaryButton")
        self.restore_tools_button.clicked.connect(self._restore_packaged_tools)
        self.restore_tools_button.setToolTip(
            "RR-V 패키지에 포함된 기본 도구와 YouTube 인증 런타임으로 복구합니다."
        )

        update_row.addStretch()
        update_row.addWidget(self.ytdlp_update_button)
        update_row.addWidget(self.deno_update_button)
        update_row.addWidget(self.restore_tools_button)

        hint = QLabel(
            "yt-dlp는 Nightly 채널을 사용합니다. Deno는 YouTube JavaScript 검증을 처리합니다. "
            "YouTube 인증 런타임은 로그인 창(nodriver)과, YouTube가 요구할 때만 추가 인증(WPC)을 처리합니다. "
            "일반 다운로드에서는 WPC가 필요하지 않으면 별도 브라우저 창을 열지 않습니다."
        )
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(path_label)
        layout.addLayout(tool_grid)
        layout.addWidget(hint)
        layout.addWidget(self.tool_action_label)
        layout.addLayout(utility_row)
        layout.addLayout(update_row)
        return card

    @staticmethod
    def _tool_heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("settingsGroupTitle")
        return label

    def _create_logs_card(self) -> QFrame:
        card, layout = create_card()
        title = QLabel("로그")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "다운로드, 변환, 썸네일, 스냅샷, 자막 작업 로그가 저장되는 폴더입니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        path_label = QLabel(str(RRV_LOGS_DIR))
        path_label.setObjectName("mutedText")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setWordWrap(True)

        button = QPushButton("로그 폴더 열기")
        button.setObjectName("secondaryButton")
        button.clicked.connect(self._open_logs_folder)
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(path_label)
        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignRight)
        return card

    def _create_diagnostics_card(self) -> QFrame:
        card, layout = create_card()
        title = QLabel("진단")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "문제가 생겼을 때 RR-V 버전과 도구 상태를 한 번에 복사합니다. 오류를 설명할 때 붙여넣기 편합니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        copy_button = QPushButton("진단 정보 복사")
        copy_button.setObjectName("secondaryButton")
        copy_button.clicked.connect(self._copy_diagnostics)

        self.diagnostic_status_label = QLabel("")
        self.diagnostic_status_label.setObjectName("mutedText")

        row = QHBoxLayout()
        row.addWidget(self.diagnostic_status_label)
        row.addStretch()
        row.addWidget(copy_button)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addLayout(row)
        return card

    def _create_backup_tab(self) -> QScrollArea:
        return self._create_scroll_page(
            [
                self._create_backup_card(),
                self._create_reset_card(),
            ]
        )

    def _create_backup_card(self) -> QFrame:
        card, layout = create_card()
        title = QLabel("설정 백업과 복구")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "다운로드 프리셋, 미디어 도구 설정, 접힘 상태와 창 설정을 JSON 파일로 백업합니다. 작업 대기열과 로그는 포함하지 않습니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        self.backup_status_label = QLabel("")
        self.backup_status_label.setObjectName("mutedText")
        self.backup_status_label.setWordWrap(True)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        open_button = QPushButton("백업 폴더 열기")
        open_button.setObjectName("secondaryButton")
        open_button.clicked.connect(self._open_backup_folder)

        backup_button = QPushButton("지금 백업")
        backup_button.setObjectName("primaryButton")
        backup_button.clicked.connect(self._manual_backup)

        restore_button = QPushButton("백업에서 복구")
        restore_button.setObjectName("secondaryButton")
        restore_button.clicked.connect(self._restore_from_backup)

        button_row.addWidget(open_button)
        button_row.addStretch()
        button_row.addWidget(restore_button)
        button_row.addWidget(backup_button)

        auto_hint = QLabel(
            "RR-V는 하루에 한 번 자동 백업을 만들고 최근 5개만 보관합니다."
        )
        auto_hint.setObjectName("mutedText")
        auto_hint.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(self.backup_status_label)
        layout.addWidget(auto_hint)
        layout.addLayout(button_row)
        return card

    def _create_reset_card(self) -> QFrame:
        card, layout = create_card()
        title = QLabel("설정 초기화")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "문제가 생긴 부분만 골라 초기화할 수 있습니다. 실행 전 현재 설정을 자동으로 백업합니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        self.reset_scope_combo = NoWheelComboBox()
        self.reset_scope_combo.setObjectName("settingsComboBox")
        self.reset_scope_combo.addItems(
            [
                "UI 배치와 접힘 상태",
                "미디어 도구 설정",
                "다운로드 프리셋",
                "모든 설정",
            ]
        )

        reset_button = QPushButton("선택 항목 초기화")
        reset_button.setObjectName("secondaryButton")
        reset_button.clicked.connect(self._reset_selected_scope)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.reset_scope_combo, 1)
        row.addWidget(reset_button)

        self.reset_status_label = QLabel("")
        self.reset_status_label.setObjectName("mutedText")
        self.reset_status_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addLayout(row)
        layout.addWidget(self.reset_status_label)
        return card

    def _set_youtube_auth_visual(self, state: str, title: str, detail: str) -> None:
        if not hasattr(self, "youtube_auth_status_label"):
            return
        self.youtube_auth_status_label.setText(title)
        self.youtube_auth_status_label.setProperty("authState", state)
        style = self.youtube_auth_status_label.style()
        style.unpolish(self.youtube_auth_status_label)
        style.polish(self.youtube_auth_status_label)
        self.youtube_auth_status_label.update()
        if hasattr(self, "youtube_auth_detail_label"):
            self.youtube_auth_detail_label.setText(detail)

    def _refresh_youtube_auth_status(self) -> None:
        if not hasattr(self, "youtube_auth_status_label"):
            return
        status = youtube_auth_status()
        if status.has_login_cookie:
            stamp = (
                status.modified_at.strftime("%Y-%m-%d %H:%M")
                if status.modified_at
                else "시간 확인 불가"
            )
            self._set_youtube_auth_visual(
                "ready",
                "YouTube 인증됨",
                f"쿠키 {status.cookie_count}개 · 마지막 갱신 {stamp}",
            )
        elif status.exists:
            self._set_youtube_auth_visual(
                "error",
                "YouTube 인증 정보 확인 필요",
                f"쿠키 {status.cookie_count}개가 있지만 로그인 인증을 확인하지 못했습니다. 인증 갱신을 실행해 주세요.",
            )
        else:
            self._set_youtube_auth_visual(
                "missing",
                "YouTube 인증 필요",
                "아직 저장된 YouTube 인증 정보가 없습니다.",
            )

        if hasattr(self, "youtube_login_button"):
            self.youtube_login_button.setText(
                "인증 갱신" if status.has_login_cookie else "YouTube 로그인"
            )

    def _load_manual_cookie_expanded(self) -> bool:
        settings = get_settings()
        if not settings.contains(_MANUAL_COOKIE_EXPANDED_KEY):
            return bool(self._general_preferences.cookie_folder.strip())
        value = settings.value(_MANUAL_COOKIE_EXPANDED_KEY, False)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _manual_cookie_toggle_changed(self, visible: bool) -> None:
        self._toggle_manual_cookie_section(visible)
        settings = get_settings()
        settings.setValue(_MANUAL_COOKIE_EXPANDED_KEY, bool(visible))
        settings.sync()

    def _toggle_manual_cookie_section(self, visible: bool) -> None:
        if hasattr(self, "manual_cookie_widget"):
            self.manual_cookie_widget.setVisible(bool(visible))
        if hasattr(self, "manual_cookie_toggle"):
            self.manual_cookie_toggle.setText(
                "고급 설정 · 수동 쿠키 숨기기"
                if visible
                else "고급 설정 · 수동 쿠키 보기"
            )

    def _show_warm_message(
        self,
        icon: QMessageBox.Icon,
        title: str,
        text: str,
    ) -> None:
        box = QMessageBox(self)
        box.setObjectName("warmMessageBox")
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(title)
        box.setInformativeText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def _start_youtube_login(self) -> None:
        browser_key = str(self.youtube_browser_combo.currentData() or "").strip()
        if not browser_key:
            self._show_warm_message(
                QMessageBox.Icon.Warning,
                "YouTube 로그인",
                "Chrome, Vivaldi, Edge 또는 Brave를 찾지 못했습니다.",
            )
            return

        self.youtube_login_button.setEnabled(False)
        self.youtube_browser_combo.setEnabled(False)
        self._set_youtube_auth_visual(
            "busy",
            "YouTube 인증 진행 중",
            "인증 창을 준비하는 중…",
        )

        def run() -> None:
            result = perform_youtube_login(
                browser_key,
                status_callback=self.youtube_login_status.emit,
            )
            self.youtube_login_finished.emit(result)

        threading.Thread(target=run, daemon=True).start()

    def _set_youtube_login_status(self, text: str) -> None:
        self._set_youtube_auth_visual(
            "busy",
            "YouTube 인증 진행 중",
            text,
        )

    def _youtube_login_done(self, result) -> None:
        self.youtube_browser_combo.setEnabled(bool(self._youtube_browsers))
        self.youtube_login_button.setEnabled(bool(self._youtube_browsers))
        self._refresh_youtube_auth_status()

        if result.success:
            self._show_warm_message(
                QMessageBox.Icon.Information,
                "YouTube 인증 완료",
                f"{result.browser_label}에서 YouTube 로그인을 확인했습니다.\n\n"
                f"인증 쿠키 {result.cookie_count}개를 RR-V에 저장했습니다.\n"
                "이제 YouTube 영상 정보 확인과 다운로드에 이 인증 정보를 자동으로 사용합니다.",
            )
            return

        self._set_youtube_auth_visual(
            "error",
            "YouTube 인증 실패",
            result.message,
        )
        self._show_warm_message(
            QMessageBox.Icon.Warning,
            "YouTube 인증 실패",
            f"{result.message}\n\n진단 파일: {RRV_YOUTUBE_AUTH_RESULT_PATH}",
        )

    def _set_instagram_auth_visual(self, state: str, title: str, detail: str) -> None:
        if not hasattr(self, "instagram_auth_status_label"):
            return
        self.instagram_auth_status_label.setText(title)
        self.instagram_auth_status_label.setProperty("authState", state)
        style = self.instagram_auth_status_label.style()
        style.unpolish(self.instagram_auth_status_label)
        style.polish(self.instagram_auth_status_label)
        self.instagram_auth_status_label.update()
        if hasattr(self, "instagram_auth_detail_label"):
            self.instagram_auth_detail_label.setText(detail)

    def _refresh_instagram_auth_status(self) -> None:
        if not hasattr(self, "instagram_auth_status_label"):
            return
        status = instagram_auth_status()
        if status.has_login_cookie:
            stamp = (
                status.modified_at.strftime("%Y-%m-%d %H:%M")
                if status.modified_at
                else "시간 확인 불가"
            )
            self._set_instagram_auth_visual(
                "ready",
                "Instagram 인증됨",
                f"로그인 세션 쿠키 {status.cookie_count}개 · {stamp}",
            )
        elif status.exists:
            self._set_instagram_auth_visual(
                "error",
                "Instagram 인증 정보 확인 필요",
                f"쿠키 {status.cookie_count}개가 있지만 로그인 세션을 확인하지 못했습니다. 인증 갱신을 실행해 주세요.",
            )
        else:
            self._set_instagram_auth_visual(
                "missing",
                "Instagram 인증 필요",
                "아직 저장된 Instagram 로그인 정보가 없습니다. 공개 콘텐츠는 인증 없이도 받을 수 있습니다.",
            )

        if hasattr(self, "instagram_login_button"):
            self.instagram_login_button.setText(
                "인증 갱신" if status.has_login_cookie else "Instagram 로그인"
            )
        if hasattr(self, "instagram_delete_button"):
            self.instagram_delete_button.setEnabled(status.exists)

    def _start_instagram_login(self) -> None:
        browser_key = str(self.instagram_browser_combo.currentData() or "").strip()
        if not browser_key:
            self._show_warm_message(
                QMessageBox.Icon.Warning,
                "Instagram 로그인",
                "Chrome, Vivaldi, Edge 또는 Brave를 찾지 못했습니다.",
            )
            return

        self.instagram_login_button.setEnabled(False)
        self.instagram_delete_button.setEnabled(False)
        self.instagram_browser_combo.setEnabled(False)
        self._set_instagram_auth_visual(
            "busy",
            "Instagram 인증 진행 중",
            "인증 창을 준비하는 중…",
        )

        def run() -> None:
            result = perform_instagram_login(
                browser_key,
                status_callback=self.instagram_login_status.emit,
            )
            self.instagram_login_finished.emit(result)

        threading.Thread(target=run, daemon=True).start()

    def _set_instagram_login_status(self, text: str) -> None:
        self._set_instagram_auth_visual(
            "busy",
            "Instagram 인증 진행 중",
            text,
        )

    def _instagram_login_done(self, result) -> None:
        self.instagram_browser_combo.setEnabled(bool(self._instagram_browsers))
        self.instagram_login_button.setEnabled(bool(self._instagram_browsers))
        self._refresh_instagram_auth_status()

        if result.success:
            self._show_warm_message(
                QMessageBox.Icon.Information,
                "Instagram 인증 완료",
                f"{result.browser_label}에서 Instagram 로그인을 확인했습니다.\n\n"
                f"인증 쿠키 {result.cookie_count}개를 RR-V에 저장했습니다.\n"
                "이제 Instagram 영상 정보 확인과 다운로드에 이 인증 정보를 자동으로 사용합니다.",
            )
            return

        self._set_instagram_auth_visual(
            "error",
            "Instagram 인증 실패",
            result.message,
        )
        self._show_warm_message(
            QMessageBox.Icon.Warning,
            "Instagram 인증 실패",
            f"{result.message}\n\n진단 파일: {RRV_INSTAGRAM_AUTH_RESULT_PATH}",
        )

    def _delete_instagram_auth(self) -> None:
        if not ask_warm_question(
            self,
            "Instagram 인증 삭제",
            "저장된 Instagram 로그인 인증 정보를 삭제할까요?\n\n"
            "Instagram 계정 자체에서 로그아웃되거나 계정 정보가 삭제되지는 않습니다.",
            yes_text="인증 삭제",
            no_text="취소",
        ):
            return

        if delete_instagram_auth():
            self._refresh_instagram_auth_status()
            show_warm_message(
                self,
                "Instagram 인증 삭제 완료",
                "RR-V에 저장된 Instagram 인증 정보를 삭제했습니다.",
            )
            return

        show_warm_message(
            self,
            "Instagram 인증 삭제 실패",
            "Instagram 인증 파일을 삭제하지 못했습니다. 파일 사용 여부를 확인한 뒤 다시 시도해 주세요.",
        )

    def _set_tiktok_auth_visual(self, state: str, title: str, detail: str) -> None:
        if not hasattr(self, "tiktok_auth_status_label"):
            return
        self.tiktok_auth_status_label.setText(title)
        self.tiktok_auth_status_label.setProperty("authState", state)
        style = self.tiktok_auth_status_label.style()
        style.unpolish(self.tiktok_auth_status_label)
        style.polish(self.tiktok_auth_status_label)
        self.tiktok_auth_status_label.update()
        if hasattr(self, "tiktok_auth_detail_label"):
            self.tiktok_auth_detail_label.setText(detail)

    def _refresh_tiktok_auth_status(self) -> None:
        if not hasattr(self, "tiktok_auth_status_label"):
            return
        status = tiktok_auth_status()
        if status.has_login_cookie:
            stamp = (
                status.modified_at.strftime("%Y-%m-%d %H:%M")
                if status.modified_at
                else "시간 확인 불가"
            )
            self._set_tiktok_auth_visual(
                "ready",
                "TikTok 인증됨",
                f"로그인 세션 쿠키 {status.cookie_count}개 · {stamp}",
            )
        elif status.exists:
            self._set_tiktok_auth_visual(
                "error",
                "TikTok 인증 정보 확인 필요",
                f"쿠키 {status.cookie_count}개가 있지만 로그인 세션을 확인하지 못했습니다. 인증 갱신을 실행해 주세요.",
            )
        else:
            self._set_tiktok_auth_visual(
                "missing",
                "TikTok 인증 필요",
                "아직 저장된 TikTok 로그인 정보가 없습니다. 공개 콘텐츠는 인증 없이도 받을 수 있습니다.",
            )

        if hasattr(self, "tiktok_login_button"):
            self.tiktok_login_button.setText(
                "인증 갱신" if status.has_login_cookie else "TikTok 로그인"
            )
        if hasattr(self, "tiktok_delete_button"):
            self.tiktok_delete_button.setEnabled(status.exists)

    def _start_tiktok_login(self) -> None:
        browser_key = str(self.tiktok_browser_combo.currentData() or "").strip()
        if not browser_key:
            self._show_warm_message(
                QMessageBox.Icon.Warning,
                "TikTok 로그인",
                "Chrome, Vivaldi, Edge 또는 Brave를 찾지 못했습니다.",
            )
            return

        self.tiktok_login_button.setEnabled(False)
        self.tiktok_delete_button.setEnabled(False)
        self.tiktok_browser_combo.setEnabled(False)
        self._set_tiktok_auth_visual(
            "busy",
            "TikTok 인증 진행 중",
            "인증 창을 준비하는 중…",
        )

        def run() -> None:
            result = perform_tiktok_login(
                browser_key,
                status_callback=self.tiktok_login_status.emit,
            )
            self.tiktok_login_finished.emit(result)

        threading.Thread(target=run, daemon=True).start()

    def _set_tiktok_login_status(self, text: str) -> None:
        self._set_tiktok_auth_visual(
            "busy",
            "TikTok 인증 진행 중",
            text,
        )

    def _tiktok_login_done(self, result) -> None:
        self.tiktok_browser_combo.setEnabled(bool(self._tiktok_browsers))
        self.tiktok_login_button.setEnabled(bool(self._tiktok_browsers))
        self._refresh_tiktok_auth_status()

        if result.success:
            self._show_warm_message(
                QMessageBox.Icon.Information,
                "TikTok 인증 완료",
                f"{result.browser_label}에서 TikTok 로그인을 확인했습니다.\n\n"
                f"인증 쿠키 {result.cookie_count}개를 RR-V에 저장했습니다.\n"
                "이제 TikTok 영상 정보 확인과 다운로드에 이 인증 정보를 자동으로 사용합니다.",
            )
            return

        self._set_tiktok_auth_visual(
            "error",
            "TikTok 인증 실패",
            result.message,
        )
        self._show_warm_message(
            QMessageBox.Icon.Warning,
            "TikTok 인증 실패",
            f"{result.message}\n\n진단 파일: {RRV_TIKTOK_AUTH_RESULT_PATH}",
        )

    def _delete_tiktok_auth(self) -> None:
        if not ask_warm_question(
            self,
            "TikTok 인증 삭제",
            "저장된 TikTok 로그인 인증 정보를 삭제할까요?\n\n"
            "TikTok 계정 자체에서 로그아웃되거나 계정 정보가 삭제되지는 않습니다.",
            yes_text="인증 삭제",
            no_text="취소",
        ):
            return

        if delete_tiktok_auth():
            self._refresh_tiktok_auth_status()
            show_warm_message(
                self,
                "TikTok 인증 삭제 완료",
                "RR-V에 저장된 TikTok 인증 정보를 삭제했습니다.",
            )
            return

        show_warm_message(
            self,
            "TikTok 인증 삭제 실패",
            "TikTok 인증 파일을 삭제하지 못했습니다. 파일 사용 여부를 확인한 뒤 다시 시도해 주세요.",
        )

    def _choose_download_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "기본 다운로드 폴더 선택",
            self.download_folder_input.text().strip(),
        )
        if selected:
            self.download_folder_input.setText(selected)

    def _open_download_folder(self) -> None:
        from pathlib import Path

        folder = Path(self.download_folder_input.text().strip()).expanduser()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.general_save_status.setText("폴더를 열지 못했습니다")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))

    def _open_logs_folder(self) -> None:
        try:
            RRV_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(RRV_LOGS_DIR.resolve()))
        )

    def _choose_cookie_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "쿠키 폴더 선택",
            self.cookie_folder_input.text().strip(),
        )
        if selected:
            self.cookie_folder_input.setText(selected)

    def _open_cookie_folder(self) -> None:
        folder_text = self.cookie_folder_input.text().strip()
        if not folder_text:
            self.general_save_status.setText("쿠키 폴더가 비어 있음")
            return
        folder = Path(folder_text).expanduser()
        if not folder.is_dir():
            self.general_save_status.setText("쿠키 폴더를 찾지 못했습니다")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))

    def _open_tools_folder(self) -> None:
        try:
            RRV_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._set_tool_action_status("도구 폴더를 만들지 못했습니다.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(RRV_TOOLS_DIR.resolve())))

    def _refresh_tool_status(self) -> None:
        for status in inspect_tools():
            status_label = self.tool_status_labels.get(status.key)
            version_label = self.tool_version_labels.get(status.key)
            if status_label is not None:
                status_label.setText("정상" if status.available else "없음")
            if version_label is not None:
                version_label.setText(status.version)
        self.restore_tools_button.setEnabled(has_bundled_tools())
        if not has_bundled_tools():
            self.restore_tools_button.setToolTip(
                "현재 소스 실행에는 내장 도구가 포함되지 않아 비활성화됩니다. 최종 단일 EXE 패키지에서 사용할 수 있습니다."
            )

    def _start_ytdlp_update(self) -> None:
        self.ytdlp_update_button.setEnabled(False)
        self.tool_action_status.emit("yt-dlp Nightly 업데이트 준비 중…")

        def run() -> None:
            ok, message = update_ytdlp(self.tool_action_status.emit)
            self.tool_action_finished.emit(ok, message)

        threading.Thread(target=run, daemon=True).start()

    def _start_deno_update(self) -> None:
        self.deno_update_button.setEnabled(False)
        self.tool_action_status.emit("Deno 업데이트 준비 중…")

        def run() -> None:
            ok, message = update_deno(self.tool_action_status.emit)
            self.tool_action_finished.emit(ok, message)

        threading.Thread(target=run, daemon=True).start()

    def _restore_packaged_tools(self) -> None:
        self.restore_tools_button.setEnabled(False)
        ok, message = restore_packaged_tools()
        self._tool_action_done(ok, message)

    def _set_tool_action_status(self, text: str) -> None:
        self.tool_action_label.setText(text)

    def _tool_action_done(self, ok: bool, message: str) -> None:
        self.ytdlp_update_button.setEnabled(True)
        self.deno_update_button.setEnabled(True)
        self.restore_tools_button.setEnabled(has_bundled_tools())
        self.tool_action_label.setText(("" if ok else "") + message)
        self._refresh_tool_status()

    def _copy_diagnostics(self) -> None:
        lines = [
            f"RR-V {APP_VERSION}",
            f"OS: {platform.platform()}",
            f"Python: {sys.version.split()[0]}",
            f"Settings: {SETTINGS_PATH}",
            f"Tools: {RRV_TOOLS_DIR}",
            f"Logs: {RRV_LOGS_DIR}",
            f"YouTube auth: {youtube_auth_status_text()}",
            f"YouTube auth result: {RRV_YOUTUBE_AUTH_RESULT_PATH}",
            f"Instagram auth: {instagram_auth_status_text()}",
            f"Instagram auth result: {RRV_INSTAGRAM_AUTH_RESULT_PATH}",
            f"TikTok auth: {tiktok_auth_status_text()}",
            f"TikTok auth result: {RRV_TIKTOK_AUTH_RESULT_PATH}",
        ]
        for status in inspect_tools():
            state = "OK" if status.available else "MISSING"
            lines.append(f"{status.label}: {state} | {status.version} | {status.path}")
        QApplication.clipboard().setText("\n".join(lines))
        self.diagnostic_status_label.setText("진단 정보 복사 완료")
        QTimer.singleShot(2200, lambda: self.diagnostic_status_label.setText(""))

    def _open_backup_folder(self) -> None:
        try:
            RRV_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(RRV_BACKUPS_DIR.resolve())))

    def _refresh_backup_status(self) -> None:
        backup = latest_backup()
        if backup is None:
            self.backup_status_label.setText("아직 설정 백업이 없습니다.")
            return
        try:
            stamp = datetime.fromtimestamp(backup.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            stamp = "시간 확인 불가"
        self.backup_status_label.setText(f"마지막 백업: {stamp} · {backup.name}")

    def _manual_backup(self) -> None:
        RRV_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        default_name = f"RR-V_settings_{datetime.now():%Y%m%d_%H%M%S}.json"
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "RR-V 설정 백업 저장",
            str(RRV_BACKUPS_DIR / default_name),
            "JSON 파일 (*.json)",
        )
        if not selected:
            return
        try:
            path = create_backup(Path(selected))
        except (OSError, ValueError) as error:
            show_warm_message(self, "설정 백업 실패", str(error))
            return
        self.backup_status_label.setText(f"백업 완료 · {path.name}")

    def _restore_from_backup(self) -> None:
        RRV_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "RR-V 설정 백업 선택",
            str(RRV_BACKUPS_DIR),
            "JSON 파일 (*.json)",
        )
        if not selected:
            return

        if not ask_warm_question(
            self,
            "설정 복구",
            "현재 설정을 안전 백업한 뒤 선택한 백업으로 복구하시겠습니까?\n복구된 설정은 RR-V를 다시 실행하면 완전히 적용됩니다.",
            yes_text="복구",
            no_text="취소",
        ):
            return

        try:
            create_backup(automatic=True)
            count = restore_backup(Path(selected))
        except (OSError, ValueError, TypeError) as error:
            show_warm_message(self, "설정 복구 실패", str(error))
            return

        self._general_preferences = load_general_preferences()
        self._sync_windows_startup_after_restore()
        self._apply_general_preferences_to_controls()
        self._load_preferences_into_controls()
        self._refresh_backup_status()
        show_warm_message(
            self,
            "설정 복구 완료",
            f"설정 {count}개를 복구했습니다. RR-V를 다시 실행하면 모든 화면에 적용됩니다.",
        )

    def _reset_selected_scope(self) -> None:
        label = self.reset_scope_combo.currentText()
        mapping = {
            "UI 배치와 접힘 상태": "ui",
            "미디어 도구 설정": "media",
            "다운로드 프리셋": "downloads",
            "모든 설정": "all",
        }
        scope = mapping.get(label, "ui")

        if not ask_warm_question(
            self,
            "설정 초기화",
            f"'{label}'을 초기화하시겠습니까?\n초기화 전에 현재 설정을 자동 백업합니다.",
            yes_text="초기화",
            no_text="취소",
        ):
            return

        try:
            create_backup(automatic=True)
            removed = reset_scope(scope)
        except (OSError, ValueError) as error:
            show_warm_message(self, "초기화 실패", str(error))
            return

        self.reset_status_label.setText(
            f"설정 {removed}개를 초기화했습니다. RR-V를 다시 실행하면 완전히 적용됩니다."
        )
        self._general_preferences = load_general_preferences()
        self._sync_windows_startup_after_restore()
        self._apply_general_preferences_to_controls()
        self._load_preferences_into_controls()
        self._refresh_backup_status()

    def _sync_windows_startup_after_restore(self) -> None:
        preferences = self._general_preferences
        try:
            set_windows_startup_enabled(
                preferences.start_with_windows,
                start_hidden=(
                    preferences.start_with_windows
                    and preferences.minimize_to_tray_on_close
                ),
            )
        except WindowsStartupError as error:
            show_warm_message(
                self,
                "Windows 자동 실행 설정 확인",
                "복구된 설정과 Windows 시작 프로그램 등록을 맞추지 못했습니다.\n"
                f"{error}",
            )

    def _apply_general_preferences_to_controls(self) -> None:
        preferences = self._general_preferences
        self.download_folder_input.setText(preferences.default_download_folder)
        self.cookie_folder_input.setText(preferences.cookie_folder)
        self.restore_queue_checkbox.setChecked(preferences.restore_queue_on_start)
        self.keep_completed_checkbox.setChecked(preferences.keep_completed_tasks)
        self.confirm_close_checkbox.setChecked(preferences.confirm_close_during_download)
        self.notify_queue_checkbox.setChecked(preferences.notify_queue_complete)
        self.notify_completion_sound_checkbox.setChecked(preferences.notify_completion_sound)
        self.minimize_to_tray_checkbox.setChecked(preferences.minimize_to_tray_on_close)
        self.start_with_windows_checkbox.setChecked(preferences.start_with_windows)
        self.keep_completed_checkbox.setEnabled(preferences.restore_queue_on_start)
        if preferences.file_collision_mode == FILE_COLLISION_OVERWRITE:
            self.overwrite_file_radio.setChecked(True)
        else:
            self.numbered_file_radio.setChecked(True)

    def _save_general_preferences(self) -> None:
        folder = self.download_folder_input.text().strip()
        if not folder:
            folder = str(Path.home() / "Downloads")
            self.download_folder_input.setText(folder)

        preferences = replace(
            self._general_preferences,
            default_download_folder=folder,
            restore_queue_on_start=self.restore_queue_checkbox.isChecked(),
            keep_completed_tasks=self.keep_completed_checkbox.isChecked(),
            confirm_close_during_download=self.confirm_close_checkbox.isChecked(),
            notify_queue_complete=self.notify_queue_checkbox.isChecked(),
            notify_completion_sound=self.notify_completion_sound_checkbox.isChecked(),
            file_collision_mode=(
                FILE_COLLISION_OVERWRITE
                if self.overwrite_file_radio.isChecked()
                else FILE_COLLISION_NUMBERED
            ),
        )
        save_general_preferences(preferences)
        self._general_preferences = preferences
        self.general_save_status.setText("저장됨")
        self.general_preferences_saved.emit()
        QTimer.singleShot(1800, lambda: self.general_save_status.setText(""))

    def _save_youtube_preferences(self) -> None:
        preferences = replace(
            self._general_preferences,
            cookie_folder=self.cookie_folder_input.text().strip(),
        )
        save_general_preferences(preferences)
        self._general_preferences = preferences
        self.youtube_cookie_save_status.setText("저장됨")
        self.general_preferences_saved.emit()
        QTimer.singleShot(
            1800,
            lambda: self.youtube_cookie_save_status.setText(""),
        )

    def _save_system_preferences(self) -> None:
        requested_start_with_windows = self.start_with_windows_checkbox.isChecked()
        requested_minimize_to_tray = self.minimize_to_tray_checkbox.isChecked()
        actual_start_with_windows = requested_start_with_windows

        try:
            set_windows_startup_enabled(
                requested_start_with_windows,
                start_hidden=(
                    requested_start_with_windows
                    and requested_minimize_to_tray
                ),
            )
        except WindowsStartupError as error:
            actual_start_with_windows = self._general_preferences.start_with_windows
            self.start_with_windows_checkbox.setChecked(actual_start_with_windows)
            show_warm_message(
                self,
                "Windows 자동 실행 설정 실패",
                "Windows 시작 프로그램 등록을 변경하지 못했습니다.\n"
                f"{error}",
            )

        preferences = replace(
            self._general_preferences,
            minimize_to_tray_on_close=requested_minimize_to_tray,
            start_with_windows=actual_start_with_windows,
        )
        save_general_preferences(preferences)
        self._general_preferences = preferences
        self.system_save_status.setText("저장됨")
        self.general_preferences_saved.emit()
        QTimer.singleShot(1800, lambda: self.system_save_status.setText(""))

    def _create_download_preferences_card(self) -> QFrame:
        card, card_layout = create_card()

        header = QHBoxLayout()
        heading = QLabel("다운로드 프리셋")
        heading.setObjectName("sectionTitle")

        self.save_status_label = QLabel("")
        self.save_status_label.setObjectName("settingsSavedStatus")

        header.addWidget(heading)
        header.addStretch()

        description = QLabel(
            "다운로드 유형에 맞는 옵션 묶음을 직접 만들고 관리합니다. "
            "별표가 붙은 기본 프리셋은 빠른 추가와 일괄 추가에 자동으로 사용됩니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        self.preset_combo = NoWheelComboBox()
        self.preset_combo.setObjectName("previewCombo")
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)

        add_preset_button = QToolButton()
        add_preset_button.setObjectName("quickAddButton")
        add_preset_button.setText("+")
        add_preset_button.setToolTip("새 프리셋 만들기")
        add_preset_button.setFixedSize(46, 46)
        add_preset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        add_preset_button.clicked.connect(self._create_preset)

        self.default_preset_label = QLabel("")
        self.default_preset_label.setObjectName("settingsSavedStatus")

        preset_select_row = QHBoxLayout()
        preset_select_row.setSpacing(10)
        preset_select_label = QLabel("프리셋")
        preset_select_label.setObjectName("previewOptionName")
        preset_select_row.addWidget(preset_select_label)
        preset_select_row.addWidget(self.preset_combo, 1)
        preset_select_row.addWidget(add_preset_button)
        preset_select_row.addWidget(self.default_preset_label)

        duplicate_button = QPushButton("복제")
        duplicate_button.setObjectName("secondaryButton")
        duplicate_button.clicked.connect(self._duplicate_preset)

        rename_button = QPushButton("이름 변경")
        rename_button.setObjectName("secondaryButton")
        rename_button.clicked.connect(self._rename_preset)

        delete_button = QPushButton("삭제")
        delete_button.setObjectName("secondaryButton")
        delete_button.clicked.connect(self._delete_preset)

        self.set_default_preset_button = QPushButton("기본 프리셋으로 지정")
        self.set_default_preset_button.setObjectName("secondaryButton")
        self.set_default_preset_button.clicked.connect(self._set_default_preset)

        preset_action_row = QHBoxLayout()
        preset_action_row.setSpacing(8)
        preset_action_row.addWidget(duplicate_button)
        preset_action_row.addWidget(rename_button)
        preset_action_row.addWidget(delete_button)
        preset_action_row.addStretch()
        preset_action_row.addWidget(self.set_default_preset_button)

        self.resolution_combo = self._combo(RESOLUTION_CHOICES)
        self.container_combo = self._combo(CONTAINER_CHOICES)
        self.codec_combo = self._combo(CODEC_CHOICES)
        self.audio_format_combo = self._combo(AUDIO_FORMAT_CHOICES)
        self.audio_quality_combo = self._combo(AUDIO_QUALITY_CHOICES)

        self.receive_subtitles_checkbox = QCheckBox("자막 받기")
        self.korean_checkbox = QCheckBox("한국어")
        self.english_checkbox = QCheckBox("영어")
        self.japanese_checkbox = QCheckBox("일본어")
        self.allow_auto_checkbox = QCheckBox("자동 생성 자막 허용")
        self.embed_subtitles_checkbox = QCheckBox("자막을 영상에 내장")
        self.embed_thumbnail_checkbox = QCheckBox("영상 안에 썸네일 내장")
        self.save_thumbnail_checkbox = QCheckBox("썸네일 JPG 별도 저장")
        self.metadata_checkbox = QCheckBox("메타데이터 보존")
        self.audio_only_checkbox = QCheckBox("오디오만 다운로드")

        for checkbox in (
            self.receive_subtitles_checkbox,
            self.korean_checkbox,
            self.english_checkbox,
            self.japanese_checkbox,
            self.allow_auto_checkbox,
            self.embed_subtitles_checkbox,
            self.embed_thumbnail_checkbox,
            self.save_thumbnail_checkbox,
            self.metadata_checkbox,
            self.audio_only_checkbox,
        ):
            checkbox.setObjectName("previewCheckBox")

        self.receive_subtitles_checkbox.toggled.connect(
            self._update_subtitle_controls
        )
        self.audio_only_checkbox.toggled.connect(self._update_audio_controls)

        form_frame = QFrame()
        form_frame.setObjectName("settingsFormFrame")
        form = QVBoxLayout(form_frame)
        form.setContentsMargins(14, 14, 14, 14)
        form.setSpacing(12)

        preset_group = QFrame()
        preset_group.setObjectName("settingsOptionGroup")
        preset_layout = QVBoxLayout(preset_group)
        preset_layout.setContentsMargins(14, 12, 14, 14)
        preset_layout.setSpacing(10)
        preset_title = QLabel("프리셋 관리")
        preset_title.setObjectName("settingsGroupTitle")
        preset_layout.addWidget(preset_title)
        preset_layout.addLayout(preset_select_row)
        preset_layout.addLayout(preset_action_row)

        video_group = QFrame()
        video_group.setObjectName("settingsOptionGroup")
        video_layout = QVBoxLayout(video_group)
        video_layout.setContentsMargins(14, 12, 14, 14)
        video_layout.setSpacing(10)
        video_title = QLabel("영상")
        video_title.setObjectName("settingsGroupTitle")
        video_grid = QGridLayout()
        video_grid.setHorizontalSpacing(14)
        video_grid.setVerticalSpacing(10)
        self._add_form_field(video_grid, 0, 0, "선호 해상도", self.resolution_combo)
        self._add_form_field(video_grid, 0, 2, "파일 형식", self.container_combo)
        self._add_form_field(video_grid, 1, 0, "코덱 우선", self.codec_combo)
        video_grid.setColumnStretch(1, 1)
        video_grid.setColumnStretch(3, 1)
        video_layout.addWidget(video_title)
        video_layout.addLayout(video_grid)
        self._video_setting_widgets = (
            self.resolution_combo,
            self.container_combo,
            self.codec_combo,
        )

        self.subtitle_group = QFrame()
        self.subtitle_group.setObjectName("settingsOptionGroup")
        subtitle_layout = QVBoxLayout(self.subtitle_group)
        subtitle_layout.setContentsMargins(14, 12, 14, 14)
        subtitle_layout.setSpacing(10)
        subtitle_title = QLabel("자막")
        subtitle_title.setObjectName("settingsGroupTitle")

        subtitle_master_row = QHBoxLayout()
        subtitle_master_row.addWidget(self.receive_subtitles_checkbox)
        subtitle_master_row.addStretch()

        language_row = QHBoxLayout()
        language_row.setSpacing(18)
        language_label = QLabel("받을 언어")
        language_label.setObjectName("settingsInlineLabel")
        language_row.addWidget(language_label)
        language_row.addWidget(self.korean_checkbox)
        language_row.addWidget(self.english_checkbox)
        language_row.addWidget(self.japanese_checkbox)
        language_row.addStretch()

        subtitle_option_row = QHBoxLayout()
        subtitle_option_row.setSpacing(18)
        subtitle_option_label = QLabel("처리 방식")
        subtitle_option_label.setObjectName("settingsInlineLabel")
        subtitle_option_row.addWidget(subtitle_option_label)
        subtitle_option_row.addWidget(self.allow_auto_checkbox)
        subtitle_option_row.addWidget(self.embed_subtitles_checkbox)
        subtitle_option_row.addStretch()

        subtitle_layout.addWidget(subtitle_title)
        subtitle_layout.addLayout(subtitle_master_row)
        subtitle_layout.addLayout(language_row)
        subtitle_layout.addLayout(subtitle_option_row)

        info_group = QFrame()
        info_group.setObjectName("settingsOptionGroup")
        info_layout = QVBoxLayout(info_group)
        info_layout.setContentsMargins(14, 12, 14, 14)
        info_layout.setSpacing(10)
        info_title = QLabel("썸네일과 정보")
        info_title.setObjectName("settingsGroupTitle")
        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(28)
        info_grid.setVerticalSpacing(10)
        info_grid.addWidget(self.embed_thumbnail_checkbox, 0, 0)
        info_grid.addWidget(self.save_thumbnail_checkbox, 0, 1)
        info_grid.addWidget(self.metadata_checkbox, 1, 0)
        info_grid.setColumnStretch(0, 1)
        info_grid.setColumnStretch(1, 1)
        info_layout.addWidget(info_title)
        info_layout.addLayout(info_grid)

        audio_group = QFrame()
        audio_group.setObjectName("settingsOptionGroup")
        audio_layout = QVBoxLayout(audio_group)
        audio_layout.setContentsMargins(14, 12, 14, 14)
        audio_layout.setSpacing(10)
        audio_title = QLabel("오디오 전용")
        audio_title.setObjectName("settingsGroupTitle")
        audio_grid = QGridLayout()
        audio_grid.setHorizontalSpacing(14)
        audio_grid.setVerticalSpacing(10)
        audio_grid.addWidget(self.audio_only_checkbox, 0, 0, 1, 4)
        self._add_form_field(audio_grid, 1, 0, "오디오 형식", self.audio_format_combo)
        self._add_form_field(audio_grid, 1, 2, "오디오 음질", self.audio_quality_combo)
        audio_grid.setColumnStretch(1, 1)
        audio_grid.setColumnStretch(3, 1)
        audio_layout.addWidget(audio_title)
        audio_layout.addLayout(audio_grid)

        form.addWidget(preset_group)
        form.addWidget(video_group)
        form.addWidget(self.subtitle_group)
        form.addWidget(info_group)
        form.addWidget(audio_group)

        button_row = QHBoxLayout()
        button_row.addStretch()

        reset_button = QPushButton("기본값 불러오기")
        reset_button.setObjectName("secondaryButton")
        reset_button.clicked.connect(self._restore_defaults)

        save_button = QPushButton("프리셋 저장")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._save_preferences)

        button_row.addWidget(self.save_status_label)
        button_row.addWidget(reset_button)
        button_row.addWidget(save_button)

        card_layout.addLayout(header)
        card_layout.addWidget(description)
        card_layout.addWidget(form_frame)
        card_layout.addLayout(button_row)
        return card

    @staticmethod
    def _combo(items: tuple[str, ...]) -> QComboBox:
        combo = NoWheelComboBox()
        combo.setObjectName("previewCombo")
        combo.addItems(list(items))
        return combo

    @staticmethod
    def _add_form_field(
        layout: QGridLayout,
        row: int,
        column: int,
        name: str,
        widget: QWidget,
    ) -> None:
        label = QLabel(name)
        label.setObjectName("previewOptionName")
        layout.addWidget(label, row, column)
        layout.addWidget(widget, row, column + 1)

    @staticmethod
    def _create_placeholder_card(
        section_title: str,
        section_description: str,
        status_text: str,
    ) -> QFrame:
        card, card_layout = create_card()

        heading_row = QHBoxLayout()
        heading_row.setSpacing(12)

        heading = QLabel(section_title)
        heading.setObjectName("sectionTitle")

        status = QLabel(status_text)
        status.setObjectName("mutedText")

        heading_row.addWidget(heading)
        heading_row.addStretch()
        heading_row.addWidget(status)

        description = QLabel(section_description)
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        button = QPushButton("열기")
        button.setObjectName("secondaryButton")
        button.setEnabled(False)
        button.setMaximumWidth(120)

        card_layout.addLayout(heading_row)
        card_layout.addWidget(description)
        card_layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignRight)
        return card

    def _load_preferences_into_controls(self) -> None:
        selected_id = ""
        if hasattr(self, "preset_combo") and self.preset_combo.count():
            selected_id = str(self.preset_combo.currentData() or "")

        self._preset_library = load_preset_library()
        if self._preset_library.get(selected_id) is None:
            selected_id = self._preset_library.default_preset_id

        self._refresh_preset_combo(selected_id)
        preset = self._preset_library.get(selected_id) or self._preset_library.default_preset
        self._set_controls(preset.to_preferences())

    def _refresh_preset_combo(self, selected_id: str = "") -> None:
        if not selected_id:
            selected_id = self._preset_library.default_preset_id

        self._applying_preset = True
        try:
            self.preset_combo.clear()
            selected_index = 0
            for index, preset in enumerate(self._preset_library.presets):
                prefix = "★ " if preset.preset_id == self._preset_library.default_preset_id else ""
                self.preset_combo.addItem(f"{prefix}{preset.name}", preset.preset_id)
                if preset.preset_id == selected_id:
                    selected_index = index
            self.preset_combo.setCurrentIndex(selected_index)
        finally:
            self._applying_preset = False
        self._update_default_preset_ui()

    def _current_preset(self) -> DownloadPreset:
        preset_id = str(self.preset_combo.currentData() or "")
        return self._preset_library.get(preset_id) or self._preset_library.default_preset

    def _set_controls(self, preferences: DownloadPreferences) -> None:
        self._applying_preset = True
        try:
            if preferences.preset_id:
                index = self.preset_combo.findData(preferences.preset_id)
                if index >= 0:
                    self.preset_combo.setCurrentIndex(index)
            self.resolution_combo.setCurrentText(preferences.resolution)
            self.container_combo.setCurrentText(preferences.container)
            self.codec_combo.setCurrentText(preferences.codec)
            self.audio_format_combo.setCurrentText(preferences.audio_format)
            self.audio_quality_combo.setCurrentText(preferences.audio_quality)

            self.receive_subtitles_checkbox.setChecked(preferences.receive_subtitles)
            preferred = set(preferences.preferred_subtitles)
            self.korean_checkbox.setChecked("ko" in preferred)
            self.english_checkbox.setChecked("en" in preferred)
            self.japanese_checkbox.setChecked("ja" in preferred)
            self.allow_auto_checkbox.setChecked(preferences.allow_automatic_subtitles)
            self.embed_subtitles_checkbox.setChecked(preferences.embed_subtitles)
            self.embed_thumbnail_checkbox.setChecked(preferences.embed_thumbnail)
            self.save_thumbnail_checkbox.setChecked(preferences.save_thumbnail)
            self.metadata_checkbox.setChecked(preferences.preserve_metadata)
            self.audio_only_checkbox.setChecked(preferences.audio_only)
        finally:
            self._applying_preset = False
        self._update_audio_controls()
        self._update_subtitle_controls()
        self._update_default_preset_ui()

    def _preset_changed(self, _index: int) -> None:
        if self._applying_preset:
            return
        preset = self._current_preset()
        self._set_controls(preset.to_preferences())
        self.save_status_label.setText("")

    def _preferences_from_controls(self) -> DownloadPreferences:
        preferred_subtitles: list[str] = []
        if self.korean_checkbox.isChecked():
            preferred_subtitles.append("ko")
        if self.english_checkbox.isChecked():
            preferred_subtitles.append("en")
        if self.japanese_checkbox.isChecked():
            preferred_subtitles.append("ja")

        preset = self._current_preset()
        return DownloadPreferences(
            preset_id=preset.preset_id,
            preset=preset.name,
            resolution=self.resolution_combo.currentText() or "최고 화질",
            container=self.container_combo.currentText() or "MP4",
            codec=self.codec_combo.currentText() or "H.264",
            receive_subtitles=self.receive_subtitles_checkbox.isChecked(),
            preferred_subtitles=tuple(preferred_subtitles),
            allow_automatic_subtitles=self.allow_auto_checkbox.isChecked(),
            embed_subtitles=self.embed_subtitles_checkbox.isChecked(),
            embed_thumbnail=self.embed_thumbnail_checkbox.isChecked(),
            save_thumbnail=self.save_thumbnail_checkbox.isChecked(),
            preserve_metadata=self.metadata_checkbox.isChecked(),
            audio_only=self.audio_only_checkbox.isChecked(),
            audio_format=self.audio_format_combo.currentText() or "M4A",
            audio_quality=self.audio_quality_combo.currentText() or "최고",
        )

    def _save_preferences(self) -> None:
        current = self._current_preset()
        replacement = current.with_preferences(self._preferences_from_controls())
        try:
            self._preset_library.replace_preset(current.preset_id, replacement)
            save_preset_library(self._preset_library)
        except (OSError, ValueError, KeyError) as error:
            show_warm_message(self, "프리셋 저장 실패", str(error))
            return
        self._refresh_preset_combo(current.preset_id)
        self.save_status_label.setText("저장됨")
        QTimer.singleShot(1800, lambda: self.save_status_label.setText(""))

    def _create_preset(self) -> None:
        source_text, ok = choose_warm_item(
            self,
            "새 프리셋 만들기",
            "새 프리셋의 시작 값을 선택해 주세요.",
            ["현재 선택값으로 만들기", "기본 다운로드 설정으로 만들기"],
            current_index=0,
        )
        if not ok:
            return

        name = self._prompt_preset_name("새 프리셋 만들기", "새 프리셋")
        if name is None:
            return

        if source_text == "기본 다운로드 설정으로 만들기":
            source = DownloadPreferences()
        else:
            source = self._preferences_from_controls()

        preset = DownloadPreset.from_preferences(name, source)
        try:
            self._preset_library.add_preset(preset)
            save_preset_library(self._preset_library)
        except (OSError, ValueError) as error:
            show_warm_message(self, "프리셋 만들기 실패", str(error))
            return

        self._refresh_preset_combo(preset.preset_id)
        self._set_controls(preset.to_preferences())
        self.save_status_label.setText(f"'{preset.name}' 프리셋을 만들었습니다.")

    def _duplicate_preset(self) -> None:
        current = self._current_preset()
        suggested = self._unique_copy_name(current.name)
        name = self._prompt_preset_name("프리셋 복제", suggested)
        if name is None:
            return

        # 저장 버튼을 누르기 전의 화면 값까지 그대로 복제하는 것이 사용자의
        # 기대에 더 가깝다.
        duplicate = DownloadPreset.from_preferences(name, self._preferences_from_controls())
        try:
            self._preset_library.add_preset(duplicate)
            save_preset_library(self._preset_library)
        except (OSError, ValueError) as error:
            show_warm_message(self, "프리셋 복제 실패", str(error))
            return

        self._refresh_preset_combo(duplicate.preset_id)
        self._set_controls(duplicate.to_preferences())
        self.save_status_label.setText(f"'{duplicate.name}' 프리셋을 만들었습니다.")

    def _rename_preset(self) -> None:
        current = self._current_preset()
        name = self._prompt_preset_name(
            "프리셋 이름 변경",
            current.name,
            exclude_id=current.preset_id,
        )
        if name is None or name == current.name:
            return

        replacement = current.renamed(name)
        try:
            self._preset_library.replace_preset(current.preset_id, replacement)
            save_preset_library(self._preset_library)
        except (OSError, ValueError, KeyError) as error:
            show_warm_message(self, "프리셋 이름 변경 실패", str(error))
            return

        self._refresh_preset_combo(current.preset_id)
        self.save_status_label.setText(f"프리셋 이름을 '{name}'(으)로 변경했습니다.")

    def _delete_preset(self) -> None:
        current = self._current_preset()
        if len(self._preset_library.presets) <= 1:
            show_warm_message(
                self,
                "프리셋 삭제",
                "RR-V에는 최소 한 개의 프리셋이 필요합니다.",
            )
            return
        if current.preset_id == self._preset_library.default_preset_id:
            show_warm_message(
                self,
                "기본 프리셋은 삭제할 수 없습니다",
                "먼저 다른 프리셋을 기본 프리셋으로 지정한 뒤 삭제해 주세요.",
            )
            return

        if not ask_warm_question(
            self,
            "프리셋 삭제",
            f"'{current.name}' 프리셋을 삭제할까요?",
            yes_text="삭제",
            no_text="취소",
        ):
            return

        current_index = self.preset_combo.currentIndex()
        try:
            self._preset_library.remove_preset(current.preset_id)
            save_preset_library(self._preset_library)
        except (OSError, ValueError, KeyError) as error:
            show_warm_message(self, "프리셋 삭제 실패", str(error))
            return

        next_index = min(current_index, len(self._preset_library.presets) - 1)
        next_id = self._preset_library.presets[next_index].preset_id
        self._refresh_preset_combo(next_id)
        self._set_controls(self._preset_library.presets[next_index].to_preferences())
        self.save_status_label.setText(f"'{current.name}' 프리셋을 삭제했습니다.")

    def _set_default_preset(self) -> None:
        current = self._current_preset()
        if current.preset_id == self._preset_library.default_preset_id:
            return
        try:
            self._preset_library.set_default(current.preset_id)
            save_preset_library(self._preset_library)
        except (OSError, KeyError, ValueError) as error:
            show_warm_message(self, "기본 프리셋 변경 실패", str(error))
            return
        self._refresh_preset_combo(current.preset_id)
        self.save_status_label.setText(f"'{current.name}'을 기본 프리셋으로 지정했습니다.")

    def _prompt_preset_name(
        self,
        title: str,
        initial: str,
        *,
        exclude_id: str = "",
    ) -> str | None:
        name, ok = prompt_warm_text(
            self,
            title,
            "프리셋 이름",
            initial,
        )
        if not ok:
            return None
        name = name.strip()
        if not name:
            show_warm_message(self, title, "프리셋 이름을 입력해 주세요.")
            return None
        if len(name) > 60:
            show_warm_message(self, title, "프리셋 이름은 60자 이하로 입력해 주세요.")
            return None
        if self._preset_library.has_name(name, exclude_id=exclude_id):
            show_warm_message(self, title, "같은 이름의 프리셋이 이미 있습니다.")
            return None
        return name

    def _unique_copy_name(self, name: str) -> str:
        base = f"{name} 복사본"
        if not self._preset_library.has_name(base):
            return base
        number = 2
        while self._preset_library.has_name(f"{base} {number}"):
            number += 1
        return f"{base} {number}"

    def _update_default_preset_ui(self) -> None:
        if not hasattr(self, "preset_combo") or not self.preset_combo.count():
            return
        current = self._current_preset()
        is_default = current.preset_id == self._preset_library.default_preset_id
        self.default_preset_label.setText("기본 프리셋" if is_default else "")
        self.set_default_preset_button.setEnabled(not is_default)

    def _restore_defaults(self) -> None:
        current = self._current_preset()
        defaults = DownloadPreferences(
            preset_id=current.preset_id,
            preset=current.name,
        )
        self._set_controls(defaults)
        self.save_status_label.setText("기본값 불러오기 완료 · 저장하면 적용됩니다.")

    def _update_subtitle_controls(self) -> None:
        enabled = self.receive_subtitles_checkbox.isChecked() and not self.audio_only_checkbox.isChecked()
        for widget in (
            self.korean_checkbox,
            self.english_checkbox,
            self.japanese_checkbox,
            self.allow_auto_checkbox,
            self.embed_subtitles_checkbox,
        ):
            widget.setEnabled(enabled)

    def _update_audio_controls(self) -> None:
        audio_only = self.audio_only_checkbox.isChecked()
        self.audio_format_combo.setEnabled(audio_only)
        self.audio_quality_combo.setEnabled(audio_only)
        for widget in self._video_setting_widgets:
            widget.setEnabled(not audio_only)
        self.subtitle_group.setEnabled(not audio_only)
        self._update_subtitle_controls()
