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


def test_does_not_answer_natural_language(tmp_path: Path):
    predictor = make_predictor(tmp_path)
    suggestion = predictor.predict(PredictRequest(buffer="почему docker не работает", cwd=str(tmp_path)))
    assert suggestion.ghost_text == ""


def test_project_context_docker_logs(tmp_path: Path):
    (tmp_path / "docker-compose.yml").write_text("services:\n  backend:\n    image: app\n")
    predictor = make_predictor(tmp_path)
    suggestion = predictor.predict(PredictRequest(buffer="docker compose lo", cwd=str(tmp_path)))
    assert suggestion.full_command == "docker compose logs -f backend"
