from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from time import monotonic, sleep
from typing import Iterable, Sequence

from PySide6.QtCore import QObject, QLockFile, QStandardPaths, Signal
from PySide6.QtNetwork import (
    QHostAddress,
    QLocalServer,
    QLocalSocket,
    QTcpServer,
    QTcpSocket,
)

from app.paths import RRV_EXTERNAL_URL_ENDPOINT_PATH
from app.url_list_io import extract_urls, probable_collection_urls


_PROTOCOL_VERSION = 1
_MAX_URLS = 500
_MAX_MESSAGE_BYTES = 512 * 1024
_CONNECT_ATTEMPT_MS = 180
_CONNECT_TOTAL_SECONDS = 1.8

# 브라우저 확장이 이미 실행 중인 RR-V로 Native Host EXE를 띄우지 않고 바로
# 전달하기 위한 loopback 전용 HTTP 입구다. 127.0.0.1에만 bind하므로 외부
# 네트워크에서는 접근할 수 없고, 확장 전용 헤더 키와 Origin도 함께 검사한다.
_BROWSER_FAST_PATH_PORT = 47813
_BROWSER_FAST_PATH_ROUTE = "/rrv/browser/send"
_BROWSER_FAST_PATH_TOKEN = (
    "rrv-bridge-6a4d40f9a5914cd3a80e4fb78558b27f-13f5"
)
_BROWSER_EXTENSION_ORIGIN = "chrome-extension://jpnikadifjddeldmjkenhoeechklnjnk"
_MAX_HTTP_HEADER_BYTES = 32 * 1024
_MAX_HTTP_BODY_BYTES = 256 * 1024


def extract_external_urls(arguments: Sequence[str]) -> list[str]:
    """명령행 인자에서 HTTP(S) URL을 입력 순서대로 중복 없이 추출한다."""
    if not arguments:
        return []
    return extract_urls("\n".join(str(argument) for argument in arguments))[:_MAX_URLS]


def _encode_request(
    urls: Iterable[str],
    *,
    activate: bool,
    source: str = "external",
) -> bytes:
    normalized = extract_urls("\n".join(str(url) for url in urls))[:_MAX_URLS]
    normalized_source = (
        "browser" if str(source).strip().lower() == "browser" else "external"
    )
    payload = {
        "version": _PROTOCOL_VERSION,
        "activate": bool(activate),
        "source": normalized_source,
        "urls": normalized,
    }
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _decode_request(payload: bytes) -> tuple[list[str], bool, str] | None:
    if not payload or len(payload) > _MAX_MESSAGE_BYTES:
        return None
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != _PROTOCOL_VERSION:
        return None

    raw_urls = data.get("urls", [])
    if not isinstance(raw_urls, list):
        raw_urls = []
    urls = extract_external_urls([str(value) for value in raw_urls])
    activate = bool(data.get("activate", False))
    source = (
        "browser"
        if str(data.get("source", "")).strip().lower() == "browser"
        else "external"
    )
    return urls, activate, source


def _instance_paths() -> tuple[Path, str]:
    local_data = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    identity_source = str(Path(local_data).resolve()) if local_data else "RR-V"
    suffix = hashlib.sha256(identity_source.encode("utf-8")).hexdigest()[:12]

    temp_dir = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.TempLocation
    )
    lock_dir = Path(temp_dir or ".")
    return lock_dir / f"rr-v-{suffix}.lock", f"RR-V.ExternalUrl.{suffix}"


