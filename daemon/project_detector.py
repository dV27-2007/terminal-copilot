from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from .models import ProjectProfile

PROJECT_MARKERS = (
    ".git", "docker-compose.yml", "compose.yml", "compose.yaml", "package.json", "pyproject.toml",
    "requirements.txt", "pytest.ini", "setup.cfg", "manage.py", "Makefile", "main.py",
)


def find_project_root(cwd: str) -> str | None:
    path = Path(cwd).resolve()
    for current in [path, *path.parents]:
        if any((current / marker).exists() for marker in PROJECT_MARKERS):
            return str(current)
    return None


def get_git_branch(cwd: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=0.25,
            check=False,
        )
    except Exception:
        return None
    branch = proc.stdout.strip()
    if not branch or branch == "HEAD":
        return None
    return branch


def _parse_compose_services(root: Path) -> list[str]:
    services: set[str] = set()
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        path = root / name
        if not path.exists():
            continue
        try:
            lines = path.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        in_services = False
        service_indent: int | None = None
        for line in lines:
            if re.match(r"^services\s*:\s*$", line):
                in_services = True
                service_indent = None
                continue
            if not in_services:
                continue
            if line.strip().startswith("#") or not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            if service_indent is None and indent > 0:
                service_indent = indent
            if service_indent is not None and indent == service_indent:
                match = re.match(r"\s*([A-Za-z0-9_.-]+)\s*:\s*(?:#.*)?$", line)
                if match:
                    services.add(match.group(1))
            elif service_indent is not None and indent < service_indent and not line.startswith(" "):
                break
    return sorted(services)


def _parse_package_scripts(root: Path) -> list[str]:
    path = root / "package.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(errors="ignore"))
    except Exception:
        return []
    scripts = data.get("scripts", {})
    if not isinstance(scripts, dict):
        return []
    return sorted(str(k) for k in scripts.keys())


def _parse_make_targets(root: Path) -> list[str]:
    path = root / "Makefile"
    if not path.exists():
        return []
    targets: set[str] = set()
    try:
        for line in path.read_text(errors="ignore").splitlines():
            if line.startswith("\t") or line.strip().startswith("#"):
                continue
            match = re.match(r"^([A-Za-z0-9_.-]+)\s*:(?![=])", line)
            if match:
                targets.add(match.group(1))
    except OSError:
        return []
    return sorted(targets)


def _detect_pytest_paths(root: Path) -> list[str]:
    paths: list[str] = []
    for candidate in (root / "tests", root / "test", root / "tests" / "pytests", root / "tests" / "unittests", root / "tests" / "integration"):
        if candidate.exists() and candidate.is_dir():
            paths.append(str(candidate.relative_to(root)))
    if (root / "pytest.ini").exists() and "tests" not in paths and (root / "tests").exists():
        paths.insert(0, "tests")
    return paths


def detect_project(cwd: str) -> ProjectProfile:
    root_s = find_project_root(cwd)
    if not root_s:
        return ProjectProfile(project_root=None)
    root = Path(root_s)
    docker_services = _parse_compose_services(root)
    package_scripts = _parse_package_scripts(root)
    make_targets = _parse_make_targets(root)
    pytest_paths = _detect_pytest_paths(root)

    types: list[str] = []
    tools: set[str] = set()
    if docker_services:
        types.append("docker")
        tools.add("docker")
    if (root / "package.json").exists():
        types.append("node")
        tools.update(["npm", "pnpm", "yarn"])
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists() or (root / "setup.py").exists():
        types.append("python")
        tools.update(["python", "pip"])
    if pytest_paths or (root / "pytest.ini").exists():
        types.append("pytest")
        tools.add("pytest")
    if (root / "manage.py").exists():
        types.append("django")
    if (root / "main.py").exists() or (root / "app").exists():
        types.append("fastapi_or_python_app")
    if make_targets:
        types.append("make")
        tools.add("make")
    if (root / ".git").exists():
        types.append("git")
        tools.add("git")

    project_type = "_".join(types) if types else "generic_project"
    return ProjectProfile(
        project_root=root_s,
        project_type=project_type,
        docker_services=docker_services,
        package_scripts=package_scripts,
        make_targets=make_targets,
        pytest_paths=pytest_paths,
        detected_tools=sorted(tools),
    )
