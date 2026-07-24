"""Finite-fleet depot/type assignment DP for the tailored decoder."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Mapping

from setp_solver.algorithms.resetp_alns.support.charging import (
    repair_route_charging,
)
from setp_solver.china81 import China81Bundle
from setp_solver.china81_completion import _single_route_cost
from setp_solver.solution import Route, Solution

from contracts import CandidateSource, DecoderCacheKey
from decoder_cache import (
    CachedRouteLocalResult,
    RouteLocalDecoderCache,
)
from evaluation import BudgetedCompleteEvaluator
from reference_decoder import (
    ChargeRepairFunction,
    ExplicitDecodeResult,
    RouteAssignment,
    decode_explicit_assignments,
)


class NoFeasibleAssignmentError(ValueError):
    """A route skeleton has no admissible finite-fleet decode state."""


@dataclass(frozen=True)
class AssignmentOption:
    route_index: int
    assignment: RouteAssignment
    route_local_cost: float
    route_local_signature: tuple[Any, ...]


@dataclass(frozen=True)
class AssignmentCandidate:
    assignments: tuple[tuple[int, RouteAssignment], ...]
    route_local_cost: float
    fleet_use: tuple[int, ...]

    def as_mapping(self) -> dict[int, RouteAssignment]:
        return dict(self.assignments)


@dataclass(frozen=True)
class AssignmentShortlistResult:
    selected: ExplicitDecodeResult | None
    candidates: tuple[AssignmentCandidate, ...]
    decoded: tuple[ExplicitDecodeResult, ...]
    decoded_count: int
    infeasible_count: int


def build_route_assignment_options(
    skeleton: Solution,
    bundle: China81Bundle,
    *,
    allowed_depots_by_route: Mapping[
        int,
        frozenset[str],
    ]
    | None = None,
    allowed_types_by_route: Mapping[
        int,
        frozenset[str],
    ]
    | None = None,
    route_local_cache: RouteLocalDecoderCache | None = None,
    dynamic_state_hash: str = "STATIC",
    charge_repair_function: ChargeRepairFunction = (repair_route_charging),
) -> dict[int, tuple[AssignmentOption, ...]]:
    """Build route-local candidates without consuming complete budget."""

    node_type = {node.node_id: node.node_type.lower() for node in bundle.instance.nodes}
    depots = tuple(sorted(bundle.fleet_caps_by_depot))
    depot_constraints = dict(allowed_depots_by_route or {})
    type_constraints = {
        int(route_index): frozenset(
            str(vehicle_type).strip().lower() for vehicle_type in vehicle_types
        )
        for route_index, vehicle_types in dict(allowed_types_by_route or {}).items()
    }
    options: dict[int, tuple[AssignmentOption, ...]] = {}
    for route_index, route in enumerate(skeleton.routes):
        customers = tuple(
            node_id for node_id in route.node_sequence if node_type.get(node_id) == "c"
        )
        if not customers:
            continue
        route_options: list[AssignmentOption] = []
        for depot_id in depots:
            if (
                route_index in depot_constraints
                and depot_id not in depot_constraints[route_index]
            ):
                continue
            permitted_types = type_constraints.get(
                route_index,
                frozenset({"cv", "ev"}),
            )
            cv_route = Route(
                vehicle_id=f"DP-{route_index:03d}-CV",
                vehicle_type="cv",
                home_depot_id=depot_id,
                node_sequence=[depot_id, *customers, depot_id],
            )
            if "cv" in permitted_types:
                cv_cost = _cached_route_local_cost(
                    cv_route,
                    bundle,
                    charge_strategy="not_applicable",
                    carbon_weight=0.0,
                    dynamic_state_hash=dynamic_state_hash,
                    cache=route_local_cache,
                    compute=lambda: _single_route_cost(
                        cv_route,
                        (),
                        bundle,
                    ),
                )
                if math.isfinite(cv_cost):
                    route_options.append(
                        AssignmentOption(
                            route_index=route_index,
                            assignment=RouteAssignment(
                                depot_id,
                                "cv",
                            ),
                            route_local_cost=float(cv_cost),
                            route_local_signature=(
                                depot_id,
                                "cv",
                                customers,
                            ),
                        )
                    )
            if "ev" not in permitted_types:
                continue
            for label, strategy, carbon_weight in (
                ("integrated", "integrated", 1.0),
                ("low_carbon", "legacy", 1.0),
                ("immediate", "integrated", 0.0),
            ):
                ev_route = Route(
                    vehicle_id=f"DP-{route_index:03d}-EV",
                    vehicle_type="ev",
                    home_depot_id=depot_id,
                    node_sequence=[depot_id, *customers, depot_id],
                )
                ev_cost = _cached_route_local_cost(
                    ev_route,
                    bundle,
                    charge_strategy=strategy,
                    carbon_weight=carbon_weight,
                    dynamic_state_hash=dynamic_state_hash,
                    cache=route_local_cache,
                    compute=lambda route=ev_route,
                    selected_strategy=strategy,
                    selected_weight=carbon_weight: (
                        _repaired_route_local_cost(
                            route,
                            bundle,
                            charge_repair_function=(charge_repair_function),
                            strategy=selected_strategy,
                            carbon_weight=selected_weight,
                        )
                    ),
                )
                if not math.isfinite(ev_cost):
                    continue
                route_options.append(
                    AssignmentOption(
                        route_index=route_index,
                        assignment=RouteAssignment(
                            depot_id,
                            "ev",
                            charge_strategy=strategy,
                            carbon_weight=carbon_weight,
                        ),
                        route_local_cost=float(ev_cost),
                        route_local_signature=(
                            depot_id,
                            "ev",
                            label,
                            customers,
                        ),
                    )
                )
        if not route_options:
            raise NoFeasibleAssignmentError(
                f"route {route_index} has no depot/type assignment"
            )
        unique: dict[tuple[Any, ...], AssignmentOption] = {}
        for option in route_options:
            key = option.route_local_signature
            incumbent = unique.get(key)
            if (
                incumbent is None
                or option.route_local_cost < incumbent.route_local_cost
            ):
                unique[key] = option
        options[route_index] = tuple(
            sorted(
                unique.values(),
                key=lambda item: (
                    item.route_local_cost,
                    item.route_local_signature,
                ),
            )
        )
    return options


def solve_finite_fleet_assignment_dp(
    options_by_route: Mapping[
        int,
        tuple[AssignmentOption, ...],
    ],
    fleet_caps_by_depot: Mapping[str, Mapping[str, int]],
    *,
    beam_per_state: int = 3,
    max_candidates: int = 12,
) -> tuple[AssignmentCandidate, ...]:
    """Jointly shortlist route assignments under exact finite fleet caps."""

    if beam_per_state < 1 or max_candidates < 1:
        raise ValueError("DP beam and candidate count must be positive")
    depots = tuple(sorted(fleet_caps_by_depot))
    dimension = {
        (depot_id, vehicle_type): 2 * depot_index + type_index
        for depot_index, depot_id in enumerate(depots)
        for type_index, vehicle_type in enumerate(("cv", "ev"))
    }
    caps = tuple(
        int(fleet_caps_by_depot[depot_id][f"num_{vehicle_type}"])
        for depot_id in depots
        for vehicle_type in ("cv", "ev")
    )
    zero = tuple(0 for _ in caps)
    states: dict[
        tuple[int, ...],
        list[AssignmentCandidate],
    ] = {
        zero: [
            AssignmentCandidate(
                assignments=(),
                route_local_cost=0.0,
                fleet_use=zero,
            )
        ]
    }
    for route_index in sorted(options_by_route):
        route_options = options_by_route[route_index]
        if not route_options:
            raise NoFeasibleAssignmentError(
                f"route {route_index} has no assignment options"
            )
        next_states: dict[
            tuple[int, ...],
            list[AssignmentCandidate],
        ] = {}
        for state, partials in states.items():
            for partial in partials:
                for option in route_options:
                    assignment = option.assignment
                    key = (
                        assignment.home_depot_id,
                        assignment.vehicle_type.strip().lower(),
                    )
                    try:
                        position = dimension[key]
                    except KeyError as exc:
                        raise ValueError(
                            f"assignment has no fleet dimension: {key}"
                        ) from exc
                    updated = list(state)
                    updated[position] += 1
                    if updated[position] > caps[position]:
                        continue
                    fleet_use = tuple(updated)
                    candidate = AssignmentCandidate(
                        assignments=(
                            *partial.assignments,
                            (route_index, assignment),
                        ),
                        route_local_cost=(
                            partial.route_local_cost + option.route_local_cost
                        ),
                        fleet_use=fleet_use,
                    )
                    bucket = next_states.setdefault(
                        fleet_use,
                        [],
                    )
                    bucket.append(candidate)
                    bucket.sort(key=_candidate_key)
                    del bucket[beam_per_state:]
        states = next_states
        if not states:
            raise NoFeasibleAssignmentError(
                "finite fleet DP has no feasible partial assignment "
                f"after route {route_index}"
            )
    candidates = sorted(
        (candidate for bucket in states.values() for candidate in bucket),
        key=_candidate_key,
    )
    unique: dict[
        tuple[tuple[int, RouteAssignment], ...],
        AssignmentCandidate,
    ] = {}
    for candidate in candidates:
        unique.setdefault(candidate.assignments, candidate)
    return tuple(list(unique.values())[:max_candidates])


def decode_assignment_shortlist(
    skeleton: Solution,
    bundle: China81Bundle,
    *,
    evaluator: BudgetedCompleteEvaluator,
    source: CandidateSource,
    beam_per_state: int = 3,
    max_candidates: int = 12,
    source_metadata: dict[str, Any] | None = None,
    allowed_depots_by_route: Mapping[
        int,
        frozenset[str],
    ]
    | None = None,
    allowed_types_by_route: Mapping[
        int,
        frozenset[str],
    ]
    | None = None,
    route_local_cache: RouteLocalDecoderCache | None = None,
    dynamic_state_hash: str = "STATIC",
    charge_repair_function: ChargeRepairFunction = (repair_route_charging),
) -> AssignmentShortlistResult:
    """Fully score a small DP shortlist and keep the best feasible result."""

    options = build_route_assignment_options(
        skeleton,
        bundle,
        allowed_depots_by_route=allowed_depots_by_route,
        allowed_types_by_route=allowed_types_by_route,
        route_local_cache=route_local_cache,
        dynamic_state_hash=dynamic_state_hash,
        charge_repair_function=charge_repair_function,
    )
    candidates = solve_finite_fleet_assignment_dp(
        options,
        bundle.fleet_caps_by_depot,
        beam_per_state=beam_per_state,
        max_candidates=max_candidates,
    )
    decoded: list[ExplicitDecodeResult] = []
    infeasible = 0
    for rank, candidate in enumerate(candidates, start=1):
        if evaluator.ledger.remaining <= 0:
            break
        result = decode_explicit_assignments(
            skeleton,
            bundle,
            assignments=candidate.as_mapping(),
            evaluator=evaluator,
            source=source,
            source_metadata={
                **dict(source_metadata or {}),
                "assignment_dp_rank": rank,
                "route_local_cost": candidate.route_local_cost,
                "fleet_use": list(candidate.fleet_use),
            },
            charge_repair_function=charge_repair_function,
        )
        if result.scored.feasible:
            decoded.append(result)
        else:
            infeasible += 1
    selected = min(decoded, key=lambda item: item.scored.objective) if decoded else None
    return AssignmentShortlistResult(
        selected=selected,
        candidates=candidates,
        decoded=tuple(decoded),
        decoded_count=len(decoded) + infeasible,
        infeasible_count=infeasible,
    )


def _candidate_key(
    candidate: AssignmentCandidate,
) -> tuple[Any, ...]:
    return (
        candidate.route_local_cost,
        tuple(
            (
                route_index,
                assignment.home_depot_id,
                assignment.vehicle_type,
                assignment.charge_strategy,
                assignment.carbon_weight,
            )
            for route_index, assignment in candidate.assignments
        ),
    )


def _cached_route_local_cost(
    route: Route,
    bundle: China81Bundle,
    *,
    charge_strategy: str,
    carbon_weight: float,
    dynamic_state_hash: str,
    cache: RouteLocalDecoderCache | None,
    compute: Callable[[], float],
) -> float:
    key = _route_cache_key(
        route,
        bundle,
        charge_strategy=charge_strategy,
        carbon_weight=carbon_weight,
        dynamic_state_hash=dynamic_state_hash,
    )
    if cache is not None:
        cached = cache.get(key)
        if cached is not None:
            return float(cached.route_local_cost) if cached.feasible else math.inf
    try:
        value = float(compute())
    except (KeyError, RuntimeError, TypeError, ValueError):
        value = math.inf
    feasible = math.isfinite(value)
    if cache is not None:
        cache.put(
            key,
            CachedRouteLocalResult(
                feasible=feasible,
                route_local_cost=value if feasible else None,
            ),
        )
    return value


def _repaired_route_local_cost(
    route: Route,
    bundle: China81Bundle,
    *,
    charge_repair_function: ChargeRepairFunction,
    strategy: str,
    carbon_weight: float,
) -> float:
    repaired, actions = charge_repair_function(
        route,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        strategy=strategy,
        carbon_weight=carbon_weight,
        depot_charge_window_mode="same_day_predeparture",
    )
    return float(
        _single_route_cost(
            repaired,
            tuple(actions),
            bundle,
        )
    )


def _route_cache_key(
    route: Route,
    bundle: China81Bundle,
    *,
    charge_strategy: str,
    carbon_weight: float,
    dynamic_state_hash: str,
) -> DecoderCacheKey:
    node_by_id = {node.node_id: node for node in bundle.instance.nodes}
    try:
        depot = node_by_id[route.home_depot_id]
    except KeyError as exc:
        raise ValueError(
            f"route cache uses unknown depot {route.home_depot_id!r}"
        ) from exc
    city = str(depot.city or "").strip().lower()
    if not city:
        raise ValueError("route cache requires an explicit depot city")
    try:
        price_area = bundle.price_area_by_city[city]
        carbon_column = bundle.carbon_source_column_by_city[city]
        diesel_zone = bundle.diesel_zone_by_city[city]
    except KeyError as exc:
        raise ValueError(
            f"route cache has incomplete runtime mapping for {city!r}"
        ) from exc
    return DecoderCacheKey(
        instance_id=bundle.instance_id,
        date=bundle.date,
        region=bundle.region,
        city=city,
        price_area_id=str(price_area),
        carbon_source_column=str(carbon_column),
        diesel_zone=str(diesel_zone),
        home_depot_id=route.home_depot_id,
        vehicle_type=route.vehicle_type.strip().lower(),
        charge_strategy=str(charge_strategy),
        carbon_weight=float(carbon_weight),
        node_sequence=tuple(route.node_sequence),
        dynamic_state_hash=str(dynamic_state_hash),
        runtime_parameter_authority=(bundle.runtime_parameter_authority),
        fleet_authority=bundle.fleet_authority,
    )
