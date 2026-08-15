from __future__ import annotations

from dataclasses import dataclass


OP_EXTRACT = "extract"
OP_INSERT = "insert"
OP_SYNC = "sync"
OP_REMOVE = "remove"

OUTPUT_OVERWRITE = "overwrite"
OUTPUT_NEW_FILE = "new_file"
OUTPUT_SOURCE = "source"
OUTPUT_CUSTOM = "custom"

EXTRACT_ORIGINAL = "original"
EXTRACT_SRT = "srt"
EXTRACT_ASS = "ass"


@dataclass(slots=True, frozen=True)
class SubtitleTrack:
    stream_index: int
    subtitle_index: int
    codec_name: str
    codec_long_name: str
    language: str
    title: str
    is_default: bool
    is_forced: bool
    is_text: bool
    is_image: bool


@dataclass(slots=True, frozen=True)
class SubtitleProbeResult:
    video_path: str
    duration: float
    width: int
    height: int
    video_codec: str
    tracks: tuple[SubtitleTrack, ...]


@dataclass(slots=True, frozen=True)
class SubtitleTask:
    primary_path: str
    secondary_path: str = ""


@dataclass(slots=True, frozen=True)
class SubtitleInsertItem:
    path: str
    language: str = "und"
    title: str = ""
    make_default: bool = False
    make_forced: bool = False


@dataclass(slots=True, frozen=True)
class SubtitleOptions:
    operation: str
    selected_stream_indices: tuple[int, ...] = ()
    extract_format: str = EXTRACT_ORIGINAL
    language: str = "und"
    track_title: str = ""
    make_default: bool = False
    make_forced: bool = False
    delete_external_after_insert: bool = False
    sync_offset_ms: int = 0
    output_mode: str = OUTPUT_OVERWRITE
    output_folder_mode: str = OUTPUT_SOURCE
    output_folder: str = ""


@dataclass(slots=True, frozen=True)
class SubtitleResult:
    operation: str
    source_path: str
    output_paths: tuple[str, ...]
    message: str
