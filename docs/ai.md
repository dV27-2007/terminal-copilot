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
  timeout_ms: 1500
  max_input_chars: 2000
```

Provider metadata lives in `config/providers.yaml`. Environment variables can
override the selected provider and runtime limits:

```text
TERM_COPILOT_AI_ENABLED=1
TERM_COPILOT_AI_PROVIDER=fake
TERM_COPILOT_AI_MODEL=...
TERM_COPILOT_AI_API_KEY_ENV=...
TERM_COPILOT_AI_TIMEOUT_MS=1500
TERM_COPILOT_AI_MAX_INPUT_CHARS=2000
```

The `fake` provider is local-only and intended for tests and manual validation.
It does not perform network IO. Non-fake providers require an API key in the
configured environment variable before the predictor considers them available.

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

Natural-language input should stay empty:

```bash
TERM_COPILOT_DB=/tmp/term-copilot-ai.sqlite3 \
TERM_COPILOT_AI_ENABLED=1 \
TERM_COPILOT_AI_PROVIDER=fake \
./venv/bin/python -m daemon.main predict "how do I run docker" --cwd "$PWD"
```
