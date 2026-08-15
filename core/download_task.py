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

        return " · ".join(
            item
            for item in (
                self.resolution,
                self.container,
                self.codec,
                self.subtitle,
            )
            if item
        )
