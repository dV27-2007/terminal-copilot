import importlib
import json
import os
import socket
import stat
import sys
from pathlib import Path

import pytest

from daemon.cache_store import CacheStore
from daemon.config import Settings
from daemon.history_store import HistoryStore
from daemon.ipc import UnixSocketPredictionServer, request_prediction, unix_socket_supported
from daemon.predictor import Predictor


def make_predictor(tmp_path: Path) -> Predictor:
    settings = Settings()
    settings.daemon.db_path = str(tmp_path / "history.sqlite3")
    settings.ai.enabled = False
    history = HistoryStore(settings.daemon.db_path)
    cache = CacheStore(settings.daemon.db_path)
    return Predictor(settings=settings, history=history, cache=cache)


def raw_socket_request(socket_path: Path, raw: bytes) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(1.0)
        client.connect(str(socket_path))
        client.sendall(raw)
        chunks = []
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
    return json.loads(b"".join(chunks).split(b"\n", 1)[0].decode("utf-8"))


@pytest.mark.skipif(not unix_socket_supported(), reason="Unix sockets are not available")
def test_successful_prediction_over_unix_socket(tmp_path: Path):
    predictor = make_predictor(tmp_path)
    predictor.record_command("docker compose up -d backend celery", cwd=str(tmp_path), exit_code=0, duration_ms=100)
    socket_path = tmp_path / "ipc" / "daemon.sock"
    server = UnixSocketPredictionServer(predictor, str(socket_path))
    server.start_in_thread()
    try:
        response = request_prediction(
            str(socket_path),
            {
                "protocol_version": 1,
                "buffer": "docker co",
                "cursor": 9,
                "cwd": str(tmp_path),
                "shell": "zsh",
                "root_mode": False,
            },
        )
    finally:
        server.stop()

    assert response["full_command"] == "docker compose up -d backend celery"
    assert response["ghost_text"].startswith("mpose")
    assert response["source"] == "history"
    assert response["risk"] == "safe"


@pytest.mark.skipif(not unix_socket_supported(), reason="Unix sockets are not available")
def test_invalid_json_request_returns_error(tmp_path: Path):
    socket_path = tmp_path / "daemon.sock"
    server = UnixSocketPredictionServer(make_predictor(tmp_path), str(socket_path))
    server.start_in_thread()
    try:
        response = raw_socket_request(socket_path, b"{not-json}\n")
    finally:
        server.stop()

    assert response["ghost_text"] == ""
    assert response["full_command"] == ""
    assert response["error"] == "invalid json"


@pytest.mark.skipif(not unix_socket_supported(), reason="Unix sockets are not available")
def test_oversized_request_returns_error(tmp_path: Path):
    socket_path = tmp_path / "daemon.sock"
    server = UnixSocketPredictionServer(make_predictor(tmp_path), str(socket_path), max_request_bytes=24)
    server.start_in_thread()
    try:
        response = raw_socket_request(socket_path, b'{"buffer":"' + b"x" * 128 + b'"}\n')
    finally:
        server.stop()

    assert response["ghost_text"] == ""
    assert response["full_command"] == ""
    assert response["error"] == "request too large"


@pytest.mark.skipif(not unix_socket_supported(), reason="Unix sockets are not available")
def test_socket_path_is_created_with_owner_only_permissions(tmp_path: Path):
    socket_path = tmp_path / "nested" / "daemon.sock"
    server = UnixSocketPredictionServer(make_predictor(tmp_path), str(socket_path))
    server.start_in_thread()
    try:
        assert socket_path.exists()
        assert stat.S_ISSOCK(socket_path.stat().st_mode)
        mode = stat.S_IMODE(os.stat(socket_path).st_mode)
        assert mode & 0o077 == 0
    finally:
        server.stop()


def test_http_predict_handler_still_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TERM_COPILOT_DB", str(tmp_path / "http.sqlite3"))
    sys.modules.pop("daemon.server", None)
    server = importlib.import_module("daemon.server")

    server.predictor.record_command("docker compose ps", cwd=str(tmp_path), exit_code=0, duration_ms=25)
    response = server.predict(server.PredictBody(buffer="docker co", cursor=9, cwd=str(tmp_path), shell="zsh"))

    assert response["full_command"] == "docker compose ps"
    assert response["ghost_text"] == "mpose ps"
    assert response["source"] == "history"
