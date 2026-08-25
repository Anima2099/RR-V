from __future__ import annotations

import threading

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSizePolicy,
)

from app.component_updates import (
    ComponentUpdateCheckResult,
    check_component_updates,
    normalize_ffmpeg_release_version,
)
from app.constants import APP_VERSION
from app.paths import RRV_TOOLS_DIR
from app.runtime_tool_installer import ensure_runtime_tools
from app.theme import (
    THEME_DARK,
    THEME_LIGHT,
    active_theme_mode,
    load_theme_preference,
    save_theme_preference,
)
from app.tool_manager import inspect_tools
from app.tool_sources import (
    DENO_RELEASES_PAGE,
    FFMPEG_RELEASES_PAGE,
    WPC_RELEASES_PAGE,
    YTDLP_RELEASES_PAGE,
)
from ui.dialogs.warm_dialogs import ask_warm_question
from ui.pages.settings_page import SettingsPage
from ui.widgets.common import create_card


GITHUB_PROFILE_URL = "https://github.com/Anima2099"
BUY_ME_A_COFFEE_URL = "https://buymeacoffee.com/anima2099"


class ThemeSettingsPage(SettingsPage):
    """1.2.0 화면 테마와 다운로드형 필수 도구 관리 UX를 제공한다."""

    component_check_finished = Signal(object, bool)
    open_tools_requested = Signal()
    ABOUT_TAB = 6

    def __init__(self) -> None:
        super().__init__()
        self._component_check_running = False
        self._last_component_result: ComponentUpdateCheckResult | None = None
        self._tools_tab_checked_once = False
        self._missing_runtime_keys: set[str] = set()
        self.component_check_finished.connect(self._component_check_done)

        self.settings_stack.addWidget(self._create_about_tab())
        tab_bar = self.findChild(QFrame, "toolTabBar")
        if tab_bar is not None and tab_bar.layout() is not None:
            info_button = QPushButton("정보")
            info_button.setObjectName("toolTabButton")
            info_button.setCheckable(True)
            info_button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            info_button.clicked.connect(
                lambda checked=False: self.show_settings_tab(self.ABOUT_TAB)
            )
            self.tab_button_group.addButton(info_button, self.ABOUT_TAB)
            self.tab_buttons.append(info_button)
            tab_bar.layout().addWidget(info_button, 1)

        self._refresh_tool_status()

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
                self._create_tools_and_updates_card(),
                self._create_logs_card(),
                self._create_diagnostics_card(),
            ]
        )

    def _create_about_tab(self):  # type: ignore[no-untyped-def]
        return self._create_scroll_page(
            [
                self._create_about_rrv_card(),
                self._create_about_links_card(),
            ]
        )

    def _create_about_rrv_card(self) -> QFrame:
        card, layout = create_card()

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

        layout.addWidget(title)
        layout.addWidget(product)
        layout.addWidget(version)
        layout.addWidget(description)
        return card

    def _create_about_links_card(self) -> QFrame:
        card, layout = create_card()

        title = QLabel("개발자와 링크")
        title.setObjectName("sectionTitle")

        developer = QLabel("개발자 Anima2099\n이메일 anima2099@proton.me")
        developer.setObjectName("bodyText")
        developer.setWordWrap(True)

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

        hint = QLabel("잘 쓰고 계신다면 커피 한 잔 부탁 드립니다")
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(developer)
        layout.addLayout(button_row)
        layout.addWidget(hint)
        return card

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

    def _create_tools_and_updates_card(self) -> QFrame:
        card, layout = create_card()

        title = QLabel("도구 및 업데이트")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "RR-V가 사용하는 외부 실행 도구를 관리합니다. "
            "도구가 없으면 각 공식 배포처에서 내려받아 설치하고, 이미 있으면 최신 상태로 맞춥니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        path_label = QLabel(str(RRV_TOOLS_DIR))
        path_label.setObjectName("mutedText")
        path_label.setWordWrap(True)

        self.tool_status_labels: dict[str, QLabel] = {}
        self.tool_version_labels: dict[str, QLabel] = {}

        tool_grid = QGridLayout()
        tool_grid.setHorizontalSpacing(16)
        tool_grid.setVerticalSpacing(8)
        tool_grid.addWidget(self._tool_heading("도구"), 0, 0)
        tool_grid.addWidget(self._tool_heading("현재 버전"), 0, 1)
        tool_grid.addWidget(self._tool_heading("상태"), 0, 2)
        tool_grid.setColumnStretch(0, 2)
        tool_grid.setColumnStretch(1, 3)
        tool_grid.setColumnStretch(2, 2)

        rows = (
            ("ytdlp", "yt-dlp Nightly", YTDLP_RELEASES_PAGE),
            ("ffmpeg", "FFmpeg / FFprobe", FFMPEG_RELEASES_PAGE),
            ("deno", "Deno", DENO_RELEASES_PAGE),
            ("pot", "YouTube 인증 런타임", WPC_RELEASES_PAGE),
        )
        for row, (key, label, url) in enumerate(rows, start=1):
            link = QPushButton(label)
            link.setObjectName("toolLinkButton")
            link.setFlat(True)
            font = link.font()
            font.setUnderline(True)
            link.setFont(font)
            link.setToolTip("공식 페이지 열기")
            link.clicked.connect(
                lambda _checked=False, target=url: QDesktopServices.openUrl(QUrl(target))
            )

            version_label = QLabel("확인 중…")
            version_label.setObjectName("mutedText")

            status_label = QLabel("확인 중…")
            status_label.setObjectName("mutedText")

            tool_grid.addWidget(link, row, 0)
            tool_grid.addWidget(version_label, row, 1)
            tool_grid.addWidget(status_label, row, 2)
            self.tool_version_labels[key] = version_label
            self.tool_status_labels[key] = status_label

        self.component_update_status = QLabel("최신 버전 확인 전")
        self.component_update_status.setObjectName("mutedText")
        self.component_update_status.setWordWrap(True)

        self.tool_action_label = QLabel("")
        self.tool_action_label.setObjectName("mutedText")
        self.tool_action_label.setWordWrap(True)

        open_button = QPushButton("도구 폴더 열기")
        open_button.setObjectName("secondaryButton")
        open_button.clicked.connect(self._open_tools_folder)

        self.component_check_button = QPushButton("업데이트 확인")
        self.component_check_button.setObjectName("secondaryButton")
        self.component_check_button.clicked.connect(
            lambda: self.start_component_update_check(force=True, notify=False)
        )

        self.latest_update_button = QPushButton("최신 상태로 맞추기")
        self.latest_update_button.setObjectName("primaryButton")
        self.latest_update_button.clicked.connect(self._start_latest_updates)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(open_button)
        action_row.addStretch()
        action_row.addWidget(self.component_check_button)
        action_row.addWidget(self.latest_update_button)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(path_label)
        layout.addLayout(tool_grid)
        layout.addWidget(self.component_update_status)
        layout.addWidget(self.tool_action_label)
        layout.addLayout(action_row)
        return card

    @staticmethod
    def _tool_heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("settingsGroupTitle")
        return label

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

    def _state_colors(self, state: str) -> tuple[str, str]:
        dark = active_theme_mode() == THEME_DARK
        if state == "update":
            return ("#D0A96D", "font-weight: 700;") if dark else ("#8A6A4D", "font-weight: 700;")
        if state == "error":
            return ("#D8877E", "font-weight: 700;") if dark else ("#A55353", "font-weight: 700;")
        return ("", "")

    def _set_tool_visual(self, key: str, state: str, text: str) -> None:
        status_label = self.tool_status_labels.get(key)
        version_label = self.tool_version_labels.get(key)
        if status_label is None:
            return
        color, extra = self._state_colors(state)
        style = f"color: {color}; {extra}" if color else ""
        status_label.setText(text)
        status_label.setStyleSheet(style)
        if version_label is not None:
            version_label.setStyleSheet(style if state == "update" else "")

    def _refresh_tool_status(self) -> None:
        if not hasattr(self, "tool_status_labels"):
            return
        statuses = {status.key: status for status in inspect_tools()}
        missing: set[str] = set()

        ytdlp = statuses.get("ytdlp")
        if ytdlp is not None:
            self.tool_version_labels["ytdlp"].setText(ytdlp.version)
            self._set_tool_visual(
                "ytdlp",
                "normal" if ytdlp.available else "error",
                "✓ 정상" if ytdlp.available else "✕ 없음",
            )
            if not ytdlp.available:
                missing.add("ytdlp")

        ffmpeg = statuses.get("ffmpeg")
        ffprobe = statuses.get("ffprobe")
        ffmpeg_available = bool(ffmpeg and ffmpeg.available and ffprobe and ffprobe.available)
        if ffmpeg_available and ffmpeg is not None and ffprobe is not None:
            ffmpeg_version = normalize_ffmpeg_release_version(ffmpeg.version)
            ffprobe_version = normalize_ffmpeg_release_version(ffprobe.version)
            if ffmpeg_version == ffprobe_version:
                version_text = ffmpeg_version
            else:
                version_text = f"ffmpeg {ffmpeg_version} / ffprobe {ffprobe_version}"
            self.tool_version_labels["ffmpeg"].setText(version_text)
            self._set_tool_visual("ffmpeg", "normal", "✓ 정상")
        else:
            self.tool_version_labels["ffmpeg"].setText("없음")
            self._set_tool_visual("ffmpeg", "error", "✕ 없음")
            missing.add("ffmpeg")

        deno = statuses.get("deno")
        if deno is not None:
            self.tool_version_labels["deno"].setText(deno.version)
            self._set_tool_visual(
                "deno",
                "normal" if deno.available else "error",
                "✓ 정상" if deno.available else "✕ 없음",
            )
            if not deno.available:
                missing.add("deno")

        pot = statuses.get("pot")
        if pot is not None:
            self.tool_version_labels["pot"].setText(pot.version)
            self._set_tool_visual(
                "pot",
                "normal" if pot.available else "error",
                "✓ 정상" if pot.available else "✕ 없음",
            )

        self._missing_runtime_keys = missing
        if missing:
            self.latest_update_button.setText("필수 구성요소 설치")
            self.latest_update_button.setEnabled(True)
            if not getattr(self, "_component_check_running", False):
                self.component_update_status.setText(
                    f"필수 실행 도구 {len(missing)}개가 필요합니다. 설치 버튼을 눌러 준비해 주세요."
                )
        else:
            self.latest_update_button.setText("최신 상태로 맞추기")
            self.latest_update_button.setEnabled(True)

    def start_component_update_check(
        self,
        *,
        force: bool = False,
        notify: bool = True,
    ) -> None:
        if getattr(self, "_component_check_running", False):
            return
        self._component_check_running = True
        if hasattr(self, "component_check_button"):
            self.component_check_button.setEnabled(False)
            self.component_update_status.setText("최신 버전 확인 중…")

        def run() -> None:
            try:
                result = check_component_updates(force=force)
            except Exception:
                result = ComponentUpdateCheckResult(components=())
            self.component_check_finished.emit(result, notify)

        threading.Thread(target=run, daemon=True).start()

    def _component_check_done(
        self,
        result: ComponentUpdateCheckResult,
        notify: bool,
    ) -> None:
        self._component_check_running = False
        self._last_component_result = result
        if hasattr(self, "component_check_button"):
            self.component_check_button.setEnabled(True)

        if result.skipped:
            if self._missing_runtime_keys:
                self.component_update_status.setText(
                    f"필수 실행 도구 {len(self._missing_runtime_keys)}개가 필요합니다. 설치 버튼을 눌러 준비해 주세요."
                )
            else:
                self.component_update_status.setText(
                    "✓ 오늘 이미 자동 확인했습니다. 도구가 바뀌면 다음 실행에서 다시 확인합니다."
                )
            return

        if not result.components:
            if self._missing_runtime_keys:
                self.component_update_status.setText(
                    "필수 도구가 없고 업데이트 서버도 확인하지 못했습니다. 인터넷 연결을 확인해 주세요."
                )
            else:
                self.component_update_status.setText(
                    "업데이트 서버를 확인하지 못했습니다. 현재 설치된 도구는 그대로 사용할 수 있습니다."
                )
            return

        for component in result.components:
            if component.key not in self.tool_status_labels:
                continue
            if component.update_available is None:
                self._set_tool_visual(component.key, "error", "확인 실패")
            elif component.update_available:
                installing = component.current.strip().lower() in {"없음", "none"}
                self._set_tool_visual(
                    component.key,
                    "update",
                    "● 설치 필요" if installing else "● 업데이트 가능",
                )
            else:
                self._set_tool_visual(component.key, "normal", "✓ 최신")

        updates = result.updates
        failed_count = len(result.errors)
        if self._missing_runtime_keys:
            self.component_update_status.setText(
                f"필수 실행 도구 {len(self._missing_runtime_keys)}개가 필요합니다. 공식 배포처에서 자동으로 설치할 수 있습니다."
            )
        elif updates:
            self.component_update_status.setText(
                f"업데이트 {len(updates)}개가 있습니다. '최신 상태로 맞추기'에서 함께 정리할 수 있습니다."
            )
        elif failed_count:
            self.component_update_status.setText(
                "확인 가능한 도구는 최신입니다. 일부 서버 확인은 실패했습니다."
            )
        else:
            self.component_update_status.setText("✓ 주요 도구가 최신 상태입니다.")

        if not notify or not updates:
            return

        installing = any(
            component.current.strip().lower() in {"없음", "none"}
            for component in updates
        )
        if installing:
            lines = [
                "RR-V 사용에 필요한 실행 도구가 준비되지 않았습니다.",
                "도구 및 리소스에서 필수 구성요소를 설치해 주세요.",
                "",
            ]
            title = "RR-V 필수 구성요소"
        else:
            lines = [
                "필수 도구 업데이트가 있습니다.",
                "안정적인 다운로드를 위해 최신 버전을 권장합니다.",
                "",
            ]
            title = "RR-V 구성요소 업데이트"

        for component in updates:
            lines.append(
                f"• {component.label}\n  {component.current} → {component.latest}"
            )

        open_tools = ask_warm_question(
            self,
            title,
            "\n".join(lines),
            yes_text="도구 및 리소스 열기",
            no_text="나중에",
        )
        if open_tools:
            self.open_tools_requested.emit()

    def _start_latest_updates(self) -> None:
        installing = bool(self._missing_runtime_keys)
        if installing:
            detail = [
                "RR-V에 필요한 외부 실행 도구를 각 공식 배포처에서 내려받습니다.",
                "yt-dlp Nightly, FFmpeg / FFprobe, Deno를 준비하며 다운로드 용량은 버전에 따라 달라질 수 있습니다.",
                "인터넷 연결이 필요합니다.",
            ]
            title = "필수 구성요소 설치"
            yes_text = "설치 시작"
            status_text = "필수 구성요소 설치 준비 중…"
        else:
            detail = [
                "yt-dlp Nightly, FFmpeg / FFprobe, Deno를 공식 배포처 기준 최신 상태로 맞춥니다.",
                "이미 최신인 도구는 다시 다운로드하지 않습니다.",
                "다운로드나 미디어 작업 중이라면 먼저 작업을 끝내는 것을 권장합니다.",
            ]
            title = "도구 최신 상태로 맞추기"
            yes_text = "확인 시작"
            status_text = "도구 상태 확인 준비 중…"

        if not ask_warm_question(
            self,
            title,
            "\n\n".join(detail),
            yes_text=yes_text,
            no_text="취소",
        ):
            return

        self.latest_update_button.setEnabled(False)
        self.component_check_button.setEnabled(False)
        self.tool_action_status.emit(status_text)

        def run() -> None:
            ok, message = ensure_runtime_tools(self.tool_action_status.emit)
            self.tool_action_finished.emit(ok, message)

        threading.Thread(target=run, daemon=True).start()

    def _tool_action_done(self, ok: bool, message: str) -> None:
        if hasattr(self, "component_check_button"):
            self.component_check_button.setEnabled(True)
        if hasattr(self, "tool_action_label"):
            prefix = "✓ 완료\n" if ok else "⚠ 일부 작업 실패\n"
            self.tool_action_label.setText(prefix + message)
        self._refresh_tool_status()
        self.start_component_update_check(force=True, notify=False)

    def show_settings_tab(self, index: int) -> None:
        super().show_settings_tab(index)
        if index == self.GENERAL_TAB:
            self._reload_theme_preferences_to_controls()
        elif index == self.TOOLS_TAB:
            self._refresh_tool_status()
            if not getattr(self, "_tools_tab_checked_once", False):
                self._tools_tab_checked_once = True
                self.start_component_update_check(force=True, notify=False)

    def _restore_from_backup(self) -> None:
        super()._restore_from_backup()
        self._reload_theme_preferences_to_controls()

    def _reset_selected_scope(self) -> None:
        super()._reset_selected_scope()
        self._reload_theme_preferences_to_controls()
