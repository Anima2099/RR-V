from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import unicodedata
from time import perf_counter
from typing import Callable

from app.download_log import create_task_log_path, write_download_event
from app.general_preferences import (
    FILE_COLLISION_OVERWRITE,
    load_general_preferences,
)
from app.paths import RRV_TOOLS_DIR, find_executable
from core.download_task import DownloadTask
from services.ytdlp_service import YtDlpService


ProgressCallback = Callable[[int, str, str, int, int, bool], None]
PhaseCallback = Callable[[str, str], None]
ProcessCallback = Callable[[int], None]


class DownloadCancelledError(RuntimeError):
    pass


class DownloadExecutionError(RuntimeError):
    def __init__(self, user_message: str, technical_detail: str = "") -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical_detail = technical_detail


@dataclass(slots=True, frozen=True)
class DownloadResult:
    output_file: str
    raw_log_path: str


@dataclass(slots=True)
class _ProgressBytesTracker:
    """여러 다운로드 스트림의 용량을 뒤로 가지 않게 누적한다."""

    completed_downloaded: int = 0
    completed_total: int = 0
    completed_estimated: bool = False
    current_downloaded: int = 0
    current_total: int = 0
    current_estimated: bool = False
    awaiting_next_stream: bool = False

    def update(
        self,
        status: str,
        downloaded_bytes: int,
        total_bytes: int,
        total_bytes_estimate: int,
    ) -> tuple[int, int, bool]:
        downloaded = max(0, downloaded_bytes)
        exact_total = max(0, total_bytes)
        estimated_total = max(0, total_bytes_estimate)
        chosen_total = exact_total or estimated_total
        is_estimated = exact_total <= 0 and estimated_total > 0

        if status != "finished":
            if self.awaiting_next_stream:
                self.current_downloaded = 0
                self.current_total = 0
                self.current_estimated = False
                self.awaiting_next_stream = False

            self.current_downloaded = max(self.current_downloaded, downloaded)
            if chosen_total > 0:
                self.current_total = max(chosen_total, self.current_downloaded)
                self.current_estimated = is_estimated

            return (
                self.completed_downloaded + self.current_downloaded,
                (
                    self.completed_total + self.current_total
                    if self.current_total > 0
                    else 0
                ),
                self.completed_estimated or self.current_estimated,
            )

        # 같은 스트림에서 finished가 중복 출력되는 경우 이중 합산하지 않는다.
        if self.awaiting_next_stream:
            return (
                self.completed_downloaded,
                self.completed_total,
                self.completed_estimated,
            )

        self.current_downloaded = max(self.current_downloaded, downloaded)
        if chosen_total > 0:
            self.current_total = max(chosen_total, self.current_downloaded)
            self.current_estimated = is_estimated
        else:
            self.current_total = max(self.current_total, self.current_downloaded)

        self.completed_downloaded += self.current_downloaded
        self.completed_total += self.current_total
        self.completed_estimated = (
            self.completed_estimated or self.current_estimated
        )
        self.current_downloaded = 0
        self.current_total = 0
        self.current_estimated = False
        self.awaiting_next_stream = True
        return (
            self.completed_downloaded,
            self.completed_total,
            self.completed_estimated,
        )


