# Benchmarks

These scripts are local-only benchmarks for the current Python MVP. They use the
standard library plus the project code. They do not enable AI, upload data, or
modify shell rc files.

All storage benchmarks use temporary SQLite databases by default.

## Safe Default Benchmarks

```bash
./venv/bin/python benchmarks/bench_sqlite_history.py
./venv/bin/python benchmarks/bench_project_detector.py
./venv/bin/python benchmarks/bench_cache.py
./venv/bin/python benchmarks/bench_predict_cli.py
./venv/bin/python benchmarks/bench_startup.py
```

Each script prints count, min, p50, p95, max, and average latency in
milliseconds. Most scripts also support:

```bash
--iterations N
--warmup N
--json
```

## Optional Running-Daemon Benchmarks

Start the daemon in another terminal:

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

On native Windows with a daemon started using `--pipe`:

```powershell
.\venv\Scripts\python.exe benchmarks\bench_windows_pipe.py --pipe $env:TERM_COPILOT_PIPE --iterations 200
```

The Windows pipe benchmark exits with a skip message on non-Windows platforms.

## Scripts

- `bench_predict_cli.py`: direct predictor latency, first prediction latency,
  and full CLI subprocess prediction latency.
- `bench_ipc_socket.py`: Unix socket prediction latency against a running
  daemon.
- `bench_windows_pipe.py`: Windows Named Pipe prediction latency against a
  running daemon.
- `bench_http_predict.py`: localhost HTTP prediction latency against a running
  daemon.
- `bench_sqlite_history.py`: history insert/upsert and prefix/context search.
- `bench_project_detector.py`: cold, cached hot, and invalidated project
  detection.
- `bench_cache.py`: suggestion cache insert, lookup, expired rejection, and
  pruning.
- `bench_startup.py`: daemon module import time, CLI status runtime, and
  lightweight resource snapshots. `--include-daemon` also measures temporary
  daemon socket readiness.

## Notes

Benchmarks are intended for trend tracking, not absolute lab-grade numbers. Run
them on an otherwise quiet machine and compare repeated runs on the same host.
