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
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=EvalBudget(limit=0, target=0),
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
            "fast route-local completion produced a non-finite delta: "
            f"{deltas}"
        )
    completed = annotate_cross_site_services(completed, owners)
    violations = check_solution(completed, bundle.instance, prices)
    if violations:
        raise ValueError(
            "fast route-local completion is infeasible: "
            f"{violations[:8]}"
        )
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
            "joint_objective_delta": float(
                deltas[0]
            ),
            "carbon_objective_delta": float(
                deltas[1]
            ),
            "projected_objective_delta": float(sum(deltas)),
            "route_proxy_evaluations": int(
                joint.get("route_proxy_evaluations", 0)
            ),
            "route_local_schedule_evaluations": int(
                carbon.get("route_local_schedule_evaluations", 0)
            ),
            "full_feasibility_checks": (
                int(joint.get("feasibility_checks", 0))
                + int(carbon.get("feasibility_checks", 0))
                + 1
            ),
            "complete_candidate_evaluations": 0,
        },
    )
