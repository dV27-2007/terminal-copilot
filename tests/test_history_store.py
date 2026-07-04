import sqlite3
from pathlib import Path

from daemon.history_store import SCHEMA_VERSION, HistoryStore


def open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_schema_initializes_with_version_and_commands_table(tmp_path: Path):
    db_path = tmp_path / "history.sqlite3"
    store = HistoryStore(str(db_path))

    assert store.schema_version() == SCHEMA_VERSION
    with open_db(db_path) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(commands)")}

    assert {
        "command_text",
        "normalized_command",
        "cwd",
        "project_root",
        "git_branch",
        "used_count",
        "success_count",
        "fail_count",
        "last_used_at",
    }.issubset(columns)


def test_wal_mode_is_enabled(tmp_path: Path):
    store = HistoryStore(str(tmp_path / "history.sqlite3"))

    assert store.journal_mode().lower() == "wal"


def test_prediction_indexes_exist(tmp_path: Path):
    store = HistoryStore(str(tmp_path / "history.sqlite3"))

    assert {
        "idx_commands_prefix",
        "idx_commands_prefix_nocase",
        "idx_commands_context",
        "idx_commands_project_context_recent",
        "idx_commands_recent",
        "idx_commands_retention",
    }.issubset(store.index_names())


def test_records_successful_command(tmp_path: Path):
    store = HistoryStore(str(tmp_path / "history.sqlite3"))

    store.record_command("docker compose ps", cwd=str(tmp_path), exit_code=0, duration_ms=50)
    row = store.get_command("docker compose ps", cwd=str(tmp_path))

    assert row is not None
    assert row["used_count"] == 1
    assert row["success_count"] == 1
    assert row["fail_count"] == 0
    assert row["exit_code"] == 0


def test_records_failed_command(tmp_path: Path):
    store = HistoryStore(str(tmp_path / "history.sqlite3"))

    store.record_command("pytest missing.py", cwd=str(tmp_path), exit_code=2, duration_ms=10)
    row = store.get_command("pytest missing.py", cwd=str(tmp_path))

    assert row is not None
    assert row["used_count"] == 1
    assert row["success_count"] == 0
    assert row["fail_count"] == 1
    assert row["exit_code"] == 2


def test_rerecord_same_command_updates_counts_without_duplicate_with_null_context(tmp_path: Path):
    store = HistoryStore(str(tmp_path / "history.sqlite3"))

    store.record_command("docker ps", cwd=str(tmp_path), exit_code=0)
    store.record_command("docker ps", cwd=str(tmp_path), exit_code=1)
    row = store.get_command("docker ps", cwd=str(tmp_path))

    assert row is not None
    assert store.count_commands() == 1
    assert row["used_count"] == 2
    assert row["success_count"] == 1
    assert row["fail_count"] == 1
    assert row["exit_code"] == 1


def test_prefix_search_returns_expected_commands(tmp_path: Path):
    store = HistoryStore(str(tmp_path / "history.sqlite3"))

    store.record_command("docker compose ps", cwd=str(tmp_path), exit_code=0)
    store.record_command("git status", cwd=str(tmp_path), exit_code=0)
    rows = store.search_prefix("docker co", cwd=str(tmp_path), project_root=None, git_branch=None)

    assert [row["command_text"] for row in rows] == ["docker compose ps"]


def test_context_search_prefers_same_cwd_project_and_branch(tmp_path: Path):
    store = HistoryStore(str(tmp_path / "history.sqlite3"))
    same_cwd = str(tmp_path / "same")
    other_cwd = str(tmp_path / "other")

    for _ in range(3):
        store.record_command("docker compose up", cwd=other_cwd, project_root=other_cwd, git_branch="main", exit_code=0)
    store.record_command("docker compose logs", cwd=same_cwd, project_root=same_cwd, git_branch="dev", exit_code=0)

    rows = store.search_prefix("docker compose", cwd=same_cwd, project_root=same_cwd, git_branch="dev")

    assert rows[0]["command_text"] == "docker compose logs"


def test_retention_prunes_old_failed_one_off_commands(tmp_path: Path):
    db_path = tmp_path / "history.sqlite3"
    store = HistoryStore(str(db_path))

    store.record_command("pytest old_missing.py", cwd=str(tmp_path), exit_code=2)
    store.record_command("pytest fresh_missing.py", cwd=str(tmp_path), exit_code=2)
    with open_db(db_path) as conn:
        conn.execute(
            "UPDATE commands SET last_used_at=datetime('now', '-45 days') WHERE normalized_command=?",
            ("pytest old_missing.py",),
        )

    deleted = store.cleanup_retention(failed_one_off_retention_days=30)

    assert deleted == 1
    assert store.get_command("pytest old_missing.py", cwd=str(tmp_path)) is None
    assert store.get_command("pytest fresh_missing.py", cwd=str(tmp_path)) is not None


def test_retention_keeps_frequent_successful_commands_when_capping(tmp_path: Path):
    store = HistoryStore(str(tmp_path / "history.sqlite3"))

    for _ in range(5):
        store.record_command("pytest tests", cwd=str(tmp_path), exit_code=0)
    for index in range(5):
        store.record_command(f"python script_{index}.py", cwd=str(tmp_path), exit_code=0)

    store.cleanup_retention(max_commands=3, failed_one_off_retention_days=9999)

    assert store.count_commands() == 3
    assert store.get_command("pytest tests", cwd=str(tmp_path)) is not None


def test_secret_looking_commands_are_not_stored(tmp_path: Path):
    store = HistoryStore(str(tmp_path / "history.sqlite3"))

    store.record_command("export DATABASE_URL=postgres://user:pass@localhost/db", cwd=str(tmp_path), exit_code=0)
    store.record_command("curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456' https://example.test", cwd=str(tmp_path), exit_code=0)
    store.record_command("echo token=abcdefghijklmnopqrstuvwxyz123456", cwd=str(tmp_path), exit_code=0)

    assert store.count_commands() == 0
