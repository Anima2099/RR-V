from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class VideoProbeResult:
    path: str
    width: int
    height: int
    duration: float
    fps: float
    format_name: str
    video_codec: str


@dataclass(slots=True, frozen=True)
class ConversionOptions:
    output_format: str
    mode: str
    quality: int
    fps: str
    resize_mode: str
    width: int
    height: int
    target_mb: float
    target_strategy: str
    target_attempts: int
    output_mode: str
    output_folder: str


@dataclass(slots=True, frozen=True)
class ConversionResult:
    output_path: str
    size_bytes: int
    attempts: int
