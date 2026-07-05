from daemon.config import DEFAULT_DANGEROUS_PATTERNS
from daemon.safety import SafetyPolicy


def policy() -> SafetyPolicy:
    return SafetyPolicy(DEFAULT_DANGEROUS_PATTERNS)


def test_blocks_destructive_ai_suggestion():
    result = policy().classify("rm -rf /", buffer="rm -", root_mode=True, source="ai")
    assert result.risk == "dangerous"
    assert not policy().is_allowed_suggestion("rm -rf /", buffer="rm -", root_mode=True, source="ai")


def test_safe_docker_logs_allowed():
    assert policy().classify("docker compose logs -f backend", buffer="docker compose lo").risk == "safe"


def test_dangerous_spacing_and_case_variations_are_blocked():
    dangerous = [
        "rm    -rf    /",
        "rm -rf /*",
        "sudo   rm   -rf   /",
        "rm -rf *",
        "CHMOD -R 777 /",
        "chown -R root:root /var/app",
        "mkfs.ext4 /dev/sda",
        "dd if=/dev/zero of=/dev/sda",
        "docker system prune --all",
        "docker system prune -a",
        "docker volume prune",
        "DROP DATABASE prod",
        "drop table users",
        "TrUnCaTe TaBlE events",
        "shutdown now",
        "reboot",
    ]
    for command in dangerous:
        assert policy().classify(command).risk == "dangerous", command
        assert not policy().is_allowed_suggestion(command, buffer=command[:4], root_mode=False, source="history")


def test_sql_words_in_non_sql_command_are_not_dangerous():
    assert policy().classify("grep 'DROP DATABASE' notes.txt").risk == "safe"
    assert policy().classify("cat truncate table notes.txt").risk == "safe"


def test_destructive_sql_in_client_context_is_dangerous():
    assert policy().classify("psql -c 'DROP DATABASE prod'").risk == "dangerous"
    assert policy().classify("mysql --execute 'DROP TABLE users'").risk == "dangerous"


def test_caution_commands_are_not_treated_like_root_delete():
    assert policy().classify("rm file.txt").risk == "caution"
    assert policy().classify("docker compose down").risk == "caution"
    assert policy().classify("docker compose ps").risk == "safe"


def test_root_mode_is_stricter_for_mutation_commands():
    normal = policy().classify("dd of=/tmp/out if=/tmp/in", root_mode=False)
    root = policy().classify("dd of=/tmp/out if=/tmp/in", root_mode=True)

    assert normal.risk == "dangerous"
    assert root.risk == "dangerous"
    assert not policy().is_allowed_suggestion("rm file.txt", buffer="rm", root_mode=True, source="ai")


def test_root_mode_marks_caution_with_root_reason():
    normal = policy().classify("rm file.txt", buffer="rm", root_mode=False, source="history")
    root = policy().classify("rm file.txt", buffer="rm", root_mode=True, source="history")

    assert normal.risk == "caution"
    assert normal.reason == "file removal"
    assert root.risk == "caution"
    assert root.reason.startswith("root mode caution")
