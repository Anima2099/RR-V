from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class MediaInfo:
    video_id: str
    extractor: str
    title: str
    webpage_url: str
    original_url: str
    uploader: str = "알 수 없는 채널"
    duration_seconds: int | None = None
    thumbnail_url: str = ""
    site_name: str = ""
    resolutions: tuple[str, ...] = ()
    manual_subtitle_languages: tuple[str, ...] = ()
    automatic_subtitle_languages: tuple[str, ...] = ()

    @property
    def identity_key(self) -> str:
        extractor = self.extractor.strip().lower() or "unknown"
        video_id = self.video_id.strip() or self.webpage_url.strip()
        return f"{extractor}:{video_id}"

    @property
    def subtitle_languages(self) -> tuple[str, ...]:
        """직접 제공 자막과 자동 생성 자막의 중복을 제거한 전체 언어 목록."""
        ordered: list[str] = []
        seen: set[str] = set()
        for language in (
            *self.manual_subtitle_languages,
            *self.automatic_subtitle_languages,
        ):
            normalized = language.strip()
            if normalized and normalized.lower() not in seen:
                seen.add(normalized.lower())
                ordered.append(normalized)
        return tuple(ordered)

    @property
    def duration_text(self) -> str:
        if self.duration_seconds is None:
            return "길이 정보 없음"

        total_seconds = max(0, int(self.duration_seconds))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours:
            return f"{hours}시간 {minutes:02d}분 {seconds:02d}초"
        if minutes:
            return f"{minutes}분 {seconds:02d}초"
        return f"{seconds}초"

    @property
    def source_text(self) -> str:
        items = [self.uploader, self.duration_text]
        if self.site_name:
            items.append(self.site_name)
        return " · ".join(item for item in items if item)
