from __future__ import annotations

import platform
from pathlib import Path
import re
import sys

from app.constants import APP_VERSION
from app.tool_manager import inspect_tools
from core.download_task import DownloadTask


_MAX_RAW_LOG_LINES = 120
_MAX_RAW_LOG_CHARS = 12000


def _redact_sensitive_text(text: object, task: DownloadTask) -> str:
    sanitized = str(text or "")

    sanitized = re.sub(
        r"(?im)(\bAuthorization\s*:\s*)[^\r\n]*",
        r"\1<redacted>",
        sanitized,
    )
    sanitized = re.sub(
        r"(?im)(\bCookie\s*:\s*)[^\r\n]*",
        r"\1<redacted>",
        sanitized,
    )
    sanitized = re.sub(
        r"(?i)((?:po[_ -]?token|visitor[_ -]?data|data[_ -]?sync[_ -]?id)\s*[=:]\s*)([^\s,;\]\}\)]+)",
        r"\1<redacted>",
        sanitized,
    )
    sanitized = re.sub(
        (
            r"(?i)([?&](?:pot|sig|lsig|spc|bui|cps|n|token|access_token|"
            r"refresh_token|auth|authorization|api_key|apikey|session|"
            r"sessionid|jwt)=)[^&\s\"]+"
        ),
        r"\1<redacted>",
        sanitized,
    )
    sanitized = re.sub(
        r'(?i)("(?:visitorData|rolloutToken|appInstallData|deviceExperimentId)"\s*:\s*")[^"]+(")',
        r"\1<redacted>\2",
        sanitized,
    )
    sanitized = re.sub(
        r'(?i)("remoteHost"\s*:\s*")[^"]+(")',
        r"\1<redacted>\2",
        sanitized,
    )

    replacements = (
        (task.raw_log_path, "<raw-log>"),
        (task.save_path, "<save-path>"),
        (str(Path.home()), "<home>"),
    )
    for raw, replacement in replacements:
        value = str(raw or "").strip()
        if not value:
            continue
        sanitized = sanitized.replace(value, replacement)
        sanitized = sanitized.replace(
            value.replace("\\", "\\\\"),
            replacement,
        )

    return sanitized


def _read_raw_log_tail(task: DownloadTask) -> str:
    raw_path = str(task.raw_log_path or "").strip()
    if not raw_path:
        return "원본 로그 없음"

    path = Path(raw_path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "원본 로그를 읽지 못했습니다."

    lines = text.splitlines()
    omitted = max(0, len(lines) - _MAX_RAW_LOG_LINES)
    selected = lines[-_MAX_RAW_LOG_LINES:]
    tail = "\n".join(selected)

    if len(tail) > _MAX_RAW_LOG_CHARS:
        tail = tail[-_MAX_RAW_LOG_CHARS:]
        tail = "[앞부분 생략]\n" + tail.lstrip()

    if omitted:
        tail = f"[앞부분 {omitted}줄 생략]\n" + tail

    return _redact_sensitive_text(tail, task)


def _tool_status_lines() -> list[str]:
    try:
        statuses = inspect_tools()
    except Exception as error:
        return [f"도구 상태 확인 실패: {type(error).__name__}"]

    lines: list[str] = []
    for status in statuses:
        state = "OK" if status.available else "MISSING/ERROR"
        version = str(status.version or "확인 불가").strip() or "확인 불가"
        lines.append(f"- {status.label}: {state} | {version}")
    return lines or ["- 확인 가능한 도구 정보 없음"]


def build_download_problem_report(task: DownloadTask) -> str:
    """실패 작업을 외부에 공유하기 쉬운 진단 텍스트로 만든다."""

    url = _redact_sensitive_text(task.url, task)
    error_message = _redact_sensitive_text(task.error_message, task) or "-"
    error_detail = _redact_sensitive_text(task.error_detail, task) or "-"
    phase = _redact_sensitive_text(task.phase_message, task) or "-"
    title = _redact_sensitive_text(task.title, task) or "-"
    source = " / ".join(
        item
        for item in (
            str(task.extractor or "").strip(),
            str(task.video_id or "").strip(),
        )
        if item
    ) or "-"

    lines = [
        "=== RR-V 문제 보고 정보 ===",
        f"RR-V: {APP_VERSION}",
        f"OS: {platform.platform()}",
        f"Python: {sys.version.split()[0]}",
        "",
        "[작업]",
        f"제목: {title}",
        f"URL: {url}",
        f"사이트 / ID: {source}",
        f"상태: {task.status.value}",
        f"프리셋: {task.preset}",
        f"설정: {task.meta_text}",
        f"진행률: {task.progress}%",
        f"현재 단계: {phase}",
        "",
        "[오류]",
        f"메시지: {error_message}",
        "기술 상세:",
        error_detail,
        "",
        "[도구 상태]",
        *_tool_status_lines(),
        "",
        "[원본 로그 마지막 부분]",
        _read_raw_log_tail(task),
    ]
    return "\n".join(lines).strip() + "\n"
