"""Fail-closed reference decoder for explicit depot and vehicle assignments.

This decoder prioritizes correctness and auditability.  The future fast
decoder must reproduce its feasible decisions and complete-model objective
before it can replace it inside search.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from setp_solver.algorithms.resetp_alns.support.charging import (
    repair_route_charging,
)
from setp_solver.china81 import China81Bundle
from setp_solver.china81_completion import (
    annotate_cross_site_services,
)
from setp_solver.solution import ChargingAction, Route, Solution

from contracts import CandidateSource
from evaluation import BudgetedCompleteEvaluator, ScoredCandidate


ChargeRepairFunction = Callable[..., tuple[Route, list[ChargingAction]]]


@dataclass(frozen=True)
class RouteAssignment:
    home_depot_id: str
    vehicle_type: str
    charge_strategy: str = "integrated"
    carbon_weight: float = 1.0

    def __post_init__(self) -> None:
        normalized = self.vehicle_type.strip().lower()
        if normalized not in {"cv", "ev"}:
            raise ValueError(f"unsupported route vehicle type {self.vehicle_type!r}")
        if self.charge_strategy not in {"integrated", "legacy"}:
            raise ValueError(f"unsupported charge strategy {self.charge_strategy!r}")


@dataclass(frozen=True)
class ExplicitDecodeResult:
    scored: ScoredCandidate
    assignments: tuple[RouteAssignment, ...]
    fleet_used: dict[str, dict[str, int]]
    charging_route_count: int


def decode_explicit_assignments(
    skeleton: Solution,
    bundle: China81Bundle,
    *,
    assignments: Mapping[int, RouteAssignment],
    evaluator: BudgetedCompleteEvaluator,
    source: CandidateSource,
    source_metadata: dict[str, Any] | None = None,
    charge_repair_function: ChargeRepairFunction = (repair_route_charging),
) -> ExplicitDecodeResult:
    """Build and score exactly one explicit depot/type assignment."""

    depots = {
        node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "d"
    }
    node_type = {node.node_id: node.node_type.lower() for node in bundle.instance.nodes}
    active: list[tuple[int, tuple[str, ...], RouteAssignment]] = []
    for route_index, route in enumerate(skeleton.routes):
        customers = tuple(
            node_id for node_id in route.node_sequence if node_type.get(node_id) == "c"
        )
        if not customers:
            continue
        try:
            assignment = assignments[route_index]
        except KeyError as exc:
            raise ValueError(
                f"missing explicit assignment for route {route_index}"
            ) from exc
        if assignment.home_depot_id not in depots:
            raise ValueError(
                f"explicit assignment uses unknown depot {assignment.home_depot_id!r}"
            )
        active.append((route_index, customers, assignment))
    unexpected = set(assignments) - {route_index for route_index, _, _ in active}
    if unexpected:
        raise ValueError(f"assignments reference empty or unknown routes: {unexpected}")

    use = Counter(
        (
            assignment.home_depot_id,
            assignment.vehicle_type.strip().lower(),
        )
        for _, _, assignment in active
    )
    for (depot_id, vehicle_type), count in use.items():
        try:
            cap = int(bundle.fleet_caps_by_depot[depot_id][f"num_{vehicle_type}"])
        except KeyError as exc:
            raise ValueError(
                "missing finite fleet cap for explicit assignment: "
                f"{depot_id}:{vehicle_type}"
            ) from exc
        if count > cap:
            raise ValueError(
                "explicit assignment exceeds finite fleet cap: "
                f"{depot_id}:{vehicle_type}:{count}>{cap}"
            )

    counters: Counter[tuple[str, str]] = Counter()
    routes: list[Route] = []
    charging_actions: list[ChargingAction] = []
    charging_route_count = 0
    normalized_assignments: list[RouteAssignment] = []
    for _, customers, assignment in active:
        depot_id = assignment.home_depot_id
        vehicle_type = assignment.vehicle_type.strip().lower()
        counters[(depot_id, vehicle_type)] += 1
        vehicle_id = (
            f"COOP-{depot_id}-{vehicle_type.upper()}-"
            f"{counters[(depot_id, vehicle_type)]:03d}"
        )
        route = Route(
            vehicle_id=vehicle_id,
            vehicle_type=vehicle_type,
            home_depot_id=depot_id,
            node_sequence=[depot_id, *customers, depot_id],
        )
        if vehicle_type == "ev":
            route, actions = charge_repair_function(
                route,
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
                strategy=assignment.charge_strategy,
                carbon_weight=float(assignment.carbon_weight),
                depot_charge_window_mode="same_day_predeparture",
            )
            charging_actions.extend(actions)
            charging_route_count += 1
        routes.append(route)
        normalized_assignments.append(
            RouteAssignment(
                home_depot_id=depot_id,
                vehicle_type=vehicle_type,
                charge_strategy=assignment.charge_strategy,
                carbon_weight=float(assignment.carbon_weight),
            )
        )

    candidate = annotate_cross_site_services(
        Solution(
            routes=routes,
            charging_actions=charging_actions,
        ),
        bundle.customer_home_depot,
    )
    scored = evaluator.score(
        candidate,
        source=source,
        metadata={
            **dict(source_metadata or {}),
            "decoder": "explicit_reference_v1",
            "assignment_count": len(normalized_assignments),
            "charging_route_count": charging_route_count,
        },
    )
    return ExplicitDecodeResult(
        scored=scored,
        assignments=tuple(normalized_assignments),
        fleet_used={
            depot_id: {
                "num_cv": use[(depot_id, "cv")],
                "num_ev": use[(depot_id, "ev")],
            }
            for depot_id in sorted({depot_id for depot_id, _ in use})
        },
        charging_route_count=charging_route_count,
    )
