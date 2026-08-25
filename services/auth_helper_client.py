from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from typing import Callable

from app.paths import (
    BUNDLED_WPC_RUNTIME_DIR,
    PROJECT_ROOT,
    RRV_WPC_RUNTIME_DIR,
    RRV_YOUTUBE_AUTH_SESSION_DIR,
)


@dataclass(slots=True, frozen=True)
class AuthHelperResult:
    success: bool
    browser_key: str
    browser_label: str
    cookie_count: int
    compact_window: bool
    hidden_after_login: bool
    message: str
    user_agent: str = ""


def _runtime_dir() -> Path | None:
    for candidate in (RRV_WPC_RUNTIME_DIR, BUNDLED_WPC_RUNTIME_DIR):
        if (candidate / "nodriver" / "__init__.py").is_file():
            return candidate
    return None


def _helper_command() -> list[str] | None:
    if getattr(sys, "frozen", False):
        helper_exe = Path(sys.executable).resolve().parent / "RR-V-Auth-Helper.exe"
        return [str(helper_exe)] if helper_exe.is_file() else None

    helper_script = PROJECT_ROOT / "auth_helper" / "main.py"
    if not helper_script.is_file():
        return None
    return [sys.executable, str(helper_script)]


def run_auth_helper(
    *,
    site: str,
    browser_key: str,
    browser_label: str,
    browser_path: Path,
    cookie_path: Path,
    status_callback: Callable[[str], None] | None = None,
) -> AuthHelperResult:
    runtime_dir = _runtime_dir()
    if runtime_dir is None:
        return AuthHelperResult(
            success=False,
            browser_key=browser_key,
            browser_label=browser_label,
            cookie_count=0,
            compact_window=False,
            hidden_after_login=False,
            message=(
                "사이트 로그인에 필요한 nodriver 런타임을 찾지 못했습니다. "
                "설정 > 도구 및 리소스에서 인증 런타임을 준비해 주세요."
            ),
        )

    command = _helper_command()
    if command is None:
        return AuthHelperResult(
            success=False,
            browser_key=browser_key,
            browser_label=browser_label,
            cookie_count=0,
            compact_window=False,
            hidden_after_login=False,
            message=(
                "RR-V 인증 Helper를 찾지 못했습니다. "
                "개발 소스라면 auth_helper/main.py를 확인하고, 배포본이라면 "
                "RR-V-Auth-Helper.exe가 RR-V.exe 옆에 있는지 확인해 주세요."
            ),
        )

    RRV_YOUTUBE_AUTH_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    command.extend(
        [
            "--site",
            site,
            "--browser-key",
            browser_key,
            "--browser-label",
            browser_label,
            "--browser-path",
            str(browser_path),
            "--runtime-dir",
            str(runtime_dir),
            "--cookie-path",
            str(cookie_path),
            "--session-root",
            str(RRV_YOUTUBE_AUTH_SESSION_DIR),
        ]
    )

    creation_flags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if sys.platform == "win32"
        else 0
    )

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creation_flags,
        )
    except OSError as error:
        return AuthHelperResult(
            success=False,
            browser_key=browser_key,
            browser_label=browser_label,
            cookie_count=0,
            compact_window=False,
            hidden_after_login=False,
            message=f"인증 Helper를 실행하지 못했습니다: {error}",
        )

    final_result: AuthHelperResult | None = None
    diagnostic_lines: list[str] = []

    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            diagnostic_lines.append(line)
            if len(diagnostic_lines) > 20:
                diagnostic_lines.pop(0)
            continue

        if not isinstance(payload, dict):
            continue
        payload_type = str(payload.get("type") or "")
        if payload_type == "status":
            message = str(payload.get("message") or "").strip()
            if message and status_callback is not None:
                status_callback(message)
            continue
        if payload_type != "result":
            continue

        final_result = AuthHelperResult(
            success=bool(payload.get("success")),
            browser_key=str(payload.get("browser_key") or browser_key),
            browser_label=str(payload.get("browser_label") or browser_label),
            cookie_count=int(payload.get("cookie_count") or 0),
            compact_window=bool(payload.get("compact_window")),
            hidden_after_login=bool(payload.get("hidden_after_login")),
            message=str(payload.get("message") or "인증 Helper 결과를 확인하지 못했습니다."),
            user_agent=str(payload.get("user_agent") or "").strip(),
        )

    return_code = process.wait()
    if final_result is not None:
        return final_result

    detail = "\n".join(diagnostic_lines[-8:]).strip()
    if detail:
        detail = f"\n{detail}"
    return AuthHelperResult(
        success=False,
        browser_key=browser_key,
        browser_label=browser_label,
        cookie_count=0,
        compact_window=False,
        hidden_after_login=False,
        message=f"인증 Helper가 결과 없이 종료되었습니다. 종료 코드: {return_code}{detail}",
    )
