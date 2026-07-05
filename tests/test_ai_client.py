import json
from pathlib import Path

import pytest

from daemon.ai_client import (
    AIClient,
    AIProviderConfig,
    FakeProvider,
    GeminiProvider,
    GroqProvider,
    OpenRouterProvider,
    UnconfiguredProvider,
    create_provider,
)
from daemon.config import load_settings
from daemon.models import CommandContext, ProjectProfile


class CaptureTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post_json(self, url: str, headers: dict[str, str], body: dict, *, timeout_ms: int) -> dict:
        self.calls.append({"url": url, "headers": headers, "body": body, "timeout_ms": timeout_ms})
        return self.response


class StaticProvider:
    def __init__(self, raw: str):
        self.raw = raw
        self.calls = 0
        self.payloads = []

    def complete_json(self, payload, *, timeout_ms: int) -> str:
        self.calls += 1
        self.payloads.append(payload)
        return self.raw


def provider_response(provider: str, raw: str) -> dict:
    if provider == "gemini":
        return {"candidates": [{"content": {"parts": [{"text": raw}]}}]}
    return {"choices": [{"message": {"content": raw}}]}


def endpoint_for(provider: str) -> str:
    if provider == "gemini":
        return "https://example.test/v1beta/models/{model}:generateContent"
    return f"https://example.test/{provider}/chat/completions"


class TimeoutProvider:
    def __init__(self):
        self.calls = 0

    def complete_json(self, payload, *, timeout_ms: int) -> str:
        self.calls += 1
        raise TimeoutError("timeout")


class FailingProvider:
    def __init__(self):
        self.calls = 0

    def complete_json(self, payload, *, timeout_ms: int) -> str:
        self.calls += 1
        raise RuntimeError("failure")


def context(tmp_path: Path, *, buffer: str = "docker compose lo", root_mode: bool = False) -> CommandContext:
    return CommandContext(
        buffer=buffer,
        cursor=len(buffer),
        cwd=str(tmp_path),
        shell="zsh",
        first_token=buffer.split()[0],
        project_root=str(tmp_path),
        git_branch="main",
        project=ProjectProfile(
            project_root=str(tmp_path),
            project_type="docker_node",
            project_types=["docker", "node"],
            docker_services=["backend", "db"],
            package_scripts=["dev", "test"],
            make_targets=["build"],
            pytest_paths=["tests/"],
            detected_tools=["docker", "npm", "pytest"],
        ),
        root_mode=root_mode,
        recent_commands=[
            "docker compose ps",
            "export DATABASE_URL=postgres://user:pass@localhost/db",
            "curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz' example.test",
        ],
    )


def test_ai_disabled_by_default_does_not_call_provider(tmp_path: Path):
    provider = StaticProvider('{"full_command":"docker compose logs -f backend","confidence":0.9,"risk":"safe"}')
    client = AIClient(enabled=False, provider="fake", provider_impl=provider)

    suggestion = client.complete(context(tmp_path))

    assert provider.calls == 0
    assert suggestion.full_command == ""


def test_provider_factory_returns_fake_provider():
    provider = create_provider(AIProviderConfig(provider="fake"))

    assert isinstance(provider, FakeProvider)


def test_provider_factory_rejects_unknown_provider_safely(tmp_path: Path):
    provider = create_provider(AIProviderConfig(provider="unknown"))
    client = AIClient(enabled=True, provider="unknown", api_key_env="")

    assert isinstance(provider, UnconfiguredProvider)
    assert not client.available()
    assert client.complete(context(tmp_path)).full_command == ""


@pytest.mark.parametrize(
    ("provider_name", "provider_cls"),
    [
        ("gemini", GeminiProvider),
        ("groq", GroqProvider),
        ("openrouter", OpenRouterProvider),
    ],
)
def test_live_provider_skeletons_require_configured_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider_name: str, provider_cls):
    monkeypatch.delenv("TERM_COPILOT_TEST_AI_KEY", raising=False)
    transport = CaptureTransport(provider_response(provider_name, "{}"))
    client = AIClient(
        enabled=True,
        provider=provider_name,
        model="model-test",
        api_key_env="TERM_COPILOT_TEST_AI_KEY",
        endpoint=endpoint_for(provider_name),
        transport=transport,
    )

    suggestion = client.complete(context(tmp_path))
    provider = create_provider(
        AIProviderConfig(provider=provider_name, model="model-test", api_key_env="TERM_COPILOT_TEST_AI_KEY", endpoint=endpoint_for(provider_name)),
        transport=transport,
    )

    assert isinstance(provider, provider_cls)
    assert not client.available()
    assert suggestion.full_command == ""
    assert transport.calls == []
    with pytest.raises(RuntimeError):
        provider.complete_json({"current_buffer": "docker co"}, timeout_ms=10)


