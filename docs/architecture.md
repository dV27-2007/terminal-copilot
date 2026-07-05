# Architecture

Runtime path:

```text
zsh/bash/fish input
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
- `fish/terminal-copilot.fish`: fish Ctrl+F fallback.
- PowerShell support is staged: install/status/doctor can manage a guarded
  profile block, but the runtime adapter is not implemented yet.

## CLI Tooling

`daemon/main.py` provides the local operational CLI:

```text
daemon      start HTTP plus Unix socket IPC when available
predict     run one local prediction
record      record one executed command
event       record accepted/ignored/executed events
status      print fast local daemon/storage/shell status
doctor      run local PASS/WARN/FAIL diagnostics
install     add managed shell rc blocks
uninstall   remove only managed shell rc blocks
```

Install blocks are delimited with exact markers:

```text
# >>> term-copilot init >>>
# <<< term-copilot init <<<
```

Install is idempotent, uses absolute plugin paths, and creates backups before
modifying existing rc/profile files. Uninstall removes only managed blocks and
does not delete history/cache data. Status and doctor are local-only and do not
enable AI or contact external services.

## Benchmarks

The `benchmarks/` directory contains local-only scripts for measuring the Python
MVP before optimizing it. The default benchmarks use temporary SQLite databases
and standard-library timing. They cover direct prediction, CLI subprocess
prediction, Unix socket and HTTP transport latency, SQLite history operations,
project detection cache behavior, suggestion cache operations, startup/import
cost, and best-effort RSS snapshots. See `docs/performance.md` for run commands,
targets, and interpretation guidance.

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

The zsh adapter uses zsh socket modules for prediction, so the socket hot path
does not spawn Python. It clears stale suggestion state before each prediction
request and records accepted/executed events through a silent background event
helper. Bash and fish remain fallback adapters: they record command execution
and offer a `Ctrl+F` prediction accept helper, but they do not render native
zsh-style ghost text.

PowerShell profile management is available as preparation for a future adapter.
`install --shell powershell` writes a guarded profile block that dot-sources
`powershell/terminal-copilot.ps1` only if that file exists. Because the adapter
is not implemented in this stage, the block binds no keys, sends no requests,
and has no runtime effect.

## Root And Session Context

The regular daemon should normally run as the regular user. Root or sudo shells
connect to that daemon only through an explicit `TERM_COPILOT_SOCKET`, typically
pointing at the user's socket such as
`/home/david/.cache/term-copilot/daemon.sock`.
Without an explicit socket, root-mode shell adapters suppress prediction and
event posting silently and do not use HTTP fallback.

Shell adapters send lightweight session metadata with prediction requests:

```text
shell
cwd
effective_uid
original_user / TERM_COPILOT_USER
TERM_COPILOT_HOME when provided
root_mode
```

Root mode is enabled when the effective uid is `0` or
`TERM_COPILOT_ROOT_MODE=1`. In root mode, zsh, bash and fish prediction adapters
fail silently if no explicit socket is configured and do not use HTTP fallback
for prediction. Normal user shell behavior keeps the existing socket-first,
HTTP-fallback path where supported.

`install --root --socket <path>` writes a managed root rc block only when root
mode is explicitly requested. The block sets `TERM_COPILOT_SOCKET` to the exact
provided path and sets `TERM_COPILOT_ROOT_MODE=1`.

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
adapter emits accepted and command-executed events with session/root metadata,
but it does not emit `suggestion_ignored`; the daemon/store side supports that
event for future adapter wiring and manual CLI testing.

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

## Optional AI Fallback

AI completion is disabled by default and is never part of the shell hot path
unless the daemon settings explicitly enable it. The predictor only reaches the
AI path after secret detection, command-like detection, local history/project
ranking, and cache lookup have failed to produce a strong suggestion.

The AI request is built inside `daemon/ai_client.py` from minimal context:
current command buffer, cursor, shell, root mode, project type, shallow project
signals such as Docker services or package scripts, and a small set of recent
successful commands. The request does not include terminal scrollback. Payloads
are redacted before provider calls, and any context value that still required
secret redaction is dropped from list fields.

AI work is scheduled in bounded background threads keyed by normalized buffer,
cursor, cwd/project root, git branch, shell, root mode and project profile
signals. Identical in-flight requests are deduplicated. Completed results are
stored only in the existing suggestion cache after validation, so stale output
for an older buffer/context cannot be returned for a newer cache key. Provider
timeouts and failures set a short in-memory backoff that skips AI while leaving
local prediction untouched.

Responses must be strict JSON with a command continuation and numeric
confidence. Markdown, explanations, non-continuations, dangerous suggestions,
secret-looking output, and invalid risk values are rejected. Accepted AI
suggestions are then passed back through the normal predictor validation,
command-like gate, safety policy, root-mode rules, and cache validation. In root
mode, AI-sourced suggestions must classify as `safe`.

The provider registry includes `fake`, `gemini`, `groq`, and `openrouter`.
`fake` is local-only for tests and manual validation. The non-fake providers are
small stdlib HTTP skeletons that read API keys only from configured environment
variables, build requests from the sanitized AI payload, normalize provider
responses to the shared JSON contract, and leave final validation to the
predictor/AI client gates. Unknown provider names fail safely.

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
