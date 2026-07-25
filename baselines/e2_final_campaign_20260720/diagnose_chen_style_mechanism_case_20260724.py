#!/usr/bin/env python3
"""Ten-seed endpoint gate for the disclosed mechanism-illustration case."""

from __future__ import annotations

import json
import multiprocessing as mp
import os
from pathlib import Path
import statistics
import sys
import traceback
from typing import Any


REPO = Path(__file__).resolve().parents[2]
PROTOTYPE = REPO / (
    "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
for path in (REPO / "solver/src", PROTOTYPE, Path(__file__).parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
OUT = Path(__file__).parent / "algorithm_repair_diagnostic_20260724"
PREREG = OUT / "chen_style_mechanism_case_preregistration.json"
RESULT = OUT / "chen_style_mechanism_case_results.json"


def _evaluate(instance_id: str, seed: int) -> dict[str, Any]:
    import run_corrected_china81_d6 as runner
    from route_pool_sp import run_hgs_route_pool_recombination
    from setp_solver.china81 import load_china81_bundle
    from setp_solver.china81_completion import exact_china81_score

    bundle = load_china81_bundle(REPO, instance_id)
    initial = runner._load_initial(instance_id)
    run = run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=seed,
        hgs_seconds_per_view=None,
        exact_elites_per_view=8,
        max_archive_candidates_per_view=24,
        sp_time_limit_seconds=5.0,
        max_hgs_iterations_per_view=5_000,
        wallclock_safety_seconds_per_view=200.0,
    )
    costs = {}
    for label, mode in runner.VIEWS.items():
        epoch = run.view_epochs[mode]
        best = min(
            (*epoch.elite_completions, epoch.proxy_best_completion),
            key=lambda item: item.objective,
        )
        costs[label] = float(best.objective)
    costs["MV-HGS-SP"] = float(run.completion.objective)
    objective, _, violations = exact_china81_score(run.solution, bundle)
    return {
        "seed": seed,
        "status": "PASS" if not violations else "HALT_VIOLATION",
        **{f"{label}_cost": value for label, value in costs.items()},
        "endpoint_recheck_delta": objective - costs["MV-HGS-SP"],
        "complete_attempts": run.stats[
            "complete_candidate_evaluation_attempts"
        ],
        "hgs_iterations": sum(
            int(epoch.stats["hgs_iterations"])
            for epoch in run.view_epochs.values()
        ),
        "selected_source": run.stats["selected_source"],
        "route_pool_size": run.stats["route_pool_size"],
        "wallclock_safety_triggered": run.stats[
            "wallclock_safety_triggered"
        ],
    }


def _worker(task: tuple[str, int]) -> dict[str, Any]:
    try:
        return _evaluate(*task)
    except BaseException as exc:
        return {
            "seed": task[1],
            "status": "HALT_EXCEPTION",
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }


def main() -> int:
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[name] = "1"
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    tasks = [
        (prereg["instance_id"], int(seed)) for seed in prereg["seeds"]
    ]
    with mp.get_context("spawn").Pool(processes=3) as pool:
        rows = pool.map(_worker, tasks)
    comparisons = {}
    for arm in ("HGS-F", "HGS-E", "HGS-M"):
        wins = ties = losses = 0
        for row in rows:
            delta = row["MV-HGS-SP_cost"] - row[f"{arm}_cost"]
            if delta < -1e-9:
                wins += 1
            elif delta > 1e-9:
                losses += 1
            else:
                ties += 1
        comparisons[arm] = {
            "wins": wins,
            "ties": ties,
            "losses": losses,
            "arm_mean": statistics.fmean(
                row[f"{arm}_cost"] for row in rows
            ),
            "main_mean": statistics.fmean(
                row["MV-HGS-SP_cost"] for row in rows
            ),
        }
    invariants = all(
        row.get("status") == "PASS"
        and row.get("complete_attempts") == 80
        and row.get("hgs_iterations") == 15_000
        and abs(row.get("endpoint_recheck_delta", 1.0)) <= 1e-9
        and row.get("wallclock_safety_triggered") is False
        for row in rows
    )
    passed = (
        invariants
        and comparisons["HGS-F"]["wins"] >= 8
        and comparisons["HGS-E"]["wins"] >= 8
        and comparisons["HGS-M"]["wins"] >= 7
        and all(item["losses"] == 0 for item in comparisons.values())
        and all(
            item["main_mean"] < item["arm_mean"] - 1e-9
            for item in comparisons.values()
        )
    )
    payload = {
        "schema": "resetp.chen-style-mechanism-case.v1",
        "formal_evidence": False,
        "verdict": (
            "PASS_CHEN_STYLE_MECHANISM_CASE_ENDPOINT_GATE"
            if passed
            else "HALT_CHEN_STYLE_MECHANISM_CASE_ENDPOINT_GATE"
        ),
        "instance_id": prereg["instance_id"],
        "invariant_pass": invariants,
        "comparisons": comparisons,
        "rows": rows,
    }
    RESULT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(RESULT.read_text(encoding="utf-8"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
