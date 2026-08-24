from __future__ import annotations

import os
from pathlib import Path
import re

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from app.paths import RRV_LOCAL_DIR, WARM_SAGE_THEME_PATH
from app.settings_store import get_settings


THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_MODES = {THEME_LIGHT, THEME_DARK}
THEME_SETTINGS_KEY = "appearance/theme"
_DARK_ICON_COLOR = "#B6C0BA"
_DARK_ICON_CACHE_DIR = RRV_LOCAL_DIR / "theme-icons"

_ACTIVE_THEME_MODE: str | None = None


def _normalize_theme_mode(value: object) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in THEME_MODES else THEME_LIGHT


def load_theme_preference() -> str:
    settings = get_settings()
    return _normalize_theme_mode(settings.value(THEME_SETTINGS_KEY, THEME_LIGHT))


def save_theme_preference(mode: str) -> str:
    normalized = _normalize_theme_mode(mode)
    settings = get_settings()
    settings.setValue(THEME_SETTINGS_KEY, normalized)
    settings.sync()
    return normalized


def initialize_active_theme() -> str:
    global _ACTIVE_THEME_MODE
    _ACTIVE_THEME_MODE = load_theme_preference()
    _activate_theme_icon_paths()
    return _ACTIVE_THEME_MODE


def active_theme_mode() -> str:
    return _ACTIVE_THEME_MODE or THEME_LIGHT


def active_theme_path() -> Path:
    # Light QSS를 유일한 selector 기준본으로 유지하고 Dark는 실행 시 색상만 변환한다.
    return WARM_SAGE_THEME_PATH


def themed_icon_path(light_icon_path: Path) -> Path:
    if active_theme_mode() != THEME_DARK or light_icon_path.suffix.lower() != ".svg":
        return light_icon_path

    try:
        source = light_icon_path.read_text(encoding="utf-8")
        dark_source = re.sub(
            r"#[0-9A-Fa-f]{6}",
            _DARK_ICON_COLOR,
            source,
        )
        _DARK_ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        candidate = _DARK_ICON_CACHE_DIR / light_icon_path.name
        expected = dark_source.encode("utf-8")
        if not candidate.is_file() or candidate.read_bytes() != expected:
            temporary = candidate.with_name(candidate.name + ".rrv-update")
            temporary.write_bytes(expected)
            os.replace(temporary, candidate)
        return candidate
    except OSError:
        return light_icon_path


def _activate_theme_icon_paths() -> None:
    """UI 모듈이 import되기 전에 app.paths의 SVG 경로를 현재 테마에 맞춘다."""
    if active_theme_mode() != THEME_DARK:
        return

    import app.paths as paths

    names = (
        "EXPAND_ICON_PATH",
        "COLLAPSE_ICON_PATH",
        "DRAG_ICON_PATH",
        "RETRY_ICON_PATH",
        "COPY_ICON_PATH",
        "MORE_ICON_PATH",
        "CLOSE_ICON_PATH",
        "STOP_ICON_PATH",
        "FOLDER_ICON_PATH",
        "SPIN_UP_ICON_PATH",
        "SPIN_DOWN_ICON_PATH",
    )
    for name in names:
        light_path = getattr(paths, name, None)
        if isinstance(light_path, Path):
            setattr(paths, name, themed_icon_path(light_path))


def apply_active_palette(app: QApplication) -> None:
    if active_theme_mode() != THEME_DARK:
        return

    palette = QPalette(app.palette())
    palette.setColor(QPalette.ColorRole.Window, QColor("#202723"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#E2E7E3"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#252D29"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#323B36"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#323B36"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#E2E7E3"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#E2E7E3"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#323B36"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#E2E7E3"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#F7FAF8"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#7EA2B3"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#202723"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#98A49D"))
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor("#8C9891"),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor("#8C9891"),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor("#8C9891"),
    )
    app.setPalette(palette)