class ExternalUrlService(QObject):
    """RR-V 단일 실행과 로컬 URL 전달을 담당한다.

    기본 단일 실행 통신은 QLocalServer/QLocalSocket을 사용한다. 첫 RR-V가
    잠금과 로컬 서버를 소유하고 이후 실행은 URL/활성화 요청만 전달한다.
    브라우저 확장에는 실행 중 RR-V로 빠르게 전달할 수 있도록 127.0.0.1
    loopback 전용의 작은 HTTP 입구도 함께 연다. 이 입구를 열지 못해도 기존
    Native Messaging/QLocalServer 경로가 그대로 폴백으로 남는다.
    """

    request_received = Signal(object, bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        lock_path, server_name = _instance_paths()
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        self._server_name = server_name
        self._lock_file = QLockFile(str(lock_path))
        # RR-V가 실행되는 동안 계속 유지하는 잠금이므로 시간 경과만으로
        # stale 판정을 내리지 않는다. 프로세스 생존 여부를 기준으로 복구한다.
        self._lock_file.setStaleLockTime(0)
        self._server = QLocalServer(self)
        self._socket_buffers: dict[int, bytearray] = {}

        self._browser_server = QTcpServer(self)
        self._browser_socket_buffers: dict[int, bytearray] = {}

        try:
            self._server.setSocketOptions(
                QLocalServer.SocketOption.UserAccessOption
            )
        except (AttributeError, TypeError):
            # 일부 플랫폼에서는 접근 옵션이 적용되지 않을 수 있다.
            pass

        self._server.newConnection.connect(self._accept_pending_connections)
        self._browser_server.newConnection.connect(
            self._accept_browser_fast_path_connections
        )

    @property
    def server_name(self) -> str:
        return self._server_name

    def try_become_primary(self) -> bool:
        """이 프로세스가 첫 RR-V라면 잠금을 얻고 로컬 수신 서버를 연다."""
        if not self._lock_file.tryLock(0):
            return False

        # 잠금을 얻은 프로세스만 stale endpoint를 정리하므로 살아 있는 첫
        # 인스턴스의 서버를 실수로 제거하지 않는다.
        QLocalServer.removeServer(self._server_name)
        if self._server.listen(self._server_name):
            self._start_browser_fast_path()
            self._publish_endpoint()
            return True

        self._lock_file.unlock()
        return False

    def try_recover_stale_primary(self) -> bool:
        """기존 프로세스가 사라졌는데 lock 파일만 남은 경우 한 번 복구한다."""
        try:
            removed = self._lock_file.removeStaleLockFile()
        except OSError:
            removed = False
        return bool(removed) and self.try_become_primary()

    def forward_to_primary(
        self,
        urls: Iterable[str],
        *,
        activate: bool,
        source: str = "external",
    ) -> bool:
        """실행 중인 첫 RR-V에 요청을 전달한다.

        첫 프로세스가 막 서버를 여는 짧은 구간을 고려해 제한된 시간 동안만
        재시도한다. 인터넷 통신은 사용하지 않는다.
        """
        payload = _encode_request(urls, activate=activate, source=source)
        if len(payload) > _MAX_MESSAGE_BYTES:
            return False

        deadline = monotonic() + _CONNECT_TOTAL_SECONDS
        while monotonic() < deadline:
            socket = QLocalSocket(self)
            socket.connectToServer(self._server_name)
            if socket.waitForConnected(_CONNECT_ATTEMPT_MS):
                written = socket.write(payload)
                if written < 0:
                    socket.abort()
                    return False
                socket.flush()
                if socket.bytesToWrite() > 0 and not socket.waitForBytesWritten(800):
                    socket.abort()
                    return False
                socket.disconnectFromServer()
                return True
            socket.abort()
            sleep(0.06)
        return False

    def close(self) -> None:
        """외부 입구, endpoint, 단일 실행 잠금을 순서대로 닫는다."""
        self._remove_published_endpoint()
        if self._browser_server.isListening():
            self._browser_server.close()
        for socket in self._browser_server.findChildren(QTcpSocket):
            socket.abort()
        self._browser_socket_buffers.clear()
        if self._server.isListening():
            self._server.close()
        if self._lock_file.isLocked():
            self._lock_file.unlock()

    def _start_browser_fast_path(self) -> bool:
        """RR-V 실행 중 브라우저용 loopback 빠른 입구를 연다.

        포트가 다른 프로그램에 의해 이미 사용 중이면 조용히 포기한다. 확장은
        이 경우 기존 Native Messaging으로 자동 폴백한다.
        """
        if self._browser_server.isListening():
            return True
        try:
            localhost = QHostAddress(QHostAddress.SpecialAddress.LocalHost)
            return bool(
                self._browser_server.listen(localhost, _BROWSER_FAST_PATH_PORT)
            )
        except (AttributeError, TypeError):
            return False

    def _publish_endpoint(self) -> None:
        """Native Messaging host가 Qt 없이 로컬 파이프로 바로 전달할 주소를 기록한다."""
        try:
            RRV_EXTERNAL_URL_ENDPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
            endpoint = {
                "version": _PROTOCOL_VERSION,
                "pid": os.getpid(),
                "server_name": self._server.serverName(),
                "full_server_name": self._server.fullServerName(),
            }
            temp_path = RRV_EXTERNAL_URL_ENDPOINT_PATH.with_suffix(".tmp")
            temp_path.write_text(
                json.dumps(endpoint, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            os.replace(temp_path, RRV_EXTERNAL_URL_ENDPOINT_PATH)
        except OSError:
            # 이 파일은 브라우저 전송 고속화용 힌트다. 기록 실패 시에도
            # DEV11의 기존 단일 실행/URL 전달 기능 자체는 계속 사용할 수 있다.
            pass

    def _remove_published_endpoint(self) -> None:
        """현재 프로세스가 기록한 endpoint만 제거한다."""
        try:
            if not RRV_EXTERNAL_URL_ENDPOINT_PATH.is_file():
                return
            data = json.loads(
                RRV_EXTERNAL_URL_ENDPOINT_PATH.read_text(encoding="utf-8")
            )
            if not isinstance(data, dict) or int(data.get("pid", -1)) != os.getpid():
                return
            RRV_EXTERNAL_URL_ENDPOINT_PATH.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

    # ------------------------------------------------------------------
    # DEV11 QLocalServer / single-instance channel
    # ------------------------------------------------------------------
    def _accept_pending_connections(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            key = id(socket)
            self._socket_buffers[key] = bytearray()
            socket.readyRead.connect(
                lambda socket=socket: self._read_socket(socket)
            )
            socket.disconnected.connect(
                lambda socket=socket: self._socket_disconnected(socket)
            )
            self._read_socket(socket)

    def _read_socket(self, socket: QLocalSocket) -> None:
        key = id(socket)
        buffer = self._socket_buffers.setdefault(key, bytearray())
        buffer.extend(bytes(socket.readAll()))
        if len(buffer) > _MAX_MESSAGE_BYTES:
            self._socket_buffers.pop(key, None)
            socket.abort()
            return

        while b"\n" in buffer:
            line, _, remainder = bytes(buffer).partition(b"\n")
            buffer.clear()
            buffer.extend(remainder)
            request = _decode_request(line)
            if request is None:
                continue
            urls, activate, source = request
            self.request_received.emit(urls, activate, source)

    def _socket_disconnected(self, socket: QLocalSocket) -> None:
        self._socket_buffers.pop(id(socket), None)
        socket.deleteLater()

    # ------------------------------------------------------------------
    # Browser loopback fast path
    # ------------------------------------------------------------------
    def _accept_browser_fast_path_connections(self) -> None:
        while self._browser_server.hasPendingConnections():
            socket = self._browser_server.nextPendingConnection()
            if socket is None:
                continue
            key = id(socket)
            self._browser_socket_buffers[key] = bytearray()
            socket.readyRead.connect(
                lambda socket=socket: self._read_browser_fast_path(socket)
            )
            socket.disconnected.connect(
                lambda socket=socket: self._browser_fast_path_disconnected(socket)
            )
            self._read_browser_fast_path(socket)

    def _read_browser_fast_path(self, socket: QTcpSocket) -> None:
        key = id(socket)
        buffer = self._browser_socket_buffers.setdefault(key, bytearray())
        buffer.extend(bytes(socket.readAll()))
        if len(buffer) > _MAX_HTTP_HEADER_BYTES + _MAX_HTTP_BODY_BYTES:
            self._send_browser_http_json(
                socket,
                413,
                {"ok": False, "error": "요청이 너무 큽니다."},
            )
            return

        header_end = buffer.find(b"\r\n\r\n")
        if header_end < 0:
            if len(buffer) > _MAX_HTTP_HEADER_BYTES:
                self._send_browser_http_json(
                    socket,
                    431,
                    {"ok": False, "error": "HTTP 헤더가 너무 큽니다."},
                )
            return

        try:
            header_text = bytes(buffer[:header_end]).decode("iso-8859-1")
        except UnicodeDecodeError:
            self._send_browser_http_json(
                socket,
                400,
                {"ok": False, "error": "HTTP 요청을 읽지 못했습니다."},
            )
            return

        lines = header_text.split("\r\n")
        if not lines:
            self._send_browser_http_json(socket, 400, {"ok": False})
            return
        request_parts = lines[0].split(" ", 2)
        if len(request_parts) < 2:
            self._send_browser_http_json(socket, 400, {"ok": False})
            return
        method = request_parts[0].upper()
        route = request_parts[1].split("?", 1)[0]

        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            headers[name.strip().casefold()] = value.strip()

        origin = headers.get("origin", "").rstrip("/")
        if origin and origin != _BROWSER_EXTENSION_ORIGIN:
            self._send_browser_http_json(
                socket,
                403,
                {"ok": False, "error": "허용되지 않은 브라우저 요청입니다."},
                allow_origin=False,
            )
            return

        if method == "OPTIONS":
            self._send_browser_http_json(
                socket,
                204,
                None,
                allow_origin=True,
            )
            return

        if method != "POST" or route != _BROWSER_FAST_PATH_ROUTE:
            self._send_browser_http_json(
                socket,
                404,
                {"ok": False, "error": "지원하지 않는 요청입니다."},
            )
            return

        if headers.get("x-rrv-bridge-key", "") != _BROWSER_FAST_PATH_TOKEN:
            self._send_browser_http_json(
                socket,
                403,
                {"ok": False, "error": "브라우저 연결 키가 올바르지 않습니다."},
            )
            return

        try:
            content_length = int(headers.get("content-length", "0") or "0")
        except ValueError:
            content_length = -1
        if content_length < 0 or content_length > _MAX_HTTP_BODY_BYTES:
            self._send_browser_http_json(
                socket,
                413,
                {"ok": False, "error": "요청 본문 크기가 올바르지 않습니다."},
            )
            return

        body_start = header_end + 4
        if len(buffer) < body_start + content_length:
            return
        body = bytes(buffer[body_start : body_start + content_length])
        self._handle_browser_fast_path_payload(socket, body)

    def _handle_browser_fast_path_payload(
        self,
        socket: QTcpSocket,
        body: bytes,
    ) -> None:
        try:
            message = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_browser_http_json(
                socket,
                400,
                {"ok": False, "error": "브라우저 요청 JSON을 읽지 못했습니다."},
            )
            return
        if not isinstance(message, dict):
            self._send_browser_http_json(socket, 400, {"ok": False})
            return

        action = str(message.get("action", "send_urls")).strip().lower()
        if action not in {"send_url", "send_urls", "enqueue"}:
            self._send_browser_http_json(
                socket,
                400,
                {"ok": False, "error": "지원하지 않는 브라우저 동작입니다."},
            )
            return

        candidates: list[object] = []
        raw_urls = message.get("urls")
        if isinstance(raw_urls, list):
            candidates.extend(raw_urls)
        raw_url = message.get("url")
        if raw_url:
            candidates.append(raw_url)
        urls = extract_external_urls([str(value) for value in candidates])[:_MAX_URLS]
        if not urls:
            self._send_browser_http_json(
                socket,
                200,
                {"ok": False, "count": 0, "error": "전달할 주소가 없습니다."},
            )
            return

        collections = probable_collection_urls(urls)
        collection_keys = {url.casefold() for url in collections}
        direct_urls = [url for url in urls if url.casefold() not in collection_keys]
        if not direct_urls:
            self._send_browser_http_json(
                socket,
                200,
                {
                    "ok": False,
                    "count": 0,
                    "skipped": len(collections),
                    "error": "재생목록/채널 주소는 목록 확인을 사용해 주세요.",
                },
            )
            return

        self.request_received.emit(direct_urls, False, "browser")
        self._send_browser_http_json(
            socket,
            200,
            {
                "ok": True,
                "count": len(direct_urls),
                "skipped": len(collections),
                "delivery": "loopback",
            },
        )

    def _send_browser_http_json(
        self,
        socket: QTcpSocket,
        status_code: int,
        payload: dict[str, object] | None,
        *,
        allow_origin: bool = True,
    ) -> None:
        reasons = {
            200: "OK",
            204: "No Content",
            400: "Bad Request",
            403: "Forbidden",
            404: "Not Found",
            413: "Payload Too Large",
            431: "Request Header Fields Too Large",
        }
        body = b""
        if payload is not None:
            body = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")

        headers = [
            f"HTTP/1.1 {status_code} {reasons.get(status_code, 'OK')}",
            "Connection: close",
            "Cache-Control: no-store",
            "Content-Type: application/json; charset=utf-8",
            f"Content-Length: {len(body)}",
        ]
        if allow_origin:
            headers.extend(
                [
                    f"Access-Control-Allow-Origin: {_BROWSER_EXTENSION_ORIGIN}",
                    "Access-Control-Allow-Methods: POST, OPTIONS",
                    "Access-Control-Allow-Headers: Content-Type, X-RRV-Bridge-Key",
                ]
            )
        response = ("\r\n".join(headers) + "\r\n\r\n").encode("ascii") + body
        socket.write(response)
        socket.flush()
        socket.disconnectFromHost()

    def _browser_fast_path_disconnected(self, socket: QTcpSocket) -> None:
        self._browser_socket_buffers.pop(id(socket), None)
        socket.deleteLater()
