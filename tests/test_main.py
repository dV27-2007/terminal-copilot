from pathlib import Path

from daemon.history_store import HistoryStore
from daemon.main import (
    MANAGED_END,
    MANAGED_START,
    _managed_block,
    _powershell_profile_path,
    _shells_from_arg,
    main,
)


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


def test_status_reports_fish_managed_blocks(tmp_path: Path, monkeypatch, capsys):
    home, _, _ = configure_temp_home(tmp_path, monkeypatch)

    assert main(["install", "--shell", "fish"]) == 0
    assert main(["status"]) == 0

    output = capsys.readouterr().out
    assert "fish blocks=1" in output
    assert (home / ".config" / "fish" / "config.fish").exists()


def test_status_reports_powershell_profile_facts(tmp_path: Path, monkeypatch, capsys):
    configure_temp_home(tmp_path, monkeypatch)
    profile = tmp_path / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    monkeypatch.setenv("TERM_COPILOT_POWERSHELL_PROFILE", str(profile))
    monkeypatch.setenv("TERM_COPILOT_PIPE", r"\\.\pipe\term-copilot-test")

    assert main(["install", "--shell", "powershell"]) == 0
    assert main(["status"]) == 0

    output = capsys.readouterr().out
    assert f"PowerShell profile path: {profile}" in output
    assert "PowerShell profile exists: yes" in output
    assert "powershell blocks=1" in output
    assert "Windows Named Pipe supported: no" in output
    assert "TERM_COPILOT_PIPE set: yes" in output
    assert r"Windows Named Pipe name: \\.\pipe\term-copilot-test" in output


def test_doctor_handles_missing_daemon_without_crashing(tmp_path: Path, monkeypatch, capsys):
    configure_temp_home(tmp_path, monkeypatch)

    assert main(["doctor"]) == 0

    output = capsys.readouterr().out
    assert "PASS: Python package import works" in output
    assert "effective uid:" in output
    assert "root mode:" in output
    assert "TERM_COPILOT_SOCKET set: yes" in output
    assert "WARN: daemon socket is not present" in output
    assert "HTTP fallback unreachable" in output


def test_doctor_reports_powershell_profile_without_requiring_powershell(tmp_path: Path, monkeypatch, capsys):
    configure_temp_home(tmp_path, monkeypatch)
    profile = tmp_path / "PowerShell" / "profile.ps1"
    monkeypatch.setenv("TERM_COPILOT_POWERSHELL_PROFILE", str(profile))
    monkeypatch.setenv("TERM_COPILOT_PIPE", r"\\.\pipe\term-copilot-test")

    assert main(["doctor"]) == 0

    output = capsys.readouterr().out
    assert f"PowerShell profile does not exist: {profile}" in output
    assert "PowerShell adapter file:" in output
    assert "PowerShell executable" in output
    assert "Windows Named Pipe support: unavailable" in output
    assert "TERM_COPILOT_PIPE set: yes" in output
    assert r"Windows Named Pipe name: \\.\pipe\term-copilot-test" in output


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


def test_install_fish_managed_block_is_idempotent_and_backed_up(tmp_path: Path, monkeypatch):
    home, _, socket_path = configure_temp_home(tmp_path, monkeypatch)
    fish_config = home / ".config" / "fish" / "config.fish"
    fish_config.parent.mkdir(parents=True)
    fish_config.write_text("set -gx KEEP_ME 1\n")

    assert main(["install", "--shell", "fish"]) == 0
    assert main(["install", "--shell", "fish"]) == 0

    text = fish_config.read_text()
    assert text.count(MANAGED_START) == 1
    assert text.count(MANAGED_END) == 1
    assert "set -gx KEEP_ME 1" in text
    assert f"set -q TERM_COPILOT_SOCKET; or set -gx TERM_COPILOT_SOCKET '{socket_path}'" in text
    assert "terminal-copilot.fish" in text
    assert list(fish_config.parent.glob("config.fish.term-copilot.bak*"))


def test_powershell_profile_path_supports_override_and_targets(tmp_path: Path, monkeypatch):
    override = tmp_path / "custom" / "profile.ps1"
    monkeypatch.setenv("TERM_COPILOT_POWERSHELL_PROFILE", str(override))

    assert _powershell_profile_path() == override

    monkeypatch.delenv("TERM_COPILOT_POWERSHELL_PROFILE")
    home = tmp_path / "home"
    assert _powershell_profile_path("current-user-current-host", home=home) == (
        home / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    )
    assert _powershell_profile_path("current-user-all-hosts", home=home) == (
        home / "Documents" / "PowerShell" / "profile.ps1"
    )


def test_powershell_managed_block_is_safe_placeholder():
    block = _managed_block("powershell", socket_path="/tmp/unused.sock")

    assert MANAGED_START in block
    assert MANAGED_END in block
    assert "$TermCopilotAdapter =" in block
    assert "Test-Path -LiteralPath $TermCopilotAdapter" in block
    assert "terminal-copilot.ps1" in block
    assert "Set-PSReadLineKeyHandler" not in block
    assert "Invoke-Expression" not in block


