"""Exact set-partitioning recombination for routes produced by multiple solvers.

This is an isolated prototype. Route scores must be additive screening costs.
The assembled solution must still pass the full ReSETP evaluator; non-additive
carbon, fairness, and shared-charging terms are deliberately not hidden here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from setp_solver.solution import (
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
    route_trip_vehicle_id,
)


@dataclass(frozen=True)
class PoolRoute:
    route: Route
    customers: frozenset[str]
    additive_score: float
    actions: tuple[ChargingAction, ...] = ()
    services: tuple[CrossSiteService, ...] = ()
    source: str = ""


@dataclass(frozen=True)
class RecombinationResult:
    solution: Solution
    additive_score: float
    selected_sources: tuple[str, ...]
    candidate_route_count: int


def _route_key(record: PoolRoute) -> tuple[object, ...]:
    return (
        tuple(record.route.node_sequence),
        record.route.vehicle_type,
        record.route.home_depot_id,
        tuple(
            (
                action.station_id,
                action.energy_kwh,
                action.occupancy_minutes,
                action.charge_start_second,
                action.charge_day_offset,
            )
            for action in record.actions
        ),
    )


def deduplicate(records: Iterable[PoolRoute]) -> list[PoolRoute]:
    best: dict[tuple[object, ...], PoolRoute] = {}
    for record in records:
        if not record.customers:
            continue
        key = _route_key(record)
        previous = best.get(key)
        if previous is None or record.additive_score < previous.additive_score:
            best[key] = record
    return sorted(
        best.values(),
        key=lambda item: (item.additive_score, _route_key(item), item.source),
    )


def exact_recombine(
    records: Iterable[PoolRoute],
    required_customers: Iterable[str],
    *,
    max_routes: int | None = None,
    time_limit_seconds: float = 1.0,
) -> RecombinationResult | None:
    candidates = deduplicate(records)
    customers = sorted(set(required_customers))
    if not candidates or not customers:
        return None
    customer_index = {customer: index for index, customer in enumerate(customers)}
    incidence = np.zeros((len(customers), len(candidates)), dtype=float)
    for column, record in enumerate(candidates):
        if not record.customers <= set(customers):
            continue
        for customer in record.customers:
            incidence[customer_index[customer], column] = 1.0
    constraints: list[LinearConstraint] = [
        LinearConstraint(incidence, np.ones(len(customers)), np.ones(len(customers)))
    ]
    if max_routes is not None:
        constraints.append(
            LinearConstraint(
                np.ones((1, len(candidates))),
                np.asarray([-np.inf]),
                np.asarray([float(max_routes)]),
            )
        )
    result = milp(
        c=np.asarray([record.additive_score for record in candidates], dtype=float),
        integrality=np.ones(len(candidates), dtype=int),
        bounds=Bounds(np.zeros(len(candidates)), np.ones(len(candidates))),
        constraints=constraints,
        options={"time_limit": max(0.001, float(time_limit_seconds))},
    )
    if not result.success or result.x is None:
        return None
    selected = [
        record
        for record, value in zip(candidates, result.x, strict=True)
        if value >= 0.5
    ]
    routes: list[Route] = []
    actions: list[ChargingAction] = []
    services: list[CrossSiteService] = []
    type_counts: dict[str, int] = {}
    for record in selected:
        vehicle_type = str(record.route.vehicle_type).lower()
        type_counts[vehicle_type] = type_counts.get(vehicle_type, 0) + 1
        prefix = "EV" if vehicle_type == "ev" else "CV"
        vehicle_id = route_trip_vehicle_id(
            f"{prefix}{type_counts[vehicle_type]}",
            1,
        )
        routes.append(replace(record.route, vehicle_id=vehicle_id))
        actions.extend(
            replace(action, vehicle_id=vehicle_id)
            for action in record.actions
        )
        services.extend(record.services)
    return RecombinationResult(
        solution=Solution(
            routes=routes,
            charging_actions=actions,
            cross_site_services=services,
        ),
        additive_score=float(sum(record.additive_score for record in selected)),
        selected_sources=tuple(record.source for record in selected),
        candidate_route_count=len(candidates),
    )
