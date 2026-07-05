# Performance

Stage 9 adds lightweight local benchmarks for the Python MVP. The goal is to
measure current behavior repeatably before optimizing or rewriting anything.

Benchmarks use only the Python standard library and existing project code. They
do not enable AI, upload data, modify shell rc files, or touch the real history
database unless you explicitly pass your own paths.

## Safe Default Run

```bash
./venv/bin/python benchmarks/bench_sqlite_history.py
./venv/bin/python benchmarks/bench_project_detector.py
./venv/bin/python benchmarks/bench_cache.py
./venv/bin/python benchmarks/bench_predict_cli.py
./venv/bin/python benchmarks/bench_startup.py
```

Each benchmark prints:

```text
count
min_ms
p50_ms
p95_ms
max_ms
avg_ms
```

Most scripts support:

```bash
--iterations N
--warmup N
--json
```

Use `--json` when capturing results for comparison across commits.

## Running-Daemon Benchmarks

Start a daemon in one terminal:

```bash
export TERM_COPILOT_DB=/tmp/term-copilot-stage9.sqlite3
export TERM_COPILOT_SOCKET=/tmp/term-copilot-stage9.sock
./venv/bin/python -m daemon.main daemon --port 9876
```

Then run:

```bash
./venv/bin/python benchmarks/bench_ipc_socket.py --socket /tmp/term-copilot-stage9.sock
./venv/bin/python benchmarks/bench_http_predict.py --url http://127.0.0.1:9876
```

These scripts intentionally benchmark localhost transports only.

## What Each Benchmark Measures

- `bench_predict_cli.py`
  - first in-process prediction;
  - warm in-process prediction;
  - full CLI subprocess prediction.
- `bench_ipc_socket.py`
  - Unix socket request/response latency against a running daemon.
- `bench_http_predict.py`
  - localhost HTTP `/predict` latency against a running daemon.
- `bench_sqlite_history.py`
  - command record/upsert speed;
  - prefix search;
  - same-context search;
  - repeated command update.
- `bench_project_detector.py`
  - cold project detection;
  - hot cached project detection;
  - cache invalidation after marker changes.
- `bench_cache.py`
  - suggestion cache insert;
  - cache lookup;
  - expired entry rejection;
  - pruning.
- `bench_startup.py`
  - `daemon.main` import cost;
  - CLI `status` subprocess runtime;
  - current process RSS/max RSS where available;
  - optional daemon socket readiness with `--include-daemon`.

## Rough Targets

These are practical MVP targets, not hard guarantees:

- local/cache suggestion target: 5-30 ms from daemon code path;
- cache lookup target: 5-20 ms;
- Unix socket transport should stay much cheaper than CLI subprocess prediction;
- zsh adapter must not spawn Python in the socket prediction path;
- daemon RAM should remain bounded as history/cache grows;
- AI fallback must not block interactive typing.

CLI subprocess prediction is expected to be much slower than daemon/socket
prediction because it pays Python interpreter startup and imports each time.

## Interpreting Results

Compare p50 and p95 first. p50 describes normal interactive feel; p95 catches
occasional pauses that are more visible while typing.

Use the same machine, same Python, and a quiet system when comparing runs. The
absolute numbers are less useful than changes between commits on the same host.

If prediction is slow:

- check `bench_project_detector.py` to see whether project parsing dominates;
- check `bench_sqlite_history.py` for prefix/context query cost;
- check `bench_cache.py` for cache lookup/prune cost;
- compare `bench_predict_cli.py` with `bench_ipc_socket.py` to separate Python
  process startup from daemon hot-path latency.

If memory grows:

- check history/cache retention policies;
- inspect daemon RSS with `bench_startup.py --include-daemon`;
- keep long-running daemon measurements separate from one-shot subprocess
  measurements.

## Known Limitations

- The benchmarks are local microbenchmarks, not full interactive shell traces.
- RSS is best-effort. Linux `/proc/<pid>/status` is used when available;
  otherwise RAM prints as unavailable.
- HTTP and Unix socket benchmarks require a separately running daemon.
- The startup daemon readiness benchmark is optional because it launches a
  temporary daemon process.
- No benchmark reads shell scrollback, `.env`, or external services.

## Next Optimization Decisions

- If CLI subprocess prediction is slow but socket prediction is fast, keep
  investing in shell-to-socket hot-path wiring.
- If socket prediction p95 is high, profile project detection, SQLite search,
  and cache lookup separately.
- If cache lookup is fast but ranking is slow, focus on candidate count and
  scoring work per prediction.
- If daemon startup/import is high, defer Rust migration decisions until the
  measured daemon hot path is understood.
