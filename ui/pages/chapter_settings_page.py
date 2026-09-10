from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import QCheckBox

from app.chapter_preferences import (
    load_delete_original_after_split,
    save_delete_original_after_split,
)
from app.download_preferences import DownloadPreferences
from ui.pages.unified_settings_page import UnifiedSettingsPage as _BaseSettingsPage


class UnifiedSettingsPage(_BaseSettingsPage):
    """1.4 챕터 관련 다운로드 옵션을 설정 화면에 추가한다."""

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