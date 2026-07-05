from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request

from common import add_common_args, clamp_iterations, print_results, summarize, time_call


def post_predict(url: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url.rstrip("/") + "/predict",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark localhost HTTP prediction latency against a running daemon.")
    add_common_args(parser, default_iterations=100)
    parser.add_argument("--url", default=os.getenv("TERM_COPILOT_URL", "http://127.0.0.1:8765"))
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--buffer", default="docker co")
    parser.add_argument("--timeout", type=float, default=1.0)
    args = parser.parse_args()

    payload = {
        "buffer": args.buffer,
        "cursor": len(args.buffer),
        "cwd": args.cwd,
        "shell": "bench",
        "root_mode": False,
    }

    def call_http():
        return post_predict(args.url, payload, args.timeout)

    try:
        samples, result = time_call(call_http, iterations=clamp_iterations(args.iterations), warmup=clamp_iterations(args.warmup, default=0))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"HTTP daemon is unavailable at {args.url}: {exc}")
        return 2

    results = [summarize("http_predict", samples, full_command=result.get("full_command"), source=result.get("source"))]
    print_results("HTTP prediction benchmark", results, json_output=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
