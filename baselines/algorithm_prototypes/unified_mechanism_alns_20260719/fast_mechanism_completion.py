"""Fast, route-local ReSETP completion used only for basin judgement.

The completion keeps every customer route and depot assignment fixed.  It
chooses the CV/EV and charging pattern route by route, then moves existing
depot charging actions to lower-carbon time slots.  Cross-depot responsibility
is intentionally left to the bounded full mechanism completion.

No complete search-candidate evaluation is hidden here.  The caller must send
the returned solution through either an explicit reference or candidate
channel before using it to choose a search basin.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.profit import infer_customer_home_depots
from setp_solver.search.bundle import SearchBundle
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import Solution
from v5_carbon_retiming_solver import carbon_aware_depot_retime
from v6_monotone_mechanism_solver import exact_joint_fleet_charge_decode
from v7_responsibility_solver import annotate_cross_site_services


@dataclass(frozen=True)
class FastCompletionResult:
    solution: Solution
    changed: bool
    activity: dict[str, Any]


def apply_fast_route_local_completion(
    solution: Solution,
    bundle: SearchBundle,
    *,
    prices: Any = DEFAULT_PRICES,
) -> FastCompletionResult:
    """Complete one fixed route skeleton without a full candidate replay."""

    owners = infer_customer_home_depots(bundle.instance)
    completion_budget = EvalBudget(limit=0, target=0)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=completion_budget,
        customer_home_depot=owners,
        allow_cross_depot=True,
    )
    source = annotate_cross_site_services(solution, owners)
    completed, proxy_objective, joint = exact_joint_fleet_charge_decode(
        source,
        context,
        incumbent_objective=0.0,
    )
    completed, _, carbon = carbon_aware_depot_retime(
        completed,
        context,
        incumbent_objective=proxy_objective,
        consume_complete_evaluation=False,
    )
    deltas = (
        float(joint.get("objective_delta", 0.0)),
        float(carbon.get("objective_delta", 0.0)),
    )
    if not all(math.isfinite(value) for value in deltas):
        raise RuntimeError(
            f"fast route-local completion produced a non-finite delta: {deltas}"
        )
    joint_complete = _strict_activity_count(
        joint,
        "complete_evaluations",
        "joint",
    )
    carbon_complete = _strict_activity_count(
        carbon,
        "complete_evaluations",
        "carbon",
    )
    complete_candidate_evaluations = joint_complete + carbon_complete
    route_search_evaluations = _strict_nonnegative_int(
        completion_budget.count,
        "completion budget count",
    )
    score_candidate_calls = _strict_nonnegative_int(
        context.score_counts.get("candidate", 0),
        "completion candidate score count",
    )
    if not (
        complete_candidate_evaluations
        == route_search_evaluations
        == score_candidate_calls
    ):
        raise RuntimeError(
            "fast route-local completion search ledger drifted: "
            f"components={complete_candidate_evaluations}, "
            f"budget={route_search_evaluations}, "
            f"scores={score_candidate_calls}"
        )
    if route_search_evaluations:
        raise RuntimeError("fast route-local completion attempted route search")
    route_proxy_evaluations = _strict_activity_count(
        joint,
        "route_proxy_evaluations",
        "joint",
    )
    route_local_schedule_evaluations = _strict_activity_count(
        carbon,
        "route_local_schedule_evaluations",
        "carbon",
    )
    full_feasibility_checks = (
        _strict_activity_count(
            joint,
            "feasibility_checks",
            "joint",
        )
        + _strict_activity_count(
            carbon,
            "feasibility_checks",
            "carbon",
        )
        + 1
    )
    completed = annotate_cross_site_services(completed, owners)
    violations = check_solution(completed, bundle.instance, prices)
    if violations:
        raise ValueError(f"fast route-local completion is infeasible: {violations[:8]}")
    changed = (
        int(joint.get("exact_decoder_updates", 0)) > 0
        or int(carbon.get("exact_decoder_updates", 0)) > 0
        or int(carbon.get("actions_retimed", 0)) > 0
    )
    return FastCompletionResult(
        solution=completed,
        changed=bool(changed),
        activity={
            "joint": joint,
            "carbon": carbon,
            "joint_objective_delta": float(deltas[0]),
            "carbon_objective_delta": float(deltas[1]),
            "projected_objective_delta": float(sum(deltas)),
            "route_proxy_evaluations": route_proxy_evaluations,
            "route_local_schedule_evaluations": (route_local_schedule_evaluations),
            "full_feasibility_checks": full_feasibility_checks,
            "complete_candidate_evaluations": (complete_candidate_evaluations),
            "complete_route_search_evaluations": (route_search_evaluations),
            "search_candidate_score_calls": score_candidate_calls,
        },
    )


def _strict_activity_count(
    activity: dict[str, Any],
    key: str,
    label: str,
) -> int:
    if key not in activity:
        raise RuntimeError(f"{label} omitted {key}")
    return _strict_nonnegative_int(activity[key], f"{label}.{key}")


def _strict_nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(f"{label} is not a nonnegative integer")
    return value
