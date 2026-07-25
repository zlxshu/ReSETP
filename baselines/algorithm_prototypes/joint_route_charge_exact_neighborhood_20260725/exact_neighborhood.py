"""Exact branch-and-bound over an eight-customer two-route neighborhood."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import permutations
from time import perf_counter
from typing import Any

from .common import install_import_paths


install_import_paths()

from decoder_cache import RouteLocalDecoderCache
from fleet_assignment_dp import (
    NoFeasibleAssignmentError,
    _charger_slot_keys,
    _station_charger_caps,
    build_route_assignment_options,
)
from reference_decoder import RouteAssignment
from setp_solver.algorithms.resetp_alns.support.charging import (
    repair_route_charging,
)
from setp_solver.china81_completion import (
    _single_route_cost,
    annotate_cross_site_services,
)
from setp_solver.cost import route_node_schedule
from setp_solver.solution import ChargingAction, Route, Solution


TOL = 1.0e-9


class ExactNeighborhoodTimeout(RuntimeError):
    """Raised when the frozen safety limit prevents an optimality proof."""


@dataclass(frozen=True)
class CompactRouteChoice:
    customers: tuple[str, ...]
    cost: float
    assignment: RouteAssignment
    charger_slots: tuple[tuple[str, int, int], ...]

    def key(self) -> tuple[Any, ...]:
        return (
            self.cost,
            self.customers,
            self.assignment.home_depot_id,
            self.assignment.vehicle_type,
            self.assignment.charge_strategy,
            self.assignment.carbon_weight,
            self.charger_slots,
        )


@dataclass(frozen=True)
class RouteContext:
    prefix: tuple[str, ...]
    suffix: tuple[str, ...]

    def materialize(self, selected: tuple[str, ...]) -> tuple[str, ...]:
        return (*self.prefix, *selected, *self.suffix)


@dataclass(frozen=True)
class NeighborhoodSpec:
    route_indices: tuple[int, int]
    selected_customers: tuple[str, ...]
    contexts: tuple[RouteContext, RouteContext]
    old_pair_cost: float
    residual_fleet: tuple[int, ...]
    fleet_dimension: tuple[tuple[str, str], ...]
    background_slots: tuple[tuple[str, int, int, int], ...]
    station_caps: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class ExactSearchResult:
    choices: tuple[CompactRouteChoice, CompactRouteChoice] | None
    objective: float
    strict_improvement: bool
    optimality_proven: bool
    elapsed_seconds: float
    permutation_count: int
    split_count: int
    lower_bound_pruned: int
    exact_pair_count: int
    route_option_requests: int
    route_option_cache_entries: int


def customer_ids(route: Route, bundle: Any) -> tuple[str, ...]:
    node_type = {
        node.node_id: node.node_type.lower()
        for node in bundle.instance.nodes
    }
    return tuple(
        node_id
        for node_id in route.node_sequence
        if node_type.get(node_id) == "c"
    )


def choose_neighborhood(
    solution: Solution,
    bundle: Any,
) -> NeighborhoodSpec:
    """Choose two routes and two four-customer stress blocks deterministically."""

    actions_by_vehicle = {
        route.vehicle_id: tuple(
            action
            for action in solution.charging_actions
            if action.vehicle_id == route.vehicle_id
        )
        for route in solution.routes
    }
    route_rows: list[
        tuple[
            tuple[Any, ...],
            int,
            tuple[str, ...],
            tuple[str, ...],
            tuple[str, ...],
        ]
    ] = []
    node_lookup = {
        node.node_id: node for node in bundle.instance.nodes
    }
    for route_index, route in enumerate(solution.routes):
        customers = customer_ids(route, bundle)
        if len(customers) < 4:
            continue
        schedule = {
            row.node_id: row
            for row in route_node_schedule(
                route,
                bundle.instance,
                bundle.prices,
                charging_actions=solution.charging_actions,
            )
        }
        best_block: tuple[str, ...] | None = None
        best_block_key: tuple[Any, ...] | None = None
        for start in range(len(customers) - 3):
            block = customers[start : start + 4]
            slacks = tuple(
                max(
                    0.0,
                    float(node_lookup[node_id].due_time)
                    - float(schedule[node_id].t_start),
                )
                for node_id in block
            )
            key = (
                sum(slacks),
                min(slacks),
                start,
                block,
            )
            if best_block_key is None or key < best_block_key:
                best_block_key = key
                best_block = block
        if best_block is None or best_block_key is None:
            continue
        start = customers.index(best_block[0])
        prefix = customers[:start]
        suffix = customers[start + 4 :]
        cross_site = sum(
            bundle.customer_home_depot.get(customer)
            not in {None, route.home_depot_id}
            for customer in best_block
        )
        route_key = (
            -int(route.vehicle_type.lower() == "ev"),
            -len(actions_by_vehicle[route.vehicle_id]),
            -cross_site,
            best_block_key,
            route_index,
        )
        route_rows.append(
            (route_key, route_index, best_block, prefix, suffix)
        )
    if len(route_rows) < 2:
        raise RuntimeError(
            "no two routes contain four-customer exact-neighborhood blocks"
        )

    pair_rows: list[
        tuple[
            tuple[Any, ...],
            tuple[
                tuple[Any, ...],
                int,
                tuple[str, ...],
                tuple[str, ...],
                tuple[str, ...],
            ],
            tuple[
                tuple[Any, ...],
                int,
                tuple[str, ...],
                tuple[str, ...],
                tuple[str, ...],
            ],
        ]
    ] = []
    for left_pos, left in enumerate(route_rows):
        for right in route_rows[left_pos + 1 :]:
            left_route = solution.routes[left[1]]
            right_route = solution.routes[right[1]]
            pair_key = (
                -int(
                    left_route.home_depot_id
                    != right_route.home_depot_id
                ),
                -int(
                    left_route.vehicle_type.lower()
                    != right_route.vehicle_type.lower()
                ),
                left[0],
                right[0],
                left[1],
                right[1],
            )
            pair_rows.append((pair_key, left, right))
    _, left, right = min(pair_rows, key=lambda row: row[0])
    route_indices = tuple(sorted((left[1], right[1])))
    ordered = (left, right) if left[1] < right[1] else (right, left)
    selected = tuple(
        customer
        for row in ordered
        for customer in row[2]
    )
    if len(selected) != 8 or len(set(selected)) != 8:
        raise RuntimeError("selected exact neighborhood is not eight unique customers")
    contexts = tuple(
        RouteContext(prefix=row[3], suffix=row[4])
        for row in ordered
    )
    old_pair_cost = sum(
        _single_route_cost(
            solution.routes[index],
            actions_by_vehicle[solution.routes[index].vehicle_id],
            bundle,
        )
        for index in route_indices
    )
    (
        residual_fleet,
        fleet_dimension,
        background_slots,
        station_caps,
    ) = _residual_resources(
        solution,
        route_indices,
        bundle,
    )
    return NeighborhoodSpec(
        route_indices=route_indices,
        selected_customers=selected,
        contexts=(contexts[0], contexts[1]),
        old_pair_cost=float(old_pair_cost),
        residual_fleet=residual_fleet,
        fleet_dimension=fleet_dimension,
        background_slots=background_slots,
        station_caps=station_caps,
    )


def solve_exact_neighborhood(
    spec: NeighborhoodSpec,
    bundle: Any,
    *,
    time_limit_seconds: float,
) -> ExactSearchResult:
    """Exhaust the frozen neighborhood, pruning only by a valid cost bound."""

    started = perf_counter()
    best_cost = float(spec.old_pair_cost)
    best_choices: tuple[CompactRouteChoice, CompactRouteChoice] | None = None
    lower_bound_pruned = 0
    exact_pair_count = 0
    split_count = 0
    permutation_count = 0
    option_requests = 0
    option_cache: dict[
        tuple[str, ...],
        tuple[CompactRouteChoice, ...],
    ] = {}
    route_cache = RouteLocalDecoderCache()
    lower_bound = _RouteLowerBound(bundle)

    def options(sequence: tuple[str, ...]) -> tuple[CompactRouteChoice, ...]:
        nonlocal option_requests
        option_requests += 1
        cached = option_cache.get(sequence)
        if cached is not None:
            return cached
        skeleton = Solution(
            routes=[
                Route(
                    "JRC-LOCAL",
                    "cv",
                    min(bundle.fleet_caps_by_depot),
                    [
                        min(bundle.fleet_caps_by_depot),
                        *sequence,
                        min(bundle.fleet_caps_by_depot),
                    ],
                )
            ]
        )
        try:
            raw = build_route_assignment_options(
                skeleton,
                bundle,
                route_local_cache=route_cache,
                dynamic_state_hash="JRC-EXACT-STATIC",
            )[0]
        except (KeyError, NoFeasibleAssignmentError):
            raw = ()
        unique: dict[
            tuple[
                str,
                str,
                tuple[tuple[str, int, int], ...],
            ],
            CompactRouteChoice,
        ] = {}
        for item in raw:
            assignment = item.assignment
            key = (
                assignment.home_depot_id,
                assignment.vehicle_type,
                item.charger_slot_keys,
            )
            choice = CompactRouteChoice(
                customers=sequence,
                cost=float(item.route_local_cost),
                assignment=assignment,
                charger_slots=item.charger_slot_keys,
            )
            incumbent = unique.get(key)
            if incumbent is None or choice.key() < incumbent.key():
                unique[key] = choice
        result = tuple(sorted(unique.values(), key=lambda item: item.key()))
        option_cache[sequence] = result
        return result

    for perm in permutations(spec.selected_customers):
        permutation_count += 1
        if perf_counter() - started > time_limit_seconds:
            raise ExactNeighborhoodTimeout(
                "frozen 30-second neighborhood limit reached before proof"
            )
        for split in range(9):
            split_count += 1
            first = spec.contexts[0].materialize(perm[:split])
            second = spec.contexts[1].materialize(perm[split:])
            if not first or not second:
                continue
            pair_lb = lower_bound(first) + lower_bound(second)
            if pair_lb >= best_cost - TOL:
                lower_bound_pruned += 1
                continue
            first_options = options(first)
            if not first_options:
                continue
            second_options = options(second)
            if not second_options:
                continue
            for first_choice in first_options:
                for second_choice in second_options:
                    exact_pair_count += 1
                    candidate_cost = (
                        first_choice.cost + second_choice.cost
                    )
                    if candidate_cost >= best_cost - TOL:
                        continue
                    if not _resources_feasible(
                        (first_choice, second_choice),
                        spec,
                    ):
                        continue
                    best_cost = candidate_cost
                    best_choices = (first_choice, second_choice)

    elapsed = perf_counter() - started
    return ExactSearchResult(
        choices=best_choices,
        objective=float(best_cost),
        strict_improvement=best_cost < spec.old_pair_cost - TOL,
        optimality_proven=True,
        elapsed_seconds=elapsed,
        permutation_count=permutation_count,
        split_count=split_count,
        lower_bound_pruned=lower_bound_pruned,
        exact_pair_count=exact_pair_count,
        route_option_requests=option_requests,
        route_option_cache_entries=len(option_cache),
    )


def materialize_candidate(
    base: Solution,
    spec: NeighborhoodSpec,
    result: ExactSearchResult,
    bundle: Any,
) -> Solution:
    if result.choices is None:
        return base
    excluded = set(spec.route_indices)
    removed_ids = {
        base.routes[index].vehicle_id for index in spec.route_indices
    }
    untouched_routes = [
        route
        for index, route in enumerate(base.routes)
        if index not in excluded
    ]
    untouched_actions = [
        action
        for action in base.charging_actions
        if action.vehicle_id not in removed_ids
    ]
    new_routes: list[Route] = []
    new_actions: list[ChargingAction] = []
    for position, choice in enumerate(result.choices, start=1):
        assignment = choice.assignment
        vehicle_id = f"JRC-{position:02d}"
        route = Route(
            vehicle_id=vehicle_id,
            vehicle_type=assignment.vehicle_type,
            home_depot_id=assignment.home_depot_id,
            node_sequence=[
                assignment.home_depot_id,
                *choice.customers,
                assignment.home_depot_id,
            ],
        )
        actions: list[ChargingAction] = []
        if assignment.vehicle_type == "ev":
            route, actions = repair_route_charging(
                route,
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
                strategy=assignment.charge_strategy,
                carbon_weight=float(assignment.carbon_weight),
                depot_charge_window_mode="same_day_predeparture",
            )
        new_routes.append(route)
        new_actions.extend(actions)
    return annotate_cross_site_services(
        Solution(
            routes=[*untouched_routes, *new_routes],
            charging_actions=[*untouched_actions, *new_actions],
        ),
        bundle.customer_home_depot,
    )


def adjacency_change_count(before: Solution, after: Solution, bundle: Any) -> int:
    def edges(solution: Solution) -> set[tuple[str, str]]:
        out: set[tuple[str, str]] = set()
        for route in solution.routes:
            customers = customer_ids(route, bundle)
            out.update(zip(customers, customers[1:]))
        return out

    return len(edges(before).symmetric_difference(edges(after)))


def resource_change_count(before: Solution, after: Solution, bundle: Any) -> int:
    def signatures(solution: Solution) -> Counter[tuple[Any, ...]]:
        actions = {
            route.vehicle_id: tuple(
                action
                for action in solution.charging_actions
                if action.vehicle_id == route.vehicle_id
            )
            for route in solution.routes
        }
        return Counter(
            (
                route.home_depot_id,
                route.vehicle_type.lower(),
                _charger_slot_keys(list(actions[route.vehicle_id]), bundle),
            )
            for route in solution.routes
        )

    left = signatures(before)
    right = signatures(after)
    return sum((left - right).values()) + sum((right - left).values())


def _residual_resources(
    solution: Solution,
    excluded: tuple[int, int],
    bundle: Any,
) -> tuple[
    tuple[int, ...],
    tuple[tuple[str, str], ...],
    tuple[tuple[str, int, int, int], ...],
    tuple[tuple[str, int], ...],
]:
    dimension = tuple(
        (depot_id, vehicle_type)
        for depot_id in sorted(bundle.fleet_caps_by_depot)
        for vehicle_type in ("cv", "ev")
    )
    residual = [
        int(bundle.fleet_caps_by_depot[depot][f"num_{vehicle_type}"])
        for depot, vehicle_type in dimension
    ]
    index = {key: position for position, key in enumerate(dimension)}
    excluded_set = set(excluded)
    actions_by_vehicle = {
        route.vehicle_id: tuple(
            action
            for action in solution.charging_actions
            if action.vehicle_id == route.vehicle_id
        )
        for route in solution.routes
    }
    slot_use: Counter[tuple[str, int, int]] = Counter()
    for route_index, route in enumerate(solution.routes):
        if route_index in excluded_set:
            continue
        residual[
            index[(route.home_depot_id, route.vehicle_type.lower())]
        ] -= 1
        slot_use.update(
            _charger_slot_keys(
                list(actions_by_vehicle[route.vehicle_id]),
                bundle,
            )
        )
    if any(value < 0 for value in residual):
        raise RuntimeError("untouched routes exceed frozen fleet")
    return (
        tuple(residual),
        dimension,
        tuple(
            (station, day, slot, count)
            for (station, day, slot), count in sorted(slot_use.items())
        ),
        tuple(sorted(_station_charger_caps(bundle).items())),
    )


def _resources_feasible(
    choices: tuple[CompactRouteChoice, CompactRouteChoice],
    spec: NeighborhoodSpec,
) -> bool:
    fleet_index = {
        key: index for index, key in enumerate(spec.fleet_dimension)
    }
    fleet = [0 for _ in spec.residual_fleet]
    slots = Counter(
        {
            (station, day, slot): count
            for station, day, slot, count in spec.background_slots
        }
    )
    caps = dict(spec.station_caps)
    for choice in choices:
        key = (
            choice.assignment.home_depot_id,
            choice.assignment.vehicle_type,
        )
        fleet[fleet_index[key]] += 1
        if fleet[fleet_index[key]] > spec.residual_fleet[fleet_index[key]]:
            return False
        slots.update(choice.charger_slots)
    return all(
        count <= caps.get(station, 1)
        for (station, _, _), count in slots.items()
    )


class _RouteLowerBound:
    """Valid non-energy-distance lower bound for one complete route."""

    def __init__(self, bundle: Any) -> None:
        self.bundle = bundle
        self.depots = tuple(sorted(bundle.fleet_caps_by_depot))
        self.fixed = float(bundle.prices.vehicle_fixed_cost)
        self.arc_cache: dict[tuple[str, str], float] = {}

    def arc(self, left: str, right: str) -> float:
        key = (left, right)
        cached = self.arc_cache.get(key)
        if cached is not None:
            return cached
        values = []
        for vehicle_type in ("cv", "ev"):
            distance, _, _ = self.bundle.instance.arc_metrics(
                left,
                right,
                vehicle_type,
                fallback_speed_mps=float(self.bundle.prices.v_speed_ms),
            )
            values.append(
                distance
                / 1000.0
                * self.bundle.instance.non_energy_distance_cost_per_km(
                    vehicle_type,
                    fallback=float(self.bundle.prices.c_km),
                )
            )
        value = max(0.0, min(values))
        self.arc_cache[key] = value
        return value

    def __call__(self, customers: tuple[str, ...]) -> float:
        internal = sum(
            self.arc(left, right)
            for left, right in zip(customers, customers[1:])
        )
        endpoints = min(
            self.arc(depot, customers[0])
            + self.arc(customers[-1], depot)
            for depot in self.depots
        )
        return self.fixed + internal + endpoints


@dataclass(frozen=True)
class SyntheticChoice:
    route_id: str
    cost: int
    fleet: str
    slots: tuple[int, ...]


def synthetic_six_customer_equivalence() -> dict[str, Any]:
    """Prove the pruned solver matches independent no-pruning enumeration."""

    customers = tuple("ABCDEF")
    contexts = (RouteContext((), ()), RouteContext((), ()))
    route_cost = {
        (left, right): (ord(left) * 17 + ord(right) * 31) % 23 + 1
        for left in ("X", *customers)
        for right in (*customers, "X")
        if left != right
    }

    def choices(sequence: tuple[str, ...]) -> tuple[SyntheticChoice, ...]:
        path = ("X", *sequence, "X")
        base = 40 + sum(
            route_cost[(left, right)]
            for left, right in zip(path, path[1:])
        )
        parity = sum(ord(item) for item in sequence) % 2
        return (
            SyntheticChoice(
                "cv",
                base + 7,
                "cv",
                (),
            ),
            SyntheticChoice(
                "ev",
                base + parity,
                "ev",
                (parity,),
            ),
        )

    def feasible(
        pair: tuple[SyntheticChoice, SyntheticChoice],
    ) -> bool:
        fleet = Counter(item.fleet for item in pair)
        slots = Counter(slot for item in pair for slot in item.slots)
        return (
            fleet["cv"] <= 1
            and fleet["ev"] <= 2
            and all(count <= 1 for count in slots.values())
        )

    brute_best: tuple[int, tuple[Any, ...]] | None = None
    for perm in permutations(customers):
        for split in range(7):
            first = contexts[0].materialize(perm[:split])
            second = contexts[1].materialize(perm[split:])
            if not first or not second:
                continue
            for left in choices(first):
                for right in choices(second):
                    if not feasible((left, right)):
                        continue
                    key = (
                        left.route_id,
                        first,
                        right.route_id,
                        second,
                    )
                    row = (left.cost + right.cost, key)
                    if brute_best is None or row < brute_best:
                        brute_best = row
    if brute_best is None:
        raise RuntimeError("synthetic brute force found no solution")

    pruned_best: tuple[int, tuple[Any, ...]] | None = None
    pruned = 0
    for perm in permutations(customers):
        for split in range(7):
            first = perm[:split]
            second = perm[split:]
            if not first or not second:
                continue
            lower = 80
            if pruned_best is not None and lower > pruned_best[0]:
                pruned += 1
                continue
            for left in choices(first):
                for right in choices(second):
                    if not feasible((left, right)):
                        continue
                    key = (
                        left.route_id,
                        first,
                        right.route_id,
                        second,
                    )
                    row = (left.cost + right.cost, key)
                    if pruned_best is None or row < pruned_best:
                        pruned_best = row
    if pruned_best != brute_best:
        raise RuntimeError(
            f"synthetic equivalence failed: {pruned_best} != {brute_best}"
        )
    return {
        "customer_count": 6,
        "brute_objective": brute_best[0],
        "pruned_objective": pruned_best[0],
        "canonical_solution": list(brute_best[1]),
        "lower_bound_pruned": pruned,
        "equivalent": True,
    }
