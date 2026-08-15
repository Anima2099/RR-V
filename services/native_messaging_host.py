from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from typing import Iterable
from urllib.parse import urlparse

from app.paths import RRV_EXTERNAL_URL_ENDPOINT_PATH
from app.url_list_io import probable_collection_urls


_NATIVE_ORIGIN_PREFIX = "chrome-extension://"
_MAX_MESSAGE_BYTES = 512 * 1024
_MAX_URLS = 100
_EXTERNAL_PROTOCOL_VERSION = 1
_EXTERNAL_MAX_MESSAGE_BYTES = 512 * 1024


class NativeMessagingError(RuntimeError):
    pass


def is_native_messaging_invocation(arguments: Iterable[str]) -> bool:
    """Chrome/Edge Native Messaging host로 실행된 RR-V 프로세스인지 판별한다."""
    for argument in arguments:
        if str(argument).startswith(_NATIVE_ORIGIN_PREFIX):
            return True
    return False


def run_native_messaging_host() -> int:
    """Native Messaging 요청 하나를 읽고 RR-V 외부 URL 입구로 넘긴다.

    Chrome/Edge의 ``runtime.sendNativeMessage``는 메시지마다 host 프로세스를
    하나 실행하고 첫 응답만 사용한다. RR-V가 이미 실행 중이면 DEV11의
    QLocalServer(named pipe)에 URL을 직접 기록하고, 실행 중인 RR-V가 없을 때만
    일반 RR-V 프로세스를 URL 인자와 함께 실행한다.
    """
    try:
        message = _read_native_message()
        urls = _extract_message_urls(message)
        if not urls:
            _write_native_message(
                {
                    "ok": False,
                    "count": 0,
                    "error": "전달할 HTTP(S) 주소가 없습니다.",
                }
            )
            return 2

        collection_urls = probable_collection_urls(urls)
        collection_keys = {url.casefold() for url in collection_urls}
        direct_urls = [url for url in urls if url.casefold() not in collection_keys]
        if not direct_urls:
            _write_native_message(
                {
                    "ok": False,
                    "count": 0,
                    "skipped": len(collection_urls),
                    "error": "재생목록/채널 주소는 RR-V 일괄 추가의 목록 확인을 사용해 주세요.",
                }
            )
            return 3

        delivery = "running" if _try_forward_to_running_rrv(direct_urls) else "launch"
        if delivery == "launch":
            _launch_rrv(direct_urls)
        _write_native_message(
            {
                "ok": True,
                "count": len(direct_urls),
                "skipped": len(collection_urls),
                "delivery": delivery,
            }
        )
        return 0
    except Exception as error:  # Native host는 브라우저에 실패 원인을 되돌려준다.
        try:
            _write_native_message(
                {
                    "ok": False,
                    "count": 0,
                    "error": str(error) or error.__class__.__name__,
                }
            )
        except Exception:
            pass
        return 1


def _extract_message_urls(message: object) -> list[str]:
    if not isinstance(message, dict):
        return []

    action = str(message.get("action", "send_urls")).strip().lower()
    if action not in {"send_url", "send_urls", "enqueue"}:
        return []

    candidates: list[object] = []
    raw_urls = message.get("urls")
    if isinstance(raw_urls, list):
        candidates.extend(raw_urls)
    raw_url = message.get("url")
    if raw_url:
        candidates.append(raw_url)

    urls: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if not _is_http_url(normalized):
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        urls.append(normalized)
        if len(urls) >= _MAX_URLS:
            break
    return urls


