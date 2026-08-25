from __future__ import annotations

from datetime import datetime
from typing import Callable

from app.paths import (
    RRV_INSTAGRAM_AUTH_COOKIE_PATH,
    RRV_INSTAGRAM_AUTH_RESULT_PATH,
    RRV_YOUTUBE_AUTH_DIR,
)
from app.settings_store import get_settings
from services.auth_helper_client import run_auth_helper
from services.site_auth_common import (
    BrowserOption,
    SiteAuthStatus,
    SiteLoginResult,
    detect_chromium_browsers,
    read_cookie_status,
    save_preferred_browser_key,
)


INSTAGRAM_COOKIE_DOMAINS = ("instagram.com",)
INSTAGRAM_LOGIN_COOKIE_NAMES = {"sessionid"}

InstagramAuthStatus = SiteAuthStatus
InstagramLoginResult = SiteLoginResult


def instagram_auth_status() -> InstagramAuthStatus:
    return read_cookie_status(
        RRV_INSTAGRAM_AUTH_COOKIE_PATH,
        login_cookie_names=INSTAGRAM_LOGIN_COOKIE_NAMES,
        domains=INSTAGRAM_COOKIE_DOMAINS,
    )


def instagram_auth_status_text() -> str:
    status = instagram_auth_status()
    if not status.exists:
        return "인증 정보 없음"
    if not status.has_login_cookie:
        return "⚠ 인증 정보 확인 필요"
    stamp = status.modified_at.strftime("%Y-%m-%d %H:%M") if status.modified_at else "시간 확인 불가"
    return f"✓ 인증 정보 저장됨 · 쿠키 {status.cookie_count}개 · {stamp}"


def load_instagram_user_agent() -> str:
    settings = get_settings()
    return str(settings.value("auth/instagram_user_agent", "") or "").strip()


def _save_instagram_user_agent(user_agent: str) -> None:
    settings = get_settings()
    settings.setValue("auth/instagram_user_agent", str(user_agent or "").strip())
    settings.sync()


def delete_instagram_auth() -> bool:
    removed = False
    try:
        if RRV_INSTAGRAM_AUTH_COOKIE_PATH.is_file():
            RRV_INSTAGRAM_AUTH_COOKIE_PATH.unlink()
            removed = True
    except OSError:
        return False

    settings = get_settings()
    if settings.contains("auth/instagram_user_agent"):
        settings.remove("auth/instagram_user_agent")
        settings.sync()
        removed = True
    return removed or not RRV_INSTAGRAM_AUTH_COOKIE_PATH.exists()


def _write_safe_result(result: InstagramLoginResult) -> None:
    RRV_YOUTUBE_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    text = "\n".join(
        [
            "RR-V Instagram Login Result",
            f"time={datetime.now().isoformat(timespec='seconds')}",
            f"status={'SUCCESS' if result.success else 'FAILED'}",
            f"browser={result.browser_label}",
            f"compact_window={'YES' if result.compact_window else 'NO'}",
            f"hidden_after_login={'YES' if result.hidden_after_login else 'NO'}",
            f"instagram_cookie_count={result.cookie_count}",
            f"cookie_file={RRV_INSTAGRAM_AUTH_COOKIE_PATH}",
            f"message={result.message}",
            "",
            "NOTE: This result file does not contain cookie values.",
        ]
    )
    try:
        RRV_INSTAGRAM_AUTH_RESULT_PATH.write_text(text, encoding="utf-8")
    except OSError:
        pass


def _missing_browser_result() -> InstagramLoginResult:
    return InstagramLoginResult(
        success=False,
        browser_key="none",
        browser_label="없음",
        cookie_count=0,
        compact_window=False,
        hidden_after_login=False,
        message="Chrome / Vivaldi / Edge / Brave를 찾지 못했습니다.",
    )


def perform_instagram_login(
    browser_key: str,
    status_callback: Callable[[str], None] | None = None,
) -> InstagramLoginResult:
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
        site="instagram",
        browser_key=selected.key,
        browser_label=selected.label,
        browser_path=selected.path,
        cookie_path=RRV_INSTAGRAM_AUTH_COOKIE_PATH,
        status_callback=status_callback,
    )
    if helper_result.success:
        _save_instagram_user_agent(helper_result.user_agent)

    result = InstagramLoginResult(
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
