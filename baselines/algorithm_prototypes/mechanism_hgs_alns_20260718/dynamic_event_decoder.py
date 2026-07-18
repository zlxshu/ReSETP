"""Dynamic event insertion decoder with frozen-history protection.

This component is born from the rolling-event mechanism, not from a wish to
add another generic neighbourhood.  When a new order appears it keeps the
completed and in-progress work sealed, removes the expensive singleton
fallback for that order, and checks every insertion into the still-editable
future routes against the inherited vehicle/clock/battery ledger.

The current gate deliberately uses one frozen real E7 event.  Depth-two
regret/ejection remains a fallback for cases without a feasible direct
insertion; its separate 0/1/2/5 functional evidence is verified by the gate.
No formal E7 record is changed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from baselines.e7_dynamic import e7_p2_single_event_probe_20260714 as p2
from setp_solver.solution import Solution


TOL = 1.0e-9


@dataclass(frozen=True)
class DynamicEventDecodeResult:
    """Auditable outcome of one exact event-insertion pass."""

    baseline_solution: Solution
    selected_search_solution: Solution
    selected_prepared_solution: Solution
    selected_certificate: Any
    baseline_cost: float
    selected_cost: float
    event_customer_id: str
    trigger_second: float
    activity: dict[str, Any]


def _customer_coverage(solution: Solution, instance: Any) -> list[str]:
    return sorted(
        customer_id
        for route in solution.routes
        for customer_id in p2.route_customers(route, instance)
    )


def run_real_single_event_insertion_decoder() -> DynamicEventDecodeResult:
    """Run the cheapest real-ledger dynamic mechanism passport."""

    sources = p2.load_formal_sources()
    selected = p2.select_probe_event(sources)
    owners = p2.load_owners()
    start = p2.build_probe_start(sources, selected, owners)
    instance = start["effective_instance"]
    event_customer_id = selected["event"].customer_id
    baseline_solution = start["search_solution"]
    baseline_prepared, _, baseline_cost = p2.exact_future_cost(
        baseline_solution,
        instance=instance,
        sources=sources,
        selected=selected,
    )
    event_route_indexes = [
        index
        for index, route in enumerate(baseline_solution.routes)
        if event_customer_id in p2.route_customers(route, instance)
    ]
    if len(event_route_indexes) != 1:
        raise RuntimeError(
            "real single-event start must contain one event route"
        )
    event_route_index = event_route_indexes[0]
    event_route = baseline_solution.routes[event_route_index]
    event_customers = p2.route_customers(event_route, instance)
    if event_customers != [event_customer_id]:
        raise RuntimeError("event route is not the frozen singleton fallback")
    remaining_routes = [
        route
        for index, route in enumerate(baseline_solution.routes)
        if index != event_route_index
    ]
    expected_coverage = _customer_coverage(baseline_solution, instance)

    selected_search = baseline_solution
    selected_prepared = baseline_prepared
    selected_certificate = start["certificate"]
    selected_cost = float(baseline_cost)
    attempts = feasible = 0
    candidate_rows: list[dict[str, Any]] = []
    for route_index, route in enumerate(remaining_routes):
        for insert_at in range(1, len(route.node_sequence)):
            attempts += 1
            changed_sequence = list(route.node_sequence)
            changed_sequence.insert(insert_at, event_customer_id)
            changed_routes = list(remaining_routes)
            changed_routes[route_index] = replace(
                route,
                node_sequence=changed_sequence,
            )
            candidate = Solution(
                routes=changed_routes,
                charging_actions=[],
                cross_site_services=p2.annotate_cross_site(
                    changed_routes,
                    instance,
                    owners,
                ),
            )
            if _customer_coverage(candidate, instance) != expected_coverage:
                raise RuntimeError(
                    "event insertion changed future-customer coverage"
                )
            try:
                prepared, certificate, cost = p2.exact_future_cost(
                    candidate,
                    instance=instance,
                    sources=sources,
                    selected=selected,
                )
            except ValueError:
                continue
            feasible += 1
            row = {
                "route_index": route_index,
                "insert_at": insert_at,
                "target_home_depot_id": route.home_depot_id,
                "target_vehicle_type": route.vehicle_type,
                "cost": float(cost),
                "cost_delta": float(cost - baseline_cost),
            }
            candidate_rows.append(row)
            if cost < selected_cost - TOL:
                selected_search = candidate
                selected_prepared = prepared
                selected_certificate = certificate
                selected_cost = float(cost)

    selected_coverage = _customer_coverage(selected_search, instance)
    if selected_coverage != expected_coverage:
        raise RuntimeError("selected dynamic candidate lost customer coverage")
    cut = selected["cut"]
    certificate_assets = {
        trip.physical_vehicle_id for trip in selected_certificate.trips
    }
    inherited_assets = set(cut.asset_states)
    if not certificate_assets.issubset(inherited_assets):
        raise RuntimeError(
            "dynamic decoder invented a physical vehicle outside the cut"
        )
    selected_event_routes = [
        route
        for route in selected_search.routes
        if event_customer_id in p2.route_customers(route, instance)
    ]
    if len(selected_event_routes) != 1:
        raise RuntimeError("selected solution does not serve the event once")
    activity = {
        "complete_route_search_evaluations": 0,
        "dynamic_insertion_attempts": attempts,
        "complete_dynamic_candidate_evaluations": attempts,
        "dynamically_feasible_candidates": feasible,
        "improvements": int(selected_cost < baseline_cost - TOL),
        "exact_decoder_updates": int(
            selected_cost < baseline_cost - TOL
        ),
        "baseline_route_count": len(baseline_solution.routes),
        "selected_route_count": len(selected_search.routes),
        "route_count_delta": (
            len(selected_search.routes) - len(baseline_solution.routes)
        ),
        "baseline_cost": float(baseline_cost),
        "selected_cost": float(selected_cost),
        "objective_delta": float(selected_cost - baseline_cost),
        "event_customer_id": event_customer_id,
        "event_owner_depot_id": owners[event_customer_id],
        "selected_service_depot_id": selected_event_routes[0].home_depot_id,
        "cross_depot_event_service": (
            selected_event_routes[0].home_depot_id
            != owners[event_customer_id]
        ),
        "completed_routes_frozen": len(cut.completed_route_ids),
        "in_progress_routes_frozen": len(cut.in_progress_route_ids),
        "editable_routes": len(cut.editable_route_ids),
        "locked_charging_actions": len(cut.locked_charging_actions),
        "inherited_physical_assets": len(inherited_assets),
        "selected_physical_assets": len(certificate_assets),
        "future_customer_coverage_preserved": True,
        "event_served_exactly_once": True,
        "candidate_rows": sorted(
            candidate_rows,
            key=lambda row: (
                row["cost"],
                row["route_index"],
                row["insert_at"],
            ),
        ),
    }
    return DynamicEventDecodeResult(
        baseline_solution=baseline_solution,
        selected_search_solution=selected_search,
        selected_prepared_solution=selected_prepared,
        selected_certificate=selected_certificate,
        baseline_cost=float(baseline_cost),
        selected_cost=float(selected_cost),
        event_customer_id=event_customer_id,
        trigger_second=float(selected["trigger_second"]),
        activity=activity,
    )
