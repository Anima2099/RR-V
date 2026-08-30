from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from urllib.error import HTTPError, URLError

from app.constants import APP_VERSION
from app.http_client import fetch_https_text
from app.settings_store import get_settings
from app.tool_manager import inspect_tools
from app.tool_sources import (
    FFMPEG_RELEASE_VERSION_URL,
    FFMPEG_RELEASES_PAGE,
    YTDLP_LATEST_API,
    YTDLP_RELEASES_PAGE,
)


_UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
_LAST_CHECK_KEY = "updates/last_component_check_epoch"
_LAST_LOCAL_SIGNATURE_KEY = "updates/last_component_local_signature"

_YTDLP_VERSION_RE = re.compile(r"\d{4}\.\d{2}\.\d{2}(?:\.\d{6})?")
_FFMPEG_RELEASE_VERSION_RE = re.compile(
    r"(?<![\d.-])(\d+\.\d+(?:\.\d+)?)(?=[-+\s]|$)",
    re.IGNORECASE,
)


@dataclass(slots=True, frozen=True)
class ComponentVersionCheck:
    key: str
    label: str
    current: str
    latest: str
    update_available: bool | None
    source_url: str
    error: str = ""


@dataclass(slots=True, frozen=True)
class ComponentUpdateCheckResult:
    components: tuple[ComponentVersionCheck, ...]
    skipped: bool = False
    installed_statuses: tuple[object, ...] = ()

    @property
    def updates(self) -> tuple[ComponentVersionCheck, ...]:
        return tuple(
            component
            for component in self.components
            if component.update_available is True
        )

    @property
    def successful_checks(self) -> tuple[ComponentVersionCheck, ...]:
        return tuple(
            component
            for component in self.components
            if component.update_available is not None
        )

    @property
    def errors(self) -> tuple[ComponentVersionCheck, ...]:
        return tuple(component for component in self.components if component.error)


