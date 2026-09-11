from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

from core.download_task import DownloadStatus, DownloadTask


_THUMBNAIL_EXTENSIONS = {".webp", ".png", ".jpg", ".jpeg", ".avif"}
_SUBTITLE_EXTENSIONS = {
    ".srt",
    ".vtt",
    ".ass",
    ".ssa",
    ".lrc",
    ".ttml",
    ".srv1",
    ".srv2",
    ".srv3",
    ".json3",
}


@dataclass(slots=True, frozen=True)
class PartialCleanupResult:
    deleted: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()

    @property
    def deleted_count(self) -> int:
        return len(self.deleted)

    @property
    def failed_count(self) -> int:
        return len(self.failed)


def should_offer_partial_cleanup(
    task: DownloadTask,
    *,
    active: bool = False,
    detected_count: int = 0,
) -> bool:
    """목록 삭제 때 미완성 파일 정리 선택을 물어볼지 판단한다."""

    if task.status in {
        DownloadStatus.DOWNLOADING,
        DownloadStatus.POSTPROCESSING,
    }:
        return True

    if task.status is DownloadStatus.STOPPED:
        return bool(
            active
            or detected_count > 0
            or task.downloaded_bytes > 0
            or str(task.output_stem).strip()
            or str(task.raw_log_path).strip()
        )

    if task.status is DownloadStatus.FAILED:
        return bool(detected_count > 0 or task.downloaded_bytes > 0)

    return False


def find_partial_download_files(task: DownloadTask) -> tuple[Path, ...]:
    """현재 작업이 만든 것으로 확인되는 yt-dlp 미완성 산출물만 찾는다.

    .part/.ytdl은 output_stem, 작업 로그, 현재 세션의 파일명/시각을 교차 확인한다.
    썸네일 내장 과정에서 중지 때문에 남은 WEBP/PNG/JPG 같은 이미지와, 자막을
    영상에 내장하기 위해 먼저 받은 SRT/VTT 등의 sidecar도 현재 작업에서 생성된
    것이 확인되는 경우에만 정리 후보에 넣는다. 이때 시각 기준은 계속 갱신되는
    raw log mtime이 아니라 다운로드 시작 때 고정한 값을 쓴다.

    yt-dlp의 --trim-filenames로 실제 파일명이 잘린 경우에도 현재 세션의 긴 공통
    파일명 접두부를 확인한다. 사용자가 '썸네일 JPG 별도 저장'을 선택한 JPG/JPEG와
    자막을 영상에 내장하지 않은 작업의 외부 자막은 최종 결과물이므로 보존한다.
    """

    directory = Path(task.save_path).expanduser()
    if not directory.is_dir():
        return ()

    stem = str(task.output_stem).strip()
    stem_key = _text_key(stem)
    stem_identity = _filename_identity(stem)
    log_key = _read_task_log_key(task)
    download_started_at = _task_download_started_at(task)

    candidates: list[Path] = []
    try:
        entries = list(directory.iterdir())
    except OSError:
        return ()

    for path in entries:
        if not path.is_file():
            continue

        name_key = _text_key(path.name)
        stem_match = bool(stem_key and name_key.startswith(f"{stem_key}."))
        log_match = bool(
            log_key
            and any(
                probe and probe in log_key
                for probe in _candidate_log_probes(path.name)
            )
        )

        if _is_incomplete_name(path.name):
            session_match = _matches_current_download_session(
                task,
                path,
                stem_identity=stem_identity,
                download_started_at=download_started_at,
            )
            if stem_match or log_match or session_match:
                candidates.append(path)
            continue

        if _is_temporary_thumbnail_name(task, path.name):
            session_match = _matches_current_thumbnail_session(
                path,
                stem_identity=stem_identity,
                download_started_at=download_started_at,
            )
            if _matches_current_sidecar_artifact(
                path,
                stem_match=stem_match,
                log_match=log_match,
                session_match=session_match,
                download_started_at=download_started_at,
            ):
                candidates.append(path)
            continue

        if _is_temporary_subtitle_name(task, path.name):
            session_match = _matches_current_subtitle_session(
                path,
                stem_identity=stem_identity,
                download_started_at=download_started_at,
            )
            if _matches_current_sidecar_artifact(
                path,
                stem_match=stem_match,
                log_match=log_match,
                session_match=session_match,
                download_started_at=download_started_at,
            ):
                candidates.append(path)

    return tuple(sorted(candidates, key=lambda item: item.name.casefold()))


def cleanup_partial_download_files(task: DownloadTask) -> PartialCleanupResult:
    deleted: list[str] = []
    failed: list[str] = []

    for path in find_partial_download_files(task):
        try:
            path.unlink()
        except OSError:
            failed.append(str(path))
        else:
            deleted.append(str(path))

    return PartialCleanupResult(tuple(deleted), tuple(failed))


