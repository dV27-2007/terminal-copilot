from pathlib import Path

from daemon.ai_client import AIClient
from daemon.models import CommandContext, ProjectProfile


class StaticProvider:
    def __init__(self, raw: str):
        self.raw = raw
        self.calls = 0
        self.payloads = []

    def complete_json(self, payload, *, timeout_ms: int) -> str:
        self.calls += 1
        self.payloads.append(payload)
        return self.raw


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
