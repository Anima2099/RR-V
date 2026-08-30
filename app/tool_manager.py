from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zipfile

from app.constants import APP_VERSION
from app.paths import (
    BUNDLED_WPC_RUNTIME_DIR,
    WPC_PROVIDER_VERSION,
    RRV_WPC_PROVIDER_DIR,
    RRV_WPC_RUNTIME_DIR,
    RRV_TOOLS_DIR,
    find_executable,
    has_bundled_tools,
    wpc_provider_runtime_ready,
    restore_bundled_tools,
)
from app.tool_sources import (
    FFMPEG_RELEASE_SHA256_URL,
    FFMPEG_RELEASE_VERSION_URL,
    FFMPEG_RELEASE_ZIP_URL,
    YTDLP_LATEST_API,
)


@dataclass(slots=True, frozen=True)
class ToolStatus:
    key: str
    label: str
    filename: str
    available: bool
    version: str
    path: str


_TOOL_SPECS = (
    ("ytdlp", "yt-dlp Nightly", "yt-dlp.exe", ("--version",)),
    ("ffmpeg", "FFmpeg", "ffmpeg.exe", ("-version",)),
    ("ffprobe", "FFprobe", "ffprobe.exe", ("-version",)),
    ("deno", "Deno", "deno.exe", ("--version",)),
)


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SHA256_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")
_FFMPEG_RELEASE_VERSION_RE = re.compile(
    r"(?<![\d.-])(\d+\.\d+(?:\.\d+)?)(?=[-+\s]|$)",
    re.IGNORECASE,
)
_UNUSABLE_VERSION_RESULTS = {"실행 오류", "버전 확인 불가"}


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", text)


