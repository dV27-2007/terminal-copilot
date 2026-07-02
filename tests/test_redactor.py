from daemon.redactor import contains_secret, redact_text


def test_redacts_password_and_tokens():
    text = "DATABASE_URL=postgres://u:p@localhost/db token=abc12345678901234567890"
    redacted = redact_text(text)
    assert "postgres://u:p" not in redacted
    assert "abc123456789" not in redacted
    assert contains_secret(text)


def test_non_secret_command_is_allowed():
    assert not contains_secret("docker compose logs -f backend")
