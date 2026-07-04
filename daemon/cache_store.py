from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import Candidate, CommandContext, Suggestion
from .redactor import contains_secret
from .safety import SafetyPolicy

DEFAULT_CACHE_TTL_DAYS = 14
DEFAULT_MAX_CACHE_ENTRIES = 5_000
DEFAULT_IGNORED_PRUNE_THRESHOLD = 3
DEFAULT_LOW_VALUE_RETENTION_DAYS = 30

_DEFAULT_SAFETY = SafetyPolicy()


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


def _sqlite_timestamp(days_from_now: int = 0) -> str:
    value = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=days_from_now)
    return value.strftime("%Y-%m-%d %H:%M:%S")


class CacheStore:
    def __init__(
        self,
        db_path: str,
        *,
        ttl_days: int = DEFAULT_CACHE_TTL_DAYS,
        max_entries: int = DEFAULT_MAX_CACHE_ENTRIES,
    ):
        self.db_path = str(Path(db_path).expanduser())
        self.ttl_days = ttl_days
        self.max_entries = max_entries
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
                CREATE TABLE IF NOT EXISTS suggestions_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    input_hash TEXT NOT NULL,
                    context_hash TEXT NOT NULL,
                    buffer TEXT NOT NULL,
                    cwd TEXT,
                    project_root TEXT,
                    git_branch TEXT,
                    shell TEXT,
                    root_mode INTEGER DEFAULT 0,
                    project_marker_hash TEXT,
                    full_command TEXT NOT NULL,
                    ghost_text TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL,
                    risk TEXT,
                    used_count INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    fail_count INTEGER DEFAULT 0,
                    exit_code INTEGER,
                    accepted_count INTEGER DEFAULT 0,
                    ignored_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    expires_at TEXT,
                    UNIQUE(input_hash, context_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_cache_lookup ON suggestions_cache(input_hash, context_hash);
                CREATE INDEX IF NOT EXISTS idx_cache_expiry ON suggestions_cache(expires_at);
                CREATE INDEX IF NOT EXISTS idx_cache_command ON suggestions_cache(full_command);
                CREATE INDEX IF NOT EXISTS idx_cache_prune
                    ON suggestions_cache(accepted_count, ignored_count, used_count, success_count, last_used_at);
                """
            )
            self._ensure_columns(conn)

    def _ensure_columns(self, conn: sqlite3.Connection) -> None:
        existing = {str(row["name"]) for row in conn.execute("PRAGMA table_info(suggestions_cache)").fetchall()}
        columns = {
            "cwd": "TEXT",
            "project_root": "TEXT",
            "git_branch": "TEXT",
            "shell": "TEXT",
            "root_mode": "INTEGER DEFAULT 0",
            "project_marker_hash": "TEXT",
            "used_count": "INTEGER DEFAULT 0",
            "success_count": "INTEGER DEFAULT 0",
            "fail_count": "INTEGER DEFAULT 0",
            "exit_code": "INTEGER",
        }
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE suggestions_cache ADD COLUMN {name} {definition}")

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def keys(self, context: CommandContext) -> tuple[str, str]:
        input_hash = self._hash_payload({"buffer": _normalize(context.buffer)})
        context_hash = self._hash_payload(
            {
                "context_root": context.project_root or context.cwd,
                "git_branch": context.git_branch,
                "shell": context.shell,
                "root_mode": bool(context.root_mode),
                "project_type": context.project.project_type,
                "project_types": context.project.project_types,
                "project_marker_hash": context.project.marker_hash,
            }
        )
        return input_hash, context_hash

    def lookup(self, context: CommandContext) -> Suggestion | None:
        candidates = self.lookup_candidates(context, limit=1)
        if not candidates:
            return None
        candidate = candidates[0]
        ghost = _ghost_from_full(context.buffer, candidate.full_command)
        if not ghost:
            return None
        confidence = float(candidate.metadata.get("confidence") or 0.0)
        return Suggestion(
            ghost_text=ghost,
            full_command=candidate.full_command,
            source="cache",
            confidence=confidence,
            risk=str(candidate.metadata.get("risk") or "safe"),  # type: ignore[arg-type]
            reason="cache hit",
        )

    def lookup_candidates(self, context: CommandContext, *, limit: int = 5) -> list[Candidate]:
        input_hash, context_hash = self.keys(context)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM suggestions_cache
                WHERE input_hash=? AND context_hash=? AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
                ORDER BY accepted_count DESC, ignored_count ASC, last_used_at DESC
                LIMIT ?
                """,
                (input_hash, context_hash, limit),
            ).fetchall()

        candidates = []
        for row in rows:
            full_command = str(row["full_command"] or "")
            if str(row["risk"] or "safe") != "safe":
                continue
            if not self._is_safe_hit(context, full_command):
                continue
            metadata = dict(row)
            metadata["command_text"] = full_command
            confidence = max(0.0, min(float(row["confidence"] or 0.0), 0.99))
            candidates.append(Candidate(full_command=full_command, source="cache", base_score=confidence * 85.0, metadata=metadata))
        return candidates

    def _is_safe_hit(self, context: CommandContext, full_command: str) -> bool:
        if not full_command or contains_secret(context.buffer) or contains_secret(full_command):
            return False
        if not _ghost_from_full(context.buffer, full_command):
            return False
        result = _DEFAULT_SAFETY.classify(full_command, buffer=context.buffer, root_mode=context.root_mode, source="cache")
        return result.risk == "safe"

    def _is_safe_save(self, context: CommandContext, suggestion: Suggestion) -> bool:
        if not suggestion.ghost_text or not suggestion.full_command:
            return False
        if suggestion.risk != "safe":
            return False
        if contains_secret(context.buffer) or contains_secret(suggestion.full_command) or contains_secret(suggestion.ghost_text):
            return False
        if not _ghost_from_full(context.buffer, suggestion.full_command):
            return False
        result = _DEFAULT_SAFETY.classify(suggestion.full_command, buffer=context.buffer, root_mode=context.root_mode, source=suggestion.source)
        return result.risk == "safe"

    def save(self, context: CommandContext, suggestion: Suggestion, *, ttl_days: int | None = None) -> bool:
        if not self._is_safe_save(context, suggestion):
            return False
        input_hash, context_hash = self.keys(context)
        expires_at = _sqlite_timestamp(ttl_days if ttl_days is not None else self.ttl_days)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO suggestions_cache (
                    input_hash, context_hash, buffer, cwd, project_root, git_branch, shell, root_mode,
                    project_marker_hash, full_command, ghost_text, source, confidence, risk, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(input_hash, context_hash) DO UPDATE SET
                    buffer=excluded.buffer,
                    cwd=excluded.cwd,
                    project_root=excluded.project_root,
                    git_branch=excluded.git_branch,
                    shell=excluded.shell,
                    root_mode=excluded.root_mode,
                    project_marker_hash=excluded.project_marker_hash,
                    full_command=excluded.full_command,
                    ghost_text=excluded.ghost_text,
                    source=excluded.source,
                    confidence=excluded.confidence,
                    risk=excluded.risk,
                    expires_at=excluded.expires_at,
                    last_used_at=CURRENT_TIMESTAMP
                """,
                (
                    input_hash,
                    context_hash,
                    context.buffer,
                    context.cwd,
                    context.project_root,
                    context.git_branch,
                    context.shell,
                    1 if context.root_mode else 0,
                    context.project.marker_hash,
                    suggestion.full_command,
                    suggestion.ghost_text,
                    suggestion.source,
                    suggestion.confidence,
                    suggestion.risk,
                    expires_at,
                ),
            )
            self._prune_conn(conn, max_entries=self.max_entries)
        return True

    def mark(self, full_command: str, *, accepted: bool) -> int:
        column = "accepted_count" if accepted else "ignored_count"
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE suggestions_cache SET {column}={column}+1, last_used_at=CURRENT_TIMESTAMP WHERE full_command=?",
                (full_command,),
            )
            self._prune_conn(conn, max_entries=self.max_entries)
            return cursor.rowcount

    def mark_execution(self, full_command: str, *, exit_code: int | None) -> int:
        success_inc = 1 if exit_code == 0 else 0
        fail_inc = 1 if exit_code not in (None, 0) else 0
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE suggestions_cache SET
                    used_count=used_count + 1,
                    success_count=success_count + ?,
                    fail_count=fail_count + ?,
                    exit_code=?,
                    last_used_at=CURRENT_TIMESTAMP
                WHERE full_command=?
                """,
                (success_inc, fail_inc, exit_code, full_command),
            )
            return cursor.rowcount

    def count(self) -> int:
        with self._lock, self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM suggestions_cache").fetchone()[0])

    def get_entry(self, full_command: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM suggestions_cache WHERE full_command=? ORDER BY last_used_at DESC LIMIT 1",
                (full_command,),
            ).fetchone()
        return dict(row) if row else None

    def prune(
        self,
        *,
        max_entries: int | None = None,
        ignored_threshold: int = DEFAULT_IGNORED_PRUNE_THRESHOLD,
        low_value_retention_days: int = DEFAULT_LOW_VALUE_RETENTION_DAYS,
    ) -> int:
        if ignored_threshold < 1:
            raise ValueError("ignored_threshold must be positive")
        if low_value_retention_days < 0:
            raise ValueError("low_value_retention_days must be non-negative")
        with self._lock, self._connect() as conn:
            before = conn.total_changes
            self._prune_conn(
                conn,
                max_entries=max_entries if max_entries is not None else self.max_entries,
                ignored_threshold=ignored_threshold,
                low_value_retention_days=low_value_retention_days,
            )
            return conn.total_changes - before

    def _prune_conn(
        self,
        conn: sqlite3.Connection,
        *,
        max_entries: int,
        ignored_threshold: int = DEFAULT_IGNORED_PRUNE_THRESHOLD,
        low_value_retention_days: int = DEFAULT_LOW_VALUE_RETENTION_DAYS,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        conn.execute(
            """
            DELETE FROM suggestions_cache
            WHERE expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP
            """
        )
        conn.execute(
            """
            DELETE FROM suggestions_cache
            WHERE ignored_count >= ? AND accepted_count = 0
            """,
            (ignored_threshold,),
        )
        conn.execute(
            """
            DELETE FROM suggestions_cache
            WHERE accepted_count = 0
              AND success_count = 0
              AND used_count <= 1
              AND last_used_at < datetime('now', ?)
            """,
            (f"-{low_value_retention_days} days",),
        )
        count = int(conn.execute("SELECT COUNT(*) FROM suggestions_cache").fetchone()[0])
        excess = max(0, count - max_entries)
        if excess:
            conn.execute(
                """
                DELETE FROM suggestions_cache
                WHERE id IN (
                    SELECT id FROM suggestions_cache
                    ORDER BY
                        CASE
                            WHEN accepted_count > 0 OR success_count > 0 OR used_count > 1 THEN 1
                            ELSE 0
                        END ASC,
                        ignored_count DESC,
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