def _creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _version_for(path: Path, args: tuple[str, ...]) -> str:
    try:
        result = subprocess.run(
            [str(path), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=_creation_flags(),
        )
    except (OSError, subprocess.SubprocessError):
        return "실행 오류"

    if result.returncode != 0:
        return "실행 오류"

    output = _strip_ansi(result.stdout or result.stderr or "").strip()
    if not output:
        return "버전 확인 불가"
    first = output.splitlines()[0].strip()
    if path.name.lower().startswith(("ffmpeg", "ffprobe")):
        marker = "version "
        lowered = first.lower()
        index = lowered.find(marker)
        if index >= 0:
            remainder = first[index + len(marker):].strip()
            return remainder.split()[0] if remainder else first[:60]
    return first[:80]


def _usable_version(version: str) -> bool:
    return bool(version.strip()) and version not in _UNUSABLE_VERSION_RESULTS


def _sha256_for(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _managed_tree_matches(source_root: Path, installed_root: Path) -> bool:
    """번들에 포함된 관리 파일이 설치 런타임에 바이트 단위로 동일한지 확인한다.

    설치 런타임에 생긴 추가 파일은 무시하되, 번들에 있던 파일이 없거나 내용이
    달라진 경우에는 손상으로 본다. __pycache__와 .pyc는 재생성 가능한 캐시라
    비교 대상에서 제외한다.
    """

    if not source_root.is_dir() or not installed_root.is_dir():
        return False

    try:
        source_files = tuple(
            path
            for path in source_root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix.lower() != ".pyc"
        )
    except OSError:
        return False

    if not source_files:
        return False

    for source in source_files:
        try:
            relative = source.relative_to(source_root)
            installed = installed_root / relative
            if not installed.is_file():
                return False
            if source.stat().st_size != installed.stat().st_size:
                return False
            if _sha256_for(source) != _sha256_for(installed):
                return False
        except (OSError, ValueError):
            return False
    return True


def _wpc_integrity_ready() -> bool:
    if not wpc_provider_runtime_ready():
        return False
    # 개발 환경에서 번들 기준 파일이 없는 경우에는 기존의 빠른 런타임 확인을
    # 유지한다. 최종 패키지에서는 번들 런타임과 SHA-256까지 비교한다.
    if not BUNDLED_WPC_RUNTIME_DIR.is_dir():
        return True
    return _managed_tree_matches(BUNDLED_WPC_RUNTIME_DIR, RRV_WPC_RUNTIME_DIR)


def _ffmpeg_pair_consistent(statuses: list[ToolStatus]) -> list[ToolStatus]:
    by_key = {status.key: status for status in statuses}
    ffmpeg = by_key.get("ffmpeg")
    ffprobe = by_key.get("ffprobe")
    if ffmpeg is None or ffprobe is None or not ffmpeg.available or not ffprobe.available:
        return statuses

    ffmpeg_version = _ffmpeg_release_version(ffmpeg.version)
    ffprobe_version = _ffmpeg_release_version(ffprobe.version)
    if ffmpeg_version == ffprobe_version:
        return statuses

    replaced: list[ToolStatus] = []
    for status in statuses:
        if status.key == "ffmpeg":
            replaced.append(
                ToolStatus(
                    key=status.key,
                    label=status.label,
                    filename=status.filename,
                    available=False,
                    version=f"{status.version} · FFprobe와 버전 불일치",
                    path=status.path,
                )
            )
        elif status.key == "ffprobe":
            replaced.append(
                ToolStatus(
                    key=status.key,
                    label=status.label,
                    filename=status.filename,
                    available=False,
                    version=f"{status.version} · FFmpeg와 버전 불일치",
                    path=status.path,
                )
            )
        else:
            replaced.append(status)
    return replaced


def inspect_tools() -> tuple[ToolStatus, ...]:
    statuses: list[ToolStatus] = []
    for key, label, filename, args in _TOOL_SPECS:
        path = find_executable(filename)
        if path is None:
            statuses.append(
                ToolStatus(
                    key=key,
                    label=label,
                    filename=filename,
                    available=False,
                    version="없음",
                    path=str(RRV_TOOLS_DIR / filename),
                )
            )
            continue

        version = _version_for(path, args)
        statuses.append(
            ToolStatus(
                key=key,
                label=label,
                filename=filename,
                available=_usable_version(version),
                version=version,
                path=str(path),
            )
        )

    statuses = _ffmpeg_pair_consistent(statuses)
    wpc_runtime_present = wpc_provider_runtime_ready()
    wpc_integrity_ok = _wpc_integrity_ready()
    statuses.append(
        ToolStatus(
            key="pot",
            label="YouTube 인증 런타임",
            filename="WPC / nodriver",
            available=wpc_integrity_ok,
            version=(
                f"WPC {WPC_PROVIDER_VERSION} + nodriver"
                if wpc_integrity_ok
                else ("손상 또는 불완전" if wpc_runtime_present else "없음")
            ),
            path=str(RRV_WPC_PROVIDER_DIR),
        )
    )
    return tuple(statuses)


def _fetch_small_text(url: str, *, accept: str = "text/plain") -> str:
    request = Request(
        url,
        headers={
            "User-Agent": f"RR-V/{APP_VERSION}",
            "Accept": accept,
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(request, timeout=12) as response:
        data = response.read(256 * 1024)
    return data.decode("utf-8", errors="replace").strip()


def _extract_named_sha256(text: str, filename: str) -> str | None:
    target = filename.casefold()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        candidate_name = parts[-1].lstrip("*./").casefold()
        match = _SHA256_RE.fullmatch(parts[0])
        if candidate_name == target and match is not None:
            return match.group(1).lower()
    return None


def _latest_ytdlp_nightly_identity() -> tuple[str, str]:
    payload = json.loads(
        _fetch_small_text(
            YTDLP_LATEST_API,
            accept="application/vnd.github+json",
        )
    )
    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        raise ValueError("yt-dlp Nightly 최신 릴리스 태그를 찾지 못했습니다.")

    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("yt-dlp Nightly 릴리스 파일 목록을 확인하지 못했습니다.")

    exe_asset: dict[str, object] | None = None
    checksum_asset: dict[str, object] | None = None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        if name == "yt-dlp.exe":
            exe_asset = asset
        elif name == "SHA2-256SUMS":
            checksum_asset = asset

    if exe_asset is None:
        raise ValueError("yt-dlp Nightly 릴리스에서 yt-dlp.exe를 찾지 못했습니다.")

    digest_text = str(exe_asset.get("digest") or "").strip()
    if digest_text.lower().startswith("sha256:"):
        digest = digest_text.split(":", 1)[1].strip().lower()
        if _SHA256_RE.fullmatch(digest):
            return tag, digest

    if checksum_asset is None:
        raise ValueError("yt-dlp Nightly SHA-256 파일을 찾지 못했습니다.")
    checksum_url = str(checksum_asset.get("browser_download_url") or "").strip()
    if not checksum_url.startswith("https://"):
        raise ValueError("yt-dlp Nightly SHA-256 다운로드 주소가 올바르지 않습니다.")
    checksum_text = _fetch_small_text(checksum_url)
    digest = _extract_named_sha256(checksum_text, "yt-dlp.exe")
    if digest is None:
        raise ValueError("yt-dlp.exe의 SHA-256 값을 확인하지 못했습니다.")
    return tag, digest


def update_ytdlp(progress: Callable[[str], None] | None = None) -> tuple[bool, str]:
    path = find_executable("yt-dlp.exe")
    if path is None:
        return False, "yt-dlp.exe가 없어서 업데이트할 수 없습니다. 도구 복구를 먼저 실행해 주세요."

    if progress is not None:
        progress("yt-dlp Nightly 공식 SHA-256 확인 중…")

    try:
        target_tag, expected_sha256 = _latest_ytdlp_nightly_identity()
        current_sha256 = _sha256_for(path)
    except (OSError, HTTPError, URLError, ValueError, json.JSONDecodeError) as error:
        return False, f"yt-dlp 공식 SHA-256을 확인하지 못해 업데이트를 중단했습니다: {error}"

    if current_sha256.lower() == expected_sha256:
        version = _version_for(path, ("--version",))
        if not _usable_version(version):
            return False, "yt-dlp 파일 해시는 정상이나 실행 검증에 실패했습니다. 도구 복구를 시도해 주세요."
        return True, f"yt-dlp Nightly {version} · 이미 최신 상태이며 SHA-256 검증을 통과했습니다."

    if progress is not None:
        progress(f"yt-dlp Nightly {target_tag} 업데이트 중…")

    try:
        result = subprocess.run(
            [str(path), "--update-to", f"nightly@{target_tag}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            creationflags=_creation_flags(),
        )
    except subprocess.TimeoutExpired:
        return False, "yt-dlp 업데이트 확인 시간이 초과되어 중단되었습니다."
    except OSError as error:
        return False, f"yt-dlp를 실행하지 못했습니다: {error}"

    output = _strip_ansi(
        "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if part and part.strip()
        )
    ).strip()

    try:
        actual_sha256 = _sha256_for(path)
    except OSError as error:
        return False, f"yt-dlp 업데이트 후 파일 무결성을 확인하지 못했습니다: {error}"
    if actual_sha256.lower() != expected_sha256:
        return False, (
            "yt-dlp 업데이트 후 SHA-256이 공식 릴리스와 일치하지 않습니다. "
            "도구 복구 후 다시 시도해 주세요."
        )

    verified_version = _version_for(path, ("--version",))
    if not _usable_version(verified_version):
        return False, "yt-dlp 업데이트 파일의 SHA-256은 일치하지만 실행 검증에 실패했습니다."

    verification = f"SHA-256 및 실행 검증 완료 · {verified_version}"
    if result.returncode != 0:
        # yt-dlp 자체 업데이터가 재시작 단계 등에서 경고/오류를 반환했더라도,
        # RR-V가 고정한 공식 릴리스 해시와 실제 파일이 일치하고 새 실행 파일이
        # 정상 실행되면 설치 결과 자체는 안전한 것으로 판단한다.
        return True, f"{output}\n{verification}" if output else verification
    return True, f"{output}\n{verification}" if output else verification


def update_deno(progress: Callable[[str], None] | None = None) -> tuple[bool, str]:
    path = find_executable("deno.exe")
    if path is None:
        return False, "deno.exe가 없어서 업데이트할 수 없습니다. 도구 복구를 먼저 실행해 주세요."

    if progress is not None:
        progress("Deno 업데이트 확인 중…")

    try:
        result = subprocess.run(
            [str(path), "upgrade"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            creationflags=_creation_flags(),
        )
    except subprocess.TimeoutExpired:
        return False, "Deno 업데이트 확인 시간이 초과되어 중단되었습니다."
    except OSError as error:
        return False, f"Deno를 실행하지 못했습니다: {error}"

    output = _strip_ansi(
        "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if part and part.strip()
        )
    ).strip()
    if result.returncode != 0:
        return False, output or "Deno 업데이트에 실패했습니다."

    verified_version = _version_for(path, ("--version",))
    if not _usable_version(verified_version):
        return False, "Deno 업데이트는 끝났지만 실행 검증에 실패했습니다. 도구 복구를 시도해 주세요."
    verification = f"실행 검증 완료 · {verified_version}"
    return True, f"{output}\n{verification}" if output else verification


def _ffmpeg_release_version(value: str) -> str:
    match = _FFMPEG_RELEASE_VERSION_RE.search(value)
    return match.group(1) if match else value.strip()


def _download_progress_text(downloaded: int, total: int) -> str:
    downloaded_mb = downloaded / (1024 * 1024)
    if total <= 0:
        return f"↓ FFmpeg 업데이트 다운로드 중 · {downloaded_mb:.1f} MB 받음"

    total_mb = total / (1024 * 1024)
    percent = max(0, min(100, int(downloaded * 100 / total)))
    slots = 16
    filled = min(slots, int(percent * slots / 100))
    bar = "█" * filled + "░" * (slots - filled)
    return (
        f"↓ FFmpeg 업데이트 다운로드 중 · {downloaded_mb:.1f} / {total_mb:.1f} MB · {percent}%\n"
        f"{bar}"
    )


def _download_file(
    url: str,
    destination: Path,
    progress: Callable[[str], None] | None = None,
) -> None:
    request = Request(
        url,
        headers={
            "User-Agent": f"RR-V/{APP_VERSION}",
            "Accept": "application/zip, application/octet-stream;q=0.9, */*;q=0.1",
            "Cache-Control": "no-cache",
        },
    )

    with urlopen(request, timeout=60) as response, destination.open("wb") as output:
        try:
            total = int(response.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total = 0

        downloaded = 0
        last_percent = -1
        if progress is not None:
            progress(_download_progress_text(0, total))

        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            downloaded += len(chunk)

            if progress is None:
                continue

            if total > 0:
                percent = max(0, min(100, int(downloaded * 100 / total)))
                # 100 MB 전후의 파일에서 UI 신호를 과도하게 보내지 않으면서도
                # 진행이 살아 움직이는 느낌을 주도록 퍼센트가 바뀔 때만 갱신한다.
                if percent == last_percent:
                    continue
                last_percent = percent
            progress(_download_progress_text(downloaded, total))

        if progress is not None:
            progress(
                f"✓ FFmpeg 다운로드 완료 · {downloaded / (1024 * 1024):.1f} MB\n"
                "파일 무결성 확인 중…"
            )


def _extract_ffmpeg_pair(archive_path: Path, target_dir: Path) -> tuple[Path, Path]:
    with zipfile.ZipFile(archive_path) as archive:
        selected: dict[str, zipfile.ZipInfo] = {}
        for member in archive.infolist():
            normalized = member.filename.replace("\\", "/").lower()
            if normalized.endswith("/bin/ffmpeg.exe"):
                selected["ffmpeg.exe"] = member
            elif normalized.endswith("/bin/ffprobe.exe"):
                selected["ffprobe.exe"] = member

        if set(selected) != {"ffmpeg.exe", "ffprobe.exe"}:
            raise ValueError("다운로드한 FFmpeg ZIP에서 ffmpeg.exe와 ffprobe.exe를 찾지 못했습니다.")

        extracted: dict[str, Path] = {}
        for filename, member in selected.items():
            destination = target_dir / filename
            with archive.open(member) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            extracted[filename] = destination

    return extracted["ffmpeg.exe"], extracted["ffprobe.exe"]


def _rollback_tool_pair(
    installed: list[Path],
    backups: dict[Path, Path],
) -> None:
    for destination in installed:
        try:
            if destination.exists():
                destination.unlink()
        except OSError:
            pass
    for destination, backup in backups.items():
        try:
            if backup.exists():
                os.replace(backup, destination)
        except OSError:
            pass


def update_ffmpeg_release(
    progress: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    """Gyan Release Essentials ZIP에서 ffmpeg/ffprobe를 검증 후 한 쌍으로 교체한다."""
    try:
        latest_text = _fetch_small_text(FFMPEG_RELEASE_VERSION_URL)
        latest_version = _ffmpeg_release_version(latest_text)
        if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", latest_version):
            return False, "FFmpeg 최신 Release 버전 정보를 확인하지 못했습니다."

        current = find_executable("ffmpeg.exe")
        if current is not None:
            current_version = _ffmpeg_release_version(_version_for(current, ("-version",)))
            if current_version == latest_version:
                return True, f"FFmpeg / FFprobe {latest_version} · 이미 최신 상태입니다."

        sha_text = _fetch_small_text(FFMPEG_RELEASE_SHA256_URL)
        sha_match = _SHA256_RE.search(sha_text)
        if sha_match is None:
            return False, "FFmpeg SHA-256 정보를 확인하지 못해 업데이트를 중단했습니다."
        expected_sha256 = sha_match.group(1).lower()

        RRV_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="rrv-ffmpeg-update-",
            dir=str(RRV_TOOLS_DIR.parent),
        ) as temporary_dir:
            temporary_root = Path(temporary_dir)
            archive_path = temporary_root / "ffmpeg-release-essentials.zip"
            staging_dir = temporary_root / "staging"
            staging_dir.mkdir(parents=True, exist_ok=True)

            _download_file(FFMPEG_RELEASE_ZIP_URL, archive_path, progress)
            if progress is not None:
                progress("✓ FFmpeg ZIP 다운로드 완료 · SHA-256 검증 중…")
            actual_sha256 = _sha256_for(archive_path)
            if actual_sha256.lower() != expected_sha256:
                return False, "FFmpeg ZIP의 SHA-256이 일치하지 않아 업데이트를 중단했습니다."

            if progress is not None:
                progress("✓ SHA-256 확인 완료 · 새 FFmpeg / FFprobe 준비 중…")
            staged_ffmpeg, staged_ffprobe = _extract_ffmpeg_pair(
                archive_path,
                staging_dir,
            )
            staged_versions = (
                _ffmpeg_release_version(_version_for(staged_ffmpeg, ("-version",))),
                _ffmpeg_release_version(_version_for(staged_ffprobe, ("-version",))),
            )
            if staged_versions != (latest_version, latest_version):
                return False, "새 FFmpeg / FFprobe 실행 파일의 버전 검증에 실패했습니다."

            if progress is not None:
                progress("↻ FFmpeg / FFprobe 안전 교체 중…")

            destinations = {
                staged_ffmpeg: RRV_TOOLS_DIR / "ffmpeg.exe",
                staged_ffprobe: RRV_TOOLS_DIR / "ffprobe.exe",
            }
            backups: dict[Path, Path] = {}
            installed: list[Path] = []

            try:
                for destination in destinations.values():
                    backup = destination.with_name(destination.name + ".rrv-backup")
                    if backup.exists():
                        backup.unlink()
                    if destination.exists():
                        os.replace(destination, backup)
                        backups[destination] = backup

                for staged, destination in destinations.items():
                    os.replace(staged, destination)
                    installed.append(destination)

                if progress is not None:
                    progress("↻ 새 FFmpeg / FFprobe 실행 확인 중…")
                final_versions = (
                    _ffmpeg_release_version(
                        _version_for(RRV_TOOLS_DIR / "ffmpeg.exe", ("-version",))
                    ),
                    _ffmpeg_release_version(
                        _version_for(RRV_TOOLS_DIR / "ffprobe.exe", ("-version",))
                    ),
                )
                if final_versions != (latest_version, latest_version):
                    raise RuntimeError("교체 후 실행 검증에 실패했습니다.")
            except (OSError, RuntimeError) as error:
                _rollback_tool_pair(installed, backups)
                if isinstance(error, PermissionError):
                    return False, (
                        "FFmpeg를 사용하는 작업이 실행 중일 수 있습니다. "
                        "다운로드와 미디어 작업을 모두 끝낸 뒤 다시 시도해 주세요."
                    )
                return False, f"FFmpeg 교체에 실패해 이전 버전으로 복구했습니다: {error}"

            for backup in backups.values():
                try:
                    backup.unlink(missing_ok=True)
                except OSError:
                    pass

        return True, f"FFmpeg / FFprobe {latest_version} 업데이트 완료"
    except (OSError, HTTPError, URLError, zipfile.BadZipFile, ValueError) as error:
        return False, f"FFmpeg 업데이트에 실패했습니다: {error}"


def restore_packaged_tools() -> tuple[bool, str]:
    if not has_bundled_tools():
        return False, "현재 개발용 실행에서는 내장 도구가 없습니다. 최종 패키지에서는 사용할 수 있습니다."
    restored = restore_bundled_tools()
    if not restored:
        return False, "복구할 수 있는 내장 도구를 찾지 못했습니다."

    status_by_key = {status.key: status for status in inspect_tools()}
    key_for_restored = {
        "yt-dlp.exe": "ytdlp",
        "ffmpeg.exe": "ffmpeg",
        "ffprobe.exe": "ffprobe",
        "deno.exe": "deno",
        "YouTube 인증 런타임 (WPC)": "pot",
    }
    failed: list[str] = []
    for item in restored:
        key = key_for_restored.get(item)
        if key is None:
            continue
        status = status_by_key.get(key)
        if status is None or not status.available:
            failed.append(item)

    if failed:
        return False, "복구 후 무결성 검증에 실패했습니다: " + ", ".join(failed)
    return True, f"도구 {len(restored)}개를 복구하고 무결성 검증을 완료했습니다."
