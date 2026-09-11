from __future__ import annotations

from app.settings_store import get_settings


_KEY_PREFIX = "downloads/chapter_delete_original"


def load_delete_original_after_split(preset_id: str) -> bool:
    """프리셋별 '챕터 분할 성공 후 원본 삭제' 값을 읽는다.

    기존 프리셋 파일 형식은 그대로 두고 1.4의 부가 옵션만 QSettings에 보존한다.
    값이 없거나 프리셋 ID가 비어 있으면 안전한 기본값(False)을 사용한다.
    """

    key = str(preset_id).strip()
    if not key:
        return False
    value = get_settings().value(f"{_KEY_PREFIX}/{key}", False)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def save_delete_original_after_split(preset_id: str, enabled: bool) -> None:
    key = str(preset_id).strip()
    if not key:
        return
    settings = get_settings()
    settings.setValue(f"{_KEY_PREFIX}/{key}", bool(enabled))
    settings.sync()
