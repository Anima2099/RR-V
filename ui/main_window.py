from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QStackedWidget,
    QSystemTrayIcon,
    QWidget,
)

from app.general_preferences import load_general_preferences
from app.settings_store import get_settings
from services.browser_integration_service import (
    BROWSER_SEND_AUTO_DOWNLOAD,
    load_browser_send_behavior,
)
from app.constants import (
    APP_NAME,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    MINIMUM_HEIGHT,
    MINIMUM_WIDTH,
)
from ui.pages.about_page import AboutPage
from ui.pages.community_settings_page import CommunitySettingsPage
from ui.pages.download_page import DownloadPage
from ui.pages.media_tools_page import MediaToolsPage
from ui.dialogs.warm_dialogs import ask_warm_question
from ui.sidebar import Sidebar


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.settings = get_settings()
        self._force_exit = False

        self.setWindowTitle(APP_NAME)
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self.setMinimumSize(MINIMUM_WIDTH, MINIMUM_HEIGHT)

        self.pages = QStackedWidget()
        self.download_page = DownloadPage()
        self.media_tools_page = MediaToolsPage()
        self.settings_page = CommunitySettingsPage()
        self.about_page = AboutPage()

        # 1.2.0에서 프로그램 정보는 설정 탭이 아니라 사이드바의 독립 페이지로
        # 이동했다. 이전 정보 탭 버튼은 화면에서 숨겨 설정 탭을 6개로 유지한다.
        if hasattr(self.settings_page, "ABOUT_TAB"):
            about_index = int(self.settings_page.ABOUT_TAB)
            if 0 <= about_index < len(self.settings_page.tab_buttons):
                self.settings_page.tab_buttons[about_index].setVisible(False)

        self.settings_page.general_preferences_saved.connect(
            self._apply_tray_preferences
        )
        self.settings_page.open_tools_requested.connect(
            self._open_tools_and_updates
        )
        self.pages.addWidget(self.download_page)
        self.pages.addWidget(self.media_tools_page)
        self.pages.addWidget(self.settings_page)
        self.pages.addWidget(self.about_page)

        self.sidebar = Sidebar()
        self.sidebar.page_requested.connect(self.show_page)

        root = QWidget()
        root.setObjectName("rootWidget")
        self.setCentralWidget(root)

        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self.sidebar)
        root_layout.addWidget(self.pages, 1)

        self._create_tray_icon()
        self._apply_tray_preferences()
        self.restore_window_state()

        # 메인 UI 생성과 복원 작업을 먼저 끝낸 뒤 구성요소 버전을 확인한다.
        # 네트워크가 느리거나 끊겨도 RR-V 시작 자체는 지연되지 않는다.
        # Windows 자동 실행으로 트레이에서 숨겨 시작한 경우에는 확인만 하고
        # 팝업은 띄우지 않아 조용한 시작 동작을 깨지 않는다.
        QTimer.singleShot(
            1400,
            lambda: self.settings_page.start_component_update_check(
                force=False,
                notify=self.isVisible(),
            ),
        )

    def _create_tray_icon(self) -> None:
        self.tray_icon = QSystemTrayIcon(self)
        application = QApplication.instance()
        tray_icon = application.windowIcon() if application is not None else self.windowIcon()
        if tray_icon.isNull():
            tray_icon = self.windowIcon()
        self.tray_icon.setIcon(tray_icon)
        self.tray_icon.setToolTip(APP_NAME)

        self.tray_menu = QMenu(self)
        self.tray_menu.setObjectName("trayMenu")

        self.tray_open_action = QAction("RR-V 열기", self)
        self.tray_download_action = QAction("다운로드 열기", self)
        self.tray_media_tools_action = QAction("미디어 도구 열기", self)
        self.tray_settings_action = QAction("설정 열기", self)
        self.tray_exit_action = QAction("종료", self)

        self.tray_open_action.triggered.connect(self._activate_existing_window)
        self.tray_download_action.triggered.connect(
            lambda checked=False: self._open_page_from_tray(0)
        )
        self.tray_media_tools_action.triggered.connect(
            lambda checked=False: self._open_page_from_tray(1)
        )
        self.tray_settings_action.triggered.connect(
            lambda checked=False: self._open_page_from_tray(2)
        )
        self.tray_exit_action.triggered.connect(self.request_exit)

        self.tray_menu.addAction(self.tray_open_action)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(self.tray_download_action)
        self.tray_menu.addAction(self.tray_media_tools_action)
        self.tray_menu.addAction(self.tray_settings_action)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(self.tray_exit_action)
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self._tray_icon_activated)

    def _tray_icon_activated(
        self,
        reason: QSystemTrayIcon.ActivationReason,
    ) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._activate_existing_window()

    def _open_page_from_tray(self, page_index: int) -> None:
        self.show_page(page_index)
        self._activate_existing_window()

    def _open_tools_and_updates(self) -> None:
        self.show_page(2)
        self.settings_page.show_settings_tab(self.settings_page.TOOLS_TAB)
        self._activate_existing_window()

    def _tray_available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def _apply_tray_preferences(self) -> None:
        preferences = load_general_preferences()
        tray_enabled = (
            preferences.minimize_to_tray_on_close
            and self._tray_available()
        )
        application = QApplication.instance()
        if application is not None:
            application.setQuitOnLastWindowClosed(not tray_enabled)
        if tray_enabled:
            self.tray_icon.show()
        else:
            self.tray_icon.hide()

    def start_hidden_to_tray(self) -> bool:
        preferences = load_general_preferences()
        if not preferences.minimize_to_tray_on_close or not self._tray_available():
            return False
        self.tray_icon.show()
        return True

    def request_exit(self) -> None:
        self._force_exit = True
        self.close()

    def _save_window_state(self) -> None:
        self.settings.setValue(
            "window/geometry",
            self.saveGeometry(),
        )
        self.settings.setValue(
            "window/current_page",
            self.pages.currentIndex(),
        )
        self.settings.sync()

    def show_page(self, index: int) -> None:
        if index < 0 or index >= self.pages.count():
            index = 0

        self.pages.setCurrentIndex(index)
        self.sidebar.set_current_page(index)
        self.settings.setValue("window/current_page", index)

    def handle_external_request(
        self,
        urls: object,
        activate: bool,
        source: str = "external",
        *,
        reveal_download_page: bool = False,
    ) -> None:
        """다른 RR-V 프로세스나 외부 실행에서 전달된 URL을 기존 큐로 넘긴다."""
        if activate:
            self._activate_existing_window()

        if not isinstance(urls, (list, tuple)) or not urls:
            return

        if reveal_download_page:
            self.show_page(0)
        browser_request = str(source).strip().lower() == "browser"
        auto_download = (
            browser_request
            and load_browser_send_behavior() == BROWSER_SEND_AUTO_DOWNLOAD
        )
        self.download_page.enqueue_external_urls(
            [str(url) for url in urls],
            auto_download=auto_download,
        )

    def _activate_existing_window(self) -> None:
        if self.isMinimized():
            self.showNormal()
        elif not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()

    def restore_window_state(self) -> None:
        saved_geometry = self.settings.value("window/geometry")

        if saved_geometry:
            self.restoreGeometry(saved_geometry)
        else:
            self.center_on_screen()

        saved_page = self.settings.value(
            "window/current_page",
            0,
            type=int,
        )
        self.show_page(saved_page)

    def center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()

        if screen is None:
            return

        available_geometry = screen.availableGeometry()
        window_geometry = self.frameGeometry()
        window_geometry.moveCenter(available_geometry.center())
        self.move(window_geometry.topLeft())

    def closeEvent(self, event: QCloseEvent) -> None:
        general_preferences = load_general_preferences()

        if (
            not self._force_exit
            and general_preferences.minimize_to_tray_on_close
            and self._tray_available()
        ):
            self._save_window_state()
            self.tray_icon.show()
            self.hide()
            event.ignore()
            return

        has_active_download = self.download_page.has_active_download
        has_active_conversion = self.media_tools_page.has_active_operation
        if (
            (has_active_download or has_active_conversion)
            and general_preferences.confirm_close_during_download
        ):
            if not self.isVisible():
                self._activate_existing_window()
            if has_active_download and has_active_conversion:
                title = "작업 중 종료"
                message = (
                    "현재 다운로드와 미디어 작업을 중지하고 RR-V를 종료하시겠습니까?\n"
                    "다운로드 작업은 다음 실행에서 복원하고 이어받기를 시도할 수 있습니다."
                )
            elif has_active_conversion:
                title = "미디어 작업 중 종료"
                message = "현재 미디어 작업을 중지하고 RR-V를 종료하시겠습니까?"
            else:
                title = "다운로드 중 종료"
                message = (
                    "현재 다운로드와 대기열을 중지하고 RR-V를 종료하시겠습니까?\n"
                    "다음 실행에서 작업 목록을 복원하고 이어받기를 시도할 수 있습니다."
                )
            if not ask_warm_question(
                self,
                title,
                message,
                yes_text="종료",
                no_text="취소",
            ):
                self._force_exit = False
                event.ignore()
                return

        application = QApplication.instance()
        if application is not None:
            application.setQuitOnLastWindowClosed(True)
        self.download_page.shutdown()
        self.media_tools_page.shutdown()
        self._save_window_state()
        self.tray_icon.hide()
        self._force_exit = False
        super().closeEvent(event)

        # 트레이 모드에서는 QApplication이 한 번 quitOnLastWindowClosed=False로
        # 동작한 뒤라, 창을 닫는 것만으로 이벤트 루프 종료가 보장되지 않는
        # 환경이 있다. 실제 종료 경로에서는 Qt 이벤트 루프를 명시적으로
        # 끝내서 Python 프로세스, 단일 실행 lock, 외부 URL endpoint까지
        # 확실히 정리되게 한다. X→트레이 숨김 경로는 위에서 이미 return한다.
        if application is not None and event.isAccepted():
            QTimer.singleShot(0, application.quit)
