#!/usr/bin/env python3
"""Run one isolated PyVRP route-core task and emit neutral route data."""

from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_HALF_UP
import importlib.metadata
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
from pyvrp import Model, Solution
from pyvrp.stop import MaxRuntime


REPO = Path(__file__).resolve().parents[3]
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    REPO / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def scaled(value: float, scale: int) -> int:
    return int(
        Decimal(str(value * scale)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def build_model(bundle: Path, scale: int, fixed_cost: int) -> Model:
    raw = json.loads((bundle / "instance.json").read_text(encoding="utf-8"))
    nodes = raw["nodes"]
    distances = np.load(bundle / "distance_matrix.npy", allow_pickle=False)
    model = Model()
    new_api = hasattr(model, "add_location")
    clients = []
    if new_api:
        locations = [
            model.add_location(float(node["x"]), float(node["y"]), name=node["node_id"])
            for node in nodes
        ]
        depot = model.add_depot(
            locations[0],
            tw_early=scaled(float(nodes[0]["ready_time"]), scale),
            tw_late=scaled(float(nodes[0]["due_time"]), scale),
            name=nodes[0]["node_id"],
        )
        for index, node in enumerate(nodes[1:], start=1):
            clients.append(
                model.add_client(
                    locations[index],
                    delivery=[int(node["demand"])],
                    service_duration=scaled(float(node["service_time"]), scale),
                    tw_early=scaled(float(node["ready_time"]), scale),
                    tw_late=scaled(float(node["due_time"]), scale),
                    name=node["node_id"],
                )
            )
    else:
        depot = model.add_depot(
            x=float(nodes[0]["x"]),
            y=float(nodes[0]["y"]),
            tw_early=scaled(float(nodes[0]["ready_time"]), scale),
            tw_late=scaled(float(nodes[0]["due_time"]), scale),
            name=nodes[0]["node_id"],
        )
        for node in nodes[1:]:
            clients.append(
                model.add_client(
                    x=float(node["x"]),
                    y=float(node["y"]),
                    delivery=int(node["demand"]),
                    service_duration=scaled(float(node["service_time"]), scale),
                    tw_early=scaled(float(node["ready_time"]), scale),
                    tw_late=scaled(float(node["due_time"]), scale),
                    name=node["node_id"],
                )
            )
        locations = [depot, *clients]
    capacity = (
        [int(raw["metadata"]["vehicle_capacity"])]
        if new_api
        else int(raw["metadata"]["vehicle_capacity"])
    )
    model.add_vehicle_type(
        num_available=int(raw["metadata"]["num_cv"]),
        capacity=capacity,
        start_depot=depot,
        end_depot=depot,
        fixed_cost=int(fixed_cost),
    )
    for source_index, source in enumerate(locations):
        for target_index, target in enumerate(locations):
            value = scaled(float(distances[source_index, target_index]), scale)
            model.add_edge(source, target, distance=value, duration=value)
    return model


def routes_from(solution: object) -> list[list[int]]:
    routes = []
    for route in solution.routes():
        visits = getattr(route, "visits", None)
        if callable(visits):
            routes.append([int(value) for value in visits()])
        else:
            routes.append(
                [
                    int(activity.idx) + 1
                    for activity in route
                    if activity.is_client()
                ]
            )
    return routes


class ProjectALNSEducator:
    """RI -> short project ALNS -> RI, applied to every HGS offspring."""

    def __init__(
        self,
        base_search: object,
        *,
        data: object,
        bundle: Path,
        seed: int,
        evaluations: int,
        fixed_cost: int,
        scale: int,
    ):
        from prototype import run_pure_alns
        from setp_solver.prices import PriceParameters
        from setp_solver.solution import Route, Solution as ProjectSolution

        raw = json.loads((bundle / "instance.json").read_text(encoding="utf-8"))
        self.base_search = base_search
        self.data = data
        self.bundle = bundle
        self.seed = int(seed)
        self.evaluations = int(evaluations)
        self.run_pure_alns = run_pure_alns
        self.Route = Route
        self.ProjectSolution = ProjectSolution
        self.node_ids = [str(node["node_id"]) for node in raw["nodes"]]
        self.node_to_index = {
            node_id: index for index, node_id in enumerate(self.node_ids)
        }
        self.prices = PriceParameters(
            Q_capacity=float(raw["metadata"]["vehicle_capacity"]),
            v_speed_ms=1.0,
            diesel_price=0.0,
            carbon_price=0.0,
            diesel_ef=0.0,
            vehicle_fixed_cost=float(fixed_cost) / float(scale),
            occupancy_fee=0.0,
            cross_site_cost=0.0,
            revenue_per_kg=0.0,
            c_km=1000.0,
        )
        self.calls = 0
        self.accepted = 0
        self.project_evaluations = 0

    def _to_project(self, solution: object) -> object:
        depot = self.node_ids[0]
        return self.ProjectSolution(
            routes=[
                self.Route(
                    f"CV{index}",
                    "cv",
                    depot,
                    [
                        depot,
                        *[self.node_ids[visit] for visit in visits],
                        depot,
                    ],
                )
                for index, visits in enumerate(routes_from(solution), start=1)
            ]
        )

    def _to_pyvrp(self, solution: object) -> Solution:
        routes = [
            [
                self.node_to_index[node_id]
                for node_id in route.node_sequence[1:-1]
            ]
            for route in solution.routes
        ]
        return Solution(self.data, routes)

    def __call__(self, solution: object, cost_evaluator: object) -> object:
        route_improved = self.base_search(solution, cost_evaluator)
        self.calls += 1
        project_initial = self._to_project(route_improved)
        educated = self.run_pure_alns(
            self.bundle,
            seed=self.seed + self.calls * 1009,
            eval_budget=self.evaluations,
            prices=self.prices,
            initial_solution=project_initial,
        )
        self.project_evaluations += int(educated.evaluations)
        candidate = self._to_pyvrp(educated.best_solution)
        candidate = self.base_search(candidate, cost_evaluator)
        if cost_evaluator.cost(candidate) < cost_evaluator.cost(route_improved):
            self.accepted += 1
            return candidate
        return route_improved

    def diagnostics(self) -> dict[str, int]:
        return {
            "education_calls": self.calls,
            "education_accepted": self.accepted,
            "project_alns_complete_evaluations": self.project_evaluations,
        }


class SISRRegretEducator:
    """RI -> sequence removal/regret-2 repair -> RI for each HGS offspring."""

    def __init__(
        self,
        base_search: object,
        *,
        data: object,
        seed: int,
        max_string_size: int = 12,
        max_routes_removed: int = 2,
        interval: int = 1,
    ):
        self.base_search = base_search
        self.data = data
        self.rng = np.random.default_rng(seed)
        self.max_string_size = int(max_string_size)
        self.max_routes_removed = int(max_routes_removed)
        self.interval = max(1, int(interval))
        self.distances = np.asarray(data.distance_matrix(0), dtype=np.int64)
        self.demands = np.asarray(
            [0, *[int(client.delivery[0]) for client in data.clients()]],
            dtype=np.int64,
        )
        self.capacity = int(data.vehicle_type(0).capacity[0])
        self.max_routes = int(data.num_vehicles)
        self.calls = 0
        self.accepted = 0
        self.removed_customers = 0

    def _remove_strings(
        self,
        routes: list[list[int]],
    ) -> tuple[list[list[int]], list[int]]:
        customer_route = {
            customer: route_index
            for route_index, route in enumerate(routes)
            for customer in route
        }
        if not customer_route:
            return routes, []
        center = int(self.rng.choice(list(customer_route)))
        neighbours = np.argsort(self.distances[center])
        selected_routes: list[int] = []
        removed: list[int] = []
        for customer_value in neighbours:
            customer = int(customer_value)
            route_index = customer_route.get(customer)
            if route_index is None or route_index in selected_routes:
                continue
            route = routes[route_index]
            size = int(
                self.rng.integers(
                    1,
                    min(len(route), self.max_string_size) + 1,
                )
            )
            customer_index = route.index(customer)
            start = customer_index - int(self.rng.integers(size))
            indices = sorted(
                {index % len(route) for index in range(start, start + size)},
                reverse=True,
            )
            removed.extend(route.pop(index) for index in indices)
            selected_routes.append(route_index)
            if len(selected_routes) >= min(
                len(routes),
                self.max_routes_removed,
            ):
                break
        return [route for route in routes if route], removed

    def _insertion_options(
        self,
        customer: int,
        routes: list[list[int]],
    ) -> list[tuple[int, int, int]]:
        options: list[tuple[int, int, int]] = []
        for route_index, route in enumerate(routes):
            if int(self.demands[route].sum()) + int(self.demands[customer]) > self.capacity:
                continue
            for position in range(len(route) + 1):
                predecessor = 0 if position == 0 else route[position - 1]
                successor = 0 if position == len(route) else route[position]
                delta = int(
                    self.distances[predecessor, customer]
                    + self.distances[customer, successor]
                    - self.distances[predecessor, successor]
                )
                options.append((delta, route_index, position))
        if len(routes) < self.max_routes and self.demands[customer] <= self.capacity:
            delta = int(
                self.distances[0, customer] + self.distances[customer, 0]
            )
            options.append((delta, len(routes), 0))
        return sorted(options)

    def _regret_repair(
        self,
        routes: list[list[int]],
        removed: list[int],
    ) -> list[list[int]]:
        unassigned = list(removed)
        while unassigned:
            best_choice: tuple[int, int, int, int, int] | None = None
            for customer in unassigned:
                options = self._insertion_options(customer, routes)
                if not options:
                    continue
                best = options[0]
                second_cost = options[1][0] if len(options) > 1 else best[0]
                regret = int(second_cost - best[0])
                choice = (regret, -best[0], customer, best[1], best[2])
                if best_choice is None or choice > best_choice:
                    best_choice = choice
            if best_choice is None:
                return []
            _, _, customer, route_index, position = best_choice
            if route_index == len(routes):
                routes.append([customer])
            else:
                routes[route_index].insert(position, customer)
            unassigned.remove(customer)
        return routes

    def __call__(self, solution: object, cost_evaluator: object) -> object:
        route_improved = self.base_search(solution, cost_evaluator)
        self.calls += 1
        if self.calls % self.interval != 0:
            return route_improved
        routes, removed = self._remove_strings(routes_from(route_improved))
        self.removed_customers += len(removed)
        repaired = self._regret_repair(routes, removed)
        if not repaired:
            return route_improved
        candidate = Solution(self.data, repaired)
        candidate = self.base_search(candidate, cost_evaluator)
        if cost_evaluator.cost(candidate) < cost_evaluator.cost(route_improved):
            self.accepted += 1
            return candidate
        return route_improved

    def diagnostics(self) -> dict[str, int]:
        return {
            "education_calls": self.calls,
            "education_accepted": self.accepted,
            "sequence_removed_customers": self.removed_customers,
        }


def solve_model(
    model: Model,
    *,
    seconds: float,
    seed: int,
    initial_routes: list[list[int]] | None,
    bundle: Path,
    alns_education_evals: int,
    educator_kind: str,
    education_interval: int,
    fixed_cost: int,
    scale: int,
) -> tuple[object, dict[str, int]]:
    if initial_routes is None:
        return model.solve(
            stop=MaxRuntime(seconds),
            seed=seed,
            display=False,
            collect_stats=True,
        ), {}
    data = model.data()
    initial = Solution(data, initial_routes)
    version = importlib.metadata.version("pyvrp")
    if version != "0.12.2":
        return model.solve(
            stop=MaxRuntime(seconds),
            seed=seed,
            display=False,
            collect_stats=True,
            initial_solution=initial,
        ), {}

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

    params = SolveParams()
    rng = RandomNumberGenerator(seed=seed)
    neighbours = compute_neighbours(data, params.neighbourhood)
    local_search = LocalSearch(data, rng, neighbours)
    for operator in params.node_ops or NODE_OPERATORS:
        if operator.supports(data):
            local_search.add_node_operator(operator(data))
    for operator in params.route_ops or ROUTE_OPERATORS:
        if operator.supports(data):
            local_search.add_route_operator(operator(data))
    penalty_manager = PenaltyManager.init_from(data, params.penalty)
    population = Population(broken_pairs_distance, params.population)
    search_method = local_search
    educator = None
    if educator_kind == "project_alns" and alns_education_evals > 0:
        educator = ProjectALNSEducator(
            local_search,
            data=data,
            bundle=bundle,
            seed=seed,
            evaluations=alns_education_evals,
            fixed_cost=fixed_cost,
            scale=scale,
        )
        search_method = educator
    elif educator_kind == "sisr_regret":
        educator = SISRRegretEducator(
            local_search,
            data=data,
            seed=seed,
            interval=education_interval,
        )
        search_method = educator
    random_starts = [
        Solution.make_random(data, rng)
        for _ in range(max(0, params.population.min_pop_size - 1))
    ]
    algorithm = GeneticAlgorithm(
        data,
        penalty_manager,
        rng,
        population,
        search_method,
        selective_route_exchange,
        [initial, *random_starts],
        params.genetic,
    )
    result = algorithm.run(
        MaxRuntime(seconds),
        collect_stats=True,
        display=False,
        display_interval=params.display_interval,
    )
    return result, educator.diagnostics() if educator else {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--scale", type=int, default=1000)
    parser.add_argument("--fixed-cost", type=int, required=True)
    parser.add_argument("--initial-routes", type=Path)
    parser.add_argument("--alns-education-evals", type=int, default=0)
    parser.add_argument(
        "--educator",
        choices=("none", "project_alns", "sisr_regret"),
        default="none",
    )
    parser.add_argument("--education-interval", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    model = build_model(args.bundle, args.scale, args.fixed_cost)
    initial_routes = (
        json.loads(args.initial_routes.read_text(encoding="utf-8"))["routes"]
        if args.initial_routes
        else None
    )
    started = time.perf_counter()
    result, education = solve_model(
        model,
        seconds=args.seconds,
        seed=args.seed,
        initial_routes=initial_routes,
        bundle=args.bundle,
        alns_education_evals=args.alns_education_evals,
        educator_kind=args.educator,
        education_interval=args.education_interval,
        fixed_cost=args.fixed_cost,
        scale=args.scale,
    )
    payload = {
        "pyvrp_version": importlib.metadata.version("pyvrp"),
        "seed": args.seed,
        "time_limit_seconds": args.seconds,
        "initial_route_count": len(initial_routes) if initial_routes else None,
        "elapsed_seconds": time.perf_counter() - started,
        "feasible": bool(result.best.is_feasible()),
        "scaled_cost": (
            int(result.cost()) if math.isfinite(float(result.cost())) else None
        ),
        "routes": routes_from(result.best),
        "education": education,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if payload["feasible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
