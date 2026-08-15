from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class BatchEntry:
    source_url: str
    source_title: str
    video_id: str
    extractor: str
    title: str
    webpage_url: str
    uploader: str = "알 수 없는 채널"
    duration_seconds: int | None = None
    thumbnail_url: str = ""

    @property
    def identity_key(self) -> str:
        extractor = self.extractor.strip().lower() or "unknown"
        identity = self.video_id.strip() or self.webpage_url.strip()
        return f"{extractor}:{identity}"

    @property
    def duration_text(self) -> str:
        if self.duration_seconds is None:
            return "-"

        total_seconds = max(0, int(self.duration_seconds))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"


@dataclass(slots=True, frozen=True)
class BatchSourceError:
    source_url: str
    message: str
    detail: str = ""


@dataclass(slots=True, frozen=True)
class BatchAnalysisResult:
    entries: tuple[BatchEntry, ...]
    errors: tuple[BatchSourceError, ...] = ()
    source_count: int = 0
