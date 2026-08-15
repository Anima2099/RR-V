from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import unicodedata

from app.paths import find_executable
from core.download_task import DownloadTask
from core.subtitle_models import SubtitleInsertItem
from services.subtitle_service import (
    INSERT_VIDEO_EXTENSIONS,
    SUPPORTED_TEXT_SUBTITLE_EXTENSIONS,
    SubtitleCancelledError,
    SubtitleExecutionError,
    SubtitleService,
)
from services.ytdlp_service import YtDlpService


RECOVERY_VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".mkv", ".webm"}

# FFmpeg/컨테이너에 기록된 3자리 언어 코드와 yt-dlp의 BCP-47 계열 코드를
# 비교하기 위한 대표 매핑. 모르는 언어는 원래 base 코드를 그대로 사용한다.
LANGUAGE_ALIASES = {
    "ko": "kor", "kor": "kor",
    "en": "eng", "eng": "eng",
    "ja": "jpn", "jp": "jpn", "jpn": "jpn",
    "zh": "zho", "zho": "zho", "chi": "zho",
    "es": "spa", "spa": "spa",
    "fr": "fra", "fre": "fra", "fra": "fra",
    "de": "deu", "ger": "deu", "deu": "deu",
    "it": "ita", "ita": "ita",
    "pt": "por", "por": "por",
    "ru": "rus", "rus": "rus",
    "ar": "ara", "ara": "ara",
    "hi": "hin", "hin": "hin",
    "id": "ind", "ind": "ind",
    "th": "tha", "tha": "tha",
    "vi": "vie", "vie": "vie",
}

LANGUAGE_TITLES = {
    "kor": "Korean",
    "eng": "English",
    "jpn": "Japanese",
    "zho": "Chinese",
    "spa": "Spanish",
    "fra": "French",
    "deu": "German",
    "ita": "Italian",
    "por": "Portuguese",
    "rus": "Russian",
    "ara": "Arabic",
    "hin": "Hindi",
    "ind": "Indonesian",
    "tha": "Thai",
    "vie": "Vietnamese",
}


class SubtitleRecoveryCancelledError(RuntimeError):
    pass


class SubtitleRecoveryError(RuntimeError):
    def __init__(self, user_message: str, technical_detail: str = "") -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical_detail = technical_detail


@dataclass(slots=True, frozen=True)
class SubtitleRecoveryResult:
    output_file: str
    sidecar_files: tuple[str, ...]
    downloaded_languages: tuple[str, ...]
    embedded_languages: tuple[str, ...]
    skipped_existing_languages: tuple[str, ...]
    embed_mode: bool

    @property
    def changed_count(self) -> int:
        if self.embed_mode:
            return len(self.embedded_languages)
        return len(self.sidecar_files)


@dataclass(slots=True, frozen=True)
class _RequestedTrack:
    kind: str
    code: str


@dataclass(slots=True, frozen=True)
class _DownloadedSubtitle:
    path: Path
    code: str
    kind: str


