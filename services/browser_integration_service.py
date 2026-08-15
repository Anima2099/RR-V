from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys

from app.settings_store import get_settings
from app.paths import (
    PROJECT_ROOT,
    RRV_BROWSER_EXTENSION_DIR,
    RRV_BROWSER_INTEGRATION_DIR,
    bootstrap_browser_extension,
)


HOST_NAME = "com.rrv.browser_bridge"
DEV_EXTENSION_ID = "jpnikadifjddeldmjkenhoeechklnjnk"
DEV_EXTENSION_ORIGIN = f"chrome-extension://{DEV_EXTENSION_ID}/"
_NATIVE_MANIFEST_PATH = RRV_BROWSER_INTEGRATION_DIR / f"{HOST_NAME}.json"

_CHROME_KEY = rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}"
_EDGE_KEY = rf"Software\Microsoft\Edge\NativeMessagingHosts\{HOST_NAME}"

BROWSER_SEND_QUEUE_ONLY = "queue_only"
BROWSER_SEND_AUTO_DOWNLOAD = "auto_download"
_BROWSER_SEND_BEHAVIOR_KEY = "integration/browser_extension_send_behavior"
_BROWSER_SEND_BEHAVIORS = {
    BROWSER_SEND_QUEUE_ONLY,
    BROWSER_SEND_AUTO_DOWNLOAD,
}


class BrowserIntegrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserIntegrationStatus:
    supported: bool
    host_executable: Path | None
    chrome_registered: bool
    edge_registered: bool
    manifest_path: Path
    extension_dir: Path

    @property
    def registered(self) -> bool:
        return self.chrome_registered or self.edge_registered


def is_browser_integration_supported() -> bool:
    return os.name == "nt"


def load_browser_send_behavior() -> str:
    """브라우저 확장으로 받은 URL의 기본 처리 방식을 읽는다.

    1.1.0과 동일한 동작을 유지하기 위해 설정이 없거나 손상된 경우에는
    항상 '대기열에 추가만'을 기본값으로 사용한다.
    """
    settings = get_settings()
    value = str(
        settings.value(
            _BROWSER_SEND_BEHAVIOR_KEY,
            BROWSER_SEND_QUEUE_ONLY,
        )
        or ""
    ).strip().lower()
    if value not in _BROWSER_SEND_BEHAVIORS:
        return BROWSER_SEND_QUEUE_ONLY
    return value


def save_browser_send_behavior(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in _BROWSER_SEND_BEHAVIORS:
        normalized = BROWSER_SEND_QUEUE_ONLY
    settings = get_settings()
    settings.setValue(_BROWSER_SEND_BEHAVIOR_KEY, normalized)
    settings.sync()
    return normalized


def resolve_host_executable() -> Path | None:
    """Native Messaging host로 실행할 현재 RR-V.exe를 찾는다."""
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        return executable if executable.is_file() else None

    candidates = (
        PROJECT_ROOT / "dist" / "RR-V.exe",
        PROJECT_ROOT / "RR-V.exe",
    )
    source_marker = Path(__file__).resolve().parent / "native_messaging_host.py"
    marker_mtime = source_marker.stat().st_mtime if source_marker.is_file() else 0.0
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            # 현재 소스보다 오래된 EXE를 실수로 Native Host로 등록하지 않는다.
            # 새 빌드가 끝나면 버튼이 자동으로 활성화된다.
            if candidate.stat().st_mtime + 1.0 < marker_mtime:
                continue
        except OSError:
            continue
        return candidate.resolve()
    return None


def browser_integration_status() -> BrowserIntegrationStatus:
    host_executable = resolve_host_executable()
    manifest_value = str(_NATIVE_MANIFEST_PATH.resolve())
    return BrowserIntegrationStatus(
        supported=is_browser_integration_supported(),
        host_executable=host_executable,
        chrome_registered=_read_registry_value(_CHROME_KEY) == manifest_value,
        edge_registered=_read_registry_value(_EDGE_KEY) == manifest_value,
        manifest_path=_NATIVE_MANIFEST_PATH,
        extension_dir=RRV_BROWSER_EXTENSION_DIR,
    )


def register_browser_integration() -> BrowserIntegrationStatus:
    if not is_browser_integration_supported():
        raise BrowserIntegrationError("브라우저 연결은 Windows에서만 사용할 수 있습니다.")

    # 연결 등록 버튼을 누르는 순간에도 번들 안 최신 확장 파일을 다시 동기화한다.
    bootstrap_browser_extension()

    host_executable = resolve_host_executable()
    if host_executable is None:
        raise BrowserIntegrationError(
            "브라우저가 실행할 RR-V.exe를 찾지 못했습니다.\n"
            "먼저 현재 소스로 RR-V.exe를 빌드한 뒤 다시 시도해 주세요."
        )
    if not RRV_BROWSER_EXTENSION_DIR.is_dir():
        raise BrowserIntegrationError(
            "RR-V 브라우저 확장 프로그램 폴더를 찾지 못했습니다."
        )

    _NATIVE_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": HOST_NAME,
        "description": "RR-V Browser Connector",
        "path": str(host_executable),
        "type": "stdio",
        "allowed_origins": [DEV_EXTENSION_ORIGIN],
    }
    try:
        _NATIVE_MANIFEST_PATH.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_value = str(_NATIVE_MANIFEST_PATH.resolve())
        _write_registry_value(_CHROME_KEY, manifest_value)
        _write_registry_value(_EDGE_KEY, manifest_value)
    except OSError as error:
        raise BrowserIntegrationError(str(error)) from error

    return browser_integration_status()


def unregister_browser_integration() -> BrowserIntegrationStatus:
    if not is_browser_integration_supported():
        return browser_integration_status()

    try:
        _delete_registry_key(_CHROME_KEY)
        _delete_registry_key(_EDGE_KEY)
        if _NATIVE_MANIFEST_PATH.is_file():
            _NATIVE_MANIFEST_PATH.unlink()
    except OSError as error:
        raise BrowserIntegrationError(str(error)) from error
    return browser_integration_status()


def sync_browser_integration_registration() -> None:
    """이미 등록된 경우 RR-V.exe 이동 뒤에도 현재 위치로 host manifest를 갱신한다."""
    if not is_browser_integration_supported():
        return
    status = browser_integration_status()
    if not status.registered:
        return
    if status.host_executable is None:
        return
    register_browser_integration()


def _read_registry_value(key_path: str) -> str | None:
    if not is_browser_integration_supported():
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            key_path,
            0,
            winreg.KEY_QUERY_VALUE,
        ) as key:
            value, value_type = winreg.QueryValueEx(key, "")
    except FileNotFoundError:
        return None
    except OSError:
        return None
    if value_type not in {winreg.REG_SZ, winreg.REG_EXPAND_SZ}:
        return None
    return str(value)


def _write_registry_value(key_path: str, value: str) -> None:
    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        key_path,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, value)


def _delete_registry_key(key_path: str) -> None:
    import winreg

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
    except FileNotFoundError:
        pass
