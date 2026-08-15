from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings
from app.settings_store import get_settings

from core.subtitle_models import (
    EXTRACT_ORIGINAL,
    OP_EXTRACT,
    OUTPUT_OVERWRITE,
    OUTPUT_SOURCE,
)


@dataclass(slots=True)
class SubtitlePreferences:
    operation: str = OP_EXTRACT
    extract_format: str = EXTRACT_ORIGINAL
    language: str = "auto"
    track_title: str = ""
    make_default: bool = False
    make_forced: bool = False
    delete_external_after_insert: bool = False
    sync_offset_ms: int = 0
    output_mode: str = OUTPUT_OVERWRITE
    output_folder_mode: str = OUTPUT_SOURCE
    output_folder: str = str(Path.home() / "Videos")
    single_expanded: bool = True
    batch_expanded: bool = False
    settings_expanded: bool = False
    output_expanded: bool = False


def _settings() -> QSettings:
    return get_settings()


def _bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        return min(maximum, max(minimum, int(value)))
    except (TypeError, ValueError):
        return default


def load_subtitle_preferences() -> SubtitlePreferences:
    s = _settings()
    d = SubtitlePreferences()
    operation = str(s.value("subtitle/operation", d.operation))
    if operation not in {"extract", "insert", "sync", "remove"}:
        operation = d.operation
    extract_format = str(s.value("subtitle/extract_format", d.extract_format))
    if extract_format not in {"original", "srt", "ass"}:
        extract_format = d.extract_format
    output_mode = str(s.value("subtitle/output_mode", d.output_mode))
    if output_mode not in {"overwrite", "new_file"}:
        output_mode = d.output_mode
    folder_mode = str(s.value("subtitle/output_folder_mode", d.output_folder_mode))
    if folder_mode not in {"source", "custom"}:
        folder_mode = d.output_folder_mode
    folder = str(s.value("subtitle/output_folder", d.output_folder)).strip() or d.output_folder

    # v0.10.2: older builds defaulted insertion metadata to Korean.
    # Migrate once so existing users also get the safer automatic language mode.
    migrated = _bool(s.value("subtitle/language_auto_v0102", False), False)
    if migrated:
        language = str(s.value("subtitle/language", d.language)).strip() or "auto"
        track_title = str(s.value("subtitle/track_title", d.track_title)).strip()
    else:
        language = "auto"
        track_title = ""
        s.setValue("subtitle/language_auto_v0102", True)
        s.setValue("subtitle/language", language)
        s.setValue("subtitle/track_title", track_title)
        s.sync()

    if language not in {"auto", "kor", "eng", "jpn", "chi", "zho", "und"}:
        language = "auto"

    return SubtitlePreferences(
        operation=operation,
        extract_format=extract_format,
        language=language,
        track_title=track_title,
        make_default=_bool(s.value("subtitle/make_default", d.make_default), d.make_default),
        make_forced=_bool(s.value("subtitle/make_forced", d.make_forced), d.make_forced),
        delete_external_after_insert=_bool(s.value("subtitle/delete_external_after_insert", d.delete_external_after_insert), d.delete_external_after_insert),
        sync_offset_ms=0,
        output_mode=output_mode,
        output_folder_mode=folder_mode,
        output_folder=folder,
        single_expanded=_bool(s.value("subtitle/single_expanded", d.single_expanded), d.single_expanded),
        batch_expanded=_bool(s.value("subtitle/batch_expanded", d.batch_expanded), d.batch_expanded),
        settings_expanded=_bool(s.value("subtitle/settings_expanded", d.settings_expanded), d.settings_expanded),
        output_expanded=_bool(s.value("subtitle/output_expanded", d.output_expanded), d.output_expanded),
    )


def save_subtitle_preferences(p: SubtitlePreferences) -> None:
    s = _settings()
    values = {
        "subtitle/operation": p.operation,
        "subtitle/extract_format": p.extract_format,
        "subtitle/language": p.language,
        "subtitle/track_title": p.track_title,
        "subtitle/make_default": p.make_default,
        "subtitle/make_forced": p.make_forced,
        "subtitle/delete_external_after_insert": p.delete_external_after_insert,
        "subtitle/sync_offset_ms": 0,
        "subtitle/output_mode": p.output_mode,
        "subtitle/output_folder_mode": p.output_folder_mode,
        "subtitle/output_folder": p.output_folder,
        "subtitle/single_expanded": p.single_expanded,
        "subtitle/batch_expanded": p.batch_expanded,
        "subtitle/settings_expanded": p.settings_expanded,
        "subtitle/output_expanded": p.output_expanded,
    }
    for key, value in values.items():
        s.setValue(key, value)
    s.sync()
