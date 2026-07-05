from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Any

from .ai_client import AIClient
from .cache_store import CacheStore
from .config import Settings, load_settings
from .context_detector import build_context, is_command_like
from .history_store import HistoryStore
from .models import Candidate, CommandContext, PredictRequest, Suggestion, empty_suggestion
from .redactor import contains_secret
from .safety import SafetyPolicy
from .scoring import rank_candidates, row_to_candidate, score_to_confidence


def ghost_from_full(buffer: str, full_command: str) -> str:
    if full_command.startswith(buffer):
        return full_command[len(buffer):]
    normalized_buffer = " ".join(buffer.strip().split())
    normalized_full = " ".join(full_command.strip().split())
    if normalized_full.startswith(normalized_buffer):
        return normalized_full[len(normalized_buffer):]
    return ""


AI_INLINE_GRACE_SECONDS = 0.01
AI_BACKOFF_REASONS = {
    "ai timeout",
    "ai provider failed",
    "invalid ai response",
    "invalid ai json",
    "invalid ai confidence",
    "invalid ai risk",
    "missing ai command",
    "dangerous ai response",
    "unsafe ai command",
    "ai command is not a continuation",
}


@dataclass(slots=True)
class _AIRequestState:
    key: str
    context: CommandContext
    done: threading.Event
    suggestion: Suggestion | None = None
    thread: threading.Thread | None = None


