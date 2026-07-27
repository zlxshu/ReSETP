"""Two-process memory probe around the frozen D7 phase-1 implementation."""

from __future__ import annotations

import json
import os
import resource
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import perf_counter, process_time


TASK_DIR = Path(__file__).resolve().parent
REFERENCE_DIR = TASK_DIR.parent / "boundary_probe_20260726"
sys.path.insert(0, str(REFERENCE_DIR))

import d7_long_runs_pooled as d7  # noqa: E402


PROBE_DIR = TASK_DIR / "resource_probe_runs"
SUMMARY_PATH = TASK_DIR / "resource_probe_summary.json"

d7.RUNS_DIR = PROBE_DIR
d7.ITERS = 6200
d7.K_NOIMPROVE = 4000


def _rss_mb(raw: int | float) -> float:
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return float(raw) / divisor


def _probe_one(seed: int) -> dict:
    wall_started = perf_counter()
    cpu_started = process_time()
    record = d7._phase1(("PR16A", seed))
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "instance_id": "PR16A",
        "seed": seed,
        "iterations_run": record["iterations"],
        "best_cost": record["best_cost"],
        "route_count": len(record["routes"]),
        "wall_seconds": round(perf_counter() - wall_started, 6),
        "process_cpu_seconds": round(process_time() - cpu_started, 6),
        "peak_rss_mb": round(_rss_mb(usage.ru_maxrss), 6),
    }


def main() -> int:
    if SUMMARY_PATH.exists() or any(PROBE_DIR.glob("*.json")):
        raise FileExistsError("resource probe evidence already exists; refusing overwrite")

    wall_started = perf_counter()
    cpu_started = process_time()
    with ProcessPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(_probe_one, (2, 3)))
    parent_usage = resource.getrusage(resource.RUSAGE_SELF)
    children_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    parent_peak_mb = _rss_mb(parent_usage.ru_maxrss)
    max_child_peak_mb = max(row["peak_rss_mb"] for row in rows)
    estimated_six_worker_peak_mb = parent_peak_mb + 6 * max_child_peak_mb
    selected_workers = 3 if estimated_six_worker_peak_mb > 4096 else 6

    summary = {
        "schema": "resetp.e2-large-pooled.resource-probe.v1",
        "task_id": "E2-LARGE-INSTANCE-POOLED-SPRINT-001",
        "probe_jobs": rows,
        "parallel_workers": 2,
        "iteration_limit_per_job": 6200,
        "no_improvement_limit": 4000,
        "parent_peak_rss_mb": round(parent_peak_mb, 6),
        "children_user_cpu_seconds": round(children_usage.ru_utime, 6),
        "children_system_cpu_seconds": round(children_usage.ru_stime, 6),
        "parent_process_cpu_seconds": round(process_time() - cpu_started, 6),
        "end_to_end_wall_seconds": round(perf_counter() - wall_started, 6),
        "six_worker_peak_estimate_formula": "parent_peak_rss_mb + 6 * max_child_peak_rss_mb",
        "estimated_six_worker_peak_mb": round(estimated_six_worker_peak_mb, 6),
        "memory_threshold_mb": 4096,
        "selected_formal_workers": selected_workers,
        "environment": {
            key: os.environ.get(key)
            for key in (
                "PYTHONHASHSEED",
                "MKL_NUM_THREADS",
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
            )
        },
    }
    tmp = SUMMARY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, SUMMARY_PATH)
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
