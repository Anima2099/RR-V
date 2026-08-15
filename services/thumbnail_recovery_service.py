from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
import threading
import unicodedata
from urllib.parse import urlparse

from core.download_task import DownloadTask
from core.thumbnail_models import OUTPUT_OVERWRITE, ThumbnailOptions
from services.thumbnail_service import (
    SUPPORTED_VIDEO_EXTENSIONS,
    ThumbnailCancelledError,
    ThumbnailExecutionError,
    ThumbnailService,
)
from services.ytdlp_service import (
    AnalysisCancelledError,
    MediaAnalysisError,
    YtDlpService,
)


RECOVERY_VIDEO_EXTENSIONS = SUPPORTED_VIDEO_EXTENSIONS | {".webm"}


class ThumbnailRecoveryCancelledError(RuntimeError):
    pass


class ThumbnailRecoveryError(RuntimeError):
    def __init__(self, user_message: str, technical_detail: str = "") -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical_detail = technical_detail


@dataclass(slots=True, frozen=True)
class ThumbnailRecoveryResult:
    output_file: str
    thumbnail_url: str
    thumbnail_data: bytes


class ThumbnailRecoveryService:
    """기존 다운로드 결과에 원본 썸네일만 다시 넣는다.

    다운로드 엔진을 다시 실행하지 않는다. 큐에 남은 썸네일 캐시를 우선 사용하고,
    필요한 경우에만 썸네일 URL 또는 원본 페이지 분석으로 이미지를 다시 확보한다.
    영상 교체와 FFprobe 검증은 Media Tools의 ThumbnailService를 그대로 사용한다.
    """

    def __init__(self) -> None:
        self._analysis_service = YtDlpService()
        self._thumbnail_service = ThumbnailService()

    def cancel(self) -> None:
        self._analysis_service.cancel()
        self._thumbnail_service.cancel()

    def recover(
        self,
        task: DownloadTask,
        cancel_event: threading.Event,
        on_phase,
    ) -> ThumbnailRecoveryResult:
        if task.audio_only:
            raise ThumbnailRecoveryError(
                "오디오 전용 작업은 다운로드 목록의 썸네일 복구 대상이 아닙니다.",
                "오디오 커버 이미지는 미디어 도구에서 처리해 주세요.",
            )

        on_phase("기존 영상 파일 확인 중…")
        video_path = self.resolve_task_video_file(task)
        if cancel_event.is_set():
            raise ThumbnailRecoveryCancelledError("썸네일 복구 중지됨")

        if video_path.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            raise ThumbnailRecoveryError(
                "이 영상 형식에는 아직 안전하게 썸네일을 복구할 수 없습니다.",
                "현재 지원 형식: MP4, M4V, MOV, MKV",
            )

        on_phase("복구할 썸네일 확인 중…")
        thumbnail_url = task.thumbnail_url.strip()
        thumbnail_data = bytes(task.thumbnail_data or b"")

        if not thumbnail_data and thumbnail_url:
            thumbnail_data = YtDlpService.download_thumbnail(thumbnail_url)

        if cancel_event.is_set():
            raise ThumbnailRecoveryCancelledError("썸네일 복구 중지됨")

        if not thumbnail_data:
            on_phase("원본 페이지에서 썸네일 다시 확인 중…")
            try:
                media_info = self._analysis_service.analyze(
                    task.url,
                    cancel_event,
                )
            except AnalysisCancelledError as error:
                raise ThumbnailRecoveryCancelledError(str(error)) from error
            except MediaAnalysisError as error:
                raise ThumbnailRecoveryError(
                    "원본 페이지에서 썸네일 정보를 다시 확인하지 못했습니다.",
                    error.technical_detail or error.user_message,
                ) from error

            thumbnail_url = media_info.thumbnail_url.strip()
            if thumbnail_url:
                thumbnail_data = YtDlpService.download_thumbnail(thumbnail_url)

        if cancel_event.is_set():
            raise ThumbnailRecoveryCancelledError("썸네일 복구 중지됨")

        if not thumbnail_data:
            raise ThumbnailRecoveryError(
                "원본 썸네일을 가져오지 못했습니다.",
                "큐에 저장된 썸네일 캐시와 원본 페이지의 썸네일 주소를 모두 확인했지만 이미지를 확보하지 못했습니다.",
            )

        temp_image = self._write_temporary_thumbnail(
            thumbnail_data,
            thumbnail_url,
        )
        try:
            on_phase("썸네일을 영상에 다시 넣는 중…")
            try:
                result = self._thumbnail_service.replace_thumbnail(
                    str(video_path),
                    str(temp_image),
                    ThumbnailOptions(
                        output_mode=OUTPUT_OVERWRITE,
                        delete_image_on_success=False,
                    ),
                    cancel_event,
                )
            except ThumbnailCancelledError as error:
                raise ThumbnailRecoveryCancelledError(str(error)) from error
            except ThumbnailExecutionError as error:
                raise ThumbnailRecoveryError(
                    error.user_message,
                    error.technical_detail,
                ) from error

            if cancel_event.is_set():
                raise ThumbnailRecoveryCancelledError("썸네일 복구 중지됨")

            on_phase("복구 결과 확인 완료")
            return ThumbnailRecoveryResult(
                output_file=result.output_path,
                thumbnail_url=thumbnail_url,
                thumbnail_data=thumbnail_data,
            )
        finally:
            try:
                temp_image.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def resolve_task_video_file(task: DownloadTask) -> Path:
        """완성본만 찾는다. yt-dlp 조각 파일이나 .part는 복구 대상으로 쓰지 않는다."""

        if task.output_file:
            output = Path(task.output_file).expanduser()
            if output.is_file():
                return output

        save_directory = Path(task.save_path).expanduser()
        output_stem = unicodedata.normalize("NFC", task.output_stem).strip()
        if not output_stem or not save_directory.is_dir():
            raise ThumbnailRecoveryError(
                "복구할 완성 영상 파일을 찾지 못했습니다.",
                "다운로드가 영상 본체를 만들기 전에 실패했거나 파일이 이동·삭제된 것으로 보입니다.",
            )

        normalized_stem = output_stem.casefold()
        candidates: list[Path] = []
        try:
            for path in save_directory.iterdir():
                if not path.is_file():
                    continue
                if path.suffix.lower() not in RECOVERY_VIDEO_EXTENSIONS:
                    continue
                path_stem = unicodedata.normalize("NFC", path.stem).casefold()
                # 정확히 같은 stem만 허용해 .f137.mp4 같은 yt-dlp 조각을 제외한다.
                if path_stem != normalized_stem:
                    continue
                candidates.append(path)
        except OSError as error:
            raise ThumbnailRecoveryError(
                "저장 폴더에서 완성 영상 파일을 확인하지 못했습니다.",
                str(error),
            ) from error

        if not candidates:
            raise ThumbnailRecoveryError(
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

    @staticmethod
    def _write_temporary_thumbnail(data: bytes, source_url: str) -> Path:
        suffix = _image_suffix(data, source_url)
        fd, temp_name = tempfile.mkstemp(prefix="rrv_recover_thumb_", suffix=suffix)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return Path(temp_name)


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _image_suffix(data: bytes, source_url: str) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"

    try:
        source_suffix = Path(urlparse(source_url).path).suffix.lower()
    except ValueError:
        source_suffix = ""
    if source_suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return source_suffix

    # FFmpeg는 실제 파일 시그니처를 다시 검사하므로, 확장자를 알 수 없는 CDN
    # 이미지도 일반적인 JPG 입력으로 한 번 처리해 볼 수 있게 한다.
    return ".jpg"
