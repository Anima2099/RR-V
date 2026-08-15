from __future__ import annotations

from dataclasses import dataclass


OUTPUT_OVERWRITE = "overwrite"
OUTPUT_NEW_FILE = "new_file"


@dataclass(slots=True, frozen=True)
class ThumbnailTask:
    video_path: str
    image_path: str


@dataclass(slots=True, frozen=True)
class ThumbnailOptions:
    output_mode: str = OUTPUT_OVERWRITE
    delete_image_on_success: bool = False


@dataclass(slots=True, frozen=True)
class ThumbnailProbeResult:
    video_path: str
    has_thumbnail: bool
    thumbnail_bytes: bytes
    thumbnail_codec: str
    stream_count: int


@dataclass(slots=True, frozen=True)
class ThumbnailReplaceResult:
    video_path: str
    image_path: str
    output_path: str
    replaced_original: bool
