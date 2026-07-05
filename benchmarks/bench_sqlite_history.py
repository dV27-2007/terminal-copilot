from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from common import add_common_args, clamp_iterations, print_results, summarize, time_call

from daemon.history_store import HistoryStore


def command_for(index: int) -> str:
    templates = [
        "docker compose ps",
        "docker compose logs -f backend",
        "docker compose up -d backend",
        "git status --short",
        "pytest tests/ -q",
        "npm run dev",
        "make test",
        "python -m pytest tests/unit -q",
    ]
    base = templates[index % len(templates)]
    return base if index < len(templates) else f"{base} # bench-{index}"


def seed_history(store: HistoryStore, count: int, cwd: str, project_root: str, git_branch: str) -> list[float]:
    samples: list[float] = []
    import time

    for index in range(count):
        start = time.perf_counter_ns()
        store.record_command(
            command_for(index),
            cwd=cwd,
            project_root=project_root,
            git_branch=git_branch,
            exit_code=0 if index % 11 else 1,
            duration_ms=20 + index % 200,
        )
        samples.append((time.perf_counter_ns() - start) / 1_000_000.0)
    return samples


def run_size(size: int, iterations: int, warmup: int) -> list[dict]:
    with tempfile.TemporaryDirectory(prefix="term-copilot-history-bench-") as tmp:
        root = Path(tmp)
        store = HistoryStore(str(root / "history.sqlite3"))
        cwd = str(root / "repo")
        project_root = cwd
        git_branch = "main"

        record_samples = seed_history(store, size, cwd, project_root, git_branch)

        prefix_samples, prefix_result = time_call(
            lambda: store.search_prefix("docker co", cwd=cwd, project_root=project_root, git_branch=git_branch, limit=20),
            iterations=iterations,
            warmup=warmup,
        )
        context_samples, context_result = time_call(
            lambda: store.search_prefix("pytest", cwd=cwd, project_root=project_root, git_branch=git_branch, limit=20),
            iterations=iterations,
            warmup=warmup,
        )
        update_samples, _ = time_call(
            lambda: store.record_command(
                "docker compose ps",
                cwd=cwd,
                project_root=project_root,
                git_branch=git_branch,
                exit_code=0,
                duration_ms=10,
            ),
            iterations=iterations,
            warmup=warmup,
        )

        return [
            summarize(f"record_commands_size_{size}", record_samples, db_commands=store.count_commands()),
            summarize(f"prefix_search_size_{size}", prefix_samples, rows=len(prefix_result or [])),
            summarize(f"context_search_size_{size}", context_samples, rows=len(context_result or [])),
            summarize(f"repeated_update_size_{size}", update_samples, db_commands=store.count_commands()),
        ]


def parse_sizes(raw: str) -> list[int]:
    sizes = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part)
        if value <= 0:
            raise argparse.ArgumentTypeError("sizes must be positive")
        sizes.append(value)
    return sizes or [100, 1000]


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark SQLite command history operations.")
    add_common_args(parser, default_iterations=200)
    parser.add_argument("--sizes", default="100,1000", help="comma-separated command counts")
    args = parser.parse_args()

    results: list[dict] = []
    for size in parse_sizes(args.sizes):
        results.extend(run_size(size, clamp_iterations(args.iterations), clamp_iterations(args.warmup, default=0)))
    print_results("SQLite history benchmark", results, json_output=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
