from __future__ import annotations

import argparse
import os
from pathlib import Path

from common import add_common_args, clamp_iterations, print_results, summarize, time_call

from daemon.ipc import PROTOCOL_VERSION, request_prediction, unix_socket_supported


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Unix socket prediction latency against a running daemon.")
    add_common_args(parser, default_iterations=200)
    parser.add_argument("--socket", default=os.getenv("TERM_COPILOT_SOCKET", str(Path.home() / ".cache/term-copilot/daemon.sock")))
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--buffer", default="docker co")
    parser.add_argument("--timeout", type=float, default=0.5)
    args = parser.parse_args()

    if not unix_socket_supported():
        print("Unix sockets are not supported on this platform.")
        return 2
    if not Path(args.socket).exists():
        print(f"Socket does not exist: {args.socket}")
        return 2

    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "buffer": args.buffer,
        "cursor": len(args.buffer),
        "cwd": args.cwd,
        "shell": "bench",
        "root_mode": False,
    }

    def call_socket():
        return request_prediction(args.socket, payload, timeout=args.timeout)

    samples, result = time_call(call_socket, iterations=clamp_iterations(args.iterations), warmup=clamp_iterations(args.warmup, default=0))
    results = [summarize("ipc_socket_predict", samples, full_command=result.get("full_command"), source=result.get("source"))]
    print_results("Unix socket prediction benchmark", results, json_output=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
