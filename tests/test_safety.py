from daemon.config import DEFAULT_DANGEROUS_PATTERNS
from daemon.safety import SafetyPolicy


def test_blocks_destructive_ai_suggestion():
    policy = SafetyPolicy(DEFAULT_DANGEROUS_PATTERNS)
    result = policy.classify("rm -rf /", buffer="rm -", root_mode=True, source="ai")
    assert result.risk == "dangerous"
    assert not policy.is_allowed_suggestion("rm -rf /", buffer="rm -", root_mode=True, source="ai")


def test_safe_docker_logs_allowed():
    policy = SafetyPolicy(DEFAULT_DANGEROUS_PATTERNS)
    assert policy.classify("docker compose logs -f backend", buffer="docker compose lo").risk == "safe"