class SubtitleRecoveryService:
    """기존 다운로드 결과에 선택했던 자막만 다시 확보하고 복구한다."""

    def __init__(self) -> None:
        self.executable = find_executable("yt-dlp.exe")
        self.ffmpeg = find_executable("ffmpeg.exe") or find_executable("ffmpeg")
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()
        self._subtitle_service = SubtitleService()

    def cancel(self) -> None:
        with self._process_lock:
            process = self._process
        if process is not None and process.poll() is None:
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
        self._subtitle_service.cancel()

    def recover(
        self,
        task: DownloadTask,
        cancel_event: threading.Event,
        on_phase,
    ) -> SubtitleRecoveryResult:
        if task.audio_only:
            raise SubtitleRecoveryError(
                "오디오 전용 작업은 자막 복구 대상이 아닙니다."
            )

        requested = self._requested_tracks(task)
        if not requested:
            raise SubtitleRecoveryError(
                "이 작업에는 복구할 자막 선택 정보가 없습니다.",
                "다운로드 목록에 추가할 때 선택했던 자막 정보가 남아 있는 작업에서 사용할 수 있습니다.",
            )

        on_phase("기존 영상 파일 확인 중…")
        video_path = self.resolve_task_video_file(task)
        if cancel_event.is_set():
            raise SubtitleRecoveryCancelledError("자막 복구 중지됨")

        if task.embed_subtitles and video_path.suffix.lower() not in INSERT_VIDEO_EXTENSIONS:
            raise SubtitleRecoveryError(
                "이 영상 형식에는 아직 자막을 안전하게 다시 내장할 수 없습니다.",
                "자막 내장은 현재 MP4, M4V, MOV, MKV 영상을 지원합니다.",
            )

        with tempfile.TemporaryDirectory(prefix="rrv_subtitle_recovery_") as temp_name:
            temp_dir = Path(temp_name)
            on_phase("선택했던 자막만 다시 받는 중…")
            downloaded = self._download_requested_subtitles(
                task,
                requested,
                temp_dir,
                cancel_event,
            )
            if cancel_event.is_set():
                raise SubtitleRecoveryCancelledError("자막 복구 중지됨")

            if not downloaded:
                raise SubtitleRecoveryError(
                    "선택했던 자막을 다시 가져오지 못했습니다.",
                    "원본 페이지에서 요청한 언어의 자막 파일을 확인하지 못했습니다.",
                )

            if task.embed_subtitles:
                return self._recover_embedded(
                    video_path,
                    downloaded,
                    cancel_event,
                    on_phase,
                )

            return self._recover_sidecars(
                video_path,
                downloaded,
                cancel_event,
                on_phase,
            )

    def _recover_embedded(
        self,
        video_path: Path,
        downloaded: tuple[_DownloadedSubtitle, ...],
        cancel_event: threading.Event,
        on_phase,
    ) -> SubtitleRecoveryResult:
        on_phase("영상에 이미 들어 있는 자막 확인 중…")
        try:
            probe = self._subtitle_service.probe_video(str(video_path))
        except SubtitleExecutionError as error:
            raise SubtitleRecoveryError(error.user_message, error.technical_detail) from error

        existing_languages = {
            _canonical_language(track.language)
            for track in probe.tracks
            if track.language and _canonical_language(track.language) != "und"
        }

        insert_items: list[SubtitleInsertItem] = []
        embedded_languages: list[str] = []
        skipped_languages: list[str] = []
        for item in downloaded:
            canonical = _canonical_language(item.code)
            if canonical != "und" and canonical in existing_languages:
                skipped_languages.append(item.code)
                continue

            title = LANGUAGE_TITLES.get(canonical, item.code)
            if item.kind == "auto":
                title = f"{title} (Auto)" if title else f"{item.code} (Auto)"
            insert_items.append(
                SubtitleInsertItem(
                    path=str(item.path),
                    language=canonical,
                    title=title,
                )
            )
            embedded_languages.append(item.code)

        if not insert_items:
            on_phase("선택한 자막이 이미 영상에 들어 있습니다.")
            return SubtitleRecoveryResult(
                output_file=str(video_path),
                sidecar_files=(),
                downloaded_languages=tuple(item.code for item in downloaded),
                embedded_languages=(),
                skipped_existing_languages=tuple(skipped_languages),
                embed_mode=True,
            )

        on_phase("자막을 영상에 다시 넣는 중…")
        try:
            result = self._subtitle_service.insert_subtitle_files(
                str(video_path),
                tuple(insert_items),
                cancel_event,
            )
        except SubtitleCancelledError as error:
            raise SubtitleRecoveryCancelledError(str(error)) from error
        except SubtitleExecutionError as error:
            raise SubtitleRecoveryError(error.user_message, error.technical_detail) from error

        if cancel_event.is_set():
            raise SubtitleRecoveryCancelledError("자막 복구 중지됨")

        on_phase("복구 결과 확인 완료")
        output_file = result.output_paths[0] if result.output_paths else str(video_path)
        return SubtitleRecoveryResult(
            output_file=output_file,
            sidecar_files=(),
            downloaded_languages=tuple(item.code for item in downloaded),
            embedded_languages=tuple(embedded_languages),
            skipped_existing_languages=tuple(skipped_languages),
            embed_mode=True,
        )

    def _recover_sidecars(
        self,
        video_path: Path,
        downloaded: tuple[_DownloadedSubtitle, ...],
        cancel_event: threading.Event,
        on_phase,
    ) -> SubtitleRecoveryResult:
        on_phase("자막 파일을 영상 옆에 다시 저장하는 중…")
        outputs: list[str] = []
        code_counts: dict[str, int] = {}
        for item in downloaded:
            key = item.code.casefold()
            code_counts[key] = code_counts.get(key, 0) + 1

        for item in downloaded:
            if cancel_event.is_set():
                raise SubtitleRecoveryCancelledError("자막 복구 중지됨")
            suffix = item.path.suffix.lower() or ".srt"
            language_token = _safe_language_token(item.code)
            if code_counts.get(item.code.casefold(), 0) > 1 and item.kind == "auto":
                language_token += ".auto"
            destination = video_path.with_name(
                f"{video_path.stem}.{language_token}{suffix}"
            )
            temp_destination = destination.with_name(
                f".{destination.name}.rrv-recovery.tmp"
            )
            try:
                shutil.copy2(item.path, temp_destination)
                os.replace(temp_destination, destination)
            except OSError as error:
                try:
                    temp_destination.unlink(missing_ok=True)
                except OSError:
                    pass
                raise SubtitleRecoveryError(
                    "자막 파일을 저장 위치에 다시 쓰지 못했습니다.",
                    str(error),
                ) from error
            outputs.append(str(destination))

        on_phase("자막 파일 복구 완료")
        return SubtitleRecoveryResult(
            output_file=str(video_path),
            sidecar_files=tuple(outputs),
            downloaded_languages=tuple(item.code for item in downloaded),
            embedded_languages=(),
            skipped_existing_languages=(),
            embed_mode=False,
        )

    def _download_requested_subtitles(
        self,
        task: DownloadTask,
        requested: tuple[_RequestedTrack, ...],
        temp_dir: Path,
        cancel_event: threading.Event,
    ) -> tuple[_DownloadedSubtitle, ...]:
        if self.executable is None:
            raise SubtitleRecoveryError(
                "yt-dlp.exe를 찾을 수 없어 자막을 다시 받을 수 없습니다."
            )

        manual = _ordered_unique([
            item.code for item in requested if item.kind == "manual"
        ])
        automatic = _ordered_unique([
            item.code for item in requested if item.kind == "auto"
        ])

        downloaded: list[_DownloadedSubtitle] = []
        if manual:
            downloaded.extend(
                self._download_subtitle_group(
                    task,
                    manual,
                    "manual",
                    temp_dir,
                    cancel_event,
                )
            )
        if automatic:
            downloaded.extend(
                self._download_subtitle_group(
                    task,
                    automatic,
                    "auto",
                    temp_dir,
                    cancel_event,
                )
            )

        request_order = {
            (item.kind, item.code.casefold()): index
            for index, item in enumerate(requested)
        }
        downloaded.sort(
            key=lambda item: (
                request_order.get((item.kind, item.code.casefold()), 10_000),
                item.path.name.casefold(),
            )
        )

        missing: list[str] = []
        for item in requested:
            exact = any(
                candidate.kind == item.kind
                and candidate.code.casefold() == item.code.casefold()
                for candidate in downloaded
            )
            if exact:
                continue
            canonical = _canonical_language(item.code)
            equivalent = any(
                candidate.kind == item.kind
                and _canonical_language(candidate.code) == canonical
                for candidate in downloaded
            )
            if not equivalent:
                suffix = "(자동)" if item.kind == "auto" else ""
                missing.append(f"{item.code}{suffix}")

        if missing:
            raise SubtitleRecoveryError(
                "선택했던 자막 중 일부를 다시 가져오지 못했습니다.",
                "가져오지 못한 자막: " + ", ".join(missing),
            )
        return tuple(downloaded)

    def _download_subtitle_group(
        self,
        task: DownloadTask,
        languages: list[str],
        kind: str,
        temp_dir: Path,
        cancel_event: threading.Event,
    ) -> list[_DownloadedSubtitle]:
        prefix = f"rrv_subtitle_{kind}"
        command = [
            str(self.executable),
            "--skip-download",
            "--no-playlist",
            "--no-color",
            "--no-warnings",
            "--windows-filenames",
            "--encoding",
            "utf-8",
            "--socket-timeout",
            "30",
            "--retries",
            "3",
            "--extractor-retries",
            "2",
        ]
        if self.ffmpeg is not None:
            command.extend(["--ffmpeg-location", str(self.ffmpeg.parent)])
        command.append("--write-subs" if kind == "manual" else "--write-auto-subs")
        command.extend(["--sub-langs", ",".join(languages)])
        command.extend(["--sub-format", "srt/best", "--convert-subs", "srt"])
        command.extend(["-o", str(temp_dir / f"{prefix}.%(ext)s")])
        YtDlpService.extend_runtime_and_auth_arguments(command, task.url)
        command.append(task.url)

        stdout, stderr = self._run_process(command, cancel_event)
        subtitle_paths = [
            path
            for path in temp_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in SUPPORTED_TEXT_SUBTITLE_EXTENSIONS
            and path.name.startswith(prefix + ".")
        ]
        subtitle_paths = self._prefer_converted_subtitles(
            subtitle_paths,
            prefix=prefix,
        )
        if not subtitle_paths:
            detail = (stderr or stdout or "자막 파일이 생성되지 않았습니다.").strip()
            label = "직접 제공 자막" if kind == "manual" else "자동 생성 자막"
            raise SubtitleRecoveryError(
                f"선택했던 {label}을 다시 가져오지 못했습니다.",
                detail[-4000:],
            )

        return [
            _DownloadedSubtitle(
                path=path,
                code=self._language_from_filename(path, prefix=prefix),
                kind=kind,
            )
            for path in subtitle_paths
        ]

    def _run_process(
        self,
        command: list[str],
        cancel_event: threading.Event,
    ) -> tuple[str, str]:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        kwargs: dict = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "creationflags": creation_flags,
        }
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(command, **kwargs)
        except OSError as error:
            raise SubtitleRecoveryError("yt-dlp.exe를 실행하지 못했습니다.", str(error)) from error

        with self._process_lock:
            self._process = process
        try:
            while True:
                if cancel_event.is_set():
                    self.cancel()
                    raise SubtitleRecoveryCancelledError("자막 복구 중지됨")
                try:
                    stdout, stderr = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            with self._process_lock:
                if self._process is process:
                    self._process = None

        if cancel_event.is_set():
            raise SubtitleRecoveryCancelledError("자막 복구 중지됨")
        if process.returncode != 0:
            detail = (stderr or stdout or f"yt-dlp returncode={process.returncode}").strip()
            raise SubtitleRecoveryError(
                "자막을 다시 받는 과정에서 yt-dlp가 실패했습니다.",
                detail[-4000:],
            )
        return stdout or "", stderr or ""

    @staticmethod
    def _requested_tracks(task: DownloadTask) -> tuple[_RequestedTrack, ...]:
        result: list[_RequestedTrack] = []
        seen: set[tuple[str, str]] = set()
        for encoded in task.subtitle_tracks:
            kind, separator, code = encoded.partition(":")
            kind = kind.strip().lower()
            code = code.strip()
            if not separator or kind not in {"manual", "auto"} or not code:
                continue
            key = (kind, code.casefold())
            if key in seen:
                continue
            seen.add(key)
            result.append(_RequestedTrack(kind, code))
        return tuple(result)

    @staticmethod
    def _language_from_filename(path: Path, *, prefix: str) -> str:
        # yt-dlp의 subtitle filename은 일반적으로 base.<lang>.<ext> 형태다.
        marker = prefix + "."
        name = path.name
        if name.startswith(marker):
            remainder = name[len(marker):]
            if remainder.endswith(path.suffix):
                remainder = remainder[:-len(path.suffix)]
            remainder = remainder.strip(".")
            if remainder:
                return remainder
        return "und"

    @staticmethod
    def _prefer_converted_subtitles(
        paths: list[Path],
        *,
        prefix: str,
    ) -> list[Path]:
        # 같은 언어에 원본 VTT와 변환된 SRT가 함께 남는 경우 SRT만 사용한다.
        by_language: dict[str, Path] = {}
        priority = {".srt": 0, ".ass": 1, ".ssa": 2, ".vtt": 3}
        for path in paths:
            code = SubtitleRecoveryService._language_from_filename(
                path,
                prefix=prefix,
            ).casefold()
            current = by_language.get(code)
            if current is None or priority.get(path.suffix.lower(), 9) < priority.get(current.suffix.lower(), 9):
                by_language[code] = path
        return list(by_language.values())

    @staticmethod
    def resolve_task_video_file(task: DownloadTask) -> Path:
        if task.output_file:
            output = Path(task.output_file).expanduser()
            if output.is_file():
                return output

        save_directory = Path(task.save_path).expanduser()
        output_stem = unicodedata.normalize("NFC", task.output_stem).strip()
        if not output_stem or not save_directory.is_dir():
            raise SubtitleRecoveryError(
                "복구할 완성 영상 파일을 찾지 못했습니다.",
                "다운로드가 영상 본체를 만들기 전에 실패했거나 파일이 이동·삭제된 것으로 보입니다.",
            )

        normalized_stem = output_stem.casefold()
        candidates: list[Path] = []
        try:
            for path in save_directory.iterdir():
                if not path.is_file() or path.suffix.lower() not in RECOVERY_VIDEO_EXTENSIONS:
                    continue
                path_stem = unicodedata.normalize("NFC", path.stem).casefold()
                if path_stem != normalized_stem:
                    continue
                candidates.append(path)
        except OSError as error:
            raise SubtitleRecoveryError(
                "저장 폴더에서 완성 영상 파일을 확인하지 못했습니다.",
                str(error),
            ) from error

        if not candidates:
            raise SubtitleRecoveryError(
                "복구할 완성 영상 파일을 찾지 못했습니다.",
                "다운로드가 영상 본체를 만들기 전에 실패했거나 파일이 이동·삭제된 것으로 보입니다.",
            )

        expected_suffix = f".{task.container.strip().lower()}"
        candidates.sort(
            key=lambda path: (
                path.suffix.lower() != expected_suffix,
                -_safe_mtime(path),
                path.name.casefold(),
            )
        )
        return candidates[0]


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _canonical_language(code: str) -> str:
    normalized = code.strip().lower()
    if not normalized or normalized == "und":
        return "und"
    base = normalized.split("-", 1)[0]
    return LANGUAGE_ALIASES.get(base, base)


def _safe_language_token(code: str) -> str:
    token = re.sub(r"[^0-9A-Za-z_-]+", "_", code.strip())
    return token[:32] or "und"


def _ordered_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result
