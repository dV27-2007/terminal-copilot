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
        escaped = re.escape(pattern).replace(r"\*", r".*")
        return re.compile(escaped, re.I)

    def classify(self, command: str, *, buffer: str = "", root_mode: bool = False, source: str = "local") -> SafetyResult:
        command_s = " ".join(command.strip().split())
        buffer_s = " ".join(buffer.strip().split())
        if not command_s:
            return SafetyResult("safe")

        for raw, regex in zip(self.dangerous_patterns, self._regexes):
            if regex.search(command_s):
                # If the user explicitly typed the dangerous prefix, do not invent more; classify as caution unless AI generated it.
                if source != "ai" and buffer_s and command_s.lower().startswith(buffer_s.lower()) and len(buffer_s) >= len(raw) * 0.6:
                    return SafetyResult("caution", f"explicit dangerous pattern: {raw}")
                return SafetyResult("dangerous", f"blocked dangerous pattern: {raw}")

        root_caution_tokens = ("rm ", "chmod ", "chown ", "dd ", "mkfs", "mount ", "umount ", "docker system", "docker volume")
        if root_mode and command_s.lower().startswith(root_caution_tokens):
            return SafetyResult("caution", "root mode requires stricter ranking")

        return SafetyResult("safe")

    def is_allowed_suggestion(self, command: str, *, buffer: str, root_mode: bool, source: str) -> bool:
        result = self.classify(command, buffer=buffer, root_mode=root_mode, source=source)
        if result.risk == "dangerous":
            return False
        if root_mode and source == "ai" and result.risk != "safe":
            return False
        return True
