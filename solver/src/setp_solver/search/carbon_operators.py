"""Carbon-aware ALNS operators for the 09x probe variant."""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Any

import numpy as np

from ..check import check_solution
from ..cost import carbon_profile_row_for_slot, charging_slot_breakdown, evaluate
from ..solution import Route, Solution
from .evaluation import BIG_M
from .feasible_repair import enumerate_feasible_insertions


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
        from .alns_wouda import worst_customer_removal

        return worst_customer_removal(state, rng, **kwargs)
    from .alns_wouda import _adaptive_remove_count, _remove_customers, _route_customer_ids

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
        from .alns_wouda import shaw_related_removal

        return shaw_related_removal(state, rng, **kwargs)
    from .alns_wouda import _adaptive_remove_count, _remove_customers, _route_customer_ids

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
        from .alns_wouda import regret2_insert_repair

        return regret2_insert_repair(state, rng, **kwargs)
    from .alns_wouda import _finalize_candidate_state, regret2_insert_repair

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


def _gamma(row: dict[str, Any]) -> float:
    return float(row.get("actual_gco2_per_kwh", row.get("forecast_gco2_per_kwh", 0.0)))


def _slot_gamma(carbon_profile: list[dict[str, Any]], slot_index: int) -> float:
    if all("horizon_second_start" in row for row in carbon_profile):
        return _gamma(carbon_profile_row_for_slot(carbon_profile, slot_index))
    idx = max(0, min(len(carbon_profile) - 1, int(slot_index)))
    return _gamma(carbon_profile[idx])
