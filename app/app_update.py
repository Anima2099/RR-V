from __future__ import annotations

from dataclasses import dataclass
import json
import re
from urllib.error import HTTPError, URLError

from app.constants import APP_VERSION
from app.http_client import fetch_https_bytes


RELEASES_API_URL = "https://api.github.com/repos/Anima2099/RR-V/releases?per_page=20"
RELEASES_PAGE_URL = "https://github.com/Anima2099/RR-V/releases"


@dataclass(slots=True, frozen=True)
class AppUpdateResult:
    current_version: str
    latest_version: str
    update_available: bool
    release_url: str
    message: str


def _version_tuple(value: str) -> tuple[int, int, int]:
    numbers = [int(item) for item in re.findall(r"\d+", str(value))[:3]]
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers[:3])


def _display_version(tag_name: str) -> str:
    match = re.search(r"\d+(?:\.\d+){1,2}", str(tag_name))
    return match.group(0) if match else str(tag_name).strip().lstrip("vV")


def check_app_update(timeout: float = 8.0) -> AppUpdateResult:
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
        return AppUpdateResult(APP_VERSION, "확인 실패", False, RELEASES_PAGE_URL, message)
    except (URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return AppUpdateResult(
            APP_VERSION,
            "확인 실패",
            False,
            RELEASES_PAGE_URL,
            "인터넷 연결 또는 GitHub 응답을 확인하지 못했습니다.",
        )

    if not isinstance(payload, list) or not payload:
        return AppUpdateResult(
            APP_VERSION,
            "릴리스 없음",
            False,
            RELEASES_PAGE_URL,
            "아직 공개된 RR-V 릴리스가 없습니다.",
        )

    candidates: list[tuple[tuple[int, int, int], dict[str, object]]] = []
    for item in payload:
        if not isinstance(item, dict) or bool(item.get("draft")):
            continue
        tag_name = str(item.get("tag_name") or "").strip()
        if not tag_name:
            continue
        candidates.append((_version_tuple(tag_name), item))

    if not candidates:
        return AppUpdateResult(
            APP_VERSION,
            "릴리스 없음",
            False,
            RELEASES_PAGE_URL,
            "확인 가능한 RR-V 릴리스가 없습니다.",
        )

    latest_tuple, latest = max(candidates, key=lambda item: item[0])
    current_tuple = _version_tuple(APP_VERSION)
    tag_name = str(latest.get("tag_name") or APP_VERSION)
    latest_version = _display_version(tag_name)
    release_url = str(latest.get("html_url") or RELEASES_PAGE_URL)
    update_available = latest_tuple > current_tuple

    if update_available:
        message = f"새 버전 RR-V {latest_version}을 사용할 수 있습니다."
    elif latest_tuple == current_tuple:
        message = "✓ 최신 버전을 사용하고 있습니다."
    else:
        message = "현재 빌드가 공개 릴리스보다 새 버전입니다."

    return AppUpdateResult(
        current_version=APP_VERSION,
        latest_version=latest_version,
        update_available=update_available,
        release_url=release_url,
        message=message,
    )
