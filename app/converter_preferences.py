from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path

from PySide6.QtCore import QSettings
from app.settings_store import get_settings


FORMAT_WEBP = "webp"
FORMAT_GIF = "gif"
FORMAT_APNG = "apng"
FORMAT_AVIF = "avif"
SUPPORTED_FORMATS = (FORMAT_WEBP, FORMAT_GIF, FORMAT_APNG, FORMAT_AVIF)

MODE_DIRECT = "direct"
MODE_TARGET = "target"
TARGET_STRATEGY_QUALITY = "quality"
TARGET_STRATEGY_SCALE = "scale"

RESIZE_ORIGINAL = "original"
RESIZE_WIDTH = "width"
RESIZE_HEIGHT = "height"
RESIZE_CUSTOM = "custom"
RESIZE_MODES = {
    RESIZE_ORIGINAL,
    RESIZE_WIDTH,
    RESIZE_HEIGHT,
    RESIZE_CUSTOM,
}

OUTPUT_SOURCE = "source"
OUTPUT_CUSTOM = "custom"


@dataclass(slots=True)
class ConverterFormatPreferences:
    mode: str = MODE_DIRECT
    quality: int = 85
    fps: str = "15"
    resize_mode: str = RESIZE_ORIGINAL
    width: int = 960
    height: int = 540
    target_mb: float = 20.0
    target_strategy: str = TARGET_STRATEGY_QUALITY
    target_attempts: int = 6


@dataclass(slots=True)
class ConverterPreferences:
    last_format: str = FORMAT_WEBP
    output_mode: str = OUTPUT_SOURCE
    output_folder: str = str(Path.home() / "Downloads")
    single_expanded: bool = True
    batch_expanded: bool = False
    settings_expanded: bool = False
    output_expanded: bool = False
    formats: dict[str, ConverterFormatPreferences] = field(
        default_factory=dict
    )


def default_format_preferences(output_format: str) -> ConverterFormatPreferences:
    defaults = {
        FORMAT_WEBP: ConverterFormatPreferences(
            quality=85,
            fps="15",
            width=960,
            height=540,
            target_strategy=TARGET_STRATEGY_QUALITY,
        ),
        FORMAT_GIF: ConverterFormatPreferences(
            quality=80,
            fps="15",
            width=850,
            height=478,
            target_strategy=TARGET_STRATEGY_QUALITY,
        ),
        FORMAT_APNG: ConverterFormatPreferences(
            quality=100,
            fps="15",
            width=850,
            height=478,
            target_strategy=TARGET_STRATEGY_SCALE,
        ),
        FORMAT_AVIF: ConverterFormatPreferences(
            quality=82,
            fps="15",
            width=960,
            height=540,
            target_strategy=TARGET_STRATEGY_QUALITY,
        ),
    }
    return defaults.get(
        output_format,
        ConverterFormatPreferences(),
    )


def default_converter_preferences() -> ConverterPreferences:
    return ConverterPreferences(
        formats={
            output_format: default_format_preferences(output_format)
            for output_format in SUPPORTED_FORMATS
        }
    )


def _settings() -> QSettings:
    return get_settings()


def _coerce_format_preferences(
    output_format: str,
    payload: object,
) -> ConverterFormatPreferences:
    default = default_format_preferences(output_format)
    if not isinstance(payload, dict):
        return default

    mode = str(payload.get("mode", default.mode))
    if mode not in {MODE_DIRECT, MODE_TARGET}:
        mode = default.mode

    resize_mode = str(payload.get("resize_mode", default.resize_mode))
    if resize_mode not in RESIZE_MODES:
        resize_mode = default.resize_mode

    strategy = str(payload.get("target_strategy", default.target_strategy))
    if strategy not in {
        TARGET_STRATEGY_QUALITY,
        TARGET_STRATEGY_SCALE,
    }:
        strategy = default.target_strategy
    if output_format == FORMAT_APNG:
        strategy = TARGET_STRATEGY_SCALE

    fps = str(payload.get("fps", default.fps))
    if fps not in {"원본", "60", "30", "24", "20", "15", "12", "10", "8"}:
        fps = default.fps

    try:
        quality = min(100, max(1, int(payload.get("quality", default.quality))))
    except (TypeError, ValueError):
        quality = default.quality

    try:
        width = min(16384, max(2, int(payload.get("width", default.width))))
    except (TypeError, ValueError):
        width = default.width

    try:
        height = min(16384, max(2, int(payload.get("height", default.height))))
    except (TypeError, ValueError):
        height = default.height

    try:
        target_mb = min(
            2048.0,
            max(0.1, float(payload.get("target_mb", default.target_mb))),
        )
    except (TypeError, ValueError):
        target_mb = default.target_mb

    try:
        target_attempts = min(10, max(3, int(payload.get("target_attempts", default.target_attempts))))
    except (TypeError, ValueError):
        target_attempts = default.target_attempts

    return ConverterFormatPreferences(
        mode=mode,
        quality=quality,
        fps=fps,
        resize_mode=resize_mode,
        width=width,
        height=height,
        target_mb=target_mb,
        target_strategy=strategy,
        target_attempts=target_attempts,
    )



def _bool_value(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

def load_converter_preferences() -> ConverterPreferences:
    settings = _settings()
    defaults = default_converter_preferences()
    raw = settings.value("converter/preferences_json", "")
    if not raw:
        return defaults

    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return defaults

    if not isinstance(payload, dict):
        return defaults

    last_format = str(payload.get("last_format", defaults.last_format)).lower()
    if last_format not in SUPPORTED_FORMATS:
        last_format = defaults.last_format

    output_mode = str(payload.get("output_mode", defaults.output_mode))
    if output_mode not in {OUTPUT_SOURCE, OUTPUT_CUSTOM}:
        output_mode = defaults.output_mode

    output_folder = str(payload.get("output_folder", defaults.output_folder)).strip()
    if not output_folder:
        output_folder = defaults.output_folder

    raw_formats = payload.get("formats", {})
    if not isinstance(raw_formats, dict):
        raw_formats = {}

    return ConverterPreferences(
        last_format=last_format,
        output_mode=output_mode,
        output_folder=output_folder,
        single_expanded=_bool_value(payload.get("single_expanded", True), True),
        batch_expanded=_bool_value(payload.get("batch_expanded", False), False),
        settings_expanded=_bool_value(payload.get("settings_expanded", False), False),
        output_expanded=_bool_value(payload.get("output_expanded", False), False),
        formats={
            output_format: _coerce_format_preferences(
                output_format,
                raw_formats.get(output_format),
            )
            for output_format in SUPPORTED_FORMATS
        },
    )


def save_converter_preferences(preferences: ConverterPreferences) -> None:
    payload = {
        "last_format": preferences.last_format,
        "output_mode": preferences.output_mode,
        "output_folder": preferences.output_folder,
        "single_expanded": preferences.single_expanded,
        "batch_expanded": preferences.batch_expanded,
        "settings_expanded": preferences.settings_expanded,
        "output_expanded": preferences.output_expanded,
        "formats": {
            output_format: asdict(format_preferences)
            for output_format, format_preferences in preferences.formats.items()
            if output_format in SUPPORTED_FORMATS
        },
    }
    settings = _settings()
    settings.setValue(
        "converter/preferences_json",
        json.dumps(payload, ensure_ascii=False),
    )
    settings.sync()
