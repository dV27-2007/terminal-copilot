from __future__ import annotations

import math
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from .models import Candidate, CommandContext
from .safety import SafetyPolicy

PREFIX_MATCH_WEIGHT = 40.0
FUZZY_MATCH_WEIGHT = 20.0
SAME_CWD_WEIGHT = 35.0
SAME_PROJECT_WEIGHT = 25.0
SAME_BRANCH_WEIGHT = 10.0
SUCCESS_RATE_WEIGHT = 20.0
PROJECT_RELEVANCE_WEIGHT = 18.0
SOURCE_RELIABILITY = {
    "history": 25.0,
    "project_context": 12.0,
    "cache": 8.0,
    "ai": -20.0,
}


def _success_rate(row: dict[str, Any]) -> float:
    success = int(row.get("success_count") or 0)
    fail = int(row.get("fail_count") or 0)
    total = success + fail
    if total == 0:
        return 0.5
    return success / total


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def _recency_score(row: dict[str, Any]) -> float:
    last_used = _parse_timestamp(row.get("last_used_at"))
    if not last_used:
        return 0.0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    age_days = max(0.0, (now - last_used).total_seconds() / 86400.0)
    if age_days <= 1:
        return 12.0
    if age_days <= 7:
        return 8.0
    if age_days <= 30:
        return 4.0
    return 0.0


def _frequency_score(row: dict[str, Any]) -> float:
    used_count = int(row.get("used_count") or 0)
    return min(math.log1p(used_count) * 7.0, 20.0)


def _accepted_score(row: dict[str, Any]) -> float:
    return min(int(row.get("accepted_count") or 0) * 8.0, 30.0)


def _ignored_penalty(row: dict[str, Any]) -> float:
    return min(int(row.get("ignored_count") or 0) * 6.0, 30.0)


def _failure_penalty(row: dict[str, Any]) -> float:
    success = int(row.get("success_count") or 0)
    fail = int(row.get("fail_count") or 0)
    penalty = 0.0
    if fail > success:
        penalty += 25.0
    if fail and int(row.get("exit_code") or 0) != 0:
        penalty += 10.0
    if fail and _recency_score(row) >= 8.0:
        penalty += 20.0
    return penalty


def _project_relevance_score(candidate: Candidate, context: CommandContext) -> float:
    if candidate.source == "project_context":
        return PROJECT_RELEVANCE_WEIGHT
    first = candidate.full_command.strip().split(maxsplit=1)[0] if candidate.full_command.strip() else ""
    if first and first in context.project.detected_tools:
        return PROJECT_RELEVANCE_WEIGHT * 0.5
    return 0.0


def _risk_penalty(command: str, buffer: str, context: CommandContext, safety: SafetyPolicy, source: str) -> float:
    risk = safety.classify(command, buffer=buffer, root_mode=context.root_mode, source=source)
    if risk.risk == "dangerous":
        return 10_000.0
    if risk.risk == "caution":
        return 65.0 if context.root_mode else 25.0
    if context.root_mode and source == "ai":
        return 25.0
    return 0.0


def row_to_candidate(row: dict[str, Any]) -> Candidate:
    return Candidate(full_command=str(row["command_text"]), source="history", metadata=row)


def score_candidate(candidate: Candidate, context: CommandContext, safety: SafetyPolicy) -> float:
    command = " ".join(candidate.full_command.strip().split())
    buffer = " ".join(context.buffer.strip().split())
    row = candidate.metadata
    score = float(candidate.base_score)

    if not command.startswith(buffer):
        ratio = SequenceMatcher(None, buffer, command[: max(len(buffer), 1)]).ratio()
        score += ratio * FUZZY_MATCH_WEIGHT
    else:
        score += PREFIX_MATCH_WEIGHT

    if row.get("cwd") and row.get("cwd") == context.cwd:
        score += SAME_CWD_WEIGHT
    if row.get("project_root") and row.get("project_root") == context.project_root:
        score += SAME_PROJECT_WEIGHT
    if row.get("git_branch") and row.get("git_branch") == context.git_branch:
        score += SAME_BRANCH_WEIGHT

    score += SOURCE_RELIABILITY.get(candidate.source, 0.0)
    score += _frequency_score(row)
    score += _recency_score(row)
    score += _success_rate(row) * SUCCESS_RATE_WEIGHT
    score += _accepted_score(row)
    score += _project_relevance_score(candidate, context)
    score -= _ignored_penalty(row)
    score -= _failure_penalty(row)

    if context.root_mode and command.split(maxsplit=1)[0] in {"rm", "chmod", "chown", "dd", "mkfs"}:
        score -= 20
    score -= _risk_penalty(command, buffer, context, safety, candidate.source)

    return max(0.0, score)


def score_to_confidence(score: float) -> float:
    return max(0.0, min(0.99, score / 180.0))


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
