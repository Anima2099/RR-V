from __future__ import annotations

import base64
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QSettings

from app.paths import RRV_BACKUPS_DIR
from app.preset_store import (
    PresetLibrary,
    export_preset_payload,
    import_preset_payload,
    reset_preset_library,
)
from app.settings_store import get_settings


BACKUP_FORMAT = "RR-V-settings-backup"
BACKUP_VERSION = 1


def _settings() -> QSettings:
    return get_settings()


def _encode(value: Any) -> Any:
    if isinstance(value, QByteArray):
        return {
            "__type__": "QByteArray",
            "base64": base64.b64encode(bytes(value)).decode("ascii"),
        }
    if isinstance(value, bytes):
        return {
            "__type__": "bytes",
            "base64": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, tuple):
        return {"__type__": "tuple", "items": [_encode(item) for item in value]}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _encode(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"__type__": "string", "value": str(value)}


def _decode(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if not isinstance(value, dict) or "__type__" not in value:
        if isinstance(value, dict):
            return {key: _decode(item) for key, item in value.items()}
        return value

    kind = value.get("__type__")
    if kind == "QByteArray":
        encoded = str(value.get("base64", ""))
        return QByteArray(base64.b64decode(encoded, validate=True))
    if kind == "bytes":
        encoded = str(value.get("base64", ""))
        return base64.b64decode(encoded, validate=True)
    if kind == "tuple":
        return tuple(_decode(item) for item in value.get("items", []))
    if kind == "string":
        return str(value.get("value", ""))
    return value


def _prepare_restore_payload(
    payload: object,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not isinstance(payload, dict):
        raise ValueError("설정 백업 파일의 최상위 형식이 올바르지 않습니다.")
    if payload.get("format") != BACKUP_FORMAT:
        raise ValueError("RR-V 설정 백업 파일이 아닙니다.")
    if int(payload.get("version", 0)) != BACKUP_VERSION:
        raise ValueError("지원하지 않는 설정 백업 버전입니다.")

    raw_settings = payload.get("settings")
    if not isinstance(raw_settings, dict):
        raise ValueError("백업 안의 설정 데이터가 올바르지 않습니다.")

    decoded_settings = {
        str(key): _decode(value)
        for key, value in raw_settings.items()
    }

    raw_presets = payload.get("download_presets")
    if raw_presets is not None and not isinstance(raw_presets, dict):
        raise ValueError("백업 안의 다운로드 프리셋 데이터가 올바르지 않습니다.")
    if isinstance(raw_presets, dict):
        # 실제 파일을 바꾸기 전에 프리셋 구조 전체를 메모리에서 검증한다.
        PresetLibrary.from_payload(raw_presets)

    return decoded_settings, raw_presets


def create_backup(destination: Path | None = None, *, automatic: bool = False) -> Path:
    RRV_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    if destination is None:
        prefix = "auto" if automatic else "manual"
        destination = RRV_BACKUPS_DIR / f"{prefix}_{now:%Y%m%d_%H%M%S}.json"

    settings = _settings()
    payload = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "created_at": now.isoformat(timespec="seconds"),
        "settings": {
            key: _encode(settings.value(key))
            for key in settings.allKeys()
        },
        # 1.1.0부터 사용자 다운로드 프리셋은 settings.ini와 분리된 JSON으로
        # 관리한다. 기존 백업 형식 버전은 유지하되 선택 필드로 함께 담아
        # 1.0.x 백업과도 계속 호환한다.
        "download_presets": export_preset_payload(),
    }

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(destination.name + ".tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())

        # 완성된 임시 파일을 다시 읽어 디코딩과 프리셋 구조까지 검증한 뒤
        # 최종 파일로 교체한다. 중간 실패 시 기존 백업 파일은 그대로 남는다.
        verified = json.loads(temp_path.read_text(encoding="utf-8"))
        _prepare_restore_payload(verified)
        os.replace(temp_path, destination)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass

    return destination


def restore_backup(source: Path) -> int:
    payload = json.loads(source.read_text(encoding="utf-8"))
    decoded_settings, raw_presets = _prepare_restore_payload(payload)

    settings = _settings()
    previous_settings = {
        key: settings.value(key)
        for key in settings.allKeys()
    }
    previous_presets = export_preset_payload()

    try:
        settings.clear()
        for key, value in decoded_settings.items():
            settings.setValue(key, value)
        settings.sync()

        if isinstance(raw_presets, dict):
            import_preset_payload(raw_presets)
        else:
            # 1.0.x 백업에는 별도 프리셋 파일이 없으므로 복구된 downloads/* 값을
            # 기준으로 1.1.0 사용자 프리셋을 다시 이관한다.
            reset_preset_library()
    except Exception:
        # 복구 적용 중 어느 단계에서든 실패하면 시작 전 상태로 되돌린다.
        # 프리셋 복구가 legacy downloads/* 값을 쓸 수 있으므로 프리셋을 먼저
        # 되돌리고 settings.ini 스냅샷을 마지막에 복원한다.
        try:
            import_preset_payload(previous_presets)
        finally:
            settings.clear()
            for key, value in previous_settings.items():
                settings.setValue(key, value)
            settings.sync()
        raise

    return len(decoded_settings) + 1


def reset_scope(scope: str) -> int:
    settings = _settings()
    keys = settings.allKeys()

    if scope == "ui":
        prefixes = ("window/", "batch_add/", "appearance/")
    elif scope == "media":
        prefixes = ("converter/", "thumbnail/", "snapshot/", "subtitle/")
    elif scope == "downloads":
        prefixes = ("downloads/",)
    elif scope == "all":
        prefixes = ("",)
    else:
        raise ValueError("알 수 없는 초기화 범위입니다.")

    removed = 0
    for key in keys:
        if any(key.startswith(prefix) for prefix in prefixes):
            settings.remove(key)
            removed += 1
    settings.sync()

    if scope in {"downloads", "all"}:
        reset_preset_library()
        removed += 1

    return removed


def latest_backup() -> Path | None:
    if not RRV_BACKUPS_DIR.exists():
        return None
    candidates = [path for path in RRV_BACKUPS_DIR.glob("*.json") if path.is_file()]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def ensure_daily_auto_backup() -> Path | None:
    RRV_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    today_prefix = f"auto_{datetime.now():%Y%m%d}_"
    if any(path.name.startswith(today_prefix) for path in RRV_BACKUPS_DIR.glob("auto_*.json")):
        return None

    path = create_backup(automatic=True)
    autos = sorted(
        (item for item in RRV_BACKUPS_DIR.glob("auto_*.json") if item.is_file()),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for old in autos[5:]:
        try:
            old.unlink()
        except OSError:
            pass
    return path
