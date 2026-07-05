from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from common import add_common_args, clamp_iterations, print_results, summarize, time_call

from daemon.project_detector import clear_project_cache, detect_project, project_cache_info


def create_project(root: Path) -> None:
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "docker-compose.yml").write_text(
        "services:\n"
        "  backend:\n"
        "    image: example/backend\n"
        "  worker:\n"
        "    image: example/worker\n"
    )
    (root / "package.json").write_text('{"scripts":{"dev":"vite","test":"vitest","build":"vite build"}}')
    (root / "Makefile").write_text("test:\n\tpytest\nbuild:\n\techo build\n")
    (root / "pytest.ini").write_text("[pytest]\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark cached project context detection.")
    add_common_args(parser, default_iterations=100)
    args = parser.parse_args()
    iterations = clamp_iterations(args.iterations)
    warmup = clamp_iterations(args.warmup, default=0)

    with tempfile.TemporaryDirectory(prefix="term-copilot-project-bench-") as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        create_project(root)
        nested = root / "tests"

        cold_samples, cold_profile = time_call(
            lambda: (clear_project_cache(), detect_project(str(nested)))[1],
            iterations=iterations,
            warmup=warmup,
        )

        clear_project_cache()
        detect_project(str(nested))
        hot_samples, hot_profile = time_call(
            lambda: detect_project(str(nested)),
            iterations=iterations,
            warmup=warmup,
        )

        counter = {"value": 0}

        def invalidate_and_detect():
            counter["value"] += 1
            (root / "package.json").write_text(
                '{"scripts":{"dev":"vite","test":"vitest","bench":"node bench.js","run_%d":"echo ok"}}'
                % counter["value"]
            )
            return detect_project(str(nested))

        invalidation_samples, invalidated_profile = time_call(
            invalidate_and_detect,
            iterations=max(1, min(iterations, 50)),
            warmup=0,
        )

        results = [
            summarize(
                "cold_detect",
                cold_samples,
                project_type=cold_profile.project_type,
                docker_services=len(cold_profile.docker_services),
                package_scripts=len(cold_profile.package_scripts),
            ),
            summarize(
                "hot_cached_detect",
                hot_samples,
                cache_size=project_cache_info()["size"],
                same_marker_hash=hot_profile.marker_hash == cold_profile.marker_hash,
            ),
            summarize(
                "invalidate_after_marker_change",
                invalidation_samples,
                package_scripts=len(invalidated_profile.package_scripts),
                cache_size=project_cache_info()["size"],
            ),
        ]
    print_results("Project detector benchmark", results, json_output=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
