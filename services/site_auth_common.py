from __future__ import annotations

import asyncio
import ctypes
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from app.paths import BUNDLED_WPC_RUNTIME_DIR, RRV_WPC_RUNTIME_DIR
from app.settings_store import get_settings


AUTH_WINDOW_WIDTH = 560
AUTH_WINDOW_HEIGHT = 760

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
class SiteAuthStatus:
    exists: bool
    has_login_cookie: bool
    cookie_count: int
    modified_at: datetime | None


@dataclass(slots=True, frozen=True)
class SiteLoginResult:
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
    settings = get_settings()
    value = str(settings.value("general/site_login_browser", "") or "").strip().lower()
    if value:
        return value
    return str(settings.value("general/youtube_login_browser", "") or "").strip().lower()


def save_preferred_browser_key(browser_key: str) -> None:
    key = str(browser_key).strip().lower()
    settings = get_settings()
    settings.setValue("general/site_login_browser", key)
    # Keep the old key synchronized for backwards compatibility with 1.1.x.
    settings.setValue("general/youtube_login_browser", key)
    settings.sync()


def load_nodriver():
    candidates = (RRV_WPC_RUNTIME_DIR, BUNDLED_WPC_RUNTIME_DIR)
    runtime = next(
        (path for path in candidates if (path / "nodriver" / "__init__.py").is_file()),
        None,
    )
    if runtime is None:
        raise RuntimeError(
            "사이트 로그인에 필요한 브라우저 런타임을 찾지 못했습니다. "
            "설정 > 도구 및 리소스에서 도구 복구를 먼저 실행해 주세요."
        )

    runtime_text = str(runtime)
    if runtime_text not in sys.path:
        sys.path.insert(0, runtime_text)
    try:
        import nodriver as uc
    except Exception as exc:
        raise RuntimeError(f"로그인 브라우저 모듈을 불러오지 못했습니다: {exc}") from exc
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


def style_auth_window(root_pid: int, title: str) -> bool:
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


def hide_browser_windows(root_pid: int) -> int:
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


async def keep_browser_hidden(root_pid: int, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        hide_browser_windows(root_pid)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=0.12)
        except asyncio.TimeoutError:
            pass


def cookie_domain_matches(cookie, domains: Iterable[str]) -> bool:
    domain = (getattr(cookie, "domain", "") or "").lower().lstrip(".")
    for allowed in domains:
        allowed = str(allowed).lower().lstrip(".")
        if domain == allowed or domain.endswith("." + allowed):
            return True
    return False


def has_login_cookie(cookies, domains: Iterable[str], names: set[str]) -> bool:
    cookie_names = {
        str(getattr(cookie, "name", "") or "")
        for cookie in cookies
        if cookie_domain_matches(cookie, domains)
    }
    return bool(cookie_names & names)


def sanitize_cookie_field(value: object) -> str:
    return str(value or "").replace("\t", " ").replace("\r", "").replace("\n", "")


def write_netscape_cookie_file(
    cookies,
    destination: Path,
    *,
    domains: Iterable[str],
    generated_for: str,
) -> tuple[int, set[str]]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    selected = [cookie for cookie in cookies if cookie_domain_matches(cookie, domains)]
    selected.sort(key=lambda c: (str(getattr(c, "domain", "")), str(getattr(c, "name", ""))))

    lines = [
        "# Netscape HTTP Cookie File",
        f"# Generated by RR-V {generated_for} account login.",
        "# This file contains private login credentials. Do not share it.",
        "",
    ]
    names: set[str] = set()

    for cookie in selected:
        domain = sanitize_cookie_field(getattr(cookie, "domain", ""))
        path = sanitize_cookie_field(getattr(cookie, "path", "/")) or "/"
        secure = "TRUE" if bool(getattr(cookie, "secure", False)) else "FALSE"
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        expires = getattr(cookie, "expires", None)
        session = bool(getattr(cookie, "session", False))
        expires_text = "0" if session or expires is None or expires <= 0 else str(int(expires))
        name = sanitize_cookie_field(getattr(cookie, "name", ""))
        value = sanitize_cookie_field(getattr(cookie, "value", ""))
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
    return len(selected), names


def read_cookie_status(
    path: Path,
    *,
    login_cookie_names: set[str],
) -> SiteAuthStatus:
    if not path.is_file():
        return SiteAuthStatus(False, False, 0, None)

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
        return SiteAuthStatus(True, False, 0, None)

    try:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        modified_at = None

    return SiteAuthStatus(
        exists=True,
        has_login_cookie=bool(names & login_cookie_names),
        cookie_count=cookie_count,
        modified_at=modified_at,
    )
