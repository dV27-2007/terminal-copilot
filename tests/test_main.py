from pathlib import Path

from daemon.history_store import HistoryStore
from daemon.main import MANAGED_END, MANAGED_START, main


def configure_temp_home(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    home = tmp_path / "home"
    home.mkdir()
    db_path = tmp_path / "history.sqlite3"
    socket_path = tmp_path / "daemon.sock"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("TERM_COPILOT_DB", str(db_path))
    monkeypatch.setenv("TERM_COPILOT_SOCKET", str(socket_path))
    monkeypatch.setenv("TERM_COPILOT_PORT", "9")
    return home, db_path, socket_path


def test_cli_event_updates_suggestion_counts(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "history.sqlite3"
    monkeypatch.setenv("TERM_COPILOT_DB", str(db_path))

    assert main(["record", "docker compose ps", "--cwd", str(tmp_path), "--exit-code", "0"]) == 0
    assert main(["event", "suggestion_accepted", "--suggestion", "docker compose ps"]) == 0
    assert main(["event", "suggestion_ignored", "--suggestion", "docker compose ps"]) == 0

    rows = HistoryStore(str(db_path)).search_prefix("docker compose", cwd=str(tmp_path.resolve()), project_root=None, git_branch=None)
    assert rows
    row = rows[0]
    assert row["accepted_count"] == 1
    assert row["ignored_count"] == 1


def test_cli_event_records_command_execution(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "history.sqlite3"
    monkeypatch.setenv("TERM_COPILOT_DB", str(db_path))

    assert main(["event", "command_executed", "--command", "pytest missing.py", "--cwd", str(tmp_path), "--exit-code", "2"]) == 0

    rows = HistoryStore(str(db_path)).search_prefix("pytest", cwd=str(tmp_path.resolve()), project_root=None, git_branch=None)
    assert rows
    row = rows[0]
    assert row["used_count"] == 1
    assert row["fail_count"] == 1


def test_status_works_without_running_daemon_and_reports_db_path(tmp_path: Path, monkeypatch, capsys):
    _, db_path, socket_path = configure_temp_home(tmp_path, monkeypatch)

    assert main(["status"]) == 0

    output = capsys.readouterr().out
    assert "daemon reachable: no" in output
    assert f"socket path: {socket_path}" in output
    assert f"DB path: {db_path}" in output
    assert "AI enabled: no" in output


def test_doctor_handles_missing_daemon_without_crashing(tmp_path: Path, monkeypatch, capsys):
    configure_temp_home(tmp_path, monkeypatch)

    assert main(["doctor"]) == 0

    output = capsys.readouterr().out
    assert "PASS: Python package import works" in output
    assert "WARN: daemon socket is not present" in output
    assert "HTTP fallback unreachable" in output


def test_install_zsh_managed_block_is_idempotent_and_backed_up(tmp_path: Path, monkeypatch):
    home, _, socket_path = configure_temp_home(tmp_path, monkeypatch)
    zshrc = home / ".zshrc"
    zshrc.write_text("alias ll='ls -la'\n")

    assert main(["install", "--shell", "zsh"]) == 0
    assert main(["install", "--shell", "zsh"]) == 0

    text = zshrc.read_text()
    assert text.count(MANAGED_START) == 1
    assert text.count(MANAGED_END) == 1
    assert "alias ll='ls -la'" in text
    assert str(socket_path) in text
    assert list(home.glob(".zshrc.term-copilot.bak*"))


def test_uninstall_removes_only_managed_block(tmp_path: Path, monkeypatch):
    home, _, _ = configure_temp_home(tmp_path, monkeypatch)
    zshrc = home / ".zshrc"
    zshrc.write_text("export KEEP_ME=1\n")

    assert main(["install", "--shell", "zsh"]) == 0
    assert main(["uninstall", "--shell", "zsh"]) == 0

    text = zshrc.read_text()
    assert MANAGED_START not in text
    assert MANAGED_END not in text
    assert "export KEEP_ME=1" in text


def test_install_collapses_duplicate_managed_blocks_safely(tmp_path: Path, monkeypatch):
    home, _, _ = configure_temp_home(tmp_path, monkeypatch)
    zshrc = home / ".zshrc"
    old_block = f"{MANAGED_START}\nold managed content\n{MANAGED_END}\n"
    zshrc.write_text("before\n" + old_block + "middle\n" + old_block + "after\n")

    assert main(["install", "--shell", "zsh"]) == 0

    text = zshrc.read_text()
    assert text.count(MANAGED_START) == 1
    assert "before" in text
    assert "middle" in text
    assert "after" in text
    assert "old managed content" not in text
