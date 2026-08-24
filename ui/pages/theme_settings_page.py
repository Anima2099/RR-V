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
)

from app.component_updates import (
    ComponentUpdateCheckResult,
    check_component_updates,
    normalize_ffmpeg_release_version,
)
from app.paths import RRV_TOOLS_DIR, has_bundled_tools
from app.theme import (
    THEME_DARK,
    THEME_LIGHT,
    active_theme_mode,
    load_theme_preference,
    save_theme_preference,
)
from app.tool_manager import (
    inspect_tools,
    update_ffmpeg_release,
    update_ytdlp,
)
from app.tool_sources import (
    DENO_RELEASES_PAGE,
    FFMPEG_RELEASES_PAGE,
    WPC_RELEASES_PAGE,
    YTDLP_RELEASES_PAGE,
)
from ui.dialogs.warm_dialogs import ask_warm_question, show_warm_message
from ui.pages.settings_page import SettingsPage
from ui.widgets.common import create_card


class ThemeSettingsPage(SettingsPage):
    """1.1.3 화면 테마와 간소화된 도구 업데이트 UX를 제공한다."""

    component_check_finished = Signal(object, bool)
    open_tools_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._component_check_running = False
        self._last_component_result: ComponentUpdateCheckResult | None = None
        self._tools_tab_checked_once = False
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
                self._create_tools_and_updates_card(),
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

    def _create_tools_and_updates_card(self) -> QFrame:
        card, layout = create_card()

        title = QLabel("도구 및 업데이트")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "RR-V가 사용하는 필수 도구의 상태와 버전을 관리합니다. "
            "새 버전이 있으면 필요한 도구만 한 번에 업데이트할 수 있습니다."
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
            version_label.setTextInteractionFlags(version_label.textInteractionFlags())

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

        self.restore_tools_button = QPushButton("문제 발생 시 복구")
        self.restore_tools_button.setObjectName("secondaryButton")
        self.restore_tools_button.clicked.connect(self._restore_packaged_tools)
        self.restore_tools_button.setToolTip(
            "RR-V 패키지에 포함된 기본 도구와 인증 런타임으로 복구합니다."
        )

        self.component_check_button = QPushButton("업데이트 확인")
        self.component_check_button.setObjectName("secondaryButton")
        self.component_check_button.clicked.connect(
            lambda: self.start_component_update_check(force=True, notify=False)
        )

        self.latest_update_button = QPushButton("최신 업데이트 하기")
        self.latest_update_button.setObjectName("primaryButton")
        self.latest_update_button.setEnabled(False)
        self.latest_update_button.clicked.connect(self._start_latest_updates)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(open_button)
        action_row.addWidget(self.restore_tools_button)
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

        ytdlp = statuses.get("ytdlp")
        if ytdlp is not None:
            self.tool_version_labels["ytdlp"].setText(ytdlp.version)
            self._set_tool_visual(
                "ytdlp",
                "normal" if ytdlp.available else "error",
                "✓ 정상" if ytdlp.available else "✕ 없음",
            )

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

        deno = statuses.get("deno")
        if deno is not None:
            self.tool_version_labels["deno"].setText(deno.version)
            self._set_tool_visual(
                "deno",
                "normal" if deno.available else "error",
                "✓ 정상" if deno.available else "✕ 없음",
            )

        pot = statuses.get("pot")
        if pot is not None:
            self.tool_version_labels["pot"].setText(pot.version)
            self._set_tool_visual(
                "pot",
                "normal" if pot.available else "error",
                "✓ 정상" if pot.available else "✕ 없음",
            )

        self.restore_tools_button.setEnabled(has_bundled_tools())
        if not has_bundled_tools():
            self.restore_tools_button.setToolTip(
                "현재 소스 실행에는 내장 복구 파일이 없습니다. 최종 패키지에서 사용할 수 있습니다."
            )

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
                # 업데이트 확인은 부가 기능이다. 예상하지 못한 네트워크/파싱
                # 오류도 RR-V 본체로 전파하지 않는다.
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
            if hasattr(self, "component_update_status"):
                self.component_update_status.setText(
                    "✓ 오늘 이미 자동 확인했습니다. 도구가 바뀌면 다음 실행에서 다시 확인합니다."
                )
            return

        if not result.components:
            if hasattr(self, "component_update_status"):
                self.component_update_status.setText(
                    "업데이트 서버를 확인하지 못했습니다. RR-V는 정상적으로 사용할 수 있습니다."
                )
                self.latest_update_button.setEnabled(False)
            return

        for component in result.components:
            if component.key not in self.tool_status_labels:
                continue
            if component.update_available is None:
                self._set_tool_visual(component.key, "error", "확인 실패")
            elif component.update_available:
                self._set_tool_visual(component.key, "update", "● 업데이트 가능")
            else:
                self._set_tool_visual(component.key, "normal", "✓ 최신")

        updates = result.updates
        failed_count = len(result.errors)
        self.latest_update_button.setEnabled(bool(updates))
        if updates:
            self.component_update_status.setText(
                f"업데이트 {len(updates)}개가 있습니다. 필요한 도구만 자동으로 업데이트합니다."
            )
        elif failed_count:
            self.component_update_status.setText(
                "확인 가능한 도구는 최신입니다. 일부 서버 확인은 실패했습니다."
            )
        else:
            self.component_update_status.setText("✓ 주요 도구가 최신 상태입니다.")

        if not notify or not updates:
            return

        lines = [
            "필수 도구 업데이트가 있습니다.",
            "안정적인 다운로드를 위해 최신 버전을 권장합니다.",
            "",
        ]
        for component in updates:
            lines.append(
                f"• {component.label}\n  {component.current} → {component.latest}"
            )

        open_tools = ask_warm_question(
            self,
            "RR-V 구성요소 업데이트",
            "\n".join(lines),
            yes_text="도구 및 리소스 열기",
            no_text="나중에",
        )
        if open_tools:
            self.open_tools_requested.emit()

    def _start_latest_updates(self) -> None:
        result = self._last_component_result
        updates = result.updates if result is not None else ()
        if not updates:
            show_warm_message(
                self,
                "도구 업데이트",
                "현재 확인된 업데이트가 없습니다. 먼저 '업데이트 확인'을 눌러 주세요.",
            )
            return

        update_keys = {component.key for component in updates}
        detail = [f"{len(updates)}개의 도구를 최신 버전으로 업데이트합니다."]
        if "ffmpeg" in update_keys:
            detail.append("FFmpeg가 포함되어 약 100 MB의 ZIP 파일을 다운로드합니다.")
        detail.append("다운로드나 미디어 작업 중이라면 먼저 작업을 끝내는 것을 권장합니다.")
        if not ask_warm_question(
            self,
            "최신 업데이트 하기",
            "\n\n".join(detail),
            yes_text="업데이트 시작",
            no_text="취소",
        ):
            return

        self.latest_update_button.setEnabled(False)
        self.component_check_button.setEnabled(False)
        self.tool_action_status.emit("업데이트 준비 중…")

        def run() -> None:
            messages: list[str] = []
            all_ok = True

            if "ytdlp" in update_keys:
                ok, message = update_ytdlp(self.tool_action_status.emit)
                all_ok = all_ok and ok
                messages.append(
                    "yt-dlp 업데이트 완료" if ok else f"yt-dlp 업데이트 실패: {message}"
                )

            if "ffmpeg" in update_keys:
                ok, message = update_ffmpeg_release(self.tool_action_status.emit)
                all_ok = all_ok and ok
                messages.append(
                    message if ok else f"FFmpeg 업데이트 실패: {message}"
                )

            self.tool_action_finished.emit(all_ok, "\n".join(messages))

        threading.Thread(target=run, daemon=True).start()

    def _tool_action_done(self, ok: bool, message: str) -> None:
        if hasattr(self, "component_check_button"):
            self.component_check_button.setEnabled(True)
        if hasattr(self, "latest_update_button"):
            self.latest_update_button.setEnabled(False)
        if hasattr(self, "restore_tools_button"):
            self.restore_tools_button.setEnabled(has_bundled_tools())
        if hasattr(self, "tool_action_label"):
            self.tool_action_label.setText(("✓ " if ok else "⚠ ") + message)
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
