from __future__ import annotations

from typing import Any

from app.filename_metadata_store import remember_filename_metadata
from core.filename_template import normalize_upload_date
from core.media_info import MediaInfo
from services.ytdlp_service import (
    AnalysisCancelledError,
    MediaAnalysisError,
    YtDlpService as _BaseYtDlpService,
)


def _source_chapters(info: dict[str, Any]) -> tuple[tuple[float, float, str], ...]:
    raw = info.get("chapters")
    if not isinstance(raw, list):
        return ()

    duration: float | None = None
    try:
        raw_duration = info.get("duration")
        if raw_duration is not None:
            duration = max(0.0, float(raw_duration))
    except (TypeError, ValueError, OverflowError):
        duration = None

    starts: list[float | None] = []
    for item in raw:
        if not isinstance(item, dict):
            starts.append(None)
            continue
        try:
            starts.append(max(0.0, float(item.get("start_time", 0.0))))
        except (TypeError, ValueError, OverflowError):
            starts.append(None)

    chapters: list[tuple[float, float, str]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or starts[index] is None:
            continue
        start = float(starts[index])
        end: float | None = None
        try:
            raw_end = item.get("end_time")
            if raw_end is not None:
                end = max(0.0, float(raw_end))
        except (TypeError, ValueError, OverflowError):
            end = None

        if end is None or end <= start:
            next_start = next(
                (
                    float(candidate)
                    for candidate in starts[index + 1 :]
                    if candidate is not None and float(candidate) > start
                ),
                None,
            )
            end = next_start if next_start is not None else duration

        if end is None or end - start <= 0.05:
            continue
        chapters.append((start, end, str(item.get("title") or "").strip()))
    return tuple(chapters)


class YtDlpService(_BaseYtDlpService):
    """기존 영상 분석 결과에서 후속 처리용 메타데이터도 함께 보관한다."""

    @staticmethod
    def _to_media_info(url: str, info: dict[str, Any]) -> MediaInfo:
        media_info = _BaseYtDlpService._to_media_info(url, info)
        remember_filename_metadata(
            media_info.identity_key,
            upload_date=normalize_upload_date(
                info.get("upload_date") or info.get("release_date") or ""
            ),
            resolutions=media_info.resolutions,
            chapters=_source_chapters(info),
        )
        return media_info


__all__ = [
    "AnalysisCancelledError",
    "MediaAnalysisError",
    "YtDlpService",
]