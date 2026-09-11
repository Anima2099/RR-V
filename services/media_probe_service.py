from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
from pathlib import Path
import subprocess
import sys
import threading
from time import monotonic
from typing import Any

from app.paths import find_executable
from core.local_media_info import (
    AudioTrackInfo,
    MediaChapter,
    MediaFileInfo,
    OtherTrackInfo,
    SubtitleTrackInfo,
    VideoTrackInfo,
)


class MediaProbeCancelledError(RuntimeError):
    pass


class MediaProbeError(RuntimeError):
    def __init__(self, user_message: str, technical_detail: str = "") -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical_detail = technical_detail


class MediaProbeService:
    def __init__(self) -> None:
        self.ffprobe = find_executable("ffprobe.exe") or find_executable("ffprobe")
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()

    def probe(
        self,
        input_path: str,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> MediaFileInfo:
        path = Path(input_path).expanduser()
        if not path.is_file():
            raise MediaProbeError(
                "선택한 미디어 파일을 찾을 수 없습니다.",
                str(path),
            )

        if self.ffprobe is None:
            raise MediaProbeError(
                "FFprobe를 찾을 수 없어 미디어 정보를 읽지 못했습니다.",
                "설정 → 도구 및 리소스에서 FFmpeg / FFprobe 상태를 확인해 주세요.",
            )

        command = [
            str(self.ffprobe),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            str(path),
        ]
        creation_flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32"
            else 0
        )

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
            )
        except OSError as error:
            raise MediaProbeError(
                "FFprobe를 실행하지 못했습니다.",
                str(error),
            ) from error

        with self._process_lock:
            self._process = process

        started_at = monotonic()
        try:
            while True:
                if is_cancelled is not None and is_cancelled():
                    self.cancel()
                    raise MediaProbeCancelledError("미디어 정보 확인 취소됨")
                if monotonic() - started_at > 30.0:
                    self.cancel()
                    raise MediaProbeError(
                        "미디어 정보 확인 시간이 너무 오래 걸렸습니다.",
                        "FFprobe가 30초 안에 응답하지 않았습니다.",
                    )
                try:
                    stdout, stderr = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            with self._process_lock:
                self._process = None

        if is_cancelled is not None and is_cancelled():
            raise MediaProbeCancelledError("미디어 정보 확인 취소됨")

        if process.returncode != 0:
            detail = (stderr or stdout or "알 수 없는 FFprobe 오류").strip()
            raise MediaProbeError(
                "선택한 파일의 미디어 정보를 읽지 못했습니다.",
                detail,
            )

        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as error:
            raise MediaProbeError(
                "FFprobe 응답을 해석하지 못했습니다.",
                str(error),
            ) from error

        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = None
        return parse_media_probe_payload(path, payload, file_size_bytes=size_bytes)

    def cancel(self) -> None:
        with self._process_lock:
            process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=1.0)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass


