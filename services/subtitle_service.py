from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from typing import Callable
from uuid import uuid4

from app.general_preferences import FILE_COLLISION_OVERWRITE, load_general_preferences
from app.paths import find_executable
from app.subtitle_log import append_subtitle_task_log, create_subtitle_task_log_path, write_subtitle_event
from core.subtitle_models import (
    EXTRACT_ASS,
    EXTRACT_SRT,
    OP_EXTRACT,
    OP_INSERT,
    OP_REMOVE,
    OP_SYNC,
    OUTPUT_CUSTOM,
    OUTPUT_OVERWRITE,
    SubtitleInsertItem,
    SubtitleOptions,
    SubtitleProbeResult,
    SubtitleResult,
    SubtitleTask,
    SubtitleTrack,
)

SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".ts", ".m2ts"}
INSERT_VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".mkv"}
SUPPORTED_TEXT_SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt"}
SUPPORTED_IMAGE_SUBTITLE_EXTENSIONS = {".sup"}
SUPPORTED_SUBTITLE_EXTENSIONS = SUPPORTED_TEXT_SUBTITLE_EXTENSIONS | SUPPORTED_IMAGE_SUBTITLE_EXTENSIONS

TEXT_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text", "microdvd", "jacosub", "sami"}
IMAGE_CODECS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"}
MP4_EXTENSIONS = {".mp4", ".m4v", ".mov"}

LANGUAGE_TITLES = {
    "kor": "Korean",
    "eng": "English",
    "jpn": "Japanese",
    "chi": "Chinese",
    "zho": "Chinese",
    "und": "",
}

LANGUAGE_FILENAME_TOKENS = {
    "kor": {"ko", "kor", "korean"},
    "eng": {"en", "eng", "english"},
    "jpn": {"ja", "jp", "jpn", "japanese"},
    "chi": {"zh", "zho", "chi", "chs", "cht", "chinese"},
}


