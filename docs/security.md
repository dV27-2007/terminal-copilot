# Security

Terminal input is high-risk data. It may contain credentials, JWTs, database URLs, API keys, private paths and destructive operational commands.

Implemented baseline:

- suggestions never execute automatically;
- command buffers with obvious secrets produce empty suggestions;
- dangerous suggestions are blocked before ghost text is returned;
- caution patterns are allowed only with lower ranking confidence;
- root mode applies stricter ranking penalties and blocks non-safe AI suggestions;
- AI is disabled by default;
- AI client stub redacts payload before provider calls are added;
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
ever enabled, root mode rejects non-safe AI suggestions.

Before enabling real cloud fallback, enforce:

- client-side redaction;
- server-side redaction verification;
- no full scrollback upload;
- no `.env`, private key or token upload;
- JSON-only AI response validation;
- safety check on `full_command`;
- cache only sanitized prompts and results.
