from __future__ import annotations

from pathlib import Path
import sys
import threading

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.app_update import (
    AppUpdateResult,
    RELEASES_PAGE_URL,
    UPDATE_CHANNEL_BETA,
    UPDATE_CHANNEL_STABLE,
    check_app_update,
    normalize_update_channel,
    update_channel_label,
)
from app.app_update_installer import (
    InstallerDownloadResult,
    download_verified_installer,
)
from app.constants import APP_RELEASE_CHANNEL, APP_VERSION
from app.settings_store import get_settings
from ui.dialogs.warm_dialogs import show_warm_message
from ui.widgets.common import create_card


GITHUB_PROFILE_URL = "https://github.com/Anima2099"
BUY_ME_A_COFFEE_URL = "https://buymeacoffee.com/anima2099"
DEVELOPER_EMAIL = "anima2099@proton.me"
_UPDATE_CHANNEL_SETTING_KEY = "updates/channel"


class AboutPage(QWidget):
    update_check_finished = Signal(object)
    auto_update_available = Signal(object)
    install_update_requested = Signal(object)
    installer_download_progress = Signal(int, int)
    installer_download_finished = Signal(object)
    installer_ready = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._settings = get_settings()
        self._update_check_running = False
        self._update_notify_on_result = False
        self._installer_download_running = False
        self._latest_update_result: AppUpdateResult | None = None
        self._release_url = RELEASES_PAGE_URL
        self._update_channel = normalize_update_channel(
            str(
                self._settings.value(
                    _UPDATE_CHANNEL_SETTING_KEY,
                    APP_RELEASE_CHANNEL,
                )
                or APP_RELEASE_CHANNEL
            ),
            APP_RELEASE_CHANNEL,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        title = QLabel("프로그램 정보")
        title.setObjectName("pageTitle")

        subtitle = QLabel("RR-V 버전, 업데이트와 개발자 정보를 확인합니다.")
        subtitle.setObjectName("bodyText")

        layout.addWidget(title)
        layout.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setObjectName("settingsTabScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 4, 20)
        content_layout.setSpacing(14)
        content_layout.addWidget(self._create_product_card())
        content_layout.addWidget(self._create_update_card())
        content_layout.addWidget(self._create_developer_card())
        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        self.update_check_finished.connect(self._update_check_done)
        self.installer_download_progress.connect(self._installer_download_progress)
        self.installer_download_finished.connect(self._installer_download_done)

    @staticmethod
    def _distribution_root() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parents[2]

    def _open_distribution_file(self, filename: str) -> None:
        path = self._distribution_root() / filename
        if path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _create_product_card(self) -> QFrame:
        card, card_layout = create_card()

        title = QLabel("RR-V")
        title.setObjectName("sectionTitle")

        product = QLabel("Video Downloader & Media Tools")
        product.setObjectName("settingsGroupTitle")

        build_label = (
            "Community Beta"
            if normalize_update_channel(APP_RELEASE_CHANNEL) == UPDATE_CHANNEL_BETA
            else "Stable"
        )
        version = QLabel(f"Version {APP_VERSION} · {build_label}")
        version.setObjectName("mutedText")

        description = QLabel(
            "누구나 손쉽게 영상을 다운 받고, 재밌게 수정하는 프로그램을 만들기 위하여"
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        license_hint = QLabel(
            "RR-V 본체와 제3자 구성요소의 라이선스 및 소스 제공 안내"
        )
        license_hint.setObjectName("mutedText")
        license_hint.setWordWrap(True)

        core_license_button = QPushButton("RR-V 라이선스")
        core_license_button.setObjectName("secondaryButton")
        core_license_button.setFixedHeight(30)
        core_license_button.clicked.connect(
            lambda: self._open_distribution_file("LICENSE.ko-KR.txt")
        )

        notices_button = QPushButton("제3자 라이선스")
        notices_button.setObjectName("secondaryButton")
        notices_button.setFixedHeight(30)
        notices_button.clicked.connect(
            lambda: self._open_distribution_file("THIRD_PARTY_NOTICES.txt")
        )

        source_button = QPushButton("소스 제공")
        source_button.setObjectName("secondaryButton")
        source_button.setFixedHeight(30)
        source_button.clicked.connect(
            lambda: self._open_distribution_file("SOURCE_OFFER.txt")
        )

        license_row = QHBoxLayout()
        license_row.setSpacing(6)
        license_row.addWidget(core_license_button)
        license_row.addWidget(notices_button)
        license_row.addWidget(source_button)
        license_row.addStretch()

        card_layout.addWidget(title)
        card_layout.addWidget(product)
        card_layout.addWidget(version)
        card_layout.addWidget(description)
        card_layout.addWidget(license_hint)
        card_layout.addLayout(license_row)
        return card

    def _create_update_card(self) -> QFrame:
        card, card_layout = create_card()

        title = QLabel("RR-V 업데이트")
        title.setObjectName("sectionTitle")

        description = QLabel(
            "선택한 업데이트 채널을 기준으로 GitHub Releases에서 RR-V의 새 버전을 확인합니다. "
            "새 버전이 있으면 검증된 설치 파일을 내려받아 바로 업데이트할 수 있습니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        channel_title = QLabel("업데이트 채널")
        channel_title.setObjectName("settingsGroupTitle")

        self.update_channel_group = QButtonGroup(self)
        self.update_channel_group.setExclusive(True)

        self.stable_channel_radio = QRadioButton("정식")
        self.stable_channel_radio.setObjectName("settingsRadioButton")
        self.beta_channel_radio = QRadioButton("베타")
        self.beta_channel_radio.setObjectName("settingsRadioButton")
        self.update_channel_group.addButton(self.stable_channel_radio)
        self.update_channel_group.addButton(self.beta_channel_radio)

        self.stable_channel_radio.setChecked(
            self._update_channel == UPDATE_CHANNEL_STABLE
        )
        self.beta_channel_radio.setChecked(
            self._update_channel == UPDATE_CHANNEL_BETA
        )
        self.stable_channel_radio.clicked.connect(self._update_channel_changed)
        self.beta_channel_radio.clicked.connect(self._update_channel_changed)

        channel_row = QHBoxLayout()
        channel_row.setSpacing(18)
        channel_row.addWidget(channel_title)
        channel_row.addWidget(self.stable_channel_radio)
        channel_row.addWidget(self.beta_channel_radio)
        channel_row.addStretch()

        channel_hint = QLabel(
            "정식은 정식 배포만 확인하고, 베타는 정식과 베타 배포를 모두 확인합니다."
        )
        channel_hint.setObjectName("mutedText")
        channel_hint.setWordWrap(True)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)

        current_title = QLabel("현재 버전")
        current_title.setObjectName("settingsGroupTitle")
        current_value = QLabel(
            f"{APP_VERSION} · {update_channel_label(APP_RELEASE_CHANNEL)}"
        )
        current_value.setObjectName("mutedText")

        latest_title = QLabel("최신 버전")
        latest_title.setObjectName("settingsGroupTitle")
        self.latest_version_label = QLabel("확인 전")
        self.latest_version_label.setObjectName("mutedText")

        grid.addWidget(current_title, 0, 0)
        grid.addWidget(current_value, 0, 1)
        grid.addWidget(latest_title, 1, 0)
        grid.addWidget(self.latest_version_label, 1, 1)
        grid.setColumnStretch(1, 1)

        self.update_status_label = QLabel("아직 업데이트를 확인하지 않았습니다.")
        self.update_status_label.setObjectName("mutedText")
        self.update_status_label.setWordWrap(True)

        self.check_update_button = QPushButton("업데이트 확인")
        self.check_update_button.setObjectName("primaryButton")
        self.check_update_button.clicked.connect(self._start_update_check)

        self.release_button = QPushButton("업데이트 설치")
        self.release_button.setObjectName("secondaryButton")
        self.release_button.setEnabled(False)
        self.release_button.clicked.connect(self._update_action_clicked)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch()
        button_row.addWidget(self.release_button)
        button_row.addWidget(self.check_update_button)

        card_layout.addWidget(title)
        card_layout.addWidget(description)
        card_layout.addLayout(channel_row)
        card_layout.addWidget(channel_hint)
        card_layout.addLayout(grid)
        card_layout.addWidget(self.update_status_label)
        card_layout.addLayout(button_row)
        return card

    def _create_developer_card(self) -> QFrame:
        card, card_layout = create_card()

        title = QLabel("개발자와 링크")
        title.setObjectName("sectionTitle")

        developer = QLabel("개발자 Anima2099")
        developer.setObjectName("bodyText")

        email = QLabel(f"이메일 {DEVELOPER_EMAIL}")
        email.setObjectName("mutedText")
        email.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        github_button = QPushButton("깃허브 프로필")
        github_button.setObjectName("primaryButton")
        github_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(GITHUB_PROFILE_URL))
        )

        support_button = QPushButton("후원하기")
        support_button.setObjectName("secondaryButton")
        support_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(BUY_ME_A_COFFEE_URL))
        )

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addWidget(github_button)
        button_row.addWidget(support_button)
        button_row.addStretch()

        support_hint = QLabel("잘 쓰고 계신다면 커피 한 잔 부탁 드립니다!")
        support_hint.setObjectName("mutedText")
        support_hint.setWordWrap(True)

        card_layout.addWidget(title)
        card_layout.addWidget(developer)
        card_layout.addWidget(email)
        card_layout.addLayout(button_row)
        card_layout.addWidget(support_hint)
        return card

    def _update_channel_changed(self) -> None:
        if self._update_check_running or self._installer_download_running:
            return
        selected = (
            UPDATE_CHANNEL_BETA
            if self.beta_channel_radio.isChecked()
            else UPDATE_CHANNEL_STABLE
        )
        if selected == self._update_channel:
            return

        self._update_channel = selected
        self._settings.setValue(_UPDATE_CHANNEL_SETTING_KEY, selected)
        self._settings.sync()
        self._release_url = RELEASES_PAGE_URL
        self._latest_update_result = None
        self.latest_version_label.setText("확인 전")
        self.release_button.setText("업데이트 설치")
        self.release_button.setEnabled(False)
        self.update_status_label.setText(
            f"{update_channel_label(selected)} 채널로 변경했습니다. 업데이트 확인을 눌러 주세요."
        )

    def _set_channel_controls_enabled(self, enabled: bool) -> None:
        self.stable_channel_radio.setEnabled(enabled)
        self.beta_channel_radio.setEnabled(enabled)

    def _start_update_check(self) -> None:
        self._begin_update_check(notify=False)

    def start_auto_update_check(self, *, notify: bool = True) -> None:
        if self._update_check_running or self._installer_download_running:
            return
        self._begin_update_check(notify=notify)

    def _begin_update_check(self, *, notify: bool) -> None:
        if self._update_check_running:
            return
        self._update_check_running = True
        self._update_notify_on_result = bool(notify)
        self.check_update_button.setEnabled(False)
        self.release_button.setEnabled(False)
        self._set_channel_controls_enabled(False)
        self.latest_version_label.setText("확인 중…")
        selected_channel = self._update_channel
        channel_label = update_channel_label(selected_channel)
        self.update_status_label.setText(
            f"GitHub Releases에서 {channel_label} 채널의 최신 버전을 확인하는 중…"
        )

        def run() -> None:
            result = check_app_update(update_channel=selected_channel)
            self.update_check_finished.emit(result)

        threading.Thread(target=run, daemon=True).start()

    def _update_check_done(self, result: AppUpdateResult) -> None:
        notify = self._update_notify_on_result
        self._update_notify_on_result = False
        self._update_check_running = False
        self._latest_update_result = result
        self.check_update_button.setEnabled(True)
        self._set_channel_controls_enabled(True)

        latest_text = result.latest_version
        if result.latest_release_channel:
            latest_text = (
                f"{latest_text} · {update_channel_label(result.latest_release_channel)}"
            )
        self.latest_version_label.setText(latest_text)
        self.update_status_label.setText(result.message)
        self._release_url = result.release_url or RELEASES_PAGE_URL

        if result.update_available and result.installer is not None:
            self.release_button.setText("업데이트 설치")
            self.release_button.setEnabled(True)
        elif result.update_available:
            self.release_button.setText("릴리스 페이지 열기")
            self.release_button.setEnabled(True)
            self.update_status_label.setText(
                result.message
                + " 자동 설치용 Installer의 SHA-256 검증 정보를 확인하지 못해 릴리스 페이지에서 직접 받아야 합니다."
            )
        else:
            self.release_button.setText("업데이트 설치")
            self.release_button.setEnabled(False)

        if notify and result.update_available:
            self.auto_update_available.emit(result)

    def _update_action_clicked(self) -> None:
        result = self._latest_update_result
        if result is None or not result.update_available:
            return
        if result.installer is None:
            self.open_current_release_page()
            return
        self.install_update_requested.emit(result)

    def begin_installer_download(self, result: AppUpdateResult) -> None:
        if self._installer_download_running:
            return
        if not result.update_available or result.installer is None:
            self.open_current_release_page()
            return

        self._installer_download_running = True
        self.check_update_button.setEnabled(False)
        self.release_button.setEnabled(False)
        self._set_channel_controls_enabled(False)
        self.update_status_label.setText(
            f"RR-V {result.latest_version} Installer를 다운로드하는 중…"
        )
        asset = result.installer

        def run() -> None:
            download_result = download_verified_installer(
                asset,
                progress=lambda downloaded, total: self.installer_download_progress.emit(
                    downloaded,
                    total,
                ),
            )
            self.installer_download_finished.emit(download_result)

        threading.Thread(target=run, daemon=True).start()

    def _installer_download_progress(self, downloaded: int, total: int) -> None:
        if not self._installer_download_running:
            return
        downloaded_mb = max(0, downloaded) / (1024 * 1024)
        if total > 0:
            percent = max(0, min(100, int(downloaded * 100 / total)))
            total_mb = total / (1024 * 1024)
            self.update_status_label.setText(
                f"Installer 다운로드 중… {percent}% · {downloaded_mb:.1f} / {total_mb:.1f} MB"
            )
        else:
            self.update_status_label.setText(
                f"Installer 다운로드 중… {downloaded_mb:.1f} MB"
            )

    def _installer_download_done(self, result: InstallerDownloadResult) -> None:
        self._installer_download_running = False
        if not result.ok or result.path is None:
            self.check_update_button.setEnabled(True)
            self._set_channel_controls_enabled(True)
            self.release_button.setEnabled(
                bool(self._latest_update_result and self._latest_update_result.update_available)
            )
            self.update_status_label.setText("⚠ 업데이트 Installer를 준비하지 못했습니다.")
            show_warm_message(
                self.window(),
                "업데이트 다운로드 실패",
                result.message,
            )
            return

        self.update_status_label.setText(
            "✓ Installer 다운로드와 SHA-256 검증이 완료되었습니다. 설치 프로그램을 실행합니다."
        )
        self.installer_ready.emit(str(result.path))

    def installer_launch_failed(self, message: str) -> None:
        self._installer_download_running = False
        self.check_update_button.setEnabled(True)
        self._set_channel_controls_enabled(True)
        self.release_button.setEnabled(
            bool(self._latest_update_result and self._latest_update_result.update_available)
        )
        self.update_status_label.setText("⚠ Installer를 실행하지 못했습니다.")
        show_warm_message(
            self.window(),
            "업데이트 실행 실패",
            message,
        )

    def open_current_release_page(self) -> None:
        QDesktopServices.openUrl(QUrl(self._release_url or RELEASES_PAGE_URL))
