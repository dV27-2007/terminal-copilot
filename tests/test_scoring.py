from pathlib import Path

from daemon.config import DEFAULT_DANGEROUS_PATTERNS
from daemon.models import CommandContext, ProjectProfile
from daemon.safety import SafetyPolicy
from daemon.scoring import rank_candidates, row_to_candidate, score_to_confidence


def test_same_cwd_history_ranks_high(tmp_path: Path):
    row = {
        "command_text": "docker compose up -d backend celery",
        "cwd": str(tmp_path),
        "project_root": str(tmp_path),
        "git_branch": "dev",
        "used_count": 5,
        "success_count": 5,
        "fail_count": 0,
        "accepted_count": 0,
        "ignored_count": 0,
    }
    context = CommandContext(
        buffer="docker co",
        cursor=9,
        cwd=str(tmp_path),
        shell="zsh",
        first_token="docker",
        project_root=str(tmp_path),
        git_branch="dev",
        project=ProjectProfile(project_root=str(tmp_path), project_type="docker"),
    )
    ranked = rank_candidates([row_to_candidate(row)], context, SafetyPolicy(DEFAULT_DANGEROUS_PATTERNS))
    assert ranked
    assert score_to_confidence(ranked[0][1]) >= 0.8
