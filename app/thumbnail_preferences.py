from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings
from app.settings_store import get_settings

from core.thumbnail_models import OUTPUT_NEW_FILE, OUTPUT_OVERWRITE


@dataclass(slots=True)
class ThumbnailPreferences:
    auto_find_image: bool = True
    delete_image_on_success: bool = False
    output_mode: str = OUTPUT_OVERWRITE
    single_expanded: bool = True
    batch_expanded: bool = False
    options_expanded: bool = False


def _settings() -> QSettings:
    return get_settings()


def load_thumbnail_preferences() -> ThumbnailPreferences:
    settings = _settings()
    output_mode = str(
        settings.value("thumbnail/output_mode", OUTPUT_OVERWRITE)
    )
    if output_mode not in {OUTPUT_OVERWRITE, OUTPUT_NEW_FILE}:
        output_mode = OUTPUT_OVERWRITE

    return ThumbnailPreferences(
        auto_find_image=_bool_value(
            settings.value("thumbnail/auto_find_image", True),
            True,
        ),
        delete_image_on_success=_bool_value(
            settings.value("thumbnail/delete_image_on_success", False),
            False,
        ),
        output_mode=output_mode,
        single_expanded=_bool_value(
            settings.value("thumbnail/single_expanded", True),
            True,
        ),
        batch_expanded=_bool_value(
            settings.value("thumbnail/batch_expanded", False),
            False,
        ),
        options_expanded=_bool_value(
            settings.value("thumbnail/options_expanded", False),
            False,
        ),
    )


def save_thumbnail_preferences(preferences: ThumbnailPreferences) -> None:
    settings = _settings()
    settings.setValue(
        "thumbnail/auto_find_image",
        preferences.auto_find_image,
    )
    settings.setValue(
        "thumbnail/delete_image_on_success",
        preferences.delete_image_on_success,
    )
    settings.setValue("thumbnail/output_mode", preferences.output_mode)
    settings.setValue("thumbnail/single_expanded", preferences.single_expanded)
    settings.setValue("thumbnail/batch_expanded", preferences.batch_expanded)
    settings.setValue("thumbnail/options_expanded", preferences.options_expanded)
    settings.sync()


def _bool_value(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
