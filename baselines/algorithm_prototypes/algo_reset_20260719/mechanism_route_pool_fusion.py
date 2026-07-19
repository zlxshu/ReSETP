"""Exact route-pool fusion followed by shared ReSETP mechanism experts.

This isolated prototype does not treat the HGS adapter as a fair full-model
baseline. HGS and ALNS only contribute route skeletons. Every candidate is
then judged by the same complete ReSETP evaluator and checker.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
MECHANISM_DIR = HERE.parent / "mechanism_hgs_alns_20260718"
if str(MECHANISM_DIR) not in sys.path:
    sys.path.insert(0, str(MECHANISM_DIR))

from exact_route_pool_recombiner import (  # noqa: E402
    PoolRoute,
    RecombinationResult,
    exact_recombine,
)
from prototype import independent_cost  # noqa: E402
from setp_solver.algorithms.resetp_alns.support.fleet import (  # noqa: E402
    normalize_solution_vehicle_trips,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.profit import infer_customer_home_depots  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.search.evaluation import EvalBudget, EvaluationContext  # noqa: E402
from setp_solver.solution import Solution  # noqa: E402
from v4_mechanism_alns_solver import _route_variants  # noqa: E402
from v5_carbon_retiming_solver import carbon_aware_depot_retime  # noqa: E402
from v6_monotone_mechanism_solver import (  # noqa: E402
    exact_joint_fleet_charge_decode,
)
from v7_responsibility_solver import (  # noqa: E402
    annotate_cross_site_services,
    exact_cross_depot_responsibility_decode,
)


TOL = 1.0e-9


@dataclass(frozen=True)
class ExpertResult:
    solution: Solution
    objective: float
    feasible: bool
    activity: dict[str, Any]


@dataclass(frozen=True)
class FusionResult:
    hgs_expert: ExpertResult
    alns_expert: ExpertResult
    pool_expert: ExpertResult | None
    recombination: RecombinationResult | None
    pool_error: str | None = None


def _price(prices: Any, name: str) -> float:
    if isinstance(prices, dict):
        return float(prices[name])
    return float(getattr(prices, name))


def apply_mechanism_experts(
    bundle_dir: str | Path,
    solution: Solution,
    *,
    prices: Any = DEFAULT_PRICES,
) -> ExpertResult:
    """Apply the same monotone expert stack to any feasible route source."""

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
    original_objective = independent_cost(bundle_dir, original, prices)
    original_violations = check_solution(original, bundle.instance, prices)
    if original_violations:
        raise ValueError(f"route source is infeasible: {original_violations}")

    responsibility_solution, responsibility_objective, responsibility = (
        exact_cross_depot_responsibility_decode(
            original,
            context,
            incumbent_objective=original_objective,
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
        return candidate, objective, joint, carbon

    responsibility_branch = downstream(
        responsibility_solution,
        responsibility_objective,
    )
    bypass_branch = downstream(original, original_objective)
    if bypass_branch[1] < responsibility_branch[1] - TOL:
        chosen = bypass_branch
        selected_branch = "bypass_responsibility"
    else:
        chosen = responsibility_branch
        selected_branch = "responsibility"

    final_solution, claimed, joint, carbon = chosen
    recomputed = independent_cost(bundle_dir, final_solution, prices)
    if abs(recomputed - claimed) > 1.0e-7:
        raise RuntimeError(
            f"expert objective mismatch: {claimed} != {recomputed}"
        )
    violations = check_solution(final_solution, bundle.instance, prices)
    return ExpertResult(
        solution=final_solution,
        objective=float(recomputed),
        feasible=not violations,
        activity={
            "source_objective": float(original_objective),
            "selected_branch": selected_branch,
            "responsibility": responsibility,
            "joint": joint,
            "carbon": carbon,
            "independent_final_replays": 1,
            "complete_route_search_evaluations": 0,
        },
    )


def route_pool_records(
    bundle_dir: str | Path,
    solution: Solution,
    *,
    source: str,
    prices: Any = DEFAULT_PRICES,
) -> list[PoolRoute]:
    """Convert a complete solution into additive route records."""

    bundle = load_search_bundle(bundle_dir)
    owners = infer_customer_home_depots(bundle.instance)
    node_types = {
        node.node_id: node.node_type.lower() for node in bundle.instance.nodes
    }
    records: list[PoolRoute] = []
    for route in solution.routes:
        customers = frozenset(
            node_id
            for node_id in route.node_sequence
            if node_types.get(node_id) == "c"
        )
        actions = tuple(
            action
            for action in solution.charging_actions
            if action.vehicle_id == route.vehicle_id
        )
        variants = _route_variants(
            route,
            current_actions=actions,
            instance=bundle.instance,
            carbon_profile=bundle.carbon_profile,
            prices=prices,
        )
        current = variants[route.vehicle_type.lower()]
        cross_site_count = sum(
            owners.get(customer) is not None
            and owners[customer] != route.home_depot_id
            for customer in customers
        )
        additive_score = (
            float(current.proxy_cost)
            + cross_site_count * _price(prices, "cross_site_cost")
        )
        records.append(
            PoolRoute(
                route=route,
                customers=customers,
                additive_score=float(additive_score),
                actions=actions,
                source=source,
            )
        )
    return records


def fuse_route_sources(
    bundle_dir: str | Path,
    *,
    hgs_solution: Solution,
    alns_solution: Solution,
    prices: Any = DEFAULT_PRICES,
    time_limit_seconds: float = 2.0,
) -> FusionResult:
    """Process both parents and their exact mixed route pool symmetrically."""

    bundle = load_search_bundle(bundle_dir)
    required = {
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    hgs_expert = apply_mechanism_experts(
        bundle_dir,
        hgs_solution,
        prices=prices,
    )
    alns_expert = apply_mechanism_experts(
        bundle_dir,
        alns_solution,
        prices=prices,
    )
    records = [
        *route_pool_records(
            bundle_dir,
            hgs_solution,
            source="hgs_adapter_route_source",
            prices=prices,
        ),
        *route_pool_records(
            bundle_dir,
            alns_solution,
            source="alns_route_source",
            prices=prices,
        ),
    ]
    recombination = exact_recombine(
        records,
        required,
        time_limit_seconds=time_limit_seconds,
    )
    pool_expert = None
    pool_error = None
    if recombination is not None:
        try:
            normalized = normalize_solution_vehicle_trips(
                recombination.solution,
                bundle.instance,
            )
            pool_expert = apply_mechanism_experts(
                bundle_dir,
                normalized,
                prices=prices,
            )
        except ValueError as exc:
            pool_error = str(exc)
    return FusionResult(
        hgs_expert=hgs_expert,
        alns_expert=alns_expert,
        pool_expert=pool_expert,
        recombination=recombination,
        pool_error=pool_error,
    )
