from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings
from app.settings_store import get_settings

from core.snapshot_models import OUTPUT_CUSTOM, OUTPUT_SOURCE, SIZE_HEIGHT, SIZE_WIDTH


@dataclass(slots=True)
class SnapshotPreferences:
    columns: int = 4
    rows: int = 12
    margin: int = 5
    size_mode: str = SIZE_WIDTH
    target_size: int = 1920
    show_info: bool = True
    show_time: bool = True
    font_family: str = "Malgun Gothic"
    info_font_size: int = 24
    time_font_size: int = 16
    output_mode: str = OUTPUT_SOURCE
    output_folder: str = str(Path.home() / "Pictures")
    create_subfolder: bool = True
    subfolder_name: str = "Snapshot"
    single_expanded: bool = True
    batch_expanded: bool = False
    layout_expanded: bool = False
    display_expanded: bool = False
    output_expanded: bool = False


def _settings() -> QSettings:
    return get_settings()


def _bool_value(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int_value(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        return min(maximum, max(minimum, int(value)))
    except (TypeError, ValueError):
        return default


def load_snapshot_preferences() -> SnapshotPreferences:
    settings = _settings()
    defaults = SnapshotPreferences()

    size_mode = str(settings.value("snapshot/size_mode", defaults.size_mode))
    if size_mode not in {SIZE_WIDTH, SIZE_HEIGHT}:
        size_mode = defaults.size_mode

    output_mode = str(settings.value("snapshot/output_mode", defaults.output_mode))
    if output_mode not in {OUTPUT_SOURCE, OUTPUT_CUSTOM}:
        output_mode = defaults.output_mode

    output_folder = str(settings.value("snapshot/output_folder", defaults.output_folder)).strip()
    if not output_folder:
        output_folder = defaults.output_folder

    font_family = str(settings.value("snapshot/font_family", defaults.font_family)).strip()
    if not font_family:
        font_family = defaults.font_family

    subfolder_name = str(settings.value("snapshot/subfolder_name", defaults.subfolder_name)).strip()
    if not subfolder_name:
        subfolder_name = defaults.subfolder_name

    return SnapshotPreferences(
        columns=_int_value(settings.value("snapshot/columns", defaults.columns), defaults.columns, 1, 12),
        rows=_int_value(settings.value("snapshot/rows", defaults.rows), defaults.rows, 1, 30),
        margin=_int_value(settings.value("snapshot/margin", defaults.margin), defaults.margin, 0, 100),
        size_mode=size_mode,
        target_size=_int_value(settings.value("snapshot/target_size", defaults.target_size), defaults.target_size, 480, 10000),
        show_info=_bool_value(settings.value("snapshot/show_info", defaults.show_info), defaults.show_info),
        show_time=_bool_value(settings.value("snapshot/show_time", defaults.show_time), defaults.show_time),
        font_family=font_family,
        info_font_size=_int_value(settings.value("snapshot/info_font_size", defaults.info_font_size), defaults.info_font_size, 10, 72),
        time_font_size=_int_value(settings.value("snapshot/time_font_size", defaults.time_font_size), defaults.time_font_size, 8, 64),
        output_mode=output_mode,
        output_folder=output_folder,
        create_subfolder=_bool_value(settings.value("snapshot/create_subfolder", defaults.create_subfolder), defaults.create_subfolder),
        subfolder_name=subfolder_name,
        single_expanded=_bool_value(settings.value("snapshot/single_expanded", defaults.single_expanded), defaults.single_expanded),
        batch_expanded=_bool_value(settings.value("snapshot/batch_expanded", defaults.batch_expanded), defaults.batch_expanded),
        layout_expanded=_bool_value(settings.value("snapshot/layout_expanded", defaults.layout_expanded), defaults.layout_expanded),
        display_expanded=_bool_value(settings.value("snapshot/display_expanded", defaults.display_expanded), defaults.display_expanded),
        output_expanded=_bool_value(settings.value("snapshot/output_expanded", defaults.output_expanded), defaults.output_expanded),
    )


def save_snapshot_preferences(preferences: SnapshotPreferences) -> None:
    settings = _settings()
    for key, value in {
        "snapshot/columns": preferences.columns,
        "snapshot/rows": preferences.rows,
        "snapshot/margin": preferences.margin,
        "snapshot/size_mode": preferences.size_mode,
        "snapshot/target_size": preferences.target_size,
        "snapshot/show_info": preferences.show_info,
        "snapshot/show_time": preferences.show_time,
        "snapshot/font_family": preferences.font_family,
        "snapshot/info_font_size": preferences.info_font_size,
        "snapshot/time_font_size": preferences.time_font_size,
        "snapshot/output_mode": preferences.output_mode,
        "snapshot/output_folder": preferences.output_folder,
        "snapshot/create_subfolder": preferences.create_subfolder,
        "snapshot/subfolder_name": preferences.subfolder_name,
        "snapshot/single_expanded": preferences.single_expanded,
        "snapshot/batch_expanded": preferences.batch_expanded,
        "snapshot/layout_expanded": preferences.layout_expanded,
        "snapshot/display_expanded": preferences.display_expanded,
        "snapshot/output_expanded": preferences.output_expanded,
    }.items():
        settings.setValue(key, value)
    settings.sync()
