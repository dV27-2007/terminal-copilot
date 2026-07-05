from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


DEFAULT_KNOWN_COMMANDS = [
    "git", "docker", "pytest", "python", "python3", "pip", "pip3", "npm", "pnpm", "yarn",
    "celery", "psql", "clickhouse-client", "ssh", "scp", "kubectl", "make", "systemctl",
    "journalctl", "cat", "grep", "awk", "sed", "less", "vim", "nano", "code", "uvicorn",
    "fastapi", "alembic", "redis-cli", "curl", "wget", "tar", "zip", "unzip", "rsync", "docker-compose",
]

DEFAULT_TYPOS = {
    "dokcer": "docker",
    "dcoker": "docker",
    "gti": "git",
    "pytes": "pytest",
    "pythno": "python",
    "celrey": "celery",
}

DEFAULT_DANGEROUS_PATTERNS = [
    "rm -rf /", "rm -rf *", "sudo rm -rf", "docker volume prune", "docker system prune -a",
    "DROP DATABASE", "DROP TABLE", "TRUNCATE TABLE", "chmod -R 777 /", "chown -R",
    "mkfs", "dd if=", "shutdown", "reboot",
]


@dataclass(slots=True)
class DaemonSettings:
    host: str = "127.0.0.1"
    port: int = 8765
    socket_path: str = "~/.cache/term-copilot/daemon.sock"
    db_path: str = "~/.local/share/term-copilot/history.sqlite3"
    debounce_ms: int = 300
    max_response_ms: int = 1200


@dataclass(slots=True)
class PredictionSettings:
    min_buffer_length: int = 2
    local_confidence_threshold: float = 0.80
    cache_confidence_threshold: float = 0.75
    ai_confidence_threshold: float = 0.70
    max_candidates: int = 20


@dataclass(slots=True)
class AISettings:
    enabled: bool = False
    provider: str = "gemini"
    model: str = "gemini-1.5-flash"
    api_key_env: str = "GEMINI_API_KEY"
    endpoint: str = ""
    timeout_ms: int = 1500
    max_input_chars: int = 2000
    max_recent_commands: int = 10
    backoff_seconds: float = 5.0
    max_in_flight: int = 2


@dataclass(slots=True)
class SecuritySettings:
    redact_secrets: bool = True
    block_dangerous_ai_suggestions: bool = True


@dataclass(slots=True)
class Settings:
    daemon: DaemonSettings = field(default_factory=DaemonSettings)
    prediction: PredictionSettings = field(default_factory=PredictionSettings)
    ai: AISettings = field(default_factory=AISettings)
    security: SecuritySettings = field(default_factory=SecuritySettings)
    known_commands: list[str] = field(default_factory=lambda: list(DEFAULT_KNOWN_COMMANDS))
    typos: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TYPOS))
    dangerous_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_DANGEROUS_PATTERNS))


def _expand(path: str) -> str:
    return str(Path(os.path.expandvars(os.path.expanduser(path))))


def load_settings(config_dir: str | Path | None = None) -> Settings:
    settings = Settings()
    config_dir = Path(config_dir or os.getenv("TERM_COPILOT_CONFIG_DIR", Path(__file__).resolve().parents[1] / "config"))

    defaults_path = config_dir / "defaults.yaml"
    rules_path = config_dir / "rules.yaml"
    providers_path = config_dir / "providers.yaml"

    if yaml and defaults_path.exists():
        raw = yaml.safe_load(defaults_path.read_text()) or {}
        for section, cls in (("daemon", DaemonSettings), ("prediction", PredictionSettings), ("ai", AISettings), ("security", SecuritySettings)):
            if section in raw and isinstance(raw[section], dict):
                current = getattr(settings, section)
                for key, value in raw[section].items():
                    if hasattr(current, key):
                        setattr(current, key, value)

    settings.ai.provider = os.getenv("TERM_COPILOT_AI_PROVIDER", settings.ai.provider)

    if yaml and providers_path.exists():
        raw = yaml.safe_load(providers_path.read_text()) or {}
        providers = raw.get("providers") if isinstance(raw, dict) else None
        selected = providers.get(settings.ai.provider) if isinstance(providers, dict) else None
        if isinstance(selected, dict):
            if "enabled" in selected:
                settings.ai.enabled = bool(selected["enabled"])
            if isinstance(selected.get("model"), str):
                settings.ai.model = str(selected["model"])
            if isinstance(selected.get("api_key_env"), str):
                settings.ai.api_key_env = str(selected["api_key_env"])
            if isinstance(selected.get("endpoint"), str):
                settings.ai.endpoint = str(selected["endpoint"])
            if isinstance(selected.get("timeout_ms"), int):
                settings.ai.timeout_ms = int(selected["timeout_ms"])
            if isinstance(selected.get("max_input_chars"), int):
                settings.ai.max_input_chars = int(selected["max_input_chars"])
            if isinstance(selected.get("backoff_seconds"), (int, float)):
                settings.ai.backoff_seconds = float(selected["backoff_seconds"])
            if isinstance(selected.get("max_in_flight"), int):
                settings.ai.max_in_flight = int(selected["max_in_flight"])

    if yaml and rules_path.exists():
        raw = yaml.safe_load(rules_path.read_text()) or {}
        if isinstance(raw.get("known_command_prefixes"), list):
            settings.known_commands = sorted(set(settings.known_commands + [str(x).split()[0] for x in raw["known_command_prefixes"]]))
        if isinstance(raw.get("typos"), dict):
            settings.typos.update({str(k): str(v) for k, v in raw["typos"].items()})
        if isinstance(raw.get("dangerous_patterns"), list):
            settings.dangerous_patterns = sorted(set(settings.dangerous_patterns + [str(x) for x in raw["dangerous_patterns"]]))

    settings.daemon.db_path = _expand(os.getenv("TERM_COPILOT_DB", settings.daemon.db_path))
    settings.daemon.socket_path = _expand(os.getenv("TERM_COPILOT_SOCKET", settings.daemon.socket_path))
    settings.daemon.host = os.getenv("TERM_COPILOT_HOST", settings.daemon.host)
    settings.daemon.port = int(os.getenv("TERM_COPILOT_PORT", settings.daemon.port))
    if "TERM_COPILOT_AI_ENABLED" in os.environ:
        settings.ai.enabled = os.getenv("TERM_COPILOT_AI_ENABLED", "").lower() in {"1", "true", "yes", "on"}
    settings.ai.provider = os.getenv("TERM_COPILOT_AI_PROVIDER", settings.ai.provider)
    settings.ai.model = os.getenv("TERM_COPILOT_AI_MODEL", settings.ai.model)
    settings.ai.api_key_env = os.getenv("TERM_COPILOT_AI_API_KEY_ENV", settings.ai.api_key_env)
    settings.ai.endpoint = os.getenv("TERM_COPILOT_AI_ENDPOINT", settings.ai.endpoint)
    settings.ai.timeout_ms = int(os.getenv("TERM_COPILOT_AI_TIMEOUT_MS", settings.ai.timeout_ms))
    settings.ai.max_input_chars = int(os.getenv("TERM_COPILOT_AI_MAX_INPUT_CHARS", settings.ai.max_input_chars))
    settings.ai.backoff_seconds = float(os.getenv("TERM_COPILOT_AI_BACKOFF_SECONDS", settings.ai.backoff_seconds))
    settings.ai.max_in_flight = int(os.getenv("TERM_COPILOT_AI_MAX_IN_FLIGHT", settings.ai.max_in_flight))
    return settings