def test_install_powershell_creates_profile_and_is_idempotent(tmp_path: Path, monkeypatch):
    configure_temp_home(tmp_path, monkeypatch)
    profile = tmp_path / "nested" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    monkeypatch.setenv("TERM_COPILOT_POWERSHELL_PROFILE", str(profile))

    assert main(["install", "--shell", "powershell"]) == 0
    assert profile.exists()
    assert main(["install", "--shell", "powershell"]) == 0

    text = profile.read_text()
    assert text.count(MANAGED_START) == 1
    assert text.count(MANAGED_END) == 1
    assert "$TermCopilotAdapter =" in text


def test_install_powershell_preserves_content_and_creates_backup(tmp_path: Path, monkeypatch):
    configure_temp_home(tmp_path, monkeypatch)
    profile = tmp_path / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    profile.parent.mkdir(parents=True)
    profile.write_text("Set-Alias ll Get-ChildItem\n")
    monkeypatch.setenv("TERM_COPILOT_POWERSHELL_PROFILE", str(profile))

    assert main(["install", "--shell", "powershell"]) == 0

    text = profile.read_text()
    assert "Set-Alias ll Get-ChildItem" in text
    assert text.count(MANAGED_START) == 1
    assert list(profile.parent.glob("Microsoft.PowerShell_profile.ps1.term-copilot.bak*"))


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


def test_uninstall_fish_removes_only_managed_block(tmp_path: Path, monkeypatch):
    home, _, _ = configure_temp_home(tmp_path, monkeypatch)
    fish_config = home / ".config" / "fish" / "config.fish"
    fish_config.parent.mkdir(parents=True)
    fish_config.write_text("set -gx KEEP_ME 1\n")

    assert main(["install", "--shell", "fish"]) == 0
    assert main(["uninstall", "--shell", "fish"]) == 0

    text = fish_config.read_text()
    assert MANAGED_START not in text
    assert MANAGED_END not in text
    assert "set -gx KEEP_ME 1" in text


def test_uninstall_powershell_removes_only_managed_block(tmp_path: Path, monkeypatch):
    configure_temp_home(tmp_path, monkeypatch)
    profile = tmp_path / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    profile.parent.mkdir(parents=True)
    profile.write_text("Set-Alias gs Get-ChildItem\n")
    monkeypatch.setenv("TERM_COPILOT_POWERSHELL_PROFILE", str(profile))

    assert main(["install", "--shell", "powershell"]) == 0
    assert main(["uninstall", "--shell", "powershell"]) == 0

    text = profile.read_text()
    assert MANAGED_START not in text
    assert MANAGED_END not in text
    assert "Set-Alias gs Get-ChildItem" in text


def test_uninstall_powershell_is_idempotent_when_profile_missing(tmp_path: Path, monkeypatch):
    configure_temp_home(tmp_path, monkeypatch)
    profile = tmp_path / "missing" / "profile.ps1"
    monkeypatch.setenv("TERM_COPILOT_POWERSHELL_PROFILE", str(profile))

    assert main(["uninstall", "--shell", "powershell"]) == 0
    assert not profile.exists()


def test_shell_all_excludes_powershell_profile(tmp_path: Path, monkeypatch):
    configure_temp_home(tmp_path, monkeypatch)
    profile = tmp_path / "PowerShell" / "profile.ps1"
    monkeypatch.setenv("TERM_COPILOT_POWERSHELL_PROFILE", str(profile))

    assert _shells_from_arg("all") == ["zsh", "bash", "fish"]
    assert main(["install", "--shell", "all"]) == 0

    assert not profile.exists()


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


def test_root_install_requires_explicit_socket(tmp_path: Path, monkeypatch, capsys):
    configure_temp_home(tmp_path, monkeypatch)
    monkeypatch.delenv("TERM_COPILOT_SOCKET", raising=False)

    assert main(["install", "--root", "--shell", "zsh"]) == 2

    assert "install --root requires --socket" in capsys.readouterr().err


def test_root_managed_block_uses_exact_socket_and_root_mode(monkeypatch):
    monkeypatch.setenv("TERM_COPILOT_USER", "david")
    monkeypatch.setenv("TERM_COPILOT_HOME", "/home/david")

    block = _managed_block("zsh", socket_path="/home/david/.cache/term-copilot/daemon.sock", root=True)

    assert "export TERM_COPILOT_SOCKET='/home/david/.cache/term-copilot/daemon.sock'" in block
    assert "export TERM_COPILOT_ROOT_MODE=1" in block
    assert "export TERM_COPILOT_USER='david'" in block
    assert "export TERM_COPILOT_HOME='/home/david'" in block
    assert "${TERM_COPILOT_SOCKET:-" not in block


def test_root_fish_managed_block_uses_fish_syntax(monkeypatch):
    monkeypatch.setenv("TERM_COPILOT_USER", "david")
    monkeypatch.setenv("TERM_COPILOT_HOME", "/home/david")

    block = _managed_block("fish", socket_path="/home/david/.cache/term-copilot/daemon.sock", root=True)

    assert "set -gx TERM_COPILOT_SOCKET '/home/david/.cache/term-copilot/daemon.sock'" in block
    assert "set -gx TERM_COPILOT_ROOT_MODE 1" in block
    assert "set -gx TERM_COPILOT_USER 'david'" in block
    assert "set -gx TERM_COPILOT_HOME '/home/david'" in block
    assert "source" in block
    assert "export " not in block
