from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .models import ProjectProfile

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

MAX_MARKER_BYTES = 256 * 1024
MAX_PROJECT_CACHE_SIZE = 128

COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
MAKE_FILES = ("Makefile", "makefile")
PYTEST_CONFIG_FILES = ("pytest.ini", "pyproject.toml", "setup.cfg")
PACKAGE_LOCKS = ("package-lock.json", "pnpm-lock.yaml", "yarn.lock")
SHALLOW_TEST_DIRS = (
    "tests",
    "test",
    "tests/unit",
    "tests/integration",
    "tests/e2e",
    "tests/functional",
)
PROJECT_MARKERS = (
    ".git",
    *COMPOSE_FILES,
    "package.json",
    *MAKE_FILES,
    "pyproject.toml",
    "pytest.ini",
    "setup.cfg",
    "requirements.txt",
    "manage.py",
    "setup.py",
    "tests",
)

_CACHE_LOCK = threading.RLock()
_PROJECT_CACHE: OrderedDict[str, tuple[str, ProjectProfile]] = OrderedDict()


def clear_project_cache() -> None:
    with _CACHE_LOCK:
        _PROJECT_CACHE.clear()


def project_cache_info() -> dict[str, int]:
    with _CACHE_LOCK:
        return {"size": len(_PROJECT_CACHE), "max_size": MAX_PROJECT_CACHE_SIZE}


def find_project_root(cwd: str) -> str | None:
    path = Path(cwd).resolve()
    for current in [path, *path.parents]:
        if any((current / marker).exists() for marker in PROJECT_MARKERS):
            return str(current)
    return None


def get_git_branch(cwd: str) -> str | None:
    root_s = find_project_root(cwd)
    if not root_s:
        return None
    git_path = Path(root_s) / ".git"
    head_path = git_path / "HEAD"
    if git_path.is_file():
        try:
            text = git_path.read_text(errors="ignore").strip()
        except OSError:
            return None
        match = re.match(r"gitdir:\s*(.+)", text)
        if not match:
            return None
        git_dir = Path(match.group(1))
        if not git_dir.is_absolute():
            git_dir = git_path.parent / git_dir
        head_path = git_dir / "HEAD"
    try:
        head = head_path.read_text(errors="ignore").strip()
    except OSError:
        return None
    if not head.startswith("ref: refs/heads/"):
        return None
    branch = head.removeprefix("ref: refs/heads/").strip()
    return branch or None


def _safe_read_text(path: Path, *, max_bytes: int = MAX_MARKER_BYTES) -> str | None:
    try:
        if not path.is_file() or path.stat().st_size > max_bytes:
            return None
        return path.read_text(errors="ignore")
    except OSError:
        return None


def _marker_paths(root: Path) -> list[Path]:
    candidates = [
        root / ".git",
        *(root / name for name in COMPOSE_FILES),
        root / "package.json",
        *(root / name for name in PACKAGE_LOCKS),
        *(root / name for name in MAKE_FILES),
        root / "pyproject.toml",
        root / "pytest.ini",
        root / "setup.cfg",
        root / "requirements.txt",
        root / "manage.py",
        root / "setup.py",
        root / "tests",
    ]
    return [path for path in candidates if path.exists()]


def _marker_signature(root: Path) -> tuple[str, list[str], dict[str, float]]:
    hasher = hashlib.sha256()
    marker_paths: list[str] = []
    marker_mtimes: dict[str, float] = {}
    for path in sorted(_marker_paths(root), key=lambda item: str(item.relative_to(root))):
        try:
            stat = path.stat()
        except OSError:
            continue
        rel = str(path.relative_to(root))
        marker_paths.append(rel)
        marker_mtimes[rel] = float(stat.st_mtime_ns)
        hasher.update(rel.encode("utf-8"))
        hasher.update(str(stat.st_mtime_ns).encode("ascii"))
        hasher.update(str(stat.st_size).encode("ascii"))
        hasher.update(b"d" if path.is_dir() else b"f")
    return hasher.hexdigest(), marker_paths, marker_mtimes


def _valid_service_name(value: Any) -> bool:
    return isinstance(value, str) and re.match(r"^[A-Za-z0-9_.-]+$", value) is not None


def _parse_compose_services_with_lines(text: str) -> list[str]:
    services: set[str] = set()
    in_services = False
    service_indent: int | None = None
    for line in text.splitlines():
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


