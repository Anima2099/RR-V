from __future__ import annotations

import unicodedata

from app.filename_metadata_store import load_filename_metadata
from app.general_preferences import load_general_preferences
from core.download_task import DownloadTask
from core.filename_template import (
    filename_template_values,
    render_filename_template,
    resolution_height_limit,
)
from services.download_service import (
    DownloadExecutionError,
    YtDlpDownloadService as _BaseDownloadService,
)


class YtDlpDownloadService(_BaseDownloadService):
    """기존 다운로드 엔진 위에 RR-V 파일명 템플릿만 적용한다.

    파일명 생성은 최초 영상 분석에서 저장한 로컬 메타데이터와 DownloadTask의
    선택값만 사용한다. 파일명 때문에 yt-dlp나 다른 외부 프로세스를 추가 실행하지
    않는다.
    """

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
