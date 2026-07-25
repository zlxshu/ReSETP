#!/usr/bin/env python3
"""Development-only paired panel for bounded segment refinement."""

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
SEGMENT = (
    REPO
    / "baselines/algorithm_prototypes/"
    "outcome_first_hybrid_20260719"
)
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    PROTOTYPE,
    SEGMENT,
    REPO / "baselines/e2_final_campaign_20260720",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

OUT = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "algorithm_repair_diagnostic_20260724"
)
RESULT = OUT / "bounded_segment_refinement_panel_results.json"
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
    from bounded_segment_generator import (
        BoundedSegmentGeneratorConfig,
        propose_bounded_segment_move,
    )
    from setp_solver.china81 import load_china81_bundle
    from setp_solver.china81_completion import (
        complete_china81_route_skeleton,
        exact_china81_score,
    )
    from setp_solver.search.evaluation import EvalBudget, EvaluationContext

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
    before_objective, _, before_violations = exact_china81_score(
        run.solution,
        bundle,
    )
    context = EvaluationContext(
        bundle.instance,
        bundle.time_profile,
        prices=bundle.prices,
        budget=EvalBudget(limit=0, target=0),
        customer_home_depot=dict(bundle.customer_home_depot),
        allow_cross_depot=True,
    )
    proposal, activity = propose_bounded_segment_move(
        run.solution,
        context,
        dict(bundle.customer_home_depot),
        config=BoundedSegmentGeneratorConfig(),
    )
    proposal_objective = None
    proposal_violation_count = None
    accepted = False
    if proposal is not None:
        completed = complete_china81_route_skeleton(
            proposal,
            bundle,
        )
        proposal_objective, _, proposal_violations = exact_china81_score(
            completed.solution,
            bundle,
        )
        proposal_violation_count = len(proposal_violations)
        accepted = bool(
            not proposal_violations
            and proposal_objective < before_objective - 1.0e-9
        )
    ledger = activity["ledger"]
    bounds_respected = bool(
        ledger["source_segments_shortlisted"] <= 64
        and ledger["maximum_positions_for_one_source"] <= 6
        and ledger["exact_candidates_shortlisted"] <= 48
        and ledger["completion_candidates_screened"] <= 12
        and ledger[
            "complete_candidate_evaluations_before_submission"
        ]
        == 0
    )
    return {
        "instance_id": instance_id,
        "seed": 1,
        "status": (
            "PASS"
            if not before_violations and bounds_respected
            else "HALT_INVARIANT"
        ),
        "before_objective": float(before_objective),
        "proposal_generated": proposal is not None,
        "proposal_objective": (
            None
            if proposal_objective is None
            else float(proposal_objective)
        ),
        "proposal_violation_count": proposal_violation_count,
        "accepted": accepted,
        "final_objective": float(
            proposal_objective if accepted else before_objective
        ),
        "improvement": float(
            before_objective
            - (proposal_objective if accepted else before_objective)
        ),
        "bounds_respected": bounds_respected,
        "stop_reason": activity["stop_reason"],
        "selected": activity["selected"],
        "ledger": ledger,
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
        and row.get("bounds_respected") is True
        and row.get("final_objective", float("inf"))
        <= row.get("before_objective", -float("inf")) + 1.0e-9
        for row in rows
    )
    accepted = invariants and improvements >= 2
    payload = {
        "schema": "resetp.bounded-segment-refinement-panel.v1",
        "formal_evidence": False,
        "verdict": (
            "PASS_BOUNDED_SEGMENT_REFINEMENT_DEVELOPMENT_GATE"
            if accepted
            else "HALT_BOUNDED_SEGMENT_REFINEMENT_DEVELOPMENT_GATE"
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
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
