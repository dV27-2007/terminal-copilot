from pathlib import Path

from daemon.cache_store import CacheStore
from daemon.config import Settings
from daemon.history_store import HistoryStore
from daemon.models import PredictRequest
from daemon.predictor import Predictor


def make_predictor(tmp_path: Path) -> Predictor:
    settings = Settings()
    settings.daemon.db_path = str(tmp_path / "history.sqlite3")
    settings.ai.enabled = False
    history = HistoryStore(settings.daemon.db_path)
    cache = CacheStore(settings.daemon.db_path)
    return Predictor(settings=settings, history=history, cache=cache)


def test_predicts_from_history(tmp_path: Path):
    predictor = make_predictor(tmp_path)
    predictor.record_command("docker compose up -d backend celery", cwd=str(tmp_path), exit_code=0, duration_ms=100)
    suggestion = predictor.predict(PredictRequest(buffer="docker co", cwd=str(tmp_path), shell="zsh"))
    assert suggestion.full_command == "docker compose up -d backend celery"
    assert suggestion.ghost_text.startswith("mpose")
    assert suggestion.source == "history"


def test_history_examples_predict_expected_suffixes(tmp_path: Path):
    predictor = make_predictor(tmp_path)
    examples = [
        ("docker compose ps", "docker co", "mpose ps"),
        ("docker compose logs -f backend", "docker compose lo", "gs -f backend"),
        ("git checkout dev", "git ch", "eckout dev"),
        ("pytest tests/ -q", "pytest te", "sts/ -q"),
        ("npm run dev", "npm ru", "n dev"),
        ("make test", "make te", "st"),
    ]
    for command, buffer, expected_ghost in examples:
        predictor.record_command(command, cwd=str(tmp_path), exit_code=0, duration_ms=100)
        suggestion = predictor.predict(PredictRequest(buffer=buffer, cwd=str(tmp_path), shell="zsh"))
        assert suggestion.full_command == command
        assert suggestion.ghost_text == expected_ghost
        assert suggestion.source == "history"


def test_does_not_answer_natural_language(tmp_path: Path):
    predictor = make_predictor(tmp_path)
    suggestion = predictor.predict(PredictRequest(buffer="почему docker не работает", cwd=str(tmp_path)))
    assert suggestion.ghost_text == ""


def test_does_not_answer_english_or_mixed_natural_language(tmp_path: Path):
    predictor = make_predictor(tmp_path)
    predictor.record_command("docker compose ps", cwd=str(tmp_path), exit_code=0, duration_ms=100)

    for buffer in (
        "what is docker",
        "how do I run tests",
        "explain pytest error",
        "что делать если postgres не работает",
        "docker почему не работает",
        "inchpes run tests",
    ):
        suggestion = predictor.predict(PredictRequest(buffer=buffer, cwd=str(tmp_path)))
        assert suggestion.ghost_text == ""
        assert suggestion.full_command == ""


def test_secret_looking_buffers_return_empty(tmp_path: Path):
    predictor = make_predictor(tmp_path)

    for buffer in (
        "DATABASE_URL=postgresql://user:pass@localhost/db",
        "export OPENAI_API_KEY=abc",
        'curl -H "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456" example.com',
    ):
        suggestion = predictor.predict(PredictRequest(buffer=buffer, cwd=str(tmp_path)))
        assert suggestion.ghost_text == ""
        assert suggestion.full_command == ""
    assert predictor.history.count_commands() == 0


def test_cursor_buffer_is_clamped_and_ghost_text_is_suffix_only(tmp_path: Path):
    predictor = make_predictor(tmp_path)
    predictor.record_command("docker compose ps", cwd=str(tmp_path), exit_code=0, duration_ms=100)

    suggestion = predictor.predict(PredictRequest(buffer="docker co ignored", cursor=9, cwd=str(tmp_path), shell="zsh"))

    assert suggestion.full_command == "docker compose ps"
    assert suggestion.ghost_text == "mpose ps"


def test_invalid_candidate_that_cannot_continue_buffer_returns_empty(tmp_path: Path):
    predictor = make_predictor(tmp_path)

    def fake_search_prefix(prefix: str, *, cwd: str | None, project_root: str | None, git_branch: str | None, limit: int = 50):
        return [
            {
                "command_text": "git status",
                "normalized_command": "git status",
                "cwd": str(tmp_path),
                "project_root": None,
                "git_branch": None,
                "used_count": 10,
                "success_count": 10,
                "fail_count": 0,
                "accepted_count": 0,
                "ignored_count": 0,
            }
        ]

    predictor.history.search_prefix = fake_search_prefix  # type: ignore[method-assign]
    suggestion = predictor.predict(PredictRequest(buffer="docker co", cwd=str(tmp_path), shell="zsh"))

    assert suggestion.ghost_text == ""
    assert suggestion.full_command == ""


def test_dangerous_history_command_is_not_returned_as_ghost_text(tmp_path: Path):
    predictor = make_predictor(tmp_path)
    predictor.record_command("rm -rf /", cwd=str(tmp_path), exit_code=0, duration_ms=100)

    suggestion = predictor.predict(PredictRequest(buffer="rm -rf", cwd=str(tmp_path), shell="zsh"))

    assert suggestion.ghost_text == ""
    assert suggestion.full_command == ""


def test_root_mode_does_not_return_dangerous_suggestion(tmp_path: Path):
    predictor = make_predictor(tmp_path)
    predictor.record_command("sudo rm -rf /", cwd=str(tmp_path), exit_code=0, duration_ms=100)

    suggestion = predictor.predict(PredictRequest(buffer="sudo rm -rf", cwd=str(tmp_path), shell="zsh", root_mode=True))

    assert suggestion.ghost_text == ""
    assert suggestion.full_command == ""


def test_project_context_docker_logs(tmp_path: Path):
    (tmp_path / "docker-compose.yml").write_text("services:\n  backend:\n    image: app\n")
    predictor = make_predictor(tmp_path)
    suggestion = predictor.predict(PredictRequest(buffer="docker compose lo", cwd=str(tmp_path)))
    assert suggestion.full_command == "docker compose logs -f backend"
