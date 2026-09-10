from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

from core.download_task import DownloadStatus, DownloadTask


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
    """목록 삭제 때 미완성 파일 정리 선택을 물어볼지 판단한다.

    중지 직후에는 Windows 파일 핸들이 아직 풀리지 않았거나 yt-dlp 임시 파일명이
    예상과 달라 사전 탐지가 0개일 수 있다. 실제 다운로드 흔적이 있으면 탐지 결과와
    별개로 사용자에게 정리 선택권을 제공한다.
    """

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

    .part/.ytdl은 기존처럼 output_stem, 작업 로그, 현재 세션의 파일명/시각을
    교차 확인한다. 썸네일 내장/별도 저장 과정에서 중지 때문에 남은 WEBP/PNG/JPG
    같은 이미지도 현재 작업에서 생성된 것이 확인되는 경우에만 정리 후보에 넣는다.
    단, 사용자가 '썸네일 JPG 별도 저장'을 선택했다면 완성 JPG/JPEG는 결과물로
    간주해 보존한다. 완성 영상과 자막 파일도 후보에 넣지 않는다.
    """

    directory = Path(task.save_path).expanduser()
    if not directory.is_dir():
        return ()

    stem = str(task.output_stem).strip()
    stem_key = _text_key(stem)
    stem_identity = _filename_identity(stem)
    log_key = _read_task_log_key(task)
    log_started_at = _task_log_started_at(task)

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
                log_started_at=log_started_at,
            )
            if stem_match or log_match or session_match:
                candidates.append(path)
            continue

        if not _is_temporary_thumbnail_name(task, path.name):
            continue

        if _matches_current_thumbnail_artifact(
            path,
            stem_match=stem_match,
            log_match=log_match,
            log_started_at=log_started_at,
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


def _is_incomplete_name(name: str) -> bool:
    lowered = name.casefold()
    return (
        lowered.endswith(".part")
        or ".part-frag" in lowered
        or lowered.endswith(".ytdl")
    )


def _is_temporary_thumbnail_name(task: DownloadTask, name: str) -> bool:
    if not (task.embed_thumbnail or task.save_thumbnail):
        return False

    suffix = Path(name).suffix.casefold()
    if suffix not in {".webp", ".png", ".jpg", ".jpeg", ".avif"}:
        return False

    # UI의 '썸네일 JPG 별도 저장'은 최종 JPG 결과를 명시적으로 요청한 것이다.
    # 중지 시 원본 WEBP/PNG가 남았다면 정리하되 완성 JPG/JPEG는 보존한다.
    if task.save_thumbnail and suffix in {".jpg", ".jpeg"}:
        return False
    return True


def _matches_current_thumbnail_artifact(
    path: Path,
    *,
    stem_match: bool,
    log_match: bool,
    log_started_at: float | None,
) -> bool:
    """현재 다운로드가 만든 썸네일 임시 산출물인지 보수적으로 확인한다."""

    if log_match:
        return True
    if not stem_match or log_started_at is None:
        return False
    try:
        modified_at = path.stat().st_mtime
    except OSError:
        return False
    return modified_at >= log_started_at - 5.0


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
    log_started_at: float | None,
) -> bool:
    """정확한 stem 비교가 빗나간 yt-dlp 임시 이름을 보수적으로 보완한다."""

    if task.downloaded_bytes <= 0 or not stem_identity or log_started_at is None:
        return False

    try:
        modified_at = path.stat().st_mtime
    except OSError:
        return False

    # 작업 로그가 만들어지기 훨씬 전부터 있던 .part는 다른 작업의 찌꺼기로 본다.
    if modified_at < log_started_at - 5.0:
        return False

    candidate_identity = _partial_filename_identity(path.name)
    if not candidate_identity:
        return False

    left_tokens = stem_identity.split()
    right_tokens = candidate_identity.split()
    shared_tokens = 0
    shared_chars = 0
    for left, right in zip(left_tokens, right_tokens):
        if left != right:
            break
        shared_tokens += 1
        shared_chars += len(left)

    shorter_length = min(len(stem_identity), len(candidate_identity))
    return bool(
        shared_tokens >= 4
        and shared_chars >= 24
        and shorter_length > 0
        and shared_chars / shorter_length >= 0.45
    )


def _partial_filename_identity(name: str) -> str:
    base = _strip_incomplete_suffix(name)
    # yt-dlp의 임시 파일은 stem 뒤에 f299 같은 포맷 ID와 실제 확장자가 붙을 수 있다.
    base = re.sub(r"\.f\d+(?:-\d+)?$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", base)
    base = re.sub(r"\.f\d+(?:-\d+)?$", "", base, flags=re.IGNORECASE)
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


def _task_log_started_at(task: DownloadTask) -> float | None:
    raw_path = str(task.raw_log_path).strip()
    if not raw_path:
        return None
    try:
        return Path(raw_path).stat().st_mtime
    except OSError:
        return None


def _read_task_log_key(task: DownloadTask) -> str:
    raw_path = str(task.raw_log_path).strip()
    if not raw_path:
        return ""
    path = Path(raw_path)
    if not path.is_file():
        return ""
    try:
        # 한 작업의 로그만 읽으며, 비정상적으로 커진 경우에도 끝부분이면 충분하다.
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
