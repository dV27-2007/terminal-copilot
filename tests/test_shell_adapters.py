import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


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
