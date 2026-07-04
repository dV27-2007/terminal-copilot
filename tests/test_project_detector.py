import os
import time
from pathlib import Path

from daemon.project_detector import clear_project_cache, detect_project, project_cache_info


def test_project_root_detection_from_git(tmp_path: Path):
    clear_project_cache()
    nested = tmp_path / "app" / "src"
    nested.mkdir(parents=True)
    (tmp_path / "app" / ".git").mkdir()

    profile = detect_project(str(nested))

    assert profile.project_root == str(tmp_path / "app")
    assert "git" in profile.project_types
    assert ".git" in profile.marker_paths


def test_project_root_detection_from_docker_compose(tmp_path: Path):
    clear_project_cache()
    nested = tmp_path / "repo" / "service"
    nested.mkdir(parents=True)
    (tmp_path / "repo" / "docker-compose.yml").write_text("services:\n  backend:\n    image: app\n")

    profile = detect_project(str(nested))

    assert profile.project_root == str(tmp_path / "repo")
    assert "docker" in profile.project_types


def test_docker_compose_service_parsing(tmp_path: Path):
    clear_project_cache()
    (tmp_path / "compose.yaml").write_text("services:\n  backend:\n    image: app\n  celery:\n    image: worker\n")

    profile = detect_project(str(tmp_path))

    assert profile.docker_services == ["backend", "celery"]
    assert "docker" in profile.detected_tools


def test_package_json_script_parsing_and_package_managers(tmp_path: Path):
    clear_project_cache()
    (tmp_path / "package.json").write_text('{"packageManager":"pnpm@9.0.0","scripts":{"dev":"vite","build":"vite build"}}')
    (tmp_path / "yarn.lock").write_text("")

    profile = detect_project(str(tmp_path))

    assert profile.package_scripts == ["build", "dev"]
    assert {"npm", "pnpm", "yarn"}.issubset(set(profile.detected_tools))


def test_makefile_target_parsing(tmp_path: Path):
    clear_project_cache()
    (tmp_path / "makefile").write_text(".PHONY: test\nbuild:\n\ttrue\ntest: build\n\tpytest\n")

    profile = detect_project(str(tmp_path))

    assert profile.make_targets == ["build", "test"]
    assert "make" in profile.detected_tools


def test_pytest_path_detection(tmp_path: Path):
    clear_project_cache()
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "tests" / "integration").mkdir(parents=True)

    profile = detect_project(str(tmp_path))

    assert "tests/" in profile.pytest_paths
    assert "tests/integration/" in profile.pytest_paths
    assert "pytest" in profile.detected_tools


def test_cache_reuse_when_markers_do_not_change(tmp_path: Path, monkeypatch):
    clear_project_cache()
    (tmp_path / "docker-compose.yml").write_text("services:\n  backend:\n    image: app\n")

    import daemon.project_detector as project_detector

    original = project_detector._parse_compose_services
    calls = {"count": 0}

    def counted(root: Path):
        calls["count"] += 1
        return original(root)

    monkeypatch.setattr(project_detector, "_parse_compose_services", counted)

    first = detect_project(str(tmp_path))
    second = detect_project(str(tmp_path))

    assert first is second
    assert calls["count"] == 1
    assert project_cache_info()["size"] == 1


def test_cache_invalidation_when_marker_changes(tmp_path: Path):
    clear_project_cache()
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services:\n  backend:\n    image: app\n")
    first = detect_project(str(tmp_path))

    compose.write_text("services:\n  api:\n    image: app\n")
    future = time.time() + 2
    os.utime(compose, (future, future))
    second = detect_project(str(tmp_path))

    assert first is not second
    assert second.docker_services == ["api"]


def test_broken_yaml_and_json_do_not_crash(tmp_path: Path):
    clear_project_cache()
    (tmp_path / "docker-compose.yml").write_text("services: [")
    (tmp_path / "package.json").write_text('{"scripts":')

    profile = detect_project(str(tmp_path))

    assert profile.project_root == str(tmp_path)
    assert profile.docker_services == []
    assert profile.package_scripts == []


def test_large_package_json_is_skipped_safely(tmp_path: Path):
    clear_project_cache()
    (tmp_path / "package.json").write_text(" " * (300 * 1024))

    profile = detect_project(str(tmp_path))

    assert profile.project_root == str(tmp_path)
    assert profile.package_scripts == []
