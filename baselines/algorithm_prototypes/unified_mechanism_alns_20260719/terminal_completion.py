"""Neutral wrapper around the frozen v7 terminal mechanism experts.

This file carries no route-pool logic.  It applies the same monotone terminal
stack to any one complete start so the initial-pool gate can compare its
default anchor and newly selected winner symmetrically.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.profit import infer_customer_home_depots
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import Solution
from v5_carbon_retiming_solver import carbon_aware_depot_retime
from v6_monotone_mechanism_solver import exact_joint_fleet_charge_decode
from v7_responsibility_solver import (
    annotate_cross_site_services,
    exact_cross_depot_responsibility_decode,
)


TOL = 1.0e-9


@dataclass(frozen=True)
class CompletionResult:
    solution: Solution
    cost: float
    source_cost: float
    feasible: bool
    selected_branch: str
    activity: dict[str, Any]


def apply_terminal_completion(
    bundle_dir: str | Path,
    solution: Solution,
    *,
    prices: Any = DEFAULT_PRICES,
) -> CompletionResult:
    """Apply responsibility, fleet/charge, and carbon experts monotonically."""

    bundle = load_search_bundle(bundle_dir)
    owners = infer_customer_home_depots(bundle.instance)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=EvalBudget(limit=0, target=0),
        customer_home_depot=owners,
        allow_cross_depot=True,
    )
    original = annotate_cross_site_services(solution, owners)
    original_cost = _model_cost(original, context)
    original_violations = check_solution(original, bundle.instance, prices)
    if original_violations:
        raise ValueError(f"terminal-completion source is infeasible: {original_violations[:8]}")

    responsibility_solution, responsibility_cost, responsibility = (
        exact_cross_depot_responsibility_decode(
            original,
            context,
            incumbent_objective=original_cost,
            owners=owners,
        )
    )

    def downstream(
        candidate: Solution,
        objective: float,
    ) -> tuple[Solution, float, dict[str, Any], dict[str, Any]]:
        candidate, objective, joint = exact_joint_fleet_charge_decode(
            candidate,
            context,
            incumbent_objective=objective,
        )
        candidate, objective, carbon = carbon_aware_depot_retime(
            candidate,
            context,
            incumbent_objective=objective,
            consume_complete_evaluation=False,
        )
        return candidate, float(objective), joint, carbon

    responsibility_branch = downstream(
        responsibility_solution,
        responsibility_cost,
    )
    bypass_branch = downstream(original, original_cost)
    if bypass_branch[1] < responsibility_branch[1] - TOL:
        selected = bypass_branch
        selected_branch = "bypass_responsibility"
    else:
        selected = responsibility_branch
        selected_branch = "responsibility"

    final_solution, claimed, joint, carbon = selected
    recomputed = _model_cost(final_solution, context)
    if abs(float(recomputed) - float(claimed)) > 1.0e-7:
        raise RuntimeError(
            f"terminal completion objective mismatch: {claimed} != {recomputed}"
        )
    if recomputed > original_cost + TOL:
        raise RuntimeError(
            f"terminal completion violated monotonicity: {recomputed} > {original_cost}"
        )
    violations = check_solution(final_solution, bundle.instance, prices)
    activity = {
        "responsibility": responsibility,
        "joint": joint,
        "carbon": carbon,
        "branches": {
            "responsibility": {
                "source_cost": float(responsibility_cost),
                "completed_cost": float(responsibility_branch[1]),
                "joint": responsibility_branch[2],
                "carbon": responsibility_branch[3],
            },
            "bypass_responsibility": {
                "source_cost": float(original_cost),
                "completed_cost": float(bypass_branch[1]),
                "joint": bypass_branch[2],
                "carbon": bypass_branch[3],
            },
        },
        "selected_branch": selected_branch,
        "responsibility_branch_completed_cost": float(
            responsibility_branch[1]
        ),
        "bypass_responsibility_completed_cost": float(bypass_branch[1]),
        "net_responsibility_gain": float(
            bypass_branch[1] - responsibility_branch[1]
        ),
        "responsibility_effective_after_downstream": bool(
            responsibility_branch[1] < bypass_branch[1] - TOL
        ),
        "full_solution_replays": (
            2 + int(responsibility.get("independent_final_replays", 0))
        ),
        "route_local_exact_evaluations": int(
            responsibility.get("local_exact_evaluations", 0)
        ),
        "route_proxy_evaluations": int(
            joint.get("route_proxy_evaluations", 0)
        ),
        "route_local_schedule_evaluations": int(
            carbon.get("route_local_schedule_evaluations", 0)
        ),
        "complete_route_search_evaluations": 0,
    }
    return CompletionResult(
        solution=final_solution,
        cost=float(recomputed),
        source_cost=float(original_cost),
        feasible=not violations,
        selected_branch=selected_branch,
        activity=activity,
    )


def _model_cost(solution: Solution, context: EvaluationContext) -> float:
    return float(
        evaluate(
            solution,
            context.instance,
            context.carbon_profile,
            context.prices,
            carbon_quota_kg=context.carbon_quota_kg,
        )["total_cost"]
    )
