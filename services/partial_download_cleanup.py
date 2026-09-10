from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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
    """현재 작업이 만든 것으로 확인되는 yt-dlp 미완성 파일만 찾는다.

    1차로 RR-V가 정한 output_stem과 정확히 맞는 파일을 찾고, 중지 시 yt-dlp가
    파일명을 조금 다르게 만든 경우에는 해당 작업의 raw log에 실제 목적 파일명이
    기록되어 있는지 교차 확인한다. 완성 영상/자막/썸네일은 후보에 넣지 않는다.
    """

    directory = Path(task.save_path).expanduser()
    if not directory.is_dir():
        return ()

    stem = str(task.output_stem).strip()
    stem_key = _text_key(stem)
    log_key = _read_task_log_key(task)

    candidates: list[Path] = []
    try:
        entries = list(directory.iterdir())
    except OSError:
        return ()

    for path in entries:
        if not path.is_file() or not _is_incomplete_name(path.name):
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
        if stem_match or log_match:
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


def _candidate_log_probes(name: str) -> tuple[str, ...]:
    lowered = name.casefold()
    base = name
    fragment_index = lowered.find(".part-frag")
    if fragment_index >= 0:
        base = name[:fragment_index]
    elif lowered.endswith(".part"):
        base = name[:-5]
    elif lowered.endswith(".ytdl"):
        base = name[:-5]

    probes = []
    for value in (name, base):
        key = _text_key(value)
        if key and key not in probes:
            probes.append(key)
    return tuple(probes)


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


def _text_key(value: str) -> str:
    return unicodedata.normalize("NFC", str(value)).casefold()
