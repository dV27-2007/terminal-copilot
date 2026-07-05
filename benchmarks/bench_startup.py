from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from common import PROJECT_ROOT, command_env, print_results, resource_snapshot, summarize, time_call


def import_subprocess() -> float:
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import time; start=time.perf_counter_ns(); import daemon.main; print((time.perf_counter_ns()-start)/1000000)",
        ],
        cwd=PROJECT_ROOT,
        env=command_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10.0,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"import failed with {proc.returncode}")
    return float(proc.stdout.strip())


def status_subprocess(db_path: Path, socket_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "daemon.main", "status"],
        cwd=PROJECT_ROOT,
        env=command_env(db_path=db_path, socket_path=socket_path, port=9),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10.0,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"status failed with {proc.returncode}")


def daemon_ready_time(db_path: Path, socket_path: Path, port: int, timeout: float) -> dict:
    proc = subprocess.Popen(
        [sys.executable, "-m", "daemon.main", "daemon", "--port", str(port), "--socket", str(socket_path), "--log-level", "error"],
        cwd=PROJECT_ROOT,
        env=command_env(db_path=db_path, socket_path=socket_path, port=port),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    start = time.perf_counter()
    ready = False
    try:
        while time.perf_counter() - start < timeout:
            if proc.poll() is not None:
                break
            if socket_path.exists():
                ready = True
                break
            time.sleep(0.02)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        rss = resource_snapshot(proc.pid)
        return {"ready": ready, "elapsed_ms": elapsed_ms, "pid": proc.pid, **rss}
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark startup and lightweight resource usage.")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--include-daemon", action="store_true", help="start a temporary local daemon and measure socket readiness")
    parser.add_argument("--port", type=int, default=9877)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    iterations = max(1, args.iterations)
    with tempfile.TemporaryDirectory(prefix="term-copilot-startup-bench-") as tmp:
        root = Path(tmp)
        db_path = root / "history.sqlite3"
        socket_path = root / "daemon.sock"

        import_samples, import_ms = time_call(import_subprocess, iterations=iterations, warmup=1)
        status_samples, _ = time_call(lambda: status_subprocess(db_path, socket_path), iterations=iterations, warmup=1)

        results = [
            summarize("python_import_daemon_main", import_samples, last_inner_import_ms=import_ms),
            summarize("cli_status_subprocess", status_samples),
            summarize("benchmark_process_resource", [], **resource_snapshot()),
        ]

        if args.include_daemon:
            daemon = daemon_ready_time(db_path, socket_path, args.port, args.timeout)
            results.append(summarize("daemon_socket_readiness", [daemon["elapsed_ms"]], **{k: v for k, v in daemon.items() if k != "elapsed_ms"}))

    print_results("Startup and resource benchmark", results, json_output=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
