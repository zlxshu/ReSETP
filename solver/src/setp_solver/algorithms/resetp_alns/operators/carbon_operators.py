"""Carbon-aware ALNS operators for the 09x probe variant."""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Any

import numpy as np

from setp_solver.check import check_solution
from setp_solver.cost import carbon_profile_row_for_slot, charging_slot_breakdown, evaluate
from setp_solver.solution import Route, Solution
from setp_solver.search.evaluation import BIG_M
from setp_solver.algorithms.resetp_alns.operators.feasible_repair import enumerate_feasible_insertions
from setp_solver.algorithms.resetp_alns.support.carbon_charging import integrated_charge_carbon_kg
from setp_solver.algorithms.resetp_alns.support.charging import repair_route_charging


def low_carbon_charging_share(solution: Solution, instance: Any, carbon_profile: list[dict[str, Any]], prices: Any) -> float:
    """Return charged energy share that lands in the lowest quartile gamma slots."""

    del prices
    if not carbon_profile or not solution.charging_actions:
        return 0.0
    sorted_gamma = sorted(_gamma(row) for row in carbon_profile)
    low_count = max(1, math.ceil(len(sorted_gamma) * 0.25))
    low_cutoff = sorted_gamma[low_count - 1]
    low_energy = 0.0
    total_energy = 0.0
    for action in solution.charging_actions:
        duration = float(action.occupancy_minutes) * 60.0
        energy = float(action.energy_kwh)
        if duration <= 1e-9 or energy <= 1e-9:
            continue
        for slot in charging_slot_breakdown(
            float(action.charge_start_second),
            duration,
            energy,
            instance,
            n_slots=len(carbon_profile),
            cyclic=True,
        ):
            gamma = _slot_gamma(carbon_profile, slot.slot_index)
            total_energy += float(slot.y_skt_kwh)
            if gamma <= low_cutoff + 1e-12:
                low_energy += float(slot.y_skt_kwh)
    return low_energy / total_energy if total_energy > 1e-12 else 0.0


def worst_carbon_removal(state: Any, rng: np.random.Generator, **kwargs: Any) -> Any:
    """Remove customers from the currently highest-carbon routes."""

    weight = float(kwargs.get("carbon_bias_weight", 1.0))
    if weight <= 1e-12:
        from setp_solver.algorithms.resetp_alns.kernel.alns_core import worst_customer_removal

        return worst_customer_removal(state, rng, **kwargs)
    from setp_solver.algorithms.resetp_alns.kernel.alns_core import _adaptive_remove_count, _remove_customers, _route_customer_ids

    route_items = [(route, _route_customer_ids(route, state.context.instance)) for route in state.solution.routes]
    route_items = [(route, customers) for route, customers in route_items if customers]
    if not route_items:
        return state
    customer_count = sum(len(customers) for _, customers in route_items)
    remove_count = _adaptive_remove_count(
        customer_count,
        rng,
        progress=float(kwargs.get("progress", 0.0)),
        remove_count_q=kwargs.get("remove_count_q"),
    )
    ranked = sorted(route_items, key=lambda item: (_route_carbon_kg(item[0], state.solution, state.context), item[0].vehicle_id), reverse=True)
    removed: list[str] = []
    for _, customers in ranked:
        removed.extend(customers)
        if len(removed) >= remove_count:
            break
    return _remove_customers(state, removed[:remove_count])


def carbon_related_removal(state: Any, rng: np.random.Generator, **kwargs: Any) -> Any:
    """Shaw-style removal that adds route carbon similarity to spatial relatedness."""

    weight = float(kwargs.get("carbon_bias_weight", 1.0))
    if weight <= 1e-12:
        from setp_solver.algorithms.resetp_alns.kernel.alns_core import shaw_related_removal

        return shaw_related_removal(state, rng, **kwargs)
    from setp_solver.algorithms.resetp_alns.kernel.alns_core import _adaptive_remove_count, _remove_customers, _route_customer_ids

    route_items = [(route, _route_customer_ids(route, state.context.instance)) for route in state.solution.routes]
    route_items = [(route, customers) for route, customers in route_items if customers]
    if not route_items:
        return state
    customer_count = sum(len(customers) for _, customers in route_items)
    remove_count = _adaptive_remove_count(
        customer_count,
        rng,
        progress=float(kwargs.get("progress", 0.0)),
        remove_count_q=kwargs.get("remove_count_q"),
    )
    route_carbon = {route.vehicle_id: _route_carbon_kg(route, state.solution, state.context) for route, _ in route_items}
    seed_route, seed_customers = max(route_items, key=lambda item: (route_carbon[item[0].vehicle_id], item[0].vehicle_id))
    seed_customer = seed_customers[int(rng.integers(0, len(seed_customers)))]
    node_lookup = {node.node_id: node for node in state.context.instance.nodes}
    seed_node = node_lookup.get(seed_customer)
    seed_ready = float(getattr(seed_node, "ready_time", 0.0)) if seed_node is not None else 0.0
    seed_carbon = route_carbon[seed_route.vehicle_id]
    scored: list[tuple[float, str]] = []
    for route, customers in route_items:
        carbon_gap = abs(route_carbon[route.vehicle_id] - seed_carbon)
        for customer_id in customers:
            node = node_lookup.get(customer_id)
            ready = float(getattr(node, "ready_time", 0.0)) if node is not None else 0.0
            try:
                distance = float(state.context.instance.distance(seed_customer, customer_id))
            except Exception:
                distance = BIG_M
            relatedness = distance + 0.001 * abs(ready - seed_ready) + weight * carbon_gap
            scored.append((relatedness, customer_id))
    scored.sort(key=lambda item: (item[0], item[1]))
    return _remove_customers(state, [customer_id for _, customer_id in scored[:remove_count]])


