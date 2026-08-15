from __future__ import annotations

import asyncio
import ctypes
import os
import shutil
import sys
import tempfile
import time
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.paths import (
    BUNDLED_WPC_RUNTIME_DIR,
    RRV_YOUTUBE_AUTH_COOKIE_PATH,
    RRV_YOUTUBE_AUTH_DIR,
    RRV_YOUTUBE_AUTH_RESULT_PATH,
    RRV_YOUTUBE_AUTH_SESSION_DIR,
    RRV_WPC_RUNTIME_DIR,
)
from app.settings_store import get_settings


YOUTUBE_HOME = "https://www.youtube.com/"
YOUTUBE_ROBOTS = "https://www.youtube.com/robots.txt"
AUTH_COOKIE_NAMES = {
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

AUTH_WINDOW_WIDTH = 560
AUTH_WINDOW_HEIGHT = 760
AUTH_WINDOW_TITLE = "RR-V YouTube 로그인"

TH32CS_SNAPPROCESS = 0x00000002
SW_HIDE = 0
SW_RESTORE = 9
SWP_NOZORDER = 0x0004
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


@dataclass(slots=True, frozen=True)
class BrowserOption:
    key: str
    label: str
    path: Path


@dataclass(slots=True, frozen=True)
class YouTubeAuthStatus:
    exists: bool
    has_login_cookie: bool
    cookie_count: int
    modified_at: datetime | None


@dataclass(slots=True, frozen=True)
class YouTubeLoginResult:
    success: bool
    browser_key: str
    browser_label: str
    cookie_count: int
    compact_window: bool
    hidden_after_login: bool
    message: str


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


def detect_chromium_browsers() -> tuple[BrowserOption, ...]:
    env = os.environ
    pf = Path(env.get("PROGRAMFILES", r"C:\Program Files"))
    pfx86 = Path(env.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    local = Path(env.get("LOCALAPPDATA", str(Path.home())))

    raw = [
        ("chrome", "Google Chrome", pf / "Google/Chrome/Application/chrome.exe"),
        ("chrome", "Google Chrome", pfx86 / "Google/Chrome/Application/chrome.exe"),
        ("chrome", "Google Chrome", local / "Google/Chrome/Application/chrome.exe"),
        ("vivaldi", "Vivaldi", local / "Vivaldi/Application/vivaldi.exe"),
        ("vivaldi", "Vivaldi", pf / "Vivaldi/Application/vivaldi.exe"),
        ("vivaldi", "Vivaldi", pfx86 / "Vivaldi/Application/vivaldi.exe"),
        ("edge", "Microsoft Edge", pfx86 / "Microsoft/Edge/Application/msedge.exe"),
        ("edge", "Microsoft Edge", pf / "Microsoft/Edge/Application/msedge.exe"),
        ("edge", "Microsoft Edge", local / "Microsoft/Edge/Application/msedge.exe"),
        ("brave", "Brave", pf / "BraveSoftware/Brave-Browser/Application/brave.exe"),
        ("brave", "Brave", pfx86 / "BraveSoftware/Brave-Browser/Application/brave.exe"),
        ("brave", "Brave", local / "BraveSoftware/Brave-Browser/Application/brave.exe"),
    ]

    found: list[BrowserOption] = []
    seen_keys: set[str] = set()
    for key, label, path in raw:
        if key in seen_keys or not path.is_file():
            continue
        seen_keys.add(key)
        found.append(BrowserOption(key=key, label=label, path=path))
    return tuple(found)


def load_preferred_browser_key() -> str:
    return str(get_settings().value("general/youtube_login_browser", "") or "").strip().lower()


def save_preferred_browser_key(browser_key: str) -> None:
    settings = get_settings()
    settings.setValue("general/youtube_login_browser", str(browser_key).strip().lower())
    settings.sync()


def youtube_auth_status() -> YouTubeAuthStatus:
    path = RRV_YOUTUBE_AUTH_COOKIE_PATH
    if not path.is_file():
        return YouTubeAuthStatus(False, False, 0, None)

    cookie_count = 0
    names: set[str] = set()
    try:
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip("\r\n")
            if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            name = parts[5].strip()
            if not name:
                continue
            cookie_count += 1
            names.add(name)
    except OSError:
        return YouTubeAuthStatus(True, False, 0, None)

    try:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        modified_at = None

    return YouTubeAuthStatus(
        exists=True,
        has_login_cookie=bool(names & AUTH_COOKIE_NAMES),
        cookie_count=cookie_count,
        modified_at=modified_at,
    )


def youtube_auth_status_text() -> str:
    status = youtube_auth_status()
    if not status.exists:
        return "인증 정보 없음"
    if not status.has_login_cookie:
        return "⚠ 인증 정보 확인 필요"
    stamp = status.modified_at.strftime("%Y-%m-%d %H:%M") if status.modified_at else "시간 확인 불가"
    return f"✓ 인증 정보 저장됨 · 쿠키 {status.cookie_count}개 · {stamp}"


def _runtime_dir() -> Path:
    candidates = (RRV_WPC_RUNTIME_DIR, BUNDLED_WPC_RUNTIME_DIR)
    for path in candidates:
        if (path / "nodriver" / "__init__.py").is_file():
            return path
    raise RuntimeError(
        "YouTube 로그인에 필요한 WPC/nodriver 런타임을 찾지 못했습니다. "
        "설정 > 도구 및 리소스에서 도구 복구를 먼저 실행해 주세요."
    )


def _load_nodriver():
    runtime = _runtime_dir()
    runtime_text = str(runtime)
    if runtime_text not in sys.path:
        sys.path.insert(0, runtime_text)
    try:
        import nodriver as uc
    except Exception as exc:
        raise RuntimeError(f"YouTube 로그인 브라우저 모듈을 불러오지 못했습니다: {exc}") from exc
    return uc


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


def _style_auth_window(root_pid: int) -> bool:
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
        user32.SetWindowTextW(hwnd, AUTH_WINDOW_TITLE)
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


def _is_youtube_cookie(cookie) -> bool:
    domain = (getattr(cookie, "domain", "") or "").lower().lstrip(".")
    return domain == "youtube.com" or domain.endswith(".youtube.com")


def _has_login_cookie(cookies) -> bool:
    names = {
        getattr(cookie, "name", "")
        for cookie in cookies
        if _is_youtube_cookie(cookie)
    }
    return bool(names & AUTH_COOKIE_NAMES)


def _sanitize_cookie_field(value: object) -> str:
    return str(value or "").replace("\t", " ").replace("\r", "").replace("\n", "")


def _write_netscape_cookie_file(cookies, destination: Path) -> tuple[int, set[str]]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    youtube_cookies = [cookie for cookie in cookies if _is_youtube_cookie(cookie)]
    youtube_cookies.sort(
        key=lambda c: (str(getattr(c, "domain", "")), str(getattr(c, "name", "")))
    )

    lines = [
        "# Netscape HTTP Cookie File",
        "# Generated by RR-V YouTube account login.",
        "# This file contains private login credentials. Do not share it.",
        "",
    ]
    names: set[str] = set()

    for cookie in youtube_cookies:
        domain = _sanitize_cookie_field(getattr(cookie, "domain", ""))
        path = _sanitize_cookie_field(getattr(cookie, "path", "/")) or "/"
        secure = "TRUE" if bool(getattr(cookie, "secure", False)) else "FALSE"
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        expires = getattr(cookie, "expires", None)
        session = bool(getattr(cookie, "session", False))
        expires_text = "0" if session or expires is None or expires <= 0 else str(int(expires))
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
    return len(youtube_cookies), names


def _write_safe_result(result: YouTubeLoginResult) -> None:
    RRV_YOUTUBE_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    text = "\n".join(
        [
            "RR-V YouTube Login Result",
            f"time={datetime.now().isoformat(timespec='seconds')}",
            f"status={'SUCCESS' if result.success else 'FAILED'}",
            f"browser={result.browser_label}",
            f"compact_window={'YES' if result.compact_window else 'NO'}",
            f"hidden_after_login={'YES' if result.hidden_after_login else 'NO'}",
            f"youtube_cookie_count={result.cookie_count}",
            f"cookie_file={RRV_YOUTUBE_AUTH_COOKIE_PATH}",
            f"message={result.message}",
            "",
            "NOTE: This result file does not contain cookie values.",
        ]
    )
    try:
        RRV_YOUTUBE_AUTH_RESULT_PATH.write_text(text, encoding="utf-8")
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

        if _has_login_cookie(cookies):
            if status_callback:
                status_callback("로그인 확인 완료 · 인증 정보를 저장하는 중…")
            return

        elapsed = int(time.monotonic() - started)
        notice = elapsed // 10
        if notice != last_notice:
            last_notice = notice
            if status_callback:
                status_callback("브라우저에서 YouTube 로그인을 완료해 주세요.")
        await asyncio.sleep(1.5)

    raise TimeoutError("10분 안에 YouTube 로그인을 확인하지 못했습니다.")


async def _run_login(
    browser: BrowserOption,
    status_callback: Callable[[str], None] | None,
) -> YouTubeLoginResult:
    if os.name != "nt":
        raise RuntimeError("현재 YouTube 로그인 UX는 Windows에서만 지원합니다.")

    uc = _load_nodriver()
    RRV_YOUTUBE_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    RRV_YOUTUBE_AUTH_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(
        tempfile.mkdtemp(prefix="session_", dir=RRV_YOUTUBE_AUTH_SESSION_DIR)
    )
    pending_cookie = RRV_YOUTUBE_AUTH_COOKIE_PATH.with_suffix(".pending.txt")

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
                f"--app={YOUTUBE_HOME}",
                f"--window-size={AUTH_WINDOW_WIDTH},{AUTH_WINDOW_HEIGHT}",
                "--disable-sync",
            ],
        )
        browser_pid = int(getattr(browser_instance, "_process_pid", 0) or 0)
        tab = await browser_instance.get(YOUTUBE_HOME)
        await asyncio.sleep(0.8)

        try:
            screen_w = ctypes.windll.user32.GetSystemMetrics(0)
            screen_h = ctypes.windll.user32.GetSystemMetrics(1)
            left = max(0, (int(screen_w) - AUTH_WINDOW_WIDTH) // 2)
            top = max(0, (int(screen_h) - AUTH_WINDOW_HEIGHT) // 2)
            await tab.set_window_size(left, top, AUTH_WINDOW_WIDTH, AUTH_WINDOW_HEIGHT)
        except Exception:
            pass

        for _ in range(8):
            if _style_auth_window(browser_pid):
                compact_window = True
                break
            await asyncio.sleep(0.25)

        if status_callback:
            status_callback("브라우저에서 YouTube의 [로그인]을 눌러 계정에 로그인해 주세요.")

        await _wait_for_login(browser_instance, status_callback)

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

        if status_callback:
            status_callback("로그인 확인 완료 · 인증 정보를 정리하는 중…")
        await browser_instance.get(YOUTUBE_ROBOTS)
        await asyncio.sleep(2.5)

        cookies = await browser_instance.cookies.get_all()
        cookie_count, cookie_names = _write_netscape_cookie_file(cookies, pending_cookie)
        if cookie_count == 0:
            raise RuntimeError("YouTube 쿠키를 한 개도 저장하지 못했습니다.")
        if not (cookie_names & AUTH_COOKIE_NAMES):
            raise RuntimeError("쿠키는 저장됐지만 YouTube 로그인 인증 쿠키를 확인하지 못했습니다.")

        os.replace(pending_cookie, RRV_YOUTUBE_AUTH_COOKIE_PATH)
        result = YouTubeLoginResult(
            success=True,
            browser_key=browser.key,
            browser_label=browser.label,
            cookie_count=cookie_count,
            compact_window=compact_window,
            hidden_after_login=hidden_after_login,
            message="YouTube 로그인 및 인증 정보 저장을 완료했습니다.",
        )
        _write_safe_result(result)
        return result

    except Exception as exc:
        try:
            pending_cookie.unlink(missing_ok=True)
        except OSError:
            pass
        result = YouTubeLoginResult(
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


def perform_youtube_login(
    browser_key: str,
    status_callback: Callable[[str], None] | None = None,
) -> YouTubeLoginResult:
    candidates = detect_chromium_browsers()
    selected = next((item for item in candidates if item.key == browser_key), None)
    if selected is None:
        selected = candidates[0] if candidates else None
    if selected is None:
        result = YouTubeLoginResult(
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
        result = YouTubeLoginResult(
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
