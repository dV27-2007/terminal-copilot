from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import load_settings
from .ipc import PROTOCOL_VERSION, UnixSocketPredictionServer, request_prediction, unix_socket_supported
from .models import PredictRequest
from .predictor import Predictor

try:
    import pwd
except ImportError:  # pragma: no cover - non-POSIX fallback
    pwd = None  # type: ignore[assignment]

MANAGED_START = "# >>> term-copilot init >>>"
MANAGED_END = "# <<< term-copilot init <<<"
SUPPORTED_SHELLS = ("zsh", "bash", "fish")
POWERSHELL_SHELL = "powershell"
SHELL_CHOICES = (*SUPPORTED_SHELLS, POWERSHELL_SHELL)
DEFAULT_POWERSHELL_PROFILE_TARGET = "current-user-current-host"
POWERSHELL_PROFILE_TARGETS = {
    "current-user-current-host": ("PowerShell", "Microsoft.PowerShell_profile.ps1"),
    "current-user-all-hosts": ("PowerShell", "profile.ps1"),
    "powershell-7-current-user-current-host": ("PowerShell", "Microsoft.PowerShell_profile.ps1"),
    "powershell-7-current-user-all-hosts": ("PowerShell", "profile.ps1"),
    "windows-powershell-5.1-current-user-current-host": ("WindowsPowerShell", "Microsoft.PowerShell_profile.ps1"),
    "windows-powershell-5.1-current-user-all-hosts": ("WindowsPowerShell", "profile.ps1"),
}


def start_ipc_server(args: argparse.Namespace, settings) -> UnixSocketPredictionServer | None:
    if args.no_ipc or not unix_socket_supported():
        return None
    socket_path = args.socket or os.getenv("TERM_COPILOT_SOCKET") or settings.daemon.socket_path
    server = UnixSocketPredictionServer(Predictor(settings=settings), socket_path)
    try:
        server.start_in_thread()
    except OSError as exc:
        print(f"term-copilot: Unix socket IPC unavailable: {exc}", file=sys.stderr)
        return None
    return server