def _is_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _try_forward_to_running_rrv(urls: list[str]) -> bool:
    """실행 중인 RR-V의 QLocalServer(named pipe)에 URL을 직접 전달한다.

    Native Messaging host는 이미 PyInstaller onefile로 한 번 실행된 상태다.
    기존 RR-V가 살아 있다면 같은 EXE를 또 띄우지 않고 DEV11 로컬 소켓으로
    바로 넘겨 두 번째 onefile 시작 비용을 피한다. endpoint가 없거나 연결에
    실패하면 기존 `_launch_rrv()` 경로로 안전하게 폴백한다.
    """
    if os.name != "nt" or not urls:
        return False

    try:
        endpoint = json.loads(
            RRV_EXTERNAL_URL_ENDPOINT_PATH.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(endpoint, dict):
        return False
    if endpoint.get("version") != _EXTERNAL_PROTOCOL_VERSION:
        return False

    pipe_name = str(endpoint.get("full_server_name", "")).strip()
    if not pipe_name:
        return False

    payload = _encode_external_request(urls)
    if len(payload) > _EXTERNAL_MAX_MESSAGE_BYTES:
        return False
    return _windows_write_named_pipe(pipe_name, payload)


def _encode_external_request(urls: list[str]) -> bytes:
    payload = {
        "version": _EXTERNAL_PROTOCOL_VERSION,
        "activate": False,
        "source": "browser",
        "urls": urls[:_MAX_URLS],
    }
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _windows_write_named_pipe(pipe_name: str, payload: bytes) -> bool:
    """Qt QLocalServer가 연 Windows named pipe에 stdlib/ctypes만으로 쓴다."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    wait_named_pipe = kernel32.WaitNamedPipeW
    wait_named_pipe.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    wait_named_pipe.restype = wintypes.BOOL

    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE

    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    generic_read = 0x80000000
    generic_write = 0x40000000
    open_existing = 3
    file_attribute_normal = 0x80
    invalid_handle = wintypes.HANDLE(-1).value

    # endpoint는 listen 성공 뒤에만 기록되므로 대개 즉시 연결된다. 아주 짧은
    # 스케줄링 차이만 흡수하고, 지연되면 기존 EXE 실행 경로로 폴백한다.
    for wait_ms in (0, 60, 120):
        if wait_ms and not wait_named_pipe(pipe_name, wait_ms):
            continue
        handle = create_file(
            pipe_name,
            generic_read | generic_write,
            0,
            None,
            open_existing,
            file_attribute_normal,
            None,
        )
        if not handle or handle == invalid_handle:
            continue
        try:
            written = _windows_write(handle, payload)
            return written == len(payload)
        except NativeMessagingError:
            return False
        finally:
            close_handle(handle)
    return False


def _launch_rrv(urls: list[str]) -> None:
    if getattr(sys, "frozen", False):
        command = [
            str(Path(sys.executable).resolve()),
            "--browser-extension",
            *urls,
        ]
    else:
        project_root = Path(__file__).resolve().parent.parent
        command = [
            str(Path(sys.executable).resolve()),
            str(project_root / "main.py"),
            "--browser-extension",
            *urls,
        ]

    child_environment = os.environ.copy()
    if getattr(sys, "frozen", False):
        # PyInstaller onefile에서 같은 EXE를 다시 실행하면 기본적으로 현재
        # _MEI 임시 디렉터리를 재사용하는 worker 프로세스로 취급된다. Native
        # Messaging host는 새 RR-V를 띄운 뒤 먼저 종료하므로, 그 임시 폴더가
        # 정리되면 새 RR-V가 base_library.zip 등을 잃고 시작 중 충돌할 수 있다.
        # 새 프로세스를 독립 인스턴스로 명시해 자체 _MEI 디렉터리를 사용한다.
        child_environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"

    kwargs: dict[str, object] = {
        "cwd": str(Path(command[0]).resolve().parent),
        "close_fds": True,
        "env": child_environment,
        # 새 RR-V 프로세스가 브라우저의 Native Messaging stdio 파이프를
        # 상속해 프로토콜 응답을 오염시키지 않도록 완전히 분리한다.
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        subprocess.Popen(command, **kwargs)
    except OSError as error:
        raise NativeMessagingError(f"RR-V를 실행하지 못했습니다: {error}") from error


def _read_native_message() -> object:
    header = _read_exact(4)
    if len(header) != 4:
        raise NativeMessagingError("Native Messaging 메시지 길이를 읽지 못했습니다.")
    message_length = struct.unpack("=I", header)[0]
    if message_length <= 0 or message_length > _MAX_MESSAGE_BYTES:
        raise NativeMessagingError("Native Messaging 메시지 크기가 올바르지 않습니다.")
    payload = _read_exact(message_length)
    if len(payload) != message_length:
        raise NativeMessagingError("Native Messaging 메시지가 중간에 끊겼습니다.")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NativeMessagingError("Native Messaging JSON을 읽지 못했습니다.") from error


def _write_native_message(message: dict[str, object]) -> None:
    payload = json.dumps(
        message,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > 1024 * 1024:
        raise NativeMessagingError("Native Messaging 응답이 너무 큽니다.")
    _write_all(struct.pack("=I", len(payload)) + payload)


def _read_exact(size: int) -> bytes:
    if os.name != "nt":
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        data = bytearray()
        while len(data) < size:
            chunk = stream.read(size - len(data))
            if not chunk:
                break
            data.extend(chunk)
        return bytes(data)

    handle = _windows_std_handle(-10)  # STD_INPUT_HANDLE
    data = bytearray()
    while len(data) < size:
        chunk = _windows_read(handle, size - len(data))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def _write_all(data: bytes) -> None:
    if os.name != "nt":
        stream = getattr(sys.stdout, "buffer", sys.stdout)
        stream.write(data)
        stream.flush()
        return

    handle = _windows_std_handle(-11)  # STD_OUTPUT_HANDLE
    offset = 0
    while offset < len(data):
        written = _windows_write(handle, data[offset:])
        if written <= 0:
            raise NativeMessagingError("Native Messaging 응답을 브라우저에 쓰지 못했습니다.")
        offset += written


def _windows_std_handle(kind: int) -> wintypes.HANDLE:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_std_handle = kernel32.GetStdHandle
    get_std_handle.argtypes = [wintypes.DWORD]
    get_std_handle.restype = wintypes.HANDLE
    handle = get_std_handle(kind & 0xFFFFFFFF)
    invalid = wintypes.HANDLE(-1).value
    if not handle or handle == invalid:
        raise NativeMessagingError("브라우저의 Native Messaging 파이프를 찾지 못했습니다.")
    return handle


def _windows_read(handle: wintypes.HANDLE, size: int) -> bytes:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    read_file = kernel32.ReadFile
    read_file.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    read_file.restype = wintypes.BOOL

    buffer = ctypes.create_string_buffer(size)
    read_count = wintypes.DWORD(0)
    if not read_file(handle, buffer, size, ctypes.byref(read_count), None):
        error = ctypes.get_last_error()
        if error in {109, 232}:  # ERROR_BROKEN_PIPE / ERROR_NO_DATA
            return b""
        raise NativeMessagingError(f"Native Messaging 읽기 오류: {error}")
    return buffer.raw[: read_count.value]


def _windows_write(handle: wintypes.HANDLE, data: bytes) -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    write_file = kernel32.WriteFile
    write_file.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    write_file.restype = wintypes.BOOL

    buffer = ctypes.create_string_buffer(data)
    write_count = wintypes.DWORD(0)
    if not write_file(
        handle,
        buffer,
        len(data),
        ctypes.byref(write_count),
        None,
    ):
        error = ctypes.get_last_error()
        raise NativeMessagingError(f"Native Messaging 쓰기 오류: {error}")
    return int(write_count.value)
