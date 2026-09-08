from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def _format_size(size_bytes: int) -> str:
    size = max(0, int(size_bytes))
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(size)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{size} B"


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "확인 불가"
    total = max(0.0, float(seconds))
    whole_seconds = int(total)
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}시간 {minutes:02d}분 {secs:02d}초"
    if minutes:
        return f"{minutes}분 {secs:02d}초"
    return f"{secs}초"


def _format_bit_rate(bit_rate: int | None) -> str:
    if bit_rate is None or bit_rate <= 0:
        return "확인 불가"
    value = float(bit_rate)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f} Mbps"
    if value >= 1_000:
        return f"{value / 1_000:.0f} kbps"
    return f"{int(value)} bps"


@dataclass(slots=True, frozen=True)
class VideoTrackInfo:
    index: int
    codec_name: str
    codec_long_name: str = ""
    profile: str = ""
    codec_tag: str = ""
    width: int | None = None
    height: int | None = None
    frame_rate: float | None = None
    bit_rate: int | None = None
    pixel_format: str = ""
    color_range: str = ""
    color_space: str = ""
    color_transfer: str = ""
    color_primaries: str = ""
    dynamic_range: str = ""
    rotation_degrees: int | None = None
    language: str = ""
    title: str = ""
    is_default: bool = False
    is_attached_picture: bool = False

    @property
    def resolution_text(self) -> str:
        if not self.width or not self.height:
            return "확인 불가"
        if self.rotation_degrees in {90, 270}:
            return f"{self.height}×{self.width}"
        return f"{self.width}×{self.height}"

    @property
    def frame_rate_text(self) -> str:
        if self.frame_rate is None or self.frame_rate <= 0:
            return "확인 불가"
        rounded = round(self.frame_rate)
        if abs(self.frame_rate - rounded) < 0.01:
            return f"{rounded} FPS"
        value = f"{self.frame_rate:.3f}".rstrip("0").rstrip(".")
        return f"{value} FPS"

    @property
    def bit_rate_text(self) -> str:
        return _format_bit_rate(self.bit_rate)


@dataclass(slots=True, frozen=True)
class AudioTrackInfo:
    index: int
    codec_name: str
    codec_long_name: str = ""
    profile: str = ""
    codec_tag: str = ""
    sample_rate: int | None = None
    channels: int | None = None
    channel_layout: str = ""
    bit_rate: int | None = None
    sample_format: str = ""
    language: str = ""
    title: str = ""
    is_default: bool = False

    @property
    def bit_rate_text(self) -> str:
        return _format_bit_rate(self.bit_rate)


@dataclass(slots=True, frozen=True)
class SubtitleTrackInfo:
    index: int
    codec_name: str
    codec_long_name: str = ""
    codec_tag: str = ""
    language: str = ""
    title: str = ""
    is_default: bool = False
    is_forced: bool = False


@dataclass(slots=True, frozen=True)
class OtherTrackInfo:
    index: int
    codec_type: str
    codec_name: str
    codec_long_name: str = ""
    codec_tag: str = ""
    language: str = ""
    title: str = ""
    is_default: bool = False


@dataclass(slots=True, frozen=True)
class MediaChapter:
    index: int
    start_seconds: float
    end_seconds: float
    title: str = ""

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)


@dataclass(slots=True, frozen=True)
class MediaFileInfo:
    path: str
    file_name: str
    size_bytes: int
    format_names: tuple[str, ...] = ()
    format_long_name: str = ""
    duration_seconds: float | None = None
    bit_rate: int | None = None
    start_time_seconds: float | None = None
    metadata: tuple[tuple[str, str], ...] = ()
    video_tracks: tuple[VideoTrackInfo, ...] = ()
    audio_tracks: tuple[AudioTrackInfo, ...] = ()
    subtitle_tracks: tuple[SubtitleTrackInfo, ...] = ()
    other_tracks: tuple[OtherTrackInfo, ...] = ()
    chapters: tuple[MediaChapter, ...] = ()

    @property
    def container_text(self) -> str:
        suffix = Path(self.file_name).suffix.lstrip(".").upper()
        raw = ", ".join(self.format_names)
        if suffix and self.format_long_name:
            return f"{suffix} · {self.format_long_name}"
        if suffix:
            return suffix
        if self.format_long_name:
            return self.format_long_name
        return raw or "확인 불가"

    @property
    def duration_text(self) -> str:
        return _format_duration(self.duration_seconds)

    @property
    def size_text(self) -> str:
        return _format_size(self.size_bytes)

    @property
    def bit_rate_text(self) -> str:
        return _format_bit_rate(self.bit_rate)

    @property
    def stream_count(self) -> int:
        return (
            len(self.video_tracks)
            + len(self.audio_tracks)
            + len(self.subtitle_tracks)
            + len(self.other_tracks)
        )

    @property
    def primary_video(self) -> VideoTrackInfo | None:
        for track in self.video_tracks:
            if not track.is_attached_picture:
                return track
        return None

    @property
    def has_video(self) -> bool:
        return self.primary_video is not None

    @property
    def has_audio(self) -> bool:
        return bool(self.audio_tracks)

    def metadata_value(self, key: str, default: str = "") -> str:
        wanted = key.strip().casefold()
        for item_key, value in self.metadata:
            if item_key.casefold() == wanted:
                return value
        return default
