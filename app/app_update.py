from __future__ import annotations

from dataclasses import dataclass
import json
import re
from urllib.error import HTTPError, URLError

from app.constants import APP_RELEASE_CHANNEL, APP_VERSION
from app.http_client import fetch_https_bytes


RELEASES_API_URL = "https://api.github.com/repos/Anima2099/RR-V/releases?per_page=20"
RELEASES_PAGE_URL = "https://github.com/Anima2099/RR-V/releases"

UPDATE_CHANNEL_STABLE = "stable"
UPDATE_CHANNEL_BETA = "beta"
_VALID_UPDATE_CHANNELS = {UPDATE_CHANNEL_STABLE, UPDATE_CHANNEL_BETA}
_PRERELEASE_TAG_MARKERS = ("beta", "alpha", "preview", "pre", "rc")


@dataclass(slots=True, frozen=True)
class AppUpdateResult:
    current_version: str
    latest_version: str
    update_available: bool
    release_url: str
    message: str
    update_channel: str = UPDATE_CHANNEL_STABLE
    latest_release_channel: str = ""


def normalize_update_channel(value: str, default: str = UPDATE_CHANNEL_STABLE) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized in _VALID_UPDATE_CHANNELS:
        return normalized
    fallback = str(default or "").strip().casefold()
    return fallback if fallback in _VALID_UPDATE_CHANNELS else UPDATE_CHANNEL_STABLE


def update_channel_label(value: str) -> str:
    return "베타" if normalize_update_channel(value) == UPDATE_CHANNEL_BETA else "정식"


def _version_tuple(value: str) -> tuple[int, int, int]:
    numbers = [int(item) for item in re.findall(r"\d+", str(value))[:3]]
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers[:3])


def _display_version(tag_name: str) -> str:
    match = re.search(r"\d+(?:\.\d+){1,2}", str(tag_name))
    return match.group(0) if match else str(tag_name).strip().lstrip("vV")


def _release_channel(item: dict[str, object]) -> str:
    if bool(item.get("prerelease")):
        return UPDATE_CHANNEL_BETA

    tag_name = str(item.get("tag_name") or "").strip().casefold()
    if any(marker in tag_name for marker in _PRERELEASE_TAG_MARKERS):
        return UPDATE_CHANNEL_BETA
    return UPDATE_CHANNEL_STABLE


def _release_key(tag_name: str, release_channel: str) -> tuple[int, int, int, int]:
    version = _version_tuple(tag_name)
    stable_rank = 1 if release_channel == UPDATE_CHANNEL_STABLE else 0
    return (*version, stable_rank)


def _select_latest_release(
    payload: object,
    update_channel: str,
) -> tuple[dict[str, object], str] | None:
    if not isinstance(payload, list):
        return None

    selected_channel = normalize_update_channel(update_channel, APP_RELEASE_CHANNEL)
    candidates: list[
        tuple[tuple[int, int, int, int], dict[str, object], str]
    ] = []

    for item in payload:
        if not isinstance(item, dict) or bool(item.get("draft")):
            continue

        tag_name = str(item.get("tag_name") or "").strip()
        if not tag_name:
            continue

        release_channel = _release_channel(item)
        if (
            selected_channel == UPDATE_CHANNEL_STABLE
            and release_channel != UPDATE_CHANNEL_STABLE
        ):
            continue

        candidates.append(
            (_release_key(tag_name, release_channel), item, release_channel)
        )

    if not candidates:
        return None

    _key, latest, release_channel = max(candidates, key=lambda candidate: candidate[0])
    return latest, release_channel


def _result(
    *,
    latest_version: str,
    update_available: bool,
    release_url: str,
    message: str,
    update_channel: str,
    latest_release_channel: str = "",
) -> AppUpdateResult:
    return AppUpdateResult(
        current_version=APP_VERSION,
        latest_version=latest_version,
        update_available=update_available,
        release_url=release_url,
        message=message,
        update_channel=update_channel,
        latest_release_channel=latest_release_channel,
    )


def check_app_update(
    timeout: float = 8.0,
    *,
    update_channel: str = APP_RELEASE_CHANNEL,
) -> AppUpdateResult:
    selected_channel = normalize_update_channel(update_channel, APP_RELEASE_CHANNEL)
    selected_label = update_channel_label(selected_channel)

    try:
        payload = json.loads(
            fetch_https_bytes(
                RELEASES_API_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"RR-V/{APP_VERSION}",
                },
                timeout=timeout,
                max_bytes=2 * 1024 * 1024,
            ).decode("utf-8")
        )
    except HTTPError as error:
        if error.code == 404:
            message = "공개 릴리스 정보를 아직 확인할 수 없습니다."
        elif error.code == 403:
            message = "GitHub 업데이트 확인 요청 한도에 도달했습니다. 잠시 후 다시 시도해 주세요."
        else:
            message = f"GitHub 릴리스 정보를 확인하지 못했습니다. (HTTP {error.code})"
        return _result(
            latest_version="확인 실패",
            update_available=False,
            release_url=RELEASES_PAGE_URL,
            message=message,
            update_channel=selected_channel,
        )
    except (URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return _result(
            latest_version="확인 실패",
            update_available=False,
            release_url=RELEASES_PAGE_URL,
            message="인터넷 연결 또는 GitHub 응답을 확인하지 못했습니다.",
            update_channel=selected_channel,
        )

    if not isinstance(payload, list) or not payload:
        return _result(
            latest_version="릴리스 없음",
            update_available=False,
            release_url=RELEASES_PAGE_URL,
            message="아직 공개된 RR-V 릴리스가 없습니다.",
            update_channel=selected_channel,
        )

    selected = _select_latest_release(payload, selected_channel)
    if selected is None:
        return _result(
            latest_version="릴리스 없음",
            update_available=False,
            release_url=RELEASES_PAGE_URL,
            message=f"아직 공개된 RR-V {selected_label} 릴리스가 없습니다.",
            update_channel=selected_channel,
        )

    latest, latest_release_channel = selected
    tag_name = str(latest.get("tag_name") or APP_VERSION)
    latest_version = _display_version(tag_name)
    release_url = str(latest.get("html_url") or RELEASES_PAGE_URL)

    latest_key = _release_key(tag_name, latest_release_channel)
    current_channel = normalize_update_channel(APP_RELEASE_CHANNEL)
    current_key = _release_key(APP_VERSION, current_channel)
    update_available = latest_key > current_key

    if update_available:
        latest_label = update_channel_label(latest_release_channel)
        if latest_release_channel == UPDATE_CHANNEL_STABLE:
            message = f"새 정식 버전 RR-V {latest_version}을 사용할 수 있습니다."
        else:
            message = f"새 베타 버전 RR-V {latest_version}을 사용할 수 있습니다."
        if _version_tuple(tag_name) == _version_tuple(APP_VERSION):
            message = (
                f"현재 베타 버전과 같은 번호의 정식 버전 RR-V {latest_version}을 "
                "사용할 수 있습니다."
                if latest_label == "정식"
                else message
            )
    elif latest_key == current_key:
        message = f"✓ {selected_label} 채널의 최신 버전을 사용하고 있습니다."
    else:
        message = f"현재 버전이 {selected_label} 채널의 최신 버전보다 새 버전입니다."

    return _result(
        latest_version=latest_version,
        update_available=update_available,
        release_url=release_url,
        message=message,
        update_channel=selected_channel,
        latest_release_channel=latest_release_channel,
    )
