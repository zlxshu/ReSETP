"""Small, result-blind contracts shared by the China E3--E7 experiments."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any, Iterable

from setp_solver.china81 import CHINA81_HORIZON_START_SECOND
from setp_solver.instance_loader import Instance
from setp_solver.search.dynamic import (
    DynamicEvent,
    RollingParameters,
    generate_dynamic_events,
)


CANDIDATE_CASE_PLAN = {
    "E3": (
        "cn-prd-50c-01-V2-LOCATIONS",
        "cn-prd-100c-02-V2-LOCATIONS",
    ),
    "E5": (
        "cn-prd-50c-01-V2-LOCATIONS",
        "cn-prd-100c-02-V2-LOCATIONS",
    ),
    "E6": ("cn-prd-150c-01-V2-LOCATIONS",),
    "E7": (
        "cn-prd-50c-01-V2-LOCATIONS",
        "cn-prd-100c-02-V2-LOCATIONS",
        "cn-prd-150c-01-V2-LOCATIONS",
    ),
}

TERMINAL_CLOSURE_SOURCES = (
    "route_pool_candidate_or_parent",
    "final_independent_certificate",
)


def search_convergence(trace: list[dict[str, Any]]) -> dict[str, Any]:
    """Implement candidate E5 option B without activating it.

    The final route-pool comparison and independent certificate still count as
    complete evaluations, but they are terminal closure, not opportunities for
    the stochastic search to continue after an improvement.  Calling this
    function does not approve option B as the experiment's starvation rule.
    """

    if len(trace) < len(TERMINAL_CLOSURE_SOURCES) + 1:
        raise ValueError("complete-candidate trace is too short")
    closure = trace[-len(TERMINAL_CLOSURE_SOURCES) :]
    observed = tuple(str(row.get("source")) for row in closure)
    if observed != TERMINAL_CLOSURE_SOURCES:
        raise ValueError(f"unexpected terminal closure: {observed}")
    incumbent = float("inf")
    flags: list[int] = []
    for row in trace:
        value = row.get("complete_objective")
        improved = value is not None and float(value) < incumbent - 1.0e-9
        flags.append(int(improved))
        if improved:
            incumbent = float(value)
    return blind_search_convergence(flags)


def blind_search_convergence(flags: list[int]) -> dict[str, Any]:
    """Apply candidate option B to an objective-blind improvement trace."""

    if len(flags) < len(TERMINAL_CLOSURE_SOURCES) + 1:
        raise ValueError("complete-candidate trace is too short")
    search_flags = [int(bool(value)) for value in flags[: -len(TERMINAL_CLOSURE_SOURCES)]]
    last = max((index for index, value in enumerate(search_flags, start=1) if value), default=0)
    if last == 0:
        raise ValueError("search trace contains no feasible incumbent")
    attempts = len(search_flags)
    return {
        "search_candidate_evaluations_S": attempts,
        "last_search_improvement_evaluation_L": last,
        "last_search_improvement_fraction_L_over_S": last / attempts,
        "search_starved_L_over_S_gt_0_5": last / attempts > 0.5,
        "search_strict_improvement_flags_without_objectives": search_flags,
        "terminal_closure_evaluations": len(TERMINAL_CLOSURE_SOURCES),
        "total_complete_candidate_evaluations": len(flags),
    }


def select_result_blind_budget(
    rows: Iterable[dict[str, Any]],
    *,
    expected_units_by_arm: dict[str, int],
    maximum_starved_share: float = 0.20,
) -> dict[str, Any]:
    """Select the smallest non-starved tested budget for every arm."""

    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["arm"]), int(row["budget"])), []).append(row)
    minima: dict[str, int] = {}
    audit: list[dict[str, Any]] = []
    for arm, expected in sorted(expected_units_by_arm.items()):
        budgets = sorted(budget for candidate_arm, budget in grouped if candidate_arm == arm)
        for budget in budgets:
            units = grouped[(arm, budget)]
            if len(units) != expected:
                raise ValueError(f"incomplete blind pilot: {arm}/{budget}: {len(units)}/{expected}")
            starved = sum(bool(row["search_starved_L_over_S_gt_0_5"]) for row in units)
            share = starved / expected
            passed = share <= maximum_starved_share
            audit.append(
                {
                    "arm": arm,
                    "budget": budget,
                    "unit_count": expected,
                    "starved_unit_count": starved,
                    "starved_unit_share": share,
                    "passed": passed,
                }
            )
            if passed:
                minima[arm] = budget
                break
    return {
        "status": "PASS" if len(minima) == len(expected_units_by_arm) else "NEEDS_HIGHER_BUDGET",
        "arm_minimum_passing_budget": minima,
        "selected_common_budget": max(minima.values()) if len(minima) == len(expected_units_by_arm) else None,
        "audit": audit,
    }


def select_participation_safe_candidate(
    candidates: Iterable[dict[str, Any]],
    *,
    independent_profit: dict[str, float],
    tolerance: float = 1.0e-6,
) -> dict[str, Any]:
    """Choose the cheapest checked candidate that weakly benefits every depot."""

    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = str(candidate["solution_sha256"])
        unique.setdefault(key, candidate)
    feasible: list[dict[str, Any]] = []
    for candidate in unique.values():
        if abs(float(candidate["accounting_residual"])) > tolerance:
            raise ValueError("depot profit ledger does not close")
        profits = candidate["profit_values"]
        if set(profits) != set(independent_profit):
            raise ValueError("depot profit ledger has the wrong members")
        if all(float(profits[depot]) >= baseline - tolerance for depot, baseline in independent_profit.items()):
            feasible.append(candidate)
    if not feasible:
        raise ValueError("no participation-safe candidate; independent fallback is missing")
    return min(feasible, key=lambda row: (float(row["objective"]), str(row["solution_sha256"])))


def china81_dynamic_events(
    instance: Instance,
    *,
    seed: int,
    params: RollingParameters | None = None,
) -> list[DynamicEvent]:
    """Generate deterministic China81 events on the absolute operating clock."""

    settings = params or RollingParameters()
    offset = float(CHINA81_HORIZON_START_SECOND)
    relative_nodes = [
        replace(
            node,
            ready_time=max(0.0, float(node.ready_time) - offset),
            due_time=max(0.0, float(node.due_time) - offset),
        )
        for node in instance.nodes
    ]
    relative = Instance(
        nodes=relative_nodes,
        distance_matrix=[list(row) for row in instance.distance_matrix],
        diesel_l_per_meter=instance.diesel_l_per_meter,
        ev_kwh_per_meter=instance.ev_kwh_per_meter,
        unit_distance_cost_per_meter=instance.unit_distance_cost_per_meter,
        num_cv=instance.num_cv,
        num_ev=instance.num_ev,
        road_profiles=instance.road_profiles,
        vehicle_parameters=instance.vehicle_parameters,
        demand_mass_per_unit_kg=instance.demand_mass_per_unit_kg,
    )
    donors = [node for node in relative.nodes if node.node_type.lower() == "c"]
    generated = generate_dynamic_events(relative, seed=seed, params=settings, add_donors=donors)
    return [
        replace(
            event,
            t_appear=float(event.t_appear) + offset,
            old_ready_time=float(event.old_ready_time) + offset,
            old_due_time=float(event.old_due_time) + offset,
            new_ready_time=float(event.new_ready_time) + offset,
            new_due_time=float(event.new_due_time) + offset,
        )
        for event in generated
    ]


def event_payload(events: list[DynamicEvent]) -> list[dict[str, Any]]:
    return [asdict(event) for event in events]
