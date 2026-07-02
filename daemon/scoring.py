from __future__ import annotations

import math
from difflib import SequenceMatcher
from typing import Any

from .models import Candidate, CommandContext
from .safety import SafetyPolicy


def _success_rate(row: dict[str, Any]) -> float:
    success = int(row.get("success_count") or 0)
    fail = int(row.get("fail_count") or 0)
    total = success + fail
    if total == 0:
        return 0.5
    return success / total


def row_to_candidate(row: dict[str, Any]) -> Candidate:
    return Candidate(full_command=str(row["command_text"]), source="history", metadata=row)


def score_candidate(candidate: Candidate, context: CommandContext, safety: SafetyPolicy) -> float:
    command = " ".join(candidate.full_command.strip().split())
    buffer = " ".join(context.buffer.strip().split())
    row = candidate.metadata
    score = float(candidate.base_score)

    if not command.startswith(buffer):
        ratio = SequenceMatcher(None, buffer, command[: max(len(buffer), 1)]).ratio()
        score += ratio * 20
    else:
        score += 30

    if row.get("cwd") and row.get("cwd") == context.cwd:
        score += 40
    if row.get("project_root") and row.get("project_root") == context.project_root:
        score += 30
    if row.get("git_branch") and row.get("git_branch") == context.git_branch:
        score += 10

    used_count = int(row.get("used_count") or 0)
    score += min(math.log1p(used_count) * 8, 20)
    score += _success_rate(row) * 15
    score += min(int(row.get("accepted_count") or 0) * 5, 25)
    score -= min(int(row.get("ignored_count") or 0) * 3, 15)
    if int(row.get("fail_count") or 0) > int(row.get("success_count") or 0):
        score -= 20

    risk = safety.classify(command, buffer=buffer, root_mode=context.root_mode, source=candidate.source)
    if risk.risk == "dangerous":
        score -= 100
    elif risk.risk == "caution":
        score -= 20 if context.root_mode else 10

    return max(0.0, score)


def score_to_confidence(score: float) -> float:
    # 0..120-ish score -> 0..1 confidence. Conservative curve for early MVP.
    return max(0.0, min(0.99, score / 120.0))


def rank_candidates(candidates: list[Candidate], context: CommandContext, safety: SafetyPolicy, limit: int = 20) -> list[tuple[Candidate, float]]:
    ranked: list[tuple[Candidate, float]] = []
    for candidate in candidates:
        if not candidate.full_command.strip() or candidate.full_command.strip() == context.buffer.strip():
            continue
        if not safety.is_allowed_suggestion(candidate.full_command, buffer=context.buffer, root_mode=context.root_mode, source=candidate.source):
            continue
        ranked.append((candidate, score_candidate(candidate, context, safety)))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked[:limit]
