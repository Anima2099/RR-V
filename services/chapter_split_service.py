from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import unicodedata
from uuid import uuid4

from app.general_preferences import (
    FILE_COLLISION_OVERWRITE,
    load_general_preferences,
)
from app.paths import find_executable
from core.local_media_info import MediaChapter, MediaFileInfo


ProgressCallback = Callable[[int], None]
PhaseCallback = Callable[[str], None]


class ChapterSplitCancelledError(RuntimeError):
    pass


class ChapterSplitError(RuntimeError):
    def __init__(self, user_message: str, technical_detail: str = "") -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical_detail = technical_detail


@dataclass(slots=True, frozen=True)
class ChapterSplitResult:
    output_directory: str
    output_files: tuple[str, ...]

    @property
    def count(self) -> int:
        return len(self.output_files)


def valid_chapters(media_info: MediaFileInfo) -> tuple[MediaChapter, ...]:
    return tuple(
        chapter
        for chapter in media_info.chapters
        if chapter.end_seconds - chapter.start_seconds > 0.05
    )


def sanitize_chapter_title(value: object) -> str:
    normalized = unicodedata.normalize("NFC", str(value or "")).strip()
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", normalized).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = "챕터"
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
    if cleaned.upper() in reserved:
        cleaned = f"_{cleaned}"
    return cleaned[:120].rstrip(" .") or "챕터"


def chapter_output_filename(
    chapter: MediaChapter,
    position: int,
    total: int,
    suffix: str,
) -> str:
    count = max(1, int(total))
    index = max(1, int(position))
    width = max(2, len(str(count)))
    fallback = f"챕터 {index:0{width}d}"
    title = sanitize_chapter_title(chapter.title or fallback)
    extension = suffix if suffix.startswith(".") else f".{suffix}"
    return f"{index:0{width}d} - {title}{extension}"


def build_chapter_split_command(
    ffmpeg_path: str | Path,
    input_path: str | Path,
    output_path: str | Path,
    chapter: MediaChapter,
) -> list[str]:
    duration = max(0.0, chapter.duration_seconds)
    return [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{max(0.0, chapter.start_seconds):.6f}",
        "-i",
        str(input_path),
        "-t",
        f"{duration:.6f}",
        "-map",
        "0",
        "-map_metadata",
        "0",
        "-map_chapters",
        "-1",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        "-progress",
        "pipe:1",
        "-nostats",
        str(output_path),
    ]


