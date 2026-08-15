from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from PySide6.QtCore import QSettings
from app.settings_store import get_settings

from app.paths import APPDATA_DIR, RRV_DATA_DIR


FILE_COLLISION_NUMBERED = "numbered"
FILE_COLLISION_OVERWRITE = "overwrite"
FILE_COLLISION_MODES = {
    FILE_COLLISION_NUMBERED,
    FILE_COLLISION_OVERWRITE,
}

@dataclass(slots=True)
class GeneralPreferences:
    default_download_folder: str = str(Path.home() / "Downloads")
    cookie_folder: str = ""
    restore_queue_on_start: bool = True
    keep_completed_tasks: bool = True
    confirm_close_during_download: bool = True
    notify_queue_complete: bool = True
    notify_completion_sound: bool = False
    minimize_to_tray_on_close: bool = False
    start_with_windows: bool = False
    file_collision_mode: str = FILE_COLLISION_NUMBERED


def _settings() -> QSettings:
    return get_settings()


def _read_bool(settings: QSettings, key: str, default: bool) -> bool:
    value = settings.value(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _migrate_legacy_cookie_folder_once(settings: QSettings) -> None:
    """v0.11.0 전환 때 RR-HUB의 쿠키 폴더 설정만 한 번 옮긴다."""

    marker = RRV_DATA_DIR / ".rrhub_cookie_migrated_v0110"
    if marker.exists():
        return

    current = str(settings.value("general/cookie_folder", "") or "").strip()
    if not current:
        legacy_settings_path = APPDATA_DIR / "RR-HUB" / "settings.json"
        try:
            raw = json.loads(legacy_settings_path.read_text(encoding="utf-8"))
            legacy_folder = str(raw.get("cookie_path") or "").strip()
        except (OSError, json.JSONDecodeError, AttributeError):
            legacy_folder = ""

        if legacy_folder and Path(legacy_folder).is_dir():
            settings.setValue("general/cookie_folder", legacy_folder)
            settings.sync()

    try:
        RRV_DATA_DIR.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            "RR-V v0.11.0 one-time RR-HUB cookie setting migration completed.\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def load_general_preferences() -> GeneralPreferences:
    settings = _settings()
    _migrate_legacy_cookie_folder_once(settings)
    if settings.contains("general/youtube_auth_source"):
        settings.remove("general/youtube_auth_source")
        settings.sync()

    default_folder = str(
        settings.value(
            "general/default_download_folder",
            str(Path.home() / "Downloads"),
        )
    ).strip()
    if not default_folder:
        default_folder = str(Path.home() / "Downloads")

    cookie_folder = str(settings.value("general/cookie_folder", "") or "").strip()

    collision_mode = str(
        settings.value(
            "general/file_collision_mode",
            FILE_COLLISION_NUMBERED,
        )
    ).strip().lower()
    if collision_mode not in FILE_COLLISION_MODES:
        collision_mode = FILE_COLLISION_NUMBERED

    return GeneralPreferences(
        default_download_folder=default_folder,
        cookie_folder=cookie_folder,
        restore_queue_on_start=_read_bool(
            settings,
            "general/restore_queue_on_start",
            True,
        ),
        keep_completed_tasks=_read_bool(
            settings,
            "general/keep_completed_tasks",
            True,
        ),
        confirm_close_during_download=_read_bool(
            settings,
            "general/confirm_close_during_download",
            True,
        ),
        notify_queue_complete=_read_bool(
            settings,
            "general/notify_queue_complete",
            True,
        ),
        notify_completion_sound=_read_bool(
            settings,
            "general/notify_completion_sound",
            False,
        ),
        minimize_to_tray_on_close=_read_bool(
            settings,
            "general/minimize_to_tray_on_close",
            False,
        ),
        start_with_windows=_read_bool(
            settings,
            "general/start_with_windows",
            False,
        ),
        file_collision_mode=collision_mode,
    )


def save_general_preferences(preferences: GeneralPreferences) -> None:
    settings = _settings()
    settings.setValue(
        "general/default_download_folder",
        preferences.default_download_folder,
    )
    settings.setValue("general/cookie_folder", preferences.cookie_folder)
    settings.remove("general/youtube_auth_source")
    settings.setValue(
        "general/restore_queue_on_start",
        preferences.restore_queue_on_start,
    )
    settings.setValue(
        "general/keep_completed_tasks",
        preferences.keep_completed_tasks,
    )
    settings.setValue(
        "general/confirm_close_during_download",
        preferences.confirm_close_during_download,
    )
    settings.setValue(
        "general/notify_queue_complete",
        preferences.notify_queue_complete,
    )
    settings.setValue(
        "general/notify_completion_sound",
        preferences.notify_completion_sound,
    )
    settings.setValue(
        "general/minimize_to_tray_on_close",
        preferences.minimize_to_tray_on_close,
    )
    settings.setValue(
        "general/start_with_windows",
        preferences.start_with_windows,
    )
    collision_mode = preferences.file_collision_mode
    if collision_mode not in FILE_COLLISION_MODES:
        collision_mode = FILE_COLLISION_NUMBERED
    settings.setValue(
        "general/file_collision_mode",
        collision_mode,
    )
    settings.sync()


def resolved_download_directory() -> Path:
    preferences = load_general_preferences()
    folder = Path(preferences.default_download_folder).expanduser()
    if not str(folder).strip():
        return Path.home() / "Downloads"
    return folder
