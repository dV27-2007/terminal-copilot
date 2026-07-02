# Security

Terminal input is high-risk data. It may contain credentials, JWTs, database URLs, API keys, private paths and destructive operational commands.

Implemented baseline:

- suggestions never execute automatically;
- command buffers with obvious secrets produce empty suggestions;
- destructive patterns are blocked or downgraded;
- root mode applies stricter ranking penalties;
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

Before enabling real cloud fallback, enforce:

- client-side redaction;
- server-side redaction verification;
- no full scrollback upload;
- no `.env`, private key or token upload;
- JSON-only AI response validation;
- safety check on `full_command`;
- cache only sanitized prompts and results.
