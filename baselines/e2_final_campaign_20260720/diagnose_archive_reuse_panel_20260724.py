#!/usr/bin/env python3
"""Development-only paired diagnosis for archive-route reuse."""

from __future__ import annotations

import csv
from dataclasses import replace
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
import traceback
from typing import Any


REPO = Path(__file__).resolve().parents[2]
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
for path in (
    REPO / "solver/src",
    PROTOTYPE,
    REPO / "baselines/e2_final_campaign_20260720",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

OUT = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "algorithm_repair_diagnostic_20260724"
)
RESULT = OUT / "archive_route_reuse_panel_results.json"
FORMAL_RAW = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v3_20260724/full_gate/raw_runs.csv"
)
PANEL = (
    "cn-cy-50c-01-V2-LOCATIONS",
    "cn-jjj-50c-01-V2-LOCATIONS",
    "cn-prd-50c-01-V2-LOCATIONS",
    "cn-cy-75c-01-V2-LOCATIONS",
    "cn-jjj-75c-01-V2-LOCATIONS",
    "cn-prd-75c-01-V2-LOCATIONS",
)


def _evaluate(instance_id: str) -> dict[str, Any]:
    import run_corrected_china81_d6 as runner
    import route_pool_sp
    from setp_solver.china81 import load_china81_bundle
    from setp_solver.china81_completion import (
        complete_china81_route_skeleton,
        exact_china81_score,
    )

    bundle = load_china81_bundle(REPO, instance_id)
    initial = runner._load_initial(instance_id)
    run = route_pool_sp.run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=1,
        hgs_seconds_per_view=None,
        exact_elites_per_view=8,
        max_archive_candidates_per_view=24,
        sp_time_limit_seconds=5.0,
        hard_home_depot_lock=False,
        max_hgs_iterations_per_view=5_000,
        wallclock_safety_seconds_per_view=max(
            180.0,
            2.0
            * sum(
                node.node_type.lower() == "c"
                for node in bundle.instance.nodes
            ),
        ),
    )
    old_epochs = {
        mode: replace(epoch, archive_completions=())
        for mode, epoch in run.view_epochs.items()
    }
    old_records = route_pool_sp._route_pool_records(
        bundle,
        old_epochs,
        hard_home_depot_lock=False,
    )
    old_solution, old_stats = route_pool_sp._solve_set_partitioning(
        bundle,
        old_records,
        time_limit_seconds=5.0,
        hard_home_depot_lock=False,
    )
    parent = run.parent_completion
    if old_solution is None:
        old_objective = parent.objective
    else:
        old_completion = complete_china81_route_skeleton(
            old_solution,
            bundle,
        )
        old_objective = min(
            parent.objective,
            old_completion.objective,
        )
    single_costs = {}
    for label, mode in runner.VIEWS.items():
        epoch = run.view_epochs[mode]
        best = min(
            (*epoch.elite_completions, epoch.proxy_best_completion),
            key=lambda item: item.objective,
        )
        single_costs[label] = float(best.objective)
    objective, _, violations = exact_china81_score(
        run.solution,
        bundle,
    )
    return {
        "instance_id": instance_id,
        "seed": 1,
        "status": "PASS" if not violations else "HALT_VIOLATION",
        "single_costs": single_costs,
        "complete_candidate_attempts": run.stats[
            "complete_candidate_evaluation_attempts"
        ],
        "old_route_pool_size": len(old_records),
        "new_route_pool_size": run.stats["route_pool_size"],
        "old_objective": float(old_objective),
        "new_objective": float(objective),
        "strict_improvement_over_old": bool(
            objective < old_objective - 1.0e-9
        ),
        "selected_source": run.stats["selected_source"],
        "new_solver_status": run.stats["route_pool_mip"][
            "status_class"
        ],
        "new_solver_gap": run.stats["route_pool_mip"]["mip_gap"],
        "old_solver_status": old_stats["status_class"],
        "old_solver_gap": old_stats["mip_gap"],
        "violation_count": len(violations),
    }


def _worker(instance_id: str) -> dict[str, Any]:
    try:
        return _evaluate(instance_id)
    except BaseException as exc:
        return {
            "instance_id": instance_id,
            "seed": 1,
            "status": "HALT_EXCEPTION",
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }


def _formal_rows() -> dict[str, dict[str, str]]:
    with FORMAL_RAW.open(newline="", encoding="utf-8") as handle:
        return {
            row["instance_id"]: row
            for row in csv.DictReader(handle)
            if row["seed"] == "1" and row["instance_id"] in PANEL
        }


def main() -> int:
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[name] = "1"
    OUT.mkdir(parents=True, exist_ok=True)
    context = mp.get_context("spawn")
    with context.Pool(processes=3) as pool:
        rows = pool.map(_worker, PANEL)
    formal = _formal_rows()
    for row in rows:
        if row["status"] != "PASS":
            continue
        reference = formal[row["instance_id"]]
        row["single_costs_match_sealed_formal"] = all(
            row["single_costs"][label]
            == float(reference[f"{label}_cost"])
            for label in ("HGS-F", "HGS-E", "HGS-M")
        )
        row["old_objective_matches_sealed_formal"] = (
            abs(
                row["old_objective"]
                - float(reference["MV-HGS-SP_cost"])
            )
            <= 1.0e-9
        )
    strict_improvements = sum(
        row.get("strict_improvement_over_old", False)
        for row in rows
    )
    invariant_pass = all(
        row.get("status") == "PASS"
        and row.get("single_costs_match_sealed_formal") is True
        and row.get("old_objective_matches_sealed_formal") is True
        and row.get("complete_candidate_attempts") == 80
        and row.get("new_route_pool_size", 0)
        >= row.get("old_route_pool_size", 1)
        and row.get("new_objective", float("inf"))
        <= min(row.get("single_costs", {}).values()) + 1.0e-9
        and row.get("violation_count") == 0
        for row in rows
    )
    accepted = invariant_pass and strict_improvements >= 2
    payload = {
        "schema": "resetp.archive-route-reuse-panel.v1",
        "formal_evidence": False,
        "verdict": (
            "PASS_ARCHIVE_ROUTE_REUSE_DEVELOPMENT_GATE"
            if accepted
            else "HALT_ARCHIVE_ROUTE_REUSE_DEVELOPMENT_GATE"
        ),
        "strict_improvements": strict_improvements,
        "required_strict_improvements": 2,
        "invariant_pass": invariant_pass,
        "rows": rows,
    }
    RESULT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(RESULT.read_text(encoding="utf-8"))
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
