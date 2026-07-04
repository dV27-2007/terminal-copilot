# Architecture

Runtime path:

```text
zsh/bash input
  -> shell integration
  -> local daemon over Unix socket or HTTP fallback
  -> context detector
  -> history/project candidates
  -> scoring + safety
  -> cache / optional AI fallback
  -> ghost suggestion
```

The shell integration is not the brain. It only captures the current buffer, cwd, shell/user/root metadata and sends it to the daemon. The daemon owns history, scoring, safety, cache and AI validation.

## Runtime modules

- `daemon/server.py`: FastAPI daemon API.
- `daemon/ipc.py`: lightweight Unix socket prediction API for Linux/macOS.
- `daemon/predictor.py`: pipeline coordinator.
- `daemon/history_store.py`: SQLite command memory.
- `daemon/cache_store.py`: SQLite suggestion cache.
- `daemon/context_detector.py`: command-like detection and context builder.
- `daemon/project_detector.py`: project root/type parser.
- `daemon/scoring.py`: local ranking.
- `daemon/safety.py`: risk classification.
- `daemon/redactor.py`: client-side redaction utility.
- `zsh/terminal-copilot.zsh`: zsh autosuggestion strategy.
- `bash/terminal-copilot.bash`: bash fallback.

## Local IPC

The daemon now starts a Unix domain socket prediction endpoint on POSIX systems
alongside the existing HTTP API. The default socket path is
`~/.cache/term-copilot/daemon.sock`, or `$TERM_COPILOT_SOCKET` when set. The
socket file is created with owner-only permissions.

The socket protocol is newline-delimited JSON. Each connection sends one request
line and receives one response line. Requests are size-limited and handled with a
strict timeout; invalid JSON, oversized payloads and internal errors return an
empty safe suggestion with an `error`/`reason` field instead of crashing the
daemon.

Minimum prediction request:

```json
{"protocol_version":1,"buffer":"docker co","cursor":9,"cwd":"/repo","shell":"zsh","root_mode":false}
```

The response preserves the existing prediction fields:

```json
{"ghost_text":"mpose ps","full_command":"docker compose ps","source":"history","confidence":0.8,"risk":"safe","reason":""}
```

HTTP on `127.0.0.1:8765` remains available as a compatibility fallback. The zsh
prediction adapter uses the socket path first and falls back to HTTP only when
the socket is unavailable. Command/event recording still uses the existing HTTP
event endpoint.

## Stages

Stage 1: local predictor without AI.

Stage 2: project context.

Stage 3: AI inline completion behind redaction and safety gates.

Stage 4: adaptive learning from accepted/ignored/success/fail events.

Stage 5: daemon auto-start, logs, config reload and hardening.