def low_carbon_charging_repair(state: Any, rng: np.random.Generator, **kwargs: Any) -> Any:
    """Repair removed customers while preferring lower-carbon charging outcomes."""

    weight = float(kwargs.get("carbon_bias_weight", 1.0))
    if weight <= 1e-12:
        from setp_solver.algorithms.resetp_alns.kernel.alns_core import regret2_insert_repair

        return regret2_insert_repair(state, rng, **kwargs)
    from setp_solver.algorithms.resetp_alns.kernel.alns_core import _finalize_candidate_state, regret2_insert_repair

    pending = list(dict.fromkeys(state.removed_customers))
    if not pending:
        return _finalize_candidate_state(state)
    current = state.solution
    while pending:
        scored: list[tuple[float, float, str, Solution]] = []
        for customer_id in pending:
            options = enumerate_feasible_insertions(
                current,
                customer_id,
                state.context,
                state.policy,
                allow_new_route=state.allow_new_route_repair,
            )
            for option in options:
                carbon_penalty = _solution_carbon_kg(option.solution, state.context)
                low_share = low_carbon_charging_share(option.solution, state.context.instance, state.context.carbon_profile, state.context.prices)
                adjusted = float(option.score) + weight * (0.01 * carbon_penalty - low_share)
                scored.append((adjusted, float(option.score), customer_id, option.solution))
        if not scored:
            return regret2_insert_repair(state, rng, **kwargs)
        _, _, customer_id, current = min(scored, key=lambda item: (item[0], item[1], item[2]))
        pending.remove(customer_id)
    if check_solution(current, state.context.instance, state.context.prices):
        return regret2_insert_repair(state, rng, **kwargs)
    return _finalize_candidate_state(
        replace(
            state,
            solution=current,
            objective_value=None,
            removed_customers=(),
            source_solution=None,
            allow_new_route_repair=True,
        )
    )


def high_carbon_charge_segment_removal(state: Any, rng: np.random.Generator, **kwargs: Any) -> Any:
    """Remove customers adjacent to a high-emission charging action.

    Keskin and Catay couple customer removal with neighbouring station visits.
    Here the same idea is targeted at the action that contributes the most EV
    charging emissions.  The paired refined repair strips obsolete stations
    and reconstructs charging from scratch.
    """

    from setp_solver.algorithms.resetp_alns.kernel.alns_core import (
        _adaptive_remove_count,
        _customers_in_solution,
        _remove_customers,
        _route_customer_ids,
    )

    actions = [action for action in state.solution.charging_actions if float(action.energy_kwh) > 1e-9]
    if not actions:
        return state
    ranked = sorted(
        actions,
        key=lambda action: (
            _action_carbon_kg(action, state.context),
            float(action.energy_kwh),
            action.vehicle_id,
            action.station_id,
        ),
        reverse=True,
    )
    action = ranked[0]
    route = next((route for route in state.solution.routes if route.vehicle_id == action.vehicle_id), None)
    if route is None:
        return state
    customers = _route_customer_ids(route, state.context.instance)
    if not customers:
        return state
    q = _adaptive_remove_count(
        len(_customers_in_solution(state.solution, state.context.instance)),
        rng,
        progress=float(kwargs.get("progress", 0.0)),
        remove_count_q=kwargs.get("remove_count_q"),
    )
    node_lookup = {node.node_id: node for node in state.context.instance.nodes}
    sequence = route.node_sequence
    station_positions = [idx for idx, node_id in enumerate(sequence) if node_id == action.station_id]
    anchor = station_positions[0] if station_positions else len(sequence) // 2
    ordered = sorted(
        (
            (abs(idx - anchor), idx, node_id)
            for idx, node_id in enumerate(sequence)
            if node_lookup.get(node_id) is not None and node_lookup[node_id].node_type.lower() == "c"
        ),
        key=lambda item: (item[0], item[1], item[2]),
    )
    selected = [node_id for _, _, node_id in ordered[: min(q, len(ordered))]]
    return _remove_customers(state, selected)


