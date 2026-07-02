from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .models import CommandContext, Suggestion


class CacheStore:
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
                CREATE TABLE IF NOT EXISTS suggestions_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    input_hash TEXT NOT NULL,
                    context_hash TEXT NOT NULL,
                    buffer TEXT NOT NULL,
                    full_command TEXT NOT NULL,
                    ghost_text TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL,
                    risk TEXT,
                    accepted_count INTEGER DEFAULT 0,
                    ignored_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    expires_at TEXT,
                    UNIQUE(input_hash, context_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_cache_lookup ON suggestions_cache(input_hash, context_hash);
                """
            )

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def keys(self, context: CommandContext) -> tuple[str, str]:
        input_hash = self._hash_payload({"buffer": context.buffer.strip()})
        context_hash = self._hash_payload(
            {
                "project_root": context.project_root,
                "git_branch": context.git_branch,
                "project_type": context.project.project_type,
                "docker_services": context.project.docker_services,
                "package_scripts": context.project.package_scripts,
                "make_targets": context.project.make_targets,
            }
        )
        return input_hash, context_hash

    def lookup(self, context: CommandContext) -> Suggestion | None:
        input_hash, context_hash = self.keys(context)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM suggestions_cache
                WHERE input_hash=? AND context_hash=? AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
                ORDER BY accepted_count DESC, ignored_count ASC, last_used_at DESC
                LIMIT 1
                """,
                (input_hash, context_hash),
            ).fetchone()
        if not row:
            return None
        return Suggestion(
            ghost_text=row["ghost_text"],
            full_command=row["full_command"],
            source=row["source"],
            confidence=float(row["confidence"] or 0.0),
            risk=row["risk"] or "safe",
            reason="cache hit",
        )

    def save(self, context: CommandContext, suggestion: Suggestion) -> None:
        if not suggestion.ghost_text or not suggestion.full_command:
            return
        input_hash, context_hash = self.keys(context)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO suggestions_cache (
                    input_hash, context_hash, buffer, full_command, ghost_text, source, confidence, risk
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(input_hash, context_hash) DO UPDATE SET
                    full_command=excluded.full_command,
                    ghost_text=excluded.ghost_text,
                    source=excluded.source,
                    confidence=excluded.confidence,
                    risk=excluded.risk,
                    last_used_at=CURRENT_TIMESTAMP
                """,
                (input_hash, context_hash, context.buffer, suggestion.full_command, suggestion.ghost_text, suggestion.source, suggestion.confidence, suggestion.risk),
            )

    def mark(self, full_command: str, *, accepted: bool) -> None:
        column = "accepted_count" if accepted else "ignored_count"
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE suggestions_cache SET {column}={column}+1, last_used_at=CURRENT_TIMESTAMP WHERE full_command=?",
                (full_command,),
            )
