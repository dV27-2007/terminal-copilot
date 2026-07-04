import os
from pathlib import Path

from daemon.config import Settings
from daemon.context_detector import is_command_like
from daemon.history_store import HistoryStore
from daemon.project_detector import clear_project_cache, detect_project


def test_natural_language_not_command_like():
    assert not is_command_like("как запустить backend", Settings())


def test_known_prefix_command_like():
    assert is_command_like("docker co", Settings())


def test_known_tool_command_like():
    assert is_command_like("pytest te", Settings())
    assert is_command_like("git ch", Settings())


def test_command_like_from_history_first_token(tmp_path: Path):
    history = HistoryStore(str(tmp_path / "history.sqlite3"))
    history.record_command("customctl deploy backend", cwd=str(tmp_path), exit_code=0)

    assert is_command_like("customctl sta", Settings(), history)


def test_multi_token_command_prefix_command_like():
    assert is_command_like("docker compose", Settings())
    assert is_command_like("docker compose lo", Settings())


def test_typo_known_tool_command_like_without_correction():
    assert is_command_like("dokcer co", Settings())


def test_english_natural_language_not_command_like():
    settings = Settings()

    assert not is_command_like("what is docker", settings)
    assert not is_command_like("how do I run tests", settings)
    assert not is_command_like("explain pytest error", settings)


def test_russian_and_mixed_natural_language_not_command_like():
    settings = Settings()

    assert not is_command_like("почему docker не работает", settings)
    assert not is_command_like("что делать если postgres не работает", settings)
    assert not is_command_like("docker почему не работает", settings)


def test_transliterated_question_not_command_like():
    assert not is_command_like("inchpes run tests", Settings())


def test_detect_project_context(tmp_path: Path):
    clear_project_cache()
    (tmp_path / "docker-compose.yml").write_text("services:\n  backend:\n    image: app\n  celery:\n    image: app\n")
    (tmp_path / "package.json").write_text('{"scripts":{"dev":"vite","build":"vite build"}}')
    (tmp_path / "tests").mkdir()
    profile = detect_project(str(tmp_path))
    assert profile.project_root == str(tmp_path)
    assert profile.docker_services == ["backend", "celery"]
    assert "dev" in profile.package_scripts
    assert "tests/" in profile.pytest_paths
