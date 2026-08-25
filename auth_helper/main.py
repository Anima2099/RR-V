from __future__ import annotations

import argparse
import asyncio
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time


AUTH_WINDOW_WIDTH = 560
AUTH_WINDOW_HEIGHT = 760
TH32CS_SNAPPROCESS = 0x00000002
SW_HIDE = 0
SW_RESTORE = 9
SWP_NOZORDER = 0x0004
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


@dataclass(slots=True, frozen=True)
class SiteConfig:
    key: str
    login_url: str
    settle_url: str
    cookie_domains: tuple[str, ...]
    login_cookie_names: frozenset[str]
    window_title: str
    profile_prefix: str
    login_prompt: str
    settle_prompt: str
    success_message: str
    settle_delay: float
    capture_user_agent: bool = False


SITE_CONFIGS = {
    "youtube": SiteConfig(
        key="youtube",
        login_url="https://www.youtube.com/",
        settle_url="https://www.youtube.com/robots.txt",
        cookie_domains=("youtube.com",),
        login_cookie_names=frozenset(
            {
                "SID",
                "SAPISID",
                "APISID",
                "SSID",
                "HSID",
                "LOGIN_INFO",
                "__Secure-1PSID",
                "__Secure-3PSID",
                "__Secure-1PAPISID",
                "__Secure-3PAPISID",
            }
        ),
        window_title="RR-V YouTube 로그인",
        profile_prefix="session_",
        login_prompt="브라우저에서 YouTube의 [로그인]을 눌러 계정에 로그인해 주세요.",
        settle_prompt="로그인 확인 완료 · 인증 정보를 정리하는 중…",
        success_message="YouTube 로그인 및 인증 정보 저장을 완료했습니다.",
        settle_delay=2.5,
    ),
    "instagram": SiteConfig(
        key="instagram",
        login_url="https://www.instagram.com/accounts/login/",
        settle_url="https://www.instagram.com/",
        cookie_domains=("instagram.com",),
        login_cookie_names=frozenset({"sessionid"}),
        window_title="RR-V Instagram 로그인",
        profile_prefix="instagram_session_",
        login_prompt="브라우저에서 Instagram 계정에 로그인해 주세요.",
        settle_prompt="로그인 확인 완료 · Instagram 인증 정보를 정리하는 중…",
        success_message="Instagram 로그인 및 인증 정보 저장을 완료했습니다.",
        settle_delay=1.5,
        capture_user_agent=True,
    ),
    "tiktok": SiteConfig(
        key="tiktok",
        login_url="https://www.tiktok.com/login",
        settle_url="https://www.tiktok.com/",
        cookie_domains=("tiktok.com",),
        login_cookie_names=frozenset({"sid_tt"}),
        window_title="RR-V TikTok 로그인",
        profile_prefix="tiktok_session_",
        login_prompt="브라우저에서 TikTok 계정에 로그인해 주세요.",
        settle_prompt="로그인 확인 완료 · TikTok 인증 정보를 정리하는 중…",
        success_message="TikTok 로그인 및 인증 정보 저장을 완료했습니다.",
        settle_delay=1.5,
    ),
}


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


def _emit(payload: dict[str, object]) -> None:
    # Keep stdout ASCII-only so the frozen helper is independent of the
    # Windows console/code-page choice. json.loads() in RR-V restores the
    # escaped Korean text after the process boundary.
    print(json.dumps(payload, ensure_ascii=True), flush=True)


def _emit_status(message: str) -> None:
    _emit({"type": "status", "message": message})


def _emit_result(
    *,
    success: bool,
    browser_key: str,
    browser_label: str,
    cookie_count: int,
    compact_window: bool,
    hidden_after_login: bool,
    message: str,
    user_agent: str = "",
) -> None:
    _emit(
        {
            "type": "result",
            "success": success,
            "browser_key": browser_key,
            "browser_label": browser_label,
            "cookie_count": cookie_count,
            "compact_window": compact_window,
            "hidden_after_login": hidden_after_login,
            "message": message,
            "user_agent": user_agent,
        }
    )