@pytest.mark.parametrize("provider_name", ["gemini", "groq", "openrouter"])
def test_live_provider_request_uses_sanitized_payload_and_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider_name: str):
    monkeypatch.setenv("TERM_COPILOT_TEST_AI_KEY", "provider-secret-value")
    raw = '{"completion":"gs -f backend","confidence":0.82,"risk":"safe"}'
    transport = CaptureTransport(provider_response(provider_name, raw))
    client = AIClient(
        enabled=True,
        provider=provider_name,
        model="model-test",
        api_key_env="TERM_COPILOT_TEST_AI_KEY",
        endpoint=endpoint_for(provider_name),
        timeout_ms=321,
        transport=transport,
    )

    suggestion = client.complete(context(tmp_path))

    assert suggestion.full_command == "docker compose logs -f backend"
    assert suggestion.source == "ai"
    assert len(transport.calls) == 1
    call = transport.calls[0]
    encoded_body = json.dumps(call["body"], ensure_ascii=False)
    assert call["timeout_ms"] == 321
    assert "provider-secret-value" not in encoded_body
    assert "postgres://user:pass" not in encoded_body
    assert "abcdefghijklmnopqrstuvwxyz" not in encoded_body
    assert str(tmp_path) not in encoded_body
    assert "docker compose lo" in encoded_body
    assert "strict JSON" in encoded_body
    if provider_name == "gemini":
        assert "model-test" in call["url"]
        assert call["headers"]["x-goog-api-key"] == "provider-secret-value"
    else:
        assert call["headers"]["Authorization"] == "Bearer provider-secret-value"


@pytest.mark.parametrize(
    "raw",
    [
        "```json\n{\"full_command\":\"docker compose logs -f backend\"}\n```",
        '{"full_command":"docker compose down","confidence":0.9,"risk":"dangerous"}',
        '{"full_command":"docker compose logs -f backend OPENAI_API_KEY=abc","confidence":0.9,"risk":"safe"}',
    ],
)
def test_provider_output_still_passes_existing_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str):
    monkeypatch.setenv("TERM_COPILOT_TEST_AI_KEY", "provider-secret-value")
    transport = CaptureTransport(provider_response("groq", raw))
    client = AIClient(
        enabled=True,
        provider="groq",
        model="model-test",
        api_key_env="TERM_COPILOT_TEST_AI_KEY",
        endpoint=endpoint_for("groq"),
        transport=transport,
    )

    suggestion = client.complete(context(tmp_path))

    assert len(transport.calls) == 1
    assert suggestion.full_command == ""


def test_provider_endpoint_config_and_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TERM_COPILOT_AI_PROVIDER", "groq")
    monkeypatch.delenv("TERM_COPILOT_AI_ENDPOINT", raising=False)
    settings = load_settings()

    assert settings.ai.endpoint == "https://api.groq.com/openai/v1/chat/completions"

    monkeypatch.setenv("TERM_COPILOT_AI_ENDPOINT", "https://example.test/custom")
    settings = load_settings()

    assert settings.ai.endpoint == "https://example.test/custom"


def test_ai_request_context_is_redacted_and_minimal(tmp_path: Path):
    provider = StaticProvider('{"full_command":"docker compose logs -f backend","confidence":0.9,"risk":"safe"}')
    client = AIClient(enabled=True, provider="fake", provider_impl=provider)

    suggestion = client.complete(context(tmp_path))

    assert suggestion.full_command == "docker compose logs -f backend"
    payload = provider.payloads[0]
    encoded = str(payload)
    assert "postgres://user:pass" not in encoded
    assert "abcdefghijklmnopqrstuvwxyz" not in encoded
    assert str(tmp_path) not in encoded
    assert payload["mode"] == "inline_shell_completion"
    assert payload["current_buffer"] == "docker compose lo"
    assert payload["docker_services"] == ["backend", "db"]
    assert payload["package_scripts"] == ["dev", "test"]


