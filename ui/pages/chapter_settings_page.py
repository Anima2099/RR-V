from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.chapter_preferences import (
    load_delete_original_after_split,
    save_delete_original_after_split,
)
from app.download_preferences import DownloadPreferences
from app.general_preferences import save_general_preferences
from ui.pages.unified_settings_page import UnifiedSettingsPage as _BaseSettingsPage
from ui.widgets.common import create_card


class UnifiedSettingsPage(_BaseSettingsPage):
    """1.4 다운로드 기능과 설정 카테고리 구조를 제공한다."""

    _CATEGORY_TABS = (
        (_BaseSettingsPage.GENERAL_TAB, "기본 설정"),
        (_BaseSettingsPage.YOUTUBE_TAB, "사이트 연동"),
        (_BaseSettingsPage.TOOLS_TAB, "프로그램 관리"),
    )

    def _create_tab_bar(self) -> QFrame:
        tab_bar = QFrame()
        tab_bar.setObjectName("toolTabBar")

        tab_layout = QHBoxLayout(tab_bar)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(8)

        self.tab_button_group = QButtonGroup(self)
        self.tab_button_group.setExclusive(True)
        self.tab_buttons: list[QPushButton] = []

        for page_index, name in self._CATEGORY_TABS:
            button = QPushButton(name)
            button.setObjectName("toolTabButton")
            button.setCheckable(True)
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            button.clicked.connect(
                lambda checked=False, target=page_index:
                self.show_settings_tab(target)
            )
            self.tab_button_group.addButton(button, page_index)
            self.tab_buttons.append(button)
            tab_layout.addWidget(button, 1)

        return tab_bar

    def _create_category_page(
        self,
        key: str,
        names: tuple[str, ...],
        pages: tuple[QWidget, ...],
    ) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(8)

        subtab_bar = QFrame()
        subtab_bar.setObjectName("toolTabBar")
        subtab_layout = QHBoxLayout(subtab_bar)
        subtab_layout.setContentsMargins(10, 10, 10, 0)
        subtab_layout.setSpacing(8)

        button_group = QButtonGroup(self)
        button_group.setExclusive(True)
        buttons: list[QPushButton] = []

        stack = QStackedWidget()
        stack.setObjectName("toolStack")
        for child_page in pages:
            stack.addWidget(child_page)

        for index, name in enumerate(names):
            button = QPushButton(name)
            button.setObjectName("queueFilterButton")
            button.setCheckable(True)
            button.setMinimumWidth(150)
            button.clicked.connect(
                lambda checked=False, group_key=key, sub_index=index:
                self._show_category_subtab(group_key, sub_index)
            )
            button_group.addButton(button, index)
            buttons.append(button)
            subtab_layout.addWidget(button)
        subtab_layout.addStretch()

        if not hasattr(self, "settings_category_stacks"):
            self.settings_category_stacks: dict[str, QStackedWidget] = {}
            self.settings_category_buttons: dict[str, list[QPushButton]] = {}
            self.settings_category_groups: dict[str, QButtonGroup] = {}
        self.settings_category_stacks[key] = stack
        self.settings_category_buttons[key] = buttons
        self.settings_category_groups[key] = button_group

        page_layout.addWidget(subtab_bar, 0)
        page_layout.addWidget(stack, 1)

        buttons[0].setChecked(True)
        stack.setCurrentIndex(0)
        return page

    def _create_general_tab(self):  # type: ignore[no-untyped-def]
        general_page = super()._create_general_tab()
        download_page = self._create_download_settings_page()
        preset_page = self._create_download_preset_page()
        return self._create_category_page(
            "basic",
            ("일반 설정", "다운로드 설정", "다운로드 프리셋"),
            (general_page, download_page, preset_page),
        )

    def _create_download_settings_page(self):  # type: ignore[no-untyped-def]
        return self._create_scroll_page(
            [
                self._create_download_folder_card(),
                self._create_quick_add_behavior_card(),
                self._create_file_collision_card(),
                self._create_filename_template_card(),
                self._create_download_common_save_bar(),
            ]
        )

    def _create_download_preset_page(self):  # type: ignore[no-untyped-def]
        return self._create_scroll_page(
            [
                self._create_download_preferences_card(),
            ]
        )

    def _create_preset_tab(self):  # type: ignore[no-untyped-def]
        # 기본 SettingsPage의 고정 6칸 stack 인덱스 호환용 자리다.
        # 실제 프리셋 화면은 '기본 설정' 내부 세 번째 탭에 한 번만 생성한다.
        return QWidget()

    def _create_youtube_tab(self):  # type: ignore[no-untyped-def]
        auth_page = super()._create_youtube_tab()
        integration_page = super()._create_integration_tab()
        return self._create_category_page(
            "site",
            ("인증 관리", "확장 프로그램"),
            (auth_page, integration_page),
        )

    def _create_integration_tab(self):  # type: ignore[no-untyped-def]
        # 실제 브라우저 확장 화면은 '사이트 연동' 내부에 생성한다.
        return QWidget()

    def _create_tools_tab(self):  # type: ignore[no-untyped-def]
        tools_page = super()._create_tools_tab()
        backup_page = super()._create_backup_tab()
        return self._create_category_page(
            "program",
            ("도구 및 리소스", "백업 및 복구"),
            (tools_page, backup_page),
        )

    def _create_backup_tab(self):  # type: ignore[no-untyped-def]
        # 실제 백업 화면은 '프로그램 관리' 내부에 생성한다.
        return QWidget()

    def _show_category_subtab(self, key: str, index: int) -> None:
        stacks = getattr(self, "settings_category_stacks", {})
        buttons_by_key = getattr(self, "settings_category_buttons", {})
        stack = stacks.get(key)
        buttons = buttons_by_key.get(key, [])
        if stack is None or not buttons:
            return
        if index < 0 or index >= stack.count():
            index = 0

        stack.setCurrentIndex(index)
        buttons[index].setChecked(True)

        if key == "basic":
            if index == 0 and hasattr(self, "theme_light_radio"):
                self._reload_theme_preferences_to_controls()
            elif index == 2 and hasattr(self, "preset_combo"):
                self._load_preferences_into_controls()
        elif key == "site":
            if index == 0 and hasattr(self, "youtube_auth_status_label"):
                self._refresh_youtube_auth_status()
                if hasattr(self, "instagram_auth_status_label"):
                    self._refresh_instagram_auth_status()
                if hasattr(self, "tiktok_auth_status_label"):
                    self._refresh_tiktok_auth_status()
            elif index == 1 and hasattr(self, "browser_integration_status_label"):
                self._refresh_browser_integration_status()
        elif key == "program":
            if index == 0 and hasattr(self, "tool_status_labels"):
                self._refresh_tool_status()
                if not getattr(self, "_tools_tab_checked_once", False):
                    self._tools_tab_checked_once = True
                    self.start_component_update_check(force=True, notify=False)
            elif index == 1 and hasattr(self, "backup_status_label"):
                self._refresh_backup_status()

    def show_settings_tab(self, index: int) -> None:
        if not hasattr(self, "settings_stack"):
            return

        # 기존 코드가 여섯 개의 과거 탭 인덱스를 직접 호출해도 같은 화면으로
        # 안전하게 연결한다. 새 상단 UI에는 세 개의 카테고리만 노출한다.
        legacy_routes = {
            self.GENERAL_TAB: (self.GENERAL_TAB, "basic", 0),
            self.PRESET_TAB: (self.GENERAL_TAB, "basic", 2),
            self.YOUTUBE_TAB: (self.YOUTUBE_TAB, "site", 0),
            self.INTEGRATION_TAB: (self.YOUTUBE_TAB, "site", 1),
            self.TOOLS_TAB: (self.TOOLS_TAB, "program", 0),
            self.BACKUP_TAB: (self.TOOLS_TAB, "program", 1),
        }
        category_index, key, sub_index = legacy_routes.get(
            index,
            legacy_routes[self.GENERAL_TAB],
        )

        self.settings_stack.setCurrentIndex(category_index)
        for button in self.tab_buttons:
            button.setChecked(
                self.tab_button_group.id(button) == category_index
            )
        self._show_category_subtab(key, sub_index)

    def _create_quick_add_behavior_card(self):  # type: ignore[no-untyped-def]
        card, layout = create_card()

        title = QLabel("빠른 추가")
        title.setObjectName("sectionTitle")

        description = QLabel(
            "빠른 추가는 기본 프리셋으로 영상 정보를 확인한 뒤 다운로드 목록에 넣습니다. "
            "자동 다운로드를 켜면 정보 확인이 끝난 뒤 기존 순차 대기열을 자동으로 시작합니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)

        self.quick_add_auto_download_checkbox = QCheckBox(
            "빠른 추가 후 자동으로 다운로드 시작"
        )
        self.quick_add_auto_download_checkbox.setObjectName("settingsCheckbox")
        self.quick_add_auto_download_checkbox.setChecked(
            self._general_preferences.quick_add_auto_download
        )

        hint = QLabel(
            "기본값은 꺼짐입니다. 이미 다운로드 중이거나 먼저 대기 중인 작업이 있으면 "
            "병렬 실행이나 새치기 없이 기존 목록 순서대로 이어서 다운로드합니다."
        )
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(self.quick_add_auto_download_checkbox)
        layout.addWidget(hint)
        return card

    def _create_download_preferences_card(self):  # type: ignore[no-untyped-def]
        card = super()._create_download_preferences_card()

        self.delete_original_after_split_checkbox = QCheckBox(
            "분할 성공 후 원본 파일 삭제"
        )
        self.delete_original_after_split_checkbox.setObjectName("previewCheckBox")
        self.delete_original_after_split_checkbox.setToolTip(
            "모든 챕터 파일이 정상 생성된 경우에만 원본 영상을 삭제합니다. "
            "분할 실패나 중지 시에는 원본을 보존합니다."
        )

        self.sponsorblock_chapters_checkbox = QCheckBox(
            "SponsorBlock 구간을 챕터로 표시"
        )
        self.sponsorblock_chapters_checkbox.setObjectName("previewCheckBox")
        self.sponsorblock_chapters_checkbox.setToolTip(
            "YouTube의 SponsorBlock 정보에서 스폰서, 인트로, 아웃트로 등 "
            "등록 구간을 영상 챕터로 표시합니다. 구간을 삭제하거나 잘라내지 않습니다."
        )

        parent = getattr(self, "split_chapters_checkbox", None)
        parent_widget = parent.parentWidget() if parent is not None else None
        parent_layout = parent_widget.layout() if parent_widget is not None else None
        if parent_layout is not None:
            parent_layout.addWidget(self.delete_original_after_split_checkbox)
            parent_layout.addWidget(self.sponsorblock_chapters_checkbox)

        if parent is not None:
            parent.toggled.connect(self._chapter_split_setting_changed)
        self.delete_original_after_split_checkbox.toggled.connect(
            self._chapter_delete_setting_changed
        )
        self._sync_chapter_delete_control()
        self._sync_sponsorblock_control()
        return card

    def _set_controls(self, preferences: DownloadPreferences) -> None:
        super()._set_controls(preferences)
        if hasattr(self, "delete_original_after_split_checkbox"):
            enabled = load_delete_original_after_split(preferences.preset_id)
            self.delete_original_after_split_checkbox.blockSignals(True)
            try:
                self.delete_original_after_split_checkbox.setChecked(
                    bool(
                        enabled
                        and preferences.split_chapters
                        and not preferences.audio_only
                    )
                )
            finally:
                self.delete_original_after_split_checkbox.blockSignals(False)
            self._sync_chapter_delete_control()

        if hasattr(self, "sponsorblock_chapters_checkbox"):
            self.sponsorblock_chapters_checkbox.blockSignals(True)
            try:
                self.sponsorblock_chapters_checkbox.setChecked(
                    bool(
                        preferences.sponsorblock_chapters
                        and not preferences.audio_only
                    )
                )
            finally:
                self.sponsorblock_chapters_checkbox.blockSignals(False)
            self._sync_sponsorblock_control()

    def _preferences_from_controls(self) -> DownloadPreferences:
        preferences = super()._preferences_from_controls()
        sponsorblock_enabled = bool(
            hasattr(self, "sponsorblock_chapters_checkbox")
            and self.sponsorblock_chapters_checkbox.isChecked()
            and hasattr(self, "audio_only_checkbox")
            and not self.audio_only_checkbox.isChecked()
        )
        return replace(
            preferences,
            sponsorblock_chapters=sponsorblock_enabled,
        ).normalized()

    def _update_audio_controls(self) -> None:
        super()._update_audio_controls()
        if hasattr(self, "delete_original_after_split_checkbox"):
            self._sync_chapter_delete_control()
        if hasattr(self, "sponsorblock_chapters_checkbox"):
            self._sync_sponsorblock_control()

    def _chapter_split_setting_changed(self, checked: bool) -> None:
        if not hasattr(self, "delete_original_after_split_checkbox"):
            return
        if not checked and self.delete_original_after_split_checkbox.isChecked():
            self.delete_original_after_split_checkbox.setChecked(False)
        self._sync_chapter_delete_control()

    def _chapter_delete_setting_changed(self, _checked: bool) -> None:
        self._sync_chapter_delete_control()

    def _sync_chapter_delete_control(self) -> None:
        if not hasattr(self, "delete_original_after_split_checkbox"):
            return
        split_enabled = bool(
            hasattr(self, "split_chapters_checkbox")
            and self.split_chapters_checkbox.isChecked()
        )
        audio_only = bool(
            hasattr(self, "audio_only_checkbox")
            and self.audio_only_checkbox.isChecked()
        )
        self.delete_original_after_split_checkbox.setEnabled(
            split_enabled and not audio_only
        )
        if (
            (not split_enabled or audio_only)
            and self.delete_original_after_split_checkbox.isChecked()
        ):
            self.delete_original_after_split_checkbox.blockSignals(True)
            try:
                self.delete_original_after_split_checkbox.setChecked(False)
            finally:
                self.delete_original_after_split_checkbox.blockSignals(False)

    def _sync_sponsorblock_control(self) -> None:
        if not hasattr(self, "sponsorblock_chapters_checkbox"):
            return
        audio_only = bool(
            hasattr(self, "audio_only_checkbox")
            and self.audio_only_checkbox.isChecked()
        )
        self.sponsorblock_chapters_checkbox.setEnabled(not audio_only)
        if audio_only and self.sponsorblock_chapters_checkbox.isChecked():
            self.sponsorblock_chapters_checkbox.blockSignals(True)
            try:
                self.sponsorblock_chapters_checkbox.setChecked(False)
            finally:
                self.sponsorblock_chapters_checkbox.blockSignals(False)

    def _apply_general_preferences_to_controls(self) -> None:
        super()._apply_general_preferences_to_controls()
        if hasattr(self, "quick_add_auto_download_checkbox"):
            self.quick_add_auto_download_checkbox.setChecked(
                self._general_preferences.quick_add_auto_download
            )

    def _save_download_settings(self) -> None:
        desired_quick_auto = bool(
            hasattr(self, "quick_add_auto_download_checkbox")
            and self.quick_add_auto_download_checkbox.isChecked()
        )
        super()._save_download_settings()

        # 파일명 템플릿 검증 등에 실패했다면 부모 저장도 중단된 상태다. 이때
        # 빠른 추가 옵션만 따로 저장되는 반쪽 상태를 만들지 않는다.
        if self.download_settings_save_status.text() != "공통 다운로드 설정이 저장되었습니다.":
            return

        preferences = replace(
            self._general_preferences,
            quick_add_auto_download=desired_quick_auto,
        )
        save_general_preferences(preferences)
        self._general_preferences = preferences

    def _save_preferences(self) -> None:
        preset = self._current_preset()
        desired_delete = self._current_delete_original_value()
        self.save_status_label.setText("")
        super()._save_preferences()
        if self.save_status_label.text() == "저장됨":
            save_delete_original_after_split(preset.preset_id, desired_delete)

    def _create_preset(self) -> None:
        before_ids = {preset.preset_id for preset in self._preset_library.presets}
        desired_delete = self._current_delete_original_value()
        super()._create_preset()
        self._save_delete_for_new_preset(before_ids, desired_delete)

    def _duplicate_preset(self) -> None:
        before_ids = {preset.preset_id for preset in self._preset_library.presets}
        desired_delete = self._current_delete_original_value()
        super()._duplicate_preset()
        self._save_delete_for_new_preset(before_ids, desired_delete)

    def _restore_defaults(self) -> None:
        super()._restore_defaults()
        if hasattr(self, "delete_original_after_split_checkbox"):
            self.delete_original_after_split_checkbox.setChecked(False)
            self._sync_chapter_delete_control()
        if hasattr(self, "sponsorblock_chapters_checkbox"):
            self.sponsorblock_chapters_checkbox.setChecked(False)
            self._sync_sponsorblock_control()

    def _current_delete_original_value(self) -> bool:
        return bool(
            hasattr(self, "delete_original_after_split_checkbox")
            and self.delete_original_after_split_checkbox.isChecked()
            and hasattr(self, "split_chapters_checkbox")
            and self.split_chapters_checkbox.isChecked()
            and hasattr(self, "audio_only_checkbox")
            and not self.audio_only_checkbox.isChecked()
        )

    def _save_delete_for_new_preset(
        self,
        before_ids: set[str],
        desired_delete: bool,
    ) -> None:
        created = next(
            (
                preset
                for preset in self._preset_library.presets
                if preset.preset_id not in before_ids
            ),
            None,
        )
        if created is None:
            return
        persisted = bool(
            desired_delete and created.split_chapters and not created.audio_only
        )
        save_delete_original_after_split(created.preset_id, persisted)

        # base 구현이 새 프리셋을 선택하면서 companion 값이 저장되기 전에 한 번
        # 컨트롤을 갱신하므로, 저장 직후 현재 화면도 같은 값으로 맞춘다.
        if self._current_preset().preset_id == created.preset_id:
            self.delete_original_after_split_checkbox.blockSignals(True)
            try:
                self.delete_original_after_split_checkbox.setChecked(persisted)
            finally:
                self.delete_original_after_split_checkbox.blockSignals(False)
            self._sync_chapter_delete_control()


__all__ = ["UnifiedSettingsPage"]
