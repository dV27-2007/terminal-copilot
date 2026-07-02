import os
from pathlib import Path

from daemon.config import Settings
from daemon.context_detector import is_command_like
from daemon.project_detector import detect_project


def test_natural_language_not_command_like():
    assert not is_command_like("как запустить backend", Settings())


def test_known_prefix_command_like():
    assert is_command_like("docker co", Settings())


def test_detect_project_context(tmp_path: Path):
    (tmp_path / "docker-compose.yml").write_text("services:\n  backend:\n    image: app\n  celery:\n    image: app\n")
    (tmp_path / "package.json").write_text('{"scripts":{"dev":"vite","build":"vite build"}}')
    (tmp_path / "tests").mkdir()
    profile = detect_project(str(tmp_path))
    assert profile.project_root == str(tmp_path)
    assert profile.docker_services == ["backend", "celery"]
    assert "dev" in profile.package_scripts
    assert "tests" in profile.pytest_paths