def _domain_matches(domain: str, accepted: tuple[str, ...]) -> bool:
    clean = (domain or "").lower().lstrip(".")
    return any(clean == item or clean.endswith("." + item) for item in accepted)


def _has_login_cookie(cookies, config: SiteConfig) -> bool:
    names = {
        str(getattr(cookie, "name", "") or "")
        for cookie in cookies
        if _domain_matches(str(getattr(cookie, "domain", "") or ""), config.cookie_domains)
    }
    return bool(names & config.login_cookie_names)


def _sanitize_cookie_field(value: object) -> str:
    return str(value or "").replace("\t", " ").replace("\r", "").replace("\n", "")


def _write_netscape_cookie_file(
    cookies,
    destination: Path,
    config: SiteConfig,
) -> tuple[int, set[str]]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    filtered = [
        cookie
        for cookie in cookies
        if _domain_matches(str(getattr(cookie, "domain", "") or ""), config.cookie_domains)
    ]
    filtered.sort(
        key=lambda cookie: (
            str(getattr(cookie, "domain", "") or ""),
            str(getattr(cookie, "name", "") or ""),
        )
    )

    lines = [
        "# Netscape HTTP Cookie File",
        f"# Generated by RR-V {config.key} account login helper.",
        "# This file contains private login credentials. Do not share it.",
        "",
    ]
    names: set[str] = set()

    for cookie in filtered:
        domain = _sanitize_cookie_field(getattr(cookie, "domain", ""))
        path = _sanitize_cookie_field(getattr(cookie, "path", "/")) or "/"
        secure = "TRUE" if bool(getattr(cookie, "secure", False)) else "FALSE"
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        expires = getattr(cookie, "expires", None)
        session = bool(getattr(cookie, "session", False))
        try:
            expires_value = float(expires) if expires is not None else 0.0
        except (TypeError, ValueError):
            expires_value = 0.0
        expires_text = "0" if session or expires_value <= 0 else str(int(expires_value))
        name = _sanitize_cookie_field(getattr(cookie, "name", ""))
        value = _sanitize_cookie_field(getattr(cookie, "value", ""))
        if not domain or not name:
            continue

        output_domain = domain
        if bool(getattr(cookie, "http_only", False)):
            output_domain = "#HttpOnly_" + output_domain

        lines.append(
            "\t".join(
                [
                    output_domain,
                    include_subdomains,
                    path,
                    secure,
                    expires_text,
                    name,
                    value,
                ]
            )
        )
        names.add(name)

    destination.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    return len(filtered), names


def _process_family(root_pid: int) -> set[int]:
    if os.name != "nt" or not root_pid:
        return {root_pid} if root_pid else set()

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        return {root_pid}

    pairs: list[tuple[int, int]] = []
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)

    try:
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            pairs.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID)))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)

    family = {int(root_pid)}
    changed = True
    while changed:
        changed = False
        for pid, ppid in pairs:
            if ppid in family and pid not in family:
                family.add(pid)
                changed = True
    return family


def _browser_windows(root_pid: int, *, visible_only: bool = True) -> list[int]:
    if os.name != "nt" or not root_pid:
        return []

    user32 = ctypes.windll.user32
    family = _process_family(root_pid)
    windows: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def enum_proc(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) not in family:
            return True
        if visible_only and not user32.IsWindowVisible(hwnd):
            return True
        windows.append(int(hwnd))
        return True

    user32.EnumWindows(enum_proc, 0)
    return windows


def _largest_window(handles: list[int]) -> int | None:
    if os.name != "nt" or not handles:
        return None
    user32 = ctypes.windll.user32
    best = None
    best_area = -1
    for hwnd in handles:
        rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            continue
        area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
        if area > best_area:
            best = hwnd
            best_area = area
    return best


