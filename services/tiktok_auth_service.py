from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.paths import (
    RRV_TIKTOK_AUTH_COOKIE_PATH,
    RRV_TIKTOK_AUTH_RESULT_PATH,
    RRV_YOUTUBE_AUTH_DIR,
    RRV_YOUTUBE_AUTH_SESSION_DIR,
)
from services.site_auth_common import (
    AUTH_WINDOW_HEIGHT,
    AUTH_WINDOW_WIDTH,
    BrowserOption,
    SiteAuthStatus,
    SiteLoginResult,
    detect_chromium_browsers,
    has_login_cookie,
    hide_browser_windows,
    keep_browser_hidden,
    load_nodriver,
    save_preferred_browser_key,
    style_auth_window,
    write_netscape_cookie_file,
    read_cookie_status,
)


TIKTOK_HOME = "https://www.tiktok.com/"
TIKTOK_LOGIN_URL = "https://www.tiktok.com/login"
TIKTOK_COOKIE_DOMAINS = ("tiktok.com",)
# yt-dlp's current TikTok extractor consumes sid_tt from the webpage cookie jar
# when authenticated API/video requests are made.
TIKTOK_LOGIN_COOKIE_NAMES = {"sid_tt"}
TIKTOK_WINDOW_TITLE = "RR-V TikTok 로그인"

TikTokAuthStatus = SiteAuthStatus
TikTokLoginResult = SiteLoginResult


