from __future__ import annotations

import json
import os
import socket
import stat
import threading
from pathlib import Path
from typing import Any

from .models import PredictRequest, empty_suggestion
from .predictor import Predictor

PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 8192
MAX_RESPONSE_BYTES = 8192
REQUEST_TIMEOUT_SECONDS = 0.5


class IPCError(Exception):
    pass


class RequestTooLarge(IPCError):
    pass


def unix_socket_supported() -> bool:
    return os.name == "posix" and hasattr(socket, "AF_UNIX")


def _error_response(reason: str) -> dict[str, Any]:
    response = empty_suggestion(reason).to_dict()
    response["error"] = reason
    return response


def _coerce_cursor(value: Any) -> int | None:
    if value is None:
        return None
    try:
        cursor = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, cursor)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def predict_from_payload(predictor: Predictor, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _error_response("request must be a JSON object")

    version = payload.get("protocol_version", PROTOCOL_VERSION)
    if version != PROTOCOL_VERSION:
        return _error_response("unsupported protocol_version")

    buffer = payload.get("buffer", "")
    if not isinstance(buffer, str):
        return _error_response("buffer must be a string")

    cwd = payload.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        return _error_response("cwd must be a string")

    shell = payload.get("shell", "zsh")
    if not isinstance(shell, str):
        shell = "zsh"

    request = PredictRequest(
        buffer=buffer,
        cursor=_coerce_cursor(payload.get("cursor")),
        cwd=cwd,
        shell=shell,
        user=payload.get("user") if isinstance(payload.get("user"), str) else None,
        effective_uid=_coerce_cursor(payload.get("effective_uid")),
        original_user=payload.get("original_user") if isinstance(payload.get("original_user"), str) else None,
        root_mode=_coerce_bool(payload.get("root_mode", False)),
    )
    try:
        return predictor.predict(request).to_dict()
    except Exception:
        return _error_response("prediction failed")


def _read_json_line(conn: socket.socket, *, max_bytes: int, timeout: float) -> bytes:
    conn.settimeout(timeout)
    chunks: list[bytes] = []
    total = 0
    while True:
        try:
            chunk = conn.recv(min(4096, max_bytes + 1 - total))
        except (TimeoutError, socket.timeout) as exc:
            raise IPCError("request timed out") from exc
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise RequestTooLarge("request too large")
        if b"\n" in chunk:
            before_newline, _ = chunk.split(b"\n", 1)
            chunks.append(before_newline)
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _encode_response(response: dict[str, Any]) -> bytes:
    return (json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _prepare_socket_path(socket_path: Path) -> None:
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if not socket_path.exists():
        return
    mode = socket_path.stat().st_mode
    if not stat.S_ISSOCK(mode):
        raise OSError(f"refusing to replace non-socket path: {socket_path}")
    try:
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(0.05)
        probe.connect(str(socket_path))
    except OSError:
        probe.close()
        socket_path.unlink()
    else:
        probe.close()
        raise OSError(f"socket already in use: {socket_path}")


class UnixSocketPredictionServer:
    def __init__(
        self,
        predictor: Predictor,
        socket_path: str,
        *,
        max_request_bytes: int = MAX_REQUEST_BYTES,
        request_timeout: float = REQUEST_TIMEOUT_SECONDS,
    ):
        if not unix_socket_supported():
            raise OSError("Unix sockets are not supported on this platform")
        self.predictor = predictor
        self.socket_path = Path(socket_path).expanduser()
        self.max_request_bytes = max_request_bytes
        self.request_timeout = request_timeout
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        _prepare_socket_path(self.socket_path)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(self.socket_path))
            os.chmod(self.socket_path, 0o600)
            server.listen(16)
            server.settimeout(0.2)
        except Exception:
            server.close()
            raise
        self._socket = server

    def start_in_thread(self) -> threading.Thread:
        self.start()
        thread = threading.Thread(target=self.serve_forever, name="term-copilot-ipc", daemon=True)
        thread.start()
        self._thread = thread
        return thread

    def serve_forever(self) -> None:
        if self._socket is None:
            self.start()
        assert self._socket is not None
        while not self._stop.is_set():
            try:
                conn, _ = self._socket.accept()
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                if self._stop.is_set():
                    break
                continue
            threading.Thread(target=self._handle_connection, args=(conn,), daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        try:
            if self.socket_path.exists() and stat.S_ISSOCK(self.socket_path.stat().st_mode):
                self.socket_path.unlink()
        except OSError:
            pass

    def _handle_connection(self, conn: socket.socket) -> None:
        with conn:
            try:
                raw = _read_json_line(conn, max_bytes=self.max_request_bytes, timeout=self.request_timeout)
                if not raw:
                    response = _error_response("empty request")
                else:
                    payload = json.loads(raw.decode("utf-8"))
                    response = predict_from_payload(self.predictor, payload)
            except RequestTooLarge as exc:
                response = _error_response(str(exc))
            except json.JSONDecodeError:
                response = _error_response("invalid json")
            except UnicodeDecodeError:
                response = _error_response("request must be utf-8")
            except IPCError as exc:
                response = _error_response(str(exc))
            except Exception:
                response = _error_response("ipc request failed")

            try:
                conn.sendall(_encode_response(response))
            except OSError:
                pass


def request_prediction(
    socket_path: str,
    payload: dict[str, Any],
    *,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
) -> dict[str, Any]:
    if not unix_socket_supported():
        raise OSError("Unix sockets are not supported on this platform")
    request = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(Path(socket_path).expanduser()))
        client.sendall(request)
        raw = _read_json_line(client, max_bytes=max_response_bytes, timeout=timeout)
    return json.loads(raw.decode("utf-8"))
