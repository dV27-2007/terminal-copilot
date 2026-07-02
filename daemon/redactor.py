from __future__ import annotations

import re
from typing import Any

SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)(SECRET_KEY\s*=\s*)[^\s]+"), r"\1<REDACTED>"),
    (re.compile(r"(?i)((?:password|passwd|pwd)\s*=\s*)[^\s]+"), r"\1<REDACTED>"),
    (re.compile(r"(?i)((?:token|access_token|refresh_token|api_key|apikey)\s*=\s*)[^\s]+"), r"\1<REDACTED>"),
    (re.compile(r"(?i)(Authorization:\s*Bearer\s+)[A-Za-z0-9._~+\-/]+=*"), r"\1<REDACTED>"),
    (re.compile(r"(?i)((?:DATABASE_URL|POSTGRES_URL|MYSQL_URL|CLICKHOUSE_PASSWORD|KERNEL_OPROJECT_TOKEN|AWS_SECRET_ACCESS_KEY|OPENAI_API_KEY|GEMINI_API_KEY|GROQ_API_KEY)\s*=\s*)[^\s]+"), r"\1<REDACTED>"),
    (re.compile(r"[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}"), "<JWT_REDACTED>"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "<PRIVATE_KEY_REDACTED>"),
]

SENSITIVE_FILE_PATTERNS = [".env", "id_rsa", "id_ed25519", "credentials", "secrets"]


def redact_text(value: str) -> str:
    result = value
    for pattern, replacement in SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def contains_secret(value: str) -> bool:
    redacted = redact_text(value)
    if redacted != value:
        return True
    lowered = value.lower()
    return any(marker in lowered for marker in SENSITIVE_FILE_PATTERNS)


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, str):
            clean[key] = redact_text(value)
        elif isinstance(value, list):
            clean[key] = [redact_text(x) if isinstance(x, str) else x for x in value]
        elif isinstance(value, dict):
            clean[key] = redact_payload(value)
        else:
            clean[key] = value
    return clean
