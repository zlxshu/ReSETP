"""Generate route moves and retain only jointly decodable structures."""

from __future__ import annotations

import heapq
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from decoder_cache import RouteLocalDecoderCache
from fleet_assignment_dp import (
    NoFeasibleAssignmentError,
    _station_charger_caps,
    build_route_assignment_options,
    solve_finite_fleet_assignment_dp,
)
from setp_solver.algorithms.resetp_alns.operators.strong_bridge import (
    solution_signature_hash,
)
from setp_solver.solution import Solution

from baselines.algorithm_prototypes.tailored_dp_vns_20260725.neighborhoods import (
    _customer_routes,
    _drop_empty_routes,
    _proxy_distance,
    _relocate_candidates,
    _swap_candidates,
    _two_opt_candidates,
    _two_opt_star_candidates,
    customer_multiset,
)

LOCAL_NEIGHBORHOODS = (
    "relocate",
    "swap",
    "two_opt",
    "two_opt_star",
)
NEIGHBORHOOD_ORDER = (*LOCAL_NEIGHBORHOODS, "ejection_rebuild")


@dataclass(frozen=True)
class RawMove:
    neighborhood: str
    skeleton: Solution
    distance_delta: float
    detail: str


@dataclass(frozen=True)
class FeasibleMove:
    neighborhood: str
    skeleton: Solution
    route_local_cost: float
    distance_delta: float
    detail: str
    assignment_candidate_count: int


@dataclass(frozen=True)
class FeasibleCollection:
    moves: tuple[FeasibleMove, ...]
    raw_generated: int
    raw_inspected: int
    duplicate_structures: int
    infeasible_structures: int
    inspection_limit_hit: bool


def iter_raw_local_moves(
    solution: Solution,
    bundle: Any,
    *,
    neighborhood: str,
    candidate_pool_limit: int = 512,
) -> Iterable[RawMove]:
    """Yield a bounded granular pool in deterministic cheap-proxy order."""

    if neighborhood not in LOCAL_NEIGHBORHOODS:
        raise ValueError(f"unknown local neighborhood {neighborhood!r}")
    if candidate_pool_limit < 1:
        raise ValueError("candidate pool limit must be positive")
    customer_ids = frozenset(
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    )
    routes = _customer_routes(solution, customer_ids)
    before = _proxy_distance(routes, bundle)
    generator = {
        "relocate": _relocate_candidates,
        "swap": _swap_candidates,
        "two_opt": _two_opt_candidates,
        "two_opt_star": _two_opt_star_candidates,
    }[neighborhood]
    incumbent_signature = solution_signature_hash(Solution(routes=routes))
    seen: set[str] = set()

    def unique_moves() -> Iterable[RawMove]:
        for changed_routes, detail in generator(routes):
            normalized = _drop_empty_routes(changed_routes)
            if not normalized:
                continue
            skeleton = Solution(routes=normalized)
            signature = solution_signature_hash(skeleton)
            if signature == incumbent_signature or signature in seen:
                continue
            seen.add(signature)
            yield RawMove(
                neighborhood=neighborhood,
                skeleton=skeleton,
                distance_delta=float(
                    _proxy_distance(normalized, bundle) - before
                ),
                detail=detail,
            )

    yield from heapq.nsmallest(
        candidate_pool_limit,
        unique_moves(),
        key=lambda item: (
            item.distance_delta,
            item.detail,
            solution_signature_hash(item.skeleton),
        ),
    )


def joint_feasibility_proxy(
    skeleton: Solution,
    bundle: Any,
    *,
    route_local_cache: RouteLocalDecoderCache,
    beam_per_state: int = 2,
    max_assignment_candidates: int = 2,
) -> tuple[float, int]:
    """Return the best route-local total after all joint hard-resource gates."""

    options = build_route_assignment_options(
        skeleton,
        bundle,
        route_local_cache=route_local_cache,
        dynamic_state_hash="STATIC",
    )
    assignments = solve_finite_fleet_assignment_dp(
        options,
        bundle.fleet_caps_by_depot,
        beam_per_state=beam_per_state,
        max_candidates=max_assignment_candidates,
        station_charger_caps=_station_charger_caps(bundle),
    )
    if not assignments:
        raise NoFeasibleAssignmentError(
            "joint assignment DP returned no candidate"
        )
    return (
        float(assignments[0].route_local_cost),
        len(assignments),
    )


def collect_feasible_moves(
    raw_moves: Iterable[RawMove],
    bundle: Any,
    *,
    baseline_customers: tuple[str, ...],
    route_local_cache: RouteLocalDecoderCache,
    inspection_limit: int,
    feasible_limit: int,
    feasibility_function: Callable[
        [Solution, Any],
        tuple[float, int],
    ]
    | None = None,
) -> FeasibleCollection:
    """Inspect raw moves until the fixed safety cap, then rank feasible moves.

    Crucially, infeasible early moves do not consume the feasible shortlist.
    This is the regression boundary that the failed distance-first candidate
    violated.
    """

    if inspection_limit < 1 or feasible_limit < 1:
        raise ValueError("inspection and feasible limits must be positive")
    feasible: dict[str, FeasibleMove] = {}
    raw_generated = 0
    raw_inspected = 0
    duplicates = 0
    infeasible = 0
    limit_hit = False
    seen: set[str] = set()

    for move in raw_moves:
        raw_generated += 1
        signature = solution_signature_hash(move.skeleton)
        if signature in seen:
            duplicates += 1
            continue
        seen.add(signature)
        if raw_inspected >= inspection_limit:
            limit_hit = True
            break
        raw_inspected += 1
        if customer_multiset(move.skeleton, bundle) != baseline_customers:
            raise RuntimeError(
                f"{move.neighborhood} changed the customer multiset"
            )
        try:
            if feasibility_function is None:
                local_cost, assignment_count = joint_feasibility_proxy(
                    move.skeleton,
                    bundle,
                    route_local_cache=route_local_cache,
                )
            else:
                local_cost, assignment_count = feasibility_function(
                    move.skeleton,
                    bundle,
                )
        except (
            KeyError,
            NoFeasibleAssignmentError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            infeasible += 1
            continue
        feasible[signature] = FeasibleMove(
            neighborhood=move.neighborhood,
            skeleton=move.skeleton,
            route_local_cost=float(local_cost),
            distance_delta=float(move.distance_delta),
            detail=move.detail,
            assignment_candidate_count=int(assignment_count),
        )

    selected = tuple(
        sorted(
            feasible.values(),
            key=lambda item: (
                item.route_local_cost,
                item.distance_delta,
                item.detail,
                solution_signature_hash(item.skeleton),
            ),
        )[:feasible_limit]
    )
    return FeasibleCollection(
        moves=selected,
        raw_generated=raw_generated,
        raw_inspected=raw_inspected,
        duplicate_structures=duplicates,
        infeasible_structures=infeasible,
        inspection_limit_hit=limit_hit,
    )
