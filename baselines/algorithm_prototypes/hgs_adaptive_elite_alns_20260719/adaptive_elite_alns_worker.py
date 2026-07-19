#!/usr/bin/env python3
"""Run PyVRP HGS with a bounded, stagnation-triggered elite-guided ALNS search."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib.metadata
import importlib.util
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Iterable

import numpy as np
from pyvrp import Solution
from pyvrp.GeneticAlgorithm import GeneticAlgorithm
from pyvrp.PenaltyManager import PenaltyManager
from pyvrp.Population import Population
from pyvrp._pyvrp import RandomNumberGenerator
from pyvrp.crossover import selective_route_exchange
from pyvrp.diversity import broken_pairs_distance
from pyvrp.search import (
    NODE_OPERATORS,
    ROUTE_OPERATORS,
    LocalSearch,
    compute_neighbours,
)
from pyvrp.solve import SolveParams
from pyvrp.stop import MaxRuntime


REPO = Path(__file__).resolve().parents[3]
BASE_WORKER_PATH = (
    REPO
    / "baselines/algorithm_prototypes/algo_reset_20260719/"
    "run_pyvrp_route_core_worker.py"
)
SPEC = importlib.util.spec_from_file_location(
    "hgs_adaptive_elite_base_worker",
    BASE_WORKER_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {BASE_WORKER_PATH}")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)


EdgeSet = frozenset[tuple[int, int]]


def _edge(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a <= b else (b, a)


def edge_signature(routes: Iterable[Iterable[int]]) -> EdgeSet:
    edges: set[tuple[int, int]] = set()
    for route in routes:
        sequence = [0, *[int(value) for value in route], 0]
        edges.update(
            _edge(first, second)
            for first, second in zip(sequence, sequence[1:])
        )
    return frozenset(edges)


def customer_neighbours(
    routes: Iterable[Iterable[int]],
) -> dict[int, frozenset[int]]:
    result: dict[int, frozenset[int]] = {}
    for route in routes:
        sequence = [0, *[int(value) for value in route], 0]
        for index in range(1, len(sequence) - 1):
            result[sequence[index]] = frozenset(
                (sequence[index - 1], sequence[index + 1])
            )
    return result


def partition_is_complete(
    routes: Iterable[Iterable[int]],
    customer_count: int,
) -> bool:
    visits = [int(value) for route in routes for value in route]
    return (
        len(visits) == customer_count
        and len(set(visits)) == customer_count
        and set(visits) == set(range(1, customer_count + 1))
    )


def _route_load(route: Iterable[int], demands: np.ndarray) -> int:
    return int(sum(int(demands[int(customer)]) for customer in route))


def _insertion_options(
    customer: int,
    routes: list[list[int]],
    *,
    demands: np.ndarray,
    capacity: int,
    max_routes: int,
    distances: np.ndarray,
    reference_edges: EdgeSet,
    mode: str,
    allow_new_route: bool,
) -> list[tuple[tuple[int, ...], int, int, int, int]]:
    options: list[tuple[tuple[int, ...], int, int, int, int]] = []
    for route_index, route in enumerate(routes):
        if _route_load(route, demands) + int(demands[customer]) > capacity:
            continue
        for position in range(len(route) + 1):
            predecessor = 0 if position == 0 else int(route[position - 1])
            successor = 0 if position == len(route) else int(route[position])
            delta = int(
                distances[predecessor, customer]
                + distances[customer, successor]
                - distances[predecessor, successor]
            )
            matches = int(_edge(predecessor, customer) in reference_edges)
            matches += int(_edge(customer, successor) in reference_edges)
            key = (
                (delta, -matches, route_index, position)
                if mode == "cost"
                else (-matches, delta, route_index, position)
            )
            options.append(
                (tuple(int(value) for value in key), delta, matches, route_index, position)
            )

    if allow_new_route and len(routes) < max_routes:
        delta = int(distances[0, customer] + distances[customer, 0])
        matches = int(_edge(0, customer) in reference_edges) * 2
        route_index = len(routes)
        key = (
            (delta, -matches, route_index, 0)
            if mode == "cost"
            else (-matches, delta, route_index, 0)
        )
        options.append(
            (tuple(int(value) for value in key), delta, matches, route_index, 0)
        )
    return sorted(options, key=lambda item: item[0])


def regret_repair(
    routes: list[list[int]],
    removed: Iterable[int],
    *,
    demands: np.ndarray,
    capacity: int,
    max_routes: int,
    distances: np.ndarray,
    reference_edges: EdgeSet,
    mode: str,
    allow_new_route: bool,
) -> list[list[int]]:
    if mode not in {"cost", "elite"}:
        raise ValueError(f"unknown repair mode: {mode}")
    repaired = [list(route) for route in routes if route]
    unassigned = [int(value) for value in removed]
    while unassigned:
        choice: tuple[tuple[int, ...], int, int, int] | None = None
        for customer in unassigned:
            options = _insertion_options(
                customer,
                repaired,
                demands=demands,
                capacity=capacity,
                max_routes=max_routes,
                distances=distances,
                reference_edges=reference_edges,
                mode=mode,
                allow_new_route=allow_new_route,
            )
            if not options:
                continue
            best = options[0]
            second = options[1] if len(options) > 1 else best
            if mode == "cost":
                priority = (
                    int(second[1] - best[1]),
                    int(best[2]),
                    -int(best[1]),
                    -customer,
                )
            else:
                priority = (
                    int(best[2] - second[2]),
                    int(second[1] - best[1]),
                    int(best[2]),
                    -int(best[1]),
                    -customer,
                )
            candidate = (priority, customer, int(best[3]), int(best[4]))
            if choice is None or candidate[0] > choice[0]:
                choice = candidate
        if choice is None:
            return []
        _, customer, route_index, position = choice
        if route_index == len(repaired):
            repaired.append([customer])
        else:
            repaired[route_index].insert(position, customer)
        unassigned.remove(customer)
    return repaired


@dataclass(frozen=True)
class EliteEntry:
    cost: int
    solution: Any
    routes: tuple[tuple[int, ...], ...]
    edges: EdgeSet


class AdaptiveEliteALNSSearch:
    """HGS local search plus bounded ALNS at evidence-based stagnation points."""

    def __init__(
        self,
        base_search: Any,
        *,
        data: Any,
        seed: int,
        gamma: int = 30,
        d_max: int = 30,
        d_min: int = 15,
        archive_size: int = 8,
        max_string_size: int = 12,
        max_source_routes: int = 2,
    ):
        self.base_search = base_search
        self.data = data
        self.rng = np.random.default_rng(seed)
        self.gamma = int(gamma)
        self.d_max = int(d_max)
        self.d_min = int(d_min)
        self.archive_size = int(archive_size)
        self.max_string_size = int(max_string_size)
        self.max_source_routes = int(max_source_routes)
        self.customer_count = len(data.clients())
        self.distances = np.asarray(data.distance_matrix(0), dtype=np.int64)
        self.demands = np.asarray(
            [0, *[int(client.delivery[0]) for client in data.clients()]],
            dtype=np.int64,
        )
        self.capacity = int(data.vehicle_type(0).capacity[0])
        self.max_routes = int(data.num_vehicles)
        self.capacity_lower_bound = int(
            math.ceil(float(self.demands.sum()) / float(self.capacity))
        )
        self.archive: list[EliteEntry] = []
        self.best_cost: int | None = None
        self.stagnation = 0
        self.current_q = max(
            self.d_min,
            min(self.d_max, self.customer_count),
        )
        self.calls = 0
        self.triggers = 0
        self.accepted = 0
        self.route_reduction_attempts = 0
        self.route_reduction_accepts = 0
        self.removed_customers = 0
        self.education_seconds = 0.0
        self.edge_distance_sum = 0
        self.mode_calls = {
            "elite_disagreement": 0,
            "weak_route_elimination": 0,
            "cost_repair": 0,
            "elite_repair": 0,
        }

    def _remember(self, solution: Any, cost: int) -> None:
        routes = tuple(
            tuple(int(value) for value in route)
            for route in BASE.routes_from(solution)
        )
        edges = edge_signature(routes)
        entry = EliteEntry(int(cost), solution, routes, edges)
        for index, existing in enumerate(self.archive):
            if existing.edges == edges:
                if entry.cost < existing.cost:
                    self.archive[index] = entry
                break
        else:
            self.archive.append(entry)
        self.archive.sort(key=lambda item: (item.cost, item.routes))
        self.archive = self.archive[: self.archive_size]

    def _reference(self, edges: EdgeSet) -> EliteEntry | None:
        choices = [
            entry
            for entry in self.archive
            if entry.edges != edges
        ]
        if not choices:
            return None
        return max(
            choices,
            key=lambda entry: (
                len(edges.symmetric_difference(entry.edges)),
                -entry.cost,
            ),
        )

    def _remove_disagreement(
        self,
        routes: list[list[int]],
        reference: EliteEntry,
    ) -> tuple[list[list[int]], list[int]]:
        current_neighbours = customer_neighbours(routes)
        reference_neighbours = customer_neighbours(reference.routes)
        ranked = []
        for customer in range(1, self.customer_count + 1):
            shared = len(
                current_neighbours.get(customer, frozenset())
                & reference_neighbours.get(customer, frozenset())
            )
            ranked.append(
                (
                    2 - shared,
                    float(self.rng.random()),
                    customer,
                )
            )
        ranked.sort(reverse=True)
        removed: set[int] = set()
        touched_routes: set[int] = set()
        target = min(self.current_q, self.customer_count)
        for _, _, center in ranked:
            if center in removed:
                continue
            route_index = next(
                (
                    index
                    for index, route in enumerate(routes)
                    if center in route
                ),
                None,
            )
            if route_index is None:
                continue
            if (
                route_index not in touched_routes
                and len(touched_routes) >= self.max_source_routes
            ):
                continue
            route = routes[route_index]
            center_index = route.index(center)
            remaining = target - len(removed)
            size = min(self.max_string_size, remaining, len(route))
            if size <= 0:
                break
            left = max(0, center_index - size // 2)
            right = min(len(route), left + size)
            left = max(0, right - size)
            removed.update(int(value) for value in route[left:right])
            touched_routes.add(route_index)
            if len(removed) >= target:
                break
        survivors = [
            [customer for customer in route if customer not in removed]
            for route in routes
        ]
        return [route for route in survivors if route], sorted(removed)

    def _remove_weak_route(
        self,
        routes: list[list[int]],
    ) -> tuple[list[list[int]], list[int]]:
        if len(routes) <= self.capacity_lower_bound:
            return routes, []
        route_index = min(
            range(len(routes)),
            key=lambda index: (
                _route_load(routes[index], self.demands),
                len(routes[index]),
                tuple(routes[index]),
            ),
        )
        removed = list(routes[route_index])
        survivors = [
            list(route)
            for index, route in enumerate(routes)
            if index != route_index
        ]
        return survivors, removed

    def __call__(self, solution: Any, cost_evaluator: Any) -> Any:
        improved = self.base_search(solution, cost_evaluator)
        self.calls += 1
        cost = int(cost_evaluator.penalised_cost(improved))
        self._remember(improved, cost)
        if self.best_cost is None or cost < self.best_cost:
            self.best_cost = cost
            self.stagnation = 0
        else:
            self.stagnation += 1

        if (
            self.stagnation < self.gamma
            or self.calls % self.gamma != 0
        ):
            return improved

        routes = [list(route) for route in BASE.routes_from(improved)]
        edges = edge_signature(routes)
        reference = self._reference(edges)
        if reference is None:
            return improved

        started = time.perf_counter()
        self.triggers += 1
        use_route_elimination = (
            self.triggers % 3 == 0
            and len(routes) > self.capacity_lower_bound
        )
        if use_route_elimination:
            self.route_reduction_attempts += 1
            self.mode_calls["weak_route_elimination"] += 1
            survivors, removed = self._remove_weak_route(routes)
        else:
            self.mode_calls["elite_disagreement"] += 1
            survivors, removed = self._remove_disagreement(
                routes,
                reference,
            )
        if not removed:
            self.education_seconds += time.perf_counter() - started
            return improved

        repair_mode = "elite" if self.triggers % 2 else "cost"
        self.mode_calls[f"{repair_mode}_repair"] += 1
        repaired = regret_repair(
            survivors,
            removed,
            demands=self.demands,
            capacity=self.capacity,
            max_routes=self.max_routes,
            distances=self.distances,
            reference_edges=reference.edges,
            mode=repair_mode,
            allow_new_route=not use_route_elimination,
        )
        self.removed_customers += len(removed)
        if not partition_is_complete(repaired, self.customer_count):
            self.education_seconds += time.perf_counter() - started
            return improved

        candidate = Solution(self.data, repaired)
        candidate = self.base_search(candidate, cost_evaluator)
        candidate_cost = int(cost_evaluator.penalised_cost(candidate))
        observed_distance = len(
            edges.symmetric_difference(
                edge_signature(BASE.routes_from(candidate))
            )
        ) // 2
        self.edge_distance_sum += observed_distance
        target = max(
            self.d_min,
            self.d_max - self.triggers // 4,
        )
        if observed_distance < target:
            self.current_q = min(self.d_max, self.current_q + 1)
        elif observed_distance > target:
            self.current_q = max(self.d_min, self.current_q - 1)

        if candidate_cost < cost:
            self.accepted += 1
            if len(BASE.routes_from(candidate)) < len(routes):
                self.route_reduction_accepts += 1
            self._remember(candidate, candidate_cost)
            self.best_cost = min(
                candidate_cost,
                self.best_cost if self.best_cost is not None else candidate_cost,
            )
            self.stagnation = 0
            self.education_seconds += time.perf_counter() - started
            return candidate

        self.education_seconds += time.perf_counter() - started
        return improved

    def diagnostics(self) -> dict[str, Any]:
        return {
            "education_calls": self.calls,
            "education_triggers": self.triggers,
            "education_accepted": self.accepted,
            "route_reduction_attempts": self.route_reduction_attempts,
            "route_reduction_accepts": self.route_reduction_accepts,
            "removed_customers": self.removed_customers,
            "education_seconds": self.education_seconds,
            "edge_distance_sum": self.edge_distance_sum,
            "final_q": self.current_q,
            "archive_size": len(self.archive),
            "mode_calls": self.mode_calls,
            "gamma": self.gamma,
            "d_max": self.d_max,
            "d_min": self.d_min,
        }


def _read_routes(path: Path) -> list[list[int]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        [int(value) for value in route]
        for route in payload["routes"]
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--scale", type=int, default=1000)
    parser.add_argument("--fixed-cost", type=int, required=True)
    parser.add_argument("--initial-routes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if importlib.metadata.version("pyvrp") != "0.12.2":
        raise RuntimeError("HGS-AEALNS-03 is frozen for PyVRP 0.12.2")
    model = BASE.build_model(args.bundle, args.scale, args.fixed_cost)
    data = model.data()
    initial_routes = _read_routes(args.initial_routes)
    initial = Solution(data, initial_routes)
    if not initial.is_feasible():
        raise RuntimeError("common initial solution must be feasible")

    params = SolveParams()
    rng = RandomNumberGenerator(seed=args.seed)
    neighbours = compute_neighbours(data, params.neighbourhood)
    local_search = LocalSearch(data, rng, neighbours)
    for operator in params.node_ops or NODE_OPERATORS:
        if operator.supports(data):
            local_search.add_node_operator(operator(data))
    for operator in params.route_ops or ROUTE_OPERATORS:
        if operator.supports(data):
            local_search.add_route_operator(operator(data))
    adaptive_search = AdaptiveEliteALNSSearch(
        local_search,
        data=data,
        seed=args.seed,
    )
    penalty_manager = PenaltyManager.init_from(data, params.penalty)
    population = Population(broken_pairs_distance, params.population)
    initial_solutions = [initial]
    initial_solutions.extend(
        Solution.make_random(data, rng)
        for _ in range(max(0, params.population.min_pop_size - 1))
    )
    algorithm = GeneticAlgorithm(
        data,
        penalty_manager,
        rng,
        population,
        adaptive_search,
        selective_route_exchange,
        initial_solutions,
        params.genetic,
    )
    started = time.perf_counter()
    result = algorithm.run(
        MaxRuntime(args.seconds),
        collect_stats=True,
        display=False,
        display_interval=params.display_interval,
    )
    payload = {
        "algorithm": "hgs_adaptive_elite_alns_03",
        "pyvrp_version": importlib.metadata.version("pyvrp"),
        "seed": args.seed,
        "time_limit_seconds": args.seconds,
        "elapsed_seconds": time.perf_counter() - started,
        "feasible": bool(result.best.is_feasible()),
        "scaled_cost": (
            int(result.cost())
            if math.isfinite(float(result.cost()))
            else None
        ),
        "routes": BASE.routes_from(result.best),
        "initial_solution_count": len(initial_solutions),
        "education": adaptive_search.diagnostics(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return 0 if payload["feasible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