def _read_last_check_epoch() -> float:
    settings = get_settings()
    try:
        return float(settings.value(_LAST_CHECK_KEY, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _read_last_local_signature() -> str:
    settings = get_settings()
    return str(settings.value(_LAST_LOCAL_SIGNATURE_KEY, "") or "").strip()


def _mark_check_attempt(local_signature: str) -> None:
    settings = get_settings()
    settings.setValue(_LAST_CHECK_KEY, time.time())
    settings.setValue(_LAST_LOCAL_SIGNATURE_KEY, local_signature)
    settings.sync()


def update_check_due(local_signature: str) -> bool:
    # 하루 안에 이미 확인했더라도 사용자가 yt-dlp/FFmpeg/FFprobe 파일을 직접
    # 교체했다면 즉시 다시 확인한다. 도구 교체를 캐시가 가리는 일을 막는다.
    if local_signature != _read_last_local_signature():
        return True

    last_check = _read_last_check_epoch()
    if last_check <= 0:
        return True
    return time.time() - last_check >= _UPDATE_CHECK_INTERVAL_SECONDS


def _fetch_text(url: str, *, accept: str = "text/plain") -> str:
    return fetch_https_text(
        url,
        headers={
            "User-Agent": f"RR-V/{APP_VERSION}",
            "Accept": accept,
            "Cache-Control": "no-cache",
        },
        timeout=8,
        max_bytes=256 * 1024,
    )


def _installed_versions(statuses: tuple[object, ...] | None = None) -> dict[str, str]:
    inspected = tuple(inspect_tools()) if statuses is None else statuses
    return {
        str(getattr(status, "key", "")): str(getattr(status, "version", ""))
        for status in inspected
        if str(getattr(status, "key", ""))
    }


def _local_signature(installed: dict[str, str]) -> str:
    # FFmpeg와 FFprobe는 한 쌍으로 관리하므로 둘 중 하나만 달라져도 새 로컬
    # 구성으로 본다. Deno는 이번 자동 확인 대상이 아니므로 제외한다.
    return "|".join(
        (
            installed.get("ytdlp", "없음"),
            installed.get("ffmpeg", "없음"),
            installed.get("ffprobe", "없음"),
        )
    )


def _normalize_ytdlp_version(value: str) -> str:
    match = _YTDLP_VERSION_RE.search(value)
    return match.group(0) if match else value.strip()


def normalize_ffmpeg_release_version(value: str) -> str:
    match = _FFMPEG_RELEASE_VERSION_RE.search(value)
    return match.group(1) if match else value.strip()


def _release_tuple(value: str) -> tuple[int, ...] | None:
    normalized = normalize_ffmpeg_release_version(value)
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", normalized):
        return None
    try:
        return tuple(int(part) for part in normalized.split("."))
    except ValueError:
        return None


def _check_ytdlp(current: str) -> ComponentVersionCheck:
    try:
        payload = json.loads(
            _fetch_text(
                YTDLP_LATEST_API,
                accept="application/vnd.github+json",
            )
        )
        latest = str(payload.get("tag_name") or "").strip().lstrip("v")
        if not latest:
            raise ValueError("최신 Nightly 버전 정보를 찾지 못했습니다.")
        current_normalized = _normalize_ytdlp_version(current)
        latest_normalized = _normalize_ytdlp_version(latest)
        return ComponentVersionCheck(
            key="ytdlp",
            label="yt-dlp Nightly",
            current=current_normalized,
            latest=latest_normalized,
            update_available=(current_normalized != latest_normalized),
            source_url=YTDLP_RELEASES_PAGE,
        )
    except (OSError, HTTPError, URLError, ValueError, json.JSONDecodeError) as error:
        return ComponentVersionCheck(
            key="ytdlp",
            label="yt-dlp Nightly",
            current=_normalize_ytdlp_version(current),
            latest="확인 실패",
            update_available=None,
            source_url=YTDLP_RELEASES_PAGE,
            error=str(error),
        )


def _check_ffmpeg(current: str) -> ComponentVersionCheck:
    try:
        latest_text = _fetch_text(FFMPEG_RELEASE_VERSION_URL)
        latest = normalize_ffmpeg_release_version(latest_text)
        latest_tuple = _release_tuple(latest)
        if latest_tuple is None:
            raise ValueError("FFmpeg Release Essentials 버전 형식을 확인하지 못했습니다.")

        current_normalized = normalize_ffmpeg_release_version(current)
        current_tuple = _release_tuple(current)
        if current_tuple is None:
            # RR-V의 공식 채널은 Release Essentials다. Git Master 등 다른
            # 채널의 빌드는 다음 업데이트에서 Release Essentials로 정리한다.
            update_available = True
        else:
            update_available = current_tuple < latest_tuple

        return ComponentVersionCheck(
            key="ffmpeg",
            label="FFmpeg / FFprobe",
            current=current_normalized,
            latest=latest,
            update_available=update_available,
            source_url=FFMPEG_RELEASES_PAGE,
        )
    except (OSError, HTTPError, URLError, ValueError) as error:
        return ComponentVersionCheck(
            key="ffmpeg",
            label="FFmpeg / FFprobe",
            current=normalize_ffmpeg_release_version(current),
            latest="확인 실패",
            update_available=None,
            source_url=FFMPEG_RELEASES_PAGE,
            error=str(error),
        )


def check_component_updates(*, force: bool = False) -> ComponentUpdateCheckResult:
    # 로컬 실행 도구 검사는 비교적 무거우므로 한 번만 수행한다. 이 스냅샷은
    # 최신 버전 비교뿐 아니라 설정 화면의 현재 버전/무결성 표시에도 재사용한다.
    installed_statuses = tuple(inspect_tools())
    installed = _installed_versions(installed_statuses)
    local_signature = _local_signature(installed)

    if not force and not update_check_due(local_signature):
        return ComponentUpdateCheckResult(
            components=(),
            skipped=True,
            installed_statuses=installed_statuses,
        )

    try:
        ytdlp = _check_ytdlp(installed.get("ytdlp", "없음"))
        ffmpeg = _check_ffmpeg(installed.get("ffmpeg", "없음"))
        return ComponentUpdateCheckResult(
            components=(ytdlp, ffmpeg),
            installed_statuses=installed_statuses,
        )
    finally:
        # 인터넷이 끊겨 있어도 실행할 때마다 같은 서버를 반복해서 두드리지 않는다.
        # 단, 로컬 도구 버전이 바뀌면 24시간 안이어도 다음 실행에서 즉시 재확인한다.
        _mark_check_attempt(local_signature)
