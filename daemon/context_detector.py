from __future__ import annotations

import os
import shutil
from difflib import SequenceMatcher
from pathlib import Path

from .config import Settings
from .history_store import HistoryStore
from .models import CommandContext, PredictRequest
from .project_detector import detect_project, get_git_branch

NATURAL_LANGUAGE_STARTS = {
    "как", "что", "почему", "зачем", "объясни", "расскажи", "можешь", "сколько", "где",
    "когда", "запусти", "покажи", "скажи", "помоги",
    "how", "what", "why", "explain", "tell", "can", "could", "please", "do",
    "does", "is", "are", "should", "when", "where", "who",
    "inchpes", "inch", "inchu", "vonc", "vor", "karox", "khndrum",
}

NATURAL_LANGUAGE_WORDS = NATURAL_LANGUAGE_STARTS | {
    "i", "you", "me", "my", "the", "a", "an", "to", "with", "if", "error",
    "run", "works", "working", "работает", "делать", "если", "не", "ошибка",
}

NATURAL_LANGUAGE_PHRASES = (
    ("how", "do", "i"),
    ("how", "to"),
    ("what", "is"),
    ("what", "are"),
    ("why", "is"),
    ("why", "does"),
    ("do", "i"),
    ("can", "you"),
    ("could", "you"),
    ("что", "делать"),
    ("как",),
    ("почему",),
    ("explain",),
    ("inchpes",),
    ("inchu",),
    ("vonc",),
)

KNOWN_MULTI_TOKEN_COMMANDS = (
    "docker compose",
    "docker-compose",
    "git checkout",
    "git switch",
    "git commit",
    "git status",
    "npm run",
    "pnpm run",
    "yarn run",
    "pytest tests",
    "python -m",
)

SHELL_CHARS = set("-/._=$:{[]}|><&;*~")


def first_token(buffer: str) -> str:
    stripped = buffer.strip()
    if not stripped:
        return ""
    return stripped.split()[0]


def _words(buffer: str) -> list[str]:
    return [part.strip(" \t\r\n?!.,:;\"'`()[]{}").lower() for part in buffer.split() if part.strip(" \t\r\n?!.,:;\"'`()[]{}")]


def _contains_cyrillic(value: str) -> bool:
    return any("\u0400" <= ch <= "\u04ff" for ch in value)


def _starts_with_phrase(words: list[str], phrase: tuple[str, ...]) -> bool:
    return len(words) >= len(phrase) and tuple(words[: len(phrase)]) == phrase


def _is_known_tool_token(token: str, settings: Settings) -> bool:
    return token in settings.known_commands or shutil.which(token) is not None


def _is_known_tool_prefix(token: str, settings: Settings) -> bool:
    if len(token) < 2:
        return False
    return any(command.startswith(token) for command in settings.known_commands)


def _is_close_tool_typo(token: str, settings: Settings) -> bool:
    if token in settings.typos:
        return True
    if len(token) < 4:
        return False
    return any(SequenceMatcher(None, token, command).ratio() >= 0.78 for command in settings.known_commands)


def _starts_with_known_multi_token(buffer: str) -> bool:
    lowered = " ".join(buffer.lower().split())
    if not lowered:
        return False
    return any(command.startswith(lowered) or lowered.startswith(command + " ") or lowered == command for command in KNOWN_MULTI_TOKEN_COMMANDS)


def looks_like_natural_language(buffer: str, settings: Settings | None = None) -> bool:
    stripped = buffer.strip()
    if not stripped:
        return False
    words = _words(stripped)
    if not words:
        return False

    token = words[0]
    has_shell_chars = any(ch in stripped for ch in SHELL_CHARS)
    known_first_token = False
    if settings:
        known_first_token = _is_known_tool_token(token, settings) or _is_known_tool_prefix(token, settings)

    if any(_starts_with_phrase(words, phrase) for phrase in NATURAL_LANGUAGE_PHRASES):
        return True
    if token in NATURAL_LANGUAGE_STARTS:
        return True
    if "?" in stripped and not has_shell_chars:
        return True
    if len(words) >= 3 and any(word in NATURAL_LANGUAGE_STARTS for word in words[1:]) and not has_shell_chars:
        return True
    if len(words) >= 3 and _contains_cyrillic(" ".join(words)) and not has_shell_chars and not _starts_with_known_multi_token(stripped):
        return True
    if len(words) >= 4 and not has_shell_chars and not known_first_token and any(word in NATURAL_LANGUAGE_WORDS for word in words):
        return True
    return False


def is_command_like(buffer: str, settings: Settings, history: HistoryStore | None = None) -> bool:
    stripped = buffer.strip()
    if len(stripped) < settings.prediction.min_buffer_length:
        return False
    token = first_token(stripped)
    if not token:
        return False
    lowered = token.lower()
    if looks_like_natural_language(stripped, settings):
        return False
    if _starts_with_known_multi_token(stripped):
        return True
    if _is_known_tool_token(lowered, settings):
        return True
    if _is_known_tool_prefix(lowered, settings):
        return True
    if _is_close_tool_typo(lowered, settings):
        return True
    if any(ch in stripped for ch in SHELL_CHARS):
        return True
    if history:
        rows = history.search_prefix(stripped, cwd=None, project_root=None, git_branch=None, limit=3)
        if rows:
            return True
        if history.has_first_token(lowered):
            return True
    return False


def build_context(request: PredictRequest, settings: Settings, history: HistoryStore | None = None) -> CommandContext:
    cwd = request.cwd or os.getcwd()
    try:
        cwd = str(Path(cwd).resolve())
    except Exception:
        cwd = os.getcwd()
    cursor = request.cursor if request.cursor is not None else len(request.buffer)
    cursor = max(0, min(cursor, len(request.buffer)))
    project = detect_project(cwd)
    branch = get_git_branch(cwd) if project.project_root and (Path(project.project_root) / ".git").exists() else None
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
