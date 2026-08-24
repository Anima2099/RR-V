from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESOURCES_DIR = PROJECT_ROOT / "resources"
THEMES_DIR = RESOURCES_DIR / "themes"
ICONS_DIR = RESOURCES_DIR / "icons"
DARK_ICONS_DIR = ICONS_DIR / "dark"
BUNDLED_TOOLS_DIR = RESOURCES_DIR / "tools"
BUNDLED_WPC_PROVIDER_DIR = RESOURCES_DIR / "wpc-provider"
BUNDLED_WPC_RUNTIME_DIR = BUNDLED_WPC_PROVIDER_DIR / "runtime"
# PyInstaller onefile에서는 data가 sys._MEIPASS 아래에 풀린다. __file__ 기반
# PROJECT_ROOT도 보통 같은 위치를 가리키지만, 브라우저 확장 업데이트는
# 배포 동기화의 핵심이므로 frozen 환경의 bundle root를 명시적으로 사용한다.
_BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)).resolve()
BUNDLED_BROWSER_EXTENSION_DIR = (
    _BUNDLE_ROOT / "resources" / "browser-extension" / "rrv-chromium"
)
_BROWSER_EXTENSION_FILES = ("manifest.json", "background.js", "RR-V.png", "README.txt")
WPC_PROVIDER_VERSION = "1.1.2"
WARM_SAGE_THEME_PATH = THEMES_DIR / "warm_sage.qss"
WARM_SAGE_DARK_THEME_PATH = THEMES_DIR / "warm_sage_dark.qss"

APPDATA_DIR = Path(os.environ.get("APPDATA", Path.home()))
LOCALAPPDATA_DIR = Path(os.environ.get("LOCALAPPDATA", APPDATA_DIR))

# 사용자 설정/로그처럼 백업할 가치가 있는 데이터는 Roaming에 둔다.
RRV_DATA_DIR = APPDATA_DIR / "RR-V"
RRV_LOGS_DIR = RRV_DATA_DIR / "logs"
RRV_BACKUPS_DIR = RRV_DATA_DIR / "backups"
RRV_YOUTUBE_AUTH_DIR = RRV_DATA_DIR / "auth"
RRV_YOUTUBE_AUTH_COOKIE_PATH = RRV_YOUTUBE_AUTH_DIR / "youtube.txt"
RRV_YOUTUBE_AUTH_RESULT_PATH = RRV_YOUTUBE_AUTH_DIR / "last_login_result.txt"
RRV_INSTAGRAM_AUTH_COOKIE_PATH = RRV_YOUTUBE_AUTH_DIR / "instagram.txt"
RRV_INSTAGRAM_AUTH_RESULT_PATH = RRV_YOUTUBE_AUTH_DIR / "last_instagram_login_result.txt"
RRV_TIKTOK_AUTH_COOKIE_PATH = RRV_YOUTUBE_AUTH_DIR / "tiktok.txt"
RRV_TIKTOK_AUTH_RESULT_PATH = RRV_YOUTUBE_AUTH_DIR / "last_tiktok_login_result.txt"

# FFmpeg/yt-dlp처럼 크고 교체 가능한 실행 도구는 Local에 둔다.
RRV_LOCAL_DIR = LOCALAPPDATA_DIR / "RR-V"
RRV_TOOLS_DIR = RRV_LOCAL_DIR / "tools"
RRV_WPC_PROVIDER_DIR = RRV_LOCAL_DIR / "wpc-provider"
RRV_YOUTUBE_AUTH_SESSION_DIR = RRV_LOCAL_DIR / "auth"
RRV_BROWSER_EXTENSION_DIR = RRV_LOCAL_DIR / "browser-extension"
RRV_BROWSER_INTEGRATION_DIR = RRV_LOCAL_DIR / "browser-integration"
RRV_EXTERNAL_URL_ENDPOINT_PATH = RRV_LOCAL_DIR / "external-url-endpoint.json"
RRV_WPC_RUNTIME_DIR = RRV_WPC_PROVIDER_DIR / "runtime"
_WPC_PROVIDER_MARKER = RRV_WPC_PROVIDER_DIR / ".rrv_wpc_version"

