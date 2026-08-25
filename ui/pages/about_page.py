from __future__ import annotations

from pathlib import Path
import sys
import threading

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.app_update import AppUpdateResult, RELEASES_PAGE_URL, check_app_update
from app.constants import APP_VERSION
from ui.widgets.common import create_card


GITHUB_PROFILE_URL = "https://github.com/Anima2099"
BUY_ME_A_COFFEE_URL = "https://buymeacoffee.com/anima2099"
DEVELOPER_EMAIL = "anima2099@proton.me"


class AboutPage(QWidget):
    update_check_finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._update_check_running = False
        self._release_url = RELEASES_PAGE_URL

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

        version = QLabel(f"Version {APP_VERSION} · Community Beta")
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
            lambda: self._open_distribution_file("LICENSE.txt" if getattr(sys, "frozen", False) else "LICENSE")
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
            "GitHub Releases에서 RR-V의 새 버전을 확인합니다. 업데이트가 있으면 릴리스 페이지에서 새 설치 파일을 받을 수 있습니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)

        current_title = QLabel("현재 버전")
        current_title.setObjectName("settingsGroupTitle")
        current_value = QLabel(APP_VERSION)
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

        self.release_button = QPushButton("새 버전 받기")
        self.release_button.setObjectName("secondaryButton")
        self.release_button.setEnabled(False)
        self.release_button.clicked.connect(self._open_release_page)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch()
        button_row.addWidget(self.release_button)
        button_row.addWidget(self.check_update_button)

        card_layout.addWidget(title)
        card_layout.addWidget(description)
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

    def _start_update_check(self) -> None:
        if self._update_check_running:
            return
        self._update_check_running = True
        self.check_update_button.setEnabled(False)
        self.release_button.setEnabled(False)
        self.latest_version_label.setText("확인 중…")
        self.update_status_label.setText("GitHub Releases에서 최신 버전을 확인하는 중…")

        def run() -> None:
            result = check_app_update()
            self.update_check_finished.emit(result)

        threading.Thread(target=run, daemon=True).start()

    def _update_check_done(self, result: AppUpdateResult) -> None:
        self._update_check_running = False
        self.check_update_button.setEnabled(True)
        self.latest_version_label.setText(result.latest_version)
        self.update_status_label.setText(result.message)
        self._release_url = result.release_url or RELEASES_PAGE_URL
        self.release_button.setEnabled(bool(result.update_available))

    def _open_release_page(self) -> None:
        QDesktopServices.openUrl(QUrl(self._release_url or RELEASES_PAGE_URL))
