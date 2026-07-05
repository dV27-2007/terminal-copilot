import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ZSH_PLUGIN = ROOT / "zsh" / "terminal-copilot.zsh"
BASH_PLUGIN = ROOT / "bash" / "terminal-copilot.bash"
FISH_PLUGIN = ROOT / "fish" / "terminal-copilot.fish"


def read_plugin(path: Path) -> str:
    return path.read_text()


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh is not available")
def test_zsh_predict_json_includes_root_mode_and_session_metadata(tmp_path: Path):
    env = dict(os.environ)
    env.update(
        {
            "TERM_COPILOT_ROOT_MODE": "1",
            "TERM_COPILOT_USER": "david",
            "TERM_COPILOT_HOME": "/home/david",
        }
    )
    env.pop("TERM_COPILOT_SOCKET", None)

    proc = subprocess.run(
        [
            "zsh",
            "-fc",
            "source zsh/terminal-copilot.zsh; _term_copilot_predict_json 'docker co' 9",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=2.0,
        check=False,
    )

    assert proc.returncode == 0
    assert proc.stderr == ""
    payload = json.loads(proc.stdout)
    assert payload["root_mode"] is True
    assert payload["original_user"] == "david"
    assert payload["term_copilot_home"] == "/home/david"
    assert payload["shell"] == "zsh"


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh is not available")
def test_zsh_event_json_includes_execution_and_root_metadata():
    env = dict(os.environ)
    env.update(
        {
            "TERM_COPILOT_ROOT_MODE": "1",
            "TERM_COPILOT_USER": "david",
            "TERM_COPILOT_HOME": "/home/david",
        }
    )

    proc = subprocess.run(
        [
            "zsh",
            "-fc",
            "source zsh/terminal-copilot.zsh; "
            "_term_copilot_event_json command_executed 'docker compose ps' 7 123 '' '' ''",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=2.0,
        check=False,
    )

    assert proc.returncode == 0
    assert proc.stderr == ""
    payload = json.loads(proc.stdout)
    assert payload["event"] == "command_executed"
    assert payload["command"] == "docker compose ps"
    assert payload["cwd"] == str(ROOT)
    assert payload["shell"] == "zsh"
    assert payload["exit_code"] == 7
    assert payload["duration_ms"] == 123
    assert payload["root_mode"] is True
    assert isinstance(payload["effective_uid"], int)
    assert payload["original_user"] == "david"
    assert payload["term_copilot_home"] == "/home/david"


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh is not available")
def test_zsh_accept_event_payload_uses_actual_accepted_command():
    proc = subprocess.run(
        [
            "zsh",
            "-fc",
            "source zsh/terminal-copilot.zsh; "
            "zle() { return 1; }; "
            "_term_copilot_post_event() { _term_copilot_event_json \"$@\"; }; "
            "TERM_COPILOT_LAST_FULL='docker compose ps'; "
            "TERM_COPILOT_LAST_BUFFER='docker co'; "
            "TERM_COPILOT_LAST_SOURCE='history'; "
            "BUFFER='docker co'; "
            "term-copilot-accept; "
            "print -r -- ''; "
            "print -r -- \"STATE:$TERM_COPILOT_LAST_FULL:$BUFFER:$CURSOR\"",
        ],
        cwd=ROOT,
        env=dict(os.environ),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=2.0,
        check=False,
    )

    assert proc.returncode == 0
    assert proc.stderr == ""
    json_line, state_line = proc.stdout.splitlines()
    payload = json.loads(json_line)
    assert payload["event"] == "suggestion_accepted"
    assert payload["suggestion"] == "docker compose ps"
    assert payload["buffer"] == "docker co"
    assert payload["source"] == "history"
    assert state_line == "STATE::docker compose ps:17"


def test_zsh_prediction_hot_path_is_socket_first_without_python():
    text = read_plugin(ZSH_PLUGIN)
    socket_start = text.index("_term_copilot_socket_json()")
    predict_start = text.index("_term_copilot_predict_transport()")
    event_start = text.index("_term_copilot_event_json()")
    socket_function = text[socket_start:predict_start]
    predict_function = text[predict_start:event_start]

    assert "python3" not in socket_function
    assert "zsocket" in socket_function
    assert predict_function.index("_term_copilot_socket_json") < predict_function.index("_term_copilot_http_json")
    assert "_term_copilot_is_root_mode && return 1" in predict_function


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh is not available")
def test_zsh_root_mode_without_socket_fails_without_http_fallback():
    env = dict(os.environ)
    env["TERM_COPILOT_ROOT_MODE"] = "1"
    env.pop("TERM_COPILOT_SOCKET", None)

    proc = subprocess.run(
        [
            "zsh",
            "-fc",
            "source zsh/terminal-copilot.zsh; "
            "_term_copilot_http_json() { print -r -- http-called; }; "
            "_term_copilot_predict_transport '{}'",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=2.0,
        check=False,
    )

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr == ""


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh is not available")
def test_zsh_root_mode_without_socket_does_not_post_events():
    env = dict(os.environ)
    env["TERM_COPILOT_ROOT_MODE"] = "1"
    env.pop("TERM_COPILOT_SOCKET", None)

    proc = subprocess.run(
        [
            "zsh",
            "-fc",
            "source zsh/terminal-copilot.zsh; "
            "_term_copilot_event_json() { print -r -- event-json-called; }; "
            "_term_copilot_post_event command_executed 'docker compose ps' 0 '' '' ''; "
            "print -r -- rc:$?",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=2.0,
        check=False,
    )

    assert proc.returncode == 0
    assert proc.stdout.strip() == "rc:1"
    assert proc.stderr == ""


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh is not available")
def test_zsh_root_mode_with_explicit_socket_uses_socket_not_http():
    env = dict(os.environ)
    env["TERM_COPILOT_ROOT_MODE"] = "1"
    env["TERM_COPILOT_SOCKET"] = "/tmp/term-copilot-test.sock"

    proc = subprocess.run(
        [
            "zsh",
            "-fc",
            "source zsh/terminal-copilot.zsh; "
            "_term_copilot_socket_json() { print -r -- socket-called; }; "
            "_term_copilot_http_json() { print -r -- http-called; }; "
            "_term_copilot_predict_transport '{}'",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=2.0,
        check=False,
    )

    assert proc.returncode == 0
    assert proc.stdout.strip() == "socket-called"
    assert proc.stderr == ""


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not available")
def test_bash_predict_json_includes_root_mode_and_session_metadata():
    env = dict(os.environ)
    env.update(
        {
            "TERM_COPILOT_ROOT_MODE": "1",
            "TERM_COPILOT_USER": "david",
            "TERM_COPILOT_HOME": "/home/david",
        }
    )
    env.pop("TERM_COPILOT_SOCKET", None)

    proc = subprocess.run(
        [
            "bash",
            "-c",
            "source bash/terminal-copilot.bash; __term_copilot_predict_json 'docker co' 9",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=2.0,
        check=False,
    )

    assert proc.returncode == 0
    assert proc.stderr == ""
    payload = json.loads(proc.stdout)
    assert payload["root_mode"] is True
    assert payload["original_user"] == "david"
    assert payload["term_copilot_home"] == "/home/david"
    assert payload["shell"] == "bash"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not available")
def test_bash_defaults_socket_for_user_shell(tmp_path: Path):
    env = dict(os.environ)
    env.pop("TERM_COPILOT_SOCKET", None)
    env.pop("TERM_COPILOT_ROOT_MODE", None)
    env.pop("TERM_COPILOT_HOME", None)
    env["HOME"] = str(tmp_path)

    proc = subprocess.run(
        [
            "bash",
            "-c",
            "source bash/terminal-copilot.bash; printf '%s' \"$TERM_COPILOT_SOCKET\"",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=2.0,
        check=False,
    )

    assert proc.returncode == 0
    assert proc.stderr == ""
    assert proc.stdout == str(tmp_path / ".cache" / "term-copilot" / "daemon.sock")


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not available")
def test_bash_root_mode_does_not_default_socket(tmp_path: Path):
    env = dict(os.environ)
    env.pop("TERM_COPILOT_SOCKET", None)
    env["TERM_COPILOT_ROOT_MODE"] = "1"
    env["HOME"] = str(tmp_path)

    proc = subprocess.run(
        [
            "bash",
            "-c",
            "source bash/terminal-copilot.bash; printf '%s' \"${TERM_COPILOT_SOCKET:-}\"",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=2.0,
        check=False,
    )

    assert proc.returncode == 0
    assert proc.stderr == ""
    assert proc.stdout == ""


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not available")
def test_bash_root_mode_without_socket_does_not_post_events():
    env = dict(os.environ)
    env.pop("TERM_COPILOT_SOCKET", None)
    env["TERM_COPILOT_ROOT_MODE"] = "1"

    proc = subprocess.run(
        [
            "bash",
            "-c",
            "source bash/terminal-copilot.bash; "
            "__term_copilot_post_json /events '{}'; "
            "printf 'rc:%s' \"$?\"",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=2.0,
        check=False,
    )

    assert proc.returncode == 0
    assert proc.stderr == ""
    assert proc.stdout == "rc:1"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not available")
def test_bash_event_json_includes_root_metadata():
    env = dict(os.environ)
    env.update(
        {
            "TERM_COPILOT_ROOT_MODE": "1",
            "TERM_COPILOT_USER": "david",
            "TERM_COPILOT_HOME": "/home/david",
        }
    )

    proc = subprocess.run(
        [
            "bash",
            "-c",
            "source bash/terminal-copilot.bash; __term_copilot_json_event command_executed 'docker compose ps' 3",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=2.0,
        check=False,
    )

    assert proc.returncode == 0
    assert proc.stderr == ""
    payload = json.loads(proc.stdout)
    assert payload["event"] == "command_executed"
    assert payload["command"] == "docker compose ps"
    assert payload["shell"] == "bash"
    assert payload["exit_code"] == 3
    assert payload["root_mode"] is True
    assert isinstance(payload["effective_uid"], int)
    assert payload["original_user"] == "david"
    assert payload["term_copilot_home"] == "/home/david"


def test_fish_adapter_file_exists_and_is_quiet():
    text = read_plugin(FISH_PLUGIN)

    assert FISH_PLUGIN.exists()
    assert "debug" not in text.lower()
    assert "terminal-copilot fish integration" in text
    assert "term_copilot_fish_accept" in text


def test_fish_adapter_has_safe_root_and_transport_guards():
    text = read_plugin(FISH_PLUGIN)

    assert "TERM_COPILOT_ROOT_MODE" in text
    assert 'not set -q TERM_COPILOT_SOCKET' in text
    assert 'if payload["root_mode"]' in text
    assert "AF_UNIX" in text
    assert "/predict" in text
    assert "/events" in text


def test_fish_adapter_does_not_auto_execute_suggestions():
    text = read_plugin(FISH_PLUGIN)

    assert "commandline --replace" in text
    assert "commandline -f execute" not in text
    assert "eval " not in text
    assert "fish_postexec" in text
    assert "suggestion_accepted" in text
    assert "suggestion_ignored" not in text


@pytest.mark.skipif(shutil.which("fish") is None, reason="fish is not available")
def test_fish_syntax_check_passes():
    proc = subprocess.run(
        ["fish", "-n", str(FISH_PLUGIN)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=2.0,
        check=False,
    )

    assert proc.returncode == 0
    assert proc.stderr == ""


def test_ignored_suggestion_limitation_is_documented():
    assert "does not yet reliably emit" in (ROOT / "docs" / "zsh_integration.md").read_text()
