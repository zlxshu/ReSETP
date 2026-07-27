"""Single-process PR16A/seed1 calibration using the frozen D7 phase-1 code."""

from __future__ import annotations

import importlib.util
import json
import os
import resource
from pathlib import Path
from time import perf_counter, process_time


TASK_DIR = Path(__file__).resolve().parent
REFERENCE = TASK_DIR.parent / "boundary_probe_20260726" / "d7_long_runs_pooled.py"
CALIBRATION_DIR = TASK_DIR / "calibration"
RESULT_PATH = CALIBRATION_DIR / "PR16A__s1.json"
SUMMARY_PATH = TASK_DIR / "calibration_summary.json"


def main() -> int:
    if RESULT_PATH.exists() or SUMMARY_PATH.exists():
        raise FileExistsError("calibration evidence already exists; refusing overwrite")

    spec = importlib.util.spec_from_file_location("resetp_d7_calibration_reference", REFERENCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load reference runner: {REFERENCE}")
    d7 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d7)

    d7.RUNS_DIR = CALIBRATION_DIR
    d7.ITERS = 6200
    d7.K_NOIMPROVE = 4000

    wall_started = perf_counter()
    cpu_started = process_time()
    record = d7._phase1(("PR16A", 1))
    wall_seconds = perf_counter() - wall_started
    cpu_seconds = process_time() - cpu_started
    usage = resource.getrusage(resource.RUSAGE_SELF)

    summary = {
        "schema": "resetp.e2-large-pooled.calibration.v1",
        "task_id": "E2-LARGE-INSTANCE-POOLED-SPRINT-001",
        "reference_runner": str(REFERENCE.relative_to(TASK_DIR.parents[2])),
        "instance_id": "PR16A",
        "seed": 1,
        "iteration_limit": 6200,
        "no_improvement_limit": 4000,
        "iterations_run": record["iterations"],
        "best_cost": record["best_cost"],
        "route_count": len(record["routes"]),
        "wall_seconds": round(wall_seconds, 6),
        "process_cpu_seconds": round(cpu_seconds, 6),
        "max_rss_raw": usage.ru_maxrss,
        "runner_cpu_seconds_field_is_perf_counter_wall": record["cpu_seconds"],
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
