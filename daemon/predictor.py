from __future__ import annotations

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
        self.ai_client = ai_client or AIClient(enabled=self.settings.ai.enabled)

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
                return self._to_suggestion(context, candidate.full_command, candidate.source, confidence)

        cached = self.cache.lookup(context)
        if cached and cached.confidence >= self.settings.prediction.cache_confidence_threshold:
            if self._valid_suggestion(context, cached, source=cached.source):
                return cached

        if self._should_call_ai(context, ranked):
            ai_suggestion = self.ai_client.complete(context)
            if self._valid_suggestion(context, ai_suggestion, source="ai") and ai_suggestion.confidence >= self.settings.prediction.ai_confidence_threshold:
                self.cache.save(context, ai_suggestion)
                return ai_suggestion

        if ranked:
            candidate, score = ranked[0]
            confidence = score_to_confidence(score)
            if confidence >= 0.45:
                return self._to_suggestion(context, candidate.full_command, candidate.source, confidence)

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
            first = p.docker_services[0]
            templates = [
                f"docker compose logs -f {first}",
                f"docker compose up -d {' '.join(p.docker_services[:2])}",
                "docker compose ps",
                "docker compose build",
            ]
            out.extend(Candidate(t, "project_context", base_score=65) for t in templates if t.startswith(b))
        if p.package_scripts:
            out.extend(Candidate(f"npm run {script}", "project_context", base_score=60) for script in p.package_scripts if f"npm run {script}".startswith(b))
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
        return self.safety.is_allowed_suggestion(suggestion.full_command, buffer=context.buffer, root_mode=context.root_mode, source=source)

    def _should_call_ai(self, context: CommandContext, ranked: list[tuple[Candidate, float]]) -> bool:
        if not self.settings.ai.enabled:
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
        return True

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

    def mark_suggestion(self, full_command: str, *, accepted: bool) -> None:
        self.history.mark_suggestion(full_command, accepted=accepted)
        self.cache.mark(full_command, accepted=accepted)
