"""Bounded reciprocal cross-depot segment refinement for China81."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

from setp_solver.china81 import China81Bundle
from setp_solver.china81_completion import (
    China81CompletionResult,
    annotate_cross_site_services,
    complete_china81_route_skeleton,
    exact_china81_score,
)
from setp_solver.solution import Route, Solution


TOL = 1.0e-9


@dataclass(frozen=True)
class ReciprocalSegmentCandidate:
    left_route_index: int
    right_route_index: int
    left_start: int
    left_length: int
    right_start: int
    right_length: int
    left_customers: tuple[str, ...]
    right_customers: tuple[str, ...]
    demand_gap: float
    distance_delta: float
    time_window_mismatch: float
    stable_key: str
    solution: Solution


@dataclass(frozen=True)
class ReciprocalSegmentRefinement:
    completion: China81CompletionResult
    accepted: bool
    stats: dict[str, Any]


def run_reciprocal_segment_refinement(
    bundle: China81Bundle,
    incumbent: China81CompletionResult,
    *,
    maximum_complete_candidates: int = 12,
) -> ReciprocalSegmentRefinement:
    """Try one fixed, bounded reciprocal exchange refinement."""

    if int(maximum_complete_candidates) != 12:
        raise ValueError("the registered candidate limit is exactly 12")
    generated = _generate_candidates(bundle, incumbent.solution)
    views = {
        "demand_balance": sorted(
            generated,
            key=lambda item: (
                item.demand_gap,
                item.distance_delta,
                item.time_window_mismatch,
                item.stable_key,
            ),
        ),
        "distance_change": sorted(
            generated,
            key=lambda item: (
                item.distance_delta,
                item.demand_gap,
                item.time_window_mismatch,
                item.stable_key,
            ),
        ),
        "time_window_compatibility": sorted(
            generated,
            key=lambda item: (
                item.time_window_mismatch,
                item.demand_gap,
                item.distance_delta,
                item.stable_key,
            ),
        ),
    }
    shortlisted: list[ReciprocalSegmentCandidate] = []
    seen: set[str] = set()
    for rank in range(4):
        for name in (
            "demand_balance",
            "distance_change",
            "time_window_compatibility",
        ):
            rows = views[name]
            if rank >= len(rows):
                continue
            candidate = rows[rank]
            if candidate.stable_key in seen:
                continue
            shortlisted.append(candidate)
            seen.add(candidate.stable_key)
    for name in (
        "demand_balance",
        "distance_change",
        "time_window_compatibility",
    ):
        for candidate in views[name]:
            if len(shortlisted) >= int(maximum_complete_candidates):
                break
            if candidate.stable_key in seen:
                continue
            shortlisted.append(candidate)
            seen.add(candidate.stable_key)
        if len(shortlisted) >= int(maximum_complete_candidates):
            break
    shortlisted = shortlisted[: int(maximum_complete_candidates)]

    best = incumbent
    completed_count = 0
    completion_failures: list[str] = []
    exact_violations = 0
    improvements: list[dict[str, Any]] = []
    for candidate in shortlisted:
        try:
            completed = complete_china81_route_skeleton(
                candidate.solution,
                bundle,
            )
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            completion_failures.append(str(exc))
            continue
        completed_count += 1
        objective, _, violations = exact_china81_score(
            completed.solution,
            bundle,
        )
        exact_violations += len(violations)
        if violations:
            continue
        if objective < best.objective - TOL:
            improvements.append(
                {
                    "objective": float(objective),
                    "improvement": float(
                        incumbent.objective - objective
                    ),
                    "stable_key": candidate.stable_key,
                }
            )
            best = completed
    return ReciprocalSegmentRefinement(
        completion=best,
        accepted=best.objective < incumbent.objective - TOL,
        stats={
            "candidate": "bounded_reciprocal_segment_refinement",
            "generated_candidates": len(generated),
            "shortlisted_candidates": len(shortlisted),
            "maximum_complete_candidates": int(
                maximum_complete_candidates
            ),
            "completed_candidates": completed_count,
            "completion_failures": completion_failures,
            "exact_violation_count": exact_violations,
            "accepted": best.objective
            < incumbent.objective - TOL,
            "before_objective": float(incumbent.objective),
            "after_objective": float(best.objective),
            "improvement": float(
                incumbent.objective - best.objective
            ),
            "improving_candidates": improvements,
        },
    )


def _generate_candidates(
    bundle: China81Bundle,
    solution: Solution,
) -> list[ReciprocalSegmentCandidate]:
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    route_customers = [
        [
            node_id
            for node_id in route.node_sequence
            if node_id in nodes
            and nodes[node_id].node_type.lower() == "c"
        ]
        for route in solution.routes
    ]
    maximum_capacity = max(
        float(parameters.payload_capacity_kg)
        for parameters in bundle.instance.vehicle_parameters.values()
    )
    rows: list[ReciprocalSegmentCandidate] = []
    for left_index, left_route in enumerate(solution.routes):
        left = route_customers[left_index]
        if len(left) < 3:
            continue
        for right_index in range(left_index + 1, len(solution.routes)):
            right_route = solution.routes[right_index]
            if left_route.home_depot_id == right_route.home_depot_id:
                continue
            right = route_customers[right_index]
            if len(right) < 3:
                continue
            before_distance = _route_distance(
                bundle,
                left_route,
                left,
            ) + _route_distance(bundle, right_route, right)
            for left_length in (2, 3):
                if left_length >= len(left):
                    continue
                for left_start in range(
                    len(left) - left_length + 1
                ):
                    left_segment = tuple(
                        left[left_start : left_start + left_length]
                    )
                    for right_length in (2, 3):
                        if right_length >= len(right):
                            continue
                        for right_start in range(
                            len(right) - right_length + 1
                        ):
                            right_segment = tuple(
                                right[
                                    right_start : right_start
                                    + right_length
                                ]
                            )
                            changed_left = [
                                *left[:left_start],
                                *right_segment,
                                *left[left_start + left_length :],
                            ]
                            changed_right = [
                                *right[:right_start],
                                *left_segment,
                                *right[
                                    right_start + right_length :
                                ],
                            ]
                            left_load = _demand(
                                changed_left,
                                nodes,
                                bundle.instance.demand_mass_per_unit_kg,
                            )
                            right_load = _demand(
                                changed_right,
                                nodes,
                                bundle.instance.demand_mass_per_unit_kg,
                            )
                            if (
                                left_load > maximum_capacity + TOL
                                or right_load > maximum_capacity + TOL
                            ):
                                continue
                            after_distance = _route_distance(
                                bundle,
                                left_route,
                                changed_left,
                            ) + _route_distance(
                                bundle,
                                right_route,
                                changed_right,
                            )
                            demand_gap = abs(
                                _demand(
                                    left_segment,
                                    nodes,
                                    bundle.instance.demand_mass_per_unit_kg,
                                )
                                - _demand(
                                    right_segment,
                                    nodes,
                                    bundle.instance.demand_mass_per_unit_kg,
                                )
                            )
                            time_mismatch = abs(
                                _mean_window_midpoint(
                                    left_segment,
                                    nodes,
                                )
                                - _mean_window_midpoint(
                                    right_segment,
                                    nodes,
                                )
                            )
                            new_routes = list(solution.routes)
                            new_routes[left_index] = Route(
                                vehicle_id=left_route.vehicle_id,
                                vehicle_type=left_route.vehicle_type,
                                home_depot_id=left_route.home_depot_id,
                                node_sequence=[
                                    left_route.home_depot_id,
                                    *changed_left,
                                    left_route.home_depot_id,
                                ],
                            )
                            new_routes[right_index] = Route(
                                vehicle_id=right_route.vehicle_id,
                                vehicle_type=right_route.vehicle_type,
                                home_depot_id=right_route.home_depot_id,
                                node_sequence=[
                                    right_route.home_depot_id,
                                    *changed_right,
                                    right_route.home_depot_id,
                                ],
                            )
                            stable_key = hashlib.sha256(
                                repr(
                                    (
                                        left_index,
                                        right_index,
                                        left_start,
                                        left_segment,
                                        right_start,
                                        right_segment,
                                    )
                                ).encode("utf-8")
                            ).hexdigest()
                            skeleton = annotate_cross_site_services(
                                Solution(routes=new_routes),
                                bundle.customer_home_depot,
                            )
                            rows.append(
                                ReciprocalSegmentCandidate(
                                    left_route_index=left_index,
                                    right_route_index=right_index,
                                    left_start=left_start,
                                    left_length=left_length,
                                    right_start=right_start,
                                    right_length=right_length,
                                    left_customers=left_segment,
                                    right_customers=right_segment,
                                    demand_gap=float(demand_gap),
                                    distance_delta=float(
                                        after_distance - before_distance
                                    ),
                                    time_window_mismatch=float(
                                        time_mismatch
                                    ),
                                    stable_key=stable_key,
                                    solution=skeleton,
                                )
                            )
    return rows


def _route_distance(
    bundle: China81Bundle,
    route: Route,
    customers: list[str],
) -> float:
    sequence = [
        route.home_depot_id,
        *customers,
        route.home_depot_id,
    ]
    return float(
        sum(
            bundle.instance.arc_metrics(
                left,
                right,
                route.vehicle_type,
                fallback_speed_mps=15.64,
            )[0]
            for left, right in zip(sequence, sequence[1:])
        )
    )


def _demand(
    customers: list[str] | tuple[str, ...],
    nodes: dict[str, Any],
    mass_per_unit: float | None,
) -> float:
    multiplier = 1.0 if mass_per_unit is None else float(mass_per_unit)
    return float(
        sum(float(nodes[item].demand) * multiplier for item in customers)
    )


def _mean_window_midpoint(
    customers: tuple[str, ...],
    nodes: dict[str, Any],
) -> float:
    return float(
        sum(
            0.5
            * (
                float(nodes[item].ready_time)
                + float(nodes[item].due_time)
            )
            for item in customers
        )
        / len(customers)
    )
