from pathlib import Path

from daemon.cache_store import CacheStore
from daemon.models import CommandContext, ProjectProfile, Suggestion


def ctx(tmp_path: Path) -> CommandContext:
    return CommandContext(
        buffer="docker co",
        cursor=9,
        cwd=str(tmp_path),
        shell="zsh",
        first_token="docker",
        project_root=str(tmp_path),
        git_branch="dev",
        project=ProjectProfile(project_root=str(tmp_path), project_type="docker", docker_services=["backend"]),
    )


def test_cache_roundtrip(tmp_path: Path):
    store = CacheStore(str(tmp_path / "db.sqlite3"))
    context = ctx(tmp_path)
    suggestion = Suggestion("mpose ps", "docker compose ps", "project_context", 0.8, "safe")
    store.save(context, suggestion)
    loaded = store.lookup(context)
    assert loaded is not None
    assert loaded.full_command == "docker compose ps"
