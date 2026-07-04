from pathlib import Path

from daemon.config import DEFAULT_DANGEROUS_PATTERNS
from daemon.models import Candidate, CommandContext, ProjectProfile
from daemon.safety import SafetyPolicy
from daemon.scoring import rank_candidates, row_to_candidate, score_candidate, score_to_confidence


def context(tmp_path: Path, *, root_mode: bool = False) -> CommandContext:
    return CommandContext(
        buffer="docker co",
        cursor=9,
        cwd=str(tmp_path / "same"),
        shell="zsh",
        first_token="docker",
        project_root=str(tmp_path / "same"),
        git_branch="dev",
        project=ProjectProfile(project_root=str(tmp_path / "same"), project_type="docker", detected_tools=["docker"]),
        root_mode=root_mode,
    )


def row(command: str, tmp_path: Path, **overrides):
    data = {
        "command_text": command,
        "cwd": str(tmp_path / "same"),
        "project_root": str(tmp_path / "same"),
        "git_branch": "dev",
        "used_count": 5,
        "success_count": 5,
        "fail_count": 0,
        "accepted_count": 0,
        "ignored_count": 0,
        "exit_code": 0,
        "last_used_at": "2099-01-01 00:00:00",
    }
    data.update(overrides)
    return data


def policy() -> SafetyPolicy:
    return SafetyPolicy(DEFAULT_DANGEROUS_PATTERNS)


def score(command_row: dict, tmp_path: Path, *, root_mode: bool = False) -> float:
    return score_candidate(row_to_candidate(command_row), context(tmp_path, root_mode=root_mode), policy())


def test_same_cwd_history_ranks_high(tmp_path: Path):
    ranked = rank_candidates([row_to_candidate(row("docker compose up -d backend celery", tmp_path))], context(tmp_path), policy())

    assert ranked
    assert score_to_confidence(ranked[0][1]) >= 0.8


def test_same_cwd_project_successful_command_ranks_above_unrelated(tmp_path: Path):
    same = row("docker compose ps", tmp_path)
    unrelated = row(
        "docker compose logs",
        tmp_path,
        cwd=str(tmp_path / "other"),
        project_root=str(tmp_path / "other"),
        git_branch="main",
        used_count=10,
        success_count=10,
    )

    ranked = rank_candidates([row_to_candidate(unrelated), row_to_candidate(same)], context(tmp_path), policy())

    assert ranked[0][0].full_command == "docker compose ps"


def test_more_recent_and_frequent_successful_command_ranks_higher(tmp_path: Path):
    frequent = row("docker compose ps", tmp_path, used_count=20, success_count=20, last_used_at="2099-01-01 00:00:00")
    stale = row("docker compose pull", tmp_path, used_count=1, success_count=1, last_used_at="2000-01-01 00:00:00")

    assert score(frequent, tmp_path) > score(stale, tmp_path)


def test_accepted_command_ranks_higher(tmp_path: Path):
    accepted = row("docker compose ps", tmp_path, accepted_count=4)
    plain = row("docker compose pull", tmp_path, accepted_count=0)

    assert score(accepted, tmp_path) > score(plain, tmp_path)


def test_ignored_command_ranks_lower(tmp_path: Path):
    ignored = row("docker compose ps", tmp_path, ignored_count=8)
    plain = row("docker compose pull", tmp_path, ignored_count=0)

    assert score(ignored, tmp_path) < score(plain, tmp_path)


def test_failed_recent_command_ranks_lower(tmp_path: Path):
    failed = row("docker compose ps", tmp_path, used_count=4, success_count=1, fail_count=5, exit_code=1, last_used_at="2099-01-01 00:00:00")
    successful = row("docker compose pull", tmp_path, used_count=4, success_count=4, fail_count=0, exit_code=0, last_used_at="2099-01-01 00:00:00")

    assert score(failed, tmp_path) < score(successful, tmp_path)


def test_dangerous_candidates_are_rejected_from_ranking(tmp_path: Path):
    dangerous = row("rm -rf /", tmp_path)
    safe = row("docker compose ps", tmp_path)

    ranked = rank_candidates([row_to_candidate(dangerous), row_to_candidate(safe)], context(tmp_path), policy())

    assert [candidate.full_command for candidate, _ in ranked] == ["docker compose ps"]


def test_root_mode_penalizes_caution_commands_more_than_normal_mode(tmp_path: Path):
    candidate = Candidate("rm file.txt", "history", metadata=row("rm file.txt", tmp_path))
    normal_context = context(tmp_path, root_mode=False)
    normal_context.buffer = "rm"
    root_context = context(tmp_path, root_mode=True)
    root_context.buffer = "rm"

    assert score_candidate(candidate, root_context, policy()) < score_candidate(candidate, normal_context, policy())


def test_project_context_ranks_below_strong_same_context_history(tmp_path: Path):
    history = row_to_candidate(row("docker compose ps", tmp_path, accepted_count=2))
    project = Candidate("docker compose logs -f backend", "project_context", base_score=65)

    ranked = rank_candidates([project, history], context(tmp_path), policy())

    assert ranked[0][0].source == "history"


def test_confidence_is_bounded():
    assert score_to_confidence(-10) == 0.0
    assert 0.0 < score_to_confidence(90) < 0.99
    assert score_to_confidence(1000) == 0.99
