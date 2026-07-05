# Security

Terminal input is high-risk data. It may contain credentials, JWTs, database URLs, API keys, private paths and destructive operational commands.

Implemented baseline:

- suggestions never execute automatically;
- command buffers with obvious secrets produce empty suggestions;
- dangerous suggestions are blocked before ghost text is returned;
- caution patterns are allowed only with lower ranking confidence;
- root mode applies stricter ranking penalties and blocks non-safe AI suggestions;
- root shell prediction requires an explicit `TERM_COPILOT_SOCKET` and does not
  use HTTP fallback;
- AI is disabled by default;
- optional AI fallback sends only minimal redacted prediction context when
  explicitly enabled;
- command history is local SQLite by default.

Blocked or risky patterns include:

```text
rm -rf /
sudo rm -rf
docker volume prune
docker system prune -a
DROP DATABASE
DROP TABLE
TRUNCATE TABLE
chmod -R 777 /
chown -R
mkfs
dd if=
shutdown
reboot
```

Risk categories:

- `safe`: normal local suggestions such as `docker compose ps`, `git checkout dev`, `pytest tests/ -q`.
- `caution`: commands that mutate local state but are not broad destructive operations, such as `rm file.txt` or `docker compose down`.
- `dangerous`: commands that must not be returned as ghost text, including recursive root/wildcard delete, broad chmod/chown, filesystem formatting, raw `dd if=`, Docker prune-all/volume prune, destructive SQL in SQL contexts, and reboot/shutdown.

SQL terms are treated as dangerous only when the command itself is SQL-like or a
SQL client invocation. Text search such as `grep 'DROP DATABASE' notes.txt` is
not blocked as destructive SQL.

Root mode keeps the same response format but uses stronger penalties for caution
commands involving `rm`, `chmod`, `chown`, `dd`, `mkfs`, Docker system/volume
mutation and mount operations. AI remains disabled by default; if an AI source is
enabled, root mode rejects non-safe AI suggestions.

Optional AI fallback is gated behind local prediction checks. The daemon rejects
secret-looking buffers before context building, only calls AI after local
history, project-context, and cache candidates are weak, and requires an
available configured provider. AI payloads include the current buffer and shallow
cwd/project metadata only; terminal scrollback is not sent. Redaction is applied
before provider calls, and list values that still contain redaction markers are
dropped rather than sent with placeholder secrets.

AI responses must be strict JSON. Markdown, explanations, non-continuations,
dangerous output, secret-looking output, and invalid confidence/risk fields are
discarded before ghost text is returned. Accepted AI responses still pass through
the normal continuation, command-like, safety, root-mode, and cache-validation
checks.

AI provider work is request-keyed and bounded in memory. Identical in-flight
requests are deduplicated, provider failures/timeouts trigger a local cooldown,
and completed AI output is cached only under the exact local context key that
produced it. A result for an older buffer cannot be served to a changed buffer.

The daemon should normally run as the regular user. A root shell can use that
daemon only when the shell environment or root install block explicitly sets
`TERM_COPILOT_SOCKET` to the user's daemon socket and marks
`TERM_COPILOT_ROOT_MODE=1`. Root shell adapters fail silently when this socket is
missing; they do not guess a user's home directory and do not send prediction
requests to HTTP fallback in root mode.

Before enabling real cloud fallback beyond the current local-only fake provider,
enforce:

- client-side redaction;
- server-side redaction verification;
- no full scrollback upload;
- no `.env`, private key or token upload;
- JSON-only AI response validation;
- safety check on `full_command`;
- cache only sanitized prompts and results.
