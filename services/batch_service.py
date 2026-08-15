from __future__ import annotations

import json
import subprocess
import sys
import threading
import unicodedata
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from app.paths import RRV_TOOLS_DIR, find_executable
from core.batch_entry import BatchAnalysisResult, BatchEntry, BatchSourceError
from services.ytdlp_service import YtDlpService


class BatchAnalysisCancelledError(RuntimeError):
    pass


class BatchAnalysisService:
    def __init__(self) -> None:
        self.executable = find_executable("yt-dlp.exe")
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()

    def analyze_sources(
        self,
        urls: list[str],
        cancel_event: threading.Event,
        status_callback: Callable[[str], None] | None = None,
    ) -> BatchAnalysisResult:
        if self.executable is None:
            return BatchAnalysisResult(
                entries=(),
                errors=(
                    BatchSourceError(
                        source_url="",
                        message="yt-dlp.exe를 찾을 수 없어서 일괄 목록을 확인할 수 없습니다.",
                        detail=f"RR-V 도구 폴더: {RRV_TOOLS_DIR}",
                    ),
                ),
                source_count=len(urls),
            )

        collected: list[BatchEntry] = []
        errors: list[BatchSourceError] = []
        seen_identity: set[str] = set()
        seen_urls: set[str] = set()

        total = len(urls)
        for index, source_url in enumerate(urls, start=1):
            if cancel_event.is_set():
                raise BatchAnalysisCancelledError("일괄 목록 확인 취소됨")

            if status_callback is not None:
                status_callback(f"{index}/{total} 주소의 영상 목록을 확인 중…")

            try:
                entries = self._analyze_source(source_url, cancel_event)
            except BatchAnalysisCancelledError:
                raise
            except Exception as error:  # 한 주소의 실패가 전체 결과를 막지 않게 한다.
                detail = str(error).strip() or repr(error)
                errors.append(
                    BatchSourceError(
                        source_url=source_url,
                        message=YtDlpService._friendly_error(detail),
                        detail=detail,
                    )
                )
                continue

            for entry in entries:
                normalized_url = entry.webpage_url.strip().lower()
                if entry.identity_key in seen_identity or normalized_url in seen_urls:
                    continue
                seen_identity.add(entry.identity_key)
                seen_urls.add(normalized_url)
                collected.append(entry)

        return BatchAnalysisResult(
            entries=tuple(collected),
            errors=tuple(errors),
            source_count=total,
        )

    def cancel(self) -> None:
        with self._process_lock:
            process = self._process

        if process is None or process.poll() is not None:
            return

        try:
            process.terminate()
            process.wait(timeout=1.5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass

    def _analyze_source(
        self,
        source_url: str,
        cancel_event: threading.Event,
    ) -> list[BatchEntry]:
        assert self.executable is not None

        clean_url = YtDlpService._validate_url(source_url)
        command = [
            str(self.executable),
            "--dump-single-json",
            "--skip-download",
            "--flat-playlist",
            "--yes-playlist",
            "--ignore-errors",
            "--no-warnings",
            "--no-color",
            "--socket-timeout",
            "30",
            "--retries",
            "2",
            "--extractor-retries",
            "2",
        ]

        YtDlpService.extend_runtime_and_auth_arguments(command, clean_url)
        command.append(clean_url)

        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
        )

        with self._process_lock:
            self._process = process

        try:
            while True:
                if cancel_event.is_set():
                    self.cancel()
                    raise BatchAnalysisCancelledError("일괄 목록 확인 취소됨")
                try:
                    stdout, stderr = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            with self._process_lock:
                self._process = None

        if cancel_event.is_set():
            raise BatchAnalysisCancelledError("일괄 목록 확인 취소됨")
        if process.returncode != 0:
            raise RuntimeError((stderr or stdout or "알 수 없는 yt-dlp 오류").strip())

        try:
            raw_info: dict[str, Any] = json.loads(stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"yt-dlp 응답을 해석하지 못했습니다: {error}\n{stdout[:2000]}"
            ) from error

        source_title = self._normalized_text(
            raw_info.get("title") or raw_info.get("playlist_title") or "개별 영상"
        )
        raw_entries = raw_info.get("entries")
        if isinstance(raw_entries, list):
            entries: list[BatchEntry] = []
            for raw_entry in raw_entries:
                if not isinstance(raw_entry, dict):
                    continue
                entry = self._entry_from_info(
                    source_url=clean_url,
                    source_title=source_title,
                    info=raw_entry,
                    source_info=raw_info,
                )
                if entry is not None:
                    entries.append(entry)
            return entries

        entry = self._entry_from_info(
            source_url=clean_url,
            source_title="개별 주소",
            info=raw_info,
            source_info=raw_info,
        )
        return [entry] if entry is not None else []

    def _entry_from_info(
        self,
        *,
        source_url: str,
        source_title: str,
        info: dict[str, Any],
        source_info: dict[str, Any],
    ) -> BatchEntry | None:
        video_id = str(info.get("id") or "").strip()
        extractor = str(
            info.get("extractor_key")
            or info.get("extractor")
            or source_info.get("extractor_key")
            or source_info.get("extractor")
            or urlparse(source_url).netloc
            or "unknown"
        ).strip()

        webpage_url = self._resolve_entry_url(
            source_url=source_url,
            info=info,
            video_id=video_id,
            extractor=extractor,
        )
        if not webpage_url:
            return None

        title = self._normalized_text(
            info.get("title") or info.get("fulltitle") or video_id or "제목 없는 영상"
        )
        uploader = self._normalized_text(
            info.get("channel")
            or info.get("uploader")
            or info.get("creator")
            or source_info.get("channel")
            or source_info.get("uploader")
            or "알 수 없는 채널"
        )
        duration = self._safe_duration(info.get("duration"))
        thumbnail_url = self._thumbnail_url(info)

        if not video_id:
            video_id = webpage_url

        return BatchEntry(
            source_url=source_url,
            source_title=source_title,
            video_id=video_id,
            extractor=extractor,
            title=title,
            webpage_url=webpage_url,
            uploader=uploader,
            duration_seconds=duration,
            thumbnail_url=thumbnail_url,
        )

    @staticmethod
    def _resolve_entry_url(
        *,
        source_url: str,
        info: dict[str, Any],
        video_id: str,
        extractor: str,
    ) -> str:
        for key in ("webpage_url", "original_url", "url"):
            value = str(info.get(key) or "").strip()
            parsed = urlparse(value)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                return value

        extractor_lower = extractor.lower()
        source_host = urlparse(source_url).netloc.lower()
        if video_id and ("youtube" in extractor_lower or "youtu" in source_host):
            return f"https://www.youtube.com/watch?v={video_id}"

        # 일부 추출기는 재생목록 주소에 현재 영상 ID를 넣어 단일 주소를 만들 수 있다.
        parsed_source = urlparse(source_url)
        query = parse_qs(parsed_source.query)
        if video_id and "v" in query and "youtu" in source_host:
            return f"https://www.youtube.com/watch?v={video_id}"
        return ""

    @staticmethod
    def _thumbnail_url(info: dict[str, Any]) -> str:
        direct = str(info.get("thumbnail") or "").strip()
        if direct:
            return direct
        thumbnails = info.get("thumbnails")
        if not isinstance(thumbnails, list):
            return ""
        valid = [
            str(item.get("url") or "").strip()
            for item in thumbnails
            if isinstance(item, dict) and str(item.get("url") or "").strip()
        ]
        return valid[-1] if valid else ""

    @staticmethod
    def _safe_duration(value: object) -> int | None:
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
        try:
            parsed = float(str(value))
        except (TypeError, ValueError):
            return None
        return int(parsed) if parsed >= 0 else None

    @staticmethod
    def _normalized_text(value: object) -> str:
        return unicodedata.normalize("NFC", str(value or "").strip())
