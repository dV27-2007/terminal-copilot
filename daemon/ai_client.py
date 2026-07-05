from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

from .models import CommandContext, Suggestion, empty_suggestion
from .redactor import contains_secret, redact_payload, redact_text


@dataclass(slots=True)
class AIProviderConfig:
    enabled: bool = False
    provider: str = "gemini"
    model: str = "gemini-1.5-flash"
    api_key_env: str = "GEMINI_API_KEY"
    timeout_ms: int = 1500
    max_input_chars: int = 2000


class AIProvider(Protocol):
    def complete_json(self, payload: dict[str, Any], *, timeout_ms: int) -> str:
        ...


class UnconfiguredProvider:
    def complete_json(self, payload: dict[str, Any], *, timeout_ms: int) -> str:
        return ""


class FakeProvider:
    """Local-only provider for tests and manual validation.

    It never performs network IO. Set TERM_COPILOT_FAKE_AI_RESPONSE to a JSON
    response to exercise response validation. TERM_COPILOT_FAKE_AI_MODE can be
    set to "fail" or "timeout" to exercise provider error handling.
    """

    def complete_json(self, payload: dict[str, Any], *, timeout_ms: int) -> str:
        mode = os.getenv("TERM_COPILOT_FAKE_AI_MODE", "").lower()
        if mode == "fail":
            raise RuntimeError("fake provider failure")
        if mode == "timeout":
            raise TimeoutError("fake provider timeout")
        delay_ms = int(os.getenv("TERM_COPILOT_FAKE_AI_DELAY_MS", "0") or "0")
        if delay_ms > 0:
            if delay_ms > timeout_ms:
                raise TimeoutError("fake provider timeout")
            time.sleep(delay_ms / 1000)
        raw = os.getenv("TERM_COPILOT_FAKE_AI_RESPONSE")
        if raw:
            return raw
        buffer = str(payload.get("current_buffer") or "")
        if buffer.startswith("docker compose lo"):
            return json.dumps(
                {
                    "full_command": "docker compose logs -f backend",
                    "confidence": 0.8,
                    "risk": "safe",
                }
            )
        return json.dumps({"full_command": buffer, "confidence": 0.0, "risk": "safe"})


def _normalize(value: str) -> str:
    return " ".join(value.strip().split())


def _ghost_from_full(buffer: str, full_command: str) -> str:
    if full_command.startswith(buffer):
        return full_command[len(buffer):]
    normalized_buffer = _normalize(buffer)
    normalized_full = _normalize(full_command)
    if normalized_full.startswith(normalized_buffer):
        return normalized_full[len(normalized_buffer):]
    return ""


def _safe_list(values: list[str], *, limit: int = 12) -> list[str]:
    out: list[str] = []
    for value in values[:limit]:
        text = redact_text(str(value))
        if "<REDACTED>" in text:
            continue
        if text and not contains_secret(text):
            out.append(text)
    return out


def _looks_like_explanation(value: str) -> bool:
    stripped = value.strip()
    lowered = stripped.lower()
    return (
        "\n" in stripped
        or "```" in stripped
        or lowered.startswith(("here ", "here's", "explanation", "sure", "the command"))
        or lowered.endswith(":")
    )


