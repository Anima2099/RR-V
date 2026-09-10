from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.download_task import DownloadTask


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


def find_partial_download_files(task: DownloadTask) -> tuple[Path, ...]:
    """현재 작업이 만든 것으로 확실한 yt-dlp 미완성 파일만 찾는다.

    완성된 영상/자막/썸네일은 절대 후보에 넣지 않는다. output_stem이 없는
    작업도 건드리지 않아 다른 파일을 잘못 지울 가능성을 차단한다.
    """

    stem = str(task.output_stem).strip()
    if not stem:
        return ()

    directory = Path(task.save_path).expanduser()
    if not directory.is_dir():
        return ()

    prefix = f"{stem}."
    candidates: list[Path] = []
    try:
        entries = list(directory.iterdir())
    except OSError:
        return ()

    for path in entries:
        if not path.is_file():
            continue
        name = path.name
        if not name.startswith(prefix):
            continue
        lowered = name.casefold()
        is_partial = (
            lowered.endswith(".part")
            or ".part-frag" in lowered
            or lowered.endswith(".ytdl")
        )
        if is_partial:
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
