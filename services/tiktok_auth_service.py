from __future__ import annotations

from datetime import datetime
from typing import Callable

from app.paths import (
    RRV_TIKTOK_AUTH_COOKIE_PATH,
    RRV_TIKTOK_AUTH_RESULT_PATH,
    RRV_YOUTUBE_AUTH_DIR,
)
from services.auth_helper_client import run_auth_helper
from services.site_auth_common import (
    BrowserOption,
    SiteAuthStatus,
    SiteLoginResult,
    detect_chromium_browsers,
    read_cookie_status,
    save_preferred_browser_key,
)


TIKTOK_COOKIE_DOMAINS = ("tiktok.com",)
TIKTOK_LOGIN_COOKIE_NAMES = {"sid_tt"}

TikTokAuthStatus = SiteAuthStatus
TikTokLoginResult = SiteLoginResult


def tiktok_auth_status() -> TikTokAuthStatus:
    return read_cookie_status(
        RRV_TIKTOK_AUTH_COOKIE_PATH,
        login_cookie_names=TIKTOK_LOGIN_COOKIE_NAMES,
        domains=TIKTOK_COOKIE_DOMAINS,
    )


def tiktok_auth_status_text() -> str:
    status = tiktok_auth_status()
    if not status.exists:
        return "인증 정보 없음"
    if not status.has_login_cookie:
        return "⚠ 인증 정보 확인 필요"
    stamp = status.modified_at.strftime("%Y-%m-%d %H:%M") if status.modified_at else "시간 확인 불가"
    return f"✓ 인증 정보 저장됨 · 쿠키 {status.cookie_count}개 · {stamp}"


def delete_tiktok_auth() -> bool:
    try:
        if RRV_TIKTOK_AUTH_COOKIE_PATH.is_file():
            RRV_TIKTOK_AUTH_COOKIE_PATH.unlink()
    except OSError:
        return False
    return not RRV_TIKTOK_AUTH_COOKIE_PATH.exists()


def _write_safe_result(result: TikTokLoginResult) -> None:
    RRV_YOUTUBE_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    text = "\n".join(
        [
            "RR-V TikTok Login Result",
            f"time={datetime.now().isoformat(timespec='seconds')}",
            f"status={'SUCCESS' if result.success else 'FAILED'}",
            f"browser={result.browser_label}",
            f"compact_window={'YES' if result.compact_window else 'NO'}",
            f"hidden_after_login={'YES' if result.hidden_after_login else 'NO'}",
            f"tiktok_cookie_count={result.cookie_count}",
            f"cookie_file={RRV_TIKTOK_AUTH_COOKIE_PATH}",
            f"message={result.message}",
            "",
            "NOTE: This result file does not contain cookie values.",
        ]
    )
    try:
        RRV_TIKTOK_AUTH_RESULT_PATH.write_text(text, encoding="utf-8")
    except OSError:
        pass


def _missing_browser_result() -> TikTokLoginResult:
    return TikTokLoginResult(
        success=False,
        browser_key="none",
        browser_label="없음",
        cookie_count=0,
        compact_window=False,
        hidden_after_login=False,
        message="Chrome / Vivaldi / Edge / Brave를 찾지 못했습니다.",
    )


def perform_tiktok_login(
    browser_key: str,
    status_callback: Callable[[str], None] | None = None,
) -> TikTokLoginResult:
    candidates: tuple[BrowserOption, ...] = detect_chromium_browsers()
    selected = next((item for item in candidates if item.key == browser_key), None)
    if selected is None:
        selected = candidates[0] if candidates else None
    if selected is None:
        result = _missing_browser_result()
        _write_safe_result(result)
        return result

    save_preferred_browser_key(selected.key)
    helper_result = run_auth_helper(
        site="tiktok",
        browser_key=selected.key,
        browser_label=selected.label,
        browser_path=selected.path,
        cookie_path=RRV_TIKTOK_AUTH_COOKIE_PATH,
        status_callback=status_callback,
    )
    result = TikTokLoginResult(
        success=helper_result.success,
        browser_key=helper_result.browser_key,
        browser_label=helper_result.browser_label,
        cookie_count=helper_result.cookie_count,
        compact_window=helper_result.compact_window,
        hidden_after_login=helper_result.hidden_after_login,
        message=helper_result.message,
    )
    _write_safe_result(result)
    return result