PERFORMANCE_LOG_PATH = RRV_LOGS_DIR / "performance.log"
DOWNLOAD_LOG_PATH = RRV_LOGS_DIR / "download.log"
DOWNLOAD_TASK_LOGS_DIR = RRV_LOGS_DIR / "downloads"
CONVERTER_LOG_PATH = RRV_LOGS_DIR / "converter.log"
CONVERSION_TASK_LOGS_DIR = RRV_LOGS_DIR / "conversions"
THUMBNAIL_LOG_PATH = RRV_LOGS_DIR / "thumbnail.log"
THUMBNAIL_TASK_LOGS_DIR = RRV_LOGS_DIR / "thumbnails"
SNAPSHOT_LOG_PATH = RRV_LOGS_DIR / "snapshot.log"
SNAPSHOT_TASK_LOGS_DIR = RRV_LOGS_DIR / "snapshots"
SUBTITLE_LOG_PATH = RRV_LOGS_DIR / "subtitle.log"
SUBTITLE_TASK_LOGS_DIR = RRV_LOGS_DIR / "subtitles"
QUEUE_PATH = RRV_DATA_DIR / "download_queue.json"
QUEUE_BACKUP_PATH = RRV_DATA_DIR / "download_queue.backup.json"
PRESETS_PATH = RRV_DATA_DIR / "download_presets.json"
PRESETS_BACKUP_PATH = RRV_DATA_DIR / "download_presets.backup.json"
QUEUE_THUMBNAILS_DIR = RRV_DATA_DIR / "queue_thumbnails"

# v0.11.0에서 딱 한 번만 기존 RR-VM/RR-HUB 도구를 옮기기 위한 이관 경로다.
# 이관 완료 후 RR-V의 실행 도구 탐색은 RRV_TOOLS_DIR만 사용한다.
_LEGACY_RRV_TOOLS_DIR = RRV_DATA_DIR / "tools"
_LEGACY_RR_HUB_DIR = APPDATA_DIR / "RR-HUB"
_TOOL_MIGRATION_MARKER = RRV_LOCAL_DIR / ".rrhub_migrated_v0110"
_LEGACY_ROAMING_TOOLS_CLEANUP_MARKER = RRV_LOCAL_DIR / ".legacy_roaming_tools_cleaned_v101"
_LEGACY_BGUTIL_PROVIDER_DIR = RRV_LOCAL_DIR / "pot-provider"
_LEGACY_YTDLP_PLUGIN_DIR = RRV_TOOLS_DIR / "yt-dlp-plugins"
_LEGACY_BGUTIL_PLUGIN_PATH = _LEGACY_YTDLP_PLUGIN_DIR / "bgutil-ytdlp-pot-provider.zip"
_LEGACY_BGUTIL_CLEANUP_MARKER = RRV_LOCAL_DIR / ".bgutil_removed_v101"
_LEGACY_AUTH_TEST_DIR = RRV_LOCAL_DIR / "auth-test"
_RUNTIME_TOOL_NAMES = ("yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe", "deno.exe")
_STALE_AUTH_SESSION_MAX_AGE_SECONDS = 24 * 60 * 60

EXPAND_ICON_PATH = ICONS_DIR / "expand.svg"
COLLAPSE_ICON_PATH = ICONS_DIR / "collapse.svg"
DRAG_ICON_PATH = ICONS_DIR / "drag.svg"
RETRY_ICON_PATH = ICONS_DIR / "retry.svg"
COPY_ICON_PATH = ICONS_DIR / "copy.svg"
MORE_ICON_PATH = ICONS_DIR / "more.svg"
CLOSE_ICON_PATH = ICONS_DIR / "close.svg"
STOP_ICON_PATH = ICONS_DIR / "stop.svg"
FOLDER_ICON_PATH = ICONS_DIR / "folder.svg"
SPIN_UP_ICON_PATH = ICONS_DIR / "spin_up.svg"
SPIN_DOWN_ICON_PATH = ICONS_DIR / "spin_down.svg"
APP_ICON_PATH = ICONS_DIR / "RR-V.png"


def ensure_runtime_directories() -> None:
    RRV_DATA_DIR.mkdir(parents=True, exist_ok=True)
    RRV_LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    RRV_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    RRV_WPC_PROVIDER_DIR.mkdir(parents=True, exist_ok=True)
    RRV_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    RRV_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    RRV_YOUTUBE_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    RRV_YOUTUBE_AUTH_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    RRV_BROWSER_EXTENSION_DIR.mkdir(parents=True, exist_ok=True)
    RRV_BROWSER_INTEGRATION_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_TASK_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    CONVERSION_TASK_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    THUMBNAIL_TASK_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_TASK_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    SUBTITLE_TASK_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    QUEUE_THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_legacy_bgutil_once()
    bootstrap_runtime_tools()
    cleanup_legacy_roaming_tools_once()
    cleanup_stale_auth_sessions()
    bootstrap_runtime_wpc_provider()
    bootstrap_browser_extension()
    cleanup_local_test_artifacts()


