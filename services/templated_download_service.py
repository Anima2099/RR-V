from __future__ import annotations

from dataclasses import dataclass
import subprocess
import sys
import threading

from app.general_preferences import load_general_preferences
from core.download_task import DownloadTask
from core.filename_template import (
    filename_template_values,
    normalize_upload_date,
    render_filename_template,
)
from services.cookie_work_file import cleanup_cookie_work_copy_from_command
from services.download_service import (
    DownloadExecutionError,
    YtDlpDownloadService as _BaseDownloadService,
)
from services.ytdlp_service import YtDlpService


@dataclass(slots=True, frozen=True)
class _TemplateProbeResult:
    upload_date: str = ""
    height: int | None = None
    codec: str = ""
    duration_seconds: float | None = None


class YtDlpDownloadService(_BaseDownloadService):
    """기존 다운로드 엔진 위에 RR-V 파일명 템플릿만 적용한다."""

    META_PREFIX = "RRV_FILENAME_META|"
    _probe_cache: dict[tuple[str, str, str, str, bool, str], _TemplateProbeResult] = {}
    _probe_cache_lock = threading.Lock()

    def _filename_title(self, task: DownloadTask) -> str:
        legacy_title = _BaseDownloadService._filename_title(task)
        template = load_general_preferences().filename_template
        probe = self._probe_template_metadata(task, template)
        values = filename_template_values(
            title=legacy_title,
            uploader=task.uploader,
            video_id=task.video_id,
            extractor=task.extractor,
            resolution=task.resolution,
            upload_date=probe.upload_date,
            duration_text=task.duration_text,
            duration_seconds=probe.duration_seconds,
            preset=task.preset,
            codec=task.codec,
            probed_height=probe.height,
            probed_codec=probe.codec,
            audio_only=task.audio_only,
            audio_format=task.audio_format,
        )
        return render_filename_template(template, values)

    def _probe_template_metadata(
        self,
        task: DownloadTask,
        template: str,
    ) -> _TemplateProbeResult:
        advanced_tokens = (
            "{업로드날짜}",
            "{업로드날짜6}",
            "{해상도}",
            "{코덱}",
        )
        if not any(token in template for token in advanced_tokens):
            return _TemplateProbeResult()
        if self.executable is None:
            return _TemplateProbeResult()

        key = (
            task.identity_key,
            task.resolution,
            task.codec,
            task.container,
            task.audio_only,
            task.audio_format,
        )
        with self._probe_cache_lock:
            cached = self._probe_cache.get(key)
        if cached is not None:
            return cached

        result = self._run_template_probe(task)
        with self._probe_cache_lock:
            self._probe_cache[key] = result
        return result

    def _run_template_probe(self, task: DownloadTask) -> _TemplateProbeResult:
        if self.executable is None:
            return _TemplateProbeResult()

        command = [
            str(self.executable),
            "--simulate",
            "--no-playlist",
            "--no-warnings",
            "--no-color",
            "--socket-timeout",
            "20",
            "--retries",
            "1",
            "--print",
            (
                self.META_PREFIX
                + "%(upload_date)s|%(height)s|%(vcodec)s|%(duration)s"
            ),
        ]

        try:
            YtDlpService.extend_runtime_and_auth_arguments(command, task.url)
            if task.audio_only:
                command.extend(["-f", "bestaudio/best"])
            else:
                try:
                    selector = self._format_selector(task)
                except DownloadExecutionError:
                    return _TemplateProbeResult()
                command.extend(["-f", selector])
            command.append(task.url)

            creation_flags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if sys.platform == "win32"
                else 0
            )
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return _TemplateProbeResult()
        finally:
            cleanup_cookie_work_copy_from_command(command)

        if completed.returncode != 0:
            return _TemplateProbeResult()

        for raw_line in reversed(completed.stdout.splitlines()):
            line = raw_line.strip()
            if not line.startswith(self.META_PREFIX):
                continue
            payload = line[len(self.META_PREFIX):]
            parts = payload.split("|", 3)
            if len(parts) != 4:
                continue
            upload_date = normalize_upload_date(parts[0])
            height = self._safe_positive_int(parts[1])
            codec = self._clean_probe_value(parts[2])
            duration_seconds = self._safe_nonnegative_float(parts[3])
            return _TemplateProbeResult(
                upload_date=upload_date,
                height=height,
                codec=codec,
                duration_seconds=duration_seconds,
            )

        return _TemplateProbeResult()

    @staticmethod
    def _clean_probe_value(value: object) -> str:
        cleaned = str(value or "").strip()
        if cleaned.lower() in {"", "na", "n/a", "none", "null", "unknown"}:
            return ""
        return cleaned

    @staticmethod
    def _safe_positive_int(value: object) -> int | None:
        try:
            parsed = int(float(str(value).strip()))
        except (TypeError, ValueError, OverflowError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _safe_nonnegative_float(value: object) -> float | None:
        try:
            parsed = float(str(value).strip())
        except (TypeError, ValueError, OverflowError):
            return None
        return parsed if parsed >= 0 else None