def _style_auth_window(root_pid: int, title: str) -> bool:
    if os.name != "nt" or not root_pid:
        return False

    user32 = ctypes.windll.user32
    hwnd = _largest_window(_browser_windows(root_pid, visible_only=True))
    if not hwnd:
        return False

    try:
        screen_w = int(user32.GetSystemMetrics(0))
        screen_h = int(user32.GetSystemMetrics(1))
        left = max(0, (screen_w - AUTH_WINDOW_WIDTH) // 2)
        top = max(0, (screen_h - AUTH_WINDOW_HEIGHT) // 2)
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetWindowTextW(hwnd, title)
        user32.SetWindowPos(
            hwnd,
            None,
            left,
            top,
            AUTH_WINDOW_WIDTH,
            AUTH_WINDOW_HEIGHT,
            SWP_NOZORDER,
        )
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def _hide_browser_windows(root_pid: int) -> int:
    if os.name != "nt" or not root_pid:
        return 0

    hidden = 0
    user32 = ctypes.windll.user32
    for hwnd in _browser_windows(root_pid, visible_only=True):
        try:
            user32.ShowWindow(hwnd, SW_HIDE)
            hidden += 1
        except Exception:
            pass
    return hidden


async def _keep_browser_hidden(root_pid: int, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        _hide_browser_windows(root_pid)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=0.12)
        except asyncio.TimeoutError:
            pass


def _load_nodriver(runtime_dir: Path):
    runtime_dir = runtime_dir.resolve()
    if not (runtime_dir / "nodriver" / "__init__.py").is_file():
        raise RuntimeError("nodriver 런타임을 찾지 못했습니다.")
    runtime_text = str(runtime_dir)
    if runtime_text not in sys.path:
        sys.path.insert(0, runtime_text)
    import nodriver as uc

    return uc


async def _wait_for_login(browser, config: SiteConfig) -> None:
    started = time.monotonic()
    last_notice = -1
    consecutive_cookie_errors = 0

    while time.monotonic() - started < 600:
        try:
            cookies = await browser.cookies.get_all()
            consecutive_cookie_errors = 0
        except Exception:
            cookies = []
            consecutive_cookie_errors += 1

        if _has_login_cookie(cookies, config):
            _emit_status("로그인 확인 완료 · 인증 정보를 저장하는 중…")
            return

        # nodriver's Browser.stopped reflects the process object it launched,
        # not necessarily the visible Chromium window. Microsoft Edge may let
        # that launcher process finish while the actual auth window and CDP
        # connection remain alive. Treat the browser as gone only after the
        # real cookie channel has failed repeatedly.
        if consecutive_cookie_errors >= 6:
            raise RuntimeError("인증 브라우저 연결이 끊어졌습니다. 로그인 창을 다시 열어 주세요.")

        elapsed = int(time.monotonic() - started)
        notice = elapsed // 10
        if notice != last_notice:
            last_notice = notice
            _emit_status(config.login_prompt)
        await asyncio.sleep(1.5)

    raise TimeoutError(f"10분 안에 {config.key} 로그인을 확인하지 못했습니다.")


async def _run_login(args: argparse.Namespace, config: SiteConfig) -> None:
    if os.name != "nt":
        raise RuntimeError("현재 RR-V 사이트 로그인은 Windows에서만 지원합니다.")

    runtime_dir = Path(args.runtime_dir)
    cookie_path = Path(args.cookie_path)
    session_root = Path(args.session_root)
    browser_path = Path(args.browser_path)

    if not browser_path.is_file():
        raise RuntimeError(f"브라우저 실행 파일을 찾지 못했습니다: {browser_path}")

    uc = _load_nodriver(runtime_dir)
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    session_root.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(tempfile.mkdtemp(prefix=config.profile_prefix, dir=session_root))
    pending_cookie = cookie_path.with_suffix(".pending.txt")

    browser_instance = None
    browser_pid = 0
    cookie_count = 0
    compact_window = False
    hidden_after_login = False
    user_agent = ""
    hide_stop = asyncio.Event()
    hide_task = None

    try:
        _emit_status(f"{args.browser_label} 인증 창을 여는 중…")

        browser_instance = await uc.Browser.create(
            user_data_dir=str(profile_dir),
            headless=False,
            browser_executable_path=str(browser_path),
            browser_args=[
                f"--app={config.login_url}",
                f"--window-size={AUTH_WINDOW_WIDTH},{AUTH_WINDOW_HEIGHT}",
                "--disable-sync",
            ],
        )
        browser_pid = int(getattr(browser_instance, "_process_pid", 0) or 0)
        tab = await browser_instance.get(config.login_url)
        await asyncio.sleep(0.8)

        try:
            screen_w = int(ctypes.windll.user32.GetSystemMetrics(0))
            screen_h = int(ctypes.windll.user32.GetSystemMetrics(1))
            left = max(0, (screen_w - AUTH_WINDOW_WIDTH) // 2)
            top = max(0, (screen_h - AUTH_WINDOW_HEIGHT) // 2)
            await tab.set_window_size(left, top, AUTH_WINDOW_WIDTH, AUTH_WINDOW_HEIGHT)
        except Exception:
            pass

        for _ in range(8):
            if _style_auth_window(browser_pid, config.window_title):
                compact_window = True
                break
            await asyncio.sleep(0.25)

        _emit_status(config.login_prompt)
        await _wait_for_login(browser_instance, config)

        hidden_now = _hide_browser_windows(browser_pid)
        if hidden_now > 0:
            hidden_after_login = True
        else:
            try:
                await tab.minimize()
                hidden_after_login = True
            except Exception:
                pass

        hide_task = asyncio.create_task(_keep_browser_hidden(browser_pid, hide_stop))
        _emit_status(config.settle_prompt)

        tab = await browser_instance.get(config.settle_url)
        await asyncio.sleep(config.settle_delay)
        cookies = await browser_instance.cookies.get_all()
        cookie_count, cookie_names = _write_netscape_cookie_file(
            cookies,
            pending_cookie,
            config,
        )
        if cookie_count == 0:
            raise RuntimeError(f"{config.key} 쿠키를 한 개도 저장하지 못했습니다.")
        if not (cookie_names & config.login_cookie_names):
            raise RuntimeError("쿠키는 저장됐지만 로그인 인증 쿠키를 확인하지 못했습니다.")

        if config.capture_user_agent:
            try:
                user_agent = str(
                    await tab.evaluate("navigator.userAgent", return_by_value=True) or ""
                ).strip()
            except Exception:
                user_agent = ""

        os.replace(pending_cookie, cookie_path)
        _emit_result(
            success=True,
            browser_key=args.browser_key,
            browser_label=args.browser_label,
            cookie_count=cookie_count,
            compact_window=compact_window,
            hidden_after_login=hidden_after_login,
            message=config.success_message,
            user_agent=user_agent,
        )
    except Exception as exc:
        try:
            pending_cookie.unlink(missing_ok=True)
        except OSError:
            pass
        _emit_result(
            success=False,
            browser_key=args.browser_key,
            browser_label=args.browser_label,
            cookie_count=cookie_count,
            compact_window=compact_window,
            hidden_after_login=hidden_after_login,
            message=f"{type(exc).__name__}: {exc}",
            user_agent=user_agent,
        )
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RR-V isolated authentication helper")
    parser.add_argument("--site", choices=tuple(SITE_CONFIGS), required=True)
    parser.add_argument("--browser-key", required=True)
    parser.add_argument("--browser-label", required=True)
    parser.add_argument("--browser-path", required=True)
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--cookie-path", required=True)
    parser.add_argument("--session-root", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = SITE_CONFIGS[args.site]
    try:
        asyncio.run(_run_login(args, config))
        return 0
    except Exception as exc:
        _emit_result(
            success=False,
            browser_key=args.browser_key,
            browser_label=args.browser_label,
            cookie_count=0,
            compact_window=False,
            hidden_after_login=False,
            message=f"{type(exc).__name__}: {exc}",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())