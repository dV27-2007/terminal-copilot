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

## Suggestion Cache

`daemon/cache_store.py` owns the local `suggestions_cache` table in the same
SQLite database. Cache entries are local-only and store only suggestions that
already passed validation:

- the current buffer and full command must not look secret-like;
- the cached command must be a valid continuation of the buffer;
- the cached command must classify as `safe`;
- dangerous or caution-risk suggestions are not cached.

The cache key is split into an input hash and a context hash. The input hash is
based on the normalized current buffer. The context hash includes the project
root when present, otherwise cwd, plus git branch, shell, root mode, project
type metadata, and the project marker hash. This keeps cached suggestions scoped
to the project shape that produced them without storing large project data in
the key.

Cache entries have a bounded TTL, currently 14 days by default. Lookups ignore
expired rows and still re-check continuation, secret detection, and safety
before returning cache candidates.

Pruning removes:

- expired entries;
- entries ignored too many times with no accepted signal;
- old low-value entries with no accepted/success signal;
- excess entries over the cache cap, preferring to keep accepted, successful,
  and repeatedly used suggestions.

Accepted and ignored events update both command history and any matching cached
suggestion. Command execution updates history success/failure counts and also
marks matching cache rows with used/success/fail counters. The current zsh
adapter emits accepted and command-executed events, but it does not yet emit a
reliable ignored event; the daemon/store side supports `suggestion_ignored` for
future adapter wiring and manual CLI testing.

## Prediction Pipeline

Prediction is local-first and quiet by default. `daemon/predictor.py` now applies
cheap gates before building project/git context:

1. Clamp the cursor to the current buffer.
2. Reject secret-looking input immediately.
3. Reject input that does not look command-like.
4. Build local context only after those checks pass.
5. Collect history candidates and lightweight project-context candidates.
6. Rank and safety-filter candidates.
7. Return strong local history/project candidates immediately and cache safe
   returned suggestions.
8. If no strong local candidate exists, add non-expired cache candidates to the
   same ranking path.
9. Return ghost text only when the full command validly continues the current
   buffer.

Cache candidates use the same deterministic scoring path as history and project
candidates. A cache hit cannot bypass continuation, secret, TTL, or safety
checks. Cache candidates use a stricter confidence threshold than weak local
fallbacks, and strong same-context successful history is considered before cache
lookup.

`daemon/context_detector.py` treats input as command-like when the first token is
on `PATH`, is a known local tool, is present in command history, is a close known
tool typo, or the buffer starts with a known multi-token command such as
`docker compose` or `npm run`.

Natural-language questions and sentences are rejected before shell-character
checks. This includes common English and Russian question starts, mixed text such
as `docker почему не работает`, and common Armenian transliteration question
starts such as `inchpes`/`vonc`. Typo-aware detection only gates whether the input
is eligible for local prediction; it does not invent corrected commands.

## Project Context

`daemon/project_detector.py` detects project roots by walking upward from the
current working directory and checking only known shallow markers:

```text
.git
docker-compose.yml / docker-compose.yaml / compose.yml / compose.yaml
package.json
Makefile / makefile
pyproject.toml / pytest.ini / setup.cfg / requirements.txt / manage.py
tests/
```

Project profiles are cached in memory by project root. Each profile stores the
project root, project types, marker paths, marker mtimes, a marker hash, Docker
Compose services, package scripts, Make targets, pytest candidate paths, and
detected tools. The cache is bounded and invalidated when marker stat metadata
changes. The hot path still stats known marker files, but it does not reparse
project files unless their marker signature changes.

Parsing stays deliberately shallow:

- Docker Compose services are read from known compose files with PyYAML when
  available. Broken YAML returns no services.
- `package.json` scripts are parsed only when the file is under the marker size
  limit. `pnpm` and `yarn` candidates require lockfile or package-manager
  evidence.
- Makefile parsing accepts simple public targets and ignores special/internal
  targets such as `.PHONY`.
- pytest detection checks pytest config files and shallow test directories only;
  it does not recursively scan the repository.

Project-generated candidates include:

```text
docker compose ps
docker compose logs -f <service>
docker compose up -d <service>
docker compose restart <service>
npm run <script>
pnpm run <script>
yarn <script>
make <target>
pytest <path> -q
```

Project candidates enter the same local ranking and safety filtering as history
candidates. They do not include destructive prune commands and do not read `.env`
or secret files.

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
