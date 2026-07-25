#!/usr/bin/env python3
"""Development-only panel for reciprocal segment refinement."""

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
RESULT = OUT / "reciprocal_segment_refinement_v2_panel_results.json"
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
    from reciprocal_segment_refinement_v2 import (
        run_reciprocal_segment_refinement_v2,
    )
    from setp_solver.china81 import load_china81_bundle
    from setp_solver.china81_completion import exact_china81_score

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
    refinement = run_reciprocal_segment_refinement_v2(
        bundle,
        run.completion,
        maximum_complete_candidates=12,
    )
    objective, _, violations = exact_china81_score(
        refinement.completion.solution,
        bundle,
    )
    return {
        "instance_id": instance_id,
        "seed": 1,
        "status": "PASS" if not violations else "HALT_VIOLATION",
        "before_objective": float(run.completion.objective),
        "final_objective": float(objective),
        "accepted": refinement.accepted,
        "violation_count": len(violations),
        "stats": refinement.stats,
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


def main() -> int:
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[name] = "1"
    OUT.mkdir(parents=True, exist_ok=True)
    with mp.get_context("spawn").Pool(processes=3) as pool:
        rows = pool.map(_worker, PANEL)
    improvements = sum(row.get("accepted", False) for row in rows)
    invariants = all(
        row.get("status") == "PASS"
        and row.get("violation_count") == 0
        and row.get("final_objective", float("inf"))
        <= row.get("before_objective", -float("inf")) + 1.0e-9
        and row.get("stats", {}).get("shortlisted_candidates", 13)
        <= 12
        for row in rows
    )
    passed = invariants and improvements >= 2
    payload = {
        "schema": "resetp.reciprocal-segment-refinement-panel.v2",
        "formal_evidence": False,
        "verdict": (
            "PASS_RECIPROCAL_SEGMENT_REFINEMENT_V2_DEVELOPMENT_GATE"
            if passed
            else "HALT_RECIPROCAL_SEGMENT_REFINEMENT_V2_DEVELOPMENT_GATE"
        ),
        "strict_improvements": improvements,
        "required_strict_improvements": 2,
        "invariant_pass": invariants,
        "representative_instance": (
            "cn-prd-50c-01-V2-LOCATIONS"
        ),
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
