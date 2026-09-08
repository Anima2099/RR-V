from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path
import queue
import subprocess
import sys
import threading
from uuid import uuid4

from app.paths import find_executable
from core.local_media_info import MediaFileInfo
from core.remux_models import (
    REMUX_TARGET_LABELS,
    REMUX_TARGET_MKV,
    REMUX_TARGET_MOV,
    REMUX_TARGET_MP4,
    REMUX_TARGETS,
    RemuxCompatibility,
    RemuxResult,
)
from services.media_probe_service import MediaProbeError, MediaProbeService


ProgressCallback = Callable[[int], None]
PhaseCallback = Callable[[str], None]


class RemuxCancelledError(RuntimeError):
    pass


class RemuxError(RuntimeError):
    def __init__(self, user_message: str, technical_detail: str = "") -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical_detail = technical_detail


_MKV_VIDEO_CODECS = {
    "h264", "hevc", "av1", "vp9", "vp8", "mpeg4", "mpeg2video", "mpeg1video",
    "theora", "prores", "mjpeg", "png", "ffv1", "huffyuv",
}
_MKV_AUDIO_CODECS = {
    "aac", "ac3", "eac3", "mp3", "mp2", "opus", "vorbis", "flac", "alac",
    "dts", "truehd", "mlp", "wavpack", "pcm_s16le", "pcm_s24le", "pcm_s32le",
    "pcm_f32le", "pcm_f64le",
}
_MKV_SUBTITLE_CODECS = {
    "subrip", "ass", "ssa", "webvtt", "hdmv_pgs_subtitle", "dvd_subtitle",
    "dvb_subtitle",
}

_MP4_VIDEO_CODECS = {
    "h264", "hevc", "av1", "vp9", "mpeg4", "mjpeg",
}
_MP4_AUDIO_CODECS = {
    "aac", "alac", "mp3", "ac3", "eac3", "opus",
}
_MP4_SUBTITLE_CODECS = {"mov_text"}

_MOV_VIDEO_CODECS = {
    "h264", "hevc", "av1", "mpeg4", "mjpeg", "prores", "dnxhd", "png", "qtrle",
}
_MOV_AUDIO_CODECS = {
    "aac", "alac", "mp3", "ac3", "eac3", "pcm_s16le", "pcm_s24le", "pcm_s32le",
    "pcm_f32le", "pcm_f64le",
}
_MOV_SUBTITLE_CODECS = {"mov_text"}

_CODEC_SETS = {
    REMUX_TARGET_MKV: (_MKV_VIDEO_CODECS, _MKV_AUDIO_CODECS, _MKV_SUBTITLE_CODECS),
    REMUX_TARGET_MP4: (_MP4_VIDEO_CODECS, _MP4_AUDIO_CODECS, _MP4_SUBTITLE_CODECS),
    REMUX_TARGET_MOV: (_MOV_VIDEO_CODECS, _MOV_AUDIO_CODECS, _MOV_SUBTITLE_CODECS),
}


def assess_remux_compatibility(
    media_info: MediaFileInfo,
    target_container: str,
) -> RemuxCompatibility:
    target = target_container.strip().lower()
    label = REMUX_TARGET_LABELS.get(target, target.upper() or "알 수 없는 형식")
    if target not in REMUX_TARGETS:
        return RemuxCompatibility(
            target_container=target,
            supported=False,
            issues=(f"지원하지 않는 출력 컨테이너입니다: {label}",),
        )

    source_suffix = Path(media_info.file_name).suffix.lstrip(".").lower()
    if source_suffix == target:
        return RemuxCompatibility(
            target_container=target,
            supported=False,
            issues=(f"이미 {label} 컨테이너인 파일입니다.",),
        )

    if media_info.stream_count <= 0:
        return RemuxCompatibility(
            target_container=target,
            supported=False,
            issues=("복사할 미디어 트랙을 찾지 못했습니다.",),
        )

    video_codecs, audio_codecs, subtitle_codecs = _CODEC_SETS[target]
    issues: list[str] = []

    for track in media_info.video_tracks:
        codec = track.codec_name.strip().lower()
        if not codec or codec not in video_codecs:
            issues.append(
                _unsupported_track_message(
                    label, "비디오", track.index, codec or "알 수 없음"
                )
            )

    for track in media_info.audio_tracks:
        codec = track.codec_name.strip().lower()
        if not codec or codec not in audio_codecs:
            issues.append(
                _unsupported_track_message(
                    label, "오디오", track.index, codec or "알 수 없음"
                )
            )

    for track in media_info.subtitle_tracks:
        codec = track.codec_name.strip().lower()
        if not codec or codec not in subtitle_codecs:
            issues.append(
                _unsupported_track_message(
                    label, "자막", track.index, codec or "알 수 없음"
                )
            )

    for track in media_info.other_tracks:
        codec_type = track.codec_type.strip().lower()
        if target == REMUX_TARGET_MKV and codec_type == "attachment":
            continue
        description = codec_type or "기타"
        issues.append(
            f"스트림 #{track.index}의 {description} 트랙은 {label}로 전체 보존할 수 없습니다."
        )

    return RemuxCompatibility(
        target_container=target,
        supported=not issues,
        issues=tuple(issues),
    )


