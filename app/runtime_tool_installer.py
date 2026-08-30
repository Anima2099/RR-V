from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Callable
from urllib.error import HTTPError, URLError
import zipfile

from app.constants import APP_VERSION
from app.http_client import download_https_file, fetch_https_bytes
from app.paths import (
    RRV_TOOLS_DIR,
    WPC_PROVIDER_VERSION,
    find_executable,
    restore_bundled_wpc_provider,
)
from app.tool_manager import inspect_tools, update_deno, update_ffmpeg_release, update_ytdlp
from app.tool_sources import DENO_LATEST_API, YTDLP_LATEST_API


ProgressCallback = Callable[[str], None]


@dataclass(slots=True, frozen=True)
class ReleaseAsset:
    name: str
    url: str
    sha256: str
    tag: str


def _creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _looks_like_certificate_error(message: str) -> bool:
    normalized = str(message or "").upper()
    return (
        "CERTIFICATE_VERIFY_FAILED" in normalized
        or "CERTIFICATE VERIFY FAILED" in normalized
        or "UNABLE TO GET LOCAL ISSUER CERTIFICATE" in normalized
    )


def _fetch_release_asset(api_url: str, asset_name: str) -> ReleaseAsset:
    payload = json.loads(
        fetch_https_bytes(
            api_url,
            headers={
                "User-Agent": f"RR-V/{APP_VERSION}",
                "Accept": "application/vnd.github+json",
                "Cache-Control": "no-cache",
            },
            timeout=15,
            max_bytes=2 * 1024 * 1024,
        ).decode("utf-8")
    )

    if not isinstance(payload, dict):
        raise ValueError("릴리스 응답 형식을 확인하지 못했습니다.")

    tag = str(payload.get("tag_name") or "").strip()
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("릴리스 파일 목록을 확인하지 못했습니다.")

    for raw_asset in assets:
        if not isinstance(raw_asset, dict):
            continue
        if str(raw_asset.get("name") or "") != asset_name:
            continue

        url = str(raw_asset.get("browser_download_url") or "").strip()
        digest = str(raw_asset.get("digest") or "").strip().lower()
        sha256 = digest.removeprefix("sha256:") if digest.startswith("sha256:") else ""
        if not url:
            break
        return ReleaseAsset(
            name=asset_name,
            url=url,
            sha256=sha256,
            tag=tag,
        )

    raise ValueError(f"최신 릴리스에서 {asset_name} 파일을 찾지 못했습니다.")


