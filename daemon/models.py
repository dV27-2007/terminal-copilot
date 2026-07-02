from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Risk = Literal["safe", "caution", "dangerous"]


@dataclass(slots=True)
class PredictRequest:
    buffer: str
    cursor: int | None = None
    cwd: str | None = None
    shell: str = "zsh"
    user: str | None = None
    effective_uid: int | None = None
    original_user: str | None = None
    root_mode: bool = False


@dataclass(slots=True)
class ProjectProfile:
    project_root: str | None = None
    project_type: str = "unknown"
    docker_services: list[str] = field(default_factory=list)
    package_scripts: list[str] = field(default_factory=list)
    make_targets: list[str] = field(default_factory=list)
    pytest_paths: list[str] = field(default_factory=list)
    detected_tools: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CommandContext:
    buffer: str
    cursor: int
    cwd: str
    shell: str
    first_token: str
    project_root: str | None
    git_branch: str | None
    project: ProjectProfile
    user: str | None = None
    effective_uid: int | None = None
    original_user: str | None = None
    root_mode: bool = False
    recent_commands: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Candidate:
    full_command: str
    source: str
    base_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Suggestion:
    ghost_text: str = ""
    full_command: str = ""
    source: str = "none"
    confidence: float = 0.0
    risk: Risk = "safe"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ghost_text": self.ghost_text,
            "full_command": self.full_command,
            "source": self.source,
            "confidence": round(float(self.confidence), 4),
            "risk": self.risk,
            "reason": self.reason,
        }


def empty_suggestion(reason: str = "") -> Suggestion:
    return Suggestion(reason=reason)
