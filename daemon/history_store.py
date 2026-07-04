from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from .redactor import contains_secret

SCHEMA_VERSION = 1
DEFAULT_MAX_COMMANDS = 50_000
DEFAULT_FAILED_ONE_OFF_RETENTION_DAYS = 30


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
        conn.execute("PRAGMA busy_timeout=2000")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            current_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(f"unsupported history schema version: {current_version}")
            if current_version < 1:
                self._migrate_to_1(conn)
            self._ensure_indexes(conn)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _migrate_to_1(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
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
            """
        )

    def _ensure_indexes(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_commands_prefix
                ON commands(normalized_command);
            CREATE INDEX IF NOT EXISTS idx_commands_prefix_nocase
                ON commands(normalized_command COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_commands_context
                ON commands(cwd, project_root, git_branch, last_used_at);
            CREATE INDEX IF NOT EXISTS idx_commands_project_context_recent
                ON commands(project_root, cwd, git_branch, last_used_at DESC);
            CREATE INDEX IF NOT EXISTS idx_commands_recent
                ON commands(last_used_at DESC);
            CREATE INDEX IF NOT EXISTS idx_commands_retention
                ON commands(used_count, success_count, fail_count, accepted_count, last_used_at);
            """
        )

    def schema_version(self) -> int:
        with self._lock, self._connect() as conn:
            return int(conn.execute("PRAGMA user_version").fetchone()[0])

    def journal_mode(self) -> str:
        with self._lock, self._connect() as conn:
            return str(conn.execute("PRAGMA journal_mode").fetchone()[0])

    def index_names(self) -> set[str]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("PRAGMA index_list(commands)").fetchall()
        return {str(row["name"]) for row in rows}

    def count_commands(self) -> int:
        with self._lock, self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM commands").fetchone()[0])

    def get_command(
        self,
        command: str,
        *,
        cwd: str | None = None,
        project_root: str | None = None,
        git_branch: str | None = None,
    ) -> dict[str, Any] | None:
        normalized = normalize_command(command)
        if not normalized:
            return None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM commands
                WHERE normalized_command=? AND cwd IS ? AND project_root IS ? AND git_branch IS ?
                ORDER BY last_used_at DESC, id DESC
                LIMIT 1
                """,
                (normalized, cwd, project_root, git_branch),
            ).fetchone()
        return dict(row) if row else None

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
        if not normalized or contains_secret(command) or contains_secret(normalized):
            return
        success_inc = 1 if exit_code == 0 else 0
        fail_inc = 1 if exit_code not in (None, 0) else 0
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                """
                SELECT id FROM commands
                WHERE normalized_command=? AND cwd IS ? AND project_root IS ? AND git_branch IS ?
                ORDER BY last_used_at DESC, id DESC
                LIMIT 1
                """,
                (normalized, cwd, project_root, git_branch),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE commands SET
                        command_text=?,
                        exit_code=?,
                        duration_ms=?,
                        used_count=used_count + 1,
                        success_count=success_count + ?,
                        fail_count=fail_count + ?,
                        source=?,
                        last_used_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (command, exit_code, duration_ms, success_inc, fail_inc, source, existing["id"]),
                )
                return

            conn.execute(
                """
                INSERT INTO commands (
                    command_text, normalized_command, cwd, project_root, git_branch, exit_code, duration_ms,
                    used_count, success_count, fail_count, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
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

    def cleanup_retention(
        self,
        *,
        max_commands: int = DEFAULT_MAX_COMMANDS,
        failed_one_off_retention_days: int = DEFAULT_FAILED_ONE_OFF_RETENTION_DAYS,
    ) -> int:
        if max_commands < 1:
            raise ValueError("max_commands must be positive")
        if failed_one_off_retention_days < 0:
            raise ValueError("failed_one_off_retention_days must be non-negative")

        with self._lock, self._connect() as conn:
            before = conn.total_changes
            conn.execute(
                """
                DELETE FROM commands
                WHERE used_count <= 1
                  AND success_count = 0
                  AND fail_count > 0
                  AND accepted_count = 0
                  AND last_used_at < datetime('now', ?)
                """,
                (f"-{failed_one_off_retention_days} days",),
            )

            count = int(conn.execute("SELECT COUNT(*) FROM commands").fetchone()[0])
            excess = max(0, count - max_commands)
            if excess:
                conn.execute(
                    """
                    DELETE FROM commands
                    WHERE id IN (
                        SELECT id FROM commands
                        ORDER BY
                            CASE
                                WHEN accepted_count > 0 OR success_count > 0 OR used_count > 1 THEN 1
                                ELSE 0
                            END ASC,
                            accepted_count ASC,
                            success_count ASC,
                            used_count ASC,
                            last_used_at ASC,
                            id ASC
                        LIMIT ?
                    )
                    """,
                    (excess,),
                )
            return conn.total_changes - before
