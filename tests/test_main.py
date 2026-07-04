from pathlib import Path

from daemon.history_store import HistoryStore
from daemon.main import main


def test_cli_event_updates_suggestion_counts(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "history.sqlite3"
    monkeypatch.setenv("TERM_COPILOT_DB", str(db_path))

    assert main(["record", "docker compose ps", "--cwd", str(tmp_path), "--exit-code", "0"]) == 0
    assert main(["event", "suggestion_accepted", "--suggestion", "docker compose ps"]) == 0
    assert main(["event", "suggestion_ignored", "--suggestion", "docker compose ps"]) == 0

    rows = HistoryStore(str(db_path)).search_prefix("docker compose", cwd=str(tmp_path.resolve()), project_root=None, git_branch=None)
    assert rows
    row = rows[0]
    assert row["accepted_count"] == 1
    assert row["ignored_count"] == 1


def test_cli_event_records_command_execution(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "history.sqlite3"
    monkeypatch.setenv("TERM_COPILOT_DB", str(db_path))

    assert main(["event", "command_executed", "--command", "pytest missing.py", "--cwd", str(tmp_path), "--exit-code", "2"]) == 0

    rows = HistoryStore(str(db_path)).search_prefix("pytest", cwd=str(tmp_path.resolve()), project_root=None, git_branch=None)
    assert rows
    row = rows[0]
    assert row["used_count"] == 1
    assert row["fail_count"] == 1
