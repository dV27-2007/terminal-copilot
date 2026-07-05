from __future__ import annotations

import argparse
import sqlite3
import tempfile
from pathlib import Path

from common import add_common_args, clamp_iterations, print_results, summarize, time_call

from daemon.cache_store import CacheStore
from daemon.models import CommandContext, ProjectProfile, Suggestion


def context(root: Path, index: int = 0, *, buffer: str | None = None) -> CommandContext:
    value = buffer or f"docker compose lo{index}"
    return CommandContext(
        buffer=value,
        cursor=len(value),
        cwd=str(root),
        shell="zsh",
        first_token=value.split()[0] if value.split() else "",
        project_root=str(root),
        git_branch="main",
        project=ProjectProfile(
            project_root=str(root),
            project_type="docker",
            project_types=["docker"],
            marker_hash="bench-profile",
            docker_services=["backend"],
            detected_tools=["docker"],
        ),
    )


def suggestion_for(index: int) -> Suggestion:
    prefix = f"docker compose lo{index}"
    full = f"{prefix}gs -f backend"
    return Suggestion(ghost_text="gs -f backend", full_command=full, source="project_context", confidence=0.9, risk="safe")


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark suggestion cache operations.")
    add_common_args(parser, default_iterations=300)
    parser.add_argument("--entries", type=int, default=1000)
    args = parser.parse_args()
    iterations = clamp_iterations(args.iterations)
    warmup = clamp_iterations(args.warmup, default=0)
    entries = max(10, args.entries)

    with tempfile.TemporaryDirectory(prefix="term-copilot-cache-bench-") as tmp:
        root = Path(tmp)
        store = CacheStore(str(root / "cache.sqlite3"), max_entries=max(entries * 2, 100))

        insert_counter = {"value": 0}

        def insert_one():
            index = insert_counter["value"]
            insert_counter["value"] += 1
            return store.save(context(root, index), suggestion_for(index))

        insert_samples, _ = time_call(insert_one, iterations=iterations, warmup=warmup)

        lookup_context = context(root, 0)
        lookup_samples, lookup_result = time_call(lambda: store.lookup(lookup_context), iterations=iterations, warmup=warmup)

        expired_context = context(root, 999_999)
        store.save(expired_context, suggestion_for(999_999))
        with sqlite3.connect(root / "cache.sqlite3") as conn:
            conn.execute("UPDATE suggestions_cache SET expires_at=datetime('now', '-1 day') WHERE full_command=?", (suggestion_for(999_999).full_command,))
        expired_samples, expired_result = time_call(lambda: store.lookup(expired_context), iterations=iterations, warmup=warmup)

        for index in range(entries):
            store.save(context(root, 10_000 + index), suggestion_for(10_000 + index))
        with sqlite3.connect(root / "cache.sqlite3") as conn:
            conn.execute("UPDATE suggestions_cache SET expires_at=datetime('now', '-1 day') WHERE id % 5 = 0")
            conn.execute("UPDATE suggestions_cache SET ignored_count=3 WHERE id % 7 = 0")
            conn.execute("UPDATE suggestions_cache SET last_used_at=datetime('now', '-45 days') WHERE id % 11 = 0")
        prune_samples, deleted = time_call(lambda: store.prune(max_entries=max(50, entries // 2)), iterations=1, warmup=0)

        results = [
            summarize("cache_insert", insert_samples, cache_count=store.count()),
            summarize("cache_lookup", lookup_samples, hit=lookup_result is not None),
            summarize("expired_lookup_rejection", expired_samples, hit=expired_result is not None),
            summarize("cache_prune", prune_samples, deleted=deleted, cache_count=store.count()),
        ]
    print_results("Suggestion cache benchmark", results, json_output=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
