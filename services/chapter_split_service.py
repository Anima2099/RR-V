from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
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
        str(output_path),
    ]


class ChapterSplitService:
    """완성된 미디어 파일을 내장 챕터 구간대로 무손실 분리한다.

    모든 조각을 같은 드라이브의 숨김 임시 폴더에 먼저 완성한 뒤 최종 폴더를
    한 번에 교체한다. 실패/취소 중에는 기존 챕터 결과 폴더를 건드리지 않는다.
    """

    def __init__(self) -> None:
        self.ffmpeg = find_executable("ffmpeg.exe") or find_executable("ffmpeg")
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()

    @staticmethod
    def _overwrite_enabled() -> bool:
        try:
            return (
                load_general_preferences().file_collision_mode
                == FILE_COLLISION_OVERWRITE
            )
        except Exception:
            return False

    def suggested_output_directory(self, media_info: MediaFileInfo) -> Path:
        input_path = Path(media_info.path).expanduser()
        base = input_path.with_name(f"{input_path.stem}_chapters")
        if self._overwrite_enabled() or not base.exists():
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

        overwrite = self._overwrite_enabled()
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

        total = len(chapters)
        temporary_names: list[str] = []
        if on_progress is not None:
            on_progress(0)

        try:
            for offset, chapter in enumerate(chapters):
                self._raise_if_cancelled(is_cancelled)
                position = offset + 1
                filename = chapter_output_filename(
                    chapter,
                    position,
                    total,
                    suffix,
                )
                temporary_output = temporary_directory / filename
                temporary_names.append(filename)

                title = chapter.title.strip() or f"챕터 {position:02d}"
                if on_phase is not None:
                    on_phase(f"챕터 {position}/{total} 분할 중 · {title}")

                command = build_chapter_split_command(
                    self.ffmpeg,
                    input_path,
                    temporary_output,
                    chapter,
                )
                self._run_ffmpeg(command, is_cancelled=is_cancelled)
                self._verify_output(temporary_output, position)

                if on_progress is not None:
                    on_progress(min(99, int(position / total * 100)))

            self._raise_if_cancelled(is_cancelled)
            self._publish_directory(
                temporary_directory,
                output_directory,
                overwrite=overwrite,
            )

            final_outputs = tuple(
                str(output_directory / name) for name in temporary_names
            )
            if on_progress is not None:
                on_progress(100)
            if on_phase is not None:
                on_phase(f"챕터 분할 완료 · {len(final_outputs)}개")

            return ChapterSplitResult(
                output_directory=str(output_directory),
                output_files=final_outputs,
            )
        finally:
            shutil.rmtree(temporary_directory, ignore_errors=True)

    @staticmethod
    def _verify_output(path: Path, position: int) -> None:
        if not path.is_file():
            raise ChapterSplitError(
                f"챕터 {position} 출력 파일이 생성되지 않았습니다.",
                str(path),
            )
        try:
            if path.stat().st_size <= 0:
                raise ChapterSplitError(
                    f"챕터 {position} 출력 파일이 비어 있습니다.",
                    str(path),
                )
        except OSError as error:
            raise ChapterSplitError(
                f"챕터 {position} 출력 파일을 확인하지 못했습니다.",
                str(error),
            ) from error

    def _publish_directory(
        self,
        temporary_directory: Path,
        output_directory: Path,
        *,
        overwrite: bool,
    ) -> None:
        if output_directory.exists() and not overwrite:
            raise ChapterSplitError(
                "챕터 출력 폴더가 이미 존재합니다.",
                str(output_directory),
            )

        backup_path: Path | None = None
        if output_directory.exists():
            backup_path = output_directory.with_name(
                f".{output_directory.name}.rrv-backup-{uuid4().hex[:8]}"
            )
            try:
                output_directory.replace(backup_path)
            except OSError as error:
                raise ChapterSplitError(
                    "기존 챕터 출력 폴더를 안전하게 교체할 준비를 하지 못했습니다.",
                    str(error),
                ) from error

        try:
            temporary_directory.replace(output_directory)
        except OSError as error:
            if backup_path is not None and backup_path.exists():
                try:
                    backup_path.replace(output_directory)
                except OSError:
                    pass
            raise ChapterSplitError(
                "완성된 챕터 파일을 최종 폴더에 저장하지 못했습니다.",
                str(error),
            ) from error
        else:
            if backup_path is not None:
                self._remove_path_quietly(backup_path)

    @staticmethod
    def _remove_path_quietly(path: Path) -> None:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _raise_if_cancelled(
        is_cancelled: Callable[[], bool] | None,
    ) -> None:
        if is_cancelled is not None and is_cancelled():
            raise ChapterSplitCancelledError("챕터 분할 중지됨")

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
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
            )
        except OSError as error:
            raise ChapterSplitError(
                "FFmpeg를 실행하지 못했습니다.",
                str(error),
            ) from error

        with self._process_lock:
            self._process = process

        try:
            while True:
                if is_cancelled is not None and is_cancelled():
                    self.cancel()
                    raise ChapterSplitCancelledError("챕터 분할 중지됨")
                try:
                    stdout, stderr = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            with self._process_lock:
                if self._process is process:
                    self._process = None

        if process.returncode != 0:
            detail = (stderr or stdout or "").strip()
            raise ChapterSplitError(
                "FFmpeg가 챕터 분할을 완료하지 못했습니다.",
                detail[-12000:] or f"FFmpeg 종료 코드: {process.returncode}",
            )
