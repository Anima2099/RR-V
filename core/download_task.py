from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DownloadStatus(StrEnum):
    ANALYZING = "analyzing"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    POSTPROCESSING = "postprocessing"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


STATUS_LABELS: dict[DownloadStatus, str] = {
    DownloadStatus.ANALYZING: "분석 중",
    DownloadStatus.QUEUED: "대기 중",
    DownloadStatus.DOWNLOADING: "다운로드 중",
    DownloadStatus.POSTPROCESSING: "마무리 중",
    DownloadStatus.COMPLETED: "완료",
    DownloadStatus.FAILED: "실패",
    DownloadStatus.STOPPED: "중지됨",
}


@dataclass(slots=True)
class DownloadTask:
    task_id: str
    title: str
    url: str
    status: DownloadStatus
    video_id: str = ""
    extractor: str = ""
    uploader: str = ""
    duration_text: str = ""
    thumbnail_url: str = ""
    thumbnail_data: bytes = b""
    preset: str = "기본 다운로드"
    resolution: str = "최고 화질"
    container: str = "MP4"
    codec: str = "H.264"
    subtitle: str = "자막 없음"
    subtitle_tracks: tuple[str, ...] = ()
    embed_subtitles: bool = False
    embed_thumbnail: bool = False
    save_thumbnail: bool = False
    audio_only: bool = False
    audio_format: str = "M4A"
    audio_quality: str = "최고"
    preserve_metadata: bool = True
    split_chapters: bool = False
    sponsorblock_chapters: bool = False
    delete_original_after_split: bool = False
    progress: int = 0
    speed: str = "-"
    eta: str = "-"
    downloaded_bytes: int = 0
    total_bytes: int = 0
    total_bytes_estimated: bool = False
    file_size_bytes: int = 0
    save_path: str = r"D:\Videos\RR-V"
    output_stem: str = ""
    output_file: str = ""
    raw_log_path: str = ""
    download_started_at: float = 0.0
    process_id: int = 0
    phase_message: str = ""
    error_message: str = ""
    error_detail: str = ""

    @property
    def identity_key(self) -> str:
        extractor = self.extractor.strip().lower() or "unknown"
        identity = self.video_id.strip() or self.url.strip()
        return f"{extractor}:{identity}"

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def meta_text(self) -> str:
        if self.audio_only:
            return " · ".join(
                item
                for item in (
                    "오디오만",
                    self.audio_format,
                    self.audio_quality,
                )
                if item
            )

        items = [
            self.resolution,
            self.container,
            self.codec,
            self.subtitle,
        ]
        if self.sponsorblock_chapters:
            items.append("SponsorBlock 챕터")
        if self.split_chapters:
            items.append("챕터별 저장")
            if self.delete_original_after_split:
                items.append("원본 삭제")
        return " · ".join(item for item in items if item)


def is_orphaned_download_task(
    task: DownloadTask,
    *,
    worker_running: bool,
    process_running: bool,
) -> bool:
    """실행 주체가 모두 사라졌는데 작업 상태만 실행 중인지 확인한다.

    시간 제한은 사용하지 않는다. Worker나 yt-dlp 프로세스 중 하나라도 실제로
    살아 있으면 정상적으로 오래 걸리는 작업일 수 있으므로 고립으로 판단하지 않는다.
    """

    return (
        task.status in {
            DownloadStatus.DOWNLOADING,
            DownloadStatus.POSTPROCESSING,
        }
        and not worker_running
        and not process_running
    )


def remove_failed_tasks(
    tasks: list[DownloadTask],
) -> tuple[list[DownloadTask], list[str]]:
    """실패 상태의 작업만 목록에서 골라낸다.

    실제 다운로드 파일은 건드리지 않고, UI/큐 목록에서 제거할 task id만 반환한다.
    입력 리스트 자체는 수정하지 않는다.
    """

    failed_ids = [
        task.task_id
        for task in tasks
        if task.status is DownloadStatus.FAILED
    ]
    if not failed_ids:
        return list(tasks), []

    failed_set = set(failed_ids)
    remaining_tasks = [
        task for task in tasks if task.task_id not in failed_set
    ]
    return remaining_tasks, failed_ids