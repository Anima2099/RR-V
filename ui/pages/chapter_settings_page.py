from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import QCheckBox, QLabel

from app.chapter_preferences import (
    load_delete_original_after_split,
    save_delete_original_after_split,
)
from app.download_preferences import DownloadPreferences
from app.general_preferences import save_general_preferences
from ui.pages.unified_settings_page import UnifiedSettingsPage as _BaseSettingsPage
from ui.widgets.common import create_card


class UnifiedSettingsPage(_BaseSettingsPage):
    """1.4 챕터와 빠른 추가 관련 다운로드 옵션을 설정 화면에 추가한다."""

    def _create_preset_tab(self):  # type: ignore[no-untyped-def]
        # 빠른 추가 자동 다운로드는 프리셋 값이 아니라 RR-V 전체 동작 설정이다.
        # 기존 다운로드 설정 구성은 유지하면서 별도 카드로 명확히 분리한다.
        return self._create_scroll_page(
            [
                self._create_download_folder_card(),
                self._create_filename_template_card(),
                self._create_file_collision_card(),
                self._create_quick_add_behavior_card(),
                self._create_download_common_save_bar(),
                self._create_download_preferences_card(),
            ]
        )

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