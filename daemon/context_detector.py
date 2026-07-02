from __future__ import annotations

import os
import shutil
from pathlib import Path

from .config import Settings
from .history_store import HistoryStore
from .models import CommandContext, PredictRequest
from .project_detector import detect_project, get_git_branch

NATURAL_LANGUAGE_STARTS = {
    "как", "что", "почему", "зачем", "объясни", "расскажи", "можешь", "сколько", "где",
    "how", "what", "why", "explain", "tell", "can", "could", "please", "когда",
}

SHELL_CHARS = set("-/._=$:{[]}|><&;*~")


def first_token(buffer: str) -> str:
    stripped = buffer.strip()
    if not stripped:
        return ""
    return stripped.split()[0]


def is_command_like(buffer: str, settings: Settings, history: HistoryStore | None = None) -> bool:
    stripped = buffer.strip()
    if len(stripped) < settings.prediction.min_buffer_length:
        return False
    token = first_token(stripped)
    if not token:
        return False
    lowered = token.lower()
    if lowered in NATURAL_LANGUAGE_STARTS:
        return False
    if any(ch in stripped for ch in SHELL_CHARS):
        return True
    if shutil.which(token) is not None:
        return True
    if token in settings.known_commands:
        return True
    if any(cmd.startswith(token) or token.startswith(cmd[: max(2, min(len(cmd), 4))]) for cmd in settings.known_commands):
        return True
    if history:
        rows = history.search_prefix(stripped, cwd=None, project_root=None, git_branch=None, limit=3)
        if rows:
            return True
    return False


def build_context(request: PredictRequest, settings: Settings, history: HistoryStore | None = None) -> CommandContext:
    cwd = request.cwd or os.getcwd()
    try:
        cwd = str(Path(cwd).resolve())
    except Exception:
        cwd = os.getcwd()
    cursor = request.cursor if request.cursor is not None else len(request.buffer)
    project = detect_project(cwd)
    branch = get_git_branch(cwd)
    recent = history.recent_commands(cwd=cwd, project_root=project.project_root, limit=settings.ai.max_recent_commands) if history else []
    uid = request.effective_uid
    if uid is None:
        try:
            uid = os.geteuid()
        except AttributeError:
            uid = None
    root_mode = request.root_mode or uid == 0 or os.getenv("TERM_COPILOT_ROOT_MODE") == "1"
    return CommandContext(
        buffer=request.buffer[:cursor],
        cursor=cursor,
        cwd=cwd,
        shell=request.shell,
        first_token=first_token(request.buffer[:cursor]),
        project_root=project.project_root,
        git_branch=branch,
        project=project,
        user=request.user or os.getenv("USER"),
        effective_uid=uid,
        original_user=request.original_user or os.getenv("SUDO_USER") or os.getenv("TERM_COPILOT_USER"),
        root_mode=root_mode,
        recent_commands=recent,
    )
