from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path

from app.settings_store import get_settings


AUTH_WINDOW_WIDTH = 560
AUTH_WINDOW_HEIGHT = 760
SUPPORTED_LOGIN_BROWSER_KEYS = frozenset({"chrome", "edge"})


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


def detect_chromium_browsers() -> tuple[BrowserOption, ...]:
    env = os.environ
    pf = Path(env.get("PROGRAMFILES", r"C:\Program Files"))
    pfx86 = Path(env.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    local = Path(env.get("LOCALAPPDATA", str(Path.home())))

    # Site authentication is intentionally limited to the two browsers that
    # RR-V actively supports and regression-tests.
    raw = [
        ("chrome", "Google Chrome", pf / "Google/Chrome/Application/chrome.exe"),
        ("chrome", "Google Chrome", pfx86 / "Google/Chrome/Application/chrome.exe"),
        ("chrome", "Google Chrome", local / "Google/Chrome/Application/chrome.exe"),
        ("edge", "Microsoft Edge", pfx86 / "Microsoft/Edge/Application/msedge.exe"),
        ("edge", "Microsoft Edge", pf / "Microsoft/Edge/Application/msedge.exe"),
        ("edge", "Microsoft Edge", local / "Microsoft/Edge/Application/msedge.exe"),
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
    if value in SUPPORTED_LOGIN_BROWSER_KEYS:
        return value

    legacy = str(settings.value("general/youtube_login_browser", "") or "").strip().lower()
    return legacy if legacy in SUPPORTED_LOGIN_BROWSER_KEYS else ""


def save_preferred_browser_key(browser_key: str) -> None:
    requested = str(browser_key).strip().lower()
    key = requested if requested in SUPPORTED_LOGIN_BROWSER_KEYS else ""
    settings = get_settings()
    settings.setValue("general/site_login_browser", key)
    settings.setValue("general/youtube_login_browser", key)
    settings.sync()


def _domain_matches(domain: str, accepted: tuple[str, ...]) -> bool:
    clean = (domain or "").lower().lstrip(".")
    return any(clean == item or clean.endswith("." + item) for item in accepted)


def read_cookie_status(
    path: Path,
    *,
    login_cookie_names: set[str],
    domains: tuple[str, ...] = (),
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
            domain = parts[0].removeprefix("#HttpOnly_").strip().lower()
            if domains and not _domain_matches(domain, domains):
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
