from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable

from app.paths import (
    WPC_PROVIDER_VERSION,
    RRV_WPC_PROVIDER_DIR,
    RRV_TOOLS_DIR,
    find_executable,
    has_bundled_tools,
    wpc_provider_runtime_ready,
    restore_bundled_tools,
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
        statuses.append(
            ToolStatus(
                key=key,
                label=label,
                filename=filename,
                available=True,
                version=_version_for(path, args),
                path=str(path),
            )
        )
    wpc_ready = wpc_provider_runtime_ready()
    statuses.append(
        ToolStatus(
            key="pot",
            label="YouTube 인증 런타임",
            filename="WPC / nodriver",
            available=wpc_ready,
            version=f"WPC {WPC_PROVIDER_VERSION} + nodriver" if wpc_ready else "없음",
            path=str(RRV_WPC_PROVIDER_DIR),
        )
    )
    return tuple(statuses)


def update_ytdlp(progress: Callable[[str], None] | None = None) -> tuple[bool, str]:
    path = find_executable("yt-dlp.exe")
    if path is None:
        return False, "yt-dlp.exe가 없어서 업데이트할 수 없습니다. 도구 복구를 먼저 실행해 주세요."

    if progress is not None:
        progress("yt-dlp Nightly 업데이트 확인 중…")

    try:
        result = subprocess.run(
            [str(path), "--update-to", "nightly"],
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
    if result.returncode != 0:
        return False, output or "yt-dlp 업데이트에 실패했습니다."
    return True, output or "yt-dlp Nightly 업데이트 확인 완료"


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
    return True, output or "Deno 업데이트 확인 완료"


def restore_packaged_tools() -> tuple[bool, str]:
    if not has_bundled_tools():
        return False, "현재 개발용 실행에서는 내장 도구가 없습니다. 최종 패키지에서는 사용할 수 있습니다."
    restored = restore_bundled_tools()
    if not restored:
        return False, "복구할 수 있는 내장 도구를 찾지 못했습니다."
    return True, f"도구 {len(restored)}개를 복구했습니다."
