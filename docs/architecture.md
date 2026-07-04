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

## Local Storage

Command history is stored in local SQLite. `daemon/history_store.py` owns the
`commands` table and uses `PRAGMA user_version` for lightweight schema
versioning. Version 1 creates:

```text
commands(
  id,
  command_text,
  normalized_command,
  cwd,
  project_root,
  git_branch,
  exit_code,
  duration_ms,
  used_count,
  success_count,
  fail_count,
  accepted_count,
  ignored_count,
  source,
  created_at,
  last_used_at
)
```

The history database enables WAL mode during initialization. Prediction-oriented
indexes cover normalized command prefix lookup, case-insensitive prefix lookup,
context ranking by cwd/project/branch, recent commands, and retention cleanup.

Recording is local-only and rejects commands that match the shared secret
detector, including obvious tokens, API keys, passwords, bearer tokens, JWTs,
private key material, database URLs, `.env` paths, and credential-like paths.

Repeated records for the same normalized command and context are updated
in-place with null-safe context matching, so `used_count`, `success_count`,
`fail_count`, `exit_code`, `duration_ms`, and `last_used_at` stay current instead
of creating duplicate nullable-context rows.

Retention is explicit through `cleanup_retention()`. It removes old failed
one-off commands first, then caps total stored commands while preferring to keep
accepted, successful, and frequently used commands.

## Prediction Pipeline

Prediction is local-first and quiet by default. `daemon/predictor.py` now applies
cheap gates before building project/git context:

1. Clamp the cursor to the current buffer.
2. Reject secret-looking input immediately.
3. Reject input that does not look command-like.
4. Build local context only after those checks pass.
5. Collect history candidates and lightweight project-context candidates.
6. Rank and safety-filter candidates.
7. Return ghost text only when the full command validly continues the current
   buffer.

`daemon/context_detector.py` treats input as command-like when the first token is
on `PATH`, is a known local tool, is present in command history, is a close known
tool typo, or the buffer starts with a known multi-token command such as
`docker compose` or `npm run`.

Natural-language questions and sentences are rejected before shell-character
checks. This includes common English and Russian question starts, mixed text such
as `docker почему не работает`, and common Armenian transliteration question
starts such as `inchpes`/`vonc`. Typo-aware detection only gates whether the input
is eligible for local prediction; it does not invent corrected commands.

## Scoring And Safety

Scoring is deterministic and local-only. `daemon/scoring.py` ranks candidates
with explicit weighted signals:

```text
score =
  candidate base score
  + prefix/fuzzy match
  + source reliability
  + same cwd/project/git branch
  + recency
  + log frequency
  + success rate
  + accepted count
  + project relevance
  - ignored count
  - failure/recent-failure penalties
  - risk/root-mode penalties
```

History is the most reliable source, project-context candidates get a smaller
source boost, and placeholder AI-source candidates receive a default penalty.
Strong accepted history in the same cwd/project should outrank project-generated
candidates. Project candidates still work when no strong history result exists.

`score_to_confidence()` maps the bounded deterministic score to `0..0.99`.
Weak candidates can still be returned through the existing low-confidence local
fallback, but dangerous candidates are removed before ranking.

`daemon/safety.py` classifies suggestions as `safe`, `caution`, or `dangerous`.
Dangerous commands are not returned as ghost text. Caution commands are penalized,
with a larger penalty in root mode. Root mode also rejects non-safe AI-source
suggestions if an AI provider is ever enabled.

## Stages

Stage 1: local predictor without AI.

Stage 2: project context.

Stage 3: AI inline completion behind redaction and safety gates.

Stage 4: adaptive learning from accepted/ignored/success/fail events.

Stage 5: daemon auto-start, logs, config reload and hardening.
