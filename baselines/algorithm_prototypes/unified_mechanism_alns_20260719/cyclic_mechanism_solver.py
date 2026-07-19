"""Monotone route--mechanism coordinate descent after one continuous ALNS.

The ordinary ALNS first spends the complete B-budget without interruption.
The frozen responsibility, fleet/charging, and carbon-time experts then
complete its best route skeleton.  A route-order expert subsequently explores
standard intra-route 2-opt and relocate neighbours, but scores each affected
route with the vehicle, charging, and time-varying carbon decisions currently
attached to it.  Any accepted route change is completed by the three mechanism
experts again.  This creates a bounded route -> mechanism -> route feedback
cycle without restarting ALNS or replacing its learned state.

Every block is strict-improvement-only and the ordinary v7 completion remains
in the final envelope.  Route-neighbour costs are affected-route calculations,
not hidden complete-solution candidate evaluations; the final saved solution
is independently replayed through the unchanged project evaluator/checker.

The route neighbourhood follows the local-improvement tradition used by
Ropke--Pisinger (2006) and Vidal et al. (2012, 2022).  The separation between
route search and fleet/charging completion follows Hiermann et al. (2019).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Iterable

from prototype import ArmResult, independent_cost, run_pure_alns
from setp_solver.algorithms.resetp_alns.support.charging import (
    repair_route_charging,
)
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import ChargingAction, Route, Solution
from terminal_completion import apply_terminal_completion
from v5_carbon_retiming_solver import carbon_aware_depot_retime


TOL = 1.0e-9


@dataclass(frozen=True)
class CyclicMechanismConfig:
    """Bounded, result-independent controls for route--mechanism feedback."""

    total_eval_budget: int = 100
    max_cycles: int = 2
    max_route_moves_per_cycle: int = 3


@dataclass(frozen=True)
class RoutePolishResult:
    solution: Solution
    cost: float
    activity: dict[str, Any]


def run_cyclic_mechanism_alns(
    bundle_dir: str | Path,
    *,
    seed: int,
    config: CyclicMechanismConfig | None = None,
    prices: Any = DEFAULT_PRICES,
) -> ArmResult:
    """Run continuous ALNS followed by monotone mechanism feedback cycles."""

    cfg = config or CyclicMechanismConfig()
    budget = max(0, int(cfg.total_eval_budget))
    started = time.perf_counter()
    base = run_pure_alns(
        bundle_dir,
        seed=int(seed),
        eval_budget=budget,
        prices=prices,
    )
    if int(base.evaluations) != budget:
        raise RuntimeError(
            f"cyclic mechanism ALNS budget mismatch: {base.evaluations} != {budget}"
        )

    ordinary = apply_terminal_completion(
        bundle_dir,
        base.best_solution,
        prices=prices,
    )
    if not ordinary.feasible:
        raise RuntimeError("ordinary terminal completion is infeasible")
    best_solution = ordinary.solution
    best_cost = float(ordinary.cost)
    cycle_rows: list[dict[str, Any]] = []
    route_local_evaluations = 0
    route_feasibility_checks = 0
    completion_replays = int(
        ordinary.activity.get("full_solution_replays", 0)
    )
    completion_route_exact = int(
        ordinary.activity.get("route_local_exact_evaluations", 0)
    )
    completion_route_proxy = int(
        ordinary.activity.get("route_proxy_evaluations", 0)
    )
    completion_schedule = int(
        ordinary.activity.get("route_local_schedule_evaluations", 0)
    )

    for cycle_index in range(max(0, int(cfg.max_cycles))):
        polished = exact_mechanism_route_order_polish(
            bundle_dir,
            best_solution,
            incumbent_objective=best_cost,
            prices=prices,
            max_moves=max(0, int(cfg.max_route_moves_per_cycle)),
        )
        route_local_evaluations += int(
            polished.activity["route_local_evaluations"]
        )
        route_feasibility_checks += int(
            polished.activity["full_feasibility_checks"]
        )
        row: dict[str, Any] = {
            "cycle": cycle_index + 1,
            "source_cost": float(best_cost),
            "after_route_polish_cost": float(polished.cost),
            "route_moves_accepted": int(
                polished.activity["accepted_move_count"]
            ),
            "route_local_evaluations": int(
                polished.activity["route_local_evaluations"]
            ),
            "full_feasibility_checks": int(
                polished.activity["full_feasibility_checks"]
            ),
            "route_polish_stop_reason": str(
                polished.activity["stop_reason"]
            ),
        }
        if polished.cost >= best_cost - TOL:
            row["completion_attempted"] = False
            cycle_rows.append(row)
            break

        completed = apply_terminal_completion(
            bundle_dir,
            polished.solution,
            prices=prices,
        )
        completion_replays += int(
            completed.activity.get("full_solution_replays", 0)
        )
        completion_route_exact += int(
            completed.activity.get("route_local_exact_evaluations", 0)
        )
        completion_route_proxy += int(
            completed.activity.get("route_proxy_evaluations", 0)
        )
        completion_schedule += int(
            completed.activity.get("route_local_schedule_evaluations", 0)
        )
        row.update(
            {
                "completion_attempted": True,
                "after_completion_cost": float(completed.cost),
                "completion_selected_branch": str(
                    completed.selected_branch
                ),
                "responsibility_updates": int(
                    completed.activity.get("responsibility", {}).get(
                        "exact_decoder_updates",
                        0,
                    )
                ),
                "fleet_charge_updates": int(
                    completed.activity.get("joint", {}).get(
                        "exact_decoder_updates",
                        0,
                    )
                ),
                "carbon_updates": int(
                    completed.activity.get("carbon", {}).get(
                        "exact_decoder_updates",
                        0,
                    )
                ),
            }
        )
        if completed.cost < best_cost - TOL:
            best_solution = completed.solution
            best_cost = float(completed.cost)
            row["cycle_accepted"] = True
        else:
            row["cycle_accepted"] = False
            cycle_rows.append(row)
            break
        cycle_rows.append(row)

    recomputed = independent_cost(bundle_dir, best_solution, prices)
    if abs(float(recomputed) - float(best_cost)) > 1.0e-7:
        raise RuntimeError(
            f"cyclic mechanism objective mismatch: {best_cost} != {recomputed}"
        )
    if recomputed > ordinary.cost + TOL:
        raise RuntimeError(
            f"cyclic mechanism envelope regressed: {recomputed} > {ordinary.cost}"
        )
    bundle = load_search_bundle(bundle_dir)
    violations = check_solution(best_solution, bundle.instance, prices)
    if violations:
        raise RuntimeError(
            f"cyclic mechanism final solution is infeasible: {violations[:8]}"
        )
    return ArmResult(
        algorithm="cyclic_mechanism_alns",
        best_solution=best_solution,
        best_cost=float(recomputed),
        evaluations=int(base.evaluations),
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(best_solution.routes),
        feasible=True,
        mechanism_activity={
            "continuous_main_search": True,
            "feedback_into_main_search": False,
            "complete_search_candidate_evaluations": int(base.evaluations),
            "ordinary_v7_completed_cost": float(ordinary.cost),
            "ordinary_v7_selected_branch": str(ordinary.selected_branch),
            "strict_gain_over_v7": bool(
                recomputed < ordinary.cost - TOL
            ),
            "gain_over_v7_percent": (
                (float(ordinary.cost) - float(recomputed))
                / float(ordinary.cost)
                * 100.0
                if float(ordinary.cost) > 0.0
                else 0.0
            ),
            "cycles_attempted": len(cycle_rows),
            "cycles": cycle_rows,
            "route_moves_accepted": sum(
                int(row["route_moves_accepted"])
                for row in cycle_rows
            ),
            "route_local_evaluations": int(route_local_evaluations),
            "route_full_feasibility_checks": int(
                route_feasibility_checks
            ),
            "completion_reference_replays": int(completion_replays),
            "completion_route_local_exact_evaluations": int(
                completion_route_exact
            ),
            "completion_route_proxy_evaluations": int(
                completion_route_proxy
            ),
            "completion_route_local_schedule_evaluations": int(
                completion_schedule
            ),
            "independent_final_replays": 1,
            "base_alns_activity": base.mechanism_activity,
            "total_compute_equalized": False,
        },
    )


def exact_mechanism_route_order_polish(
    bundle_dir: str | Path,
    solution: Solution,
    *,
    incumbent_objective: float,
    prices: Any = DEFAULT_PRICES,
    max_moves: int = 3,
) -> RoutePolishResult:
    """Best-improvement 2-opt/relocate using affected-route exact costs."""

    bundle = load_search_bundle(bundle_dir)
    context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=EvalBudget(limit=0, target=0),
        allow_cross_depot=True,
    )
    current = solution
    objective = float(incumbent_objective)
    route_local_evaluations = 0
    full_feasibility_checks = 0
    proxy_moves_considered = 0
    accepted: list[dict[str, Any]] = []

    for move_index in range(max(0, int(max_moves))):
        selected: tuple[
            float,
            int,
            str,
            tuple[str, ...],
            Solution,
            dict[str, Any],
        ] | None = None
        for route_index, route in enumerate(current.routes):
            customers = _customer_ids(route, bundle.instance)
            if len(customers) < 2:
                continue
            current_actions = tuple(
                action
                for action in current.charging_actions
                if action.vehicle_id == route.vehicle_id
            )
            current_route_cost = _route_cost(
                route,
                current_actions,
                context,
            )
            for kind, order in _route_order_neighbours(customers):
                proxy_moves_considered += 1
                built = _build_route_variant(
                    route,
                    order,
                    context,
                )
                route_local_evaluations += 1
                if built is None:
                    continue
                candidate_route, candidate_actions, candidate_route_cost = (
                    built
                )
                claimed = (
                    objective
                    + float(candidate_route_cost)
                    - float(current_route_cost)
                )
                if claimed >= objective - TOL:
                    continue
                candidate = _replace_route(
                    current,
                    route_index,
                    candidate_route,
                    candidate_actions,
                )
                candidate, claimed, carbon = carbon_aware_depot_retime(
                    candidate,
                    context,
                    incumbent_objective=claimed,
                    consume_complete_evaluation=False,
                )
                full_feasibility_checks += 1
                if check_solution(
                    candidate,
                    bundle.instance,
                    prices,
                ):
                    continue
                rank = (
                    float(claimed),
                    int(route_index),
                    str(kind),
                    tuple(order),
                )
                if selected is None or rank < selected[:4]:
                    selected = (
                        *rank,
                        candidate,
                        carbon,
                    )
        if selected is None:
            stop_reason = "no_improving_route_neighbour"
            break
        (
            selected_objective,
            route_index,
            kind,
            order,
            candidate,
            carbon,
        ) = selected
        delta = float(selected_objective) - float(objective)
        current = candidate
        objective = float(selected_objective)
        accepted.append(
            {
                "move": move_index + 1,
                "kind": str(kind),
                "route_index": int(route_index),
                "customer_order": list(order),
                "exact_objective_delta": float(delta),
                "carbon_updates": int(
                    carbon.get("exact_decoder_updates", 0)
                ),
                "carbon_actions_retimed": int(
                    carbon.get("actions_retimed", 0)
                ),
            }
        )
    else:
        stop_reason = "max_moves_reached"

    recomputed = float(
        evaluate(
            current,
            bundle.instance,
            bundle.carbon_profile,
            prices,
        )["total_cost"]
    )
    if abs(recomputed - objective) > 1.0e-7:
        raise RuntimeError(
            "route-local objective did not close under full replay: "
            f"{objective} != {recomputed}"
        )
    if recomputed > incumbent_objective + TOL:
        raise RuntimeError(
            "route-order polish violated monotonicity: "
            f"{recomputed} > {incumbent_objective}"
        )
    return RoutePolishResult(
        solution=current,
        cost=float(recomputed),
        activity={
            "accepted_move_count": len(accepted),
            "accepted_moves": accepted,
            "route_local_evaluations": int(route_local_evaluations),
            "proxy_moves_considered": int(proxy_moves_considered),
            "full_feasibility_checks": int(full_feasibility_checks),
            "independent_final_replays": 1,
            "stop_reason": stop_reason,
        },
    )


def _customer_ids(route: Route, instance: Any) -> list[str]:
    nodes = {node.node_id: node for node in instance.nodes}
    return [
        node_id
        for node_id in route.node_sequence
        if node_id in nodes and nodes[node_id].node_type.lower() == "c"
    ]


def _route_order_neighbours(
    customers: list[str],
) -> Iterable[tuple[str, tuple[str, ...]]]:
    seen: set[tuple[str, ...]] = {tuple(customers)}
    count = len(customers)
    for start in range(count - 1):
        for end in range(start + 1, count):
            candidate = tuple(
                [
                    *customers[:start],
                    *reversed(customers[start : end + 1]),
                    *customers[end + 1 :],
                ]
            )
            if candidate not in seen:
                seen.add(candidate)
                yield "two_opt", candidate
    for source in range(count):
        customer = customers[source]
        remaining = [
            node
            for index, node in enumerate(customers)
            if index != source
        ]
        for target in range(count):
            candidate_list = list(remaining)
            candidate_list.insert(target, customer)
            candidate = tuple(candidate_list)
            if candidate not in seen:
                seen.add(candidate)
                yield "relocate", candidate


def _build_route_variant(
    source: Route,
    customers: tuple[str, ...],
    context: EvaluationContext,
) -> tuple[Route, tuple[ChargingAction, ...], float] | None:
    route = Route(
        vehicle_id=source.vehicle_id,
        vehicle_type=source.vehicle_type,
        home_depot_id=source.home_depot_id,
        node_sequence=[
            source.home_depot_id,
            *customers,
            source.home_depot_id,
        ],
    )
    actions: tuple[ChargingAction, ...] = ()
    if source.vehicle_type.lower() == "ev":
        try:
            route, repaired = repair_route_charging(
                route,
                context.instance,
                context.carbon_profile,
                context.prices,
            )
        except ValueError:
            return None
        actions = tuple(repaired)
    objective = _route_cost(route, actions, context)
    return route, actions, float(objective)


def _route_cost(
    route: Route,
    actions: tuple[ChargingAction, ...],
    context: EvaluationContext,
) -> float:
    return float(
        evaluate(
            Solution(
                routes=[route],
                charging_actions=list(actions),
            ),
            context.instance,
            context.carbon_profile,
            context.prices,
        )["total_cost"]
    )


def _replace_route(
    solution: Solution,
    route_index: int,
    route: Route,
    actions: tuple[ChargingAction, ...],
) -> Solution:
    routes = list(solution.routes)
    old_vehicle = routes[route_index].vehicle_id
    routes[route_index] = route
    retained_actions = [
        action
        for action in solution.charging_actions
        if action.vehicle_id != old_vehicle
    ]
    return Solution(
        routes=routes,
        charging_actions=[*retained_actions, *actions],
        cross_site_services=list(solution.cross_site_services),
    )
