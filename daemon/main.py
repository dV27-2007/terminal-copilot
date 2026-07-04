from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import load_settings
from .ipc import UnixSocketPredictionServer, unix_socket_supported
from .models import PredictRequest
from .predictor import Predictor


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


def install(args: argparse.Namespace) -> int:
    project_root = Path(__file__).resolve().parents[1]
    shell_file = project_root / "zsh" / "terminal-copilot.zsh"
    bash_file = project_root / "bash" / "terminal-copilot.bash"
    home = Path.home()
    if args.root:
        zshrc = Path("/root/.zshrc")
        bashrc = Path("/root/.bashrc")
        socket = args.socket or os.getenv("TERM_COPILOT_SOCKET") or str(home / ".cache/term-copilot/daemon.sock")
        block = f"\n# terminal-copilot root integration\nexport TERM_COPILOT_USER={os.getenv('SUDO_USER') or os.getenv('USER') or 'david'}\nexport TERM_COPILOT_SOCKET={socket}\nexport TERM_COPILOT_ROOT_MODE=1\n[ -f {shell_file} ] && source {shell_file}\n[ -f {bash_file} ] && source {bash_file}\n"
        targets = [zshrc, bashrc]
    else:
        block = f"\n# terminal-copilot user integration\nexport TERM_COPILOT_HOME={home}\nexport TERM_COPILOT_SOCKET=${{TERM_COPILOT_SOCKET:-{home}/.cache/term-copilot/daemon.sock}}\n[ -f {shell_file} ] && source {shell_file}\n[ -f {bash_file} ] && source {bash_file}\n"
        targets = [home / ".zshrc", home / ".bashrc"]
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = target.read_text(errors="ignore") if target.exists() else ""
        if "terminal-copilot" not in existing:
            target.write_text(existing + block)
            print(f"updated {target}")
        else:
            print(f"already configured {target}")
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

    p_install = sub.add_parser("install")
    p_install.add_argument("--root", action="store_true")
    p_install.add_argument("--socket", default=None)
    p_install.set_defaults(func=install)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
