from __future__ import annotations

import argparse
import os

from common import add_common_args, clamp_iterations, print_results, summarize, time_call

from daemon.ipc import PROTOCOL_VERSION
from daemon.windows_ipc import (
    WindowsPipeError,
    default_pipe_name,
    request_prediction_pipe,
    windows_named_pipe_supported,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark Windows Named Pipe prediction latency against a running daemon."
    )
    add_common_args(parser, default_iterations=200)
    parser.add_argument("--pipe", default=None)
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--buffer", default="docker co")
    parser.add_argument("--timeout", type=float, default=0.5)
    args = parser.parse_args()

    if not windows_named_pipe_supported():
        print("Windows Named Pipes are not supported on this platform; skipping benchmark.")
        return 0

    pipe_name = args.pipe or os.getenv("TERM_COPILOT_PIPE") or default_pipe_name()
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "buffer": args.buffer,
        "cursor": len(args.buffer),
        "cwd": args.cwd,
        "shell": "bench",
        "root_mode": False,
    }

    def call_pipe():
        return request_prediction_pipe(pipe_name, payload, timeout=args.timeout)

    try:
        samples, result = time_call(
            call_pipe,
            iterations=clamp_iterations(args.iterations),
            warmup=clamp_iterations(args.warmup, default=0),
        )
    except (OSError, TimeoutError, WindowsPipeError, EOFError) as exc:
        print(f"Windows Named Pipe daemon is unavailable at {pipe_name}: {exc}")
        return 2

    results = [
        summarize(
            "windows_pipe_predict",
            samples,
            pipe=pipe_name,
            full_command=result.get("full_command"),
            source=result.get("source"),
        )
    ]
    print_results("Windows Named Pipe prediction benchmark", results, json_output=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
