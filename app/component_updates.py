from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.constants import APP_VERSION
from app.settings_store import get_settings
from app.tool_manager import inspect_tools


YTDLP_LATEST_API = "https://api.github.com/repos/yt-dlp/yt-dlp-nightly-builds/releases/latest"
YTDLP_RELEASES_PAGE = "https://github.com/yt-dlp/yt-dlp-nightly-builds/releases"
FFMPEG_GYAN_VERSION_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-git-essentials.7z.ver"
FFMPEG_GYAN_PAGE = "https://www.gyan.dev/ffmpeg/builds/"

_UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
_LAST_CHECK_KEY = "updates/last_component_check_epoch"

_YTDLP_VERSION_RE = re.compile(r"\d{4}\.\d{2}\.\d{2}(?:\.\d{6})?")
_FFMPEG_GIT_VERSION_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}-git-[0-9a-f]+",
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


def _mark_check_attempt() -> None:
    settings = get_settings()
    settings.setValue(_LAST_CHECK_KEY, time.time())
    settings.sync()


def update_check_due() -> bool:
    last_check = _read_last_check_epoch()
    if last_check <= 0:
        return True
    return time.time() - last_check >= _UPDATE_CHECK_INTERVAL_SECONDS


def _fetch_text(url: str, *, accept: str = "text/plain") -> str:
    request = Request(
        url,
        headers={
            "User-Agent": f"RR-V/{APP_VERSION}",
            "Accept": accept,
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(request, timeout=8) as response:
        data = response.read(256 * 1024)
    return data.decode("utf-8", errors="replace").strip()


def _installed_versions() -> dict[str, str]:
    return {status.key: status.version for status in inspect_tools()}


def _normalize_ytdlp_version(value: str) -> str:
    match = _YTDLP_VERSION_RE.search(value)
    return match.group(0) if match else value.strip()


def _normalize_ffmpeg_version(value: str) -> str:
    match = _FFMPEG_GIT_VERSION_RE.search(value)
    return match.group(0) if match else value.strip()


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
        latest_text = _fetch_text(FFMPEG_GYAN_VERSION_URL)
        latest = _normalize_ffmpeg_version(latest_text)
        if not _FFMPEG_GIT_VERSION_RE.fullmatch(latest):
            raise ValueError("Gyan Git Essentials 버전 형식을 확인하지 못했습니다.")

        current_normalized = _normalize_ffmpeg_version(current)
        if _FFMPEG_GIT_VERSION_RE.fullmatch(current_normalized):
            update_available = current_normalized.lower() != latest.lower()
        else:
            # RR-V의 공식 FFmpeg 채널은 Gyan Git Master Essentials다. 다른 형식의
            # 빌드가 설치되어 있으면 최신 공식 채널로 교체할 수 있게 안내한다.
            update_available = True

        return ComponentVersionCheck(
            key="ffmpeg",
            label="FFmpeg / FFprobe · Gyan Git Essentials",
            current=current_normalized,
            latest=latest,
            update_available=update_available,
            source_url=FFMPEG_GYAN_PAGE,
        )
    except (OSError, HTTPError, URLError, ValueError) as error:
        return ComponentVersionCheck(
            key="ffmpeg",
            label="FFmpeg / FFprobe · Gyan Git Essentials",
            current=_normalize_ffmpeg_version(current),
            latest="확인 실패",
            update_available=None,
            source_url=FFMPEG_GYAN_PAGE,
            error=str(error),
        )


def check_component_updates(*, force: bool = False) -> ComponentUpdateCheckResult:
    if not force and not update_check_due():
        return ComponentUpdateCheckResult(components=(), skipped=True)

    installed = _installed_versions()
    try:
        ytdlp = _check_ytdlp(installed.get("ytdlp", "없음"))
        ffmpeg = _check_ffmpeg(installed.get("ffmpeg", "없음"))
        return ComponentUpdateCheckResult(components=(ytdlp, ffmpeg))
    finally:
        # 인터넷이 끊겨 있어도 실행할 때마다 같은 서버를 반복해서 두드리지 않는다.
        # 사용자는 설정 화면의 '지금 업데이트 확인'으로 언제든 강제 재확인할 수 있다.
        _mark_check_attempt()
