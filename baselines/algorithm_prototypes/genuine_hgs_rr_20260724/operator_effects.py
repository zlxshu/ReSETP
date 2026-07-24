"""Semantic effect checks for the problem-specific RR operators.

Changing a solution hash is not sufficient evidence that an operator did
what its name claims.  These checks ignore vehicle identifiers and verify the
corresponding depot, vehicle, charging, order, or dynamic-tail decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from setp_solver.solution import Route, Solution

from operator_plans import DestroyPlan, OperatorKind


@dataclass(frozen=True)
class OperatorEffect:
    passed: bool
    changed_decisions: tuple[str, ...]
    detail: str


def verify_operator_effect(
    before: Solution,
    after: Solution,
    plan: DestroyPlan,
    *,
    customer_ids: frozenset[str],
) -> OperatorEffect:
    """Verify that ``after`` changed the decision targeted by ``plan``."""

    if plan.kind == OperatorKind.CROSS_DEPOT_ROUTE_REASSIGNMENT:
        return _verify_whole_route_reassignment(
            before,
            after,
            plan,
            customer_ids=customer_ids,
        )
    if plan.kind == OperatorKind.BIDIRECTIONAL_CROSS_DEPOT_SEGMENT:
        return _verify_bidirectional_exchange(
            before,
            after,
            plan,
            customer_ids=customer_ids,
        )
    if plan.kind == OperatorKind.VEHICLE_TYPE_FLIP:
        return _verify_type_flip(
            after,
            plan,
            customer_ids=customer_ids,
        )
    if plan.kind == OperatorKind.CHARGE_DEPARTURE_RETIMING:
        return _verify_charge_retiming(
            before,
            after,
            plan,
            customer_ids=customer_ids,
        )
    if plan.kind == OperatorKind.TIME_WINDOW_PRESSURE_STRING:
        return _verify_customer_structure_change(
            before,
            after,
            plan.removed_customer_ids,
            customer_ids=customer_ids,
            label="time_window_structure",
        )
    if plan.kind == OperatorKind.DYNAMIC_UNEXECUTED_TAIL:
        return _verify_dynamic_tail(
            before,
            after,
            plan,
            customer_ids=customer_ids,
        )
    raise ValueError(f"unsupported operator effect {plan.kind.value}")


def _verify_whole_route_reassignment(
    before: Solution,
    after: Solution,
    plan: DestroyPlan,
    *,
    customer_ids: frozenset[str],
) -> OperatorEffect:
    group = frozenset(plan.source_customer_groups[0])
    matching = [
        route
        for route in after.routes
        if frozenset(_customers(route, customer_ids)) == group
    ]
    passed = len(matching) == 1 and (matching[0].home_depot_id in plan.target_depot_ids)
    return OperatorEffect(
        passed=passed,
        changed_decisions=(("route_home_depot",) if passed else ()),
        detail=(
            "whole customer set moved together to the registered other depot"
            if passed
            else "the selected route was not wholly reassigned"
        ),
    )


def _verify_bidirectional_exchange(
    before: Solution,
    after: Solution,
    plan: DestroyPlan,
    *,
    customer_ids: frozenset[str],
) -> OperatorEffect:
    if len(plan.source_customer_groups) != 2:
        return OperatorEffect(
            False,
            (),
            "bidirectional plan lacks two source customer groups",
        )
    first_depot = before.routes[plan.route_indices[0]].home_depot_id
    second_depot = before.routes[plan.route_indices[1]].home_depot_id
    first_group, second_group = (
        frozenset(group) for group in plan.source_customer_groups
    )
    served = _served_depot_by_customer(after, customer_ids)
    first_crossed = all(
        served.get(customer_id) == second_depot for customer_id in first_group
    )
    second_crossed = all(
        served.get(customer_id) == first_depot for customer_id in second_group
    )
    passed = bool(first_group and second_group) and (first_crossed and second_crossed)
    return OperatorEffect(
        passed=passed,
        changed_decisions=(
            ("two_way_cross_depot_customer_exchange",) if passed else ()
        ),
        detail=(
            "both selected strings crossed to the opposite depot"
            if passed
            else "the candidate did not preserve a reciprocal depot exchange"
        ),
    )


def _verify_type_flip(
    after: Solution,
    plan: DestroyPlan,
    *,
    customer_ids: frozenset[str],
) -> OperatorEffect:
    group = frozenset(plan.source_customer_groups[0])
    matching = [
        route
        for route in after.routes
        if frozenset(_customers(route, customer_ids)) == group
    ]
    passed = (
        len(matching) == 1
        and matching[0].vehicle_type.strip().lower() in plan.target_vehicle_types
    )
    return OperatorEffect(
        passed=passed,
        changed_decisions=(("vehicle_type",) if passed else ()),
        detail=(
            "selected route uses the opposite registered vehicle type"
            if passed
            else "the selected customer set was not assigned to the opposite type"
        ),
    )


def _verify_charge_retiming(
    before: Solution,
    after: Solution,
    plan: DestroyPlan,
    *,
    customer_ids: frozenset[str],
) -> OperatorEffect:
    group = frozenset(plan.preserved_customer_ids)
    old_route = _unique_route_for_group(
        before,
        group,
        customer_ids=customer_ids,
    )
    new_route = _unique_route_for_group(
        after,
        group,
        customer_ids=customer_ids,
    )
    if old_route is None or new_route is None:
        return OperatorEffect(
            False,
            (),
            "charge retiming did not preserve the selected customer set",
        )
    old_actions = _route_charge_signature(before, old_route)
    new_actions = _route_charge_signature(after, new_route)
    passed = old_actions != new_actions
    return OperatorEffect(
        passed=passed,
        changed_decisions=(("charging_location_amount_or_time",) if passed else ()),
        detail=(
            "charging location, amount, or start time changed"
            if passed
            else "the rebuilt EV charge schedule is identical"
        ),
    )


def _verify_customer_structure_change(
    before: Solution,
    after: Solution,
    affected: Iterable[str],
    *,
    customer_ids: frozenset[str],
    label: str,
) -> OperatorEffect:
    before_context = _customer_context(before, customer_ids)
    after_context = _customer_context(after, customer_ids)
    changed = tuple(
        customer_id
        for customer_id in affected
        if before_context.get(customer_id) != after_context.get(customer_id)
    )
    passed = bool(changed)
    return OperatorEffect(
        passed=passed,
        changed_decisions=((label,) if passed else ()),
        detail=(
            f"{len(changed)} affected customer contexts changed"
            if passed
            else "removed customers returned to the same structural context"
        ),
    )


def _verify_dynamic_tail(
    before: Solution,
    after: Solution,
    plan: DestroyPlan,
    *,
    customer_ids: frozenset[str],
) -> OperatorEffect:
    route_before = before.routes[plan.route_indices[0]]
    before_customers = _customers(route_before, customer_ids)
    prefix = tuple(plan.preserved_customer_ids)
    prefix_preserved = any(
        route.vehicle_id == route_before.vehicle_id
        and route.home_depot_id == route_before.home_depot_id
        and route.vehicle_type.strip().lower()
        == route_before.vehicle_type.strip().lower()
        and _customers(route, customer_ids)[: len(prefix)] == prefix
        for route in after.routes
    )
    structure = _verify_customer_structure_change(
        before,
        after,
        plan.removed_customer_ids,
        customer_ids=customer_ids,
        label="unexecuted_tail_structure",
    )
    passed = (
        tuple(before_customers[: len(prefix)]) == prefix
        and prefix_preserved
        and structure.passed
    )
    return OperatorEffect(
        passed=passed,
        changed_decisions=(
            (
                "physical_vehicle_and_depot_preserved",
                "frozen_prefix_preserved",
                "unexecuted_tail_changed",
            )
            if passed
            else ()
        ),
        detail=(
            "physical vehicle/depot and executed prefix stayed fixed while "
            "the unexecuted tail changed"
            if passed
            else "dynamic prefix/tail semantics were not both satisfied"
        ),
    )


def _customers(
    route: Route,
    customer_ids: frozenset[str],
) -> tuple[str, ...]:
    return tuple(node_id for node_id in route.node_sequence if node_id in customer_ids)


def _served_depot_by_customer(
    solution: Solution,
    customer_ids: frozenset[str],
) -> dict[str, str]:
    return {
        customer_id: route.home_depot_id
        for route in solution.routes
        for customer_id in _customers(route, customer_ids)
    }


def _unique_route_for_group(
    solution: Solution,
    group: frozenset[str],
    *,
    customer_ids: frozenset[str],
) -> Route | None:
    matching = [
        route
        for route in solution.routes
        if frozenset(_customers(route, customer_ids)) == group
    ]
    return matching[0] if len(matching) == 1 else None


def _route_charge_signature(
    solution: Solution,
    route: Route,
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        sorted(
            (
                action.station_id,
                round(float(action.charge_start_second), 6),
                round(float(action.energy_kwh), 9),
                round(float(action.occupancy_minutes), 9),
                int(action.charge_day_offset),
            )
            for action in solution.charging_actions
            if action.vehicle_id == route.vehicle_id
        )
    )


def _customer_context(
    solution: Solution,
    customer_ids: frozenset[str],
) -> dict[str, tuple[object, ...]]:
    context: dict[str, tuple[object, ...]] = {}
    for route in solution.routes:
        customers = _customers(route, customer_ids)
        for index, customer_id in enumerate(customers):
            context[customer_id] = (
                route.home_depot_id,
                route.vehicle_type.strip().lower(),
                customers[index - 1] if index > 0 else None,
                (customers[index + 1] if index + 1 < len(customers) else None),
            )
    return context
