from daemon.redactor import contains_secret, redact_text


def test_redacts_password_and_tokens():
    text = "DATABASE_URL=postgres://u:p@localhost/db token=abc12345678901234567890"
    redacted = redact_text(text)
    assert "postgres://u:p" not in redacted
    assert "abc123456789" not in redacted
    assert contains_secret(text)


def test_non_secret_command_is_allowed():
    assert not contains_secret("docker compose logs -f backend")


def test_redacts_raw_database_urls_and_bearer_tokens():
    text = "psql postgres://user:pass@localhost/db -c 'select 1' && curl -H 'Bearer abcdefghijklmnopqrstuvwxyz123456'"
    redacted = redact_text(text)

    assert "user:pass" not in redacted
    assert "abcdefghijklmnopqrstuvwxyz" not in redacted
    assert contains_secret(text)
