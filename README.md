# Terminal Copilot

Local-first inline shell command predictor for terminal sessions. The MVP implements:

- local daemon on `127.0.0.1:8765`;
- SQLite command memory;
- history-based prediction;
- project-context prediction from `docker-compose.yml`, `package.json`, `Makefile`, `pytest` paths;
- zsh ghost suggestions through `zsh-autosuggestions` custom strategy;
- bash fallback with command recording and `Ctrl+F` manual accept;
- safety filtering for destructive commands;
- secret redaction before any future AI fallback;
- root/session-aware fields for `sudo su`, `sudo -i`, `tmux`, `screen`, and remote installs.

AI is disabled by default. The current implementation is Stage 1 + part of Stage 2. The AI provider interface exists, but it returns empty suggestions until a provider is configured and validated.

## Install locally

```bash
cd terminal-copilot
python -m venv .venv
source .venv/bin/activate
pip install -e .[test]
./scripts/install.sh
```

Install `zsh-autosuggestions` if it is not already installed. This project uses it only as the UI layer; the daemon remains the prediction brain.

Start the daemon:

```bash
term-predictord
```

or:

```bash
python -m daemon.main daemon
```

Restart zsh:

```bash
exec zsh
```

## Test manually

Record a successful command:

```bash
term-copilot record "docker compose up -d backend celery" --cwd "$PWD" --exit-code 0
```

Ask for a prediction:

```bash
term-copilot predict "docker co" --cwd "$PWD"
```

Expected JSON shape:

```json
{
  "ghost_text": "mpose up -d backend celery",
  "full_command": "docker compose up -d backend celery",
  "source": "history",
  "confidence": 0.8,
  "risk": "safe"
}
```

## Root / sudo support

The daemon should normally run as the regular user. Root shells connect back to the user's daemon through explicit environment variables:

```bash
export TERM_COPILOT_USER=david
export TERM_COPILOT_SOCKET=/home/david/.cache/term-copilot/daemon.sock
export TERM_COPILOT_ROOT_MODE=1
```

Install root shell integration separately:

```bash
sudo term-copilot install --root --socket /home/david/.cache/term-copilot/daemon.sock
```

In root mode, destructive commands are downgraded or blocked more aggressively. AI suggestions are not allowed to invent destructive commands.

## HTTP API

`POST /predict`

```json
{
  "buffer": "docker compose lo",
  "cursor": 17,
  "cwd": "/home/david/Desktop/work/O_Project",
  "shell": "zsh"
}
```

`POST /events`

```json
{
  "event": "command_executed",
  "command": "docker compose logs -f backend",
  "cwd": "/home/david/Desktop/work/O_Project",
  "exit_code": 0,
  "duration_ms": 1532,
  "shell": "zsh"
}
```

## Current limitations

- zsh ghost text depends on `zsh-autosuggestions`.
- bash cannot display native ghost text; it records commands and can accept a prediction with `Ctrl+F`.
- Unix socket is represented in config, but MVP serving uses localhost HTTP for simpler shell integration.
- AI providers are intentionally stubbed until the redaction/validation path is fully tested with real API keys.