def bootstrap_runtime_tools() -> tuple[str, ...]:
    """필요한 도구를 RR-V 전용 LocalAppData 폴더에 준비한다.

    우선 배포 EXE에 포함된 기본 도구를 복사한다. v0.11.0 전환 시에는
    기존 RR-HUB가 남아 있을 때 딱 한 번만 누락 도구를 복사한다.
    이후 실행 파일 탐색은 이 위치만 사용하므로 RR-HUB를 지워도 된다.
    """

    RRV_LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    RRV_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []

    for name in _RUNTIME_TOOL_NAMES:
        destination = RRV_TOOLS_DIR / name
        if destination.is_file():
            continue
        bundled = BUNDLED_TOOLS_DIR / name
        if bundled.is_file():
            try:
                shutil.copy2(bundled, destination)
                copied.append(name)
            except OSError:
                pass

    if not _TOOL_MIGRATION_MARKER.exists():
        for name in _RUNTIME_TOOL_NAMES:
            destination = RRV_TOOLS_DIR / name
            if destination.is_file():
                continue
            legacy_candidates = (
                _LEGACY_RRV_TOOLS_DIR / name,
                _LEGACY_RR_HUB_DIR / name,
            )
            for legacy in legacy_candidates:
                if not legacy.is_file():
                    continue
                try:
                    shutil.copy2(legacy, destination)
                    copied.append(name)
                except OSError:
                    pass
                break
        try:
            _TOOL_MIGRATION_MARKER.write_text(
                "RR-V v0.11.0 one-time RR-HUB tool migration completed.\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    return tuple(copied)



def bootstrap_browser_extension() -> tuple[str, ...]:
    """Chrome/Edge 개발용 확장 파일을 LocalAppData에 확실히 동기화한다.

    PyInstaller onefile 안에 포함된 4개 파일만 명시적으로 복사한다. 이전 버전이
    LocalAppData에 남아 있어도 내용이 다르면 임시 파일을 거쳐 원자적으로
    교체하므로 Chrome/Edge Reload 전에 항상 최신 소스를 보게 한다.
    """
    RRV_BROWSER_EXTENSION_DIR.mkdir(parents=True, exist_ok=True)
    if not BUNDLED_BROWSER_EXTENSION_DIR.is_dir():
        return ()

    copied: list[str] = []
    for name in _BROWSER_EXTENSION_FILES:
        source = BUNDLED_BROWSER_EXTENSION_DIR / name
        if not source.is_file():
            continue
        destination = RRV_BROWSER_EXTENSION_DIR / name
        temporary = destination.with_name(destination.name + ".rrv-update")
        try:
            source_bytes = source.read_bytes()
            if destination.is_file() and destination.read_bytes() == source_bytes:
                continue
            temporary.write_bytes(source_bytes)
            try:
                shutil.copystat(source, temporary)
            except OSError:
                pass
            os.replace(temporary, destination)
            copied.append(name)
        except OSError:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass
            continue
    return tuple(copied)

def cleanup_legacy_roaming_tools_once() -> bool:
    """이관이 끝난 Roaming의 구형 도구 복사본을 한 번 정리한다.

    현재 LocalAppData에 필수 실행 도구 4개가 모두 준비된 경우에만, RR-V가
    더 이상 사용하지 않는 Roaming\\RR-V\\tools 폴더를 제거한다.
    """
    if _LEGACY_ROAMING_TOOLS_CLEANUP_MARKER.exists():
        return False
    if not all((RRV_TOOLS_DIR / name).is_file() for name in _RUNTIME_TOOL_NAMES):
        return False

    removed = False
    if _LEGACY_RRV_TOOLS_DIR.exists():
        try:
            shutil.rmtree(_LEGACY_RRV_TOOLS_DIR)
            removed = True
        except OSError:
            return False

    try:
        _LEGACY_ROAMING_TOOLS_CLEANUP_MARKER.write_text(
            "RR-V 1.0.1 legacy Roaming tool cleanup completed.\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    return removed


def cleanup_legacy_bgutil_once() -> bool:
    """1.0.1에서 사용하지 않는 bgutil provider 잔재를 한 번 제거한다."""
    if _LEGACY_BGUTIL_CLEANUP_MARKER.exists():
        return False

    removed = False
    for path in (_LEGACY_BGUTIL_PROVIDER_DIR, _LEGACY_BGUTIL_PLUGIN_PATH):
        if not path.exists():
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed = True
        except OSError:
            return False

    try:
        _LEGACY_BGUTIL_CLEANUP_MARKER.parent.mkdir(parents=True, exist_ok=True)
        _LEGACY_BGUTIL_CLEANUP_MARKER.write_text(
            "RR-V 1.0.1 legacy bgutil provider cleanup completed.\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    return removed


def cleanup_stale_auth_sessions() -> int:
    """하루 이상 남은 로그인 임시 프로필만 안전하게 정리한다."""
    if not RRV_YOUTUBE_AUTH_SESSION_DIR.exists():
        return 0

    now = time.time()
    removed = 0
    for path in RRV_YOUTUBE_AUTH_SESSION_DIR.iterdir():
        if not path.is_dir() or not path.name.startswith("session_"):
            continue
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        if age < _STALE_AUTH_SESSION_MAX_AGE_SECONDS:
            continue
        try:
            shutil.rmtree(path)
            removed += 1
        except OSError:
            pass
    return removed


def cleanup_local_test_artifacts() -> bool:
    """개발 중에만 사용했던 auth-test 폴더가 남아 있으면 제거한다."""
    if not _LEGACY_AUTH_TEST_DIR.exists():
        return False
    try:
        shutil.rmtree(_LEGACY_AUTH_TEST_DIR)
        return True
    except OSError:
        return False


def bootstrap_runtime_wpc_provider() -> bool:
    """검증된 WPC provider 런타임을 LocalAppData에 준비한다."""
    bundled_runtime = BUNDLED_WPC_RUNTIME_DIR
    if not bundled_runtime.is_dir():
        return False

    current_marker = ""
    try:
        current_marker = _WPC_PROVIDER_MARKER.read_text(encoding="utf-8").strip()
    except OSError:
        pass

    required_paths = (
        RRV_WPC_RUNTIME_DIR / "yt_dlp_plugins" / "extractor" / "getpot_wpc.py",
        RRV_WPC_RUNTIME_DIR / "nodriver" / "__init__.py",
    )
    if current_marker == WPC_PROVIDER_VERSION and all(path.is_file() for path in required_paths):
        return False

    temporary = RRV_WPC_PROVIDER_DIR.with_name(RRV_WPC_PROVIDER_DIR.name + ".rrv-update")
    backup = RRV_WPC_PROVIDER_DIR.with_name(RRV_WPC_PROVIDER_DIR.name + ".rrv-backup")
    try:
        if temporary.exists():
            shutil.rmtree(temporary)
        if backup.exists():
            shutil.rmtree(backup)

        shutil.copytree(BUNDLED_WPC_PROVIDER_DIR, temporary)
        marker = temporary / ".rrv_wpc_version"
        marker.write_text(WPC_PROVIDER_VERSION + "\n", encoding="utf-8")

        if RRV_WPC_PROVIDER_DIR.exists():
            os.replace(RRV_WPC_PROVIDER_DIR, backup)
        os.replace(temporary, RRV_WPC_PROVIDER_DIR)
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        return True
    except OSError:
        try:
            if RRV_WPC_PROVIDER_DIR.exists() and backup.exists():
                shutil.rmtree(RRV_WPC_PROVIDER_DIR, ignore_errors=True)
                os.replace(backup, RRV_WPC_PROVIDER_DIR)
        except OSError:
            pass
        try:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)
        except OSError:
            pass
        return False


def find_executable(name: str) -> Path | None:
    candidate = RRV_TOOLS_DIR / name
    return candidate if candidate.is_file() else None


def has_bundled_tools() -> bool:
    return all((BUNDLED_TOOLS_DIR / name).is_file() for name in _RUNTIME_TOOL_NAMES)


def restore_bundled_tools() -> tuple[str, ...]:
    restored: list[str] = []
    RRV_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    for name in _RUNTIME_TOOL_NAMES:
        source = BUNDLED_TOOLS_DIR / name
        if not source.is_file():
            continue
        destination = RRV_TOOLS_DIR / name
        temporary = destination.with_name(destination.name + ".rrv-update")
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
            restored.append(name)
        except OSError:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass
    bootstrap_runtime_wpc_provider()
    return tuple(restored)


def wpc_provider_runtime_ready() -> bool:
    return (
        (RRV_WPC_RUNTIME_DIR / "yt_dlp_plugins" / "extractor" / "getpot_wpc.py").is_file()
        and (RRV_WPC_RUNTIME_DIR / "nodriver" / "__init__.py").is_file()
    )