def _sha256_for(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _download_progress_text(label: str, downloaded: int, total: int) -> str:
    downloaded_mb = downloaded / (1024 * 1024)
    if total <= 0:
        return f"↓ {label} 다운로드 중 · {downloaded_mb:.1f} MB 받음"

    total_mb = total / (1024 * 1024)
    percent = max(0, min(100, int(downloaded * 100 / total)))
    slots = 16
    filled = min(slots, int(percent * slots / 100))
    bar = "█" * filled + "░" * (slots - filled)
    return (
        f"↓ {label} 다운로드 중 · {downloaded_mb:.1f} / {total_mb:.1f} MB · {percent}%\n"
        f"{bar}"
    )


def _download_asset(
    asset: ReleaseAsset,
    destination: Path,
    *,
    label: str,
    progress: ProgressCallback | None,
) -> None:
    last_percent = -1
    last_downloaded_mb = -1

    def report(downloaded: int, total: int) -> None:
        nonlocal last_percent, last_downloaded_mb
        if progress is None:
            return
        if total > 0:
            percent = max(0, min(100, int(downloaded * 100 / total)))
            if percent == last_percent:
                return
            last_percent = percent
        else:
            downloaded_mb = int(downloaded / (1024 * 1024))
            if downloaded > 0 and downloaded_mb == last_downloaded_mb:
                return
            last_downloaded_mb = downloaded_mb
        progress(_download_progress_text(label, downloaded, total))

    download_https_file(
        asset.url,
        destination,
        headers={
            "User-Agent": f"RR-V/{APP_VERSION}",
            "Accept": "application/octet-stream, application/zip;q=0.9, */*;q=0.1",
            "Cache-Control": "no-cache",
        },
        timeout=60,
        progress=report,
    )

    if asset.sha256:
        if progress is not None:
            progress(f"✓ {label} 다운로드 완료 · SHA-256 확인 중…")
        actual = _sha256_for(destination)
        if actual.lower() != asset.sha256.lower():
            raise ValueError(f"{label} 다운로드 파일의 SHA-256이 일치하지 않습니다.")
    elif progress is not None:
        progress(f"✓ {label} 다운로드 완료 · 실행 파일 확인 중…")


def _executable_version(path: Path, args: tuple[str, ...]) -> str:
    result = subprocess.run(
        [str(path), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        creationflags=_creation_flags(),
    )
    output = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0 or not output:
        raise RuntimeError(f"{path.name} 실행 검증에 실패했습니다.")
    return output.splitlines()[0].strip()[:100]


def ensure_ytdlp(progress: ProgressCallback | None = None) -> tuple[bool, str]:
    current = find_executable("yt-dlp.exe")
    if current is not None:
        ok, message = update_ytdlp(progress)
        if ok or not _looks_like_certificate_error(message):
            return ok, message
        if progress is not None:
            progress("yt-dlp 자체 업데이트의 인증서 확인이 실패해 Windows HTTPS 경로로 다시 준비합니다…")

    try:
        if progress is not None:
            progress("yt-dlp Nightly 최신 릴리스 확인 중…")
        asset = _fetch_release_asset(YTDLP_LATEST_API, "yt-dlp.exe")
        RRV_TOOLS_DIR.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(
            prefix="rrv-ytdlp-install-",
            dir=str(RRV_TOOLS_DIR.parent),
        ) as temporary_dir:
            staged = Path(temporary_dir) / "yt-dlp.exe"
            _download_asset(
                asset,
                staged,
                label="yt-dlp Nightly",
                progress=progress,
            )
            version = _executable_version(staged, ("--version",))
            os.replace(staged, RRV_TOOLS_DIR / "yt-dlp.exe")

        return True, f"yt-dlp {version} 설치 완료"
    except (OSError, HTTPError, URLError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        return False, f"yt-dlp 설치에 실패했습니다: {error}"


def _deno_windows_asset_name() -> str:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "deno-aarch64-pc-windows-msvc.zip"
    return "deno-x86_64-pc-windows-msvc.zip"


def ensure_deno(progress: ProgressCallback | None = None) -> tuple[bool, str]:
    current = find_executable("deno.exe")
    if current is not None:
        ok, message = update_deno(progress)
        if ok or not _looks_like_certificate_error(message):
            return ok, message
        if progress is not None:
            progress("Deno 자체 업데이트의 인증서 확인이 실패해 Windows HTTPS 경로로 다시 준비합니다…")

    try:
        if progress is not None:
            progress("Deno 최신 릴리스 확인 중…")
        asset = _fetch_release_asset(DENO_LATEST_API, _deno_windows_asset_name())
        RRV_TOOLS_DIR.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(
            prefix="rrv-deno-install-",
            dir=str(RRV_TOOLS_DIR.parent),
        ) as temporary_dir:
            temporary_root = Path(temporary_dir)
            archive_path = temporary_root / "deno.zip"
            staged = temporary_root / "deno.exe"
            _download_asset(
                asset,
                archive_path,
                label="Deno",
                progress=progress,
            )

            with zipfile.ZipFile(archive_path) as archive:
                member = next(
                    (
                        item
                        for item in archive.infolist()
                        if Path(item.filename).name.lower() == "deno.exe"
                    ),
                    None,
                )
                if member is None:
                    raise ValueError("Deno ZIP에서 deno.exe를 찾지 못했습니다.")
                with archive.open(member) as source, staged.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)

            version_line = _executable_version(staged, ("--version",))
            os.replace(staged, RRV_TOOLS_DIR / "deno.exe")

        return True, f"{version_line} 설치 완료"
    except (OSError, HTTPError, URLError, ValueError, RuntimeError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        return False, f"Deno 설치에 실패했습니다: {error}"


def _wpc_status():  # type: ignore[no-untyped-def]
    return next((status for status in inspect_tools() if status.key == "pot"), None)


def ensure_wpc_runtime(progress: ProgressCallback | None = None) -> tuple[bool, str]:
    """WPC / nodriver 런타임의 관리 파일 무결성을 확인하고 필요할 때만 복구한다."""

    current = _wpc_status()
    if current is not None and current.available:
        return True, f"YouTube 인증 런타임 {current.version} · 무결성 정상"

    if progress is not None:
        progress("YouTube 인증 런타임 무결성 복구 중…")

    if not restore_bundled_wpc_provider():
        return False, "YouTube 인증 런타임 검증본을 복구하지 못했습니다."

    refreshed = _wpc_status()
    if refreshed is None or not refreshed.available:
        return False, "YouTube 인증 런타임 복구 후 SHA-256 검증에 실패했습니다."

    return True, (
        f"YouTube 인증 런타임 {refreshed.version} · "
        f"WPC {WPC_PROVIDER_VERSION} 검증본 복구 및 SHA-256 확인 완료"
    )


def ensure_runtime_tools(progress: ProgressCallback | None = None) -> tuple[bool, str]:
    """필수 외부 도구와 인증 런타임을 설치·업데이트하고 무결성을 확인한다."""
    actions = (
        ("yt-dlp", ensure_ytdlp),
        ("FFmpeg / FFprobe", update_ffmpeg_release),
        ("Deno", ensure_deno),
        ("YouTube 인증 런타임", ensure_wpc_runtime),
    )

    messages: list[str] = []
    all_ok = True
    for label, action in actions:
        if progress is not None:
            progress(f"{label} 준비 중…")
        ok, message = action(progress)
        all_ok = all_ok and ok
        messages.append(("✓ " if ok else "✕ ") + message)

    return all_ok, "\n".join(messages)
