from __future__ import annotations

from dataclasses import dataclass


SIZE_WIDTH = "width"
SIZE_HEIGHT = "height"
OUTPUT_SOURCE = "source"
OUTPUT_CUSTOM = "custom"


@dataclass(slots=True, frozen=True)
class SnapshotProbeResult:
    input_path: str
    stream_index: int
    width: int
    height: int
    duration_seconds: float
    codec_name: str
    file_size_bytes: int
    frame_rate: float = 0.0
    bit_rate: int = 0
    profile: str = ""
    pixel_format: str = ""
    container_name: str = ""


@dataclass(slots=True, frozen=True)
class SnapshotOptions:
    columns: int
    rows: int
    margin: int
    size_mode: str
    target_size: int
    show_info: bool
    show_time: bool
    font_family: str
    info_font_size: int
    time_font_size: int
    output_mode: str
    output_folder: str
    create_subfolder: bool
    subfolder_name: str


@dataclass(slots=True, frozen=True)
class SnapshotResult:
    output_path: str
    sheet_width: int
    sheet_height: int
    shot_count: int
