from __future__ import annotations

from typing import Any

from app.filename_metadata_store import remember_filename_metadata
from core.filename_template import normalize_upload_date
from core.media_info import MediaInfo
from services.ytdlp_service import (
    AnalysisCancelledError,
    MediaAnalysisError,
    YtDlpService as _BaseYtDlpService,
)


class YtDlpService(_BaseYtDlpService):
    """기존 영상 분석 결과에서 파일명 템플릿용 메타데이터도 함께 보관한다."""

    @staticmethod
    def _to_media_info(url: str, info: dict[str, Any]) -> MediaInfo:
        media_info = _BaseYtDlpService._to_media_info(url, info)
        remember_filename_metadata(
            media_info.identity_key,
            upload_date=normalize_upload_date(
                info.get("upload_date") or info.get("release_date") or ""
            ),
            resolutions=media_info.resolutions,
        )
        return media_info


__all__ = [
    "AnalysisCancelledError",
    "MediaAnalysisError",
    "YtDlpService",
]
