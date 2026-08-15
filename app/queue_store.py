from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import unicodedata

from app.paths import (
    QUEUE_BACKUP_PATH,
    QUEUE_PATH,
    QUEUE_THUMBNAILS_DIR,
    ensure_runtime_directories,
)
from core.download_task import DownloadStatus, DownloadTask


SCHEMA_VERSION = 1


@dataclass(slots=True)
class QueueLoadResult:
    tasks: list[DownloadTask]
    restored_from_backup: bool = False
    error_message: str = ""


def save_queue(tasks: list[DownloadTask]) -> None:
    ensure_runtime_directories()
    QUEUE_THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)

    serialized_tasks: list[dict[str, object]] = []
    active_thumbnail_names: set[str] = set()

    for task in tasks:
        thumbnail_name = ""
        if task.thumbnail_data:
            thumbnail_name = _thumbnail_name(task.task_id)
            active_thumbnail_names.add(thumbnail_name)
            _atomic_write_bytes(
                QUEUE_THUMBNAILS_DIR / thumbnail_name,
                task.thumbnail_data,
            )

        task_data: dict[str, object] = {}
        for field in fields(DownloadTask):
            name = field.name
            if name in {"thumbnail_data", "process_id"}:
                continue
            value = getattr(task, name)
            if isinstance(value, DownloadStatus):
                value = value.value
            elif isinstance(value, tuple):
                value = list(value)
            task_data[name] = value
        task_data["thumbnail_cache"] = thumbnail_name
        serialized_tasks.append(task_data)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "tasks": serialized_tasks,
    }

    temp_path = QUEUE_PATH.with_suffix(".json.tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())

        if QUEUE_PATH.exists() and _is_valid_queue_file(QUEUE_PATH):
            shutil.copy2(QUEUE_PATH, QUEUE_BACKUP_PATH)
        os.replace(temp_path, QUEUE_PATH)
        _cleanup_thumbnail_cache(active_thumbnail_names)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def load_queue() -> QueueLoadResult:
    ensure_runtime_directories()

    primary_error = ""
    try:
        return QueueLoadResult(tasks=_load_from_path(QUEUE_PATH))
    except FileNotFoundError:
        return QueueLoadResult(tasks=[])
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        primary_error = str(error)

    try:
        tasks = _load_from_path(QUEUE_BACKUP_PATH)
        return QueueLoadResult(
            tasks=tasks,
            restored_from_backup=True,
            error_message=primary_error,
        )
    except FileNotFoundError:
        return QueueLoadResult(tasks=[], error_message=primary_error)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        combined = f"기본 저장본: {primary_error} / 백업본: {error}"
        return QueueLoadResult(tasks=[], error_message=combined)



def _is_valid_queue_file(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return isinstance(payload, dict) and isinstance(
            payload.get("tasks", []),
            list,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False

def _load_from_path(path: Path) -> list[DownloadTask]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise ValueError("작업 목록 파일 형식이 올바르지 않습니다.")
    if int(payload.get("schema_version", 0)) > SCHEMA_VERSION:
        raise ValueError("더 새로운 RR-V에서 저장한 작업 목록입니다.")

    raw_tasks = payload.get("tasks", [])
    if not isinstance(raw_tasks, list):
        raise ValueError("작업 목록 데이터가 올바르지 않습니다.")

    tasks: list[DownloadTask] = []
    for raw_task in raw_tasks:
        if not isinstance(raw_task, dict):
            continue
        task = _task_from_dict(raw_task)
        if task is not None:
            tasks.append(task)
    return tasks


def _task_from_dict(raw: dict[str, object]) -> DownloadTask | None:
    task_id = str(raw.get("task_id", "")).strip()
    url = str(raw.get("url", "")).strip()
    if not task_id or not url:
        return None

    try:
        status = DownloadStatus(str(raw.get("status", "queued")))
    except ValueError:
        status = DownloadStatus.QUEUED

    title = unicodedata.normalize(
        "NFC",
        str(raw.get("title", "영상 작업")),
    )

    task = DownloadTask(
        task_id=task_id,
        title=title,
        url=url,
        status=status,
        video_id=str(raw.get("video_id", "")),
        extractor=str(raw.get("extractor", "")),
        uploader=str(raw.get("uploader", "")),
        duration_text=str(raw.get("duration_text", "")),
        thumbnail_url=str(raw.get("thumbnail_url", "")),
        thumbnail_data=_read_thumbnail(str(raw.get("thumbnail_cache", ""))),
        preset=str(raw.get("preset", "기본 다운로드")),
        resolution=str(raw.get("resolution", "최고 화질")),
        container=str(raw.get("container", "MP4")),
        codec=str(raw.get("codec", "H.264")),
        subtitle=str(raw.get("subtitle", "자막 없음")),
        subtitle_tracks=tuple(
            str(item) for item in raw.get("subtitle_tracks", [])
        ) if isinstance(raw.get("subtitle_tracks", []), list) else (),
        embed_subtitles=bool(raw.get("embed_subtitles", False)),
        embed_thumbnail=bool(raw.get("embed_thumbnail", False)),
        save_thumbnail=bool(raw.get("save_thumbnail", False)),
        audio_only=bool(raw.get("audio_only", False)),
        audio_format=str(raw.get("audio_format", "M4A")),
        audio_quality=str(raw.get("audio_quality", "최고")),
        preserve_metadata=bool(raw.get("preserve_metadata", True)),
        progress=_safe_int(raw.get("progress", 0)),
        speed=str(raw.get("speed", "-")),
        eta=str(raw.get("eta", "-")),
        downloaded_bytes=_safe_nonnegative_int(raw.get("downloaded_bytes", 0)),
        total_bytes=_safe_nonnegative_int(raw.get("total_bytes", 0)),
        total_bytes_estimated=bool(raw.get("total_bytes_estimated", False)),
        file_size_bytes=_safe_nonnegative_int(raw.get("file_size_bytes", 0)),
        save_path=str(raw.get("save_path", "")),
        output_stem=unicodedata.normalize(
            "NFC",
            str(raw.get("output_stem", "")),
        ),
        output_file=unicodedata.normalize(
            "NFC",
            str(raw.get("output_file", "")),
        ),
        raw_log_path=str(raw.get("raw_log_path", "")),
        process_id=0,
        phase_message=str(raw.get("phase_message", "")),
        error_message=str(raw.get("error_message", "")),
        error_detail=str(raw.get("error_detail", "")),
    )

    if task.status in {DownloadStatus.DOWNLOADING, DownloadStatus.POSTPROCESSING}:
        task.status = DownloadStatus.STOPPED
        task.speed = "-"
        task.eta = "-"
        task.phase_message = "프로그램 종료로 중지됨 · 재시도 시 이어받기 시도"
    elif task.status is DownloadStatus.ANALYZING:
        task.speed = "-"
        task.eta = "-"
        task.phase_message = "프로그램 재시작 후 상세 정보 확인 대기 중…"
        task.error_message = ""
        task.error_detail = ""

    if (
        task.status is DownloadStatus.COMPLETED
        and task.file_size_bytes <= 0
        and task.output_file
    ):
        try:
            task.file_size_bytes = max(0, Path(task.output_file).stat().st_size)
        except OSError:
            pass

    return task


def _safe_int(value: object) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return 0


def _safe_nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def _thumbnail_name(task_id: str) -> str:
    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
    return f"{digest}.img"


def _read_thumbnail(name: str) -> bytes:
    if not name or Path(name).name != name:
        return b""
    try:
        return (QUEUE_THUMBNAILS_DIR / name).read_bytes()
    except OSError:
        return b""


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with temp_path.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _cleanup_thumbnail_cache(active_names: set[str]) -> None:
    try:
        files = list(QUEUE_THUMBNAILS_DIR.iterdir())
    except OSError:
        return
    for path in files:
        if path.is_file() and path.name not in active_names:
            try:
                path.unlink()
            except OSError:
                pass