class AIClient:
    def __init__(
        self,
        *,
        enabled: bool = False,
        provider: str = "gemini",
        model: str = "gemini-1.5-flash",
        api_key_env: str = "GEMINI_API_KEY",
        timeout_ms: int = 1500,
        max_input_chars: int = 2000,
        provider_impl: AIProvider | None = None,
    ):
        self.config = AIProviderConfig(
            enabled=enabled,
            provider=provider,
            model=model,
            api_key_env=api_key_env,
            timeout_ms=timeout_ms,
            max_input_chars=max_input_chars,
        )
        self.provider = provider_impl or self._default_provider(provider)
        self.last_payload: dict[str, Any] | None = None
        self.called = False

    @classmethod
    def from_settings(cls, settings) -> "AIClient":
        return cls(
            enabled=settings.ai.enabled,
            provider=settings.ai.provider,
            model=settings.ai.model,
            api_key_env=settings.ai.api_key_env,
            timeout_ms=settings.ai.timeout_ms,
            max_input_chars=settings.ai.max_input_chars,
        )

    @staticmethod
    def _default_provider(provider: str) -> AIProvider:
        if provider == "fake":
            return FakeProvider()
        return UnconfiguredProvider()

    def has_api_key(self) -> bool:
        if self.config.provider == "fake":
            return True
        return bool(self.config.api_key_env and os.getenv(self.config.api_key_env))

    def available(self) -> bool:
        return self.config.enabled and self.has_api_key()

    def build_payload(self, context: CommandContext) -> dict[str, Any] | None:
        raw_payload: dict[str, Any] = {
            "mode": "inline_shell_completion",
            "contract": {
                "response_format": "strict_json_only",
                "fields": ["full_command", "completion_or_ghost_text", "confidence", "risk"],
                "no_markdown": True,
                "no_explanations": True,
            },
            "provider": self.config.provider,
            "model": self.config.model,
            "shell": context.shell,
            "root_mode": context.root_mode,
            "cwd_type": context.project.project_type,
            "project_type": context.project.project_type,
            "project_tools": _safe_list(context.project.detected_tools),
            "current_buffer": context.buffer,
            "cursor_position": context.cursor,
            "docker_services": _safe_list(context.project.docker_services),
            "package_scripts": _safe_list(context.project.package_scripts),
            "make_targets": _safe_list(context.project.make_targets),
            "pytest_paths": _safe_list(context.project.pytest_paths),
            "recent_successful_commands": _safe_list(context.recent_commands, limit=8),
        }
        payload = redact_payload(raw_payload)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if len(encoded) > self.config.max_input_chars:
            payload["recent_successful_commands"] = []
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if len(encoded) > self.config.max_input_chars:
            payload["docker_services"] = payload["docker_services"][:4]
            payload["package_scripts"] = payload["package_scripts"][:6]
            payload["make_targets"] = payload["make_targets"][:6]
            payload["pytest_paths"] = payload["pytest_paths"][:4]
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if len(encoded) > self.config.max_input_chars:
            return None
        if contains_secret(encoded):
            return None
        return payload

    def complete(self, context: CommandContext) -> Suggestion:
        if not self.available():
            return empty_suggestion("ai disabled or provider unavailable")
        payload = self.build_payload(context)
        if payload is None:
            return empty_suggestion("redaction failed")
        self.last_payload = payload
        self.called = True
        try:
            raw = self.provider.complete_json(payload, timeout_ms=self.config.timeout_ms)
        except TimeoutError:
            return empty_suggestion("ai timeout")
        except Exception:
            return empty_suggestion("ai provider failed")
        return self.validate_response(raw, context)

    def validate_response(self, raw: str, context: CommandContext) -> Suggestion:
        if not raw or _looks_like_explanation(raw):
            return empty_suggestion("invalid ai response")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return empty_suggestion("invalid ai json")
        if not isinstance(data, dict):
            return empty_suggestion("invalid ai json")

        confidence_raw = data.get("confidence")
        if not isinstance(confidence_raw, (int, float)) or isinstance(confidence_raw, bool):
            return empty_suggestion("invalid ai confidence")
        confidence = float(confidence_raw)
        if confidence < 0.0 or confidence > 1.0:
            return empty_suggestion("invalid ai confidence")

        risk = str(data.get("risk") or "safe").lower()
        if risk == "dangerous":
            return empty_suggestion("dangerous ai response")
        if risk not in {"safe", "caution"}:
            return empty_suggestion("invalid ai risk")

        full_command = data.get("full_command")
        completion = data.get("completion", data.get("ghost_text"))
        if isinstance(full_command, str):
            full = full_command.strip()
        elif isinstance(completion, str):
            full = context.buffer + completion
        else:
            return empty_suggestion("missing ai command")

        if not full or _looks_like_explanation(full) or contains_secret(full):
            return empty_suggestion("unsafe ai command")
        ghost = _ghost_from_full(context.buffer, full)
        if not ghost or contains_secret(ghost):
            return empty_suggestion("ai command is not a continuation")
        return Suggestion(
            ghost_text=ghost,
            full_command=full,
            source="ai",
            confidence=confidence,
            risk=risk,  # type: ignore[arg-type]
            reason="ai fallback",
        )