def _parse_compose_services(root: Path) -> list[str]:
    services: set[str] = set()
    for name in COMPOSE_FILES:
        text = _safe_read_text(root / name)
        if text is None:
            continue
        if yaml is not None:
            try:
                data = yaml.safe_load(text) or {}
            except Exception:
                continue
            raw_services = data.get("services") if isinstance(data, dict) else None
            if isinstance(raw_services, dict):
                services.update(str(key) for key in raw_services.keys() if _valid_service_name(str(key)))
            continue
        services.update(_parse_compose_services_with_lines(text))
    return sorted(services)


def _parse_package(root: Path) -> tuple[list[str], list[str]]:
    text = _safe_read_text(root / "package.json")
    if text is None:
        return [], []
    try:
        data = json.loads(text)
    except Exception:
        return [], []
    scripts = data.get("scripts", {})
    script_names = sorted(str(key) for key in scripts.keys()) if isinstance(scripts, dict) else []

    managers = {"npm"}
    package_manager = data.get("packageManager")
    if isinstance(package_manager, str):
        if package_manager.startswith("pnpm@"):
            managers.add("pnpm")
        elif package_manager.startswith("yarn@"):
            managers.add("yarn")
    if (root / "pnpm-lock.yaml").exists():
        managers.add("pnpm")
    if (root / "yarn.lock").exists():
        managers.add("yarn")
    return script_names, sorted(managers)


def _parse_make_targets(root: Path) -> list[str]:
    targets: set[str] = set()
    for name in MAKE_FILES:
        text = _safe_read_text(root / name)
        if text is None:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if line.startswith("\t") or not stripped or stripped.startswith("#"):
                continue
            match = re.match(r"^([A-Za-z0-9_-][A-Za-z0-9_.-]*)\s*:(?![=:])", line)
            if not match:
                continue
            target = match.group(1)
            if target.startswith(".") or "%" in target:
                continue
            targets.add(target)
    return sorted(targets)


def _detect_pytest_paths(root: Path) -> list[str]:
    paths: list[str] = []
    for rel in SHALLOW_TEST_DIRS:
        candidate = root / rel
        if candidate.exists() and candidate.is_dir():
            paths.append(rel.rstrip("/") + "/")
    has_pytest_config = any((root / name).exists() for name in PYTEST_CONFIG_FILES)
    if has_pytest_config and "tests/" not in paths and (root / "tests").exists():
        paths.insert(0, "tests/")
    return sorted(dict.fromkeys(paths))


def _build_project_profile(root: Path, marker_hash: str, marker_paths: list[str], marker_mtimes: dict[str, float]) -> ProjectProfile:
    docker_services = _parse_compose_services(root)
    package_scripts, package_managers = _parse_package(root)
    make_targets = _parse_make_targets(root)
    pytest_paths = _detect_pytest_paths(root)

    types: list[str] = []
    tools: set[str] = set()
    if any((root / name).exists() for name in COMPOSE_FILES) or docker_services:
        types.append("docker")
        tools.add("docker")
    if (root / "package.json").exists():
        types.append("node")
        tools.update(package_managers or ["npm"])
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists() or (root / "setup.py").exists():
        types.append("python")
        tools.update(["python", "pip"])
    if pytest_paths or (root / "pytest.ini").exists():
        types.append("pytest")
        tools.add("pytest")
    if (root / "manage.py").exists():
        types.append("django")
    if make_targets:
        types.append("make")
        tools.add("make")
    if (root / ".git").exists():
        types.append("git")
        tools.add("git")

    project_types = sorted(dict.fromkeys(types))
    project_type = "_".join(project_types) if project_types else "generic_project"
    return ProjectProfile(
        project_root=str(root),
        project_type=project_type,
        project_types=project_types,
        marker_paths=marker_paths,
        marker_mtimes=marker_mtimes,
        marker_hash=marker_hash,
        docker_services=docker_services,
        package_scripts=package_scripts,
        make_targets=make_targets,
        pytest_paths=pytest_paths,
        detected_tools=sorted(tools),
    )


def detect_project(cwd: str) -> ProjectProfile:
    root_s = find_project_root(cwd)
    if not root_s:
        return ProjectProfile(project_root=None)
    root = Path(root_s)
    marker_hash, marker_paths, marker_mtimes = _marker_signature(root)

    with _CACHE_LOCK:
        cached = _PROJECT_CACHE.get(root_s)
        if cached and cached[0] == marker_hash:
            _PROJECT_CACHE.move_to_end(root_s)
            return cached[1]

    profile = _build_project_profile(root, marker_hash, marker_paths, marker_mtimes)
    with _CACHE_LOCK:
        _PROJECT_CACHE[root_s] = (marker_hash, profile)
        _PROJECT_CACHE.move_to_end(root_s)
        while len(_PROJECT_CACHE) > MAX_PROJECT_CACHE_SIZE:
            _PROJECT_CACHE.popitem(last=False)
    return profile
