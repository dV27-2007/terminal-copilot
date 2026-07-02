from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any


def normalize_command(command: str) -> str:
    return " ".join(command.strip().split())


class HistoryStore:
    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path).expanduser())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=2.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command_text TEXT NOT NULL,
                    normalized_command TEXT NOT NULL,
                    cwd TEXT,
                    project_root TEXT,
                    git_branch TEXT,
                    exit_code INTEGER,
                    duration_ms INTEGER,
                    used_count INTEGER DEFAULT 1,
                    success_count INTEGER DEFAULT 0,
                    fail_count INTEGER DEFAULT 0,
                    accepted_count INTEGER DEFAULT 0,
                    ignored_count INTEGER DEFAULT 0,
                    source TEXT DEFAULT 'user_executed',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(normalized_command, cwd, project_root, git_branch)
                );
                CREATE INDEX IF NOT EXISTS idx_commands_prefix ON commands(normalized_command);
                CREATE INDEX IF NOT EXISTS idx_commands_context ON commands(cwd, project_root, git_branch, last_used_at);
                """
            )

    def record_command(
        self,
        command: str,
        *,
        cwd: str | None = None,
        project_root: str | None = None,
        git_branch: str | None = None,
        exit_code: int | None = None,
        duration_ms: int | None = None,
        source: str = "user_executed",
    ) -> None:
        normalized = normalize_command(command)
        if not normalized:
            return
        success_inc = 1 if exit_code == 0 else 0
        fail_inc = 1 if exit_code not in (None, 0) else 0
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO commands (
                    command_text, normalized_command, cwd, project_root, git_branch, exit_code, duration_ms,
                    used_count, success_count, fail_count, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(normalized_command, cwd, project_root, git_branch) DO UPDATE SET
                    command_text=excluded.command_text,
                    exit_code=excluded.exit_code,
                    duration_ms=excluded.duration_ms,
                    used_count=commands.used_count + 1,
                    success_count=commands.success_count + excluded.success_count,
                    fail_count=commands.fail_count + excluded.fail_count,
                    source=excluded.source,
                    last_used_at=CURRENT_TIMESTAMP
                """,
                (command, normalized, cwd, project_root, git_branch, exit_code, duration_ms, success_inc, fail_inc, source),
            )

    def search_prefix(self, prefix: str, *, cwd: str | None, project_root: str | None, git_branch: str | None, limit: int = 50) -> list[dict[str, Any]]:
        prefix_norm = normalize_command(prefix)
        if not prefix_norm:
            return []
        like = prefix_norm + "%"
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM commands
                WHERE normalized_command LIKE ? AND normalized_command != ?
                ORDER BY
                    CASE WHEN cwd IS ? THEN 1 ELSE 0 END DESC,
                    CASE WHEN project_root IS ? THEN 1 ELSE 0 END DESC,
                    CASE WHEN git_branch IS ? THEN 1 ELSE 0 END DESC,
                    success_count DESC,
                    used_count DESC,
                    last_used_at DESC
                LIMIT ?
                """,
                (like, prefix_norm, cwd, project_root, git_branch, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_commands(self, *, cwd: str | None = None, project_root: str | None = None, limit: int = 10) -> list[str]:
        clauses = []
        params: list[Any] = []
        if cwd:
            clauses.append("cwd = ?")
            params.append(cwd)
        if project_root:
            clauses.append("project_root = ?")
            params.append(project_root)
        where = "WHERE " + " OR ".join(clauses) if clauses else ""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT command_text FROM commands
                {where}
                ORDER BY last_used_at DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [str(row["command_text"]) for row in rows]

    def mark_suggestion(self, full_command: str, *, accepted: bool) -> None:
        normalized = normalize_command(full_command)
        if not normalized:
            return
        column = "accepted_count" if accepted else "ignored_count"
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE commands SET {column}={column}+1, last_used_at=CURRENT_TIMESTAMP WHERE normalized_command=?",
                (normalized,),
            )
