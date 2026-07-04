from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .models import Risk


@dataclass(slots=True)
class SafetyResult:
    risk: Risk
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.risk != "dangerous"


class SafetyPolicy:
    def __init__(self, dangerous_patterns: Iterable[str] | None = None):
        self.dangerous_patterns = list(dangerous_patterns or [])
        self._regexes = [self._compile_pattern(p) for p in self.dangerous_patterns]

    @staticmethod
    def _compile_pattern(pattern: str) -> re.Pattern[str]:
        escaped = re.escape(pattern).replace(r"\*", r"\S*")
        escaped = escaped.replace(r"\ ", r"\s+")
        return re.compile(escaped, re.I)

    @staticmethod
    def _normalize(command: str) -> str:
        return " ".join(command.strip().split())

    @staticmethod
    def _lower(command: str) -> str:
        return SafetyPolicy._normalize(command).lower()

    @staticmethod
    def _is_sql_context(command_l: str) -> bool:
        sql_clients = ("psql", "mysql", "sqlite3", "clickhouse-client")
        if command_l.startswith(("drop database", "drop table", "truncate table")):
            return True
        if command_l.startswith(sql_clients):
            return True
        return bool(re.search(r"\b(-c|--command|--execute|--query)\b.*\b(drop\s+database|drop\s+table|truncate\s+table)\b", command_l))

    @staticmethod
    def _matches_destructive_sql(command_l: str) -> str | None:
        if not SafetyPolicy._is_sql_context(command_l):
            return None
        if re.search(r"\bdrop\s+database\b", command_l):
            return "DROP DATABASE"
        if re.search(r"\bdrop\s+table\b", command_l):
            return "DROP TABLE"
        if re.search(r"\btruncate\s+table\b", command_l):
            return "TRUNCATE TABLE"
        return None

    @staticmethod
    def _matches_builtin_danger(command_l: str) -> str | None:
        if re.search(r"^(?:sudo\s+)?rm\s+-[^\s]*r[^\s]*f[^\s]*\s+(?:/|/\*|\*)(?:\s|$)", command_l):
            return "recursive remove of root or wildcard"
        if re.search(r"^(?:sudo\s+)?chmod\s+-r\s+777\s+/(?:\s|$)", command_l):
            return "recursive chmod 777 on root"
        if re.search(r"^(?:sudo\s+)?chown\s+-r\b", command_l):
            return "recursive chown"
        if re.search(r"^(?:sudo\s+)?mkfs(?:\.|\s|$)", command_l):
            return "filesystem format"
        if re.search(r"^(?:sudo\s+)?dd\s+.*\bif=", command_l):
            return "raw disk copy"
        if re.search(r"^docker\s+system\s+prune\b.*(?:\s-a\b|--all\b)", command_l):
            return "docker system prune all"
        if re.search(r"^docker\s+volume\s+prune\b", command_l):
            return "docker volume prune"
        if re.search(r"^(?:sudo\s+)?(?:shutdown|reboot)(?:\s|$)", command_l):
            return "system power command"
        sql_reason = SafetyPolicy._matches_destructive_sql(command_l)
        if sql_reason:
            return sql_reason
        return None

    @staticmethod
    def _matches_caution(command_l: str, *, root_mode: bool) -> str | None:
        if re.search(r"^(?:sudo\s+)?rm\s+", command_l):
            return "file removal"
        if re.search(r"^(?:sudo\s+)?chmod\s+", command_l):
            return "permission change"
        if re.search(r"^(?:sudo\s+)?chown\s+", command_l):
            return "ownership change"
        if re.search(r"^docker\s+compose\s+down(?:\s|$)", command_l):
            return "docker compose down"
        if root_mode and re.search(r"^(?:dd|mount|umount|docker\s+system|docker\s+volume)(?:\s|$)", command_l):
            return "root mode mutation"
        return None

    @staticmethod
    def _config_pattern_is_handled(raw: str) -> bool:
        raw_l = " ".join(raw.lower().split())
        return raw_l in {
            "rm -rf /",
            "rm -rf *",
            "sudo rm -rf",
            "chmod -r 777 /",
            "chown -r",
            "mkfs",
            "dd if=",
            "docker volume prune",
            "docker system prune -a",
            "drop database",
            "drop table",
            "truncate table",
            "shutdown",
            "reboot",
        }

    def classify(self, command: str, *, buffer: str = "", root_mode: bool = False, source: str = "local") -> SafetyResult:
        command_s = self._normalize(command)
        if not command_s:
            return SafetyResult("safe")
        command_l = command_s.lower()

        builtin_reason = self._matches_builtin_danger(command_l)
        if builtin_reason:
            return SafetyResult("dangerous", f"blocked dangerous pattern: {builtin_reason}")

        for raw, regex in zip(self.dangerous_patterns, self._regexes):
            if self._config_pattern_is_handled(raw):
                continue
            if regex.search(command_s):
                return SafetyResult("dangerous", f"blocked dangerous pattern: {raw}")

        caution_reason = self._matches_caution(command_l, root_mode=root_mode)
        if caution_reason:
            if root_mode:
                return SafetyResult("caution", f"root mode caution: {caution_reason}")
            return SafetyResult("caution", caution_reason)

        return SafetyResult("safe")

    def is_allowed_suggestion(self, command: str, *, buffer: str, root_mode: bool, source: str) -> bool:
        result = self.classify(command, buffer=buffer, root_mode=root_mode, source=source)
        if result.risk == "dangerous":
            return False
        if root_mode and source == "ai" and result.risk != "safe":
            return False
        return True
