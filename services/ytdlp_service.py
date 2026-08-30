from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.download_log import create_task_log_path, write_download_event
from app.general_preferences import load_general_preferences
from app.paths import (
    RRV_INSTAGRAM_AUTH_COOKIE_PATH,
    RRV_TIKTOK_AUTH_COOKIE_PATH,
    RRV_TOOLS_DIR,
    RRV_WPC_PROVIDER_DIR,
    RRV_WPC_RUNTIME_DIR,
    RRV_YOUTUBE_AUTH_COOKIE_PATH,
    find_executable,
    wpc_provider_runtime_ready,
)
from core.media_info import MediaInfo
from services.cookie_work_file import (
    cleanup_cookie_work_copy_from_command,
    prepare_cookie_work_copy,
)
from services.instagram_auth_service import load_instagram_user_agent


class AnalysisCancelledError(RuntimeError):
    pass


class MediaAnalysisError(RuntimeError):
    def __init__(
        self,
        user_message: str,
        technical_detail: str = "",
        raw_log_path: str = "",
    ) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical_detail = technical_detail
        self.raw_log_path = raw_log_path


class YtDlpService:
    def __init__(self) -> None:
        self.executable = find_executable("yt-dlp.exe")
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()

    @property
    def executable_path(self) -> Path | None:
        return self.executable

    def analyze(
        self,
        url: str,
        cancel_event: threading.Event,
        log_id: str = "",
    ) -> MediaInfo:
        clean_url = self._validate_url(url)

        if self.executable is None:
            detail = f"RR-V 도구 폴더: {RRV_TOOLS_DIR}"
            raw_log_path = self._write_analysis_failure_log(
                log_id,
                clean_url,
                command=(),
                return_code=None,
                stdout="",
                stderr="",
                failure_detail=detail,
            )
            raise MediaAnalysisError(
                "yt-dlp.exe를 찾을 수 없어서 영상 정보를 확인할 수 없습니다.",
                detail,
                raw_log_path,
            )

        command = [
            str(self.executable),
            "--dump-single-json",
            "--skip-download",
            "--no-playlist",
            "--no-warnings",
            "--no-color",
            "--socket-timeout",
            "20",
            "--retries",
            "1",
            "--extractor-retries",
            "1",
        ]

        self.extend_runtime_and_auth_arguments(command, clean_url)

        command.append(clean_url)

        creation_flags = (
            subprocess.CREATE_NO_WINDOW
            if sys.platform == "win32"
            else 0
        )

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
            )
        except OSError as error:
            detail = str(error)
            raw_log_path = self._write_analysis_failure_log(
                log_id,
                clean_url,
                command=command,
                return_code=None,
                stdout="",
                stderr="",
                failure_detail=detail,
            )
            cleanup_cookie_work_copy_from_command(command)
            raise MediaAnalysisError(
                "yt-dlp.exe를 실행하지 못했습니다.",
                detail,
                raw_log_path,
            ) from error

        with self._process_lock:
            self._process = process

        try:
            while True:
                if cancel_event.is_set():
                    self.cancel()
                    raise AnalysisCancelledError("영상 정보 확인 취소됨")

                try:
                    stdout, stderr = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            with self._process_lock:
                self._process = None
            cleanup_cookie_work_copy_from_command(command)

        if cancel_event.is_set():
            raise AnalysisCancelledError("영상 정보 확인 취소됨")

        if process.returncode != 0:
            detail = (stderr or stdout or "알 수 없는 yt-dlp 오류").strip()
            raw_log_path = self._write_analysis_failure_log(
                log_id,
                clean_url,
                command=command,
                return_code=process.returncode,
                stdout=stdout,
                stderr=stderr,
                failure_detail="",
            )
            raise MediaAnalysisError(
                self._friendly_error(detail, clean_url),
                detail,
                raw_log_path,
            )

        try:
            raw_info: dict[str, Any] = json.loads(stdout)
        except json.JSONDecodeError as error:
            detail = f"{error}\n\n{stdout[:2000]}"
            raw_log_path = self._write_analysis_failure_log(
                log_id,
                clean_url,
                command=command,
                return_code=process.returncode,
                stdout=stdout,
                stderr=stderr,
                failure_detail=str(error),
            )
            raise MediaAnalysisError(
                "영상 정보를 읽는 과정에서 응답 형식을 해석하지 못했습니다.",
                detail,
                raw_log_path,
            ) from error

        return self._to_media_info(clean_url, raw_info)

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

    @staticmethod
    def download_thumbnail(url: str) -> bytes:
        if not url:
            return b""

        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 RR-V/0.3"},
        )

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                content_type = response.headers.get("Content-Type", "")
                if content_type and not content_type.startswith("image/"):
                    return b""
                return response.read(8 * 1024 * 1024)
        except (OSError, urllib.error.URLError, ValueError):
            return b""

    @staticmethod
    def _validate_url(url: str) -> str:
        clean_url = url.strip()
        parsed = urlparse(clean_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise MediaAnalysisError(
                "올바른 영상 주소를 입력해 주세요.",
                f"입력값: {clean_url}",
            )
        return clean_url

    @staticmethod
    def _to_media_info(url: str, info: dict[str, Any]) -> MediaInfo:
        video_id = str(info.get("id") or "").strip()
        title = unicodedata.normalize(
            "NFC", str(info.get("title") or "제목 없는 영상").strip()
        )
        extractor = str(
            info.get("extractor_key")
            or info.get("extractor")
            or info.get("webpage_url_domain")
            or "unknown"
        ).strip()
        webpage_url = str(info.get("webpage_url") or url).strip()
        uploader = unicodedata.normalize(
            "NFC",
            str(
                info.get("channel")
                or info.get("uploader")
                or info.get("creator")
                or "알 수 없는 채널"
            ).strip(),
        )
        site_name = str(
            info.get("extractor_key")
            or info.get("webpage_url_domain")
            or ""
        ).strip()

        duration_raw = info.get("duration")
        duration = int(duration_raw) if isinstance(duration_raw, (int, float)) else None

        thumbnail_url = str(info.get("thumbnail") or "").strip()
        if not thumbnail_url:
            thumbnails = info.get("thumbnails") or []
            if isinstance(thumbnails, list):
                valid = [item for item in thumbnails if isinstance(item, dict) and item.get("url")]
                if valid:
                    thumbnail_url = str(valid[-1]["url"])

        resolutions = YtDlpService._extract_resolutions(info)
        manual_subtitles, automatic_subtitles = (
            YtDlpService._extract_subtitle_languages(info)
        )

        if not video_id:
            video_id = webpage_url

        return MediaInfo(
            video_id=video_id,
            extractor=extractor,
            title=title,
            webpage_url=webpage_url,
            original_url=url,
            uploader=uploader,
            duration_seconds=duration,
            thumbnail_url=thumbnail_url,
            site_name=site_name,
            resolutions=resolutions,
            manual_subtitle_languages=manual_subtitles,
            automatic_subtitle_languages=automatic_subtitles,
        )

    @staticmethod
    def _extract_resolutions(info: dict[str, Any]) -> tuple[str, ...]:
        heights: set[int] = set()
        formats = info.get("formats") or []

        if isinstance(formats, list):
            for item in formats:
                if not isinstance(item, dict):
                    continue
                height = item.get("height")
                if isinstance(height, (int, float)) and height > 0:
                    heights.add(int(height))

        ordered = sorted(heights, reverse=True)
        return tuple(f"{height}p" for height in ordered)

    @staticmethod
    def _extract_subtitle_languages(
        info: dict[str, Any],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        def extract(key: str) -> tuple[str, ...]:
            tracks = info.get(key) or {}
            if not isinstance(tracks, dict):
                return ()
            languages = {
                str(language).strip()
                for language in tracks.keys()
                if str(language).strip()
            }
            return tuple(sorted(languages, key=str.lower))

        return extract("subtitles"), extract("automatic_captions")

    @staticmethod
    def is_youtube_url(url: str) -> bool:
        try:
            host = (urlparse(url).hostname or "").lower().rstrip(".")
        except ValueError:
            return False
        return (
            host == "youtu.be"
            or host.endswith(".youtu.be")
            or host == "youtube.com"
            or host.endswith(".youtube.com")
            or host == "youtube-nocookie.com"
            or host.endswith(".youtube-nocookie.com")
        )

    @staticmethod
    def is_instagram_url(url: str) -> bool:
        return YtDlpService._matches_host(url, "instagram.com")

    @staticmethod
    def is_tiktok_url(url: str) -> bool:
        return YtDlpService._matches_host(url, "tiktok.com")

    @staticmethod
    def _append_protected_cookie_argument(command: list[str], cookie_file: Path) -> None:
        # yt-dlp saves its cookie jar back to the file passed with --cookies.
        # RR-V login files are the source of truth, so give yt-dlp a disposable
        # work copy and keep the saved authentication file immutable.
        work_copy = prepare_cookie_work_copy(cookie_file)
        command.extend(["--cookies", str(work_copy)])

    @staticmethod
    def extend_runtime_and_auth_arguments(command: list[str], url: str) -> None:
        if YtDlpService.is_youtube_url(url):
            deno = find_executable("deno.exe")
            if deno is not None:
                command.extend(["--js-runtimes", f"deno:{deno}"])

            # 기본 YouTube client는 yt-dlp가 선택한다. WPC는 설치된 안전망으로
            # 연결만 해 두고, YouTube가 실제로 PO Token을 요구할 때만 사용된다.
            if wpc_provider_runtime_ready():
                command.extend(["--no-plugin-dirs", "--plugin-dirs", str(RRV_WPC_PROVIDER_DIR)])

            # RR-V 전용 로그인 파일은 원본을 보존하고 작업용 복사본만 yt-dlp에
            # 전달한다. yt-dlp가 쿠키를 갱신/삭제해도 다음 작업은 저장된 원본에서
            # 다시 시작한다.
            if RRV_YOUTUBE_AUTH_COOKIE_PATH.is_file():
                YtDlpService._append_protected_cookie_argument(
                    command,
                    RRV_YOUTUBE_AUTH_COOKIE_PATH,
                )
                return

        if YtDlpService.is_instagram_url(url) and RRV_INSTAGRAM_AUTH_COOKIE_PATH.is_file():
            YtDlpService._append_protected_cookie_argument(
                command,
                RRV_INSTAGRAM_AUTH_COOKIE_PATH,
            )
            user_agent = load_instagram_user_agent()
            if user_agent:
                command.extend(["--user-agent", user_agent])
            return

        if YtDlpService.is_tiktok_url(url) and RRV_TIKTOK_AUTH_COOKIE_PATH.is_file():
            YtDlpService._append_protected_cookie_argument(
                command,
                RRV_TIKTOK_AUTH_COOKIE_PATH,
            )
            return

        # Manually supplied cookie files keep their previous behavior. RR-V's
        # own login files above are the credentials that must never be mutated.
        cookie_file = YtDlpService._find_cookie_file(url)
        if cookie_file is not None:
            command.extend(["--cookies", str(cookie_file)])

    @staticmethod
    def authentication_summary(url: str) -> str:
        if YtDlpService.is_youtube_url(url) and RRV_YOUTUBE_AUTH_COOKIE_PATH.is_file():
            return "rrv-login:youtube.txt"
        if YtDlpService.is_instagram_url(url) and RRV_INSTAGRAM_AUTH_COOKIE_PATH.is_file():
            return "rrv-login:instagram.txt"
        if YtDlpService.is_tiktok_url(url) and RRV_TIKTOK_AUTH_COOKIE_PATH.is_file():
            return "rrv-login:tiktok.txt"
        cookie_file = YtDlpService._find_cookie_file(url)
        return f"file:{cookie_file.name}" if cookie_file is not None else "none"

    @staticmethod
    def javascript_runtime_summary(url: str) -> str:
        if not YtDlpService.is_youtube_url(url):
            return "not-required"
        deno = find_executable("deno.exe")
        return f"deno:{deno}" if deno is not None else "deno-missing"

    @staticmethod
    def youtube_support_runtime_summary(url: str) -> str:
        if not YtDlpService.is_youtube_url(url):
            return "not-required"
        if wpc_provider_runtime_ready():
            return f"wpc-available:{RRV_WPC_RUNTIME_DIR}"
        return "wpc-missing"

    @staticmethod
    def find_cookie_file(url: str) -> Path | None:
        return YtDlpService._find_cookie_file(url)

    @staticmethod
    def _find_cookie_file(url: str) -> Path | None:
        if YtDlpService.is_youtube_url(url) and RRV_YOUTUBE_AUTH_COOKIE_PATH.is_file():
            return RRV_YOUTUBE_AUTH_COOKIE_PATH
        if YtDlpService.is_instagram_url(url) and RRV_INSTAGRAM_AUTH_COOKIE_PATH.is_file():
            return RRV_INSTAGRAM_AUTH_COOKIE_PATH
        if YtDlpService.is_tiktok_url(url) and RRV_TIKTOK_AUTH_COOKIE_PATH.is_file():
            return RRV_TIKTOK_AUTH_COOKIE_PATH

        raw_folder = load_general_preferences().cookie_folder.strip()
        if not raw_folder:
            return None
        cookie_directory = Path(raw_folder).expanduser()
        if not cookie_directory.is_dir():
            return None

        lowered_url = url.lower()
        rules = {
            "youtube": ("youtube.txt", "유튜브.txt"),
            "chzzk": ("chzzk.txt", "치지직.txt"),
            "soop": ("soop.txt", "afreecatv.txt", "숲.txt", "아프리카.txt"),
            "twitch": ("twitch.txt", "트위치.txt"),
            "instagram": ("instagram.txt", "인스타그램.txt", "insta.txt"),
            "tiktok": ("tiktok.txt", "틱톡.txt"),
        }

        names: tuple[str, ...] = ("cookies.txt", "cookie.txt")
        for site, site_names in rules.items():
            if site in lowered_url or (site == "soop" and "afreeca" in lowered_url):
                names = site_names + names
                break

        for name in names:
            candidate = cookie_directory / name
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _friendly_error(detail: str, url: str = "") -> str:
        lowered = detail.lower()
        is_youtube = YtDlpService.is_youtube_url(url)
        is_instagram = YtDlpService._matches_host(url, "instagram.com")
        is_tiktok = YtDlpService.is_tiktok_url(url)

        if is_instagram and any(
            token in lowered
            for token in (
                "this content isn't available to everyone",
                "can't be seen by certain audiences",
                "cannot be seen by certain audiences",
            )
        ):
            return (
                "Instagram에서 일부 사용자에게 제한된 콘텐츠입니다. "
                "로그인 또는 계정 인증이 필요한 영상일 수 있습니다."
            )

        if is_tiktok and "unexpected response from webpage request" in lowered:
            return (
                "TikTok이 현재 yt-dlp가 예상한 방식으로 응답하지 않아 영상 정보를 "
                "가져오지 못했습니다. yt-dlp 업데이트 후 다시 시도하거나 잠시 후 "
                "다시 확인해 주세요."
            )

        login_tokens = ("sign in", "login", "cookies", "cookie")
        if is_instagram and any(token in lowered for token in login_tokens):
            return (
                "Instagram 로그인이 필요한 콘텐츠로 보입니다. 설정 > 사이트 인증에서 "
                "Instagram 로그인 또는 인증 갱신을 실행한 뒤 다시 시도해 주세요."
            )
        if is_tiktok and any(token in lowered for token in login_tokens):
            return (
                "TikTok 로그인이 필요한 콘텐츠로 보입니다. 설정 > 사이트 인증에서 "
                "TikTok 로그인 또는 인증 갱신을 실행한 뒤 다시 시도해 주세요."
            )

        if "sign in to confirm" in lowered or "not a bot" in lowered:
            return (
                "유튜브가 봇 확인을 위해 로그인을 요구했습니다. "
                "설정 > 사이트 인증에서 로그인 / 인증 갱신을 실행한 뒤 다시 시도해 주세요."
            )
        if any(token in lowered for token in ("po token", "pot provider", "webpoclient", "wpc")):
            return "YouTube 추가 인증에 필요한 WPC 런타임을 사용할 수 없습니다. 설정 > 도구 및 리소스에서 YouTube 인증 런타임 상태를 확인해 주세요."
        if "javascript runtime" in lowered or "js runtime" in lowered:
            return "YouTube 검증에 필요한 Deno를 사용할 수 없습니다. 설정 > 도구 및 리소스에서 Deno 상태를 확인해 주세요."
        if any(token in lowered for token in login_tokens):
            if is_youtube:
                return (
                    "로그인 또는 쿠키가 필요한 영상이거나 YouTube 인증 정보가 만료된 "
                    "것으로 보입니다. 설정 > 사이트 인증에서 인증 갱신을 시도해 주세요."
                )
            return "로그인 또는 쿠키가 필요한 콘텐츠로 보입니다. 해당 사이트의 인증이 필요한지 확인해 주세요."
        if any(token in lowered for token in ("unsupported url", "no suitable extractor")):
            return "현재 yt-dlp가 지원하지 않는 주소로 보입니다."
        if any(token in lowered for token in ("404", "not found")):
            return "영상 페이지를 찾을 수 없습니다. 주소가 올바른지 확인해 주세요."
        if any(token in lowered for token in ("private video", "video unavailable", "not available")):
            return "영상이 비공개이거나 현재 재생할 수 없는 상태입니다."
        if any(token in lowered for token in ("timed out", "timeout", "temporary failure", "network")):
            return "네트워크 연결이 불안정해서 영상 정보를 확인하지 못했습니다."
        return "영상 정보를 확인하지 못했습니다. 아래 상세 내용에서 실패 원인을 확인해 주세요."

    @staticmethod
    def _matches_host(url: str, domain: str) -> bool:
        try:
            host = (urlparse(url).hostname or "").lower().rstrip(".")
        except ValueError:
            return False
        normalized = domain.lower().rstrip(".")
        return host == normalized or host.endswith(f".{normalized}")

    @staticmethod
    def _write_analysis_failure_log(
        log_id: str,
        url: str,
        *,
        command: tuple[str, ...] | list[str],
        return_code: int | None,
        stdout: str,
        stderr: str,
        failure_detail: str,
    ) -> str:
        if not log_id:
            return ""
        log_path = create_task_log_path(log_id)
        try:
            with log_path.open("w", encoding="utf-8") as raw_log:
                raw_log.write("RR-V yt-dlp analysis failure log\n")
                raw_log.write(f"Analysis: {log_id}\n")
                raw_log.write(f"URL: {url}\n")
                raw_log.write(
                    f"Authentication: {YtDlpService.authentication_summary(url)}\n"
                )
                raw_log.write(
                    f"JavaScript runtime: {YtDlpService.javascript_runtime_summary(url)}\n"
                )
                raw_log.write(
                    "YouTube support runtime: "
                    f"{YtDlpService.youtube_support_runtime_summary(url)}\n"
                )
                if command:
                    raw_log.write(
                        f"Command: {YtDlpService._display_command(command)}\n"
                    )
                raw_log.write(
                    f"Return code: {return_code if return_code is not None else '-'}\n"
                )
                raw_log.write("=" * 72 + "\n")
                if failure_detail:
                    raw_log.write("Failure detail:\n")
                    raw_log.write(
                        YtDlpService._sanitize_analysis_log_text(
                            failure_detail,
                            url,
                        ).rstrip()
                        + "\n"
                    )
                if stderr.strip():
                    raw_log.write("\nSTDERR:\n")
                    raw_log.write(
                        YtDlpService._sanitize_analysis_log_text(stderr, url).rstrip()
                        + "\n"
                    )
                if stdout.strip():
                    raw_log.write("\nSTDOUT:\n")
                    raw_log.write(
                        YtDlpService._sanitize_analysis_log_text(stdout, url).rstrip()
                        + "\n"
                    )
        except OSError as error:
            write_download_event(
                "analysis.log_write_failed",
                analysis_id=log_id,
                error=error,
            )
            return ""

        write_download_event(
            "analysis.failed",
            analysis_id=log_id,
            raw_log=log_path,
        )
        return str(log_path)

    @staticmethod
    def _display_command(command: tuple[str, ...] | list[str]) -> str:
        displayed: list[str] = []
        redact_next = False
        for item in command:
            if redact_next:
                displayed.append("<cookie-file>")
                redact_next = False
                continue
            displayed.append(str(item))
            if item == "--cookies":
                redact_next = True
        return subprocess.list2cmdline(displayed)

    @staticmethod
    def _sanitize_analysis_log_text(text: str, url: str) -> str:
        sanitized = text
        cookie_file = YtDlpService.find_cookie_file(url)
        if cookie_file is not None:
            cookie_text = str(cookie_file)
            sanitized = sanitized.replace(cookie_text, "<cookie-file>")
            sanitized = sanitized.replace(
                cookie_text.replace("\\", "\\\\"),
                "<cookie-file>",
            )
        sanitized = re.sub(
            r"(?im)^(\s*Authorization\s*:\s*).*$",
            r"\1<redacted>",
            sanitized,
        )
        sanitized = re.sub(
            r"(?im)^(\s*Cookie\s*:\s*).*$",
            r"\1<redacted>",
            sanitized,
        )
        sanitized = re.sub(
            r"(?i)((?:po[_ -]?token|visitor[_ -]?data|data[_ -]?sync[_ -]?id)\s*[=:]\s*)([^\s,;\]\}\)]+)",
            r"\1<redacted>",
            sanitized,
        )
        return sanitized
