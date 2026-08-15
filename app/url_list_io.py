from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable
from urllib.parse import parse_qs, urlparse


_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}"
_COLLECTION_PATH_SEGMENTS = {"playlist", "playlists", "sets", "showcase"}


def extract_urls(text: str) -> list[str]:
    """텍스트 어디에 있든 HTTP(S) URL을 입력 순서대로 중복 없이 추출한다."""
    urls: list[str] = []
    seen: set[str] = set()
    for match in _URL_PATTERN.finditer(text or ""):
        url = match.group(0).rstrip(_TRAILING_URL_PUNCTUATION)
        key = url.lower()
        if key and key not in seen:
            seen.add(key)
            urls.append(url)
    return urls


def is_probable_collection_url(url: str) -> bool:
    """바로 추가보다 목록 확인이 안전한 재생목록·채널 계열 URL인지 가볍게 판별한다.

    이 함수는 yt-dlp 분석을 대신하는 완전한 사이트 판별기가 아니다. 빠른 추가에서
    명백한 다중 영상 주소가 실수로 큐에 들어가는 것을 막는 보수적인 안전장치다.
    """
    try:
        parsed = urlparse(str(url).strip())
    except ValueError:
        return False

    host = parsed.netloc.lower().split(":", 1)[0]
    path = parsed.path or "/"
    path_lower = path.lower()
    query = parse_qs(parsed.query)

    if _is_youtube_host(host):
        # YouTube의 list= 파라미터는 재생목록 문맥을 뜻한다. 검색 결과의 재생목록
        # 링크도 watch?v=...&list=... 형태가 될 수 있으므로 바로 추가에서는
        # 예외 없이 목록 확인으로 보낸다.
        if any(key.casefold() == "list" for key in query):
            return True

        # youtu.be/<id>는 list=가 없는 경우에만 단일 영상 주소다.
        if host == "youtu.be" or host.endswith(".youtu.be"):
            return not bool(path.strip("/"))

        # list=가 없는 일반 watch?v=... 주소는 단일 영상으로 취급한다.
        if path_lower.rstrip("/") == "/watch" and query.get("v"):
            return False

        single_video_prefixes = (
            "/shorts/",
            "/live/",
            "/embed/",
            "/v/",
            "/clip/",
        )
        if any(path_lower.startswith(prefix) for prefix in single_video_prefixes):
            return False

        # YouTube에서 위 단일 영상 형태가 아닌 주소는 재생목록·채널·홈 등
        # 여러 항목을 가리킬 가능성이 있으므로 목록 확인으로 유도한다.
        return True

    segments = {segment for segment in path_lower.split("/") if segment}
    if segments.intersection(_COLLECTION_PATH_SEGMENTS):
        return True

    query_keys = {key.lower() for key in query}
    return bool(query_keys.intersection({"playlist", "playlist_id"}))


def probable_collection_urls(urls: Iterable[str]) -> list[str]:
    return [url for url in urls if is_probable_collection_url(url)]


def read_text_file(path: str | Path) -> str:
    """Windows에서 흔한 UTF-8/UTF-8 BOM/CP949 TXT를 안전하게 읽는다."""
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def write_text_file(path: str | Path, text: str) -> None:
    """Windows 메모장 호환성을 위해 UTF-8 BOM으로 저장한다."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8-sig", newline="\n")


def format_download_list(
    entries: Iterable[tuple[str, str]],
    *,
    scope_label: str,
) -> str:
    normalized = [
        (_single_line(title) or "제목 없음", url.strip())
        for title, url in entries
        if url and url.strip()
    ]
    lines = [
        "RR-V 다운로드 목록",
        f"내보내기: {scope_label}",
        f"총 {len(normalized)}개",
        "",
    ]
    for index, (title, url) in enumerate(normalized, start=1):
        lines.extend((f"{index}. {title}", f"   {url}", ""))
    return "\n".join(lines).rstrip() + "\n"


def format_source_url_list(urls: Iterable[str]) -> str:
    normalized = _unique_urls(urls)
    lines = [
        "RR-V 일괄 추가 주소 목록",
        f"총 {len(normalized)}개",
        "",
    ]
    for index, url in enumerate(normalized, start=1):
        lines.extend((f"{index}. {url}", ""))
    return "\n".join(lines).rstrip() + "\n"


def merge_urls(existing: Iterable[str], incoming: Iterable[str]) -> tuple[list[str], int]:
    """기존 순서를 유지한 채 새 URL만 뒤에 붙이고 제외한 중복 개수를 반환한다."""
    merged: list[str] = []
    seen: set[str] = set()
    duplicate_count = 0
    for url in [*existing, *incoming]:
        normalized = str(url).strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        merged.append(normalized)
    return merged, duplicate_count


def _is_youtube_host(host: str) -> bool:
    normalized = host.lower().split(":", 1)[0]
    return (
        normalized == "youtu.be"
        or normalized.endswith(".youtu.be")
        or normalized == "youtube.com"
        or normalized.endswith(".youtube.com")
        or normalized == "youtube-nocookie.com"
        or normalized.endswith(".youtube-nocookie.com")
    )


def _unique_urls(urls: Iterable[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for url in urls:
        normalized = str(url).strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            unique.append(normalized)
    return unique


def _single_line(text: str) -> str:
    return " ".join(str(text or "").split())