def build_remux_command(
    ffmpeg_path: str | Path,
    input_path: str | Path,
    output_path: str | Path,
) -> list[str]:
    return [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0",
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",
        "-c",
        "copy",
        "-progress",
        "pipe:1",
        "-nostats",
        str(output_path),
    ]


class RemuxService:
    def __init__(self) -> None:
        self.ffmpeg = find_executable("ffmpeg.exe") or find_executable("ffmpeg")
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()
        self._probe_service = MediaProbeService()

    def suggested_output_path(
        self,
        media_info: MediaFileInfo,
        target_container: str,
    ) -> Path:
        target = target_container.strip().lower()
        input_path = Path(media_info.path).expanduser()
        base = input_path.with_name(f"{input_path.stem}_remux.{target}")

        try:
            from app.general_preferences import (
                FILE_COLLISION_OVERWRITE,
                load_general_preferences,
            )
            overwrite = (
                load_general_preferences().file_collision_mode
                == FILE_COLLISION_OVERWRITE
            )
        except Exception:
            overwrite = False

        if overwrite or not base.exists():
            return base

        counter = 1
        while True:
            candidate = base.with_name(f"{base.stem} ({counter}){base.suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def remux(
        self,
        media_info: MediaFileInfo,
        target_container: str,
        *,
        on_progress: ProgressCallback | None = None,
        on_phase: PhaseCallback | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> RemuxResult:
        compatibility = assess_remux_compatibility(media_info, target_container)
        if not compatibility.supported:
            raise RemuxError(
                "선택한 컨테이너로 무손실 Remux할 수 없습니다.",
                "\n".join(compatibility.issues),
            )

        if self.ffmpeg is None:
            raise RemuxError(
                "FFmpeg를 찾을 수 없어 Remux를 시작하지 못했습니다.",
                "설정 → 도구 및 리소스에서 FFmpeg / FFprobe 상태를 확인해 주세요.",
            )

        input_path = Path(media_info.path).expanduser()
        if not input_path.is_file():
            raise RemuxError(
                "입력 미디어 파일을 찾을 수 없습니다.",
                str(input_path),
            )

        target = target_container.strip().lower()
        output_path = self.suggested_output_path(media_info, target)
        temporary_path = output_path.with_name(
            f".{output_path.stem}.rrv-{uuid4().hex[:8]}.{target}"
        )

        if on_progress is not None:
            on_progress(0)
        if on_phase is not None:
            on_phase("컨테이너를 다시 구성하는 중…")

        command = build_remux_command(self.ffmpeg, input_path, temporary_path)
        try:
            self._run_ffmpeg(
                command,
                duration_seconds=media_info.duration_seconds,
                on_progress=on_progress,
                is_cancelled=is_cancelled,
            )

            if is_cancelled is not None and is_cancelled():
                raise RemuxCancelledError("Remux 중지됨")

            if on_phase is not None:
                on_phase("결과를 확인하는 중…")

            try:
                output_info = self._probe_service.probe(
                    str(temporary_path),
                    is_cancelled=is_cancelled,
                )
            except MediaProbeError as error:
                raise RemuxError(
                    "Remux 결과를 확인하지 못했습니다.",
                    error.technical_detail or error.user_message,
                ) from error

            self._verify_output(media_info, output_info)

            try:
                if output_path.exists():
                    output_path.unlink()
                temporary_path.replace(output_path)
            except OSError as error:
                raise RemuxError(
                    "완성된 Remux 파일을 저장하지 못했습니다.",
                    str(error),
                ) from error

            if on_progress is not None:
                on_progress(100)
            if on_phase is not None:
                on_phase("Remux 완료")

            try:
                size_bytes = output_path.stat().st_size
            except OSError:
                size_bytes = 0
            return RemuxResult(
                output_path=str(output_path),
                size_bytes=size_bytes,
            )
        finally:
            try:
                if temporary_path.exists():
                    temporary_path.unlink()
            except OSError:
                pass

    def cancel(self) -> None:
        self._probe_service.cancel()
        with self._process_lock:
            process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    timeout=5,
                    check=False,
                )
            else:
                process.terminate()
                process.wait(timeout=2.0)
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass

    def _run_ffmpeg(
        self,
        command: list[str],
        *,
        duration_seconds: float | None,
        on_progress: ProgressCallback | None,
        is_cancelled: Callable[[], bool] | None,
    ) -> None:
        creation_flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32"
            else 0
        )
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
                bufsize=1,
            )
        except OSError as error:
            raise RemuxError(
                "FFmpeg를 실행하지 못했습니다.",
                str(error),
            ) from error

        with self._process_lock:
            self._process = process

        lines: queue.Queue[str | None] = queue.Queue()
        collected: list[str] = []

        def read_output() -> None:
            assert process.stdout is not None
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()

        try:
            reader_done = False
            while True:
                if is_cancelled is not None and is_cancelled():
                    self.cancel()
                    raise RemuxCancelledError("Remux 중지됨")

                try:
                    line = lines.get(timeout=0.1)
                except queue.Empty:
                    line = ""
                if line is None:
                    reader_done = True
                elif line:
                    collected.append(line)
                    self._apply_progress_line(
                        line,
                        duration_seconds=duration_seconds,
                        on_progress=on_progress,
                    )

                if process.poll() is not None and reader_done:
                    break

            return_code = process.wait()
        finally:
            with self._process_lock:
                if self._process is process:
                    self._process = None
            reader.join(timeout=1.0)

        if return_code != 0:
            detail = "".join(collected[-80:]).strip()
            raise RemuxError(
                "FFmpeg가 Remux를 완료하지 못했습니다.",
                detail or f"FFmpeg 종료 코드: {return_code}",
            )

    @staticmethod
    def _apply_progress_line(
        line: str,
        *,
        duration_seconds: float | None,
        on_progress: ProgressCallback | None,
    ) -> None:
        if on_progress is None or not duration_seconds or duration_seconds <= 0:
            return
        text = line.strip()
        if "=" not in text:
            return
        key, value = text.split("=", 1)
        if key not in {"out_time_us", "out_time_ms"}:
            return
        try:
            current_seconds = max(0.0, float(value) / 1_000_000.0)
        except ValueError:
            return
        percent = int(max(0.0, min(99.0, current_seconds / duration_seconds * 100.0)))
        on_progress(percent)

    @staticmethod
    def _verify_output(source: MediaFileInfo, output: MediaFileInfo) -> None:
        source_signature = _stream_signature(source)
        output_signature = _stream_signature(output)
        issues: list[str] = []

        if source_signature != output_signature:
            issues.append(
                "입력과 출력의 스트림 종류 또는 코덱 구성이 일치하지 않습니다."
            )
        if len(source.chapters) != len(output.chapters):
            issues.append(
                f"챕터 수가 달라졌습니다: {len(source.chapters)}개 → {len(output.chapters)}개"
            )
        if output.size_bytes <= 0:
            issues.append("출력 파일 크기가 0입니다.")

        if (
            source.duration_seconds is not None
            and output.duration_seconds is not None
            and abs(source.duration_seconds - output.duration_seconds) > 2.0
        ):
            issues.append(
                "입력과 출력의 재생 시간이 2초 이상 차이 납니다."
            )

        if issues:
            raise RemuxError(
                "Remux 결과 검증에 실패했습니다.",
                "\n".join(issues),
            )


def _unsupported_track_message(
    target_label: str,
    track_kind: str,
    index: int,
    codec: str,
) -> str:
    return (
        f"{track_kind} 스트림 #{index}의 {codec} 코덱은 "
        f"{target_label}에서 그대로 복사할 수 없습니다."
    )


def _stream_signature(media_info: MediaFileInfo) -> tuple[tuple[str, str, int], ...]:
    counter: Counter[tuple[str, str]] = Counter()

    for track in media_info.video_tracks:
        counter[("video", track.codec_name.strip().lower())] += 1
    for track in media_info.audio_tracks:
        counter[("audio", track.codec_name.strip().lower())] += 1
    for track in media_info.subtitle_tracks:
        counter[("subtitle", track.codec_name.strip().lower())] += 1
    for track in media_info.other_tracks:
        kind = track.codec_type.strip().lower() or "other"
        counter[(kind, track.codec_name.strip().lower())] += 1

    return tuple(
        sorted((kind, codec, count) for (kind, codec), count in counter.items())
    )