def tiktok_auth_status() -> TikTokAuthStatus:
    return read_cookie_status(
        RRV_TIKTOK_AUTH_COOKIE_PATH,
        login_cookie_names=TIKTOK_LOGIN_COOKIE_NAMES,
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


async def _wait_for_login(browser, status_callback: Callable[[str], None] | None) -> None:
    started = time.monotonic()
    last_notice = -1
    while time.monotonic() - started < 600:
        if getattr(browser, "stopped", False):
            raise RuntimeError("로그인 완료 전에 인증 브라우저가 종료되었습니다.")

        try:
            cookies = await browser.cookies.get_all()
        except Exception:
            cookies = []

        if has_login_cookie(cookies, TIKTOK_COOKIE_DOMAINS, TIKTOK_LOGIN_COOKIE_NAMES):
            if status_callback:
                status_callback("로그인 확인 완료 · 인증 정보를 저장하는 중…")
            return

        elapsed = int(time.monotonic() - started)
        notice = elapsed // 10
        if notice != last_notice:
            last_notice = notice
            if status_callback:
                status_callback("브라우저에서 TikTok 로그인을 완료해 주세요.")
        await asyncio.sleep(1.5)

    raise TimeoutError("10분 안에 TikTok 로그인을 확인하지 못했습니다.")


async def _run_login(
    browser: BrowserOption,
    status_callback: Callable[[str], None] | None,
) -> TikTokLoginResult:
    if os.name != "nt":
        raise RuntimeError("현재 TikTok 로그인 UX는 Windows에서만 지원합니다.")

    uc = load_nodriver()
    RRV_YOUTUBE_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    RRV_YOUTUBE_AUTH_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(
        tempfile.mkdtemp(prefix="tiktok_session_", dir=RRV_YOUTUBE_AUTH_SESSION_DIR)
    )
    pending_cookie = RRV_TIKTOK_AUTH_COOKIE_PATH.with_suffix(".pending.txt")

    browser_instance = None
    browser_pid = 0
    cookie_count = 0
    compact_window = False
    hidden_after_login = False
    hide_stop = asyncio.Event()
    hide_task = None

    try:
        if status_callback:
            status_callback(f"{browser.label} 인증 창을 여는 중…")

        browser_instance = await uc.Browser.create(
            user_data_dir=str(profile_dir),
            headless=False,
            browser_executable_path=str(browser.path),
            browser_args=[
                f"--app={TIKTOK_LOGIN_URL}",
                f"--window-size={AUTH_WINDOW_WIDTH},{AUTH_WINDOW_HEIGHT}",
                "--disable-sync",
            ],
        )
        browser_pid = int(getattr(browser_instance, "_process_pid", 0) or 0)
        tab = await browser_instance.get(TIKTOK_LOGIN_URL)
        await asyncio.sleep(0.8)

        try:
            await tab.set_window_size(0, 0, AUTH_WINDOW_WIDTH, AUTH_WINDOW_HEIGHT)
        except Exception:
            pass

        for _ in range(8):
            if style_auth_window(browser_pid, TIKTOK_WINDOW_TITLE):
                compact_window = True
                break
            await asyncio.sleep(0.25)

        if status_callback:
            status_callback("브라우저에서 TikTok 계정에 로그인해 주세요.")

        await _wait_for_login(browser_instance, status_callback)

        hidden_now = hide_browser_windows(browser_pid)
        if hidden_now > 0:
            hidden_after_login = True
        else:
            try:
                await tab.minimize()
                hidden_after_login = True
            except Exception:
                pass

        hide_task = asyncio.create_task(keep_browser_hidden(browser_pid, hide_stop))

        if status_callback:
            status_callback("로그인 확인 완료 · TikTok 인증 정보를 정리하는 중…")

        # TikTok 홈으로 한 번 돌아가 세션 쿠키가 모두 정착한 뒤 내보낸다.
        tab = await browser_instance.get(TIKTOK_HOME)
        await asyncio.sleep(1.5)
        cookies = await browser_instance.cookies.get_all()
        cookie_count, cookie_names = write_netscape_cookie_file(
            cookies,
            pending_cookie,
            domains=TIKTOK_COOKIE_DOMAINS,
            generated_for="TikTok",
        )
        if cookie_count == 0:
            raise RuntimeError("TikTok 쿠키를 한 개도 저장하지 못했습니다.")
        if not (cookie_names & TIKTOK_LOGIN_COOKIE_NAMES):
            raise RuntimeError("쿠키는 저장됐지만 TikTok 로그인 인증 쿠키를 확인하지 못했습니다.")

        os.replace(pending_cookie, RRV_TIKTOK_AUTH_COOKIE_PATH)
        result = TikTokLoginResult(
            success=True,
            browser_key=browser.key,
            browser_label=browser.label,
            cookie_count=cookie_count,
            compact_window=compact_window,
            hidden_after_login=hidden_after_login,
            message="TikTok 로그인 및 인증 정보 저장을 완료했습니다.",
        )
        _write_safe_result(result)
        return result

    except Exception as exc:
        try:
            pending_cookie.unlink(missing_ok=True)
        except OSError:
            pass
        result = TikTokLoginResult(
            success=False,
            browser_key=browser.key,
            browser_label=browser.label,
            cookie_count=cookie_count,
            compact_window=compact_window,
            hidden_after_login=hidden_after_login,
            message=f"{type(exc).__name__}: {exc}",
        )
        _write_safe_result(result)
        return result

    finally:
        hide_stop.set()
        if hide_task is not None:
            try:
                await hide_task
            except Exception:
                pass

        if browser_instance is not None:
            try:
                browser_instance.stop()
            except Exception:
                pass
            await asyncio.sleep(1.0)

        for _ in range(6):
            try:
                shutil.rmtree(profile_dir, ignore_errors=False)
                break
            except OSError:
                await asyncio.sleep(0.6)


def perform_tiktok_login(
    browser_key: str,
    status_callback: Callable[[str], None] | None = None,
) -> TikTokLoginResult:
    candidates = detect_chromium_browsers()
    selected = next((item for item in candidates if item.key == browser_key), None)
    if selected is None:
        selected = candidates[0] if candidates else None
    if selected is None:
        result = TikTokLoginResult(
            success=False,
            browser_key="none",
            browser_label="없음",
            cookie_count=0,
            compact_window=False,
            hidden_after_login=False,
            message="Chrome / Vivaldi / Edge / Brave를 찾지 못했습니다.",
        )
        _write_safe_result(result)
        return result

    save_preferred_browser_key(selected.key)
    try:
        return asyncio.run(_run_login(selected, status_callback))
    except Exception as exc:
        result = TikTokLoginResult(
            success=False,
            browser_key=selected.key,
            browser_label=selected.label,
            cookie_count=0,
            compact_window=False,
            hidden_after_login=False,
            message=f"{type(exc).__name__}: {exc}",
        )
        _write_safe_result(result)
        return result
