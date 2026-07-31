"""Time-window-positioned reciprocal segment refinement for China81."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from typing import Any

from reciprocal_segment_refinement import (
    ReciprocalSegmentCandidate,
    ReciprocalSegmentRefinement,
    TOL,
    _demand,
    _mean_window_midpoint,
    _route_distance,
)
from setp_solver.china81 import China81Bundle
from setp_solver.china81_completion import (
    China81CompletionResult,
    annotate_cross_site_services,
    complete_china81_route_skeleton,
    exact_china81_score,
)
from setp_solver.solution import Route, Solution


def run_reciprocal_segment_refinement_v2(
    bundle: China81Bundle,
    incumbent: China81CompletionResult,
    *,
    maximum_complete_candidates: int = 12,
) -> ReciprocalSegmentRefinement:
    if int(maximum_complete_candidates) != 12:
        raise ValueError("the registered candidate limit is exactly 12")
    generated = _generate_positioned_candidates(
        bundle,
        incumbent.solution,
    )
    views = {
        "demand_balance": sorted(
            generated,
            key=lambda item: (
                item.demand_gap,
                item.time_window_mismatch,
                item.distance_delta,
                item.stable_key,
            ),
        ),
        "distance_change": sorted(
            generated,
            key=lambda item: (
                item.distance_delta,
                item.time_window_mismatch,
                item.demand_gap,
                item.stable_key,
            ),
        ),
        "time_window_compatibility": sorted(
            generated,
            key=lambda item: (
                item.time_window_mismatch,
                item.distance_delta,
                item.demand_gap,
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
    for name in views:
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
            "candidate": (
                "bounded_reciprocal_segment_refinement_v2"
            ),
            "generated_candidates": len(generated),
            "zero_estimated_lateness_candidates": sum(
                item.time_window_mismatch <= TOL
                for item in generated
            ),
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


def _generate_positioned_candidates(
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
                    stripped_left = [
                        *left[:left_start],
                        *left[left_start + left_length :],
                    ]
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
                            stripped_right = [
                                *right[:right_start],
                                *right[
                                    right_start + right_length :
                                ],
                            ]
                            best_layout = None
                            for incoming_left in _orientations(
                                right_segment
                            ):
                                for incoming_right in _orientations(
                                    left_segment
                                ):
                                    for left_position in range(
                                        len(stripped_left) + 1
                                    ):
                                        changed_left = [
                                            *stripped_left[
                                                :left_position
                                            ],
                                            *incoming_left,
                                            *stripped_left[
                                                left_position:
                                            ],
                                        ]
                                        left_lateness = _route_lateness(
                                            bundle,
                                            left_route,
                                            changed_left,
                                            nodes,
                                        )
                                        for right_position in range(
                                            len(stripped_right) + 1
                                        ):
                                            changed_right = [
                                                *stripped_right[
                                                    :right_position
                                                ],
                                                *incoming_right,
                                                *stripped_right[
                                                    right_position:
                                                ],
                                            ]
                                            lateness = (
                                                left_lateness
                                                + _route_lateness(
                                                    bundle,
                                                    right_route,
                                                    changed_right,
                                                    nodes,
                                                )
                                            )
                                            after_distance = (
                                                _route_distance(
                                                    bundle,
                                                    left_route,
                                                    changed_left,
                                                )
                                                + _route_distance(
                                                    bundle,
                                                    right_route,
                                                    changed_right,
                                                )
                                            )
                                            key = (
                                                lateness,
                                                after_distance,
                                                left_position,
                                                right_position,
                                                incoming_left,
                                                incoming_right,
                                            )
                                            if (
                                                best_layout is None
                                                or key
                                                < best_layout[0]
                                            ):
                                                best_layout = (
                                                    key,
                                                    changed_left,
                                                    changed_right,
                                                    after_distance,
                                                )
                            if best_layout is None:
                                continue
                            _, changed_left, changed_right, after_distance = (
                                best_layout
                            )
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
                            lateness = best_layout[0][0]
                            new_routes = list(solution.routes)
                            new_routes[left_index] = replace(
                                left_route,
                                node_sequence=[
                                    left_route.home_depot_id,
                                    *changed_left,
                                    left_route.home_depot_id,
                                ],
                            )
                            new_routes[right_index] = replace(
                                right_route,
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
                                        tuple(changed_left),
                                        tuple(changed_right),
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
                                        lateness
                                    ),
                                    stable_key=stable_key,
                                    solution=skeleton,
                                )
                            )
    return rows


def _orientations(
    segment: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    reversed_segment = tuple(reversed(segment))
    return (
        (segment,)
        if reversed_segment == segment
        else (segment, reversed_segment)
    )


def _route_lateness(
    bundle: China81Bundle,
    route: Route,
    customers: list[str],
    nodes: dict[str, Any],
) -> float:
    current = max(
        6.0 * 60.0 * 60.0,
        float(nodes[route.home_depot_id].ready_time),
    )
    previous = route.home_depot_id
    lateness = 0.0
    for customer_id in customers:
        current += bundle.instance.arc_metrics(
            previous,
            customer_id,
            route.vehicle_type,
            fallback_speed_mps=15.64,
        )[1]
        node = nodes[customer_id]
        current = max(current, float(node.ready_time))
        lateness += max(0.0, current - float(node.due_time))
        current += float(node.service_time)
        previous = customer_id
    current += bundle.instance.arc_metrics(
        previous,
        route.home_depot_id,
        route.vehicle_type,
        fallback_speed_mps=15.64,
    )[1]
    lateness += max(
        0.0,
        current - float(nodes[route.home_depot_id].due_time),
    )
    return float(lateness)
