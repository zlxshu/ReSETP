"""Isolated dynamic-replanning micro-probes under EA-001.

This module is intentionally independent from the formal ReSETP solver and E7.
It implements only hand-checkable synthetic examples for functionality,
operator activity, and complete-evaluation accounting.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Callable, Mapping, Sequence


class ProbeContractError(ValueError):
    """Raised when a synthetic probe violates its frozen micro-contract."""


@dataclass(frozen=True)
class VehicleState:
    vehicle_id: str
    current_node: str
    current_time_min: int
    load_kg: int
    capacity_kg: int
    soc_kwh: float
    battery_kwh: float
    frozen_prefix: tuple[str, ...]
    onboard_orders: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.vehicle_id:
            raise ProbeContractError("vehicle_id must be non-empty")
        if self.load_kg < 0 or self.load_kg > self.capacity_kg:
            raise ProbeContractError("load_kg must be within [0, capacity_kg]")
        if self.soc_kwh < 0 or self.soc_kwh > self.battery_kwh:
            raise ProbeContractError("soc_kwh must be within [0, battery_kwh]")
        if not self.frozen_prefix:
            raise ProbeContractError("frozen_prefix must contain the current state")


@dataclass(frozen=True)
class PseudoDepotSnapshot:
    schema_version: str
    event_id: str
    decision_time_min: int
    vehicles: tuple[VehicleState, ...]

    def __post_init__(self) -> None:
        vehicle_ids = [vehicle.vehicle_id for vehicle in self.vehicles]
        if len(vehicle_ids) != len(set(vehicle_ids)):
            raise ProbeContractError("physical vehicle IDs must be unique")


def snapshot_to_json(snapshot: PseudoDepotSnapshot) -> str:
    """Serialize a state snapshot deterministically without changing units."""
    payload = asdict(snapshot)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def snapshot_from_json(payload: str) -> PseudoDepotSnapshot:
    """Read a state snapshot and restore tuple/identity semantics."""
    raw = json.loads(payload)
    vehicles = tuple(
        VehicleState(
            vehicle_id=str(item["vehicle_id"]),
            current_node=str(item["current_node"]),
            current_time_min=int(item["current_time_min"]),
            load_kg=int(item["load_kg"]),
            capacity_kg=int(item["capacity_kg"]),
            soc_kwh=float(item["soc_kwh"]),
            battery_kwh=float(item["battery_kwh"]),
            frozen_prefix=tuple(str(node) for node in item["frozen_prefix"]),
            onboard_orders=tuple(str(order) for order in item["onboard_orders"]),
        )
        for item in raw["vehicles"]
    )
    return PseudoDepotSnapshot(
        schema_version=str(raw["schema_version"]),
        event_id=str(raw["event_id"]),
        decision_time_min=int(raw["decision_time_min"]),
        vehicles=vehicles,
    )


def assert_frozen_prefixes(
    routes: Mapping[str, Sequence[str]],
    frozen_prefixes: Mapping[str, Sequence[str]],
) -> None:
    """Require exact prefix and physical-vehicle preservation."""
    if set(routes) != set(frozen_prefixes):
        raise ProbeContractError("route vehicle IDs differ from frozen vehicle IDs")
    for vehicle_id, prefix in frozen_prefixes.items():
        route = tuple(routes[vehicle_id])
        expected = tuple(prefix)
        if route[: len(expected)] != expected:
            raise ProbeContractError(
                f"frozen prefix changed for {vehicle_id}: "
                f"expected={expected}, observed={route[:len(expected)]}"
            )


def own_minimal_suffix_repair(
    routes: Mapping[str, Sequence[str]],
    frozen_prefixes: Mapping[str, Sequence[str]],
    suffix_rank: Mapping[str, int],
) -> dict[str, tuple[str, ...]]:
    """Deterministically reorder only suffixes in a hand-checkable probe."""
    repaired: dict[str, tuple[str, ...]] = {}
    for vehicle_id, route_items in routes.items():
        route = tuple(route_items)
        prefix = tuple(frozen_prefixes[vehicle_id])
        if route[: len(prefix)] != prefix:
            raise ProbeContractError("input already violates the frozen prefix")
        suffix = route[len(prefix) :]
        repaired[vehicle_id] = prefix + tuple(
            sorted(suffix, key=lambda node: (suffix_rank[node], node))
        )
    assert_frozen_prefixes(repaired, frozen_prefixes)
    return repaired


def ortools_lock_probe() -> dict[str, Any]:
    """Run an optional OR-Tools external lock-preservation comparison."""
    try:
        import ortools
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    except ImportError:
        return {
            "available": False,
            "status": "SKIP_OPTIONAL_DEPENDENCY_NOT_INSTALLED",
            "version": None,
            "routes": {},
            "prefix_preserved": None,
        }

    coordinates = [(0, 0), (1, 0), (2, 0), (3, 0), (0, 1), (0, 2), (0, 3)]
    manager = pywrapcp.RoutingIndexManager(len(coordinates), 2, 0)
    routing = pywrapcp.RoutingModel(manager)

    def distance(from_index: int, to_index: int) -> int:
        from_node = coordinates[manager.IndexToNode(from_index)]
        to_node = coordinates[manager.IndexToNode(to_index)]
        return abs(from_node[0] - to_node[0]) + abs(from_node[1] - to_node[1])

    callback_index = routing.RegisterTransitCallback(distance)
    routing.SetArcCostEvaluatorOfAllVehicles(callback_index)

    parameters = pywrapcp.DefaultRoutingSearchParameters()
    parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    parameters.time_limit.seconds = 1
    routing.CloseModelWithParameters(parameters)

    lock_nodes = [[1, 2], [4]]
    locks_applied = routing.ApplyLocksToAllVehicles(lock_nodes, False)
    if not locks_applied:
        raise ProbeContractError("OR-Tools rejected the hand-built lock chains")
    solution = routing.SolveWithParameters(parameters)
    if solution is None:
        raise ProbeContractError("OR-Tools did not return a micro-solution")

    routes: dict[str, tuple[str, ...]] = {}
    for vehicle in range(2):
        nodes: list[str] = []
        index = routing.Start(vehicle)
        while not routing.IsEnd(index):
            nodes.append(str(manager.IndexToNode(index)))
            index = solution.Value(routing.NextVar(index))
        routes[f"V{vehicle + 1}"] = tuple(nodes)

    frozen = {"V1": ("0", "1", "2"), "V2": ("0", "4")}
    assert_frozen_prefixes(routes, frozen)
    return {
        "available": True,
        "status": "PASS_EXTERNAL_LOCK_COMPARISON",
        "version": ortools.__version__,
        "routes": {key: list(value) for key, value in routes.items()},
        "prefix_preserved": True,
    }


@dataclass(frozen=True)
class SyntheticOrder:
    order_id: str
    demand: int
    allowed_vehicles: tuple[str, ...]


@dataclass
class CompleteEvaluationCounter:
    budget: int
    complete_evaluations: int = 0

    def evaluate(
        self,
        candidate: Mapping[str, Sequence[str]],
        evaluator: Callable[[Mapping[str, Sequence[str]]], tuple[bool, str]],
    ) -> tuple[bool, str]:
        if self.complete_evaluations >= self.budget:
            raise ProbeContractError("complete-evaluation budget exceeded")
        self.complete_evaluations += 1
        return evaluator(candidate)


def regret_rank(
    insertion_costs: Mapping[str, Sequence[float]],
) -> tuple[str, dict[str, float]]:
    """Return the highest regret-2 request and all computed regret values."""
    regrets: dict[str, float] = {}
    for request_id, costs in insertion_costs.items():
        ordered = sorted(float(cost) for cost in costs)
        if len(ordered) < 2:
            raise ProbeContractError("regret-2 requires at least two insertion costs")
        regrets[request_id] = ordered[1] - ordered[0]
    selected = max(regrets, key=lambda request_id: (regrets[request_id], request_id))
    return selected, regrets


def _synthetic_orders() -> dict[str, SyntheticOrder]:
    return {
        "A": SyntheticOrder("A", 6, ("V1", "V2")),
        "B": SyntheticOrder("B", 4, ("V1",)),
        "C": SyntheticOrder("C", 6, ("V2", "V3")),
        "D": SyntheticOrder("D", 4, ("V2",)),
        "E": SyntheticOrder("E", 4, ("V3",)),
        "N": SyntheticOrder("N", 6, ("V1",)),
    }


def _evaluate_synthetic_routes(
    candidate: Mapping[str, Sequence[str]],
) -> tuple[bool, str]:
    orders = _synthetic_orders()
    if set(candidate) != {"V1", "V2", "V3"}:
        return False, "vehicle_set_mismatch"
    flattened = [order_id for route in candidate.values() for order_id in route]
    if sorted(flattened) != sorted(orders):
        return False, "customer_coverage_or_uniqueness"
    for vehicle_id, route in candidate.items():
        load = sum(orders[order_id].demand for order_id in route)
        if load > 10:
            return False, f"capacity:{vehicle_id}"
        for order_id in route:
            if vehicle_id not in orders[order_id].allowed_vehicles:
                return False, f"compatibility:{order_id}:{vehicle_id}"
    return True, "feasible"


def bounded_regret_ejection_probe(budget: int) -> dict[str, Any]:
    """Exercise regret and a depth-2 ejection chain at budget 0/1/2/5."""
    if budget not in {0, 1, 2, 5}:
        raise ProbeContractError("micro-probe budget must be one of 0, 1, 2, 5")

    selected, regrets = regret_rank({"U": (2.0, 9.0), "V": (4.0, 5.0)})
    initial = {"V1": ("A", "B"), "V2": ("C", "D"), "V3": ("E",)}
    candidates: list[tuple[dict[str, tuple[str, ...]], int]] = [
        ({"V1": ("N", "B"), "V2": ("C", "D"), "V3": ("E", "A")}, 1),
        ({"V1": ("N", "B"), "V2": ("A", "D"), "V3": ("E", "C")}, 2),
        ({"V1": ("B", "N"), "V2": ("D", "A"), "V3": ("C", "E")}, 2),
        ({"V1": ("N", "B"), "V2": ("A", "D"), "V3": ("E", "C", "C")}, 2),
        ({"V1": ("B", "N"), "V2": ("A", "D"), "V3": ("E", "C")}, 2),
    ]

    direct_feasible = any(
        sum(_synthetic_orders()[order_id].demand for order_id in route) + 6 <= 10
        and vehicle_id == "V1"
        for vehicle_id, route in initial.items()
    )
    if direct_feasible:
        raise ProbeContractError("micro-instance must block direct insertion")

    counter = CompleteEvaluationCounter(budget=budget)
    evaluated: list[dict[str, Any]] = []
    for candidate, ejection_depth in candidates[:budget]:
        accepted, reason = counter.evaluate(candidate, _evaluate_synthetic_routes)
        evaluated.append(
            {
                "candidate_index": len(evaluated) + 1,
                "ejection_depth": ejection_depth,
                "accepted": accepted,
                "reason": reason,
            }
        )

    accepted_depths = [
        int(row["ejection_depth"]) for row in evaluated if bool(row["accepted"])
    ]
    return {
        "budget": budget,
        "complete_evaluations": counter.complete_evaluations,
        "budget_closed": counter.complete_evaluations == budget,
        "cheap_direct_checks": 3,
        "regret_rank_calls": 1,
        "regret_selected": selected,
        "regret_values": regrets,
        "direct_insertion_feasible": False,
        "ejection_candidates_evaluated": len(evaluated),
        "accepted_candidate_count": len(accepted_depths),
        "accepted_ejection_depths": accepted_depths,
        "bounded_depth_two_active": 2 in accepted_depths,
        "evaluated": evaluated,
    }


def _levenshtein(sequence_a: Sequence[str], sequence_b: Sequence[str]) -> int:
    previous = list(range(len(sequence_b) + 1))
    for index_a, item_a in enumerate(sequence_a, start=1):
        current = [index_a]
        for index_b, item_b in enumerate(sequence_b, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[index_b] + 1,
                    previous[index_b - 1] + (item_a != item_b),
                )
            )
        previous = current
    return previous[-1]


def route_stability_metrics(
    before: Mapping[str, Sequence[str]],
    after: Mapping[str, Sequence[str]],
    frozen_prefix_lengths: Mapping[str, int],
) -> dict[str, int]:
    """Compute future-only route-stability metrics by physical vehicle."""
    assert_frozen_prefixes(
        after,
        {
            vehicle_id: tuple(before[vehicle_id])[:prefix_length]
            for vehicle_id, prefix_length in frozen_prefix_lengths.items()
        },
    )

    before_locations: dict[str, tuple[str, int]] = {}
    after_locations: dict[str, tuple[str, int]] = {}
    before_edges: set[tuple[str, str, str]] = set()
    after_edges: set[tuple[str, str, str]] = set()
    edit_distance = 0

    for vehicle_id, prefix_length in frozen_prefix_lengths.items():
        before_route = tuple(before[vehicle_id])
        after_route = tuple(after[vehicle_id])
        before_suffix = before_route[prefix_length:]
        after_suffix = after_route[prefix_length:]
        for index, customer in enumerate(before_suffix):
            before_locations[customer] = (vehicle_id, index)
        for index, customer in enumerate(after_suffix):
            after_locations[customer] = (vehicle_id, index)

        before_chain = before_route[prefix_length - 1 :]
        after_chain = after_route[prefix_length - 1 :]
        before_edges.update(
            (vehicle_id, left, right)
            for left, right in zip(before_chain, before_chain[1:], strict=False)
        )
        after_edges.update(
            (vehicle_id, left, right)
            for left, right in zip(after_chain, after_chain[1:], strict=False)
        )
        edit_distance += _levenshtein(before_suffix, after_suffix)

    if set(before_locations) != set(after_locations):
        raise ProbeContractError("future customer sets differ")

    vehicle_changes = sum(
        before_locations[customer][0] != after_locations[customer][0]
        for customer in before_locations
    )
    route_position_changes = sum(
        before_locations[customer] != after_locations[customer]
        for customer in before_locations
    )
    return {
        "customer_vehicle_changes": vehicle_changes,
        "future_edge_symmetric_difference": len(before_edges ^ after_edges),
        "future_route_position_changes": route_position_changes,
        "future_levenshtein_distance": edit_distance,
    }


def independent_route_stability_oracle(
    before: Mapping[str, Sequence[str]],
    after: Mapping[str, Sequence[str]],
    frozen_prefix_lengths: Mapping[str, int],
) -> dict[str, int]:
    """Independently recompute the same metrics without shared helpers."""

    def recursive_edit(left: tuple[str, ...], right: tuple[str, ...]) -> int:
        memo: dict[tuple[int, int], int] = {}

        def solve(i: int, j: int) -> int:
            if (i, j) in memo:
                return memo[(i, j)]
            if i == len(left):
                return len(right) - j
            if j == len(right):
                return len(left) - i
            value = min(
                1 + solve(i + 1, j),
                1 + solve(i, j + 1),
                (left[i] != right[j]) + solve(i + 1, j + 1),
            )
            memo[(i, j)] = value
            return value

        return solve(0, 0)

    old_place: dict[str, tuple[str, int]] = {}
    new_place: dict[str, tuple[str, int]] = {}
    old_arcs: list[tuple[str, str, str]] = []
    new_arcs: list[tuple[str, str, str]] = []
    total_edit = 0
    for vehicle_id in sorted(frozen_prefix_lengths):
        cut = frozen_prefix_lengths[vehicle_id]
        old_route = list(before[vehicle_id])
        new_route = list(after[vehicle_id])
        if old_route[:cut] != new_route[:cut]:
            raise ProbeContractError("independent oracle detected frozen-prefix change")
        old_future = tuple(old_route[cut:])
        new_future = tuple(new_route[cut:])
        for position, customer in enumerate(old_future):
            old_place[customer] = (vehicle_id, position)
        for position, customer in enumerate(new_future):
            new_place[customer] = (vehicle_id, position)
        for position in range(cut - 1, len(old_route) - 1):
            old_arcs.append((vehicle_id, old_route[position], old_route[position + 1]))
        for position in range(cut - 1, len(new_route) - 1):
            new_arcs.append((vehicle_id, new_route[position], new_route[position + 1]))
        total_edit += recursive_edit(old_future, new_future)

    if sorted(old_place) != sorted(new_place):
        raise ProbeContractError("independent oracle detected customer-set change")
    changed_vehicle = 0
    changed_place = 0
    for customer in old_place:
        if old_place[customer][0] != new_place[customer][0]:
            changed_vehicle += 1
        if old_place[customer] != new_place[customer]:
            changed_place += 1

    return {
        "customer_vehicle_changes": changed_vehicle,
        "future_edge_symmetric_difference": len(set(old_arcs) ^ set(new_arcs)),
        "future_route_position_changes": changed_place,
        "future_levenshtein_distance": total_edit,
    }


def build_hand_checkable_stability_case() -> tuple[
    dict[str, tuple[str, ...]],
    dict[str, tuple[str, ...]],
    dict[str, int],
]:
    before = {"V1": ("F1", "A", "B", "C"), "V2": ("F2", "D", "E")}
    after = {"V1": ("F1", "A", "E", "C"), "V2": ("F2", "D", "B")}
    return before, after, {"V1": 1, "V2": 1}
