from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from common import PROJECT_ROOT, add_common_args, clamp_iterations, command_env, print_results, summarize, time_call

from daemon.cache_store import CacheStore
from daemon.config import Settings
from daemon.history_store import HistoryStore
from daemon.models import PredictRequest
from daemon.predictor import Predictor


def make_predictor(db_path: Path) -> Predictor:
    settings = Settings()
    settings.daemon.db_path = str(db_path)
    settings.ai.enabled = False
    history = HistoryStore(str(db_path))
    cache = CacheStore(str(db_path))
    predictor = Predictor(settings=settings, history=history, cache=cache)
    predictor.record_command("docker compose ps", cwd=str(db_path.parent), exit_code=0, duration_ms=20)
    predictor.record_command("docker compose logs -f backend", cwd=str(db_path.parent), exit_code=0, duration_ms=25)
    predictor.record_command("pytest tests/ -q", cwd=str(db_path.parent), exit_code=0, duration_ms=30)
    return predictor


def cli_predict(db_path: Path, cwd: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "daemon.main", "predict", "docker co", "--cwd", str(cwd)],
        cwd=PROJECT_ROOT,
        env=command_env(db_path=db_path),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5.0,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"predict failed with {proc.returncode}")
    return json.loads(proc.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark direct and CLI prediction latency.")
    add_common_args(parser, default_iterations=50)
    args = parser.parse_args()
    iterations = clamp_iterations(args.iterations)
    warmup = clamp_iterations(args.warmup, default=0)

    with tempfile.TemporaryDirectory(prefix="term-copilot-predict-bench-") as tmp:
        root = Path(tmp)
        db_path = root / "history.sqlite3"
        predictor = make_predictor(db_path)
        request = PredictRequest(buffer="docker co", cwd=str(root), shell="zsh")

        start = time.perf_counter_ns()
        first = predictor.predict(request)
        first_ms = [(time.perf_counter_ns() - start) / 1_000_000.0]

        direct_samples, direct_result = time_call(lambda: predictor.predict(request), iterations=iterations, warmup=warmup)
        cli_samples, cli_result = time_call(lambda: cli_predict(db_path, root), iterations=iterations, warmup=min(warmup, 3))

        results = [
            summarize("direct_first_prediction", first_ms, full_command=first.full_command, source=first.source),
            summarize("direct_warm_prediction", direct_samples, full_command=direct_result.full_command, source=direct_result.source),
            summarize("cli_predict_subprocess", cli_samples, full_command=cli_result.get("full_command"), source=cli_result.get("source")),
        ]
    print_results("Prediction benchmark", results, json_output=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
