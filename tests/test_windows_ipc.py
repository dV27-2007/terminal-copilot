import subprocess
import sys
from pathlib import Path

import pytest

from daemon.windows_ipc import (
    WindowsNamedPipePredictionServer,
    default_pipe_name,
    normalize_pipe_name,
    pipe_client_name,
    pipe_response_from_payload,
    request_prediction_pipe,
    request_pipe,
    windows_named_pipe_supported,
)

ROOT = Path(__file__).resolve().parents[1]


def test_named_pipe_reports_unavailable_on_non_windows():
    assert windows_named_pipe_supported("linux") is False
    assert windows_named_pipe_supported("darwin") is False


def test_default_pipe_name_uses_env_override():
    env = {"TERM_COPILOT_PIPE": r"\\.\pipe\custom-term-copilot"}

    assert default_pipe_name(env=env) == r"\\.\pipe\custom-term-copilot"


def test_default_pipe_name_is_deterministic_with_fake_username_and_sid():
    assert default_pipe_name(env={}, username="David User") == r"\\.\pipe\term-copilot-David_User"
    assert default_pipe_name(env={}, sid="S-1-5-21-123-456") == r"\\.\pipe\term-copilot-S-1-5-21-123-456"


def test_pipe_name_normalization_and_client_name():
    assert normalize_pipe_name("term-copilot-david") == r"\\.\pipe\term-copilot-david"
    assert pipe_client_name(r"\\.\pipe\term-copilot-david") == "term-copilot-david"


def test_pipe_routes_suggestion_accepted_event():
    class FakePredictor:
        def __init__(self):
            self.marked = []

        def mark_suggestion(self, suggestion: str, *, accepted: bool):
            self.marked.append((suggestion, accepted))

    predictor = FakePredictor()

    response = pipe_response_from_payload(
        predictor,
        {
            "protocol_version": 1,
            "event": "suggestion_accepted",
            "suggestion": "docker compose ps",
            "shell": "powershell",
        },
    )

    assert response == {"ok": True}
    assert predictor.marked == [("docker compose ps", True)]


def test_pipe_rejects_unsupported_event_safely():
    class FakePredictor:
        def mark_suggestion(self, suggestion: str, *, accepted: bool):  # pragma: no cover - should not be called
            raise AssertionError("unexpected mark_suggestion call")

    response = pipe_response_from_payload(
        FakePredictor(),
        {
            "protocol_version": 1,
            "event": "suggestion_ignored",
            "suggestion": "docker compose ps",
        },
    )

    assert response == {"ok": False, "reason": "unsupported event"}


@pytest.mark.skipif(windows_named_pipe_supported(), reason="non-Windows behavior only")
def test_pipe_request_is_unavailable_on_non_windows():
    with pytest.raises(Exception, match="not supported"):
        request_prediction_pipe(r"\\.\pipe\term-copilot-test", {"protocol_version": 1, "buffer": ""})


@pytest.mark.skipif(windows_named_pipe_supported(), reason="non-Windows behavior only")
def test_generic_pipe_request_is_unavailable_on_non_windows():
    with pytest.raises(Exception, match="not supported"):
        request_pipe(
            r"\\.\pipe\term-copilot-test",
            {
                "protocol_version": 1,
                "event": "suggestion_accepted",
                "suggestion": "docker compose ps",
            },
        )


@pytest.mark.skipif(windows_named_pipe_supported(), reason="non-Windows behavior only")
def test_pipe_server_is_unavailable_on_non_windows():
    with pytest.raises(Exception, match="not supported"):
        WindowsNamedPipePredictionServer(object(), r"\\.\pipe\term-copilot-test")


def test_windows_validation_doc_exists_and_covers_required_shells():
    text = (ROOT / "docs" / "windows_validation.md").read_text()

    assert "Windows PowerShell 5.1" in text
    assert "PowerShell 7+" in text
    assert "Windows Terminal" in text
    assert "Administrator" in text


def test_windows_validation_doc_covers_transports_and_safety_limits():
    text = (ROOT / "docs" / "windows_validation.md").read_text()

    assert "Pipe-Only Accepted Event" in text
    assert "HTTP-Only Accepted Event" in text
    assert "HTTP Fallback Prediction" in text
    assert "no automatic execution" in text
    assert "secret-looking input rejection" in text
    assert "`command_executed`" in text
    assert "remains deferred" in text


def test_windows_pipe_benchmark_exists_and_exposes_expected_options():
    script = ROOT / "benchmarks" / "bench_windows_pipe.py"

    assert script.exists()
    help_proc = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5.0,
        check=False,
    )

    assert help_proc.returncode == 0
    assert "--pipe" in help_proc.stdout
    assert "--iterations" in help_proc.stdout


@pytest.mark.skipif(windows_named_pipe_supported(), reason="non-Windows behavior only")
def test_windows_pipe_benchmark_skips_gracefully_on_non_windows():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "benchmarks" / "bench_windows_pipe.py"), "--iterations", "1"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5.0,
        check=False,
    )

    assert proc.returncode == 0
    assert "skipping benchmark" in proc.stdout
    assert proc.stderr == ""
