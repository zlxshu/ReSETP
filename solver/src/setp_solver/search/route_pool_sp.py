"""Route-pool set-partitioning helpers for Pilot19.

This module is deliberately a post-processing layer. It does not change the
winner kernel, scoring, or checker semantics; every route cost and final
solution verdict still goes through ``cost.evaluate`` and ``check_solution``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
import math
import time
from typing import Any, Iterable

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix, csr_matrix, vstack

from ..check import check_solution
from ..cost import charging_slot_breakdown, evaluate
from ..instance_loader import Instance, Node
from ..prices import DEFAULT_PRICES, PriceParameters
from ..solution import ChargingAction, Route, Solution
from .charging import repair_route_charging
from .fleet import normalize_solution_vehicle_trips


RoutePoolKey = tuple[frozenset[str], str]


@dataclass(frozen=True)
class RoutePoolEntry:
    entry_id: str
    route: Route
    charging_actions: tuple[ChargingAction, ...]
    customer_ids: tuple[str, ...]
    vehicle_type: str
    cost: float
    source: str
    is_fallback: bool = False

    @property
    def key(self) -> RoutePoolKey:
        return (frozenset(self.customer_ids), self.vehicle_type)


@dataclass(frozen=True)
class RoutePoolBuildResult:
    entries: tuple[RoutePoolEntry, ...]
    alternates: dict[RoutePoolKey, tuple[RoutePoolEntry, ...]]
    raw_entry_count: int
    duplicate_signature_count: int
    skipped_empty_route_count: int
    fallback_added_count: int
    fallback_failed_customers: tuple[str, ...]


@dataclass(frozen=True)
class SpSolveResult:
    selected_indices: tuple[int, ...]
    objective: float
    status: int | str
    success: bool
    message: str
    mip_gap: float | None
    runtime_seconds: float
    cover_constraint_count: int
    station_capacity_constraint_count: int
    fallback_used: bool = False


@dataclass(frozen=True)
class RebuildResult:
    solution: Solution
    metrics: dict[str, float]
    violations: tuple[Any, ...]
    selected_entry_ids: tuple[str, ...]
    repaired_by_alternate: bool = False

    @property
    def feasible(self) -> bool:
        return len(self.violations) == 0


def build_route_pool(
    solutions: Iterable[tuple[Solution, str]],
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    include_fallback: bool = True,
) -> RoutePoolBuildResult:
    """Build a deduplicated route pool from complete feasible solutions."""

    raw_entries: list[RoutePoolEntry] = []
    skipped_empty = 0
    for solution, source in solutions:
        if getattr(solution, "cross_site_services", None):
            raise RuntimeError(f"HALT_CROSS_SITE_PRESENT: source={source}")
        for route_index, route in enumerate(solution.routes):
            customers = route_customer_ids(route, instance)
            if not customers:
                skipped_empty += 1
                continue
            actions = tuple(actions_for_route(solution, route.vehicle_id))
            raw_entries.append(
                make_pool_entry(
                    route,
                    actions,
                    instance,
                    carbon_profile,
                    prices,
                    source=f"{source}:route{route_index}",
                    is_fallback=False,
                )
            )

    fallback_failed: list[str] = []
    fallback_added = 0
    if include_fallback:
        for entry in fallback_entries(instance, carbon_profile, prices):
            raw_entries.append(entry)
            fallback_added += 1
        expected_customers = set(customer_node_ids(instance))
        fallback_customers = {
            entry.customer_ids[0]
            for entry in raw_entries
            if entry.is_fallback and len(entry.customer_ids) == 1
        }
        fallback_failed = sorted(expected_customers - fallback_customers)

    return dedupe_route_pool(
        raw_entries,
        raw_entry_count=len(raw_entries),
        skipped_empty_route_count=skipped_empty,
        fallback_added_count=fallback_added,
        fallback_failed_customers=tuple(fallback_failed),
    )


def make_pool_entry(
    route: Route,
    charging_actions: Iterable[ChargingAction],
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
    *,
    source: str,
    is_fallback: bool = False,
) -> RoutePoolEntry:
    actions = tuple(charging_actions)
    customers = route_customer_ids(route, instance)
    cost = single_route_cost(route, actions, instance, carbon_profile, prices)
    return RoutePoolEntry(
        entry_id=route_entry_id(route, actions, source=source),
        route=route,
        charging_actions=actions,
        customer_ids=customers,
        vehicle_type=route.vehicle_type.lower(),
        cost=float(cost),
        source=source,
        is_fallback=bool(is_fallback),
    )


def dedupe_route_pool(
    raw_entries: Iterable[RoutePoolEntry],
    *,
    raw_entry_count: int | None = None,
    skipped_empty_route_count: int = 0,
    fallback_added_count: int = 0,
    fallback_failed_customers: tuple[str, ...] = (),
) -> RoutePoolBuildResult:
    """Keep the cheapest route per ``(customer set, vehicle type)`` key."""

    unique_by_signature: dict[tuple[Any, ...], RoutePoolEntry] = {}
    duplicate_signatures = 0
    for entry in raw_entries:
        signature = route_signature(entry.route, entry.charging_actions)
        previous = unique_by_signature.get(signature)
        if previous is None or entry.cost < previous.cost - 1e-9:
            unique_by_signature[signature] = entry
        else:
            duplicate_signatures += 1

    grouped: dict[RoutePoolKey, list[RoutePoolEntry]] = defaultdict(list)
    for entry in unique_by_signature.values():
        grouped[entry.key].append(entry)

    best_entries: list[RoutePoolEntry] = []
    alternates: dict[RoutePoolKey, tuple[RoutePoolEntry, ...]] = {}
    for key, entries in grouped.items():
        ordered = tuple(sorted(entries, key=lambda item: (item.cost, item.entry_id)))
        best_entries.append(ordered[0])
        alternates[key] = ordered[1:]

    return RoutePoolBuildResult(
        entries=tuple(sorted(best_entries, key=lambda item: item.entry_id)),
        alternates=alternates,
        raw_entry_count=len(unique_by_signature) if raw_entry_count is None else int(raw_entry_count),
        duplicate_signature_count=duplicate_signatures,
        skipped_empty_route_count=int(skipped_empty_route_count),
        fallback_added_count=int(fallback_added_count),
        fallback_failed_customers=tuple(fallback_failed_customers),
    )


def single_route_cost(
    route: Route,
    charging_actions: Iterable[ChargingAction],
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> float:
    """Evaluate one route under quota-neutral carbon semantics."""

    result = evaluate(
        Solution(routes=[route], charging_actions=list(charging_actions)),
        instance,
        carbon_profile,
        prices,
        carbon_quota_kg=0.0,
    )
    return float(result["total_cost"])


def solve_route_pool_sp(
    entries: tuple[RoutePoolEntry, ...] | list[RoutePoolEntry],
    instance: Instance,
    *,
    milp_time_limit_seconds: float = 180.0,
    allow_covering_fallback: bool = True,
) -> SpSolveResult:
    """Solve the set-partitioning route recombination MILP."""

    entries = tuple(entries)
    if not entries:
        raise ValueError("route pool is empty")
    customers = customer_node_ids(instance)
    cover_matrix = coverage_matrix(entries, customers)
    cap_matrix, cap_bounds = station_capacity_matrix(entries, instance)
    matrices = [cover_matrix]
    lower = [1.0] * cover_matrix.shape[0]
    upper = [1.0] * cover_matrix.shape[0]
    if cap_matrix.shape[0] > 0:
        matrices.append(cap_matrix)
        lower.extend([-math.inf] * cap_matrix.shape[0])
        upper.extend(cap_bounds)
    constraints = LinearConstraint(vstack(matrices, format="csr"), np.array(lower), np.array(upper))
    started = time.perf_counter()
    result = milp(
        c=np.array([entry.cost for entry in entries], dtype=float),
        integrality=np.ones(len(entries), dtype=int),
        bounds=Bounds(np.zeros(len(entries)), np.ones(len(entries))),
        constraints=constraints,
        options={"time_limit": float(milp_time_limit_seconds), "mip_rel_gap": 0.0},
    )
    runtime = time.perf_counter() - started
    selected = tuple(idx for idx, value in enumerate(np.asarray(result.x if result.x is not None else [])) if value >= 0.5)
    if selected and _selected_exactly_covers(entries, selected, customers):
        return SpSolveResult(
            selected_indices=selected,
            objective=float(sum(entries[idx].cost for idx in selected)),
            status=int(result.status),
            success=bool(result.success),
            message=str(result.message),
            mip_gap=_maybe_float(getattr(result, "mip_gap", None)),
            runtime_seconds=runtime,
            cover_constraint_count=cover_matrix.shape[0],
            station_capacity_constraint_count=cap_matrix.shape[0],
            fallback_used=False,
        )

    if allow_covering_fallback:
        selected = greedy_singleton_cover(entries, customers)
        if selected:
            return SpSolveResult(
                selected_indices=selected,
                objective=float(sum(entries[idx].cost for idx in selected)),
                status="GREEDY_COVER_FALLBACK",
                success=False,
                message=f"MILP failed exact-cover selection: {result.message}",
                mip_gap=_maybe_float(getattr(result, "mip_gap", None)),
                runtime_seconds=runtime,
                cover_constraint_count=cover_matrix.shape[0],
                station_capacity_constraint_count=cap_matrix.shape[0],
                fallback_used=True,
            )

    return SpSolveResult(
        selected_indices=(),
        objective=math.inf,
        status=int(result.status),
        success=False,
        message=str(result.message),
        mip_gap=_maybe_float(getattr(result, "mip_gap", None)),
        runtime_seconds=runtime,
        cover_constraint_count=cover_matrix.shape[0],
        station_capacity_constraint_count=cap_matrix.shape[0],
        fallback_used=False,
    )


def rebuild_solution_from_entries(
    entries: tuple[RoutePoolEntry, ...] | list[RoutePoolEntry],
    selected_indices: Iterable[int],
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> RebuildResult:
    """Build and check a complete solution from selected route-pool entries."""

    selected_entries = [entries[idx] for idx in selected_indices]
    solution = _retag_selected_entries(selected_entries, instance)
    violations = tuple(check_solution(solution, instance, prices))
    metrics = evaluate(solution, instance, carbon_profile, prices, carbon_quota_kg=0.0)
    return RebuildResult(
        solution=solution,
        metrics={key: float(value) for key, value in metrics.items()},
        violations=violations,
        selected_entry_ids=tuple(entry.entry_id for entry in selected_entries),
        repaired_by_alternate=False,
    )


def _retag_selected_entries(entries: list[RoutePoolEntry], instance: Instance) -> Solution:
    routes: list[Route] = []
    actions: list[ChargingAction] = []
    counters: dict[str, int] = {"cv": 0, "ev": 0}
    for entry in entries:
        vehicle_type = entry.vehicle_type.lower()
        counters[vehicle_type] = int(counters.get(vehicle_type, 0)) + 1
        temp_id = f"TMP_{vehicle_type.upper()}{counters[vehicle_type]}"
        home_depot = entry.route.node_sequence[0] if entry.route.node_sequence else entry.route.home_depot_id
        routes.append(replace(entry.route, vehicle_id=temp_id, home_depot_id=home_depot))
        actions.extend(replace(action, vehicle_id=temp_id) for action in entry.charging_actions)
    return normalize_solution_vehicle_trips(Solution(routes=routes, charging_actions=actions, cross_site_services=[]), instance)


def coverage_matrix(entries: tuple[RoutePoolEntry, ...] | list[RoutePoolEntry], customers: tuple[str, ...]) -> csr_matrix:
    customer_index = {customer_id: row for row, customer_id in enumerate(customers)}
    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    for col, entry in enumerate(entries):
        for customer_id in entry.customer_ids:
            if customer_id in customer_index:
                rows.append(customer_index[customer_id])
                cols.append(col)
                data.append(1.0)
    return coo_matrix((data, (rows, cols)), shape=(len(customers), len(entries)), dtype=float).tocsr()


def station_capacity_matrix(
    entries: tuple[RoutePoolEntry, ...] | list[RoutePoolEntry],
    instance: Instance,
) -> tuple[csr_matrix, list[float]]:
    row_keys: dict[tuple[str, int], int] = {}
    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    bounds: list[float] = []
    node_lookup = {node.node_id: node for node in instance.nodes}
    for col, entry in enumerate(entries):
        for station_slot in public_station_slots(entry, node_lookup, instance):
            row = row_keys.get(station_slot)
            if row is None:
                row = len(row_keys)
                row_keys[station_slot] = row
                station = node_lookup[station_slot[0]]
                bounds.append(float(station_charger_count(station, instance)))
            rows.append(row)
            cols.append(col)
            data.append(1.0)
    return coo_matrix((data, (rows, cols)), shape=(len(row_keys), len(entries)), dtype=float).tocsr(), bounds


def public_station_slots(
    entry: RoutePoolEntry,
    node_lookup: dict[str, Node],
    instance: Instance,
) -> tuple[tuple[str, int], ...]:
    slots: set[tuple[str, int]] = set()
    for action in entry.charging_actions:
        node = node_lookup.get(action.station_id)
        if node is None or node.node_type.lower() != "f":
            continue
        for slot in charging_slot_breakdown(
            float(action.charge_start_second),
            float(action.occupancy_minutes) * 60.0,
            float(action.energy_kwh),
            instance,
            n_slots=48,
            cyclic=True,
        ):
            slots.add((action.station_id, int(slot.slot_index)))
    return tuple(sorted(slots))


def fallback_entries(
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any = DEFAULT_PRICES,
) -> tuple[RoutePoolEntry, ...]:
    entries: list[RoutePoolEntry] = []
    depots = [node for node in instance.nodes if node.node_type.lower() == "d"]
    if not depots:
        return ()
    for customer_id in customer_node_ids(instance):
        entry = _fallback_entry_for_customer(customer_id, depots, instance, carbon_profile, prices)
        if entry is not None:
            entries.append(entry)
    return tuple(entries)


def _fallback_entry_for_customer(
    customer_id: str,
    depots: list[Node],
    instance: Instance,
    carbon_profile: list[dict[str, Any]],
    prices: PriceParameters | dict[str, float] | Any,
) -> RoutePoolEntry | None:
    subinstance = subinstance_for_customers(instance, {customer_id})
    ordered_depots = sorted(
        depots,
        key=lambda depot: (
            instance.distance(depot.node_id, customer_id) + instance.distance(customer_id, depot.node_id),
            depot.node_id,
        ),
    )
    if getattr(instance, "num_cv", None) != 0:
        for depot in ordered_depots:
            route = Route(f"FB_CV_{customer_id}", "cv", depot.node_id, [depot.node_id, customer_id, depot.node_id])
            if not check_solution(Solution(routes=[route]), subinstance, prices):
                return make_pool_entry(
                    route,
                    (),
                    instance,
                    carbon_profile,
                    prices,
                    source=f"fallback:{customer_id}:cv",
                    is_fallback=True,
                )
    if getattr(instance, "num_ev", None) != 0:
        for depot in ordered_depots:
            base = Route(f"FB_EV_{customer_id}", "ev", depot.node_id, [depot.node_id, customer_id, depot.node_id])
            try:
                route, actions = repair_route_charging(base, instance, carbon_profile, prices)
            except Exception:
                continue
            if not check_solution(Solution(routes=[route], charging_actions=actions), subinstance, prices):
                return make_pool_entry(
                    route,
                    tuple(actions),
                    instance,
                    carbon_profile,
                    prices,
                    source=f"fallback:{customer_id}:ev",
                    is_fallback=True,
                )
    return None


def subinstance_for_customers(instance: Instance, customer_ids: set[str]) -> Instance:
    keep = {
        node.node_id
        for node in instance.nodes
        if node.node_type.lower() in {"d", "f"} or node.node_id in customer_ids
    }
    nodes = [node for node in instance.nodes if node.node_id in keep]
    original = instance.node_index
    matrix = [
        [float(instance.distance_matrix[original[left.node_id]][original[right.node_id]]) for right in nodes]
        for left in nodes
    ]
    return Instance(
        nodes=nodes,
        distance_matrix=matrix,
        diesel_l_per_meter=instance.diesel_l_per_meter,
        ev_kwh_per_meter=instance.ev_kwh_per_meter,
        unit_distance_cost_per_meter=instance.unit_distance_cost_per_meter,
        num_cv=instance.num_cv,
        num_ev=instance.num_ev,
    )


def greedy_singleton_cover(entries: tuple[RoutePoolEntry, ...], customers: tuple[str, ...]) -> tuple[int, ...]:
    selected: list[int] = []
    used_customers: set[str] = set()
    for customer_id in customers:
        candidates = [
            (idx, entry)
            for idx, entry in enumerate(entries)
            if set(entry.customer_ids) == {customer_id} and customer_id not in used_customers
        ]
        if not candidates:
            return ()
        idx, entry = min(candidates, key=lambda item: (item[1].cost, item[1].entry_id))
        selected.append(idx)
        used_customers.update(entry.customer_ids)
    return tuple(selected)


def _selected_exactly_covers(entries: tuple[RoutePoolEntry, ...], selected: tuple[int, ...], customers: tuple[str, ...]) -> bool:
    counts = {customer_id: 0 for customer_id in customers}
    for idx in selected:
        for customer_id in entries[idx].customer_ids:
            if customer_id in counts:
                counts[customer_id] += 1
    return all(value == 1 for value in counts.values())


def route_customer_ids(route: Route, instance: Instance) -> tuple[str, ...]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    return tuple(
        node_id
        for node_id in route.node_sequence
        if node_lookup.get(node_id) is not None and node_lookup[node_id].node_type.lower() == "c"
    )


def customer_node_ids(instance: Instance) -> tuple[str, ...]:
    return tuple(sorted(node.node_id for node in instance.nodes if node.node_type.lower() == "c"))


def actions_for_route(solution: Solution, vehicle_id: str) -> tuple[ChargingAction, ...]:
    return tuple(action for action in solution.charging_actions if action.vehicle_id == vehicle_id)


def station_charger_count(station: Node, instance: Instance) -> int:
    if station.station_chargers is not None:
        return int(station.station_chargers)
    if station.node_type.lower() == "d":
        return max(1, len(customer_node_ids(instance)))
    if station.node_type.lower() == "f":
        return 1
    return 0


def route_entry_id(route: Route, actions: tuple[ChargingAction, ...], *, source: str) -> str:
    return f"{source}|{route.vehicle_type.lower()}|{'/'.join(route.node_sequence)}|{len(actions)}"


def route_signature(route: Route, actions: tuple[ChargingAction, ...]) -> tuple[Any, ...]:
    return (
        route.vehicle_type.lower(),
        route.home_depot_id,
        tuple(route.node_sequence),
        tuple(
            sorted(
                (
                    action.station_id,
                    round(float(action.energy_kwh), 9),
                    round(float(action.occupancy_minutes), 9),
                    round(float(action.charge_start_second), 9),
                )
                for action in actions
            )
        ),
    )


def _maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None
