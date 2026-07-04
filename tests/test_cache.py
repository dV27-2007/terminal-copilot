from pathlib import Path
import sqlite3

from daemon.cache_store import CacheStore
from daemon.models import CommandContext, ProjectProfile, Suggestion


def ctx(tmp_path: Path, *, buffer: str = "docker co") -> CommandContext:
    return CommandContext(
        buffer=buffer,
        cursor=len(buffer),
        cwd=str(tmp_path),
        shell="zsh",
        first_token=buffer.strip().split()[0] if buffer.strip() else "",
        project_root=str(tmp_path),
        git_branch="dev",
        project=ProjectProfile(
            project_root=str(tmp_path),
            project_type="docker",
            marker_hash="profile-v1",
            docker_services=["backend"],
        ),
    )


def test_cache_roundtrip(tmp_path: Path):
    store = CacheStore(str(tmp_path / "db.sqlite3"))
    context = ctx(tmp_path)
    suggestion = Suggestion("mpose ps", "docker compose ps", "project_context", 0.8, "safe")
    store.save(context, suggestion)
    loaded = store.lookup(context)
    assert loaded is not None
    assert loaded.full_command == "docker compose ps"


def test_cache_rejects_secret_looking_suggestion(tmp_path: Path):
    store = CacheStore(str(tmp_path / "db.sqlite3"))
    context = ctx(tmp_path, buffer="export O")
    suggestion = Suggestion("PENAI_API_KEY=sk-secret1234567890", "export OPENAI_API_KEY=sk-secret1234567890", "history", 0.9, "safe")

    assert store.save(context, suggestion) is False
    assert store.count() == 0


def test_cache_rejects_dangerous_suggestion(tmp_path: Path):
    store = CacheStore(str(tmp_path / "db.sqlite3"))
    context = ctx(tmp_path, buffer="rm")
    suggestion = Suggestion(" -rf /", "rm -rf /", "history", 0.9, "safe")

    assert store.save(context, suggestion) is False
    assert store.count() == 0


def test_cache_hit_requires_valid_suffix_continuation(tmp_path: Path):
    db_path = tmp_path / "db.sqlite3"
    store = CacheStore(str(db_path))
    context = ctx(tmp_path)
    input_hash, context_hash = store.keys(context)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO suggestions_cache (
                input_hash, context_hash, buffer, full_command, ghost_text, source, confidence, risk, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', '+14 days'))
            """,
            (input_hash, context_hash, context.buffer, "git status", " status", "history", 0.95, "safe"),
        )

    assert store.lookup(context) is None
    assert store.lookup_candidates(context) == []


def test_expired_cache_entry_is_ignored(tmp_path: Path):
    db_path = tmp_path / "db.sqlite3"
    store = CacheStore(str(db_path))
    context = ctx(tmp_path)
    suggestion = Suggestion("mpose ps", "docker compose ps", "history", 0.9, "safe")
    assert store.save(context, suggestion) is True

    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE suggestions_cache SET expires_at=datetime('now', '-1 day')")

    assert store.lookup(context) is None


def test_cache_pruning_removes_expired_ignored_and_old_low_value_entries(tmp_path: Path):
    db_path = tmp_path / "db.sqlite3"
    store = CacheStore(str(db_path), max_entries=10)
    keep = ctx(tmp_path, buffer="docker co")
    expired = ctx(tmp_path, buffer="git st")
    ignored = ctx(tmp_path, buffer="npm r")
    old_low_value = ctx(tmp_path, buffer="pytest t")

    assert store.save(keep, Suggestion("mpose ps", "docker compose ps", "history", 0.9, "safe"))
    assert store.save(expired, Suggestion("atus", "git status", "history", 0.9, "safe"))
    assert store.save(ignored, Suggestion("un dev", "npm run dev", "history", 0.9, "safe"))
    assert store.save(old_low_value, Suggestion("ests/ -q", "pytest tests/ -q", "history", 0.9, "safe"))
    store.mark("docker compose ps", accepted=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE suggestions_cache SET expires_at=datetime('now', '-1 day') WHERE full_command='git status'")
        conn.execute("UPDATE suggestions_cache SET ignored_count=3 WHERE full_command='npm run dev'")
        conn.execute("UPDATE suggestions_cache SET last_used_at=datetime('now', '-45 days') WHERE full_command='pytest tests/ -q'")

    deleted = store.prune(max_entries=10, ignored_threshold=3, low_value_retention_days=30)

    assert deleted == 3
    assert store.get_entry("docker compose ps") is not None
    assert store.get_entry("git status") is None
    assert store.get_entry("npm run dev") is None
    assert store.get_entry("pytest tests/ -q") is None


def test_cache_pruning_caps_oversized_cache_and_keeps_accepted_entries(tmp_path: Path):
    store = CacheStore(str(tmp_path / "db.sqlite3"), max_entries=10)
    keep = ctx(tmp_path, buffer="docker co")
    assert store.save(keep, Suggestion("mpose ps", "docker compose ps", "history", 0.9, "safe"))
    store.mark("docker compose ps", accepted=True)

    for index in range(5):
        context = ctx(tmp_path, buffer=f"git status {index}")
        assert store.save(context, Suggestion(" --short", f"git status {index} --short", "history", 0.9, "safe"))

    store.prune(max_entries=3)

    assert store.count() == 3
    assert store.get_entry("docker compose ps") is not None


def test_cache_mark_updates_accepted_and_ignored_counts(tmp_path: Path):
    store = CacheStore(str(tmp_path / "db.sqlite3"))
    context = ctx(tmp_path)
    suggestion = Suggestion("mpose ps", "docker compose ps", "history", 0.9, "safe")
    assert store.save(context, suggestion)

    assert store.mark("docker compose ps", accepted=True) == 1
    assert store.mark("docker compose ps", accepted=False) == 1

    entry = store.get_entry("docker compose ps")
    assert entry is not None
    assert entry["accepted_count"] == 1
    assert entry["ignored_count"] == 1


def test_cache_mark_execution_updates_success_and_failure_counts(tmp_path: Path):
    store = CacheStore(str(tmp_path / "db.sqlite3"))
    context = ctx(tmp_path)
    suggestion = Suggestion("mpose ps", "docker compose ps", "history", 0.9, "safe")
    assert store.save(context, suggestion)

    store.mark_execution("docker compose ps", exit_code=0)
    store.mark_execution("docker compose ps", exit_code=1)

    entry = store.get_entry("docker compose ps")
    assert entry is not None
    assert entry["used_count"] == 2
    assert entry["success_count"] == 1
    assert entry["fail_count"] == 1
