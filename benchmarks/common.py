from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def add_common_args(parser: argparse.ArgumentParser, *, default_iterations: int = 200) -> None:
    parser.add_argument("--iterations", type=int, default=default_iterations)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--json", action="store_true")


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[index]


def summarize(name: str, samples_ms: list[float], **extra: Any) -> dict[str, Any]:
    if not samples_ms:
        result: dict[str, Any] = {
            "name": name,
            "count": 0,
            "min_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "max_ms": 0.0,
            "avg_ms": 0.0,
        }
    else:
        result = {
            "name": name,
            "count": len(samples_ms),
            "min_ms": min(samples_ms),
            "p50_ms": statistics.median(samples_ms),
            "p95_ms": percentile(samples_ms, 95),
            "max_ms": max(samples_ms),
            "avg_ms": statistics.fmean(samples_ms),
        }
    result.update(extra)
    return result


def time_call(fn: Callable[[], Any], *, iterations: int, warmup: int = 0) -> tuple[list[float], Any]:
    last: Any = None
    for _ in range(max(0, warmup)):
        last = fn()
    samples: list[float] = []
    for _ in range(max(0, iterations)):
        start = time.perf_counter_ns()
        last = fn()
        samples.append((time.perf_counter_ns() - start) / 1_000_000.0)
    return samples, last


def print_results(title: str, results: list[dict[str, Any]], *, json_output: bool = False) -> None:
    payload = {"title": title, "results": results}
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(title)
    for result in results:
        print(f"\n{result['name']}")
        for key, value in result.items():
            if key == "name":
                continue
            if isinstance(value, float):
                print(f"{key}: {value:.3f}")
            else:
                print(f"{key}: {value}")


def command_env(*, db_path: Path | None = None, socket_path: Path | None = None, port: int | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    if db_path is not None:
        env["TERM_COPILOT_DB"] = str(db_path)
    if socket_path is not None:
        env["TERM_COPILOT_SOCKET"] = str(socket_path)
    if port is not None:
        env["TERM_COPILOT_PORT"] = str(port)
    env.setdefault("TERM_COPILOT_PORT", "9")
    return env


def resource_snapshot(pid: int | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"rss_kb": "unavailable", "max_rss_kb": "unavailable"}
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        data["max_rss_kb"] = int(usage.ru_maxrss)
    except Exception:
        pass

    status_path = Path("/proc") / str(pid or os.getpid()) / "status"
    try:
        for line in status_path.read_text(errors="ignore").splitlines():
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2:
                    data["rss_kb"] = int(parts[1])
                break
    except OSError:
        pass
    return data


def clamp_iterations(value: int, *, default: int = 1) -> int:
    return max(default, int(value))
