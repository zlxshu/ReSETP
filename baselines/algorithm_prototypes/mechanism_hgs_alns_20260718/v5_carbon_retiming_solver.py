"""Mechanism-first ALNS v5 with carbon-aware depot-charge retiming.

This isolated development layer preserves the v4 routing, fleet, and charging
quantity decisions.  It adds one model-specific expert: after a route returns
to its home depot, the expert retimes the already-required charge inside the
checker-approved overnight window.  Candidate start times are the exact
breakpoints of the piecewise-constant carbon profile (including shifted end
breakpoints), so the route and energy quantity are never changed.

The expert uses route-local arithmetic for screening and consumes at most one
complete-solution evaluation.  If it has no feasible improvement, the reserved
evaluation is returned to the current ALNS as a one-evaluation continuation.
This file is development-only and does not alter the formal solver.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time
from typing import Any

from prototype import ArmResult, independent_cost
from setp_solver.algorithms.resetp_alns.runtime.budgeted_scoring import (
    score_search_candidate,
)
from setp_solver.check import check_solution
from setp_solver.cost import (
    CARBON_SLOT_SECONDS,
    GCO2_PER_KGCO2,
    _price,
    carbon_profile_row_for_slot,
    charging_slot_breakdown,
    route_next_day_departure_second,
    route_return_arrival_without_charging,
)
from setp_solver.prices import DEFAULT_PRICES, PriceParameters
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import ChargingAction, Route, Solution
from v4_mechanism_alns_solver import run_mechanism_alns_v4


def _effective_carbon_price(
    prices: PriceParameters | dict[str, float] | Any,
    carbon_weight: float,
) -> float:
    return _price(prices, "carbon_price") * float(carbon_weight)


def _charging_emissions_kg(
    action: ChargingAction,
    *,
    instance: Any,
    carbon_profile: list[dict[str, Any]],
) -> float:
    emissions = 0.0
    for slot in charging_slot_breakdown(
        float(action.charge_start_second),
        float(action.occupancy_minutes) * 60.0,
        float(action.energy_kwh),
        instance,
        n_slots=len(carbon_profile),
        cyclic=True,
    ):
        row = carbon_profile_row_for_slot(carbon_profile, slot.slot_index)
        emissions += (
            float(slot.y_skt_kwh)
            * float(row["actual_gco2_per_kwh"])
            / GCO2_PER_KGCO2
        )
    return float(emissions)


def _depot_charge_local_objective(
    action: ChargingAction,
    context: EvaluationContext,
) -> float:
    return (
        float(action.energy_kwh)
        * _price(context.prices, "depot_electricity_price")
        + _charging_emissions_kg(
            action,
            instance=context.instance,
            carbon_profile=context.carbon_profile,
        )
        * _effective_carbon_price(context.prices, context.carbon_weight)
    )


def depot_charge_candidate_starts(
    *,
    earliest_start: float,
    latest_start: float,
    occupancy_seconds: float,
    current_start: float,
) -> tuple[float, ...]:
    """Return all breakpoints needed for exact one-action retiming.

    For a fixed-duration charge under a piecewise-constant signal, the
    integrated objective is piecewise linear in the start time.  A minimum is
    therefore attained at a window endpoint, a signal boundary, or a point
    where the charge end meets a signal boundary.
    """

    lower = float(earliest_start)
    upper = float(latest_start)
    duration = float(occupancy_seconds)
    if upper < lower - 1.0e-9:
        return ()
    candidates = {lower, upper}
    if lower - 1.0e-9 <= float(current_start) <= upper + 1.0e-9:
        candidates.add(float(current_start))
    first_boundary = int((lower - duration) // CARBON_SLOT_SECONDS) - 2
    last_boundary = int((upper + duration) // CARBON_SLOT_SECONDS) + 2
    for index in range(first_boundary, last_boundary + 1):
        boundary = float(index) * float(CARBON_SLOT_SECONDS)
        for start in (boundary, boundary - duration):
            if lower - 1.0e-9 <= start <= upper + 1.0e-9:
                candidates.add(min(upper, max(lower, float(start))))
    return tuple(sorted(candidates))


def _depot_action_window(
    action: ChargingAction,
    route: Route,
    context: EvaluationContext,
) -> tuple[float, float] | None:
    if int(action.charge_day_offset) != 0:
        return None
    node_lookup = {node.node_id: node for node in context.instance.nodes}
    station = node_lookup.get(action.station_id)
    if (
        station is None
        or station.node_type.lower() != "d"
        or action.station_id != route.home_depot_id
        or action.station_id != route.node_sequence[0]
    ):
        return None
    earliest = route_return_arrival_without_charging(
        route,
        context.instance,
        context.prices,
    )
    latest = route_next_day_departure_second(
        route,
        context.instance,
        context.prices,
    ) - float(action.occupancy_minutes) * 60.0
    if latest < earliest - 1.0e-9:
        return None
    return float(earliest), float(latest)


def carbon_aware_depot_retime(
    solution: Solution,
    context: EvaluationContext,
    *,
    incumbent_objective: float,
    consume_complete_evaluation: bool = True,
) -> tuple[Solution, float, dict[str, Any]]:
    """Retime existing depot charges under one of two explicit ledgers.

    ``consume_complete_evaluation=True`` is the conservative component probe:
    it submits the selected schedule as one full search candidate. ``False``
    is the embedded fixed-route decoder: since only charge starts change and
    route-local charging cost is exactly separable here, it applies the exact
    local objective delta without consuming a route-search evaluation. The
    caller must independently replay the final complete solution.
    """

    budget = context.budget
    activity: dict[str, Any] = {
        "eligible_actions": 0,
        "actions_retimed": 0,
        "candidate_start_count": 0,
        "route_local_schedule_evaluations": 0,
        "complete_evaluations": 0,
        "exact_decoder_updates": 0,
        "feasibility_checks": 0,
        "improvements": 0,
        "old_local_objective": 0.0,
        "selected_local_objective": 0.0,
        "action_changes": [],
    }
    if (
        consume_complete_evaluation
        and budget is not None
        and budget.count >= budget.limit
    ):
        activity["stop_reason"] = "no_complete_evaluation_budget"
        return solution, float(incumbent_objective), activity

    routes = {route.vehicle_id: route for route in solution.routes}
    selected_actions = list(solution.charging_actions)
    proposals: list[
        tuple[int, ChargingAction, ChargingAction, float, float]
    ] = []
    for index, action in enumerate(solution.charging_actions):
        route = routes.get(action.vehicle_id)
        if route is None:
            continue
        window = _depot_action_window(action, route, context)
        if window is None:
            continue
        activity["eligible_actions"] += 1
        starts = depot_charge_candidate_starts(
            earliest_start=window[0],
            latest_start=window[1],
            occupancy_seconds=float(action.occupancy_minutes) * 60.0,
            current_start=float(action.charge_start_second),
        )
        activity["candidate_start_count"] += len(starts)
        old_local = _depot_charge_local_objective(action, context)
        activity["old_local_objective"] += old_local
        options: list[tuple[float, float, ChargingAction]] = []
        for start in starts:
            candidate_action = replace(action, charge_start_second=float(start))
            local_objective = _depot_charge_local_objective(
                candidate_action,
                context,
            )
            activity["route_local_schedule_evaluations"] += 1
            options.append((float(local_objective), float(start), candidate_action))
        if not options:
            activity["selected_local_objective"] += old_local
            continue

        local_objective, _, candidate_action = min(options)
        if local_objective < old_local - 1.0e-12:
            proposals.append(
                (
                    index,
                    action,
                    candidate_action,
                    old_local,
                    local_objective,
                )
            )
        else:
            activity["selected_local_objective"] += old_local

    if not proposals:
        activity["stop_reason"] = "no_feasible_improving_retime"
        return solution, float(incumbent_objective), activity

    def record_change(
        old_action: ChargingAction,
        new_action: ChargingAction,
    ) -> None:
        activity["actions_retimed"] += 1
        activity["action_changes"].append(
            {
                "vehicle_id": old_action.vehicle_id,
                "station_id": old_action.station_id,
                "old_start_second": float(old_action.charge_start_second),
                "new_start_second": float(new_action.charge_start_second),
                "old_emissions_kg": _charging_emissions_kg(
                    old_action,
                    instance=context.instance,
                    carbon_profile=context.carbon_profile,
                ),
                "new_emissions_kg": _charging_emissions_kg(
                    new_action,
                    instance=context.instance,
                    carbon_profile=context.carbon_profile,
                ),
            }
        )

    # Fast path: all route-local optima are assembled first and the complete
    # solution is checked once.  Only a real shared-capacity conflict falls
    # back to sequential acceptance.
    for index, _, candidate_action, _, _ in proposals:
        selected_actions[index] = candidate_action
    candidate = Solution(
        routes=list(solution.routes),
        charging_actions=selected_actions,
        cross_site_services=list(solution.cross_site_services),
    )
    activity["feasibility_checks"] += 1
    combined_violations = check_solution(
        candidate,
        context.instance,
        context.prices,
    )
    if not combined_violations:
        for _, old_action, candidate_action, _, selected_local in proposals:
            record_change(old_action, candidate_action)
            activity["selected_local_objective"] += selected_local
    else:
        activity["combined_schedule_violation_count"] = len(
            combined_violations
        )
        selected_actions = list(solution.charging_actions)
        for (
            index,
            old_action,
            candidate_action,
            old_local,
            selected_local,
        ) in sorted(
            proposals,
            key=lambda item: item[4] - item[3],
        ):
            trial_actions = list(selected_actions)
            trial_actions[index] = candidate_action
            trial = Solution(
                routes=list(solution.routes),
                charging_actions=trial_actions,
                cross_site_services=list(solution.cross_site_services),
            )
            activity["feasibility_checks"] += 1
            if check_solution(trial, context.instance, context.prices):
                activity["selected_local_objective"] += old_local
                continue
            selected_actions = trial_actions
            record_change(old_action, candidate_action)
            activity["selected_local_objective"] += selected_local
        if not activity["actions_retimed"]:
            activity["stop_reason"] = "no_feasible_improving_retime"
            return solution, float(incumbent_objective), activity
        candidate = Solution(
            routes=list(solution.routes),
            charging_actions=selected_actions,
            cross_site_services=list(solution.cross_site_services),
        )

    if not consume_complete_evaluation:
        delta = (
            float(activity["selected_local_objective"])
            - float(activity["old_local_objective"])
        )
        objective = float(incumbent_objective) + delta
        activity["exact_decoder_updates"] = 1
        activity["objective_delta"] = float(delta)
        if objective < incumbent_objective - 1.0e-9:
            activity["improvements"] = 1
            return candidate, objective, activity
        activity["stop_reason"] = "exact_decoder_delta_did_not_improve"
        return solution, float(incumbent_objective), activity

    candidate, objective = score_search_candidate(
        candidate,
        context,
        channel="carbon_aware_depot_charge_retime",
    )
    activity["complete_evaluations"] = 1
    if objective < incumbent_objective - 1.0e-9:
        activity["improvements"] = 1
        return candidate, float(objective), activity
    activity["stop_reason"] = "complete_score_did_not_improve"
    return solution, float(incumbent_objective), activity


def _run_v5(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any,
    depot_room: int,
    use_carbon_retiming: bool,
    algorithm_label: str,
) -> ArmResult:
    started = time.perf_counter()
    total = max(0, int(eval_budget))
    if total == 0:
        base = run_mechanism_alns_v4(
            bundle_dir,
            seed=seed,
            eval_budget=0,
            prices=prices,
            depot_room=depot_room,
        )
        return replace(
            base,
            algorithm=algorithm_label,
            elapsed_seconds=time.perf_counter() - started,
            mechanism_activity={
                "v4_activity": base.mechanism_activity,
                "carbon_activity": {
                    "development_ablation": (
                        "carbon_retiming_removed"
                        if not use_carbon_retiming
                        else "zero_budget"
                    ),
                    "complete_evaluations": 0,
                    "improvements": 0,
                },
            },
        )

    base = run_mechanism_alns_v4(
        bundle_dir,
        seed=seed,
        eval_budget=total,
        prices=prices,
        depot_room=depot_room,
    )
    bundle = load_search_bundle(bundle_dir)
    solution = base.best_solution
    objective = float(base.best_cost)
    carbon_budget = EvalBudget(limit=0, target=0)
    carbon_context = EvaluationContext(
        bundle.instance,
        bundle.carbon_profile,
        prices=prices,
        budget=carbon_budget,
    )
    if use_carbon_retiming:
        solution, objective, carbon_activity = carbon_aware_depot_retime(
            solution,
            carbon_context,
            incumbent_objective=objective,
            consume_complete_evaluation=False,
        )
    else:
        carbon_activity = {
            "development_ablation": "carbon_retiming_removed",
            "complete_evaluations": 0,
            "improvements": 0,
        }

    evaluations = base.evaluations
    recomputed = independent_cost(bundle_dir, solution, prices)
    violations = check_solution(solution, bundle.instance, prices)
    if abs(recomputed - objective) > 1.0e-7:
        raise RuntimeError(
            "v5 objective mismatch after independent replay: "
            f"{objective} != {recomputed}"
        )
    return ArmResult(
        algorithm=algorithm_label,
        best_solution=solution,
        best_cost=float(objective),
        evaluations=int(evaluations),
        elapsed_seconds=time.perf_counter() - started,
        route_count=len(solution.routes),
        feasible=not violations,
        mechanism_activity={
            "v4_activity": base.mechanism_activity,
            "carbon_activity": carbon_activity,
            "carbon_fixed_route_decoder_complete_evaluations": 0,
            "independent_final_replays": 1,
            "final_recomputed_cost": float(recomputed),
        },
    )


def run_mechanism_alns_v5(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    depot_room: int = 2,
) -> ArmResult:
    """Run v4 plus the carbon-aware depot-charge retiming expert."""

    return _run_v5(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        prices=prices,
        depot_room=depot_room,
        use_carbon_retiming=True,
        algorithm_label="mechanism_alns_v5",
    )


def run_mechanism_alns_v5_without_carbon(
    bundle_dir: str | Path,
    *,
    seed: int,
    eval_budget: int,
    prices: Any = DEFAULT_PRICES,
    depot_room: int = 2,
) -> ArmResult:
    """Equal-budget ablation that returns the reserved score to ALNS."""

    return _run_v5(
        bundle_dir,
        seed=seed,
        eval_budget=eval_budget,
        prices=prices,
        depot_room=depot_room,
        use_carbon_retiming=False,
        algorithm_label="mechanism_alns_v5_without_carbon_ablation",
    )


def action_change_dicts(result: ArmResult) -> list[dict[str, Any]]:
    """Small serialization helper used by the isolated evidence runner."""

    carbon = result.mechanism_activity.get("carbon_activity", {})
    return [
        dict(item)
        for item in carbon.get("action_changes", [])
        if isinstance(item, dict)
    ]
