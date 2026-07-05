import pytest

from daemon.windows_ipc import (
    WindowsNamedPipePredictionServer,
    default_pipe_name,
    normalize_pipe_name,
    pipe_client_name,
    request_prediction_pipe,
    windows_named_pipe_supported,
)


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


@pytest.mark.skipif(windows_named_pipe_supported(), reason="non-Windows behavior only")
def test_pipe_request_is_unavailable_on_non_windows():
    with pytest.raises(Exception, match="not supported"):
        request_prediction_pipe(r"\\.\pipe\term-copilot-test", {"protocol_version": 1, "buffer": ""})


@pytest.mark.skipif(windows_named_pipe_supported(), reason="non-Windows behavior only")
def test_pipe_server_is_unavailable_on_non_windows():
    with pytest.raises(Exception, match="not supported"):
        WindowsNamedPipePredictionServer(object(), r"\\.\pipe\term-copilot-test")
