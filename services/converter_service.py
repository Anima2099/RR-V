from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
from time import perf_counter
import unicodedata
from typing import Callable
from uuid import uuid4

from app.converter_log import (
    append_conversion_log,
    create_conversion_log_path,
    write_converter_event,
)
from app.converter_preferences import (
    FORMAT_APNG,
    FORMAT_AVIF,
    FORMAT_GIF,
    FORMAT_WEBP,
    MODE_TARGET,
    OUTPUT_CUSTOM,
    RESIZE_CUSTOM,
    RESIZE_HEIGHT,
    RESIZE_ORIGINAL,
    RESIZE_WIDTH,
    TARGET_STRATEGY_QUALITY,
)
from app.general_preferences import (
    FILE_COLLISION_OVERWRITE,
    load_general_preferences,
)
from app.paths import find_executable
from core.converter_models import (
    ConversionOptions,
    ConversionResult,
    VideoProbeResult,
)


ProgressCallback = Callable[[int], None]
PhaseCallback = Callable[[str], None]
AttemptCallback = Callable[[int, int, str], None]
ProcessCallback = Callable[[int], None]


class ConversionCancelledError(RuntimeError):
    pass


class ConversionExecutionError(RuntimeError):
    def __init__(self, user_message: str, technical_detail: str = "") -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical_detail = technical_detail


@dataclass(slots=True, frozen=True)
class _Candidate:
    path: Path
    size_bytes: int
    quality: int
    scale_factor: float
    attempt: int