def partial_cleanup_scan_diagnostics(task: DownloadTask) -> tuple[str, ...]:
    """미완성 파일 판별 근거를 다운로드 로그에 남기기 위한 짧은 진단 정보."""

    directory = Path(task.save_path).expanduser()
    if not directory.is_dir():
        return ("directory-missing",)

    stem = str(task.output_stem).strip()
    stem_key = _text_key(stem)
    stem_identity = _filename_identity(stem)
    log_key = _read_task_log_key(task)
    started_at = _task_download_started_at(task)

    try:
        entries = list(directory.iterdir())
    except OSError:
        return ("directory-unreadable",)

    details: list[str] = []
    for path in entries:
        if not path.is_file():
            continue
        if (
            not _is_incomplete_name(path.name)
            and not _is_thumbnail_extension(path.name)
            and not _is_subtitle_extension(path.name)
        ):
            continue

        name_key = _text_key(path.name)
        stem_match = bool(stem_key and name_key.startswith(f"{stem_key}."))
        log_match = bool(
            log_key
            and any(
                probe and probe in log_key
                for probe in _candidate_log_probes(path.name)
            )
        )
        try:
            modified_at = path.stat().st_mtime
        except OSError:
            modified_at = 0.0
        delta = (
            modified_at - started_at
            if started_at is not None and started_at > 0.0 and modified_at > 0.0
            else 0.0
        )

        if _is_incomplete_name(path.name):
            session_match = _matches_current_download_session(
                task,
                path,
                stem_identity=stem_identity,
                download_started_at=started_at,
            )
            candidate = stem_match or log_match or session_match
            kind = "partial"
            eligible = True
            extra = f"session={int(session_match)}"
        elif _is_thumbnail_extension(path.name):
            eligible = _is_temporary_thumbnail_name(task, path.name)
            session_match = bool(
                eligible
                and _matches_current_thumbnail_session(
                    path,
                    stem_identity=stem_identity,
                    download_started_at=started_at,
                )
            )
            candidate = bool(
                eligible
                and _matches_current_sidecar_artifact(
                    path,
                    stem_match=stem_match,
                    log_match=log_match,
                    session_match=session_match,
                    download_started_at=started_at,
                )
            )
            kind = "thumb"
            extra = f"eligible={int(eligible)};session={int(session_match)}"
        else:
            eligible = _is_temporary_subtitle_name(task, path.name)
            session_match = bool(
                eligible
                and _matches_current_subtitle_session(
                    path,
                    stem_identity=stem_identity,
                    download_started_at=started_at,
                )
            )
            candidate = bool(
                eligible
                and _matches_current_sidecar_artifact(
                    path,
                    stem_match=stem_match,
                    log_match=log_match,
                    session_match=session_match,
                    download_started_at=started_at,
                )
            )
            kind = "subtitle"
            extra = f"eligible={int(eligible)};session={int(session_match)}"

        # 부가 sidecar는 후보에서 탈락해도 판정 근거를 남겨 다음 스모크에서
        # 파일명 잘림/시각/설정 중 무엇이 원인인지 바로 확인할 수 있게 한다.
        if candidate or stem_match or log_match or (kind in {"thumb", "subtitle"} and eligible):
            details.append(
                f"{path.name};kind={kind};candidate={int(candidate)};"
                f"stem={int(stem_match)};log={int(log_match)};{extra};"
                f"delta={delta:.3f}s"
            )

    if not details:
        started_text = started_at if started_at is not None else 0.0
        return (f"none;started_at={started_text:.3f}",)
    return tuple(details[:12])


def _is_incomplete_name(name: str) -> bool:
    lowered = name.casefold()
    return (
        lowered.endswith(".part")
        or ".part-frag" in lowered
        or lowered.endswith(".ytdl")
    )


def _is_thumbnail_extension(name: str) -> bool:
    return Path(name).suffix.casefold() in _THUMBNAIL_EXTENSIONS


def _is_subtitle_extension(name: str) -> bool:
    return Path(name).suffix.casefold() in _SUBTITLE_EXTENSIONS


def _is_temporary_thumbnail_name(task: DownloadTask, name: str) -> bool:
    if not (task.embed_thumbnail or task.save_thumbnail):
        return False

    suffix = Path(name).suffix.casefold()
    if suffix not in _THUMBNAIL_EXTENSIONS:
        return False

    # UI의 '썸네일 JPG 별도 저장'은 최종 JPG 결과를 명시적으로 요청한 것이다.
    if task.save_thumbnail and suffix in {".jpg", ".jpeg"}:
        return False
    return True


def _is_temporary_subtitle_name(task: DownloadTask, name: str) -> bool:
    """영상 내장을 위해 받은 자막 sidecar만 미완성 정리 대상으로 본다."""

    if task.audio_only or not task.embed_subtitles or not task.subtitle_tracks:
        return False
    return _is_subtitle_extension(name)


def _matches_current_sidecar_artifact(
    path: Path,
    *,
    stem_match: bool,
    log_match: bool,
    session_match: bool,
    download_started_at: float | None,
) -> bool:
    if log_match or session_match:
        return True
    if not stem_match or download_started_at is None:
        return False
    try:
        modified_at = path.stat().st_mtime
    except OSError:
        return False
    return modified_at >= download_started_at - 5.0