class Predictor:
    def __init__(
        self,
        settings: Settings | None = None,
        history: HistoryStore | None = None,
        cache: CacheStore | None = None,
        ai_client: AIClient | None = None,
    ):
        self.settings = settings or load_settings()
        self.history = history or HistoryStore(self.settings.daemon.db_path)
        self.cache = cache or CacheStore(self.settings.daemon.db_path)
        self.safety = SafetyPolicy(self.settings.dangerous_patterns)
        self.ai_client = ai_client or AIClient.from_settings(self.settings)
        self._ai_lock = threading.RLock()
        self._ai_inflight: dict[str, _AIRequestState] = {}
        self._ai_backoff_until = 0.0
        self._ai_backoff_reason = ""

    def predict(self, request: PredictRequest) -> Suggestion:
        cursor = request.cursor if request.cursor is not None else len(request.buffer)
        cursor = max(0, min(cursor, len(request.buffer)))
        buffer = request.buffer[:cursor]
        if contains_secret(buffer):
            return empty_suggestion("buffer contains secret")
        if not is_command_like(buffer, self.settings, self.history):
            return empty_suggestion("not command-like")

        context = build_context(request, self.settings, self.history)

        local = self._local_candidates(context)
        ranked = rank_candidates(local, context, self.safety, limit=self.settings.prediction.max_candidates)
        if ranked:
            candidate, score = ranked[0]
            confidence = score_to_confidence(score)
            if confidence >= self.settings.prediction.local_confidence_threshold:
                suggestion = self._to_suggestion(context, candidate.full_command, candidate.source, confidence)
                if self._valid_suggestion(context, suggestion, source=candidate.source):
                    self.cache.save(context, suggestion)
                    return suggestion

        cache_candidates = self.cache.lookup_candidates(context, limit=self.settings.prediction.max_candidates)
        combined = self._dedupe(local + cache_candidates)
        ranked = rank_candidates(combined, context, self.safety, limit=self.settings.prediction.max_candidates)
        if ranked:
            for candidate, score in ranked:
                confidence = score_to_confidence(score)
                threshold = self.settings.prediction.cache_confidence_threshold if candidate.source == "cache" else 0.45
                if confidence >= threshold:
                    suggestion = self._to_suggestion(context, candidate.full_command, candidate.source, confidence)
                    if self._valid_suggestion(context, suggestion, source=candidate.source):
                        if candidate.source != "cache":
                            self.cache.save(context, suggestion)
                        return suggestion

        if self._should_call_ai(context, ranked):
            ai_state = self._schedule_ai(context)
            if ai_state and ai_state.done.wait(AI_INLINE_GRACE_SECONDS):
                ai_suggestion = ai_state.suggestion or empty_suggestion("ai pending")
                if self._valid_ai_result(context, ai_suggestion):
                    return ai_suggestion

        return empty_suggestion("no confident suggestion")

    def _local_candidates(self, context: CommandContext) -> list[Candidate]:
        rows = self.history.search_prefix(
            context.buffer,
            cwd=context.cwd,
            project_root=context.project_root,
            git_branch=context.git_branch,
            limit=50,
        )
        candidates = [row_to_candidate(row) for row in rows]
        candidates.extend(self._project_candidates(context))
        return self._dedupe(candidates)

    def _project_candidates(self, context: CommandContext) -> list[Candidate]:
        b = context.buffer.strip()
        p = context.project
        out: list[Candidate] = []
        if p.docker_services:
            templates = ["docker compose ps"]
            for service in p.docker_services[:8]:
                templates.extend(
                    [
                        f"docker compose logs -f {service}",
                        f"docker compose up -d {service}",
                        f"docker compose restart {service}",
                    ]
                )
            out.extend(Candidate(t, "project_context", base_score=65) for t in templates if t.startswith(b))
        if p.package_scripts:
            script_templates: list[str] = []
            if "npm" in p.detected_tools:
                script_templates.extend(f"npm run {script}" for script in p.package_scripts)
            if "pnpm" in p.detected_tools:
                script_templates.extend(f"pnpm run {script}" for script in p.package_scripts)
            if "yarn" in p.detected_tools:
                script_templates.extend(f"yarn {script}" for script in p.package_scripts)
            out.extend(Candidate(t, "project_context", base_score=60) for t in script_templates if t.startswith(b))
        if p.make_targets:
            out.extend(Candidate(f"make {target}", "project_context", base_score=58) for target in p.make_targets if f"make {target}".startswith(b))
        if p.pytest_paths:
            out.extend(Candidate(f"pytest {path} -q", "project_context", base_score=60) for path in p.pytest_paths if f"pytest {path} -q".startswith(b))
        return out

    @staticmethod
    def _dedupe(candidates: list[Candidate]) -> list[Candidate]:
        seen: set[str] = set()
        out: list[Candidate] = []
        for candidate in candidates:
            key = " ".join(candidate.full_command.strip().split())
            if key and key not in seen:
                seen.add(key)
                out.append(candidate)
        return out

    def _to_suggestion(self, context: CommandContext, full_command: str, source: str, confidence: float) -> Suggestion:
        ghost = ghost_from_full(context.buffer, full_command)
        if not ghost:
            return empty_suggestion("not a continuation")
        risk = self.safety.classify(full_command, buffer=context.buffer, root_mode=context.root_mode, source=source)
        return Suggestion(
            ghost_text=ghost,
            full_command=full_command,
            source=source,
            confidence=confidence,
            risk=risk.risk,
            reason=risk.reason,
        )

    def _valid_suggestion(self, context: CommandContext, suggestion: Suggestion, *, source: str) -> bool:
        if not suggestion.ghost_text or not suggestion.full_command:
            return False
        if contains_secret(suggestion.full_command):
            return False
        if not ghost_from_full(context.buffer, suggestion.full_command):
            return False
        if source == "ai" and not is_command_like(suggestion.full_command, self.settings, self.history):
            return False
        return self.safety.is_allowed_suggestion(suggestion.full_command, buffer=context.buffer, root_mode=context.root_mode, source=source)

    def _should_call_ai(self, context: CommandContext, ranked: list[tuple[Candidate, float]]) -> bool:
        if not self.settings.ai.enabled:
            return False
        if not self.ai_client.available():
            return False
        if self._ai_in_backoff():
            return False
        if len(context.buffer.strip()) < max(4, self.settings.prediction.min_buffer_length):
            return False
        if contains_secret(context.buffer):
            return False
        if ranked and score_to_confidence(ranked[0][1]) >= self.settings.prediction.local_confidence_threshold:
            return False
        safety = self.safety.classify(context.buffer, buffer=context.buffer, root_mode=context.root_mode, source="user")
        if safety.risk == "dangerous":
            return False
        if context.root_mode and safety.risk != "safe":
            return False
        return True

    def _valid_ai_result(self, context: CommandContext, suggestion: Suggestion) -> bool:
        return (
            self._valid_suggestion(context, suggestion, source="ai")
            and suggestion.confidence >= self.settings.prediction.ai_confidence_threshold
        )

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _ai_request_key(self, context: CommandContext) -> str:
        return self._hash_payload(
            {
                "buffer": " ".join(context.buffer.strip().split()),
                "cursor": context.cursor,
                "cwd": context.cwd,
                "project_root": context.project_root,
                "git_branch": context.git_branch,
                "shell": context.shell,
                "root_mode": bool(context.root_mode),
                "project_type": context.project.project_type,
                "project_types": context.project.project_types,
                "project_marker_hash": context.project.marker_hash,
                "project_tools": context.project.detected_tools,
                "docker_services": context.project.docker_services,
                "package_scripts": context.project.package_scripts,
                "make_targets": context.project.make_targets,
                "pytest_paths": context.project.pytest_paths,
            }
        )

    def _ai_in_backoff(self) -> bool:
        with self._ai_lock:
            return time.monotonic() < self._ai_backoff_until

    def _record_ai_backoff(self, reason: str) -> None:
        backoff_seconds = max(0.0, float(self.settings.ai.backoff_seconds))
        if backoff_seconds <= 0:
            return
        with self._ai_lock:
            self._ai_backoff_until = max(self._ai_backoff_until, time.monotonic() + backoff_seconds)
            self._ai_backoff_reason = reason

    def _schedule_ai(self, context: CommandContext) -> _AIRequestState | None:
        key = self._ai_request_key(context)
        max_in_flight = max(0, int(self.settings.ai.max_in_flight))
        if max_in_flight <= 0:
            return None
        with self._ai_lock:
            existing = self._ai_inflight.get(key)
            if existing:
                return existing
            if len(self._ai_inflight) >= max_in_flight:
                return None
            state = _AIRequestState(key=key, context=context, done=threading.Event())
            thread = threading.Thread(target=self._run_ai_request, args=(state,), name="term-copilot-ai", daemon=True)
            state.thread = thread
            self._ai_inflight[key] = state
            thread.start()
            return state

    def _run_ai_request(self, state: _AIRequestState) -> None:
        suggestion = empty_suggestion("ai pending")
        try:
            suggestion = self.ai_client.complete(state.context)
            if self._ai_request_key(state.context) == state.key and self._valid_ai_result(state.context, suggestion):
                self.cache.save(state.context, suggestion)
            elif suggestion.reason in AI_BACKOFF_REASONS:
                self._record_ai_backoff(suggestion.reason)
        except Exception:
            suggestion = empty_suggestion("ai provider failed")
            self._record_ai_backoff(suggestion.reason)
        finally:
            state.suggestion = suggestion
            state.done.set()
            with self._ai_lock:
                if self._ai_inflight.get(state.key) is state:
                    self._ai_inflight.pop(state.key, None)

    def wait_for_pending_ai(self, timeout: float = 1.0) -> None:
        deadline = time.monotonic() + timeout
        while True:
            with self._ai_lock:
                states = list(self._ai_inflight.values())
            if not states:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            for state in states:
                thread = state.thread
                if thread is not None:
                    thread.join(timeout=max(0.0, min(remaining, 0.05)))

    def record_command(self, command: str, *, cwd: str | None, exit_code: int | None, duration_ms: int | None, shell: str = "zsh") -> None:
        request = PredictRequest(buffer=command, cwd=cwd, shell=shell)
        context = build_context(request, self.settings, self.history)
        if contains_secret(command):
            return
        self.history.record_command(
            command,
            cwd=context.cwd,
            project_root=context.project_root,
            git_branch=context.git_branch,
            exit_code=exit_code,
            duration_ms=duration_ms,
        )
        self.cache.mark_execution(command, exit_code=exit_code)

    def mark_suggestion(self, full_command: str, *, accepted: bool) -> None:
        self.history.mark_suggestion(full_command, accepted=accepted)
        self.cache.mark(full_command, accepted=accepted)