def run_daemon(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required: pip install -e .", file=sys.stderr)
        return 2
    settings = load_settings(args.config_dir)
    ipc_server = start_ipc_server(args, settings)
    host = args.host or settings.daemon.host
    port = args.port or settings.daemon.port
    try:
        uvicorn.run("daemon.server:app", host=host, port=port, reload=False, log_level=args.log_level)
    finally:
        if ipc_server is not None:
            ipc_server.stop()
    return 0


def predict_once(args: argparse.Namespace) -> int:
    settings = load_settings(args.config_dir)
    predictor = Predictor(settings=settings)
    request = PredictRequest(
        buffer=args.buffer,
        cursor=args.cursor if args.cursor is not None else len(args.buffer),
        cwd=args.cwd or os.getcwd(),
        shell=args.shell,
        effective_uid=os.geteuid() if hasattr(os, "geteuid") else None,
    )
    print(json.dumps(predictor.predict(request).to_dict(), ensure_ascii=False))
    return 0


def record(args: argparse.Namespace) -> int:
    settings = load_settings(args.config_dir)
    predictor = Predictor(settings=settings)
    predictor.record_command(args.command, cwd=args.cwd or os.getcwd(), exit_code=args.exit_code, duration_ms=args.duration_ms, shell=args.shell)
    return 0


def event(args: argparse.Namespace) -> int:
    settings = load_settings(args.config_dir)
    predictor = Predictor(settings=settings)
    if args.event == "command_executed":
        if not args.command:
            print("command_executed requires --command", file=sys.stderr)
            return 2
        predictor.record_command(args.command, cwd=args.cwd or os.getcwd(), exit_code=args.exit_code, duration_ms=args.duration_ms, shell=args.shell)
        return 0
    if args.event in {"suggestion_accepted", "suggestion_ignored"}:
        suggestion = args.suggestion or args.command
        if not suggestion:
            print(f"{args.event} requires --suggestion", file=sys.stderr)
            return 2
        predictor.mark_suggestion(suggestion, accepted=args.event == "suggestion_accepted")
        return 0
    print(f"unknown event: {args.event}", file=sys.stderr)
    return 2


def _shells_from_arg(value: str) -> list[str]:
    if value == "all":
        return list(SUPPORTED_SHELLS)
    if value in SHELL_CHOICES:
        return [value]
    raise ValueError(f"unsupported shell: {value}")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _shell_plugin_path(shell: str) -> Path:
    root = _project_root()
    if shell == "zsh":
        return root / "zsh" / "terminal-copilot.zsh"
    if shell == "bash":
        return root / "bash" / "terminal-copilot.bash"
    if shell == "fish":
        return root / "fish" / "terminal-copilot.fish"
    if shell == POWERSHELL_SHELL:
        return root / "powershell" / "terminal-copilot.ps1"
    raise ValueError(f"unsupported shell: {shell}")


def _powershell_profile_path(
    target: str | None = None,
    *,
    profile_override: str | Path | None = None,
    home: Path | None = None,
) -> Path:
    override = profile_override if profile_override is not None else os.getenv("TERM_COPILOT_POWERSHELL_PROFILE")
    if override:
        return Path(override).expanduser()

    target_name = target or os.getenv("TERM_COPILOT_POWERSHELL_PROFILE_TARGET") or DEFAULT_POWERSHELL_PROFILE_TARGET
    try:
        directory_name, file_name = POWERSHELL_PROFILE_TARGETS[target_name]
    except KeyError as exc:
        supported = ", ".join(sorted(POWERSHELL_PROFILE_TARGETS))
        raise ValueError(f"unsupported PowerShell profile target: {target_name}; expected one of: {supported}") from exc
    return (home or Path.home()) / "Documents" / directory_name / file_name


def _rc_path(shell: str, *, root: bool = False) -> Path:
    if shell == POWERSHELL_SHELL:
        return _powershell_profile_path()
    if shell == "fish":
        return Path("/root/.config/fish/config.fish") if root else Path.home() / ".config" / "fish" / "config.fish"
    if root:
        return Path("/root/.zshrc" if shell == "zsh" else "/root/.bashrc")
    home = Path.home()
    return home / (".zshrc" if shell == "zsh" else ".bashrc")


def _sh_quote(value: str | Path) -> str:
    text = str(value)
    return "'" + text.replace("'", "'\"'\"'") + "'"


def _fish_quote(value: str | Path) -> str:
    text = str(value)
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _powershell_quote(value: str | Path) -> str:
    text = str(value)
    return "'" + text.replace("'", "''") + "'"


def _default_socket_path(settings) -> str:
    return os.getenv("TERM_COPILOT_SOCKET") or settings.daemon.socket_path


def _http_url(settings) -> str:
    return f"http://{settings.daemon.host}:{settings.daemon.port}"


def _root_session_values() -> tuple[str | None, str | None]:
    user = os.getenv("TERM_COPILOT_USER") or os.getenv("SUDO_USER")
    home = os.getenv("TERM_COPILOT_HOME")
    if user and not home and pwd is not None:
        try:
            home = pwd.getpwnam(user).pw_dir
        except KeyError:
            home = None
    return user, home


def _managed_block(shell: str, *, socket_path: str, root: bool = False) -> str:
    plugin = _shell_plugin_path(shell)
    lines = [
        MANAGED_START,
        "# Managed by terminal-copilot. Remove with: python -m daemon.main uninstall",
    ]
    if shell == "fish":
        if root:
            user, home = _root_session_values()
            lines.append(f"set -gx TERM_COPILOT_SOCKET {_fish_quote(socket_path)}")
            if user:
                lines.append(f"set -gx TERM_COPILOT_USER {_fish_quote(user)}")
            if home:
                lines.append(f"set -gx TERM_COPILOT_HOME {_fish_quote(home)}")
            lines.append("set -gx TERM_COPILOT_ROOT_MODE 1")
        else:
            lines.append(f"set -q TERM_COPILOT_SOCKET; or set -gx TERM_COPILOT_SOCKET {_fish_quote(socket_path)}")
        lines.append(f"test -f {_fish_quote(plugin)}; and source {_fish_quote(plugin)}")
    elif shell == POWERSHELL_SHELL:
        lines.append("# PowerShell runtime adapter is staged; this guard is a no-op until it exists.")
        lines.append(f"$TermCopilotAdapter = {_powershell_quote(plugin)}")
        lines.append("if (Test-Path -LiteralPath $TermCopilotAdapter) { . $TermCopilotAdapter }")
    else:
        if root:
            user, home = _root_session_values()
            lines.append(f"export TERM_COPILOT_SOCKET={_sh_quote(socket_path)}")
            if user:
                lines.append(f"export TERM_COPILOT_USER={_sh_quote(user)}")
            if home:
                lines.append(f"export TERM_COPILOT_HOME={_sh_quote(home)}")
            lines.append("export TERM_COPILOT_ROOT_MODE=1")
        else:
            lines.append(f"export TERM_COPILOT_SOCKET=${{TERM_COPILOT_SOCKET:-{_sh_quote(socket_path)}}}")
        lines.append(f"[ -f {_sh_quote(plugin)} ] && source {_sh_quote(plugin)}")
    lines.extend([MANAGED_END, ""])
    return "\n".join(lines)


def _find_managed_blocks(text: str) -> list[tuple[int, int]]:
    lines = text.splitlines(keepends=True)
    blocks: list[tuple[int, int]] = []
    start: int | None = None
    for index, line in enumerate(lines):
        if line.strip() == MANAGED_START:
            start = index
        elif line.strip() == MANAGED_END and start is not None:
            blocks.append((start, index + 1))
            start = None
    return blocks


def _replace_managed_blocks(text: str, block: str) -> tuple[str, int]:
    lines = text.splitlines(keepends=True)
    blocks = _find_managed_blocks(text)
    if not blocks:
        prefix = text
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        return prefix + block, 0

    kept: list[str] = []
    cursor = 0
    for start, end in blocks:
        kept.extend(lines[cursor:start])
        cursor = end
    kept.extend(lines[cursor:])
    prefix = "".join(kept).rstrip() + "\n\n" if "".join(kept).strip() else ""
    return prefix + block, len(blocks)


def _remove_managed_blocks(text: str) -> tuple[str, int]:
    lines = text.splitlines(keepends=True)
    blocks = _find_managed_blocks(text)
    if not blocks:
        return text, 0
    kept: list[str] = []
    cursor = 0
    for start, end in blocks:
        kept.extend(lines[cursor:start])
        cursor = end
    kept.extend(lines[cursor:])
    result = "".join(kept)
    if result and not result.endswith("\n"):
        result += "\n"
    return result, len(blocks)


def _backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.term-copilot.bak")
    counter = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.term-copilot.bak.{counter}")
        counter += 1
    shutil.copy2(path, backup)
    return backup


def install_shell(shell: str, *, socket_path: str, root: bool = False) -> tuple[Path, str]:
    target = _rc_path(shell, root=root)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text(errors="ignore") if target.exists() else ""
    block = _managed_block(shell, socket_path=socket_path, root=root)
    updated, replaced = _replace_managed_blocks(existing, block)
    if updated == existing:
        return target, "already installed"
    backup = _backup_file(target)
    target.write_text(updated)
    if replaced > 1:
        action = f"updated; collapsed {replaced} managed blocks"
    elif replaced == 1:
        action = "updated managed block"
    else:
        action = "installed"
    if backup:
        action += f"; backup {backup}"
    return target, action


def uninstall_shell(shell: str, *, root: bool = False) -> tuple[Path, str]:
    target = _rc_path(shell, root=root)
    if not target.exists():
        return target, "not installed"
    existing = target.read_text(errors="ignore")
    updated, removed = _remove_managed_blocks(existing)
    if removed == 0:
        return target, "not installed"
    backup = _backup_file(target)
    target.write_text(updated)
    action = f"removed {removed} managed block" + ("s" if removed != 1 else "")
    if backup:
        action += f"; backup {backup}"
    return target, action


def _count_table(db_path: str, table: str) -> int | None:
    path = Path(db_path).expanduser()
    if not path.exists():
        return None
    try:
        with sqlite3.connect(path) as conn:
            row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not row:
                return None
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except sqlite3.Error:
        return None


def _socket_status(socket_path: str, *, cwd: str | None = None) -> tuple[bool, str]:
    path = Path(socket_path).expanduser()
    if not unix_socket_supported():
        return False, "unsupported"
    if not path.exists():
        return False, "missing"
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        return False, f"stat failed: {exc}"
    if not stat.S_ISSOCK(mode):
        return False, "path exists but is not a socket"
    try:
        request_prediction(
            str(path),
            {"protocol_version": PROTOCOL_VERSION, "buffer": "", "cursor": 0, "cwd": cwd or os.getcwd(), "shell": "status"},
            timeout=0.2,
        )
    except Exception as exc:
        return False, f"unreachable: {exc}"
    return True, "reachable"


def _http_status(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url + "/health", timeout=0.25) as response:
            if response.status == 200:
                return True, "reachable"
            return False, f"HTTP {response.status}"
    except (urllib.error.URLError, TimeoutError, OSError, socket.timeout) as exc:
        return False, f"unreachable: {exc}"


def _current_euid() -> int | None:
    try:
        return os.geteuid()
    except AttributeError:
        return None


def _env_root_mode(euid: int | None = None) -> bool:
    return os.getenv("TERM_COPILOT_ROOT_MODE") == "1" or euid == 0


def _socket_permission_message(path: Path, *, euid: int | None) -> tuple[str, str] | None:
    if not path.exists():
        return None
    try:
        info = path.stat()
    except OSError as exc:
        return ("WARN", f"socket permission check failed: {path} ({exc})")
    mode = stat.S_IMODE(info.st_mode)
    details = f"socket owner uid={info.st_uid}, mode={oct(mode)}"
    if euid == 0:
        return ("PASS", f"{details}; root can normally open owner-only sockets")
    if euid is not None and euid != info.st_uid and mode & 0o022 == 0:
        return ("WARN", f"{details}; current uid may not be allowed to connect")
    return ("PASS", details)


def _managed_block_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(_find_managed_blocks(path.read_text(errors="ignore")))


def _legacy_integration_present(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(errors="ignore")
    return "terminal-copilot" in text and MANAGED_START not in text


def status(args: argparse.Namespace) -> int:
    settings = load_settings(args.config_dir)
    socket_path = _default_socket_path(settings)
    http_url = _http_url(settings)
    socket_ok, socket_msg = _socket_status(socket_path)
    http_ok, http_msg = _http_status(http_url)
    if socket_ok:
        mode = "Unix socket"
    elif http_ok:
        mode = "HTTP fallback"
    else:
        mode = "unavailable"
    db_path = str(Path(settings.daemon.db_path).expanduser())
    command_count = _count_table(db_path, "commands")
    cache_count = _count_table(db_path, "suggestions_cache")
    zsh_blocks = _managed_block_count(Path.home() / ".zshrc")
    bash_blocks = _managed_block_count(Path.home() / ".bashrc")
    fish_blocks = _managed_block_count(Path.home() / ".config" / "fish" / "config.fish")
    powershell_profile = _powershell_profile_path()
    powershell_blocks = _managed_block_count(powershell_profile)

    print(f"daemon reachable: {'yes' if socket_ok or http_ok else 'no'}")
    print(f"IPC mode: {mode}")
    print(f"socket path: {socket_path}")
    print(f"socket status: {socket_msg}")
    print(f"HTTP URL: {http_url}")
    print(f"HTTP status: {http_msg}")
    print(f"DB path: {db_path}")
    print(f"DB exists: {'yes' if Path(db_path).exists() else 'no'}")
    print(f"command count: {command_count if command_count is not None else 'unknown'}")
    print(f"cache count: {cache_count if cache_count is not None else 'unknown'}")
    print(f"AI enabled: {'yes' if settings.ai.enabled else 'no'}")
    print(f"protocol version: {PROTOCOL_VERSION}")
    print(
        "shell integration: "
        f"zsh blocks={zsh_blocks}, bash blocks={bash_blocks}, "
        f"fish blocks={fish_blocks}, powershell blocks={powershell_blocks}"
    )
    print(f"PowerShell profile path: {powershell_profile}")
    print(f"PowerShell profile exists: {'yes' if powershell_profile.exists() else 'no'}")
    return 0


def _doctor_line(kind: str, message: str) -> tuple[str, bool]:
    print(f"{kind}: {message}")
    return message, kind == "FAIL"


def doctor(args: argparse.Namespace) -> int:
    settings = load_settings(args.config_dir)
    failures = 0
    euid = _current_euid()
    root_mode = _env_root_mode(euid)

    _, failed = _doctor_line("PASS", "Python package import works")
    failures += int(failed)

    _doctor_line("PASS", f"effective uid: {euid if euid is not None else 'unknown'}")
    _doctor_line("PASS" if not root_mode or os.getenv("TERM_COPILOT_ROOT_MODE") == "1" or euid == 0 else "WARN", f"root mode: {'enabled' if root_mode else 'disabled'}")
    socket_env = os.getenv("TERM_COPILOT_SOCKET")
    _doctor_line("PASS" if socket_env else "WARN", f"TERM_COPILOT_SOCKET set: {'yes' if socket_env else 'no'}")
    if root_mode and not socket_env:
        _doctor_line("WARN", "root mode should use an explicit TERM_COPILOT_SOCKET pointing at the user daemon")
    original_user = os.getenv("TERM_COPILOT_USER") or os.getenv("SUDO_USER")
    if root_mode:
        _doctor_line("PASS" if original_user else "WARN", f"original user metadata: {'set' if original_user else 'missing'}")
        _doctor_line("PASS" if os.getenv("TERM_COPILOT_HOME") else "WARN", f"TERM_COPILOT_HOME set: {'yes' if os.getenv('TERM_COPILOT_HOME') else 'no'}")

    db_path = Path(settings.daemon.db_path).expanduser()
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA user_version")
        _, failed = _doctor_line("PASS", f"DB writable: {db_path}")
    except Exception as exc:
        _, failed = _doctor_line("FAIL", f"DB is not writable: {db_path} ({exc})")
    failures += int(failed)

    socket_path = Path(_default_socket_path(settings)).expanduser()
    try:
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        _, failed = _doctor_line("PASS", f"socket directory writable: {socket_path.parent}")
    except Exception as exc:
        _, failed = _doctor_line("FAIL", f"socket directory is not writable: {socket_path.parent} ({exc})")
    failures += int(failed)

    socket_ok, socket_msg = _socket_status(str(socket_path))
    if socket_ok:
        _doctor_line("PASS", f"daemon reachable over Unix socket: {socket_path}")
    elif socket_path.exists():
        try:
            socket_mode = socket_path.stat().st_mode
            kind = "FAIL" if not stat.S_ISSOCK(socket_mode) else "WARN"
        except OSError:
            kind = "WARN"
        _, failed = _doctor_line(kind, f"Unix socket {socket_msg}: {socket_path}")
        failures += int(failed)
    else:
        _doctor_line("WARN", f"daemon socket is not present: {socket_path}")
    permission = _socket_permission_message(socket_path, euid=euid)
    if permission:
        _doctor_line(*permission)

    http_url = _http_url(settings)
    http_ok, http_msg = _http_status(http_url)
    _doctor_line("PASS" if http_ok else "WARN", f"HTTP fallback {http_msg}: {http_url}")

    for shell in SUPPORTED_SHELLS:
        plugin = _shell_plugin_path(shell)
        _, failed = _doctor_line("PASS" if plugin.exists() else "FAIL", f"{shell} plugin file: {plugin}")
        failures += int(failed)

    powershell_adapter = _shell_plugin_path(POWERSHELL_SHELL)
    _doctor_line("PASS" if powershell_adapter.exists() else "WARN", f"PowerShell adapter file: {powershell_adapter}")

    zsh_bin = shutil.which("zsh")
    if zsh_bin:
        proc = subprocess.run([zsh_bin, "-n", str(_shell_plugin_path("zsh"))], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if proc.returncode == 0:
            _doctor_line("PASS", "zsh syntax check passed")
        else:
            _, failed = _doctor_line("FAIL", f"zsh syntax check failed: {proc.stderr.strip()}")
            failures += int(failed)
    else:
        _doctor_line("WARN", "zsh is not installed; skipped zsh syntax check")

    bash_bin = shutil.which("bash")
    if bash_bin:
        proc = subprocess.run([bash_bin, "-n", str(_shell_plugin_path("bash"))], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if proc.returncode == 0:
            _doctor_line("PASS", "bash syntax check passed")
        else:
            _, failed = _doctor_line("FAIL", f"bash syntax check failed: {proc.stderr.strip()}")
            failures += int(failed)
    else:
        _doctor_line("WARN", "bash is not installed; skipped bash syntax check")

    fish_bin = shutil.which("fish")
    if fish_bin:
        proc = subprocess.run([fish_bin, "-n", str(_shell_plugin_path("fish"))], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if proc.returncode == 0:
            _doctor_line("PASS", "fish syntax check passed")
        else:
            _, failed = _doctor_line("FAIL", f"fish syntax check failed: {proc.stderr.strip()}")
            failures += int(failed)
    else:
        _doctor_line("WARN", "fish is not installed; skipped fish syntax check")

    pwsh_bin = shutil.which("pwsh")
    powershell_bin = shutil.which("powershell.exe") or shutil.which("powershell")
    if pwsh_bin or powershell_bin:
        available = ", ".join(path for path in (pwsh_bin, powershell_bin) if path)
        _doctor_line("PASS", f"PowerShell executable available: {available}")
    else:
        _doctor_line("WARN", "PowerShell executable not found; skipped PowerShell syntax check")

    autosuggest_paths = [
        Path.home() / ".oh-my-zsh/custom/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh",
        Path.home() / ".zsh/zsh-autosuggestions/zsh-autosuggestions.zsh",
        Path("/usr/share/zsh-autosuggestions/zsh-autosuggestions.zsh"),
        Path("/usr/local/share/zsh-autosuggestions/zsh-autosuggestions.zsh"),
    ]
    if any(path.exists() for path in autosuggest_paths):
        _doctor_line("PASS", "zsh-autosuggestions appears to be installed")
    else:
        _doctor_line("WARN", "zsh-autosuggestions not found in common locations")

    check_root_rc = root_mode
    for shell in SUPPORTED_SHELLS:
        rc = _rc_path(shell, root=check_root_rc)
        count = _managed_block_count(rc)
        if count == 1:
            _doctor_line("PASS", f"{rc} contains one managed install block")
        elif count > 1:
            _doctor_line("WARN", f"{rc} contains duplicate managed install blocks; rerun install --shell {shell}")
        elif _legacy_integration_present(rc):
            _doctor_line("WARN", f"{rc} has legacy terminal-copilot lines without managed markers")
        else:
            _doctor_line("WARN", f"{rc} has no managed install block")

    powershell_profile = _powershell_profile_path()
    powershell_count = _managed_block_count(powershell_profile)
    _doctor_line(
        "PASS" if powershell_profile.exists() else "WARN",
        f"PowerShell profile {'exists' if powershell_profile.exists() else 'does not exist'}: {powershell_profile}",
    )
    if powershell_count == 1:
        _doctor_line("PASS", f"{powershell_profile} contains one managed install block")
    elif powershell_count > 1:
        _doctor_line("WARN", f"{powershell_profile} contains duplicate managed install blocks; rerun install --shell powershell")
    elif _legacy_integration_present(powershell_profile):
        _doctor_line("WARN", f"{powershell_profile} has legacy terminal-copilot lines without managed markers")
    else:
        _doctor_line("WARN", f"{powershell_profile} has no managed install block")

    config_root = Path(args.config_dir) if args.config_dir else _project_root() / "config"
    for name in ("defaults.yaml", "rules.yaml", "providers.yaml"):
        path = config_root / name
        _doctor_line("PASS" if path.exists() else "WARN", f"config file {'exists' if path.exists() else 'not found, defaults may apply'}: {path}")

    return 1 if failures else 0


def install(args: argparse.Namespace) -> int:
    settings = load_settings(args.config_dir)
    if args.root and args.user:
        print("choose either --user or --root", file=sys.stderr)
        return 2
    if args.root and not args.socket and not os.getenv("TERM_COPILOT_SOCKET"):
        print("install --root requires --socket or TERM_COPILOT_SOCKET", file=sys.stderr)
        return 2
    socket_path = args.socket or _default_socket_path(settings)
    for shell in _shells_from_arg(args.shell):
        target, action = install_shell(shell, socket_path=socket_path, root=args.root)
        print(f"{shell}: {action}: {target}")
    return 0


def uninstall(args: argparse.Namespace) -> int:
    for shell in _shells_from_arg(args.shell):
        target, action = uninstall_shell(shell, root=args.root)
        print(f"{shell}: {action}: {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="term-copilot")
    parser.add_argument("--config-dir", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_daemon = sub.add_parser("daemon")
    p_daemon.add_argument("--host", default=None)
    p_daemon.add_argument("--port", type=int, default=None)
    p_daemon.add_argument("--log-level", default="warning")
    p_daemon.add_argument("--socket", default=None)
    p_daemon.add_argument("--no-ipc", action="store_true")
    p_daemon.set_defaults(func=run_daemon)

    p_predict = sub.add_parser("predict")
    p_predict.add_argument("buffer")
    p_predict.add_argument("--cursor", type=int, default=None)
    p_predict.add_argument("--cwd", default=None)
    p_predict.add_argument("--shell", default="zsh")
    p_predict.set_defaults(func=predict_once)

    p_record = sub.add_parser("record")
    p_record.add_argument("command")
    p_record.add_argument("--cwd", default=None)
    p_record.add_argument("--shell", default="zsh")
    p_record.add_argument("--exit-code", type=int, default=None)
    p_record.add_argument("--duration-ms", type=int, default=None)
    p_record.set_defaults(func=record)

    p_event = sub.add_parser("event")
    p_event.add_argument("event", choices=["command_executed", "suggestion_accepted", "suggestion_ignored"])
    p_event.add_argument("--command", default=None)
    p_event.add_argument("--suggestion", default=None)
    p_event.add_argument("--cwd", default=None)
    p_event.add_argument("--shell", default="zsh")
    p_event.add_argument("--exit-code", type=int, default=None)
    p_event.add_argument("--duration-ms", type=int, default=None)
    p_event.set_defaults(func=event)

    p_status = sub.add_parser("status")
    p_status.set_defaults(func=status)

    p_doctor = sub.add_parser("doctor")
    p_doctor.set_defaults(func=doctor)

    p_install = sub.add_parser("install")
    p_install.add_argument("--user", action="store_true")
    p_install.add_argument("--root", action="store_true")
    p_install.add_argument("--shell", choices=["zsh", "bash", "fish", "powershell", "all"], default="all")
    p_install.add_argument("--socket", default=None)
    p_install.set_defaults(func=install)

    p_uninstall = sub.add_parser("uninstall")
    p_uninstall.add_argument("--root", action="store_true")
    p_uninstall.add_argument("--shell", choices=["zsh", "bash", "fish", "powershell", "all"], default="all")
    p_uninstall.set_defaults(func=uninstall)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
