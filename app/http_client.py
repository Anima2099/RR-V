from __future__ import annotations

import math
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import time
from typing import Callable, Mapping
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DownloadProgress = Callable[[int, int], None]


class HttpsTransportError(OSError):
    pass


def _require_https(url: str) -> None:
    parsed = urlparse(str(url))
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ValueError(f"HTTPS 주소만 사용할 수 있습니다: {url}")


def _is_certificate_verify_error(error: BaseException) -> bool:
    current: object | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, ssl.SSLCertVerificationError):
            return True
        text = str(current).upper()
        if "CERTIFICATE_VERIFY_FAILED" in text or "CERTIFICATE VERIFY FAILED" in text:
            return True
        current = getattr(current, "reason", None)
    return False


def _windows_curl() -> Path | None:
    if sys.platform != "win32":
        return None

    discovered = shutil.which("curl.exe")
    if discovered:
        path = Path(discovered)
        if path.is_file():
            return path

    system_root = os.environ.get("SystemRoot", "").strip()
    if system_root:
        candidate = Path(system_root) / "System32" / "curl.exe"
        if candidate.is_file():
            return candidate
    return None


def _curl_base_command(
    url: str,
    *,
    headers: Mapping[str, str] | None,
    timeout: float,
) -> list[str]:
    curl = _windows_curl()
    if curl is None:
        raise HttpsTransportError(
            "Windows curl.exe를 찾지 못해 시스템 인증서 저장소로 재시도할 수 없습니다."
        )

    command = [
        str(curl),
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "--proto",
        "=https",
        "--proto-redir",
        "=https",
        "--connect-timeout",
        str(max(1, min(30, int(math.ceil(timeout))))),
        "--max-time",
        str(max(1, int(math.ceil(timeout)))),
    ]
    for name, value in (headers or {}).items():
        command.extend(("--header", f"{name}: {value}"))
    command.append(url)
    return command


def _curl_fetch_bytes(
    url: str,
    *,
    headers: Mapping[str, str] | None,
    timeout: float,
    max_bytes: int,
) -> bytes:
    command = _curl_base_command(url, headers=headers, timeout=timeout)
    creation_flags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if sys.platform == "win32"
        else 0
    )
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=max(2.0, timeout + 3.0),
            creationflags=creation_flags,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise HttpsTransportError(f"Windows HTTPS 재시도 실행 실패: {error}") from error

    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise HttpsTransportError(
            f"Windows HTTPS 재시도 실패 (curl {result.returncode}): "
            f"{detail or '응답을 받지 못했습니다.'}"
        )
    if len(result.stdout) > max_bytes:
        raise ValueError("HTTPS 응답 크기가 허용 범위를 초과했습니다.")
    return bytes(result.stdout)


def fetch_https_bytes(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 10.0,
    max_bytes: int = 2 * 1024 * 1024,
) -> bytes:
    """HTTPS 데이터를 읽는다.

    일반 환경에서는 Python urllib을 그대로 사용한다. Windows에서 인증서 체인
    검증만 실패한 경우에 한해, 인증서 검증을 끄지 않고 Windows curl.exe로
    재시도한다. Windows curl은 시스템 인증서 저장소(Schannel)를 사용하므로
    로컬/조직 인증서가 Windows에는 신뢰되어 있지만 Python/OpenSSL 경로에서
    보이지 않는 환경을 안전하게 흡수한다.
    """
    _require_https(url)
    if max_bytes <= 0:
        raise ValueError("max_bytes는 0보다 커야 합니다.")

    request = Request(url, headers=dict(headers or {}))
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
    except (URLError, OSError) as error:
        if sys.platform != "win32" or not _is_certificate_verify_error(error):
            raise
        return _curl_fetch_bytes(
            url,
            headers=headers,
            timeout=timeout,
            max_bytes=max_bytes,
        )

    if len(data) > max_bytes:
        raise ValueError("HTTPS 응답 크기가 허용 범위를 초과했습니다.")
    return data


def fetch_https_text(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 10.0,
    max_bytes: int = 256 * 1024,
) -> str:
    return fetch_https_bytes(
        url,
        headers=headers,
        timeout=timeout,
        max_bytes=max_bytes,
    ).decode("utf-8", errors="replace").strip()


def _urllib_download(
    url: str,
    temporary: Path,
    *,
    headers: Mapping[str, str] | None,
    timeout: float,
    progress: DownloadProgress | None,
) -> None:
    request = Request(url, headers=dict(headers or {}))
    with urlopen(request, timeout=timeout) as response, temporary.open("wb") as output:
        try:
            total = int(response.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total = 0

        downloaded = 0
        if progress is not None:
            progress(0, total)
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            downloaded += len(chunk)
            if progress is not None:
                progress(downloaded, total)


def _curl_download(
    url: str,
    temporary: Path,
    *,
    headers: Mapping[str, str] | None,
    timeout: float,
    progress: DownloadProgress | None,
) -> None:
    command = _curl_base_command(url, headers=headers, timeout=timeout)
    command[-1:-1] = ("--output", str(temporary))
    creation_flags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if sys.platform == "win32"
        else 0
    )

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
        )
    except OSError as error:
        raise HttpsTransportError(f"Windows HTTPS 다운로드 실행 실패: {error}") from error

    last_size = -1
    if progress is not None:
        progress(0, 0)
    while process.poll() is None:
        try:
            current_size = temporary.stat().st_size if temporary.exists() else 0
        except OSError:
            current_size = 0
        if progress is not None and current_size != last_size:
            last_size = current_size
            progress(current_size, 0)
        time.sleep(0.15)

    _, stderr = process.communicate()
    if process.returncode != 0:
        detail = (stderr or b"").decode("utf-8", errors="replace").strip()
        raise HttpsTransportError(
            f"Windows HTTPS 다운로드 실패 (curl {process.returncode}): "
            f"{detail or '응답을 받지 못했습니다.'}"
        )

    if progress is not None:
        try:
            final_size = temporary.stat().st_size
        except OSError:
            final_size = 0
        progress(final_size, 0)


def download_https_file(
    url: str,
    destination: Path,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 60.0,
    progress: DownloadProgress | None = None,
) -> None:
    """HTTPS 파일을 검증된 연결로 다운로드하고 원자적으로 교체한다."""
    _require_https(url)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".rrv-http-part")
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass

    try:
        try:
            _urllib_download(
                url,
                temporary,
                headers=headers,
                timeout=timeout,
                progress=progress,
            )
        except (URLError, OSError) as error:
            if sys.platform != "win32" or not _is_certificate_verify_error(error):
                raise
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            _curl_download(
                url,
                temporary,
                headers=headers,
                timeout=timeout,
                progress=progress,
            )

        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise HttpsTransportError("다운로드한 파일이 비어 있습니다.")
        os.replace(temporary, destination)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
