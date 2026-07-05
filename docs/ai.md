# AI Fallback

AI inline completion is optional and disabled by default. The default daemon
configuration does not call a network provider and shell adapters do not enable
AI.

## Configuration

Defaults live in `config/defaults.yaml`:

```yaml
ai:
  enabled: false
  provider: "gemini"
  model: "gemini-1.5-flash"
  api_key_env: "GEMINI_API_KEY"
  endpoint: ""
  timeout_ms: 1500
  max_input_chars: 2000
  backoff_seconds: 5.0
  max_in_flight: 2
```

Provider metadata lives in `config/providers.yaml`. Environment variables can
override the selected provider and runtime limits:

```text
TERM_COPILOT_AI_ENABLED=1
TERM_COPILOT_AI_PROVIDER=fake
TERM_COPILOT_AI_MODEL=...
TERM_COPILOT_AI_API_KEY_ENV=...
TERM_COPILOT_AI_ENDPOINT=...
TERM_COPILOT_AI_TIMEOUT_MS=1500
TERM_COPILOT_AI_MAX_INPUT_CHARS=2000
TERM_COPILOT_AI_BACKOFF_SECONDS=5
TERM_COPILOT_AI_MAX_IN_FLIGHT=2
```

The provider registry currently supports:

- `fake`: local-only test/manual provider, no network IO;
- `gemini`: Gemini API skeleton using `GEMINI_API_KEY` by default;
- `groq`: Groq chat-completions skeleton using `GROQ_API_KEY` by default;
- `openrouter`: OpenRouter chat-completions skeleton using
  `OPENROUTER_API_KEY` by default.

Unknown providers fail safely and are treated as unavailable. Non-fake providers
require an API key in the configured environment variable before the predictor
considers them available. For local failure testing, set
`TERM_COPILOT_FAKE_AI_MODE=fail` or `TERM_COPILOT_FAKE_AI_MODE=timeout`.

Example live-provider configuration:

```bash
export TERM_COPILOT_AI_ENABLED=1
export TERM_COPILOT_AI_PROVIDER=gemini
export GEMINI_API_KEY=...
```

Provider endpoints are loaded from `config/providers.yaml` and can be overridden
with `TERM_COPILOT_AI_ENDPOINT`. Gemini endpoints may use `{model}` as a
placeholder. Live provider use sends the sanitized command-context payload to
the configured external API.

## Prediction Flow

The predictor only calls AI after:

- the current buffer passes secret detection;
- the buffer looks command-like;
- local history and project-context ranking do not produce a strong suggestion;
- cache lookup does not produce a strong suggestion;
- AI is enabled and the provider is available;
- the current buffer is not dangerous, and root-mode input is safe.

AI is not called for natural-language questions, very short input, dangerous
commands, secret-looking buffers, or when local/cache suggestions are already
strong.

When AI is eligible, the predictor schedules provider work in a bounded
background thread and returns the normal local/cache result or an empty
suggestion immediately. A tiny grace wait lets instant local fake-provider calls
finish during CLI/manual checks, but slow providers are not allowed to become the
interactive hot path. Completed AI output is stored in the existing local
suggestion cache only after full validation. Later identical requests can reuse
that cached result through the normal cache path.

Each AI request is tied to a local request key built from the normalized buffer,
cursor, cwd/project root, git branch, shell, root mode, and project profile
signals. Identical requests share one in-flight provider call. Results for an
older buffer/context are saved under the old cache key and cannot be returned for
a changed buffer/context.

Provider failures and timeouts set an in-memory cooldown controlled by
`backoff_seconds`. During cooldown, AI is skipped and prediction stays local.
The cooldown is process-local and disappears when the daemon restarts.

## Request Contract

The daemon builds a minimal payload with:

- current command buffer and cursor;
- shell and root-mode flags;
- project type and shallow project signals;
- Docker services, package scripts, Make targets, pytest paths;
- a small set of recent successful commands.

Terminal scrollback is not sent. Payloads are redacted before provider calls.
List entries that still contain redaction markers are dropped, so secret-looking
recent commands are not sent as placeholder-bearing strings. If the payload still
exceeds `max_input_chars` after optional context is trimmed, the AI call is
skipped.

Provider skeletons build requests only from this sanitized payload. They do not
read `.env` files, shell scrollback, logs, private keys, or arbitrary project
files. API keys are read only from the configured environment variable and are
sent as provider authentication headers, never inside the prompt body.

## Response Contract

Responses must be strict JSON and must describe a continuation of the current
buffer:

```json
{"full_command":"docker compose logs -f backend","confidence":0.8,"risk":"safe"}
```

The client also accepts a `completion` or `ghost_text` field instead of
`full_command`. Responses are rejected when they contain markdown, explanations,
invalid JSON, non-numeric confidence, confidence outside `0..1`, invalid risk,
dangerous risk, secrets, or commands that do not continue the buffer.

Accepted AI responses still pass through the normal predictor checks:
continuation validation, command-like validation, safety classification,
root-mode restrictions, and cache validation. Root mode only allows AI-sourced
suggestions that classify as `safe`.

Gemini, Groq, and OpenRouter responses are normalized to the same internal JSON
shape before validation. Provider output is never trusted directly: markdown,
explanations, dangerous commands, secrets, invalid confidence/risk, and
non-continuations are rejected by the shared validator.

## Manual Validation

Default behavior should not call AI:

```bash
TERM_COPILOT_DB=/tmp/term-copilot-ai.sqlite3 \
./venv/bin/python -m daemon.main predict "docker compose lo" --cwd "$PWD"
```

Use the local fake provider for deterministic validation without network IO:

```bash
TERM_COPILOT_DB=/tmp/term-copilot-ai.sqlite3 \
TERM_COPILOT_AI_ENABLED=1 \
TERM_COPILOT_AI_PROVIDER=fake \
./venv/bin/python -m daemon.main predict "docker compose lo" --cwd "$PWD"
```

Timeout/failure backoff can be smoke-tested without network IO:

```bash
TERM_COPILOT_DB=/tmp/term-copilot-ai.sqlite3 \
TERM_COPILOT_AI_ENABLED=1 \
TERM_COPILOT_AI_PROVIDER=fake \
TERM_COPILOT_FAKE_AI_MODE=timeout \
./venv/bin/python -m daemon.main predict "docker compose lo" --cwd "$PWD"
```

Natural-language input should stay empty:

```bash
TERM_COPILOT_DB=/tmp/term-copilot-ai.sqlite3 \
TERM_COPILOT_AI_ENABLED=1 \
TERM_COPILOT_AI_PROVIDER=fake \
./venv/bin/python -m daemon.main predict "how do I run docker" --cwd "$PWD"
```

Provider configuration can be checked without a live call by omitting the API
key. Missing keys make the provider unavailable and prediction falls back safely:

```bash
TERM_COPILOT_DB=/tmp/term-copilot-ai.sqlite3 \
TERM_COPILOT_AI_ENABLED=1 \
TERM_COPILOT_AI_PROVIDER=gemini \
TERM_COPILOT_AI_API_KEY_ENV=TERM_COPILOT_MISSING_KEY \
./venv/bin/python -m daemon.main predict "docker compose lo" --cwd "$PWD"
```