class ChapterSplitService:
    def __init__(self) -> None:
        self.ffmpeg = find_executable("ffmpeg.exe") or find_executable("ffmpeg")
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()

    def suggested_output_directory(self, media_info: MediaFileInfo) -> Path:
        input_path = Path(media_info.path).expanduser()
        base = input_path.with_name(f"{input_path.stem}_chapters")

        try:
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
            candidate = base.with_name(f"{base.name} ({counter})")
            if not candidate.exists():
                return candidate
            counter += 1

    def split(
        self,
        media_info: MediaFileInfo,
        *,
        on_progress: ProgressCallback | None = None,
        on_phase: PhaseCallback | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> ChapterSplitResult:
        if self.ffmpeg is None:
            raise ChapterSplitError(
                "FFmpeg를 찾을 수 없어 챕터 분할을 시작하지 못했습니다.",
                "설정 → 도구 및 리소스에서 FFmpeg / FFprobe 상태를 확인해 주세요.",
            )

        input_path = Path(media_info.path).expanduser()
        if not input_path.is_file():
            raise ChapterSplitError(
                "입력 미디어 파일을 찾을 수 없습니다.",
                str(input_path),
            )

        chapters = valid_chapters(media_info)
        if not chapters:
            raise ChapterSplitError(
                "분할할 수 있는 챕터를 찾지 못했습니다.",
                "파일에 유효한 내장 챕터 정보가 없습니다.",
            )

        suffix = input_path.suffix
        if not suffix:
            raise ChapterSplitError(
                "출력 형식을 결정할 수 없습니다.",
                "입력 파일에 확장자가 없습니다.",
            )

        output_directory = self.suggested_output_directory(media_info)
        temporary_directory = input_path.parent / (
            f".{input_path.stem}.rrv-chapters-{uuid4().hex[:8]}"
        )
        try:
            temporary_directory.mkdir(parents=False, exist_ok=False)
        except OSError as error:
            raise ChapterSplitError(
                "임시 챕터 분할 폴더를 만들지 못했습니다.",
                str(error),
            ) from error

        temporary_outputs: list[Path] = []
        total = len(chapters)
        if on_progress is not None:
            on_progress(0)

        try:
            for offset, chapter in enumerate(chapters):
                if is_cancelled is not None and is_cancelled():
                    raise ChapterSplitCancelledError("챕터 분할 중지됨")

                position = offset + 1
                filename = chapter_output_filename(
                    chapter,
                    position,
                    total,
                    suffix,
                )
                temporary_output = temporary_directory / filename
                temporary_outputs.append(temporary_output)

                title = chapter.title.strip() or f"챕터 {position:02d}"
                if on_phase is not None:
                    on_phase(f"챕터 {position}/{total} 분할 중 · {title}")

                command = build_chapter_split_command(
                    self.ffmpeg,
                    input_path,
                    temporary_output,
                    chapter,
                )
                self._run_ffmpeg(
                    command,
                    duration_seconds=chapter.duration_seconds,
                    on_progress=(
                        None
                        if on_progress is None
                        else lambda chapter_percent, index=offset: on_progress(
                            min(
                                99,
                                int(
                                    (
                                        index
                                        + max(0, min(100, chapter_percent)) / 100.0
                                    )
                                    / total
                                    * 100
                                ),
                            )
                        )
                    ),
                    is_cancelled=is_cancelled,
                )

                if not temporary_output.is_file():
                    raise ChapterSplitError(
                        f"챕터 {position} 출력 파일이 생성되지 않았습니다.",
                        str(temporary_output),
                    )
                try:
                    if temporary_output.stat().st_size <= 0:
                        raise ChapterSplitError(
                            f"챕터 {position} 출력 파일이 비어 있습니다.",
                            str(temporary_output),
                        )
                except OSError as error:
                    raise ChapterSplitError(
                        f"챕터 {position} 출력 파일을 확인하지 못했습니다.",
                        str(error),
                    ) from error

                if on_progress is not None:
                    on_progress(min(99, int(position / total * 100)))

            if is_cancelled is not None and is_cancelled():
                raise ChapterSplitCancelledError("챕터 분할 중지됨")

            try:
                output_directory.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise ChapterSplitError(
                    "챕터 출력 폴더를 만들지 못했습니다.",
                    str(error),
                ) from error

            final_outputs: list[str] = []
            for temporary_output in temporary_outputs:
                destination = output_directory / temporary_output.name
                try:
                    if destination.exists():
                        destination.unlink()
                    temporary_output.replace(destination)
                except OSError as error:
                    raise ChapterSplitError(
                        "분할한 챕터 파일을 최종 폴더에 저장하지 못했습니다.",
                        str(error),
                    ) from error
                final_outputs.append(str(destination))

            if on_progress is not None:
                on_progress(100)
            if on_phase is not None:
                on_phase(f"챕터 분할 완료 · {len(final_outputs)}개")

            return ChapterSplitResult(
                output_directory=str(output_directory),
                output_files=tuple(final_outputs),
            )
        finally:
            shutil.rmtree(temporary_directory, ignore_errors=True)

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
        duration_seconds: float,
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
            raise ChapterSplitError(
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
                    raise ChapterSplitCancelledError("챕터 분할 중지됨")

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
            raise ChapterSplitError(
                "FFmpeg가 챕터 분할을 완료하지 못했습니다.",
                detail or f"FFmpeg 종료 코드: {return_code}",
            )

    @staticmethod
    def _apply_progress_line(
        line: str,
        *,
        duration_seconds: float,
        on_progress: ProgressCallback | None,
    ) -> None:
        if on_progress is None or duration_seconds <= 0:
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
        percent = int(
            max(
                0.0,
                min(100.0, current_seconds / duration_seconds * 100.0),
            )
        )
        on_progress(percent)
