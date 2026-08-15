from __future__ import annotations

from bisect import bisect_right
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter

from app.general_preferences import FILE_COLLISION_OVERWRITE, load_general_preferences
from app.paths import find_executable
from app.snapshot_log import (
    append_snapshot_task_log,
    create_snapshot_task_log_path,
    write_snapshot_event,
)
from core.snapshot_models import (
    OUTPUT_CUSTOM,
    SIZE_HEIGHT,
    SnapshotOptions,
    SnapshotProbeResult,
    SnapshotResult,
)


SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".ts"}


class SnapshotCancelledError(RuntimeError):
    pass


class SnapshotExecutionError(RuntimeError):
    def __init__(self, user_message: str, technical_detail: str = "") -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical_detail = technical_detail


class SnapshotService:
    def __init__(self) -> None:
        self.ffmpeg = find_executable("ffmpeg.exe") or find_executable("ffmpeg")
        self.ffprobe = find_executable("ffprobe.exe") or find_executable("ffprobe")
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()

    def probe(self, input_path: str) -> SnapshotProbeResult:
        path = Path(input_path)
        if not path.is_file():
            raise SnapshotExecutionError("영상 파일을 찾을 수 없습니다.", str(path))
        if self.ffprobe is None:
            raise SnapshotExecutionError("FFprobe를 찾을 수 없습니다.")

        command = [
            str(self.ffprobe), "-v", "error",
            "-show_streams", "-show_format", "-of", "json", str(path),
        ]
        result = self._run_simple(command, timeout=35)
        if result.returncode != 0:
            raise SnapshotExecutionError(
                "영상 정보를 확인하지 못했습니다.",
                result.stderr.strip() or result.stdout.strip(),
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise SnapshotExecutionError("FFprobe 응답을 해석하지 못했습니다.", str(error)) from error

        streams = payload.get("streams", []) if isinstance(payload, dict) else []
        video_stream = None
        for stream in streams if isinstance(streams, list) else []:
            if not isinstance(stream, dict) or stream.get("codec_type") != "video":
                continue
            disposition = stream.get("disposition", {})
            if isinstance(disposition, dict) and int(disposition.get("attached_pic", 0) or 0) == 1:
                continue
            video_stream = stream
            break
        if video_stream is None:
            raise SnapshotExecutionError("영상 스트림을 찾을 수 없습니다.", str(path))

        fmt = payload.get("format", {}) if isinstance(payload, dict) else {}
        duration = self._float_value(video_stream.get("duration"))
        if duration <= 0 and isinstance(fmt, dict):
            duration = self._float_value(fmt.get("duration"))
        width = int(video_stream.get("width", 0) or 0)
        height = int(video_stream.get("height", 0) or 0)
        stream_index = int(video_stream.get("index", 0) or 0)
        if duration <= 0 or width <= 0 or height <= 0:
            raise SnapshotExecutionError("영상 길이나 해상도를 확인하지 못했습니다.", str(path))

        try:
            file_size = path.stat().st_size
        except OSError:
            file_size = 0

        frame_rate = self._rate_value(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))
        bit_rate = self._int_value(video_stream.get("bit_rate"))
        if bit_rate <= 0 and isinstance(fmt, dict):
            bit_rate = self._int_value(fmt.get("bit_rate"))

        return SnapshotProbeResult(
            input_path=str(path),
            stream_index=stream_index,
            width=width,
            height=height,
            duration_seconds=duration,
            codec_name=str(video_stream.get("codec_name", "")).upper(),
            file_size_bytes=file_size,
            frame_rate=frame_rate,
            bit_rate=bit_rate,
            profile=str(video_stream.get("profile", "") or ""),
            pixel_format=str(video_stream.get("pix_fmt", "") or ""),
            container_name=str(fmt.get("format_name", "") if isinstance(fmt, dict) else ""),
        )

    def create_snapshot(
        self,
        input_path: str,
        probe: SnapshotProbeResult,
        options: SnapshotOptions,
        cancel_event: threading.Event,
        on_progress=None,
        on_phase=None,
    ) -> SnapshotResult:
        if self.ffmpeg is None:
            raise SnapshotExecutionError("FFmpeg를 찾을 수 없습니다.")
        input_file = Path(input_path)
        if not input_file.is_file():
            raise SnapshotExecutionError("영상 파일을 찾을 수 없습니다.", str(input_file))

        columns = min(12, max(1, int(options.columns)))
        rows = min(30, max(1, int(options.rows)))
        shot_count = columns * rows
        margin = min(100, max(0, int(options.margin)))
        target_size = min(10000, max(480, int(options.target_size)))
        if shot_count > 360:
            raise SnapshotExecutionError("스냅샷 수가 너무 많습니다. 가로×세로를 360장 이하로 줄여 주세요.")

        shot_width, shot_height, sheet_width, sheet_height, header_height = self._sheet_geometry(
            probe, options, columns, rows, margin, target_size
        )
        if shot_width < 24 or shot_height < 24:
            raise SnapshotExecutionError("한 장의 크기가 너무 작습니다. 완성 이미지 크기나 격자 수를 조정해 주세요.")
        if sheet_width * sheet_height > 160_000_000:
            raise SnapshotExecutionError("완성 이미지가 너무 큽니다. 이미지 크기나 스냅샷 수를 줄여 주세요.")

        output_path = self._resolve_output_path(input_file, options)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        task_log = create_snapshot_task_log_path()
        interval = probe.duration_seconds / (shot_count + 1)
        task_started = time.monotonic()

        write_snapshot_event(
            "snapshot.start",
            input=input_file,
            output=output_path,
            grid=f"{columns}x{rows}",
            size=f"{sheet_width}x{sheet_height}",
            duration=f"{probe.duration_seconds:.3f}s",
            codec=probe.codec_name or "UNKNOWN",
            fps=f"{probe.frame_rate:.3f}" if probe.frame_rate > 0 else "unknown",
            bitrate=probe.bit_rate,
            log=task_log,
        )
        extract_width = self._even_floor(shot_width)
        extract_height = self._even_floor(shot_height)

        append_snapshot_task_log(
            task_log,
            f"input={input_file}\noutput={output_path}\n"
            f"source_duration={probe.duration_seconds:.3f}s\n"
            f"source_resolution={probe.width}x{probe.height}\n"
            f"source_codec={probe.codec_name or 'UNKNOWN'}\n"
            f"source_profile={probe.profile or 'unknown'}\n"
            f"source_pixel_format={probe.pixel_format or 'unknown'}\n"
            f"source_fps={probe.frame_rate:.3f}\n"
            f"source_bitrate={probe.bit_rate}\n"
            f"source_bitrate_mbps={probe.bit_rate / 1_000_000:.3f}\n"
            f"source_file_size={probe.file_size_bytes}\n"
            f"source_file_size_mb={probe.file_size_bytes / (1024 ** 2):.2f}\n"
            f"source_stream_index={probe.stream_index}\n"
            f"source_container={probe.container_name or 'unknown'}\n"
            f"grid={columns}x{rows}\nshot={shot_width}x{shot_height}\n"
            f"extract={extract_width}x{extract_height}\n"
            f"sheet={sheet_width}x{sheet_height}\ninterval={interval:.6f}\n",
        )

        keyframe_info = self._probe_keyframes(input_file, probe.stream_index, probe.frame_rate)
        keyframe_timestamps = keyframe_info["timestamps"]
        append_snapshot_task_log(
            task_log,
            f"keyframe_probe={keyframe_info['status']}\n"
            f"keyframe_probe_elapsed={keyframe_info['elapsed']:.3f}s\n"
            f"keyframe_count={len(keyframe_timestamps)}\n"
            f"keyframe_avg_gap={keyframe_info['avg_gap']:.3f}s\n"
            f"keyframe_min_gap={keyframe_info['min_gap']:.3f}s\n"
            f"keyframe_max_gap={keyframe_info['max_gap']:.3f}s\n"
            f"keyframe_avg_gap_frames={keyframe_info['avg_gap_frames']:.1f}\n",
        )

        if on_phase:
            on_phase("장면 추출 준비 중")
        if on_progress:
            on_progress(2)

        try:
            with tempfile.TemporaryDirectory(prefix="rrv_snapshot_") as temp_dir:
                temp_path = Path(temp_dir)
                scale_filter = (
                    f"scale={extract_width}:{extract_height}:force_original_aspect_ratio=decrease:flags=lanczos,"
                    f"pad={extract_width}:{extract_height}:(ow-iw)/2:(oh-ih)/2:color=black"
                )
                append_snapshot_task_log(
                    task_log,
                    "extract_mode=fast_seek\ndecoder_threads=2\nprocess_priority=below_normal_on_windows\n"
                    + "-" * 72 + "\n",
                )
                extract_started = time.monotonic()
                frame_elapsed_times: list[tuple[int, float]] = []
                for index in range(shot_count):
                    if cancel_event.is_set():
                        raise SnapshotCancelledError("스냅샷 생성 중지됨")
                    frame_number = index + 1
                    timestamp = interval * frame_number
                    frame_path = temp_path / f"shot_{frame_number:04d}.jpg"
                    if on_phase:
                        on_phase(f"장면 {frame_number}/{shot_count} 추출 중")
                    frame_elapsed = self._run_seek_extract(
                        input_file=input_file,
                        stream_index=probe.stream_index,
                        timestamp=timestamp,
                        output_path=frame_path,
                        scale_filter=scale_filter,
                        cancel_event=cancel_event,
                        task_log=task_log,
                        frame_number=frame_number,
                        shot_count=shot_count,
                    )
                    frame_elapsed_times.append((frame_number, frame_elapsed))
                    if on_progress:
                        on_progress(5 + min(65, int(round(frame_number / shot_count * 65))))

                extract_elapsed = time.monotonic() - extract_started
                if frame_elapsed_times:
                    values = [elapsed for _, elapsed in frame_elapsed_times]
                    slowest = sorted(frame_elapsed_times, key=lambda item: item[1], reverse=True)[:5]
                    slow_text = ", ".join(f"{number}:{elapsed:.3f}s" for number, elapsed in slowest)
                    append_snapshot_task_log(
                        task_log,
                        "-" * 72 + "\n"
                        f"extract_summary total={extract_elapsed:.3f}s avg={sum(values)/len(values):.3f}s "
                        f"min={min(values):.3f}s max={max(values):.3f}s\n"
                        f"slowest_frames={slow_text}\n",
                    )
                    if keyframe_timestamps:
                        backtracks = []
                        for frame_index in range(1, shot_count + 1):
                            target = interval * frame_index
                            previous = self._previous_keyframe(keyframe_timestamps, target)
                            if previous is not None:
                                backtracks.append(max(0.0, target - previous))
                        if backtracks:
                            append_snapshot_task_log(
                                task_log,
                                f"target_keyframe_backtrack avg={sum(backtracks)/len(backtracks):.3f}s "
                                f"max={max(backtracks):.3f}s\n",
                            )
                        append_snapshot_task_log(task_log, "slowest_keyframe_context:\n")
                        for frame_number, elapsed in slowest:
                            target = interval * frame_number
                            previous = self._previous_keyframe(keyframe_timestamps, target)
                            following = self._next_keyframe(keyframe_timestamps, target)
                            previous_text = f"{previous:.3f}s" if previous is not None else "none"
                            following_text = f"{following:.3f}s" if following is not None else "none"
                            backtrack_text = f"{max(0.0, target - previous):.3f}s" if previous is not None else "unknown"
                            append_snapshot_task_log(
                                task_log,
                                f"  frame={frame_number} target={target:.3f}s elapsed={elapsed:.3f}s "
                                f"prev_keyframe={previous_text} backtrack={backtrack_text} "
                                f"next_keyframe={following_text}\n",
                            )

                frame_paths = sorted(temp_path.glob("shot_*.jpg"))
                if not frame_paths:
                    raise SnapshotExecutionError("영상에서 장면을 추출하지 못했습니다.", str(input_file))

                if cancel_event.is_set():
                    raise SnapshotCancelledError("스냅샷 생성 중지됨")
                if on_phase:
                    on_phase("스냅샷 시트 조립 중")

                assemble_started = time.monotonic()
                sheet = QImage(sheet_width, sheet_height, QImage.Format.Format_RGB32)
                sheet.fill(QColor("white"))
                painter = QPainter(sheet)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                try:
                    if options.show_info:
                        self._draw_header(painter, input_file, probe, options, margin, sheet_width, header_height)

                    time_font = QFont(options.font_family or "Malgun Gothic")
                    time_font.setPointSize(max(8, int(options.time_font_size)))
                    painter.setFont(time_font)
                    time_metrics = QFontMetrics(time_font)

                    last_image = QImage()
                    for index in range(shot_count):
                        if cancel_event.is_set():
                            raise SnapshotCancelledError("스냅샷 생성 중지됨")
                        if index < len(frame_paths):
                            image = QImage(str(frame_paths[index]))
                            if not image.isNull():
                                last_image = image
                        image = last_image
                        if image.isNull():
                            continue

                        row = index // columns
                        col = index % columns
                        x = margin + col * (shot_width + margin)
                        y = header_height + row * (shot_height + margin)
                        painter.drawImage(QRect(x, y, shot_width, shot_height), image)

                        if options.show_time:
                            timestamp = interval * (index + 1)
                            text = self._duration_text(timestamp)
                            text_width = time_metrics.horizontalAdvance(text)
                            text_height = time_metrics.height()
                            pad_x = 6
                            pad_y = 3
                            bx = x + shot_width - text_width - pad_x * 2 - 5
                            by = y + shot_height - text_height - pad_y * 2 - 5
                            painter.fillRect(
                                QRect(bx, by, text_width + pad_x * 2, text_height + pad_y * 2),
                                QColor(0, 0, 0, 150),
                            )
                            painter.setPen(QColor("white"))
                            painter.drawText(
                                bx + pad_x,
                                by + pad_y + time_metrics.ascent(),
                                text,
                            )

                        if on_progress:
                            on_progress(72 + int(round((index + 1) / shot_count * 23)))
                finally:
                    painter.end()

                assemble_elapsed = time.monotonic() - assemble_started
                append_snapshot_task_log(task_log, f"assemble_elapsed={assemble_elapsed:.3f}s\n")

                if cancel_event.is_set():
                    raise SnapshotCancelledError("스냅샷 생성 중지됨")
                if on_phase:
                    on_phase("JPG 저장 중")
                save_started = time.monotonic()
                if not sheet.save(str(output_path), "JPG", 90):
                    raise SnapshotExecutionError("스냅샷 이미지를 저장하지 못했습니다.", str(output_path))
                save_elapsed = time.monotonic() - save_started
                append_snapshot_task_log(task_log, f"save_elapsed={save_elapsed:.3f}s\n")
                if on_progress:
                    on_progress(100)

            total_elapsed = time.monotonic() - task_started
            write_snapshot_event(
                "snapshot.success", input=input_file, output=output_path, elapsed=f"{total_elapsed:.3f}s", log=task_log
            )
            append_snapshot_task_log(task_log, f"total_elapsed={total_elapsed:.3f}s\n\nSUCCESS output={output_path}\n")
            return SnapshotResult(
                output_path=str(output_path),
                sheet_width=sheet_width,
                sheet_height=sheet_height,
                shot_count=shot_count,
            )
        except SnapshotCancelledError:
            write_snapshot_event("snapshot.cancelled", input=input_file, log=task_log)
            raise
        except SnapshotExecutionError:
            write_snapshot_event("snapshot.failed", input=input_file, log=task_log)
            raise
        except Exception as error:
            write_snapshot_event("snapshot.failed", input=input_file, error=repr(error), log=task_log)
            append_snapshot_task_log(task_log, f"\nERROR {error!r}\n")
            raise SnapshotExecutionError("스냅샷을 만드는 중 예상하지 못한 문제가 발생했습니다.", repr(error)) from error

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

    def _run_seek_extract(
        self,
        *,
        input_file: Path,
        stream_index: int,
        timestamp: float,
        output_path: Path,
        scale_filter: str,
        cancel_event: threading.Event,
        task_log: Path,
        frame_number: int,
        shot_count: int,
    ) -> float:
        command = [
            str(self.ffmpeg), "-hide_banner", "-y", "-loglevel", "error",
            "-threads", "2",
            "-ss", f"{timestamp:.6f}",
            "-i", str(input_file),
            "-map", f"0:{stream_index}",
            "-an",
            "-vf", scale_filter,
            "-frames:v", "1",
            "-threads", "1",
            "-q:v", "2",
            str(output_path),
        ]

        creation_flags = 0
        popen_kwargs: dict[str, object] = {}
        if sys.platform == "win32":
            creation_flags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
            )
        else:
            popen_kwargs["start_new_session"] = True

        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
                **popen_kwargs,
            )
        except OSError as error:
            raise SnapshotExecutionError("FFmpeg를 실행하지 못했습니다.", str(error)) from error

        with self._process_lock:
            self._process = process

        try:
            while process.poll() is None:
                if cancel_event.is_set():
                    self.cancel()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        try:
                            process.kill()
                        except OSError:
                            pass
                    raise SnapshotCancelledError("스냅샷 생성 중지됨")
                time.sleep(0.05)

            stderr_text = process.stderr.read() if process.stderr is not None else ""
            return_code = process.returncode
        finally:
            if process.stderr is not None:
                process.stderr.close()
            with self._process_lock:
                if self._process is process:
                    self._process = None

        elapsed = time.monotonic() - started
        if cancel_event.is_set():
            raise SnapshotCancelledError("스냅샷 생성 중지됨")

        if return_code != 0 or not output_path.is_file() or output_path.stat().st_size <= 0:
            append_snapshot_task_log(
                task_log,
                f"frame={frame_number}/{shot_count} time={timestamp:.3f}s elapsed={elapsed:.3f}s result=failed\n"
                + "command=" + subprocess.list2cmdline(command) + "\n"
                + ("stderr:\n" + stderr_text.strip() + "\n" if stderr_text.strip() else ""),
            )
            raise SnapshotExecutionError("영상 장면을 추출하지 못했습니다.", stderr_text.strip())

        slow_marker = " slow=1" if elapsed >= 1.5 else ""
        append_snapshot_task_log(
            task_log,
            f"frame={frame_number}/{shot_count} time={timestamp:.3f}s elapsed={elapsed:.3f}s result=ok{slow_marker}\n",
        )
        return elapsed

    def _probe_keyframes(self, input_file: Path, stream_index: int, frame_rate: float) -> dict[str, object]:
        info: dict[str, object] = {
            "status": "unavailable",
            "elapsed": 0.0,
            "timestamps": [],
            "avg_gap": 0.0,
            "min_gap": 0.0,
            "max_gap": 0.0,
            "avg_gap_frames": 0.0,
        }
        if self.ffprobe is None:
            info["status"] = "ffprobe_missing"
            return info

        command = [
            str(self.ffprobe), "-v", "error",
            "-select_streams", str(stream_index),
            "-show_entries", "packet=pts_time,flags",
            "-of", "csv=p=0",
            str(input_file),
        ]
        started = time.monotonic()
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                check=False,
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0),
            )
        except subprocess.TimeoutExpired:
            info["elapsed"] = time.monotonic() - started
            info["status"] = "timeout"
            return info
        except OSError:
            info["elapsed"] = time.monotonic() - started
            info["status"] = "error"
            return info

        info["elapsed"] = time.monotonic() - started
        if result.returncode != 0:
            info["status"] = "failed"
            return info

        timestamps: list[float] = []
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line or "," not in line:
                continue
            time_text, flags = line.rsplit(",", 1)
            if "K" not in flags:
                continue
            try:
                timestamp = float(time_text)
            except (TypeError, ValueError):
                continue
            if math.isfinite(timestamp) and timestamp >= 0:
                timestamps.append(timestamp)

        # Packet PTS can be reported out of decode order, so sort and de-duplicate.
        timestamps = sorted(set(timestamps))
        info["timestamps"] = timestamps
        if not timestamps:
            info["status"] = "no_keyframes"
            return info

        gaps = [later - earlier for earlier, later in zip(timestamps, timestamps[1:]) if later > earlier]
        if gaps:
            avg_gap = sum(gaps) / len(gaps)
            info["avg_gap"] = avg_gap
            info["min_gap"] = min(gaps)
            info["max_gap"] = max(gaps)
            info["avg_gap_frames"] = avg_gap * frame_rate if frame_rate > 0 else 0.0
        info["status"] = "ok"
        return info

    @staticmethod
    def _previous_keyframe(timestamps: list[float], target: float) -> float | None:
        position = bisect_right(timestamps, target) - 1
        if position < 0:
            return None
        return timestamps[position]

    @staticmethod
    def _next_keyframe(timestamps: list[float], target: float) -> float | None:
        position = bisect_right(timestamps, target)
        if position >= len(timestamps):
            return None
        return timestamps[position]

    def _sheet_geometry(self, probe, options, columns, rows, margin, target_size):
        if options.size_mode == SIZE_HEIGHT:
            grid_height = target_size
            shot_height = max(1, (grid_height - margin * (rows + 1)) // rows)
            shot_width = max(1, int(round(shot_height * probe.width / probe.height)))
            sheet_width = shot_width * columns + margin * (columns + 1)
        else:
            sheet_width = target_size
            shot_width = max(1, (sheet_width - margin * (columns + 1)) // columns)
            shot_height = max(1, int(round(shot_width * probe.height / probe.width)))
        header_height = self._header_height(options, margin)
        sheet_height = header_height + shot_height * rows + margin * (rows + 1)
        return shot_width, shot_height, sheet_width, sheet_height, header_height

    @staticmethod
    def _header_height(options: SnapshotOptions, margin: int) -> int:
        if not options.show_info:
            return margin
        return max(92, int(options.info_font_size) * 2 + 42)

    def _draw_header(self, painter, input_file, probe, options, margin, sheet_width, header_height):
        title_font = QFont(options.font_family or "Malgun Gothic")
        title_font.setPointSize(max(10, int(options.info_font_size) + 3))
        title_font.setBold(True)
        info_font = QFont(options.font_family or "Malgun Gothic")
        info_font.setPointSize(max(10, int(options.info_font_size)))

        painter.setPen(QColor("#27332E"))
        painter.setFont(title_font)
        title_metrics = QFontMetrics(title_font)
        title_y = margin + title_metrics.ascent()
        painter.drawText(margin, title_y, input_file.name)

        painter.setPen(QColor("#59645E"))
        painter.setFont(info_font)
        info_metrics = QFontMetrics(info_font)
        info_y = title_y + info_metrics.height() + 6
        details = (
            f"크기 {self._size_text(probe.file_size_bytes)}  ·  "
            f"길이 {self._duration_text(probe.duration_seconds)}  ·  "
            f"해상도 {probe.width}×{probe.height}"
        )
        painter.drawText(margin, info_y, details)
        line_y = max(info_y + 12, header_height - 10)
        painter.setPen(QColor("#D3D1C8"))
        painter.drawLine(margin, line_y, sheet_width - margin, line_y)

    def _resolve_output_path(self, input_file: Path, options: SnapshotOptions) -> Path:
        if options.output_mode == OUTPUT_CUSTOM:
            directory = Path(options.output_folder).expanduser()
        else:
            directory = input_file.parent
            if options.create_subfolder:
                name = self._safe_folder_name(options.subfolder_name) or "Snapshot"
                directory = directory / name

        stem = unicodedata.normalize("NFC", input_file.stem).strip() or "snapshot"
        base = directory / f"{stem}_snapshot.jpg"
        if load_general_preferences().file_collision_mode == FILE_COLLISION_OVERWRITE:
            return base
        if not base.exists():
            return base
        index = 2
        while True:
            candidate = directory / f"{stem}_snapshot ({index}).jpg"
            if not candidate.exists():
                return candidate
            index += 1

    @staticmethod
    def _safe_folder_name(name: str) -> str:
        cleaned = "".join(ch for ch in str(name).strip() if ch not in '<>:"/\\|?*')
        return cleaned.strip(" .")

    @staticmethod
    def _duration_text(seconds: float) -> str:
        total = max(0, int(round(seconds)))
        hours, rem = divmod(total, 3600)
        minutes, secs = divmod(rem, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def _size_text(size_bytes: int) -> str:
        if size_bytes >= 1024 ** 3:
            return f"{size_bytes / 1024 ** 3:.2f} GB"
        return f"{size_bytes / 1024 ** 2:.1f} MB"

    @staticmethod
    def _even_floor(value: int, minimum: int = 2) -> int:
        safe_value = max(minimum, int(value))
        if safe_value % 2:
            safe_value -= 1
        return max(minimum, safe_value)

    @staticmethod
    def _float_value(value: object) -> float:
        try:
            result = float(value)
            return result if math.isfinite(result) else 0.0
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _int_value(value: object) -> int:
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _rate_value(value: object) -> float:
        text = str(value or "").strip()
        if not text:
            return 0.0
        if "/" in text:
            left, right = text.split("/", 1)
            try:
                denominator = float(right)
                if denominator == 0:
                    return 0.0
                result = float(left) / denominator
                return result if math.isfinite(result) else 0.0
            except (TypeError, ValueError, ZeroDivisionError):
                return 0.0
        return SnapshotService._float_value(text)

    @staticmethod
    def _run_simple(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0),
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise SnapshotExecutionError("외부 도구를 실행하지 못했습니다.", str(error)) from error
