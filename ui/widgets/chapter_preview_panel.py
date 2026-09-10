from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import QCheckBox, QHBoxLayout

from app.chapter_preferences import (
    load_delete_original_after_split,
    save_delete_original_after_split,
)
from app.download_preferences import DownloadPreferences
from app.preset_store import save_preset_library
from ui.widgets.preview_panel import PreviewPanel as _BasePreviewPanel


class PreviewPanel(_BasePreviewPanel):
    """1.4 챕터 관련 옵션을 기존 영상 정보 편집 패널에 덧붙인다.

    프리셋 값은 초기값으로만 사용하고, 여기서 체크를 바꾸면 현재 영상에만
    적용된다. 사용자가 '프리셋으로 저장'을 눌렀을 때만 새 프리셋에 반영한다.
    """

    def _create_settings_frame(self):  # type: ignore[no-untyped-def]
        frame = super()._create_settings_frame()

        self.split_chapters_checkbox = QCheckBox("챕터별 파일 저장")
        self.split_chapters_checkbox.setObjectName("previewCheckBox")
        self.split_chapters_checkbox.setToolTip(
            "다운로드가 끝난 뒤 영상의 챕터를 각각 별도 파일로 저장합니다."
        )
        self.delete_original_after_split_checkbox = QCheckBox(
            "분할 성공 후 원본 삭제"
        )
        self.delete_original_after_split_checkbox.setObjectName("previewCheckBox")
        self.delete_original_after_split_checkbox.setToolTip(
            "모든 챕터 파일이 정상 생성된 경우에만 원본 영상을 삭제합니다."
        )
        self.sponsorblock_chapters_checkbox = QCheckBox("SponsorBlock 챕터")
        self.sponsorblock_chapters_checkbox.setObjectName("previewCheckBox")
        self.sponsorblock_chapters_checkbox.setToolTip(
            "YouTube의 SponsorBlock 구간을 영상 챕터로 표시합니다. "
            "구간을 삭제하거나 잘라내지 않습니다."
        )

        root_layout = frame.layout()
        thumbnail_row = None
        if root_layout is not None and root_layout.count():
            thumbnail_row = root_layout.itemAt(root_layout.count() - 1).layout()

        if thumbnail_row is not None and hasattr(thumbnail_row, "insertWidget"):
            insert_at = max(0, thumbnail_row.count() - 1)
            thumbnail_row.insertWidget(insert_at, self.split_chapters_checkbox)
            thumbnail_row.insertWidget(
                insert_at + 1,
                self.delete_original_after_split_checkbox,
            )
            thumbnail_row.insertWidget(
                insert_at + 2,
                self.sponsorblock_chapters_checkbox,
            )
        elif root_layout is not None:
            row = QHBoxLayout()
            row.setSpacing(18)
            row.addWidget(self.split_chapters_checkbox)
            row.addWidget(self.delete_original_after_split_checkbox)
            row.addWidget(self.sponsorblock_chapters_checkbox)
            row.addStretch()
            root_layout.addLayout(row)

        return frame

    def _connect_option_signals(self) -> None:
        super()._connect_option_signals()
        self.split_chapters_checkbox.toggled.connect(self._split_chapters_changed)
        self.delete_original_after_split_checkbox.toggled.connect(self._option_changed)
        self.sponsorblock_chapters_checkbox.toggled.connect(self._option_changed)

    def selected_options(self) -> dict[str, object]:
        options = super().selected_options()
        split_enabled = bool(
            self.split_chapters_checkbox.isChecked()
            and not self.audio_only_checkbox.isChecked()
        )
        options["split_chapters"] = split_enabled
        options["delete_original_after_split"] = bool(
            split_enabled and self.delete_original_after_split_checkbox.isChecked()
        )
        options["sponsorblock_chapters"] = bool(
            self.sponsorblock_chapters_checkbox.isChecked()
            and not self.audio_only_checkbox.isChecked()
            and self._sponsorblock_supported()
        )
        return options

    def _apply_preferences(self, preferences: DownloadPreferences) -> None:
        super()._apply_preferences(preferences)

        self.split_chapters_checkbox.blockSignals(True)
        self.delete_original_after_split_checkbox.blockSignals(True)
        self.sponsorblock_chapters_checkbox.blockSignals(True)
        try:
            split_enabled = bool(
                preferences.split_chapters and not preferences.audio_only
            )
            self.split_chapters_checkbox.setChecked(split_enabled)
            self.delete_original_after_split_checkbox.setChecked(
                bool(
                    split_enabled
                    and load_delete_original_after_split(preferences.preset_id)
                )
            )
            self.sponsorblock_chapters_checkbox.setChecked(
                bool(
                    preferences.sponsorblock_chapters
                    and not preferences.audio_only
                )
            )
        finally:
            self.split_chapters_checkbox.blockSignals(False)
            self.delete_original_after_split_checkbox.blockSignals(False)
            self.sponsorblock_chapters_checkbox.blockSignals(False)

        self._sync_chapter_controls()
        self._sync_sponsorblock_control()
        self._update_settings_summary()

    def _split_chapters_changed(self, checked: bool) -> None:
        if not checked and self.delete_original_after_split_checkbox.isChecked():
            self.delete_original_after_split_checkbox.blockSignals(True)
            try:
                self.delete_original_after_split_checkbox.setChecked(False)
            finally:
                self.delete_original_after_split_checkbox.blockSignals(False)
        self._sync_chapter_controls()
        self._option_changed()

    def _audio_only_changed(self, checked: bool) -> None:
        super()._audio_only_changed(checked)
        if not hasattr(self, "split_chapters_checkbox"):
            return

        if checked:
            for checkbox in (
                self.split_chapters_checkbox,
                self.delete_original_after_split_checkbox,
                self.sponsorblock_chapters_checkbox,
            ):
                checkbox.blockSignals(True)
                try:
                    checkbox.setChecked(False)
                finally:
                    checkbox.blockSignals(False)
        self._sync_chapter_controls()
        self._sync_sponsorblock_control()
        self._update_settings_summary()

    def _sync_chapter_controls(self) -> None:
        if not hasattr(self, "split_chapters_checkbox"):
            return
        audio_only = self.audio_only_checkbox.isChecked()
        self.split_chapters_checkbox.setEnabled(not audio_only)
        self.delete_original_after_split_checkbox.setEnabled(
            not audio_only and self.split_chapters_checkbox.isChecked()
        )

    def _sync_sponsorblock_control(self) -> None:
        if not hasattr(self, "sponsorblock_chapters_checkbox"):
            return
        supported = self._sponsorblock_supported()
        audio_only = self.audio_only_checkbox.isChecked()
        self.sponsorblock_chapters_checkbox.setEnabled(
            supported and not audio_only
        )
        if supported:
            self.sponsorblock_chapters_checkbox.setToolTip(
                "YouTube의 SponsorBlock 구간을 영상 챕터로 표시합니다. "
                "구간을 삭제하거나 잘라내지 않습니다."
            )
        else:
            self.sponsorblock_chapters_checkbox.setToolTip(
                "SponsorBlock 챕터 표시는 YouTube 영상에서만 사용할 수 있습니다."
            )

    def _sponsorblock_supported(self) -> bool:
        media_info = self.media_info
        if media_info is None:
            return False
        return str(media_info.extractor or "").strip().casefold().startswith(
            "youtube"
        )

    def _update_settings_summary(self) -> None:
        super()._update_settings_summary()
        if not hasattr(self, "split_chapters_checkbox"):
            return
        current = self.settings_summary.text().strip()
        if (
            self.sponsorblock_chapters_checkbox.isChecked()
            and not self.audio_only_checkbox.isChecked()
            and self._sponsorblock_supported()
        ):
            current = (
                f"{current} · SponsorBlock 챕터"
                if current
                else "SponsorBlock 챕터"
            )
        if (
            self.split_chapters_checkbox.isChecked()
            and not self.audio_only_checkbox.isChecked()
        ):
            current = f"{current} · 챕터별 저장" if current else "챕터별 저장"
            if self.delete_original_after_split_checkbox.isChecked():
                current += " · 원본 삭제"
        self.settings_summary.setText(current)

    def _save_current_as_preset(self) -> None:
        desired_split = bool(
            self.split_chapters_checkbox.isChecked()
            and not self.audio_only_checkbox.isChecked()
        )
        desired_delete = bool(
            desired_split and self.delete_original_after_split_checkbox.isChecked()
        )
        desired_sponsorblock = bool(
            self.sponsorblock_chapters_checkbox.isChecked()
            and not self.audio_only_checkbox.isChecked()
        )
        before_ids = {preset.preset_id for preset in self._preset_library.presets}

        super()._save_current_as_preset()

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

        preferences = replace(
            created.to_preferences(),
            split_chapters=desired_split,
            sponsorblock_chapters=desired_sponsorblock,
        ).normalized()
        replacement = created.with_preferences(preferences)
        try:
            self._preset_library.replace_preset(created.preset_id, replacement)
            save_preset_library(self._preset_library)
            save_delete_original_after_split(
                replacement.preset_id,
                desired_delete,
            )
        except (OSError, ValueError, KeyError):
            return

        self._refresh_preset_combo(replacement.preset_id)
        self._select_default_subtitles(replacement.to_preferences())
        self._apply_preferences(replacement.to_preferences())
        self.preset_status_label.setText("저장됨")


__all__ = ["PreviewPanel"]