def _matches_current_thumbnail_session(
    path: Path,
    *,
    stem_identity: str,
    download_started_at: float | None,
) -> bool:
    if not stem_identity or download_started_at is None:
        return False

    try:
        modified_at = path.stat().st_mtime
    except OSError:
        return False
    if modified_at < download_started_at - 5.0:
        return False

    candidate_identity = _thumbnail_filename_identity(path.name)
    return _has_matching_filename_prefix(stem_identity, candidate_identity)


def _matches_current_subtitle_session(
    path: Path,
    *,
    stem_identity: str,
    download_started_at: float | None,
) -> bool:
    if not stem_identity or download_started_at is None:
        return False

    try:
        modified_at = path.stat().st_mtime
    except OSError:
        return False
    if modified_at < download_started_at - 5.0:
        return False

    candidate_identity = _subtitle_filename_identity(path.name)
    return _has_matching_filename_prefix(stem_identity, candidate_identity)


def _candidate_log_probes(name: str) -> tuple[str, ...]:
    base = _strip_incomplete_suffix(name)
    probes = []
    for value in (name, base):
        key = _text_key(value)
        if key and key not in probes:
            probes.append(key)
    return tuple(probes)


def _matches_current_download_session(
    task: DownloadTask,
    path: Path,
    *,
    stem_identity: str,
    download_started_at: float | None,
) -> bool:
    if task.downloaded_bytes <= 0 or not stem_identity or download_started_at is None:
        return False

    try:
        modified_at = path.stat().st_mtime
    except OSError:
        return False

    if modified_at < download_started_at - 5.0:
        return False

    candidate_identity = _partial_filename_identity(path.name)
    return _has_matching_filename_prefix(stem_identity, candidate_identity)


def _has_matching_filename_prefix(
    expected_identity: str,
    candidate_identity: str,
) -> bool:
    if not expected_identity or not candidate_identity:
        return False

    left_tokens = expected_identity.split()
    right_tokens = candidate_identity.split()
    shared_tokens = 0
    shared_chars = 0
    for left, right in zip(left_tokens, right_tokens):
        if left != right:
            break
        shared_tokens += 1
        shared_chars += len(left)

    shorter_length = min(len(expected_identity), len(candidate_identity))
    return bool(
        shared_tokens >= 4
        and shared_chars >= 24
        and shorter_length > 0
        and shared_chars / shorter_length >= 0.45
    )


def _partial_filename_identity(name: str) -> str:
    base = _strip_incomplete_suffix(name)
    base = re.sub(r"\.f\d+(?:-\d+)?$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", base)
    base = re.sub(r"\.f\d+(?:-\d+)?$", "", base, flags=re.IGNORECASE)
    return _filename_identity(base)


def _thumbnail_filename_identity(name: str) -> str:
    base = re.sub(
        r"\.(?:webp|png|jpe?g|avif)$",
        "",
        name,
        flags=re.IGNORECASE,
    )
    return _filename_identity(base)


def _subtitle_filename_identity(name: str) -> str:
    base = re.sub(
        r"\.(?:srt|vtt|ass|ssa|lrc|ttml|srv[123]|json3)$",
        "",
        name,
        flags=re.IGNORECASE,
    )
    return _filename_identity(base)


def _strip_incomplete_suffix(name: str) -> str:
    lowered = name.casefold()
    fragment_index = lowered.find(".part-frag")
    if fragment_index >= 0:
        return name[:fragment_index]
    if lowered.endswith(".part"):
        return name[:-5]
    if lowered.endswith(".ytdl"):
        return name[:-5]
    return name


def _task_download_started_at(task: DownloadTask) -> float | None:
    fixed = float(getattr(task, "download_started_at", 0.0) or 0.0)
    if fixed > 0.0:
        return fixed

    # 구버전에서 저장된 대기열처럼 고정 시각이 없는 작업만 호환용 fallback을 쓴다.
    # raw log의 mtime은 다운로드 중 계속 움직이므로 시작 시각으로 쓰지 않는다.
    raw_path = str(task.raw_log_path).strip()
    if not raw_path:
        return None
    try:
        stat_result = Path(raw_path).stat()
    except OSError:
        return None
    values = [value for value in (stat_result.st_ctime, stat_result.st_mtime) if value > 0.0]
    return min(values) if values else None


def _read_task_log_key(task: DownloadTask) -> str:
    raw_path = str(task.raw_log_path).strip()
    if not raw_path:
        return ""
    path = Path(raw_path)
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return _text_key(text[-160000:])


def _filename_identity(value: str) -> str:
    normalized = unicodedata.normalize("NFC", str(value)).casefold()
    normalized = "".join(
        character if character.isalnum() else " "
        for character in normalized
    )
    return " ".join(normalized.split())


def _text_key(value: str) -> str:
    return unicodedata.normalize("NFC", str(value)).casefold()
