from __future__ import annotations

from app.general_preferences import load_general_preferences
from core.download_task import DownloadTask
from core.filename_template import (
    filename_template_values,
    render_filename_template,
)
from services.download_service import YtDlpDownloadService as _BaseDownloadService


class YtDlpDownloadService(_BaseDownloadService):
    """기존 다운로드 엔진 위에 RR-V 파일명 템플릿만 적용한다."""

    @staticmethod
    def _filename_title(task: DownloadTask) -> str:
        legacy_title = _BaseDownloadService._filename_title(task)
        template = load_general_preferences().filename_template
        values = filename_template_values(
            title=legacy_title,
            uploader=task.uploader,
            video_id=task.video_id,
            extractor=task.extractor,
        )
        return render_filename_template(template, values)
