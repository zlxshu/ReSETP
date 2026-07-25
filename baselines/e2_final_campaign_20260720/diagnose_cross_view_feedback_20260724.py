#!/usr/bin/env python3
"""Preregistered development gate for cross-view complete-elite feedback."""

from __future__ import annotations

import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
import traceback
from typing import Any


REPO = Path(__file__).resolve().parents[2]
PROTOTYPE = (
    REPO / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
for path in (REPO / "solver/src", PROTOTYPE, Path(__file__).parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

OUT = Path(__file__).parent / "algorithm_repair_diagnostic_20260724"
PREREG = OUT / "cross_view_feedback_preregistration.json"
RESULT = OUT / "cross_view_feedback_panel_results.json"


def _evaluate(instance_id: str, seed: int) -> dict[str, Any]:
    import run_corrected_china81_d6 as runner
    from cross_view_feedback import run_cross_view_feedback
    from route_pool_sp import run_hgs_route_pool_recombination
    from setp_solver.china81 import load_china81_bundle
    from setp_solver.china81_completion import exact_china81_score

    bundle = load_china81_bundle(REPO, instance_id)
    initial = runner._load_initial(instance_id)
    customers = sum(
        node.node_type.lower() == "c"
        for node in bundle.instance.nodes
    )
    safety = max(180.0, 2.0 * customers)
    control = run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=seed,
        hgs_seconds_per_view=None,
        exact_elites_per_view=8,
        max_archive_candidates_per_view=24,
        sp_time_limit_seconds=5.0,
        hard_home_depot_lock=False,
        max_hgs_iterations_per_view=5_000,
        wallclock_safety_seconds_per_view=safety,
    )
    candidate = run_cross_view_feedback(
        bundle,
        initial,
        seed=seed,
        max_hgs_iterations_per_view=5_000,
        archive_candidates_per_stage=11,
        feedback_elite_count=8,
        exact_elites_per_stage=8,
        sp_time_limit_seconds=5.0,
        wallclock_safety_seconds_per_stage=safety,
        hard_home_depot_lock=False,
    )
    control_obj, _, control_violations = exact_china81_score(
        control.solution,
        bundle,
    )
    candidate_obj, _, candidate_violations = exact_china81_score(
        candidate.solution,
        bundle,
    )
    delta = candidate_obj - control_obj
    return {
        "instance_id": instance_id,
        "seed": seed,
        "status": (
            "PASS"
            if not control_violations and not candidate_violations
            else "HALT_VIOLATION"
        ),
        "control_objective": float(control_obj),
        "candidate_objective": float(candidate_obj),
        "candidate_minus_control": float(delta),
        "result": (
            "win"
            if delta < -1.0e-9
            else "loss"
            if delta > 1.0e-9
            else "tie"
        ),
        "control_complete_attempts": int(
            control.stats["complete_candidate_evaluation_attempts"]
        ),
        "candidate_complete_attempts": int(
            candidate.stats["complete_candidate_evaluation_attempts"]
        ),
        "candidate_total_hgs_iterations": int(
            candidate.stats["total_hgs_iterations"]
        ),
        "control_route_pool_size": int(control.stats["route_pool_size"]),
        "candidate_route_pool_size": int(
            candidate.stats["route_pool_size"]
        ),
        "candidate_feedback_elite_count": int(
            candidate.stats["feedback_elite_count"]
        ),
        "control_selected_source": control.stats["selected_source"],
        "candidate_selected_source": candidate.stats["selected_source"],
        "candidate_mip_status": candidate.stats["route_pool_mip"][
            "status_class"
        ],
        "candidate_mip_gap": candidate.stats["route_pool_mip"]["mip_gap"],
        "wallclock_safety_triggered": bool(
            control.stats["wallclock_safety_triggered"]
            or candidate.stats["wallclock_safety_triggered"]
        ),
    }


def _worker(args: tuple[str, int]) -> dict[str, Any]:
    try:
        return _evaluate(*args)
    except BaseException as exc:
        return {
            "instance_id": args[0],
            "seed": args[1],
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
        (instance_id, int(prereg["seed"]))
        for instance_id in prereg["development_panel"]
    ]
    context = mp.get_context("spawn")
    with context.Pool(processes=3) as pool:
        rows = pool.map(_worker, tasks)
    wins = sum(row.get("result") == "win" for row in rows)
    losses = sum(row.get("result") == "loss" for row in rows)
    invariant_pass = all(
        row.get("status") == "PASS"
        and row.get("control_complete_attempts") == 80
        and row.get("candidate_complete_attempts") == 80
        and row.get("candidate_total_hgs_iterations") == 15_000
        and row.get("wallclock_safety_triggered") is False
        for row in rows
    )
    passed = invariant_pass and wins >= 2 and losses == 0
    payload = {
        "schema": "resetp.cross-view-feedback-panel.v1",
        "formal_evidence": False,
        "verdict": (
            "PASS_CROSS_VIEW_FEEDBACK_DEVELOPMENT_GATE"
            if passed
            else "HALT_CROSS_VIEW_FEEDBACK_DEVELOPMENT_GATE"
        ),
        "wins": wins,
        "ties": sum(row.get("result") == "tie" for row in rows),
        "losses": losses,
        "required_wins": 2,
        "allowed_losses": 0,
        "invariant_pass": invariant_pass,
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