def detect_subtitle_language(subtitle_path: str) -> tuple[str, str, str]:
    """Return (ISO-ish code, friendly track title, detection source)."""
    path = Path(subtitle_path)
    stem = path.stem.casefold()
    tokens = {token for token in re.split(r"[^a-z0-9]+", stem) if token}
    for code, candidates in LANGUAGE_FILENAME_TOKENS.items():
        if tokens & candidates:
            return code, LANGUAGE_TITLES.get(code, ""), "filename"

    if path.suffix.lower() not in SUPPORTED_TEXT_SUBTITLE_EXTENSIONS or not path.is_file():
        return "und", "", "unknown"

    try:
        data = path.read_bytes()[:1_500_000]
    except OSError:
        return "und", "", "unknown"

    text = ""
    for encoding in ("utf-8-sig", "utf-16", "cp949", "utf-8"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        text = data.decode("latin-1", errors="ignore")

    # Remove the most common timing/format noise before counting script characters.
    sample = re.sub(r"\d{1,2}:\d{2}:\d{2}[,.]\d{2,3}|\d+|-->|<[^>]+>|\{[^}]+\}", " ", text)
    hangul = len(re.findall(r"[\uac00-\ud7a3]", sample))
    kana = len(re.findall(r"[\u3040-\u30ff]", sample))
    han = len(re.findall(r"[\u4e00-\u9fff]", sample))
    latin = len(re.findall(r"[A-Za-z]", sample))

    if hangul >= 8 and hangul >= kana * 2:
        return "kor", LANGUAGE_TITLES["kor"], "content"
    if kana >= 5:
        return "jpn", LANGUAGE_TITLES["jpn"], "content"
    if han >= 10 and hangul < 5 and kana < 5:
        return "chi", LANGUAGE_TITLES["chi"], "content"
    if latin >= 40 and latin > (hangul + kana + han) * 2:
        return "eng", LANGUAGE_TITLES["eng"], "content"
    return "und", "", "unknown"


def _subtitle_match_rank(video_path: str, subtitle_path: str) -> tuple[int, int, int, str] | None:
    video = Path(video_path)
    sub = Path(subtitle_path)
    if not sub.is_file() or sub.suffix.lower() not in SUPPORTED_SUBTITLE_EXTENSIONS:
        return None
    if video.suffix.lower() in MP4_EXTENSIONS and sub.suffix.lower() in SUPPORTED_IMAGE_SUBTITLE_EXTENSIONS:
        return None
    vstem = video.stem.casefold()
    sstem = sub.stem.casefold()
    if not (sstem == vstem or sstem.startswith(vstem + ".") or sstem.startswith(vstem + "_") or sstem.startswith(vstem + "-")):
        return None
    exact = 0 if sstem == vstem else 1
    rrv_generated = 0 if re.match(rf"^{re.escape(vstem)}_sub\d+(?:[_\-.].*)?$", sstem) else 1
    return exact, rrv_generated, len(sub.name), sub.name.casefold()


class SubtitleCancelledError(RuntimeError):
    pass


class SubtitleExecutionError(RuntimeError):
    def __init__(self, user_message: str, technical_detail: str = "") -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical_detail = technical_detail


class SubtitleService:
    def __init__(self) -> None:
        self.ffmpeg = find_executable("ffmpeg.exe") or find_executable("ffmpeg")
        self.ffprobe = find_executable("ffprobe.exe") or find_executable("ffprobe")
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()

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

    def probe_video(self, video_path: str) -> SubtitleProbeResult:
        path = Path(video_path)
        if not path.is_file():
            raise SubtitleExecutionError("영상 파일을 찾을 수 없습니다.", str(path))
        payload = self._probe_json(path)
        streams = payload.get("streams", []) if isinstance(payload, dict) else []
        if not isinstance(streams, list):
            streams = []

        width = height = 0
        video_codec = ""
        tracks: list[SubtitleTrack] = []
        sub_index = 0
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            if stream.get("codec_type") == "video" and not video_codec:
                disposition = stream.get("disposition") or {}
                if not bool(disposition.get("attached_pic", 0)):
                    width = int(stream.get("width") or 0)
                    height = int(stream.get("height") or 0)
                    video_codec = str(stream.get("codec_name") or "").upper()
            if stream.get("codec_type") != "subtitle":
                continue
            codec = str(stream.get("codec_name") or "").lower()
            tags = stream.get("tags") or {}
            disposition = stream.get("disposition") or {}
            tracks.append(
                SubtitleTrack(
                    stream_index=int(stream.get("index") or 0),
                    subtitle_index=sub_index,
                    codec_name=codec,
                    codec_long_name=str(stream.get("codec_long_name") or codec),
                    language=str(tags.get("language") or "und"),
                    title=str(tags.get("title") or ""),
                    is_default=bool(disposition.get("default", 0)),
                    is_forced=bool(disposition.get("forced", 0)),
                    is_text=codec in TEXT_CODECS,
                    is_image=codec in IMAGE_CODECS,
                )
            )
            sub_index += 1

        fmt = payload.get("format") or {}
        try:
            duration = float(fmt.get("duration") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
        return SubtitleProbeResult(
            video_path=str(path),
            duration=max(0.0, duration),
            width=width,
            height=height,
            video_codec=video_codec or "VIDEO",
            tracks=tuple(tracks),
        )

    def execute(
        self,
        task: SubtitleTask,
        options: SubtitleOptions,
        cancel_event: threading.Event,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> SubtitleResult:
        if options.operation == OP_SYNC:
            return self._sync_external(task.primary_path, options, cancel_event, progress_callback)
        probe = self.probe_video(task.primary_path)
        if options.operation == OP_EXTRACT:
            return self._extract(probe, options, cancel_event, progress_callback)
        if options.operation == OP_INSERT:
            return self._insert(probe, task.secondary_path, options, cancel_event, progress_callback)
        if options.operation == OP_REMOVE:
            return self._remove(probe, options, cancel_event, progress_callback)
        raise SubtitleExecutionError("알 수 없는 자막 작업입니다.", options.operation)

    def insert_subtitle_files(
        self,
        video_path: str,
        subtitles: tuple[SubtitleInsertItem, ...],
        cancel_event: threading.Event,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> SubtitleResult:
        """여러 외부 자막을 한 번의 스트림 복사 작업으로 원본 영상에 삽입한다."""
        if self.ffmpeg is None:
            raise SubtitleExecutionError("FFmpeg를 찾을 수 없습니다.")
        if not subtitles:
            raise SubtitleExecutionError("삽입할 자막 파일이 없습니다.")

        probe = self.probe_video(video_path)
        video = Path(probe.video_path)
        if video.suffix.lower() not in INSERT_VIDEO_EXTENSIONS:
            raise SubtitleExecutionError(
                "자막 삽입은 현재 MP4/M4V/MOV/MKV 영상을 지원합니다.",
                str(video),
            )

        items: list[tuple[SubtitleInsertItem, Path]] = []
        for item in subtitles:
            path = Path(item.path)
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_TEXT_SUBTITLE_EXTENSIONS:
                raise SubtitleExecutionError(
                    "지원하는 텍스트 자막 파일을 선택해 주세요.",
                    str(path),
                )
            items.append((item, path))

        task_log = create_subtitle_task_log_path()
        started = time.perf_counter()
        temp_output = video.with_name(f".{video.stem}.rrv-submulti-{uuid4().hex[:8]}{video.suffix}")
        existing_count = len(probe.tracks)
        write_subtitle_event(
            "subtitle.insert_many.start",
            video=video,
            subtitles=len(items),
            log=task_log,
        )
        append_subtitle_task_log(
            task_log,
            f"operation=insert_many\nsource={video}\nsubtitle_count={len(items)}\n"
            f"ffmpeg={self.ffmpeg}\nffprobe={self.ffprobe}\n{'-'*72}\n",
        )
        try:
            command = [
                str(self.ffmpeg), "-hide_banner", "-y", "-v", "error",
                "-i", str(video),
            ]
            for _item, subtitle in items:
                command += ["-i", str(subtitle)]

            command += ["-map", "0"]
            for input_index in range(1, len(items) + 1):
                command += ["-map", f"{input_index}:0"]
            command += ["-map_metadata", "0", "-map_chapters", "0", "-c", "copy"]

            for offset, (item, _subtitle) in enumerate(items):
                subtitle_index = existing_count + offset
                if video.suffix.lower() in MP4_EXTENSIONS:
                    command += [f"-c:s:{subtitle_index}", "mov_text"]

                language = (item.language or "und").strip().lower()[:16] or "und"
                command += [f"-metadata:s:s:{subtitle_index}", f"language={language}"]
                title = item.title.strip()
                if title:
                    command += [f"-metadata:s:s:{subtitle_index}", f"title={title}"]
                dispositions: list[str] = []
                if item.make_default:
                    dispositions.append("default")
                if item.make_forced:
                    dispositions.append("forced")
                command += [
                    f"-disposition:s:{subtitle_index}",
                    "+".join(dispositions) if dispositions else "0",
                ]

            command.append(str(temp_output))
            self._run_ffmpeg(
                command,
                cancel_event,
                task_log,
                duration=probe.duration,
                progress_callback=(
                    (lambda percent, _detail: progress_callback(
                        percent,
                        f"영상·음성을 그대로 복사해 자막 복구 중 · {percent}%",
                    ))
                    if progress_callback is not None else None
                ),
                phase_name="insert_many",
                source_path=video,
            )

            new_probe = self.probe_video(str(temp_output))
            expected_count = existing_count + len(items)
            if len(new_probe.tracks) < expected_count:
                raise SubtitleExecutionError(
                    "복구한 자막 트랙을 결과 영상에서 모두 확인하지 못했습니다.",
                    f"expected>={expected_count}, actual={len(new_probe.tracks)}",
                )

            self._safe_replace_original(video, temp_output)
            elapsed = time.perf_counter() - started
            write_subtitle_event(
                "subtitle.insert_many.success",
                video=video,
                subtitles=len(items),
                elapsed=f"{elapsed:.3f}s",
                log=task_log,
            )
            append_subtitle_task_log(
                task_log,
                f"\nSUCCESS output={video}\nsubtitles={len(items)}\nelapsed={elapsed:.3f}s\n",
            )
            return SubtitleResult(
                OP_INSERT,
                str(video),
                (str(video),),
                f"자막 {len(items)}개 삽입 완료",
            )
        except SubtitleCancelledError:
            write_subtitle_event("subtitle.insert_many.cancelled", video=video, log=task_log)
            raise
        except SubtitleExecutionError:
            write_subtitle_event("subtitle.insert_many.failed", video=video, log=task_log)
            raise
        finally:
            self._unlink_quietly(temp_output)

    def _extract(
        self,
        probe: SubtitleProbeResult,
        options: SubtitleOptions,
        cancel_event: threading.Event,
        progress_callback: Callable[[int, str], None] | None,
    ) -> SubtitleResult:
        if self.ffmpeg is None:
            raise SubtitleExecutionError("FFmpeg를 찾을 수 없습니다.")
        selected_indices = set(options.selected_stream_indices)
        chosen = [t for t in probe.tracks if not selected_indices or t.stream_index in selected_indices]
        if not chosen:
            raise SubtitleExecutionError("추출할 자막 트랙을 선택해 주세요.")
        source = Path(probe.video_path)
        output_dir = self._output_dir_for(source, options)
        output_dir.mkdir(parents=True, exist_ok=True)
        task_log = create_subtitle_task_log_path()
        started = time.perf_counter()
        write_subtitle_event("subtitle.extract.start", input=source, tracks=len(chosen), format=options.extract_format, log=task_log)
        self._log_header(task_log, OP_EXTRACT, source, options)
        outputs: list[str] = []
        try:
            for number, track in enumerate(chosen, start=1):
                if cancel_event.is_set():
                    raise SubtitleCancelledError("자막 추출 중지됨")
                ext, codec_args = self._extract_target(track, options.extract_format)
                lang = self._safe_token(track.language or "und")
                base = output_dir / f"{source.stem}_sub{number}_{lang}.{ext}"
                output = self._resolve_collision(base)
                command = [
                    str(self.ffmpeg), "-hide_banner", "-y", "-v", "error",
                    "-i", str(source), "-map", f"0:{track.stream_index}", *codec_args, str(output),
                ]
                def on_track_progress(local_percent: int, _detail: str, *, n: int = number) -> None:
                    overall = int(round(((n - 1) + (local_percent / 100.0)) / len(chosen) * 100.0))
                    detail = f"자막 {n}/{len(chosen)} · 영상에서 자막 읽는 중 · {local_percent}%"
                    if progress_callback is not None:
                        progress_callback(overall, detail)

                self._run_ffmpeg(
                    command,
                    cancel_event,
                    task_log,
                    duration=probe.duration,
                    progress_callback=on_track_progress,
                    phase_name="extract",
                    source_path=source,
                )
                if not output.is_file() or output.stat().st_size <= 0:
                    raise SubtitleExecutionError("자막 파일이 정상적으로 만들어지지 않았습니다.", str(output))
                outputs.append(str(output))
            elapsed = time.perf_counter() - started
            write_subtitle_event("subtitle.extract.success", input=source, outputs=len(outputs), elapsed=f"{elapsed:.3f}s", log=task_log)
            append_subtitle_task_log(task_log, f"\nSUCCESS outputs={outputs!r}\nelapsed={elapsed:.3f}s\n")
            return SubtitleResult(OP_EXTRACT, str(source), tuple(outputs), f"자막 {len(outputs)}개 추출 완료")
        except SubtitleCancelledError:
            write_subtitle_event("subtitle.extract.cancelled", input=source, log=task_log)
            raise
        except SubtitleExecutionError:
            write_subtitle_event("subtitle.extract.failed", input=source, log=task_log)
            raise

    def _insert(
        self,
        probe: SubtitleProbeResult,
        subtitle_path: str,
        options: SubtitleOptions,
        cancel_event: threading.Event,
        progress_callback: Callable[[int, str], None] | None,
    ) -> SubtitleResult:
        if self.ffmpeg is None:
            raise SubtitleExecutionError("FFmpeg를 찾을 수 없습니다.")
        video = Path(probe.video_path)
        subtitle = Path(subtitle_path)
        if video.suffix.lower() not in INSERT_VIDEO_EXTENSIONS:
            raise SubtitleExecutionError("자막 삽입은 현재 MP4/M4V/MOV/MKV 영상을 지원합니다.", str(video))
        if not subtitle.is_file() or subtitle.suffix.lower() not in SUPPORTED_SUBTITLE_EXTENSIONS:
            raise SubtitleExecutionError("지원하는 외부 자막 파일을 선택해 주세요.", "SRT, ASS, SSA, VTT, SUP")
        if video.suffix.lower() in MP4_EXTENSIONS and subtitle.suffix.lower() in SUPPORTED_IMAGE_SUBTITLE_EXTENSIONS:
            raise SubtitleExecutionError("MP4 계열에는 이미지형 SUP 자막을 안전하게 넣을 수 없습니다.", "MKV 영상을 사용해 주세요.")

        task_log = create_subtitle_task_log_path()
        started = time.perf_counter()
        temp_output = video.with_name(f".{video.stem}.rrv-sub-{uuid4().hex[:8]}{video.suffix}")
        existing_count = len(probe.tracks)
        write_subtitle_event("subtitle.insert.start", video=video, subtitle=subtitle, log=task_log)
        self._log_header(task_log, OP_INSERT, video, options, secondary=subtitle)
        try:
            command = [
                str(self.ffmpeg), "-hide_banner", "-y", "-v", "error",
                "-i", str(video), "-i", str(subtitle),
                "-map", "0", "-map", "1:0", "-map_metadata", "0", "-map_chapters", "0", "-c", "copy",
            ]
            if video.suffix.lower() in MP4_EXTENSIONS:
                command += [f"-c:s:{existing_count}", "mov_text"]

            requested_language = (options.language or "auto").strip().lower()
            detection_source = "manual"
            if requested_language == "auto":
                language, auto_title, detection_source = detect_subtitle_language(str(subtitle))
            else:
                language = requested_language or "und"
                auto_title = LANGUAGE_TITLES.get(language, "")
            language = language[:16]
            track_title = options.track_title.strip() or auto_title
            append_subtitle_task_log(
                task_log,
                f"detected_language={language}\nlanguage_source={detection_source}\nresolved_track_title={track_title}\n",
            )
            command += [f"-metadata:s:s:{existing_count}", f"language={language}"]
            if track_title:
                command += [f"-metadata:s:s:{existing_count}", f"title={track_title}"]
            dispositions: list[str] = []
            if options.make_default:
                dispositions.append("default")
            if options.make_forced:
                dispositions.append("forced")
            command += [f"-disposition:s:{existing_count}", "+".join(dispositions) if dispositions else "0"]
            command.append(str(temp_output))
            self._run_ffmpeg(
                command,
                cancel_event,
                task_log,
                duration=probe.duration,
                progress_callback=(
                    (lambda percent, _detail: progress_callback(percent, f"영상·음성을 그대로 복사해 새 파일 구성 중 · {percent}%"))
                    if progress_callback is not None else None
                ),
                phase_name="insert",
                source_path=video,
            )
            new_probe = self.probe_video(str(temp_output))
            if len(new_probe.tracks) < existing_count + 1:
                raise SubtitleExecutionError("새 자막 트랙을 결과 영상에서 확인하지 못했습니다.")
            final_output = self._final_video_output(video, temp_output, options, "_subbed")
            deleted_external = False
            if options.delete_external_after_insert:
                try:
                    subtitle.unlink()
                    deleted_external = True
                    append_subtitle_task_log(task_log, f"external_subtitle_deleted={subtitle}\n")
                except OSError as error:
                    append_subtitle_task_log(task_log, f"external_subtitle_delete_failed={error!r}\n")
            elapsed = time.perf_counter() - started
            write_subtitle_event(
                "subtitle.insert.success", video=video, output=final_output,
                subtitle_deleted=deleted_external, elapsed=f"{elapsed:.3f}s", log=task_log,
            )
            append_subtitle_task_log(task_log, f"\nSUCCESS output={final_output}\nelapsed={elapsed:.3f}s\n")
            message = "자막 삽입 완료" + (" · 외부 자막 삭제" if deleted_external else "")
            return SubtitleResult(OP_INSERT, str(video), (str(final_output),), message)
        except SubtitleCancelledError:
            write_subtitle_event("subtitle.insert.cancelled", video=video, log=task_log)
            raise
        except SubtitleExecutionError:
            write_subtitle_event("subtitle.insert.failed", video=video, log=task_log)
            raise
        finally:
            self._unlink_quietly(temp_output)

    def _remove(
        self,
        probe: SubtitleProbeResult,
        options: SubtitleOptions,
        cancel_event: threading.Event,
        progress_callback: Callable[[int, str], None] | None,
    ) -> SubtitleResult:
        if self.ffmpeg is None:
            raise SubtitleExecutionError("FFmpeg를 찾을 수 없습니다.")
        video = Path(probe.video_path)
        selected = set(options.selected_stream_indices)
        existing_indices = {t.stream_index for t in probe.tracks}
        if not selected:
            selected = set(existing_indices)
        selected &= existing_indices
        if not selected:
            raise SubtitleExecutionError("선택한 자막 트랙을 영상에서 찾지 못했습니다.")
        task_log = create_subtitle_task_log_path()
        temp_output = video.with_name(f".{video.stem}.rrv-nosub-{uuid4().hex[:8]}{video.suffix}")
        started = time.perf_counter()
        write_subtitle_event("subtitle.remove.start", video=video, tracks=len(selected), log=task_log)
        self._log_header(task_log, OP_REMOVE, video, options)
        try:
            command = [str(self.ffmpeg), "-hide_banner", "-y", "-v", "error", "-i", str(video), "-map", "0"]
            for stream_index in sorted(selected):
                command += ["-map", f"-0:{stream_index}"]
            command += ["-map_metadata", "0", "-map_chapters", "0", "-c", "copy", str(temp_output)]
            self._run_ffmpeg(
                command,
                cancel_event,
                task_log,
                duration=probe.duration,
                progress_callback=(
                    (lambda percent, _detail: progress_callback(percent, f"자막을 제외하고 새 영상 구성 중 · {percent}%"))
                    if progress_callback is not None else None
                ),
                phase_name="remove",
                source_path=video,
            )
            new_probe = self.probe_video(str(temp_output))
            expected = len(probe.tracks) - len(selected)
            if len(new_probe.tracks) != expected:
                raise SubtitleExecutionError("자막 제거 결과를 검증하지 못했습니다.", f"expected={expected}, actual={len(new_probe.tracks)}")
            final_output = self._final_video_output(video, temp_output, options, "_nosub")
            elapsed = time.perf_counter() - started
            write_subtitle_event("subtitle.remove.success", video=video, output=final_output, elapsed=f"{elapsed:.3f}s", log=task_log)
            append_subtitle_task_log(task_log, f"\nSUCCESS output={final_output}\nelapsed={elapsed:.3f}s\n")
            return SubtitleResult(OP_REMOVE, str(video), (str(final_output),), f"자막 {len(selected)}개 제거 완료")
        except SubtitleCancelledError:
            write_subtitle_event("subtitle.remove.cancelled", video=video, log=task_log)
            raise
        except SubtitleExecutionError:
            write_subtitle_event("subtitle.remove.failed", video=video, log=task_log)
            raise
        finally:
            self._unlink_quietly(temp_output)

    def _sync_external(
        self,
        subtitle_path: str,
        options: SubtitleOptions,
        cancel_event: threading.Event,
        progress_callback: Callable[[int, str], None] | None,
    ) -> SubtitleResult:
        source = Path(subtitle_path)
        if not source.is_file() or source.suffix.lower() not in SUPPORTED_TEXT_SUBTITLE_EXTENSIONS:
            raise SubtitleExecutionError("싱크 조정은 SRT/ASS/SSA/VTT 자막을 지원합니다.")
        if cancel_event.is_set():
            raise SubtitleCancelledError("자막 싱크 작업 중지됨")
        task_log = create_subtitle_task_log_path()
        started = time.perf_counter()
        if progress_callback is not None:
            progress_callback(10, "자막 시간 정보를 읽는 중")
        write_subtitle_event("subtitle.sync.start", input=source, offset_ms=options.sync_offset_ms, log=task_log)
        self._log_header(task_log, OP_SYNC, source, options)
        text = self._read_subtitle_text(source)
        suffix = source.suffix.lower()
        if suffix == ".srt":
            shifted, count = self._shift_srt(text, options.sync_offset_ms)
        elif suffix in {".ass", ".ssa"}:
            shifted, count = self._shift_ass(text, options.sync_offset_ms)
        else:
            shifted, count = self._shift_vtt(text, options.sync_offset_ms)
        if count <= 0:
            raise SubtitleExecutionError("조정할 자막 시간 정보를 찾지 못했습니다.", str(source))
        if progress_callback is not None:
            progress_callback(70, f"자막 {count}개 시간 조정 완료 · 파일 저장 중")
        output_dir = self._output_dir_for(source, options)
        output_dir.mkdir(parents=True, exist_ok=True)
        if options.output_mode == OUTPUT_OVERWRITE:
            temp = source.with_name(f".{source.stem}.rrv-sync-{uuid4().hex[:8]}{source.suffix}")
            try:
                self._write_subtitle_text(temp, shifted, suffix)
                self._safe_replace_original(source, temp)
            finally:
                self._unlink_quietly(temp)
            output = source
        else:
            output = self._resolve_collision(output_dir / f"{source.stem}_synced{source.suffix}")
            self._write_subtitle_text(output, shifted, suffix)
        elapsed = time.perf_counter() - started
        if progress_callback is not None:
            progress_callback(100, "싱크 보정 완료")
        write_subtitle_event("subtitle.sync.success", input=source, output=output, cues=count, elapsed=f"{elapsed:.3f}s", log=task_log)
        append_subtitle_task_log(task_log, f"\nSUCCESS output={output}\ncues={count}\nelapsed={elapsed:.3f}s\n")
        return SubtitleResult(OP_SYNC, str(source), (str(output),), f"자막 {count}개 시간 보정 완료")

    def _extract_target(self, track: SubtitleTrack, target: str) -> tuple[str, list[str]]:
        if target in {EXTRACT_SRT, EXTRACT_ASS} and track.is_image:
            raise SubtitleExecutionError("이미지형 자막은 SRT/ASS로 바로 변환할 수 없습니다.", f"codec={track.codec_name}")
        if target == EXTRACT_SRT:
            return "srt", ["-c:s", "srt"]
        if target == EXTRACT_ASS:
            return "ass", ["-c:s", "ass"]
        codec = track.codec_name
        if codec in {"subrip", "srt"}:
            return "srt", ["-c:s", "copy"]
        if codec == "ass":
            return "ass", ["-c:s", "copy"]
        if codec == "ssa":
            return "ssa", ["-c:s", "copy"]
        if codec == "webvtt":
            return "vtt", ["-c:s", "copy"]
        if codec == "mov_text":
            return "srt", ["-c:s", "srt"]
        if codec == "hdmv_pgs_subtitle":
            return "sup", ["-c:s", "copy"]
        if codec in {"dvd_subtitle", "dvb_subtitle", "xsub"}:
            return "mks", ["-c:s", "copy"]
        if track.is_text:
            return "srt", ["-c:s", "srt"]
        return "mks", ["-c:s", "copy"]

    def _probe_json(self, path: Path) -> dict:
        if self.ffprobe is None:
            raise SubtitleExecutionError("FFprobe를 찾을 수 없습니다.")
        command = [str(self.ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
                timeout=45, check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise SubtitleExecutionError("영상 정보를 확인하지 못했습니다.", str(error)) from error
        if result.returncode != 0:
            raise SubtitleExecutionError("영상 정보를 확인하지 못했습니다.", result.stderr.strip())
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as error:
            raise SubtitleExecutionError("FFprobe 결과를 읽지 못했습니다.", str(error)) from error
        return payload if isinstance(payload, dict) else {}

    def _run_ffmpeg(
        self,
        command: list[str],
        cancel_event: threading.Event,
        task_log: Path,
        *,
        duration: float = 0.0,
        progress_callback: Callable[[int, str], None] | None = None,
        phase_name: str = "ffmpeg",
        source_path: Path | None = None,
    ) -> None:
        if cancel_event.is_set():
            raise SubtitleCancelledError("자막 작업 중지됨")
        progress_command = [command[0], "-progress", "pipe:1", "-stats_period", "0.5", "-nostats", *command[1:]]
        append_subtitle_task_log(task_log, "COMMAND\n" + subprocess.list2cmdline(progress_command) + "\n\n")
        source_size = 0
        if source_path is not None:
            try:
                source_size = source_path.stat().st_size
            except OSError:
                source_size = 0
        append_subtitle_task_log(
            task_log,
            f"progress_phase={phase_name}\nduration={duration:.3f}s\n"
            f"source_size_bytes={source_size}\nsource_size_mb={source_size / (1024 * 1024):.2f}\n\n",
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        popen_kwargs: dict = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "creationflags": creationflags,
        }
        if sys.platform != "win32":
            popen_kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(progress_command, **popen_kwargs)
        except OSError as error:
            raise SubtitleExecutionError("FFmpeg를 실행하지 못했습니다.", str(error)) from error
        with self._process_lock:
            self._process = process
        line_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
        stderr_lines: list[str] = []

        def reader(stream, channel: str) -> None:
            if stream is None:
                line_queue.put((channel, None))
                return
            try:
                for line in iter(stream.readline, ""):
                    line_queue.put((channel, line.rstrip("\r\n")))
            finally:
                line_queue.put((channel, None))

        stdout_thread = threading.Thread(target=reader, args=(process.stdout, "stdout"), daemon=True)
        stderr_thread = threading.Thread(target=reader, args=(process.stderr, "stderr"), daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        started = time.perf_counter()
        stdout_done = False
        stderr_done = False
        last_percent = -1
        last_logged_bucket = -1
        last_out_seconds = 0.0
        try:
            while process.poll() is None or not (stdout_done and stderr_done):
                if cancel_event.is_set():
                    self.cancel()
                    raise SubtitleCancelledError("자막 작업 중지됨")
                try:
                    channel, line = line_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line is None:
                    if channel == "stdout":
                        stdout_done = True
                    else:
                        stderr_done = True
                    continue
                if channel == "stderr":
                    stderr_lines.append(line)
                    continue
                if line.startswith("out_time="):
                    last_out_seconds = self._parse_progress_time(line.partition("=")[2])
                    if duration > 0:
                        percent = max(0, min(99, int(last_out_seconds / duration * 100.0)))
                        if percent != last_percent:
                            last_percent = percent
                            if progress_callback is not None:
                                progress_callback(percent, f"{percent}%")
                        bucket = percent // 10
                        if bucket > last_logged_bucket:
                            last_logged_bucket = bucket
                            append_subtitle_task_log(
                                task_log,
                                f"progress={percent}% out_time={last_out_seconds:.3f}s elapsed={time.perf_counter() - started:.3f}s\n",
                            )
                elif line == "progress=end":
                    if progress_callback is not None:
                        progress_callback(100, "100%")
                    append_subtitle_task_log(
                        task_log,
                        f"progress=100% out_time={last_out_seconds:.3f}s elapsed={time.perf_counter() - started:.3f}s\n",
                    )
            stdout_thread.join(timeout=1.0)
            stderr_thread.join(timeout=1.0)
            stderr = "\n".join(stderr_lines)
            append_subtitle_task_log(task_log, f"\nSTDERR\n{stderr}\n")
            if process.returncode != 0:
                raise SubtitleExecutionError("FFmpeg 자막 작업에 실패했습니다.", stderr.strip() or f"returncode={process.returncode}")
            elapsed = max(0.001, time.perf_counter() - started)
            if source_size > 0:
                append_subtitle_task_log(
                    task_log,
                    f"throughput_source_mb_s={(source_size / (1024 * 1024)) / elapsed:.2f}\nffmpeg_elapsed={elapsed:.3f}s\n",
                )
        finally:
            with self._process_lock:
                if self._process is process:
                    self._process = None

    @staticmethod
    def _parse_progress_time(value: str) -> float:
        try:
            h, m, s = value.strip().split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
        except (TypeError, ValueError):
            return 0.0

    def _final_video_output(self, source: Path, temp_output: Path, options: SubtitleOptions, suffix: str) -> Path:
        if options.output_mode == OUTPUT_OVERWRITE:
            self._safe_replace_original(source, temp_output)
            return source
        output_dir = self._output_dir_for(source, options)
        output_dir.mkdir(parents=True, exist_ok=True)
        final = self._resolve_collision(output_dir / f"{source.stem}{suffix}{source.suffix}")
        os.replace(temp_output, final)
        return final

    def _safe_replace_original(self, source: Path, replacement: Path) -> None:
        backup = source.with_name(f".{source.name}.rrv-backup-{uuid4().hex[:8]}")
        try:
            os.replace(source, backup)
            try:
                os.replace(replacement, source)
            except Exception:
                if backup.exists() and not source.exists():
                    os.replace(backup, source)
                raise
            self._unlink_quietly(backup)
        except OSError as error:
            raise SubtitleExecutionError("원본 파일을 안전하게 교체하지 못했습니다.", str(error)) from error

    def _output_dir_for(self, source: Path, options: SubtitleOptions) -> Path:
        if options.output_folder_mode == OUTPUT_CUSTOM and options.output_folder.strip():
            return Path(options.output_folder.strip())
        return source.parent

    def _resolve_collision(self, target: Path) -> Path:
        if not target.exists():
            return target
        prefs = load_general_preferences()
        if prefs.file_collision_mode == FILE_COLLISION_OVERWRITE:
            self._unlink_quietly(target)
            return target
        counter = 2
        while True:
            candidate = target.with_name(f"{target.stem} ({counter}){target.suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def _log_header(self, task_log: Path, operation: str, source: Path, options: SubtitleOptions, secondary: Path | None = None) -> None:
        append_subtitle_task_log(
            task_log,
            f"operation={operation}\nsource={source}\nsecondary={secondary or ''}\n"
            f"selected_streams={options.selected_stream_indices}\nextract_format={options.extract_format}\n"
            f"language={options.language}\ntrack_title={options.track_title}\n"
            f"default={options.make_default}\nforced={options.make_forced}\n"
            f"delete_external_after_insert={options.delete_external_after_insert}\n"
            f"sync_offset_ms={options.sync_offset_ms}\noutput_mode={options.output_mode}\n"
            f"output_folder_mode={options.output_folder_mode}\noutput_folder={options.output_folder}\n"
            f"ffmpeg={self.ffmpeg}\nffprobe={self.ffprobe}\n{'-'*72}\n",
        )

    @staticmethod
    def _safe_token(text: str) -> str:
        token = re.sub(r"[^0-9A-Za-z_-]+", "_", text.strip())
        return token[:24] or "und"

    @staticmethod
    def _unlink_quietly(path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    @staticmethod
    def _read_subtitle_text(path: Path) -> str:
        data = path.read_bytes()
        for encoding in ("utf-8-sig", "utf-16", "cp949", "utf-8"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("latin-1", errors="replace")

    @staticmethod
    def _write_subtitle_text(path: Path, text: str, suffix: str) -> None:
        encoding = "utf-8-sig" if suffix == ".srt" else "utf-8"
        path.write_text(text, encoding=encoding, newline="\n")

    @classmethod
    def _shift_srt(cls, text: str, offset_ms: int) -> tuple[str, int]:
        pattern = re.compile(r"(?m)^(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})(.*)$")
        count = 0
        def repl(match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            start = cls._parse_hms_ms(match.group(1)) + offset_ms
            end = cls._parse_hms_ms(match.group(2)) + offset_ms
            start = max(0, start)
            end = max(start + 1, end)
            return f"{cls._format_hms_ms(start, ',')} --> {cls._format_hms_ms(end, ',')}{match.group(3)}"
        return pattern.sub(repl, text), count

    @classmethod
    def _shift_vtt(cls, text: str, offset_ms: int) -> tuple[str, int]:
        pattern = re.compile(r"(?m)^(?P<a>(?:\d{1,2}:)?\d{2}:\d{2}\.\d{3})\s*-->\s*(?P<b>(?:\d{1,2}:)?\d{2}:\d{2}\.\d{3})(?P<tail>.*)$")
        count = 0
        def parse(value: str) -> int:
            parts = value.split(":")
            if len(parts) == 2:
                value = "00:" + value
            return cls._parse_hms_ms(value)
        def repl(match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            start = max(0, parse(match.group("a")) + offset_ms)
            end = max(start + 1, parse(match.group("b")) + offset_ms)
            return f"{cls._format_hms_ms(start, '.')} --> {cls._format_hms_ms(end, '.')}{match.group('tail')}"
        return pattern.sub(repl, text), count

    @classmethod
    def _shift_ass(cls, text: str, offset_ms: int) -> tuple[str, int]:
        lines = text.splitlines()
        count = 0
        output: list[str] = []
        for line in lines:
            if not line.lstrip().lower().startswith("dialogue:"):
                output.append(line)
                continue
            prefix, payload = line.split(":", 1)
            fields = payload.split(",", 9)
            if len(fields) < 3:
                output.append(line)
                continue
            try:
                start = cls._parse_ass_time(fields[1].strip()) + offset_ms
                end = cls._parse_ass_time(fields[2].strip()) + offset_ms
            except ValueError:
                output.append(line)
                continue
            start = max(0, start)
            end = max(start + 10, end)
            fields[1] = cls._format_ass_time(start)
            fields[2] = cls._format_ass_time(end)
            output.append(prefix + ":" + ",".join(fields))
            count += 1
        trailing = "\n" if text.endswith(("\n", "\r")) else ""
        return "\n".join(output) + trailing, count

    @staticmethod
    def _parse_hms_ms(value: str) -> int:
        value = value.replace(",", ".")
        h, m, sec = value.split(":")
        s, ms = sec.split(".")
        return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms[:3].ljust(3, "0"))

    @staticmethod
    def _format_hms_ms(value: int, separator: str) -> str:
        value = max(0, int(value))
        h, rem = divmod(value, 3_600_000)
        m, rem = divmod(rem, 60_000)
        s, ms = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d}{separator}{ms:03d}"

    @staticmethod
    def _parse_ass_time(value: str) -> int:
        h, m, sec = value.split(":")
        s, cs = sec.split(".")
        return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(cs[:2].ljust(2, "0")) * 10

    @staticmethod
    def _format_ass_time(value: int) -> str:
        value = max(0, int(value))
        h, rem = divmod(value, 3_600_000)
        m, rem = divmod(rem, 60_000)
        s, ms = divmod(rem, 1000)
        return f"{h}:{m:02d}:{s:02d}.{ms // 10:02d}"


def find_matching_subtitle(video_path: str, candidate_paths: list[str] | tuple[str, ...] | None = None) -> str:
    video = Path(video_path)
    if not video.is_file():
        return ""
    if candidate_paths is None:
        subtitles = [
            str(p) for p in video.parent.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_SUBTITLE_EXTENSIONS
        ]
    else:
        subtitles = [str(Path(p)) for p in candidate_paths]

    ranked: list[tuple[tuple[int, int, int, str], str]] = []
    for subtitle_path in subtitles:
        rank = _subtitle_match_rank(str(video), subtitle_path)
        if rank is not None:
            ranked.append((rank, subtitle_path))
    if not ranked:
        return ""
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


def scan_folder_for_insert_tasks(folder: str) -> list[SubtitleTask]:
    root = Path(folder)
    if not root.is_dir():
        return []
    videos = sorted(
        (p for p in root.iterdir() if p.is_file() and p.suffix.lower() in INSERT_VIDEO_EXTENSIONS),
        key=lambda p: p.name.lower(),
    )
    return [SubtitleTask(str(video), find_matching_subtitle(str(video))) for video in videos]