class YtDlpDownloadService:
    PROGRESS_PREFIX = "RRV_PROGRESS|"
    OUTPUT_PREFIX = "RRV_OUTPUT|"

    def __init__(self) -> None:
        self.executable = find_executable("yt-dlp.exe")
        self.ffmpeg = find_executable("ffmpeg.exe")
        self.ffprobe = find_executable("ffprobe.exe")
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()

    def download(
        self,
        task: DownloadTask,
        cancel_event: threading.Event,
        on_progress: ProgressCallback,
        on_phase: PhaseCallback,
        on_process: ProcessCallback,
    ) -> DownloadResult:
        if self.executable is None:
            raise DownloadExecutionError(
                "yt-dlp.exe를 찾을 수 없어서 다운로드를 시작할 수 없습니다.",
                f"RR-V 도구 폴더: {RRV_TOOLS_DIR}",
            )

        save_directory = Path(task.save_path).expanduser()
        try:
            save_directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise DownloadExecutionError(
                "저장 폴더를 만들거나 사용할 수 없습니다.",
                str(error),
            ) from error

        if not os.access(save_directory, os.W_OK):
            raise DownloadExecutionError(
                "선택한 저장 폴더에 파일을 쓸 수 없습니다.",
                str(save_directory),
            )

        task.title = unicodedata.normalize("NFC", task.title)
        collision_mode = load_general_preferences().file_collision_mode
        overwrite_existing = collision_mode == FILE_COLLISION_OVERWRITE

        output_stem = unicodedata.normalize("NFC", task.output_stem).strip()
        if not output_stem:
            filename_title = self._filename_title(task)
            if overwrite_existing:
                output_stem = self._sanitize_filename(filename_title)
            else:
                output_stem = self._choose_unique_stem(
                    save_directory,
                    filename_title,
                )
        task.output_stem = output_stem
        task_log_path = create_task_log_path(task.task_id)
        task.raw_log_path = str(task_log_path)
        command = self._build_command(
            task,
            save_directory,
            output_stem,
            overwrite_existing=overwrite_existing,
        )

        write_download_event(
            "download.start_requested",
            task_id=task.task_id,
            title=task.title,
            save_path=save_directory,
            output_stem=output_stem,
            collision_mode=collision_mode,
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

        started = perf_counter()
        final_output = ""
        captured_lines: list[str] = []
        progress_bytes = _ProgressBytesTracker()

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
            raise DownloadExecutionError(
                "yt-dlp.exe를 실행하지 못했습니다.",
                str(error),
            ) from error

        with self._process_lock:
            self._process = process

        on_process(process.pid)
        write_download_event(
            "download.process_started",
            task_id=task.task_id,
            pid=process.pid,
            raw_log=task_log_path,
        )

        try:
            with task_log_path.open("w", encoding="utf-8") as raw_log:
                raw_log.write("RR-V yt-dlp task log\n")
                raw_log.write(f"Task: {task.task_id}\n")
                raw_log.write(f"Title: {task.title}\n")
                raw_log.write(f"URL: {task.url}\n")
                raw_log.write(f"Authentication: {YtDlpService.authentication_summary(task.url)}\n")
                raw_log.write(f"JavaScript runtime: {YtDlpService.javascript_runtime_summary(task.url)}\n")
                raw_log.write(f"YouTube support runtime: {YtDlpService.youtube_support_runtime_summary(task.url)}\n")
                raw_log.write(f"Command: {self._display_command(command)}\n")
                raw_log.write("=" * 72 + "\n")
                raw_log.flush()

                assert process.stdout is not None
                for raw_line in process.stdout:
                    line = raw_line.rstrip("\r\n")
                    line = self._sanitize_log_line(line, task.url)
                    raw_log.write(line + "\n")
                    raw_log.flush()
                    captured_lines.append(line)
                    if len(captured_lines) > 300:
                        captured_lines.pop(0)

                    if cancel_event.is_set():
                        self.cancel()
                        raise DownloadCancelledError("다운로드 중지됨")

                    if line.startswith(self.PROGRESS_PREFIX):
                        self._handle_progress_line(
                            line,
                            on_progress,
                            on_phase,
                            progress_bytes,
                        )
                        continue

                    if line.startswith(self.OUTPUT_PREFIX):
                        final_output = line[len(self.OUTPUT_PREFIX):].strip()
                        continue

                    phase = self._phase_from_line(line)
                    if phase is not None:
                        on_phase(*phase)

                return_code = process.wait()
        except DownloadCancelledError:
            write_download_event(
                "download.cancelled",
                task_id=task.task_id,
                pid=process.pid,
            )
            raise
        except OSError as error:
            self.cancel()
            raise DownloadExecutionError(
                "다운로드 로그를 기록하는 과정에서 문제가 발생했습니다.",
                str(error),
            ) from error
        finally:
            with self._process_lock:
                self._process = None

        elapsed_ms = (perf_counter() - started) * 1000.0

        if cancel_event.is_set():
            raise DownloadCancelledError("다운로드 중지됨")

        if return_code != 0:
            detail = "\n".join(captured_lines[-80:]).strip()
            write_download_event(
                "download.failed",
                task_id=task.task_id,
                return_code=return_code,
                elapsed_ms=f"{elapsed_ms:.1f}",
                raw_log=task_log_path,
            )
            raise DownloadExecutionError(
                self._friendly_error(detail, task.url),
                detail,
            )

        resolved_output = self._resolve_output_file(
            final_output,
            save_directory,
            output_stem,
            task,
        )
        if not resolved_output:
            raise DownloadExecutionError(
                "다운로드는 끝났지만 완성된 파일 위치를 확인하지 못했습니다.",
                f"저장 폴더: {save_directory}\n원본 로그: {task_log_path}",
            )

        if task.embed_subtitles and not task.audio_only:
            self._cleanup_embedded_subtitle_sidecars(
                resolved_output,
                save_directory,
                output_stem,
                task,
            )

        write_download_event(
            "download.completed",
            task_id=task.task_id,
            elapsed_ms=f"{elapsed_ms:.1f}",
            output=resolved_output,
            raw_log=task_log_path,
        )
        return DownloadResult(
            output_file=str(resolved_output),
            raw_log_path=str(task_log_path),
        )

    def cancel(self) -> None:
        with self._process_lock:
            process = self._process

        if process is None or process.poll() is not None:
            return

        pid = process.pid
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    timeout=5,
                    check=False,
                )
            else:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass

    def _build_command(
        self,
        task: DownloadTask,
        save_directory: Path,
        output_stem: str,
        *,
        overwrite_existing: bool,
    ) -> list[str]:
        assert self.executable is not None

        command = [
            str(self.executable),
            "--newline",
            "--no-color",
            "--no-playlist",
            "--windows-filenames",
            "--trim-filenames",
            "170",
            "--encoding",
            "utf-8",
            "--socket-timeout",
            "30",
            "--retries",
            "5",
            "--fragment-retries",
            "5",
            "--progress",
            "--progress-delta",
            "0.2",
            "--progress-template",
            "download:RRV_PROGRESS|%(progress.status)s|%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s",
            "--print",
            "after_move:RRV_OUTPUT|%(filepath)s",
            "-o",
            str(save_directory / f"{output_stem}.%(ext)s"),
        ]

        if overwrite_existing:
            command.append("--force-overwrites")

        if self.ffmpeg is not None:
            command.extend(["--ffmpeg-location", str(self.ffmpeg.parent)])

        YtDlpService.extend_runtime_and_auth_arguments(command, task.url)

        if task.audio_only:
            command.extend(["-f", "bestaudio/best", "-x"])
            command.extend(["--audio-format", task.audio_format.lower()])
            quality = self._audio_quality_value(task.audio_quality)
            if quality:
                command.extend(["--audio-quality", quality])
        else:
            command.extend(["-f", self._format_selector(task)])
            container = task.container.lower()
            command.extend(["--merge-output-format", container])
            command.extend(["--remux-video", container])

        manual_languages: list[str] = []
        automatic_languages: list[str] = []
        for encoded in task.subtitle_tracks:
            kind, separator, code = encoded.partition(":")
            if not separator or not code:
                continue
            if kind == "manual":
                manual_languages.append(code)
            elif kind == "auto":
                automatic_languages.append(code)

        selected_languages = self._ordered_unique(
            manual_languages + automatic_languages
        )
        # 오디오 전용 프리셋에서는 자막 설정을 실행하지 않는다. UI도 오디오
        # 전용일 때 자막 영역을 비활성화하므로 불필요한 SRT sidecar 다운로드를
        # 막아 동작을 일치시킨다.
        if selected_languages and not task.audio_only:
            if manual_languages:
                command.append("--write-subs")
            if automatic_languages:
                command.append("--write-auto-subs")
            command.extend(["--sub-langs", ",".join(selected_languages)])
            command.extend(["--sub-format", "srt/best"])
            command.extend(["--convert-subs", "srt"])
            if task.embed_subtitles and not task.audio_only:
                command.append("--embed-subs")

        if task.embed_thumbnail:
            command.append("--embed-thumbnail")
        if task.save_thumbnail:
            command.extend(["--write-thumbnail", "--convert-thumbnails", "jpg"])

        if task.preserve_metadata:
            command.extend(["--embed-metadata", "--embed-chapters"])

        command.append(task.url)
        return command

    @staticmethod
    def _format_selector(task: DownloadTask) -> str:
        height = YtDlpDownloadService._height_limit(task.resolution)
        height_filter = f"[height<={height}]" if height else ""
        codec_filters = {
            "H.264": "[vcodec^=avc1]",
            "VP9": "[vcodec^=vp9]",
            "AV1": "[vcodec^=av01]",
        }
        codec_filter = codec_filters.get(task.codec, "")
        container = task.container.lower()

        if container == "webm" and task.codec == "H.264":
            raise DownloadExecutionError(
                "WebM과 H.264 조합은 사용할 수 없습니다.",
                "파일 형식을 MP4/MKV로 바꾸거나 코덱을 VP9/AV1로 선택해 주세요.",
            )

        if container == "mp4" and task.codec == "H.264":
            return (
                f"bestvideo*{height_filter}[ext=mp4]{codec_filter}+bestaudio[ext=m4a]/"
                f"bestvideo*{height_filter}[ext=mp4]+bestaudio[ext=m4a]/"
                f"bestvideo*{height_filter}+bestaudio/best{height_filter}"
            )

        if container == "webm":
            return (
                f"bestvideo*{height_filter}[ext=webm]{codec_filter}+bestaudio[ext=webm]/"
                f"bestvideo*{height_filter}[ext=webm]+bestaudio[ext=webm]/"
                f"bestvideo*{height_filter}+bestaudio/best{height_filter}"
            )

        return (
            f"bestvideo*{height_filter}{codec_filter}+bestaudio/"
            f"bestvideo*{height_filter}+bestaudio/best{height_filter}"
        )

    @staticmethod
    def _height_limit(resolution: str) -> int | None:
        mapping = {
            "8K (4320p)": 4320,
            "4K (2160p)": 2160,
            "1440p": 1440,
            "1080p": 1080,
            "720p": 720,
            "480p": 480,
        }
        return mapping.get(resolution)

    @staticmethod
    def _audio_quality_value(quality: str) -> str:
        if quality == "최고":
            return "0"
        return quality.upper()

    @staticmethod
    def _handle_progress_line(
        line: str,
        on_progress: ProgressCallback,
        on_phase: PhaseCallback,
        bytes_tracker: _ProgressBytesTracker,
    ) -> None:
        parts = line.split("|", 7)
        if len(parts) < 8:
            return
        status = parts[1].strip().lower()
        percent_text = parts[2].strip()
        speed = YtDlpDownloadService._clean_progress_value(parts[3])
        eta = YtDlpDownloadService._clean_progress_value(parts[4])
        downloaded_bytes = YtDlpDownloadService._parse_progress_bytes(parts[5])
        total_bytes = YtDlpDownloadService._parse_progress_bytes(parts[6])
        total_bytes_estimate = YtDlpDownloadService._parse_progress_bytes(parts[7])
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", percent_text)
        percent = int(float(match.group(1))) if match else 0
        percent = max(0, min(100, percent))
        if status == "finished":
            percent = 100
            on_phase("postprocessing", "다운로드 마무리 중…")
        else:
            on_phase("downloading", "파일 다운로드 중…")
        received, total, estimated = bytes_tracker.update(
            status,
            downloaded_bytes,
            total_bytes,
            total_bytes_estimate,
        )
        on_progress(percent, speed, eta, received, total, estimated)

    @staticmethod
    def _phase_from_line(line: str) -> tuple[str, str] | None:
        lowered = line.lower()
        if "[merger]" in lowered:
            return "postprocessing", "영상과 오디오를 합치는 중…"
        if "[extractaudio]" in lowered:
            return "postprocessing", "오디오 파일을 변환하는 중…"
        if "[embedsubtitles]" in lowered or "[embedsubtitle]" in lowered:
            return "postprocessing", "자막을 영상에 내장하는 중…"
        if "[embedthumbnail]" in lowered or "thumbnailconvertor" in lowered or "thumbnailsconvertor" in lowered:
            return "postprocessing", "썸네일을 저장하고 내장하는 중…"
        if "[metadata]" in lowered:
            return "postprocessing", "메타데이터를 저장하는 중…"
        if "[ffmpeg]" in lowered or "[videoremuxer]" in lowered:
            return "postprocessing", "파일 형식을 정리하는 중…"
        return None

    @staticmethod
    def _clean_progress_value(value: str) -> str:
        cleaned = value.strip()
        if not cleaned or cleaned.lower() in {"na", "n/a", "none", "unknown"}:
            return "-"
        return cleaned

    @staticmethod
    def _parse_progress_bytes(value: str) -> int:
        cleaned = value.strip()
        if not cleaned or cleaned.lower() in {"na", "n/a", "none", "unknown"}:
            return 0
        try:
            return max(0, int(float(cleaned)))
        except (TypeError, ValueError, OverflowError):
            return 0

    @staticmethod
    def _filename_title(task: DownloadTask) -> str:
        """표시 제목은 유지하면서 저장 파일명에 필요한 최소 식별자만 보강한다."""
        title = unicodedata.normalize("NFC", task.title).strip() or "video"
        extractor = task.extractor.strip().lower()
        video_id = task.video_id.strip()
        if not extractor.startswith("instagram") or not video_id:
            return title
        if not title.lower().startswith("video by "):
            return title

        segments = {segment.lower() for segment in task.url.split("/") if segment}
        if not ({"reel", "reels"} & segments):
            return title
        if f"[{video_id}]" in title:
            return title
        return f"{title} [{video_id}]"

    @staticmethod
    def _choose_unique_stem(directory: Path, title: str) -> str:
        base = YtDlpDownloadService._sanitize_filename(title)
        candidate = base
        index = 2
        while YtDlpDownloadService._stem_exists(directory, candidate):
            suffix = f" ({index})"
            candidate = f"{base[: max(1, 150 - len(suffix))]}{suffix}"
            index += 1
        return candidate

    @staticmethod
    def _sanitize_filename(value: str) -> str:
        normalized = unicodedata.normalize("NFC", value)
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", normalized).strip(" .")
        cleaned = re.sub(r"\s+", " ", cleaned)
        if not cleaned:
            cleaned = "video"
        reserved = {
            "CON", "PRN", "AUX", "NUL",
            *(f"COM{number}" for number in range(1, 10)),
            *(f"LPT{number}" for number in range(1, 10)),
        }
        if cleaned.upper() in reserved:
            cleaned = f"_{cleaned}"
        return cleaned[:150].rstrip(" .") or "video"

    @staticmethod
    def _stem_exists(directory: Path, stem: str) -> bool:
        try:
            return any(path.name.startswith(stem + ".") for path in directory.iterdir())
        except OSError:
            return False

    @staticmethod
    def _resolve_output_file(
        reported: str,
        directory: Path,
        stem: str,
        task: DownloadTask,
    ) -> Path | None:
        if reported:
            candidate = Path(reported)
            if candidate.is_file():
                return candidate

        expected_extensions = (
            (task.audio_format.lower(),)
            if task.audio_only
            else (task.container.lower(), "mp4", "mkv", "webm")
        )
        candidates: list[Path] = []
        try:
            for path in directory.iterdir():
                if not path.is_file() or not path.name.startswith(stem + "."):
                    continue
                if path.suffix.lower().lstrip(".") in expected_extensions:
                    candidates.append(path)
        except OSError:
            return None
        return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None

    def _cleanup_embedded_subtitle_sidecars(
        self,
        output_file: Path,
        directory: Path,
        stem: str,
        task: DownloadTask,
    ) -> None:
        """최종 파일 안의 자막 스트림을 확인한 뒤 작업용 SRT만 정리한다.

        yt-dlp의 화면 출력 문구에 의존하지 않는다. --verbose 유무나 yt-dlp의
        메시지 형식이 바뀌어도 ffprobe가 실제 완성 파일의 자막 스트림을 확인한
        경우에만 외부 SRT를 삭제한다.
        """

        languages: list[str] = []
        for encoded in task.subtitle_tracks:
            _kind, separator, code = encoded.partition(":")
            code = code.strip()
            if separator and code and code not in languages:
                languages.append(code)

        sidecars = [
            directory / f"{stem}.{code}.srt"
            for code in languages
            if (directory / f"{stem}.{code}.srt").is_file()
        ]
        if not sidecars:
            return

        subtitle_stream_count = self._probe_subtitle_stream_count(output_file)
        if subtitle_stream_count is None:
            write_download_event(
                "download.subtitle_sidecars_cleanup_skipped",
                task_id=task.task_id,
                reason="ffprobe verification unavailable",
                files=", ".join(path.name for path in sidecars),
            )
            return

        if subtitle_stream_count < len(sidecars):
            write_download_event(
                "download.subtitle_sidecars_cleanup_skipped",
                task_id=task.task_id,
                reason=f"embedded subtitles {subtitle_stream_count} < sidecars {len(sidecars)}",
                files=", ".join(path.name for path in sidecars),
            )
            return

        removed: list[str] = []
        failed: list[str] = []
        for candidate in sidecars:
            try:
                candidate.unlink()
                removed.append(candidate.name)
            except OSError:
                failed.append(candidate.name)

        if removed:
            write_download_event(
                "download.subtitle_sidecars_cleaned",
                task_id=task.task_id,
                verified_subtitle_streams=subtitle_stream_count,
                files=", ".join(removed),
            )
        if failed:
            write_download_event(
                "download.subtitle_sidecars_cleanup_failed",
                task_id=task.task_id,
                files=", ".join(failed),
            )

    def _probe_subtitle_stream_count(self, output_file: Path) -> int | None:
        if self.ffprobe is None or not output_file.is_file():
            return None

        command = [
            str(self.ffprobe),
            "-v",
            "error",
            "-select_streams",
            "s",
            "-show_entries",
            "stream=index",
            "-of",
            "json",
            str(output_file),
        ]
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        if result.returncode != 0:
            return None

        try:
            payload = json.loads(result.stdout or "{}")
        except (TypeError, json.JSONDecodeError):
            return None
        streams = payload.get("streams", [])
        if not isinstance(streams, list):
            return None
        return len(streams)

    @staticmethod
    def _ordered_unique(values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result

    @staticmethod
    def _friendly_error(detail: str, url: str = "") -> str:
        lowered = detail.lower()
        if "requested format is not available" in lowered:
            return "선택한 화질·형식·코덱 조합을 이 영상에서 찾지 못했습니다."
        if "ffmpeg" in lowered and any(token in lowered for token in ("not found", "not installed")):
            return "FFmpeg를 찾지 못해 영상과 오디오를 합치지 못했습니다."
        if any(token in lowered for token in ("permission denied", "access is denied")):
            return "저장 폴더에 파일을 쓸 권한이 없습니다."
        if any(token in lowered for token in ("no space left", "not enough space")):
            return "저장 장치의 남은 공간이 부족합니다."
        if any(
            token in lowered
            for token in (
                "sign in to confirm",
                "not a bot",
                "could not copy",
                "failed to decrypt",
                "cookie database",
                "browser cookies",
                "javascript runtime",
                "js runtime",
                "sign in",
                "login",
                "cookies",
                "cookie",
                "unexpected response from webpage request",
                "this content isn't available to everyone",
                "can't be seen by certain audiences",
                "cannot be seen by certain audiences",
            )
        ):
            return YtDlpService._friendly_error(detail, url)
        if any(token in lowered for token in ("unsupported url", "no suitable extractor")):
            return "현재 yt-dlp가 지원하지 않는 주소로 보입니다."
        if "http error 403" in lowered or "403: forbidden" in lowered:
            if YtDlpService.is_youtube_url(url):
                return "YouTube에서 영상 스트림 접근을 거부했습니다. (HTTP 403) 원본 로그에서 인증 상세 정보를 확인해 주세요."
            return "사이트에서 영상 스트림 접근을 거부했습니다. (HTTP 403) 원본 로그에서 상세 원인을 확인해 주세요."
        if any(token in lowered for token in ("unable to download", "network", "timed out")):
            return "네트워크 문제로 다운로드를 계속하지 못했습니다."
        return "다운로드 중 오류가 발생했습니다. 상세 로그에서 원인을 확인할 수 있습니다."

    @staticmethod
    def _sanitize_log_line(line: str, url: str) -> str:
        """공유 가능한 진단 로그를 위해 인증 관련 값을 가린다."""

        sanitized = line
        cookie_file = YtDlpService.find_cookie_file(url)
        if cookie_file is not None:
            cookie_text = str(cookie_file)
            sanitized = sanitized.replace(cookie_text, "<cookie-file>")
            sanitized = sanitized.replace(cookie_text.replace("\\", "\\\\"), "<cookie-file>")

        # 오류 출력에 인증 헤더가 포함되더라도 실제 인증 값은 남기지 않는다.
        sanitized = re.sub(
            r"(?i)(\bAuthorization\s*:\s*).*$",
            r"\1<redacted>",
            sanitized,
        )
        sanitized = re.sub(
            r"(?i)(\bCookie\s*:\s*).*$",
            r"\1<redacted>",
            sanitized,
        )
        sanitized = re.sub(
            r"(?i)((?:po[_ -]?token|visitor[_ -]?data|data[_ -]?sync[_ -]?id)\s*[=:]\s*)([^\s,;\]\}\)]+)",
            r"\1<redacted>",
            sanitized,
        )
        # URL/query 및 JSON 형태 인증값도 공유 가능한 수준으로 가린다.
        sanitized = re.sub(r"(?i)([?&](?:pot|sig|lsig|spc|bui|cps|n)=)[^&\s\"]+", r"\1<redacted>", sanitized)
        sanitized = re.sub(r'(?i)("(?:visitorData|rolloutToken|appInstallData|deviceExperimentId)"\s*:\s*")[^"]+(")', r"\1<redacted>\2", sanitized)
        sanitized = re.sub(r'(?i)("remoteHost"\s*:\s*")[^"]+(")', r"\1<redacted>\2", sanitized)
        return sanitized

    @staticmethod
    def _display_command(command: list[str]) -> str:
        displayed: list[str] = []
        redact_next = False
        for item in command:
            if redact_next:
                displayed.append("<cookie-file>")
                redact_next = False
                continue
            displayed.append(item)
            if item == "--cookies":
                redact_next = True
        return subprocess.list2cmdline(displayed)
