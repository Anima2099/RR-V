from __future__ import annotations

from pathlib import Path
import threading
import unicodedata

from app.download_log import write_download_event
from app.filename_metadata_store import load_filename_metadata
from app.general_preferences import load_general_preferences
from app.preset_store import load_preset_library
from core.download_task import DownloadTask
from core.filename_template import (
    filename_template_values,
    render_filename_template,
    resolution_height_limit,
)
from core.local_media_info import MediaChapter, MediaFileInfo
from services.chapter_split_service import (
    ChapterSplitCancelledError,
    ChapterSplitError,
    ChapterSplitService,
    valid_chapters,
)
from services.download_service import (
    DownloadCancelledError,
    DownloadExecutionError,
    DownloadResult,
    YtDlpDownloadService as _BaseDownloadService,
)
from services.media_probe_service import (
    MediaProbeCancelledError,
    MediaProbeError,
    MediaProbeService,
)


class YtDlpDownloadService(_BaseDownloadService):
    """기존 다운로드 엔진 위에 1.4의 가벼운 후처리만 덧붙인다.

    일반 다운로드는 검증된 기존 yt-dlp 경로를 그대로 사용한다. 파일명 템플릿은
    최초 분석 캐시만 사용하고, 챕터 분할을 선택한 작업만 다운로드 완료 뒤 RR-V의
    FFmpeg 스트림 복사 엔진으로 별도 챕터 파일을 만든다.
    """

    def __init__(self) -> None:
        super().__init__()
        self._chapter_split_service = ChapterSplitService()
        self._chapter_probe_service = MediaProbeService()

    def download(
        self,
        task: DownloadTask,
        cancel_event: threading.Event,
        on_progress,
        on_phase,
        on_process,
    ) -> DownloadResult:
        # 다운로드 자체에는 --split-chapters를 주입하지 않는다. 먼저 기존 안정 경로로
        # 완성 파일을 확보한 뒤, 필요한 작업만 별도 후처리한다.
        result = super().download(
            task,
            cancel_event,
            on_progress,
            on_phase,
            on_process,
        )

        if not self._resolve_chapter_split_intent(task):
            return result
        if cancel_event.is_set():
            raise DownloadCancelledError("챕터 분할 시작 전 다운로드가 중지되었습니다.")

        output_path = Path(result.output_file)
        media_info = self._media_info_for_chapter_split(task, output_path, cancel_event)
        if media_info is None or not valid_chapters(media_info):
            write_download_event(
                "download.chapter_split_skipped",
                task_id=task.task_id,
                reason="no usable chapters",
                output=output_path,
            )
            on_phase("postprocessing", "내장 챕터가 없어 분할을 건너뜁니다.")
            return result

        chapter_count = len(valid_chapters(media_info))
        on_phase(
            "postprocessing",
            f"챕터 {chapter_count}개를 별도 파일로 저장하는 중…",
        )
        write_download_event(
            "download.chapter_split_started",
            task_id=task.task_id,
            chapter_count=chapter_count,
            output=output_path,
        )

        try:
            split_result = self._chapter_split_service.split(
                media_info,
                on_progress=None,
                on_phase=lambda message: on_phase("postprocessing", message),
                is_cancelled=cancel_event.is_set,
            )
        except ChapterSplitCancelledError as error:
            raise DownloadCancelledError(str(error) or "챕터 분할 중지됨") from error
        except ChapterSplitError as error:
            write_download_event(
                "download.chapter_split_failed",
                task_id=task.task_id,
                output=output_path,
                detail=error.technical_detail or error.user_message,
            )
            raise DownloadExecutionError(
                "영상 다운로드는 완료됐지만 챕터별 파일 저장에 실패했습니다.",
                error.technical_detail or error.user_message,
            ) from error

        write_download_event(
            "download.chapter_split_completed",
            task_id=task.task_id,
            chapter_count=split_result.count,
            output_directory=split_result.output_directory,
        )

        completion_message = f"챕터별 파일 저장 완료 · {split_result.count}개"
        completion_result = result
        if task.delete_original_after_split:
            try:
                output_path.unlink(missing_ok=True)
            except OSError as error:
                write_download_event(
                    "download.chapter_original_delete_failed",
                    task_id=task.task_id,
                    output=output_path,
                    error=str(error),
                )
                completion_message += " · 원본 삭제 실패"
            else:
                write_download_event(
                    "download.chapter_original_deleted",
                    task_id=task.task_id,
                    output=output_path,
                )
                completion_message += " · 원본 삭제"
                # 완료 카드가 존재하지 않는 원본을 가리키지 않도록 첫 챕터를
                # 대표 완료 파일로 사용한다. 전체 결과는 같은 _chapters 폴더에 있다.
                if split_result.output_files:
                    completion_result = DownloadResult(
                        output_file=split_result.output_files[0],
                        raw_log_path=result.raw_log_path,
                    )

        on_phase("postprocessing", completion_message)
        return completion_result

    def cancel(self) -> None:
        # 다운로드 중지 버튼 하나로 현재 단계가 yt-dlp이든 FFprobe/FFmpeg 후처리든
        # 모두 중단할 수 있게 각 프로세스 소유자에게 취소를 전달한다.
        self._chapter_split_service.cancel()
        self._chapter_probe_service.cancel()
        super().cancel()

    def _resolve_chapter_split_intent(self, task: DownloadTask) -> bool:
        if task.audio_only:
            task.split_chapters = False
            task.delete_original_after_split = False
            return False
        if task.split_chapters:
            return True

        # 현재 DownloadTask에는 기존 프리셋 이름이 이미 저장된다. 1.4 이전에 만든
        # 대기 작업에도 안전하게 적용할 수 있도록 이름으로 한 번만 보완 확인한다.
        try:
            preset = load_preset_library().get_by_name(task.preset)
        except Exception:
            preset = None
        task.split_chapters = bool(preset and preset.split_chapters)
        if not task.split_chapters:
            task.delete_original_after_split = False
        return task.split_chapters

    def _media_info_for_chapter_split(
        self,
        task: DownloadTask,
        output_path: Path,
        cancel_event: threading.Event,
    ) -> MediaFileInfo | None:
        metadata = load_filename_metadata(task.identity_key)
        cached_chapters = tuple(
            MediaChapter(
                index=index,
                start_seconds=start,
                end_seconds=end,
                title=title,
            )
            for index, (start, end, title) in enumerate(metadata.chapters)
        )
        if cached_chapters:
            try:
                size_bytes = max(0, output_path.stat().st_size)
            except OSError:
                size_bytes = 0
            return MediaFileInfo(
                path=str(output_path),
                file_name=output_path.name,
                size_bytes=size_bytes,
                chapters=cached_chapters,
            )

        # 오래된 대기 작업처럼 분석 캐시에 챕터가 없는 경우만 완성 파일을 한 번
        # FFprobe한다. 메타데이터 보존 옵션으로 챕터가 내장된 경우의 안전망이다.
        try:
            return self._chapter_probe_service.probe(
                str(output_path),
                is_cancelled=cancel_event.is_set,
            )
        except MediaProbeCancelledError as error:
            raise DownloadCancelledError("챕터 확인 중지됨") from error
        except MediaProbeError as error:
            write_download_event(
                "download.chapter_split_probe_failed",
                task_id=task.task_id,
                output=output_path,
                detail=error.technical_detail or error.user_message,
            )
            return None

    def _filename_title(self, task: DownloadTask) -> str:
        template = load_general_preferences().filename_template
        raw_title = unicodedata.normalize("NFC", task.title).strip() or "video"

        # Instagram Reel의 일반적인 'Video by ...' 제목에는 기존 RR-V가 Reel ID를
        # 자동 보강한다. 사용자가 템플릿에 {영상ID}를 직접 넣었다면 같은 ID가
        # 두 번 붙지 않도록 제목 쪽 자동 보강만 생략한다.
        legacy_title = (
            raw_title
            if "{영상ID}" in template
            else _BaseDownloadService._filename_title(task)
        )

        metadata = load_filename_metadata(task.identity_key)
        values = filename_template_values(
            title=legacy_title,
            uploader=task.uploader,
            video_id=task.video_id,
            extractor=task.extractor,
            resolution=task.resolution,
            available_resolutions=metadata.resolutions,
            upload_date=metadata.upload_date,
            duration_text=task.duration_text,
            preset=task.preset,
            codec=task.codec,
            audio_only=task.audio_only,
            audio_format=task.audio_format,
        )
        return render_filename_template(template, values)

    @staticmethod
    def _format_selector(task: DownloadTask) -> str:
        """기존 선택 규칙을 유지하면서 감지된 임의 p 해상도도 제한값으로 받는다."""
        height = resolution_height_limit(task.resolution)
        height_filter = f"[height<={height}]" if height else ""
        codec_filters = {
            "H.264": "[vcodec^=avc1]",
            "VP9": "[vcodec^=vp9]",
            "AV1": "[vcodec^=av01]",
        }
        codec_filter = codec_filters.get(task.codec, "")
        container = task.container.lower()

        if container == "webm" and task.codec == "H.264":
            raise DownloadExecutionError(
                "WebM과 H.264 조합은 사용할 수 없습니다.",
                "파일 형식을 MP4/MKV로 바꾸거나 코덱을 VP9/AV1로 선택해 주세요.",
            )

        if container == "mp4" and task.codec == "H.264":
            return (
                f"bestvideo*{height_filter}[ext=mp4]{codec_filter}+bestaudio[ext=m4a]/"
                f"bestvideo*{height_filter}[ext=mp4]+bestaudio[ext=m4a]/"
                f"bestvideo*{height_filter}+bestaudio/best{height_filter}"
            )

        if container == "webm":
            return (
                f"bestvideo*{height_filter}[ext=webm]{codec_filter}+bestaudio[ext=webm]/"
                f"bestvideo*{height_filter}[ext=webm]+bestaudio[ext=webm]/"
                f"bestvideo*{height_filter}+bestaudio/best{height_filter}"
            )

        return (
            f"bestvideo*{height_filter}{codec_filter}+bestaudio/"
            f"bestvideo*{height_filter}+bestaudio/best{height_filter}"
        )
