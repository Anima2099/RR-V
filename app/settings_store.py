from __future__ import annotations


from PySide6.QtCore import QSettings

from app.paths import RRV_DATA_DIR


SETTINGS_PATH = RRV_DATA_DIR / "settings.ini"
_MIGRATION_MARKER = RRV_DATA_DIR / ".registry_settings_migrated_v0110"


def get_settings() -> QSettings:
    RRV_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return QSettings(str(SETTINGS_PATH), QSettings.Format.IniFormat)


def _legacy_settings() -> QSettings:
    settings = QSettings(
        QSettings.Format.NativeFormat,
        QSettings.Scope.UserScope,
        "RR-V",
        "RR-V",
    )
    # RR-V/RR-V 애플리케이션 키만 다룬다. 조직 레벨 fallback 값은
    # 이관하거나 지우지 않는다.
    settings.setFallbacksEnabled(False)
    return settings


def _ensure_no_settings_error(settings: QSettings, action: str) -> None:
    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        raise OSError(f"RR-V settings {action} failed: {settings.status()}")


def _verify_migrated_values(values: dict[str, object]) -> None:
    """settings.ini를 다시 열어 이관 값이 실제로 저장됐는지 확인한다."""

    verified = get_settings()
    _ensure_no_settings_error(verified, "verification")

    for key, expected in values.items():
        if not verified.contains(key):
            raise OSError(f"RR-V settings migration verification failed: missing {key}")
        if verified.value(key) != expected:
            raise OSError(f"RR-V settings migration verification failed: mismatch {key}")


def _clear_legacy_registry(legacy: QSettings) -> None:
    """검증이 끝난 RR-V/RR-V Native QSettings 값만 제거한다."""

    legacy.clear()
    _ensure_no_settings_error(legacy, "legacy registry cleanup")
    if legacy.allKeys():
        raise OSError("RR-V legacy registry cleanup verification failed")


def _write_migration_marker() -> None:
    _MIGRATION_MARKER.write_text(
        "RR-V 1.0.1 one-time native QSettings migration and cleanup completed.\n",
        encoding="utf-8",
    )


def initialize_settings_store() -> int:
    """구형 Native QSettings를 마지막 한 번 이관한 뒤 원본을 정리한다.

    - 현재 settings.ini가 없다면 구형 레지스트리 값을 복사하고, 파일을 다시
      열어 값이 저장됐는지 검증한 뒤 레지스트리 원본을 지운다.
    - settings.ini가 이미 있다면 현재 파일을 우선하며 구형 값을 덮어쓰지
      않는다. 파일 접근이 정상인지 확인한 뒤 남아 있는 구형 레지스트리만
      정리한다.
    - 어떤 단계라도 실패하면 완료 표식을 만들지 않아 다음 실행에서 다시
      정리할 수 있게 한다.
    """

    RRV_DATA_DIR.mkdir(parents=True, exist_ok=True)
    if _MIGRATION_MARKER.exists():
        return 0

    legacy = _legacy_settings()
    _ensure_no_settings_error(legacy, "legacy registry read")
    legacy_keys = legacy.allKeys()
    migrated_count = 0

    if SETTINGS_PATH.exists():
        # settings.ini가 이미 존재하면 더 최신인 현재 저장소를 절대 레거시
        # 값으로 덮어쓰지 않는다. 정상적으로 읽을 수 있는지만 확인한다.
        current = get_settings()
        _ensure_no_settings_error(current, "current store check")
    elif legacy_keys:
        values = {key: legacy.value(key) for key in legacy_keys}
        target = get_settings()
        for key, value in values.items():
            target.setValue(key, value)
        _ensure_no_settings_error(target, "migration write")
        _verify_migrated_values(values)
        migrated_count = len(values)

    if legacy_keys:
        _clear_legacy_registry(legacy)

    _write_migration_marker()
    return migrated_count
