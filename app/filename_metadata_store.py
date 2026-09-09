from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from threading import Lock
from time import time
import unicodedata

from app.paths import RRV_LOCAL_DIR
from core.filename_template import normalize_upload_date


_METADATA_PATH = RRV_LOCAL_DIR / "filename_metadata.json"
_MAX_ENTRIES = 512
_LOCK = Lock()
_CACHE: dict[str, dict[str, object]] | None = None
_RESOLUTION_PATTERN = re.compile(r"^(\d{2,4})p$", re.IGNORECASE)


@dataclass(slots=True, frozen=True)
class FilenameMetadata:
    upload_date: str = ""
    resolutions: tuple[str, ...] = ()
    chapters: tuple[tuple[float, float, str], ...] = ()


def remember_filename_metadata(
    identity_key: object,
    *,
    upload_date: object = "",
    resolutions: object = (),
    chapters: object = (),
) -> None:
    """최초 영상 분석에서 후속 처리에 필요한 작은 메타데이터를 보관한다.

    파일명 템플릿과 챕터 분할 때문에 같은 URL을 다시 yt-dlp로 조회하지 않도록
    하기 위한 보조 캐시다. 캐시 저장 실패는 영상 분석이나 다운로드 실패로
    전파하지 않는다.
    """
    cache_key = _hashed_identity(identity_key)
    if not cache_key:
        return

    normalized_resolutions = _normalize_resolutions(resolutions)
    normalized_chapters = _normalize_chapters(chapters)
    entry = {
        "upload_date": normalize_upload_date(upload_date),
        "resolutions": list(normalized_resolutions),
        "chapters": [list(item) for item in normalized_chapters],
        "updated_at": time(),
    }

    with _LOCK:
        cache = _load_cache_locked()
        cache[cache_key] = entry
        if len(cache) > _MAX_ENTRIES:
            ordered = sorted(
                cache.items(),
                key=lambda item: _safe_timestamp(item[1].get("updated_at")),
                reverse=True,
            )
            cache.clear()
            cache.update(ordered[:_MAX_ENTRIES])
        _write_cache_locked(cache)


def load_filename_metadata(identity_key: object) -> FilenameMetadata:
    cache_key = _hashed_identity(identity_key)
    if not cache_key:
        return FilenameMetadata()

    with _LOCK:
        cache = _load_cache_locked()
        raw = cache.get(cache_key)
        if not isinstance(raw, dict):
            return FilenameMetadata()
        return FilenameMetadata(
            upload_date=normalize_upload_date(raw.get("upload_date", "")),
            resolutions=_normalize_resolutions(raw.get("resolutions", ())),
            chapters=_normalize_chapters(raw.get("chapters", ())),
        )


def _hashed_identity(identity_key: object) -> str:
    raw = str(identity_key or "").strip()
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_resolutions(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()

    heights: set[int] = set()
    for item in value:
        match = _RESOLUTION_PATTERN.fullmatch(str(item or "").strip())
        if match is None:
            continue
        height = int(match.group(1))
        if height > 0:
            heights.add(height)
    return tuple(f"{height}p" for height in sorted(heights, reverse=True))


def _normalize_chapters(value: object) -> tuple[tuple[float, float, str], ...]:
    if not isinstance(value, (list, tuple)):
        return ()

    normalized: list[tuple[float, float, str]] = []
    for item in value:
        start: object
        end: object
        title: object
        if isinstance(item, dict):
            start = item.get("start_time", item.get("start", 0.0))
            end = item.get("end_time", item.get("end", start))
            title = item.get("title", "")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            start = item[0]
            end = item[1]
            title = item[2] if len(item) >= 3 else ""
        else:
            continue

        try:
            start_seconds = max(0.0, float(start))
            end_seconds = max(0.0, float(end))
        except (TypeError, ValueError, OverflowError):
            continue
        if end_seconds - start_seconds <= 0.05:
            continue

        chapter_title = unicodedata.normalize(
            "NFC", str(title or "")
        ).strip()
        normalized.append((start_seconds, end_seconds, chapter_title))

    normalized.sort(key=lambda item: (item[0], item[1]))
    return tuple(normalized)


def _load_cache_locked() -> dict[str, dict[str, object]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    try:
        payload = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    cache: dict[str, dict[str, object]] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        cache[key] = value
    _CACHE = cache
    return _CACHE


def _write_cache_locked(cache: dict[str, dict[str, object]]) -> None:
    temporary = _METADATA_PATH.with_suffix(".json.tmp")
    try:
        _METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, _METADATA_PATH)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _safe_timestamp(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0