"""Monotone mechanism-first ALNS v6.

The architecture follows a simple division of labour:

* the current ReSETP ALNS receives the complete route-search budget and decides
  customer grouping and order;
* an exact fixed-route fleet/charging decoder chooses the CV/EV pattern;
* an exact fixed-route carbon decoder retimes depot charging.

Both decoders have separate route-local ledgers, consume zero complete route
search evaluations, and accept only strict improvements.  A final independent
complete replay protects the arithmetic.  This isolated development candidate
does not modify the formal solver or the three protected referee files.
"""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from prototype import ArmResult, independent_cost, run_pure_alns
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import Solution
from v4_mechanism_alns_solver import (
    _assemble_pattern,
    _pattern_candidates,
    _route_variants,
)
from v5_carbon_retiming_solver import carbon_aware_depot_retime


def exact_joint_fleet_charge_decode(
    solution: Solution,
    context: EvaluationContext,
    *,
    incumbent_objective: float,
) -> tuple[Solution, float, dict[str, Any]]:
    """Choose a fixed-route CV/EV pattern by exact separable objective delta."""

    route_variants = []
    current_pattern: list[str] = []
    route_proxy_evaluations = 0
    for route in solution.routes:
        current_actions = tuple(
            action
            for action in solution.charging_actions
            if action.vehicle_id == route.vehicle_id
        )
        variants = _route_variants(
            route,
            current_actions=current_actions,
            instance=context.instance,
            carbon_profile=context.carbon_profile,
            prices=context.prices,
        )
        route_variants.append(variants)
        current_pattern.append(route.vehicle_type.lower())
        route_proxy_evaluations += len(variants)

    current_tuple = tuple(current_pattern)
    current_proxy = sum(
        route_variants[index][vehicle_type].proxy_cost
        for index, vehicle_type in enumerate(current_tuple)
    )
    best_pattern = current_tuple
    best_proxy = float(current_proxy)
    best_candidate = solution
    patterns_considered = 0
    assembled_patterns = 0
    feasibility_checks = 0
    for pattern in _pattern_candidates(route_variants, current_tuple):
        patterns_considered += 1
        proxy = sum(
            route_variants[index][vehicle_type].proxy_cost
            for index, vehicle_type in enumerate(pattern)
        )
        if proxy >= best_proxy - 1.0e-9 and pattern != current_tuple:
            continue
        candidate = _assemble_pattern(
            route_variants,
            pattern,
            parent=solution,
            instance=context.instance,
        )
        assembled_patterns += 1
        if candidate is None:
            continue
        feasibility_checks += 1
        if check_solution(candidate, context.instance, context.prices):
            continue
        if proxy < best_proxy - 1.0e-9:
            best_pattern = pattern
            best_proxy = float(proxy)
            best_candidate = candidate

    activity: dict[str, Any] = {
        "route_proxy_evaluations": route_proxy_evaluations,
        "patterns_considered": patterns_considered,
        "assembled_patterns": assembled_patterns,
        "feasibility_checks": feasibility_checks,
        "current_pattern": list(current_tuple),
        "selected_pattern": list(best_pattern),
        "current_proxy_cost": float(current_proxy),
        "selected_proxy_cost": float(best_proxy),
        "complete_evaluations": 0,
        "exact_decoder_updates": 0,
        "improvements": 0,
    }
    if best_pattern == current_tuple:
        activity["stop_reason"] = "current_pattern_is_best"
        return solution, float(incumbent_objective), activity

    delta = float(best_proxy) - float(current_proxy)
    objective = float(incumbent_objective) + delta
    activity["objective_delta"] = delta
    activity["exact_decoder_updates"] = 1
    if objective < incumbent_objective - 1.0e-9:
        activity["improvements"] = 1
        return best_candidate, objective, activity
    activity["stop_reason"] = "exact_decoder_delta_did_not_improve"
    return solution, float(incumbent_objective), activity


def _run_v6(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any,
    use_joint_decoder: bool,
    use_carbon_decoder: bool,
    algorithm_label: str,
) -> ArmResult:
    started = time.perf_counter()
    total = max(0, int(eval_budget))
    base = run_pure_alns(
        bundle_dir,
        seed=seed,
        eval_budget=total,
        prices=prices,
    )
    if total == 0:
        return ArmResult(
            algorithm=algorithm_label,
            best_solution=base.best_solution,
            best_cost=float(base.best_cost),
            evaluations=0,
            elapsed_seconds=time.perf_counter() - started,
            route_count=len(base.best_solution.routes),
            feasible=base.feasible,
            mechanism_activity={
                "base_alns_activity": base.mechanism_activity,
                "joint_activity": {
                    "development_ablation": (
                        "joint_decoder_removed"
                        if not use_joint_decoder
                        else "zero_budget"
                    ),
                    "complete_evaluations": 0,
                    "improvements": 0,
                },
                "carbon_activity": {
                    "development_ablation": (
                        "carbon_decoder_removed"
                        if not use_carbon_decoder
                        else "zero_budget"
                    ),
                    "complete_evaluations": 0,
                    "improvements": 0,
                },
            },
        )

    bundle = load_search_bundle(bundle_dir)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=EvalBudget(limit=0, target=0),
    )
    solution = base.best_solution
    objective = float(base.best_cost)
    if use_joint_decoder:
        solution, objective, joint_activity = exact_joint_fleet_charge_decode(
            solution,
            context,
            incumbent_objective=objective,
        )
    else:
        joint_activity = {
            "development_ablation": "joint_decoder_removed",
            "complete_evaluations": 0,
            "exact_decoder_updates": 0,
            "improvements": 0,
        }
    if use_carbon_decoder:
        solution, objective, carbon_activity = carbon_aware_depot_retime(
            solution,
            context,
            incumbent_objective=objective,
            consume_complete_evaluation=False,
        )
    else:
        carbon_activity = {
            "development_ablation": "carbon_decoder_removed",
            "complete_evaluations": 0,
            "exact_decoder_updates": 0,
            "improvements": 0,
        }

    recomputed = independent_cost(bundle_dir, solution, prices)
    violations = check_solution(solution, bundle.instance, prices)
    if abs(recomputed - objective) > 1.0e-7:
        raise RuntimeError(
            "v6 exact-decoder objective mismatch after independent replay: "
            f"{objective} != {recomputed}"
        )
    return ArmResult(
        algorithm=algorithm_label,
        best_solution=solution,
        best_cost=float(objective),
        evaluations=int(base.evaluations),
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(solution.routes),
        feasible=not violations,
        mechanism_activity={
            "base_alns_activity": base.mechanism_activity,
            "joint_activity": joint_activity,
            "carbon_activity": carbon_activity,
            "independent_final_replays": 1,
            "final_recomputed_cost": float(recomputed),
        },
    )


def run_mechanism_alns_v6(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
) -> ArmResult:
    return _run_v6(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        prices=prices,
        use_joint_decoder=True,
        use_carbon_decoder=True,
        algorithm_label="mechanism_alns_v6",
    )


def run_mechanism_alns_v6_without_joint(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
) -> ArmResult:
    return _run_v6(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        prices=prices,
        use_joint_decoder=False,
        use_carbon_decoder=True,
        algorithm_label="mechanism_alns_v6_without_joint_ablation",
    )


def run_mechanism_alns_v6_without_carbon(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
) -> ArmResult:
    return _run_v6(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        prices=prices,
        use_joint_decoder=True,
        use_carbon_decoder=False,
        algorithm_label="mechanism_alns_v6_without_carbon_ablation",
    )