def parse_media_probe_payload(
    input_path: str | Path,
    payload: Mapping[str, Any],
    *,
    file_size_bytes: int | None = None,
) -> MediaFileInfo:
    if not isinstance(payload, Mapping):
        raise MediaProbeError(
            "FFprobe 응답을 해석하지 못했습니다.",
            "최상위 응답이 객체 형식이 아닙니다.",
        )

    path = Path(input_path)
    format_info = _mapping(payload.get("format"))
    streams = _sequence(payload.get("streams"))
    chapters_payload = _sequence(payload.get("chapters"))

    video_tracks: list[VideoTrackInfo] = []
    audio_tracks: list[AudioTrackInfo] = []
    subtitle_tracks: list[SubtitleTrackInfo] = []
    other_tracks: list[OtherTrackInfo] = []

    for fallback_index, raw_stream in enumerate(streams):
        stream = _mapping(raw_stream)
        if not stream:
            continue
        index = _int_value(stream.get("index"))
        if index is None:
            index = fallback_index
        codec_type = _text(stream.get("codec_type")).casefold()
        tags = _tags(stream.get("tags"))
        disposition = _mapping(stream.get("disposition"))
        common = {
            "index": index,
            "codec_name": _text(stream.get("codec_name")),
            "codec_long_name": _text(stream.get("codec_long_name")),
            "codec_tag": _text(stream.get("codec_tag_string")),
            "language": _tag_value(tags, "language"),
            "title": _tag_value(tags, "title"),
            "is_default": _truthy(disposition.get("default")),
        }

        if codec_type == "video":
            video_tracks.append(
                VideoTrackInfo(
                    **common,
                    profile=_text(stream.get("profile")),
                    width=_int_value(stream.get("width")),
                    height=_int_value(stream.get("height")),
                    frame_rate=_frame_rate(stream),
                    bit_rate=_int_value(stream.get("bit_rate")),
                    pixel_format=_text(stream.get("pix_fmt")),
                    color_range=_text(stream.get("color_range")),
                    color_space=_text(stream.get("color_space")),
                    color_transfer=_text(stream.get("color_transfer")),
                    color_primaries=_text(stream.get("color_primaries")),
                    dynamic_range=_dynamic_range(stream),
                    rotation_degrees=_rotation_degrees(stream, tags),
                    is_attached_picture=_truthy(disposition.get("attached_pic")),
                )
            )
        elif codec_type == "audio":
            audio_tracks.append(
                AudioTrackInfo(
                    **common,
                    profile=_text(stream.get("profile")),
                    sample_rate=_int_value(stream.get("sample_rate")),
                    channels=_int_value(stream.get("channels")),
                    channel_layout=_text(stream.get("channel_layout")),
                    bit_rate=_int_value(stream.get("bit_rate")),
                    sample_format=_text(stream.get("sample_fmt")),
                )
            )
        elif codec_type == "subtitle":
            subtitle_tracks.append(
                SubtitleTrackInfo(
                    **common,
                    is_forced=_truthy(disposition.get("forced")),
                )
            )
        else:
            other_tracks.append(
                OtherTrackInfo(
                    **common,
                    codec_type=codec_type or "unknown",
                )
            )

    chapters: list[MediaChapter] = []
    for index, raw_chapter in enumerate(chapters_payload):
        chapter = _mapping(raw_chapter)
        if not chapter:
            continue
        start = _float_value(chapter.get("start_time"))
        end = _float_value(chapter.get("end_time"))
        if start is None:
            start = 0.0
        if end is None:
            end = start
        if end < start:
            end = start
        tags = _tags(chapter.get("tags"))
        chapters.append(
            MediaChapter(
                index=index,
                start_seconds=start,
                end_seconds=end,
                title=_tag_value(tags, "title"),
            )
        )

    format_names = tuple(
        item.strip()
        for item in _text(format_info.get("format_name")).split(",")
        if item.strip()
    )
    duration = _float_value(format_info.get("duration"))
    if duration is None:
        duration = _longest_stream_duration(streams)
    if duration is None and chapters:
        duration = max(chapter.end_seconds for chapter in chapters)

    if file_size_bytes is None:
        file_size_bytes = _int_value(format_info.get("size"))
    size_bytes = max(0, int(file_size_bytes or 0))

    return MediaFileInfo(
        path=str(path),
        file_name=path.name,
        size_bytes=size_bytes,
        format_names=format_names,
        format_long_name=_text(format_info.get("format_long_name")),
        duration_seconds=duration,
        bit_rate=_int_value(format_info.get("bit_rate")),
        start_time_seconds=_float_value(format_info.get("start_time")),
        metadata=_tags(format_info.get("tags")),
        video_tracks=tuple(video_tracks),
        audio_tracks=tuple(audio_tracks),
        subtitle_tracks=tuple(subtitle_tracks),
        other_tracks=tuple(other_tracks),
        chapters=tuple(chapters),
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _float_value(value: object) -> float | None:
    text = _text(value)
    if not text or text.casefold() in {"n/a", "nan", "inf", "-inf"}:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _int_value(value: object) -> int | None:
    parsed = _float_value(value)
    if parsed is None:
        return None
    try:
        return int(parsed)
    except (OverflowError, ValueError):
        return None


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return _text(value).casefold() in {"1", "true", "yes", "on"}


def _tags(value: object) -> tuple[tuple[str, str], ...]:
    mapping = _mapping(value)
    return tuple(
        (str(key).strip(), _text(item))
        for key, item in mapping.items()
        if str(key).strip() and _text(item)
    )


def _tag_value(tags: tuple[tuple[str, str], ...], key: str) -> str:
    wanted = key.casefold()
    for item_key, value in tags:
        if item_key.casefold() == wanted:
            return value
    return ""


def _rate_value(value: object) -> float | None:
    text = _text(value)
    if not text or text in {"0/0", "0/1"}:
        return None
    if "/" not in text:
        return _float_value(text)
    numerator_text, denominator_text = text.split("/", 1)
    numerator = _float_value(numerator_text)
    denominator = _float_value(denominator_text)
    if numerator is None or denominator in {None, 0.0}:
        return None
    return numerator / denominator


def _frame_rate(stream: Mapping[str, Any]) -> float | None:
    average = _rate_value(stream.get("avg_frame_rate"))
    if average is not None and average > 0:
        return average
    rate = _rate_value(stream.get("r_frame_rate"))
    return rate if rate is not None and rate > 0 else None


def _longest_stream_duration(streams: Sequence[object]) -> float | None:
    durations: list[float] = []
    for raw_stream in streams:
        duration = _float_value(_mapping(raw_stream).get("duration"))
        if duration is not None and duration >= 0:
            durations.append(duration)
    return max(durations) if durations else None


def _dynamic_range(stream: Mapping[str, Any]) -> str:
    side_data = _sequence(stream.get("side_data_list"))
    side_text = " ".join(
        " ".join(_text(value) for value in _mapping(item).values())
        for item in side_data
    ).casefold()
    if "dovi" in side_text or "dolby vision" in side_text:
        return "Dolby Vision"
    if "smpte2094-40" in side_text or "hdr10+" in side_text:
        return "HDR10+"

    transfer = _text(stream.get("color_transfer")).casefold()
    if transfer in {"smpte2084", "pq"}:
        return "HDR (PQ)"
    if transfer in {"arib-std-b67", "hlg"}:
        return "HDR (HLG)"
    return ""


def _rotation_degrees(
    stream: Mapping[str, Any],
    tags: tuple[tuple[str, str], ...],
) -> int | None:
    tagged = _int_value(_tag_value(tags, "rotate"))
    if tagged is not None:
        return tagged % 360
    for item in _sequence(stream.get("side_data_list")):
        rotation = _int_value(_mapping(item).get("rotation"))
        if rotation is not None:
            return rotation % 360
    return None