def test_ai_request_context_respects_max_input_chars(tmp_path: Path):
    provider = StaticProvider('{"full_command":"docker compose logs -f backend","confidence":0.9,"risk":"safe"}')
    client = AIClient(enabled=True, provider="fake", max_input_chars=64, provider_impl=provider)

    suggestion = client.complete(context(tmp_path))

    assert provider.calls == 0
    assert suggestion.full_command == ""


def test_ai_timeout_and_provider_failure_return_empty(tmp_path: Path):
    timeout_provider = TimeoutProvider()
    timeout_client = AIClient(enabled=True, provider="fake", provider_impl=timeout_provider)
    timeout_suggestion = timeout_client.complete(context(tmp_path))

    failing_provider = FailingProvider()
    failing_client = AIClient(enabled=True, provider="fake", provider_impl=failing_provider)
    failing_suggestion = failing_client.complete(context(tmp_path))

    assert timeout_provider.calls == 1
    assert timeout_suggestion.full_command == ""
    assert timeout_suggestion.reason == "ai timeout"
    assert failing_provider.calls == 1
    assert failing_suggestion.full_command == ""
    assert failing_suggestion.reason == "ai provider failed"


def test_fake_provider_failure_modes_are_local_only(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TERM_COPILOT_FAKE_AI_MODE", "timeout")
    timeout_client = AIClient(enabled=True, provider="fake")
    timeout_suggestion = timeout_client.complete(context(tmp_path))

    monkeypatch.setenv("TERM_COPILOT_FAKE_AI_MODE", "fail")
    failing_client = AIClient(enabled=True, provider="fake")
    failing_suggestion = failing_client.complete(context(tmp_path))

    assert timeout_suggestion.full_command == ""
    assert timeout_suggestion.reason == "ai timeout"
    assert failing_suggestion.full_command == ""
    assert failing_suggestion.reason == "ai provider failed"


def test_valid_ai_json_response_is_accepted_as_suffix(tmp_path: Path):
    client = AIClient(enabled=True, provider="fake", provider_impl=StaticProvider("{}"))

    suggestion = client.validate_response(
        '{"full_command":"docker compose logs -f backend","confidence":0.81,"risk":"safe"}',
        context(tmp_path),
    )

    assert suggestion.full_command == "docker compose logs -f backend"
    assert suggestion.ghost_text == "gs -f backend"
    assert suggestion.source == "ai"
    assert suggestion.confidence == 0.81


def test_ai_response_completion_field_is_accepted(tmp_path: Path):
    client = AIClient(enabled=True, provider="fake", provider_impl=StaticProvider("{}"))

    suggestion = client.validate_response(
        '{"completion":"gs -f backend","confidence":0.75,"risk":"safe"}',
        context(tmp_path),
    )

    assert suggestion.full_command == "docker compose logs -f backend"
    assert suggestion.ghost_text == "gs -f backend"


def test_ai_response_markdown_or_explanation_is_rejected(tmp_path: Path):
    client = AIClient(enabled=True, provider="fake", provider_impl=StaticProvider("{}"))

    for raw in (
        "```json\n{\"full_command\":\"docker compose logs -f backend\"}\n```",
        "Here is the command: docker compose logs -f backend",
        '{"full_command":"docker compose logs -f backend\\n# explanation","confidence":0.9,"risk":"safe"}',
    ):
        suggestion = client.validate_response(raw, context(tmp_path))
        assert suggestion.full_command == ""


def test_ai_response_non_continuation_dangerous_or_secret_is_rejected(tmp_path: Path):
    client = AIClient(enabled=True, provider="fake", provider_impl=StaticProvider("{}"))

    responses = [
        '{"full_command":"git status","confidence":0.9,"risk":"safe"}',
        '{"full_command":"docker compose logs -f backend","confidence":1.2,"risk":"safe"}',
        '{"full_command":"docker compose down","confidence":0.9,"risk":"dangerous"}',
        '{"full_command":"docker compose logs -f backend OPENAI_API_KEY=abc","confidence":0.9,"risk":"safe"}',
    ]
    for raw in responses:
        suggestion = client.validate_response(raw, context(tmp_path))
        assert suggestion.full_command == ""
