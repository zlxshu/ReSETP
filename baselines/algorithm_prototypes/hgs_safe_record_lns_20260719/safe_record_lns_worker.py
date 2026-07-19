#!/usr/bin/env python3
"""Run PyVRP HGS with a feasibility-safe, record-only LNS educator."""

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
from pyvrp import Route as PyVRPRoute
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
PREDECESSOR_PATH = (
    REPO
    / "baselines/algorithm_prototypes/hgs_adaptive_elite_alns_20260719/"
    "adaptive_elite_alns_worker.py"
)
SPEC = importlib.util.spec_from_file_location(
    "hgs_safe_record_predecessor",
    PREDECESSOR_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {PREDECESSOR_PATH}")
PREDECESSOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREDECESSOR
SPEC.loader.exec_module(PREDECESSOR)
BASE = PREDECESSOR.BASE


EdgeSet = PREDECESSOR.EdgeSet
edge_signature = PREDECESSOR.edge_signature
customer_neighbours = PREDECESSOR.customer_neighbours
partition_is_complete = PREDECESSOR.partition_is_complete


@dataclass(frozen=True)
class SafeInsertion:
    sort_key: tuple[int, ...]
    objective_delta: int
    distance_delta: int
    matches: int
    route_index: int
    position: int
    route_delta: int


@dataclass
class SafeInsertionStats:
    positions_considered: int = 0
    capacity_filtered: int = 0
    time_window_filtered: int = 0
    feasible_options: int = 0
    new_route_options: int = 0
    fixed_cost_charged: int = 0

    def payload(self) -> dict[str, int]:
        return {
            "positions_considered": self.positions_considered,
            "capacity_filtered": self.capacity_filtered,
            "time_window_filtered": self.time_window_filtered,
            "feasible_options": self.feasible_options,
            "new_route_options": self.new_route_options,
            "fixed_cost_charged": self.fixed_cost_charged,
        }


def _route_load(route: Iterable[int], demands: np.ndarray) -> int:
    return int(sum(int(demands[int(customer)]) for customer in route))


def route_is_feasible(data: Any, route: Iterable[int]) -> bool:
    return bool(PyVRPRoute(data, list(route), 0).is_feasible())


def solution_key(solution: Any) -> tuple[int, int]:
    return int(solution.num_routes()), int(solution.distance())


def is_record_improvement(
    candidate_key: tuple[int, int],
    current_key: tuple[int, int],
    best_key: tuple[int, int],
) -> bool:
    return candidate_key < current_key and candidate_key < best_key


def safe_insertion_options(
    customer: int,
    routes: list[list[int]],
    *,
    data: Any,
    demands: np.ndarray,
    capacity: int,
    max_routes: int,
    reference_edges: EdgeSet,
    mode: str,
    allow_new_route: bool,
    stats: SafeInsertionStats,
) -> list[SafeInsertion]:
    if mode not in {"cost", "elite"}:
        raise ValueError(f"unknown repair mode: {mode}")
    fixed_cost = int(data.vehicle_type(0).fixed_cost)
    options: list[SafeInsertion] = []
    for route_index, route in enumerate(routes):
        before = PyVRPRoute(data, route, 0)
        for position in range(len(route) + 1):
            stats.positions_considered += 1
            if (
                _route_load(route, demands)
                + int(demands[customer])
                > capacity
            ):
                stats.capacity_filtered += 1
                continue
            trial = [*route[:position], customer, *route[position:]]
            after = PyVRPRoute(data, trial, 0)
            if not after.is_feasible():
                stats.time_window_filtered += 1
                continue
            predecessor = 0 if position == 0 else int(route[position - 1])
            successor = (
                0 if position == len(route) else int(route[position])
            )
            matches = int(
                PREDECESSOR._edge(predecessor, customer)
                in reference_edges
            )
            matches += int(
                PREDECESSOR._edge(customer, successor)
                in reference_edges
            )
            distance_delta = int(after.distance() - before.distance())
            objective_delta = distance_delta
            key = (
                (0, objective_delta, -matches, route_index, position)
                if mode == "cost"
                else (0, -matches, objective_delta, route_index, position)
            )
            options.append(
                SafeInsertion(
                    tuple(int(value) for value in key),
                    objective_delta,
                    distance_delta,
                    matches,
                    route_index,
                    position,
                    0,
                )
            )
            stats.feasible_options += 1

    if allow_new_route and len(routes) < max_routes:
        stats.positions_considered += 1
        trial = PyVRPRoute(data, [customer], 0)
        if trial.is_feasible():
            distance_delta = int(trial.distance())
            objective_delta = fixed_cost + distance_delta
            matches = int(
                PREDECESSOR._edge(0, customer) in reference_edges
            ) * 2
            route_index = len(routes)
            key = (
                (1, objective_delta, -matches, route_index, 0)
                if mode == "cost"
                else (1, -matches, objective_delta, route_index, 0)
            )
            options.append(
                SafeInsertion(
                    tuple(int(value) for value in key),
                    objective_delta,
                    distance_delta,
                    matches,
                    route_index,
                    0,
                    1,
                )
            )
            stats.feasible_options += 1
            stats.new_route_options += 1
            stats.fixed_cost_charged += fixed_cost
        else:
            stats.time_window_filtered += 1
    return sorted(options, key=lambda item: item.sort_key)


def safe_regret_repair(
    routes: list[list[int]],
    removed: Iterable[int],
    *,
    data: Any,
    demands: np.ndarray,
    capacity: int,
    max_routes: int,
    reference_edges: EdgeSet,
    mode: str,
    allow_new_route: bool,
    stats: SafeInsertionStats,
) -> list[list[int]]:
    repaired = [list(route) for route in routes if route]
    if (
        len(repaired) > max_routes
        or any(not route_is_feasible(data, route) for route in repaired)
    ):
        return []
    unassigned = [int(value) for value in removed]
    while unassigned:
        choice: tuple[tuple[int, ...], int, int, int] | None = None
        for customer in unassigned:
            options = safe_insertion_options(
                customer,
                repaired,
                data=data,
                demands=demands,
                capacity=capacity,
                max_routes=max_routes,
                reference_edges=reference_edges,
                mode=mode,
                allow_new_route=allow_new_route,
                stats=stats,
            )
            if not options:
                continue
            best = options[0]
            second = options[1] if len(options) > 1 else best
            regret = int(second.objective_delta - best.objective_delta)
            priority = (
                regret,
                -best.route_delta,
                best.matches,
                -best.objective_delta,
                -customer,
            )
            candidate = (
                priority,
                customer,
                best.route_index,
                best.position,
            )
            if choice is None or candidate[0] > choice[0]:
                choice = candidate
        if choice is None:
            return []
        _, customer, route_index, position = choice
        if route_index == len(repaired):
            repaired.append([customer])
        else:
            repaired[route_index].insert(position, customer)
        if (
            len(repaired) > max_routes
            or not route_is_feasible(data, repaired[route_index])
        ):
            return []
        unassigned.remove(customer)
    return repaired


@dataclass(frozen=True)
class SafeEliteEntry:
    key: tuple[int, int]
    routes: tuple[tuple[int, ...], ...]
    edges: EdgeSet


class SafeRecordLNS:
    """Return an LNS child only when it is a new feasible global record."""

    def __init__(
        self,
        base_search: Any,
        candidate_search: Any,
        *,
        data: Any,
        seed: int,
        enabled: bool = True,
        gamma: int = 30,
        d_max: int = 30,
        d_min: int = 15,
        archive_size: int = 8,
        max_string_size: int = 12,
        max_source_routes: int = 2,
    ):
        self.base_search = base_search
        self.candidate_search = candidate_search
        self.data = data
        self.enabled = bool(enabled)
        self.rng = np.random.default_rng(seed + 104729)
        self.gamma = int(gamma)
        self.d_max = int(d_max)
        self.d_min = int(d_min)
        self.archive_size = int(archive_size)
        self.max_string_size = int(max_string_size)
        self.max_source_routes = int(max_source_routes)
        self.customer_count = len(data.clients())
        self.demands = np.asarray(
            [0, *[int(client.delivery[0]) for client in data.clients()]],
            dtype=np.int64,
        )
        self.capacity = int(data.vehicle_type(0).capacity[0])
        self.capacity_lower_bound = int(
            math.ceil(float(self.demands.sum()) / float(self.capacity))
        )
        self.archive: list[SafeEliteEntry] = []
        self.best_key: tuple[int, int] | None = None
        self.stagnation = 0
        self.current_q = max(
            self.d_min,
            min(self.d_max, self.customer_count),
        )
        self.calls = 0
        self.feasible_calls = 0
        self.infeasible_base_returns = 0
        self.triggers = 0
        self.accepted_records = 0
        self.repair_failures = 0
        self.pre_local_infeasible = 0
        self.post_local_infeasible = 0
        self.not_record_rejections = 0
        self.route_guard_rejections = 0
        self.route_reduction_attempts = 0
        self.route_reduction_accepts = 0
        self.removed_customers = 0
        self.education_seconds = 0.0
        self.insertion_stats = SafeInsertionStats()
        self.mode_calls = {
            "elite_disagreement": 0,
            "weak_route_elimination": 0,
            "cost_repair": 0,
            "elite_repair": 0,
        }

    def _remember(self, solution: Any) -> None:
        if not solution.is_feasible():
            return
        routes = tuple(
            tuple(int(value) for value in route)
            for route in BASE.routes_from(solution)
        )
        entry = SafeEliteEntry(
            solution_key(solution),
            routes,
            edge_signature(routes),
        )
        for index, existing in enumerate(self.archive):
            if existing.edges == entry.edges:
                if entry.key < existing.key:
                    self.archive[index] = entry
                break
        else:
            self.archive.append(entry)
        self.archive.sort(key=lambda item: (item.key, item.routes))
        self.archive = self.archive[: self.archive_size]

    def _reference(self, edges: EdgeSet) -> SafeEliteEntry | None:
        choices = [
            entry for entry in self.archive if entry.edges != edges
        ]
        if not choices:
            return None
        return max(
            choices,
            key=lambda entry: (
                len(edges.symmetric_difference(entry.edges)),
                -entry.key[0],
                -entry.key[1],
            ),
        )

    def _remove_disagreement(
        self,
        routes: list[list[int]],
        reference: SafeEliteEntry,
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
                (2 - shared, float(self.rng.random()), customer)
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
        return (
            [
                list(route)
                for index, route in enumerate(routes)
                if index != route_index
            ],
            list(routes[route_index]),
        )

    def __call__(self, solution: Any, cost_evaluator: Any) -> Any:
        improved = self.base_search(solution, cost_evaluator)
        self.calls += 1
        if not self.enabled:
            return improved
        if not improved.is_feasible():
            self.infeasible_base_returns += 1
            return improved

        self.feasible_calls += 1
        current_key = solution_key(improved)
        is_new_record = (
            self.best_key is None or current_key < self.best_key
        )
        if is_new_record:
            self.best_key = current_key
            self.stagnation = 0
        else:
            self.stagnation += 1
        self._remember(improved)
        if (
            self.stagnation < self.gamma
            or self.feasible_calls % self.gamma != 0
        ):
            return improved

        routes = [list(route) for route in BASE.routes_from(improved)]
        reference = self._reference(edge_signature(routes))
        if reference is None or self.best_key is None:
            return improved

        started = time.perf_counter()
        self.triggers += 1
        original_route_count = len(routes)
        use_route_elimination = (
            self.triggers % 3 == 0
            and original_route_count > self.capacity_lower_bound
        )
        if use_route_elimination:
            self.route_reduction_attempts += 1
            self.mode_calls["weak_route_elimination"] += 1
            survivors, removed = self._remove_weak_route(routes)
            max_routes = original_route_count - 1
        else:
            self.mode_calls["elite_disagreement"] += 1
            survivors, removed = self._remove_disagreement(
                routes,
                reference,
            )
            max_routes = original_route_count
        if not removed:
            self.education_seconds += time.perf_counter() - started
            return improved

        repair_mode = "elite" if self.triggers % 2 else "cost"
        self.mode_calls[f"{repair_mode}_repair"] += 1
        repaired = safe_regret_repair(
            survivors,
            removed,
            data=self.data,
            demands=self.demands,
            capacity=self.capacity,
            max_routes=max_routes,
            reference_edges=reference.edges,
            mode=repair_mode,
            allow_new_route=True,
            stats=self.insertion_stats,
        )
        self.removed_customers += len(removed)
        if not repaired or not partition_is_complete(
            repaired,
            self.customer_count,
        ):
            self.repair_failures += 1
            self.education_seconds += time.perf_counter() - started
            return improved
        if len(repaired) > max_routes:
            self.route_guard_rejections += 1
            self.education_seconds += time.perf_counter() - started
            return improved

        candidate = Solution(self.data, repaired)
        if not candidate.is_feasible():
            self.pre_local_infeasible += 1
            self.education_seconds += time.perf_counter() - started
            return improved
        candidate = self.candidate_search(candidate, cost_evaluator)
        if not candidate.is_feasible():
            self.post_local_infeasible += 1
            self.education_seconds += time.perf_counter() - started
            return improved

        candidate_key = solution_key(candidate)
        if use_route_elimination and candidate_key[0] >= current_key[0]:
            self.route_guard_rejections += 1
            self.education_seconds += time.perf_counter() - started
            return improved
        if not is_record_improvement(
            candidate_key,
            current_key,
            self.best_key,
        ):
            self.not_record_rejections += 1
            self.education_seconds += time.perf_counter() - started
            return improved

        self.accepted_records += 1
        if candidate_key[0] < current_key[0]:
            self.route_reduction_accepts += 1
        self.best_key = candidate_key
        self.stagnation = 0
        self._remember(candidate)
        self.education_seconds += time.perf_counter() - started
        return candidate

    def diagnostics(self) -> dict[str, Any]:
        return {
            "education_calls": self.calls,
            "feasible_base_calls": self.feasible_calls,
            "infeasible_base_returns": self.infeasible_base_returns,
            "education_triggers": self.triggers,
            "accepted_global_records": self.accepted_records,
            "repair_failures": self.repair_failures,
            "pre_local_infeasible": self.pre_local_infeasible,
            "post_local_infeasible": self.post_local_infeasible,
            "not_record_rejections": self.not_record_rejections,
            "route_guard_rejections": self.route_guard_rejections,
            "route_reduction_attempts": self.route_reduction_attempts,
            "route_reduction_accepts": self.route_reduction_accepts,
            "removed_customers": self.removed_customers,
            "education_seconds": self.education_seconds,
            "archive_size": len(self.archive),
            "best_key": list(self.best_key) if self.best_key else None,
            "final_q": self.current_q,
            "mode_calls": self.mode_calls,
            "insertion": self.insertion_stats.payload(),
            "gamma": self.gamma,
            "d_max": self.d_max,
            "d_min": self.d_min,
            "independent_candidate_random_stream": True,
            "feasible_record_only": True,
        }


def _build_local_search(
    data: Any,
    rng: Any,
    params: Any,
) -> Any:
    neighbours = compute_neighbours(data, params.neighbourhood)
    search = LocalSearch(data, rng, neighbours)
    for operator in params.node_ops or NODE_OPERATORS:
        if operator.supports(data):
            search.add_node_operator(operator(data))
    for operator in params.route_ops or ROUTE_OPERATORS:
        if operator.supports(data):
            search.add_route_operator(operator(data))
    return search


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
    parser.add_argument("--disable-enhancement", action="store_true")
    args = parser.parse_args()

    if importlib.metadata.version("pyvrp") != "0.12.2":
        raise RuntimeError("HGS-SAFE-RECORD-LNS-04 requires PyVRP 0.12.2")
    model = BASE.build_model(args.bundle, args.scale, args.fixed_cost)
    data = model.data()
    initial = Solution(data, _read_routes(args.initial_routes))
    if not initial.is_feasible():
        raise RuntimeError("common initial solution must be feasible")

    params = SolveParams()
    core_rng = RandomNumberGenerator(seed=args.seed)
    candidate_rng = RandomNumberGenerator(seed=args.seed + 104729)
    core_search = _build_local_search(data, core_rng, params)
    candidate_search = _build_local_search(data, candidate_rng, params)
    educator = SafeRecordLNS(
        core_search,
        candidate_search,
        data=data,
        seed=args.seed,
        enabled=not args.disable_enhancement,
    )
    penalty_manager = PenaltyManager.init_from(data, params.penalty)
    population = Population(broken_pairs_distance, params.population)
    initial_solutions = [initial]
    initial_solutions.extend(
        Solution.make_random(data, core_rng)
        for _ in range(max(0, params.population.min_pop_size - 1))
    )
    algorithm = GeneticAlgorithm(
        data,
        penalty_manager,
        core_rng,
        population,
        educator,
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
        "algorithm": "hgs_safe_record_lns_04",
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
        "enhancement_enabled": not args.disable_enhancement,
        "education": educator.diagnostics(),
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
