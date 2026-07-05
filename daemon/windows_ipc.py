from __future__ import annotations

import json
import os
import re
import sys
import threading
from multiprocessing.connection import Client, Connection, Listener
from typing import Any

from .ipc import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, REQUEST_TIMEOUT_SECONDS, predict_from_payload
from .models import empty_suggestion
from .predictor import Predictor

PIPE_PREFIX = "\\\\.\\pipe\\"
DEFAULT_PIPE_PREFIX = "term-copilot"


class WindowsPipeError(Exception):
    pass


class WindowsPipeUnavailable(WindowsPipeError):
    pass


def windows_named_pipe_supported(platform: str | None = None) -> bool:
    return (platform or sys.platform) == "win32"


def _sanitize_pipe_component(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return sanitized.strip("._-") or "user"


def default_pipe_name(
    *,
    env: dict[str, str] | None = None,
    username: str | None = None,
    sid: str | None = None,
) -> str:
    values = env if env is not None else os.environ
    override = values.get("TERM_COPILOT_PIPE")
    if override:
        return normalize_pipe_name(override)

    identity = sid or values.get("TERM_COPILOT_USER_SID")
    if not identity:
        identity = username or values.get("USERNAME") or values.get("USER") or "user"
    return normalize_pipe_name(f"{DEFAULT_PIPE_PREFIX}-{_sanitize_pipe_component(identity)}")


def normalize_pipe_name(pipe_name: str) -> str:
    if pipe_name.startswith(PIPE_PREFIX):
        return pipe_name
    return PIPE_PREFIX + pipe_name.lstrip("\\/")


def pipe_client_name(pipe_name: str) -> str:
    normalized = normalize_pipe_name(pipe_name)
    return normalized[len(PIPE_PREFIX) :]


def _encode_message(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _error_response(reason: str) -> dict[str, Any]:
    response = empty_suggestion(reason).to_dict()
    response["error"] = reason
    return response


def _decode_request(raw: bytes) -> Any:
    if len(raw) > MAX_REQUEST_BYTES:
        raise WindowsPipeError("request too large")
    return json.loads(raw.decode("utf-8"))


class WindowsNamedPipePredictionServer:
    def __init__(
        self,
        predictor: Predictor,
        pipe_name: str,
        *,
        max_request_bytes: int = MAX_REQUEST_BYTES,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        request_timeout: float = REQUEST_TIMEOUT_SECONDS,
    ):
        if not windows_named_pipe_supported():
            raise WindowsPipeUnavailable("Windows Named Pipes are not supported on this platform")
        self.predictor = predictor
        self.pipe_name = normalize_pipe_name(pipe_name)
        self.max_request_bytes = max_request_bytes
        self.max_response_bytes = max_response_bytes
        self.request_timeout = request_timeout
        self._listener: Listener | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._listener = Listener(self.pipe_name, family="AF_PIPE", backlog=16, authkey=None)

    def start_in_thread(self) -> threading.Thread:
        self.start()
        thread = threading.Thread(target=self.serve_forever, name="term-copilot-windows-pipe", daemon=True)
        thread.start()
        self._thread = thread
        return thread

    def serve_forever(self) -> None:
        if self._listener is None:
            self.start()
        assert self._listener is not None
        while not self._stop.is_set():
            try:
                conn = self._listener.accept()
            except (OSError, EOFError):
                if self._stop.is_set():
                    break
                continue
            threading.Thread(target=self._handle_connection, args=(conn,), daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
            self._listener = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _handle_connection(self, conn: Connection) -> None:
        try:
            if not conn.poll(self.request_timeout):
                response = _error_response("request timed out")
            else:
                raw = conn.recv_bytes(maxlength=self.max_request_bytes + 1)
                payload = _decode_request(raw)
                response = predict_from_payload(self.predictor, payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            response = _error_response("invalid json")
        except OSError:
            response = _error_response("request too large")
        except Exception:
            response = _error_response("pipe request failed")

        try:
            encoded = _encode_message(response)
            if len(encoded) <= self.max_response_bytes:
                conn.send_bytes(encoded)
            else:
                conn.send_bytes(_encode_message(_error_response("response too large")))
        except OSError:
            pass
        finally:
            conn.close()


def request_prediction_pipe(
    pipe_name: str,
    payload: dict[str, Any],
    *,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
) -> dict[str, Any]:
    if not windows_named_pipe_supported():
        raise WindowsPipeUnavailable("Windows Named Pipes are not supported on this platform")

    encoded = _encode_message(payload)
    if len(encoded) > MAX_REQUEST_BYTES:
        raise WindowsPipeError("request too large")

    conn = Client(normalize_pipe_name(pipe_name), family="AF_PIPE", authkey=None)
    try:
        conn.send_bytes(encoded)
        if not conn.poll(timeout):
            raise WindowsPipeError("request timed out")
        raw = conn.recv_bytes(maxlength=max_response_bytes)
        return json.loads(raw.decode("utf-8"))
    finally:
        conn.close()
