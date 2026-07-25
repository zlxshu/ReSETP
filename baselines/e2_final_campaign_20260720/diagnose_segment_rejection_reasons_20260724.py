#!/usr/bin/env python3
"""Explain why SEG-GEN-02 candidates are rejected on the simulation case."""

from __future__ import annotations

import collections
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
RESULT = OUT / "representative_segment_rejection_reasons.json"


def _reason_key(message: str) -> str:
    return str(message).split(":", 1)[0].strip()


def _worker(result_path: str) -> None:
    try:
        import bounded_segment_generator as generator
        import run_corrected_china81_d6 as runner
        import route_pool_sp
        from setp_solver.algorithms.resetp_alns.operators.local_search import (
            repair_route_charging,
        )
        from setp_solver.check import check_solution
        from setp_solver.china81 import load_china81_bundle
        from setp_solver.search.evaluation import (
            EvalBudget,
            EvaluationContext,
            fairness_context_for_solution,
        )
        from setp_solver.solution import Solution

        bundle = load_china81_bundle(
            REPO,
            "cn-prd-50c-01-V2-LOCATIONS",
        )
        initial = runner._load_initial(
            "cn-prd-50c-01-V2-LOCATIONS"
        )
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
            wallclock_safety_seconds_per_view=180.0,
        )
        context = EvaluationContext(
            bundle.instance,
            bundle.time_profile,
            prices=bundle.prices,
            budget=EvalBudget(limit=0, target=0),
            customer_home_depot=dict(bundle.customer_home_depot),
            allow_cross_depot=True,
        )
        reasons: collections.Counter[str] = collections.Counter()
        examples: dict[str, str] = {}

        def diagnostic_builder(
            solution: Any,
            eval_context: Any,
            route_customers: dict[int, list[str]],
        ) -> Any | None:
            routes = list(solution.routes)
            changed_vehicle_ids = {
                routes[index].vehicle_id for index in route_customers
            }
            actions = [
                action
                for action in solution.charging_actions
                if action.vehicle_id not in changed_vehicle_ids
            ]
            new_actions = []
            for route_index, customers in route_customers.items():
                route = routes[route_index]
                clean_route = replace(
                    route,
                    node_sequence=[
                        route.home_depot_id,
                        *customers,
                        route.home_depot_id,
                    ],
                )
                if route.vehicle_type.lower() == "ev":
                    try:
                        clean_route, route_actions = (
                            repair_route_charging(
                                clean_route,
                                eval_context.instance,
                                eval_context.carbon_profile,
                                eval_context.prices,
                            )
                        )
                    except ValueError as exc:
                        key = "EV_CHARGING_REPAIR"
                        reasons[key] += 1
                        examples.setdefault(key, str(exc))
                        return None
                    new_actions.extend(route_actions)
                routes[route_index] = clean_route
            candidate = Solution(
                routes=routes,
                charging_actions=[*actions, *new_actions],
                cross_site_services=solution.cross_site_services,
            )
            violations = check_solution(
                candidate,
                eval_context.instance,
                eval_context.prices,
                fairness_context=fairness_context_for_solution(
                    candidate,
                    eval_context,
                ),
                fairness_enabled=eval_context.fairness_enabled,
            )
            if violations:
                for violation in violations:
                    key = _reason_key(violation)
                    reasons[key] += 1
                    examples.setdefault(key, str(violation))
                return None
            reasons["CANDIDATE_PASSED_LOCAL_CHECK"] += 1
            return candidate

        generator._candidate_with_route_customers = diagnostic_builder
        _, activity = generator.propose_bounded_segment_move(
            run.solution,
            context,
            dict(bundle.customer_home_depot),
            config=generator.BoundedSegmentGeneratorConfig(),
        )
        payload = {
            "status": "PASS_DIAGNOSTIC",
            "formal_evidence": False,
            "instance_id": "cn-prd-50c-01-V2-LOCATIONS",
            "seed": 1,
            "stop_reason": activity["stop_reason"],
            "rejection_reason_counts": dict(reasons),
            "examples": examples,
            "ledger": activity["ledger"],
        }
    except BaseException as exc:
        payload = {
            "status": "HALT_DIAGNOSTIC_EXCEPTION",
            "formal_evidence": False,
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
    Path(result_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[name] = "1"
    OUT.mkdir(parents=True, exist_ok=True)
    process = mp.get_context("spawn").Process(
        target=_worker,
        args=(str(RESULT),),
    )
    process.start()
    process.join(timeout=240)
    if process.is_alive():
        process.terminate()
        process.join()
        RESULT.write_text(
            json.dumps(
                {
                    "status": "HALT_DIAGNOSTIC_TIMEOUT",
                    "formal_evidence": False,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    elif not RESULT.is_file():
        RESULT.write_text(
            json.dumps(
                {
                    "status": "HALT_DIAGNOSTIC_CHILD_EXIT",
                    "formal_evidence": False,
                    "child_exit_code": process.exitcode,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print(RESULT.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