class AnimatedImageConverterService:
    DEFAULT_TARGET_ATTEMPTS = 6

    def __init__(self) -> None:
        self.ffmpeg = find_executable("ffmpeg.exe") or find_executable("ffmpeg")
        self.ffprobe = find_executable("ffprobe.exe") or find_executable("ffprobe")
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()
        self._active_log_path: Path | None = None

    def probe(self, input_path: str) -> VideoProbeResult:
        if self.ffprobe is None:
            raise ConversionExecutionError(
                "FFprobe를 찾을 수 없어서 영상 정보를 읽지 못했습니다.",
                "설정 → 도구 및 리소스에서 FFprobe 상태를 확인해 주세요.",
            )

        command = [
            str(self.ffprobe),
            "-v", "error",
            "-print_format", "json",
            "-show_streams",
            "-show_format",
            input_path,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if sys.platform == "win32"
                    else 0
                ),
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ConversionExecutionError(
                "영상 정보를 읽는 과정에서 문제가 발생했습니다.",
                str(error),
            ) from error

        if result.returncode != 0:
            raise ConversionExecutionError(
                "선택한 파일에서 영상 정보를 읽지 못했습니다.",
                result.stderr.strip() or result.stdout.strip(),
            )

        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise ConversionExecutionError(
                "FFprobe 응답을 해석하지 못했습니다.",
                str(error),
            ) from error

        streams = payload.get("streams", [])
        video_stream = next(
            (
                stream
                for stream in streams
                if stream.get("codec_type") == "video"
            ),
            None,
        )
        if not isinstance(video_stream, dict):
            raise ConversionExecutionError(
                "영상 스트림이 없는 파일입니다.",
                input_path,
            )

        width = int(video_stream.get("width") or 0)
        height = int(video_stream.get("height") or 0)
        duration = self._parse_duration(payload, video_stream)
        fps = self._parse_rate(
            str(
                video_stream.get("avg_frame_rate")
                or video_stream.get("r_frame_rate")
                or "0/1"
            )
        )
        format_name = str(payload.get("format", {}).get("format_name", ""))
        video_codec = str(video_stream.get("codec_name", ""))

        if width <= 0 or height <= 0 or duration <= 0:
            raise ConversionExecutionError(
                "영상의 크기나 재생 시간을 확인하지 못했습니다.",
                result.stdout[-2000:],
            )

        return VideoProbeResult(
            path=input_path,
            width=width,
            height=height,
            duration=duration,
            fps=fps,
            format_name=format_name,
            video_codec=video_codec,
        )

    def convert(
        self,
        input_path: str,
        probe: VideoProbeResult,
        options: ConversionOptions,
        cancel_event: threading.Event,
        on_progress: ProgressCallback,
        on_phase: PhaseCallback,
        on_attempt: AttemptCallback,
        on_process: ProcessCallback,
    ) -> ConversionResult:
        if self.ffmpeg is None:
            raise ConversionExecutionError(
                "FFmpeg를 찾을 수 없어서 변환을 시작하지 못했습니다.",
                "설정 → 도구 및 리소스에서 FFmpeg 상태를 확인해 주세요.",
            )

        self._active_log_path = create_conversion_log_path(options.output_format)
        ffmpeg_version = self._ffmpeg_version_line()
        append_conversion_log(
            self._active_log_path,
            f"RR-V conversion started: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
            f"input={input_path}\n"
            f"format={options.output_format} mode={options.mode} quality={options.quality} "
            f"fps={options.fps} resize={options.resize_mode} "
            f"target_mb={options.target_mb} target_strategy={options.target_strategy} "
            f"target_attempts={options.target_attempts}\n"
            f"ffmpeg={self.ffmpeg}\n"
            f"ffmpeg_version={ffmpeg_version}\n\n",
        )
        write_converter_event(
            "conversion.start",
            format=options.output_format,
            mode=options.mode,
            input=input_path,
            log=self._active_log_path,
        )

        input_file = Path(input_path)
        if not input_file.is_file():
            raise ConversionExecutionError(
                "입력 영상 파일을 찾을 수 없습니다.",
                input_path,
            )

        output_directory = self._resolve_output_directory(input_file, options)
        try:
            output_directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ConversionExecutionError(
                "출력 폴더를 만들거나 사용할 수 없습니다.",
                str(error),
            ) from error

        if not os.access(output_directory, os.W_OK):
            raise ConversionExecutionError(
                "선택한 출력 폴더에 파일을 쓸 수 없습니다.",
                str(output_directory),
            )

        output_path = self._resolve_output_path(
            input_file,
            output_directory,
            options.output_format,
        )

        if options.mode != MODE_TARGET:
            on_attempt(1, 1, "직접 설정으로 변환")
            self._run_attempt(
                input_path=input_path,
                output_path=output_path,
                probe=probe,
                options=options,
                quality=options.quality,
                scale_factor=1.0,
                cancel_event=cancel_event,
                on_progress=on_progress,
                on_phase=on_phase,
                on_process=on_process,
            )
            result = ConversionResult(
                output_path=str(output_path),
                size_bytes=output_path.stat().st_size,
                attempts=1,
            )
            write_converter_event(
                "conversion.success",
                format=options.output_format,
                attempts=1,
                size=result.size_bytes,
                output=result.output_path,
                log=self._active_log_path,
            )
            return result

        if (
            options.output_format == FORMAT_APNG
            and options.target_strategy == TARGET_STRATEGY_QUALITY
        ):
            raise ConversionExecutionError(
                "APNG는 품질 수치만으로 용량을 안정적으로 줄일 수 없습니다.",
                "목표 용량 모드에서 ‘품질 유지, 이미지 크기 조절’을 선택해 주세요.",
            )

        result = self._convert_to_target(
            input_path=input_path,
            output_path=output_path,
            probe=probe,
            options=options,
            cancel_event=cancel_event,
            on_progress=on_progress,
            on_phase=on_phase,
            on_attempt=on_attempt,
            on_process=on_process,
        )
        write_converter_event(
            "conversion.success",
            format=options.output_format,
            attempts=result.attempts,
            size=result.size_bytes,
            output=result.output_path,
            log=self._active_log_path,
        )
        return result

    def cancel(self) -> None:
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
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass

    def _convert_to_target(
        self,
        input_path: str,
        output_path: Path,
        probe: VideoProbeResult,
        options: ConversionOptions,
        cancel_event: threading.Event,
        on_progress: ProgressCallback,
        on_phase: PhaseCallback,
        on_attempt: AttemptCallback,
        on_process: ProcessCallback,
    ) -> ConversionResult:
        target_bytes = max(1, int(options.target_mb * 1024 * 1024))
        best_valid: _Candidate | None = None
        smallest_size: int | None = None
        attempts_run = 0

        if options.target_strategy == TARGET_STRATEGY_QUALITY:
            low = 5
            high = max(low, options.quality)
            current_quality = high
            current_scale = 1.0
        else:
            low_scale = 0.18
            high_scale = 1.0
            current_scale = high_scale
            current_quality = options.quality

        max_attempts = min(10, max(3, int(options.target_attempts or self.DEFAULT_TARGET_ATTEMPTS)))

        try:
            for attempt in range(1, max_attempts + 1):
                if cancel_event.is_set():
                    raise ConversionCancelledError("변환 중지됨")

                attempts_run = attempt
                if options.target_strategy == TARGET_STRATEGY_QUALITY:
                    detail = f"품질 {current_quality}로 시험 변환"
                    attempt_scale = 1.0
                    attempt_quality = current_quality
                else:
                    percent_scale = max(1, round(current_scale * 100))
                    detail = f"이미지 크기 {percent_scale}%로 시험 변환"
                    attempt_scale = current_scale
                    attempt_quality = current_quality

                on_attempt(attempt, max_attempts, detail)
                temp_path = output_path.with_name(
                    f".{output_path.stem}.rrv-{uuid4().hex[:8]}.{options.output_format}"
                )

                self._run_attempt(
                    input_path=input_path,
                    output_path=temp_path,
                    probe=probe,
                    options=options,
                    quality=attempt_quality,
                    scale_factor=attempt_scale,
                    cancel_event=cancel_event,
                    on_progress=on_progress,
                    on_phase=on_phase,
                    on_process=on_process,
                )
                size_bytes = temp_path.stat().st_size
                smallest_size = (
                    size_bytes
                    if smallest_size is None
                    else min(smallest_size, size_bytes)
                )
                candidate = _Candidate(
                    path=temp_path,
                    size_bytes=size_bytes,
                    quality=attempt_quality,
                    scale_factor=attempt_scale,
                    attempt=attempt,
                )
                on_phase(
                    f"시험 결과 {self._format_size(size_bytes)} · "
                    f"목표 {self._format_size(target_bytes)} 이하"
                )

                if size_bytes <= target_bytes:
                    is_better = (
                        best_valid is None
                        or (
                            options.target_strategy == TARGET_STRATEGY_QUALITY
                            and candidate.quality > best_valid.quality
                        )
                        or (
                            options.target_strategy != TARGET_STRATEGY_QUALITY
                            and candidate.scale_factor > best_valid.scale_factor
                        )
                    )
                    if is_better:
                        if best_valid is not None and best_valid.path.exists():
                            best_valid.path.unlink(missing_ok=True)
                        best_valid = candidate
                    else:
                        temp_path.unlink(missing_ok=True)
                else:
                    temp_path.unlink(missing_ok=True)

                if options.target_strategy == TARGET_STRATEGY_QUALITY:
                    if size_bytes <= target_bytes:
                        low = current_quality + 1
                    else:
                        high = current_quality - 1
                    if low > high:
                        break
                    current_quality = (low + high) // 2
                else:
                    if size_bytes <= target_bytes:
                        low_scale = current_scale + 0.01
                    else:
                        high_scale = current_scale - 0.01
                    if high_scale - low_scale < 0.025:
                        break
                    current_scale = (low_scale + high_scale) / 2.0

            if best_valid is None:
                write_converter_event(
                    "conversion.target_not_met",
                    format=options.output_format,
                    attempts=attempts_run,
                    target_mb=options.target_mb,
                    log=self._active_log_path or "",
                )
                smallest_text = (
                    self._format_size(smallest_size)
                    if smallest_size is not None
                    else "확인 불가"
                )
                raise ConversionExecutionError(
                    "현재 조건으로 목표 용량 이하를 만들지 못했습니다.",
                    f"가장 작은 결과: {smallest_text}\n"
                    f"목표: {self._format_size(target_bytes)}\n"
                    "FPS를 낮추거나 이미지 크기 조절 방식을 사용해 주세요.",
                )

            if output_path.exists():
                output_path.unlink()
            best_valid.path.replace(output_path)
            return ConversionResult(
                output_path=str(output_path),
                size_bytes=output_path.stat().st_size,
                attempts=attempts_run,
            )
        finally:
            if best_valid is not None and best_valid.path.exists():
                try:
                    best_valid.path.unlink()
                except OSError:
                    pass

    def _run_attempt(
        self,
        input_path: str,
        output_path: Path,
        probe: VideoProbeResult,
        options: ConversionOptions,
        quality: int,
        scale_factor: float,
        cancel_event: threading.Event,
        on_progress: ProgressCallback,
        on_phase: PhaseCallback,
        on_process: ProcessCallback,
    ) -> None:
        command = self._build_command(
            input_path,
            output_path,
            probe,
            options,
            quality,
            scale_factor,
        )
        started = perf_counter()
        raw_log_path = self._active_log_path
        if raw_log_path is not None:
            append_conversion_log(
                raw_log_path,
                "-" * 72 + "\n"
                f"attempt started: {datetime.now():%H:%M:%S}\n"
                f"quality={quality} scale_factor={scale_factor:.4f}\n"
                f"command={subprocess.list2cmdline(command)}\n"
                + "-" * 72 + "\n",
            )
        creation_flags = 0
        popen_kwargs: dict[str, object] = {}
        if sys.platform == "win32":
            creation_flags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        else:
            popen_kwargs["start_new_session"] = True

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creation_flags,
                **popen_kwargs,
            )
        except OSError as error:
            raise ConversionExecutionError(
                "FFmpeg를 실행하지 못했습니다.",
                str(error),
            ) from error

        with self._process_lock:
            self._process = process
        on_process(process.pid)
        write_converter_event(
            "ffmpeg.start",
            pid=process.pid,
            format=options.output_format,
            output=output_path,
            log=raw_log_path or "",
        )
        on_phase("프레임 변환 중…")
        captured_lines: list[str] = []
        last_progress = -1
        effective_fps = probe.fps if options.fps == "원본" else float(options.fps)
        expected_frames = max(1.0, probe.duration * max(0.1, effective_fps))

        try:
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.strip()
                if cancel_event.is_set():
                    self.cancel()
                    raise ConversionCancelledError("변환 중지됨")

                captured_lines.append(line)
                if len(captured_lines) > 100:
                    captured_lines.pop(0)
                if raw_log_path is not None:
                    append_conversion_log(raw_log_path, line + "\n")

                percent: int | None = None
                if line.startswith("frame="):
                    value = line.partition("=")[2].strip()
                    try:
                        frame = int(value)
                    except ValueError:
                        frame = 0
                    if frame > 0:
                        percent = int(min(99.0, max(0.0, frame / expected_frames * 100.0)))
                elif line.startswith("out_time_us="):
                    value = line.partition("=")[2]
                    try:
                        seconds = int(value) / 1_000_000.0
                    except ValueError:
                        seconds = 0.0
                    if seconds > 0:
                        percent = int(
                            min(99.0, max(0.0, seconds / probe.duration * 100.0))
                        )
                elif line == "progress=end":
                    percent = 100

                if percent is not None and percent > last_progress:
                    last_progress = percent
                    on_progress(percent)

            return_code = process.wait()
            elapsed = perf_counter() - started
            if raw_log_path is not None:
                append_conversion_log(
                    raw_log_path,
                    f"ffmpeg return_code={return_code} elapsed={elapsed:.3f}s\n\n",
                )
            write_converter_event(
                "ffmpeg.finish",
                pid=process.pid,
                return_code=return_code,
                elapsed=f"{elapsed:.3f}s",
                output=output_path,
                log=raw_log_path or "",
            )
        except ConversionCancelledError:
            if output_path.exists():
                try:
                    output_path.unlink()
                except OSError:
                    pass
            raise
        finally:
            with self._process_lock:
                self._process = None

        if cancel_event.is_set():
            if output_path.exists():
                try:
                    output_path.unlink()
                except OSError:
                    pass
            raise ConversionCancelledError("변환 중지됨")
        if return_code != 0 or not output_path.is_file():
            detail = "\n".join(captured_lines[-50:])
            if output_path.exists():
                try:
                    output_path.unlink()
                except OSError:
                    pass
            write_converter_event(
                "ffmpeg.failed",
                format=options.output_format,
                return_code=return_code,
                output=output_path,
                log=raw_log_path or "",
            )
            raise ConversionExecutionError(
                self._friendly_ffmpeg_error(detail, options.output_format),
                detail,
            )

    def _build_command(
        self,
        input_path: str,
        output_path: Path,
        probe: VideoProbeResult,
        options: ConversionOptions,
        quality: int,
        scale_factor: float,
    ) -> list[str]:
        filters = self._base_filters(probe, options, scale_factor)
        command = [
            str(self.ffmpeg),
            "-hide_banner",
            "-y",
            "-i", input_path,
            "-an",
        ]

        if options.output_format == FORMAT_GIF:
            base_filter = ",".join(filters) if filters else "null"
            max_colors = max(16, min(256, round(16 + quality / 100 * 240)))
            complex_filter = (
                f"[0:v]{base_filter},split[s0][s1];"
                f"[s0]palettegen=max_colors={max_colors}:stats_mode=diff[p];"
                f"[s1][p]paletteuse=dither=sierra2_4a[v]"
            )
            command.extend([
                "-filter_complex", complex_filter,
                "-map", "[v]",
                "-loop", "0",
            ])
        else:
            command.extend(["-map", "0:v:0"])
            if filters:
                command.extend(["-vf", ",".join(filters)])

            if options.output_format == FORMAT_WEBP:
                command.extend([
                    "-c:v", "libwebp",
                    "-q:v", str(quality),
                    "-compression_level", "4",
                    "-loop", "0",
                ])
            elif options.output_format == FORMAT_APNG:
                command.extend([
                    "-c:v", "apng",
                    "-plays", "0",
                    "-f", "apng",
                ])
            elif options.output_format == FORMAT_AVIF:
                crf = max(0, min(63, round((100 - quality) * 0.63)))
                command.extend([
                    "-c:v", "libaom-av1",
                    "-crf", str(crf),
                    "-b:v", "0",
                    "-cpu-used", "6",
                    "-still-picture", "0",
                    "-pix_fmt", "yuv420p",
                    "-f", "avif",
                ])
            else:
                raise ConversionExecutionError(
                    "지원하지 않는 출력 형식입니다.",
                    options.output_format,
                )

        command.extend([
            "-stats_period", "0.25",
            "-progress", "pipe:1",
            "-nostats",
            str(output_path),
        ])
        return command

    def _base_filters(
        self,
        probe: VideoProbeResult,
        options: ConversionOptions,
        scale_factor: float,
    ) -> list[str]:
        filters: list[str] = []
        if options.fps != "원본":
            filters.append(f"fps={int(options.fps)}")

        width, height = self._base_dimensions(probe, options)
        if scale_factor < 0.999:
            width = max(2, self._even(width * scale_factor))
            height = max(2, self._even(height * scale_factor))

        if width != probe.width or height != probe.height:
            filters.append(
                f"scale={width}:{height}:flags=lanczos"
            )
        return filters

    def _base_dimensions(
        self,
        probe: VideoProbeResult,
        options: ConversionOptions,
    ) -> tuple[int, int]:
        if options.resize_mode == RESIZE_ORIGINAL:
            return self._even(probe.width), self._even(probe.height)
        if options.resize_mode == RESIZE_WIDTH:
            width = self._even(options.width)
            height = self._even(width * probe.height / probe.width)
            return width, height
        if options.resize_mode == RESIZE_HEIGHT:
            height = self._even(options.height)
            width = self._even(height * probe.width / probe.height)
            return width, height
        if options.resize_mode == RESIZE_CUSTOM:
            return self._even(options.width), self._even(options.height)
        return self._even(probe.width), self._even(probe.height)

    def _resolve_output_directory(
        self,
        input_file: Path,
        options: ConversionOptions,
    ) -> Path:
        if options.output_mode == OUTPUT_CUSTOM:
            folder = Path(options.output_folder).expanduser()
            if str(folder).strip():
                return folder
        return input_file.parent

    def _resolve_output_path(
        self,
        input_file: Path,
        output_directory: Path,
        extension: str,
    ) -> Path:
        normalized_stem = unicodedata.normalize("NFC", input_file.stem).strip()
        if not normalized_stem:
            normalized_stem = "converted"

        base_path = output_directory / f"{normalized_stem}.{extension}"
        collision_mode = load_general_preferences().file_collision_mode
        if collision_mode == FILE_COLLISION_OVERWRITE:
            return base_path
        if not base_path.exists():
            return base_path

        index = 2
        while True:
            candidate = output_directory / f"{normalized_stem} ({index}).{extension}"
            if not candidate.exists():
                return candidate
            index += 1


    def _ffmpeg_version_line(self) -> str:
        if self.ffmpeg is None:
            return "unknown"
        try:
            result = subprocess.run(
                [str(self.ffmpeg), "-version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if sys.platform == "win32"
                    else 0
                ),
            )
        except (OSError, subprocess.SubprocessError):
            return "unknown"
        output = result.stdout.strip() or result.stderr.strip()
        return output.splitlines()[0] if output else "unknown"

    @staticmethod
    def _parse_duration(payload: dict, video_stream: dict) -> float:
        values = (
            video_stream.get("duration"),
            payload.get("format", {}).get("duration"),
        )
        for value in values:
            try:
                duration = float(value)
            except (TypeError, ValueError):
                continue
            if duration > 0:
                return duration
        return 0.0

    @staticmethod
    def _parse_rate(value: str) -> float:
        try:
            numerator, denominator = value.split("/", 1)
            denominator_value = float(denominator)
            if denominator_value == 0:
                return 0.0
            return float(numerator) / denominator_value
        except (ValueError, ZeroDivisionError):
            return 0.0

    @staticmethod
    def _even(value: float | int) -> int:
        rounded = max(2, int(round(float(value))))
        return rounded if rounded % 2 == 0 else rounded - 1

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        return f"{size_bytes / (1024 * 1024):.1f}MB"

    @staticmethod
    def _friendly_ffmpeg_error(detail: str, output_format: str) -> str:
        lowered = detail.lower()
        if "unknown encoder" in lowered or "encoder not found" in lowered:
            return f"현재 FFmpeg가 {output_format.upper()} 인코더를 지원하지 않습니다."
        if "unrecognized option" in lowered and "vsync" in lowered and output_format == FORMAT_WEBP:
            return "현재 FFmpeg에서는 WebP 변환 옵션 중 일부가 맞지 않습니다. WebP 명령을 다시 확인해 주세요."
        if "invalid argument" in lowered and output_format == FORMAT_AVIF:
            return "현재 FFmpeg 구성에서는 움직이는 AVIF 출력을 지원하지 않는 것으로 보입니다."
        if "permission denied" in lowered:
            return "출력 파일을 쓸 수 없습니다. 파일이 열려 있거나 권한이 부족할 수 있습니다."
        return "움직이는 이미지 변환에 실패했습니다."