def charging_station_reset_destroy(state: Any, rng: np.random.Generator, **kwargs: Any) -> Any:
    """Strip one high-carbon EV route's station visits before reconstruction."""

    del rng, kwargs
    actions = [action for action in state.solution.charging_actions if float(action.energy_kwh) > 1e-9]
    if not actions:
        return state
    vehicle_scores: dict[str, float] = {}
    for action in actions:
        vehicle_scores[action.vehicle_id] = vehicle_scores.get(action.vehicle_id, 0.0) + _action_carbon_kg(action, state.context)
    vehicle_id = max(vehicle_scores, key=lambda item: (vehicle_scores[item], item))
    node_lookup = {node.node_id: node for node in state.context.instance.nodes}
    routes: list[Route] = []
    changed = False
    for route in state.solution.routes:
        if route.vehicle_id != vehicle_id:
            routes.append(route)
            continue
        sequence = [
            node_id
            for node_id in route.node_sequence
            if node_lookup.get(node_id) is None or node_lookup[node_id].node_type.lower() != "f"
        ]
        changed = changed or sequence != route.node_sequence
        routes.append(replace(route, node_sequence=sequence))
    if not changed:
        return state
    solution = replace(
        state.solution,
        routes=routes,
        charging_actions=[action for action in state.solution.charging_actions if action.vehicle_id != vehicle_id],
    )
    return replace(
        state,
        solution=solution,
        objective_value=None,
        source_solution=state.solution if state.source_solution is None else state.source_solution,
    )


def integrated_carbon_reconstruction_repair(state: Any, rng: np.random.Generator, **kwargs: Any) -> Any:
    """Repair customers, then rebuild EV stations and timing in common units."""

    del rng
    from setp_solver.algorithms.resetp_alns.kernel.alns_core import _finalize_candidate_state, _insert_removed

    repaired_state = _insert_removed(state, mode="regret2") if state.removed_customers else state
    if repaired_state.removed_customers:
        return _finalize_candidate_state(repaired_state)
    node_lookup = {node.node_id: node for node in repaired_state.context.instance.nodes}
    routes: list[Route] = []
    actions: list[Any] = []
    carbon_weight = float(kwargs.get("carbon_bias_weight", repaired_state.context.carbon_weight))
    try:
        for route in repaired_state.solution.routes:
            clean = replace(
                route,
                node_sequence=[
                    node_id
                    for node_id in route.node_sequence
                    if node_lookup.get(node_id) is None or node_lookup[node_id].node_type.lower() != "f"
                ],
            )
            if clean.vehicle_type.lower() != "ev":
                routes.append(clean)
                continue
            rebuilt, route_actions = repair_route_charging(
                clean,
                repaired_state.context.instance,
                repaired_state.context.carbon_profile,
                repaired_state.context.prices,
                strategy="integrated",
                carbon_weight=carbon_weight,
            )
            routes.append(rebuilt)
            actions.extend(route_actions)
        candidate = replace(repaired_state.solution, routes=routes, charging_actions=actions)
        if check_solution(candidate, repaired_state.context.instance, repaired_state.context.prices):
            raise ValueError("refined carbon reconstruction produced a hard violation")
        return _finalize_candidate_state(
            replace(
                repaired_state,
                solution=candidate,
                objective_value=None,
                removed_customers=(),
                source_solution=None,
            )
        )
    except (TypeError, ValueError):
        fallback = state.source_solution or state.solution
        return _finalize_candidate_state(
            replace(
                state,
                solution=fallback,
                objective_value=None,
                removed_customers=(),
                source_solution=None,
                allow_new_route_repair=True,
            )
        )


def _route_carbon_kg(route: Route, solution: Solution, context: Any) -> float:
    actions = [action for action in solution.charging_actions if action.vehicle_id == route.vehicle_id]
    try:
        return float(
            evaluate(
                Solution(routes=[route], charging_actions=actions),
                context.instance,
                context.carbon_profile,
                context.prices,
                carbon_quota_kg=0.0,
            )["E_total"]
        )
    except Exception:
        return 0.0


def _solution_carbon_kg(solution: Solution, context: Any) -> float:
    try:
        return float(
            evaluate(
                solution,
                context.instance,
                context.carbon_profile,
                context.prices,
                carbon_quota_kg=context.carbon_quota_kg,
            )["E_total"]
        )
    except Exception:
        return BIG_M


def _action_carbon_kg(action: Any, context: Any) -> float:
    try:
        return integrated_charge_carbon_kg(
            float(action.charge_start_second),
            float(action.occupancy_minutes) * 60.0,
            float(action.energy_kwh),
            context.instance,
            context.carbon_profile,
        )
    except Exception:
        return 0.0


def _gamma(row: dict[str, Any]) -> float:
    return float(row.get("actual_gco2_per_kwh", row.get("forecast_gco2_per_kwh", 0.0)))


def _slot_gamma(carbon_profile: list[dict[str, Any]], slot_index: int) -> float:
    if all("horizon_second_start" in row for row in carbon_profile):
        return _gamma(carbon_profile_row_for_slot(carbon_profile, slot_index))
    idx = max(0, min(len(carbon_profile) - 1, int(slot_index)))
    return _gamma(carbon_profile[idx])
