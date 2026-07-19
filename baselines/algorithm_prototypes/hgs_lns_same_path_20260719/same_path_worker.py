#!/usr/bin/env python3
"""Run official-reference, HGS, LNS, or hybrid modes through one worker.

Foundation version:
* ``official`` uses the PyVRP 0.12.2 solve-path construction verbatim.
* ``hgs`` uses the same construction with a transparent educator wrapper.
* ``hybrid --disable-enhancement`` uses that exact same wrapper path.
* armed ``lns`` and armed ``hybrid`` deliberately fail closed until the
  literature-backed large-neighbourhood component is frozen.

The fixed-iteration equivalence gate must pass before performance work starts.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import time
from typing import Any

from pyvrp import Solution, read
from pyvrp.GeneticAlgorithm import GeneticAlgorithm
from pyvrp.PenaltyManager import PenaltyManager
from pyvrp.Population import Population
from pyvrp._pyvrp import RandomNumberGenerator
from pyvrp.crossover import ordered_crossover, selective_route_exchange
from pyvrp.diversity import broken_pairs_distance
from pyvrp.search import LocalSearch, compute_neighbours
from pyvrp.solve import SolveParams
from pyvrp.stop import MaxIterations


PYVRP_VERSION = "0.12.2"
ARMED_MODES = {"official", "hgs"}
DECLARED_MODES = {"official", "hgs", "lns", "hybrid"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json_sha(value: Any) -> str:
    return sha256_bytes(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def ordered_routes(solution: Any) -> list[list[int]]:
    return [[int(client) for client in route.visits()] for route in solution.routes()]


def canonical_routes(solution: Any) -> list[list[int]]:
    normalised = []
    for route in ordered_routes(solution):
        reversed_route = list(reversed(route))
        normalised.append(min(route, reversed_route))
    return sorted(normalised)


def datum_payload(datum: Any) -> dict[str, int | float]:
    return {
        "size": int(datum.size),
        "avg_diversity": float(datum.avg_diversity),
        "best_cost": int(datum.best_cost),
        "avg_cost": float(datum.avg_cost),
        "avg_num_routes": float(datum.avg_num_routes),
    }


def trace_payload(stats: Any) -> list[dict[str, Any]]:
    if len(stats.feas_stats) != len(stats.infeas_stats):
        raise RuntimeError("feasible/infeasible statistics length mismatch")
    return [
        {
            "iteration": index + 1,
            "feasible": datum_payload(feasible),
            "infeasible": datum_payload(infeasible),
        }
        for index, (feasible, infeasible) in enumerate(
            zip(stats.feas_stats, stats.infeas_stats)
        )
    ]


class TransparentEducator:
    """Call the native local search exactly once and do nothing else."""

    def __init__(
        self,
        base_search: Any,
        *,
        mode: str,
        enhancement_enabled: bool,
    ) -> None:
        self.base_search = base_search
        self.mode = mode
        self.enhancement_enabled = enhancement_enabled
        self.calls = 0
        self.enhancement_calls = 0

    def __call__(self, solution: Any, cost_evaluator: Any) -> Any:
        self.calls += 1
        improved = self.base_search(solution, cost_evaluator)
        if self.enhancement_enabled:
            self.enhancement_calls += 1
            raise RuntimeError(
                "large-neighbourhood component is not armed in the "
                "same-path foundation version"
            )
        return improved

    def diagnostics(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "education_calls": self.calls,
            "enhancement_enabled": self.enhancement_enabled,
            "enhancement_calls": self.enhancement_calls,
            "transparent_base_search_calls": self.calls,
        }


def build_algorithm(
    instance: Path,
    *,
    seed: int,
    mode: str,
    disable_enhancement: bool,
) -> tuple[Any, Any, TransparentEducator | None]:
    data = read(instance, round_func="round")
    params = SolveParams()
    rng = RandomNumberGenerator(seed=seed)
    neighbours = compute_neighbours(data, params.neighbourhood)
    local_search = LocalSearch(data, rng, neighbours)
    for node_operator in params.node_ops:
        if node_operator.supports(data):
            local_search.add_node_operator(node_operator(data))
    for route_operator in params.route_ops:
        if route_operator.supports(data):
            local_search.add_route_operator(route_operator(data))

    educator: Any = local_search
    wrapper: TransparentEducator | None = None
    if mode != "official":
        enhancement_enabled = mode in {"lns", "hybrid"} and not disable_enhancement
        wrapper = TransparentEducator(
            local_search,
            mode=mode,
            enhancement_enabled=enhancement_enabled,
        )
        educator = wrapper

    penalty_manager = PenaltyManager.init_from(data, params.penalty)
    population = Population(broken_pairs_distance, params.population)
    initial_solutions = [
        Solution.make_random(data, rng)
        for _ in range(params.population.min_pop_size)
    ]
    crossover = (
        selective_route_exchange if data.num_vehicles > 1 else ordered_crossover
    )
    algorithm = GeneticAlgorithm(
        data,
        penalty_manager,
        rng,
        population,
        educator,
        crossover,
        initial_solutions,
        params.genetic,
    )
    return algorithm, rng, wrapper


def run(
    instance: Path,
    *,
    seed: int,
    iterations: int,
    mode: str,
    disable_enhancement: bool,
) -> dict[str, Any]:
    if importlib.metadata.version("pyvrp") != PYVRP_VERSION:
        raise RuntimeError(
            f"same-path worker requires PyVRP {PYVRP_VERSION}, found "
            f"{importlib.metadata.version('pyvrp')}"
        )
    if mode not in DECLARED_MODES:
        raise ValueError(f"unknown mode: {mode}")
    if mode in {"lns", "hybrid"} and not disable_enhancement:
        raise RuntimeError(
            f"{mode} enhancement is deliberately unarmed until the "
            "same-path no-op equivalence gate passes"
        )
    if iterations <= 0:
        raise ValueError("iterations must be positive")

    algorithm, rng, wrapper = build_algorithm(
        instance,
        seed=seed,
        mode=mode,
        disable_enhancement=disable_enhancement,
    )
    started = time.perf_counter()
    result = algorithm.run(
        MaxIterations(iterations),
        collect_stats=True,
        display=False,
        display_interval=SolveParams().display_interval,
    )
    elapsed = time.perf_counter() - started
    trace = trace_payload(result.stats)
    routes_in_order = ordered_routes(result.best)
    routes_canonical = canonical_routes(result.best)
    feasible = bool(result.best.is_feasible())
    return {
        "schema": "resetp_hgs_lns_same_path_v1",
        "mode": mode,
        "pyvrp_version": importlib.metadata.version("pyvrp"),
        "instance": instance.name,
        "instance_sha256": sha256_file(instance),
        "round_func": "round",
        "seed": seed,
        "iteration_limit": iterations,
        "iterations_completed": int(result.num_iterations),
        "elapsed_seconds": elapsed,
        "feasible": feasible,
        "cost": int(result.cost()) if math.isfinite(float(result.cost())) else None,
        "distance": int(result.best.distance()),
        "num_routes": int(result.best.num_routes()),
        "routes_ordered": routes_in_order,
        "routes_canonical": routes_canonical,
        "routes_ordered_sha256": canonical_json_sha(routes_in_order),
        "routes_canonical_sha256": canonical_json_sha(routes_canonical),
        "trace": trace,
        "trace_sha256": canonical_json_sha(trace),
        "core_rng_state_after": [int(value) for value in rng.state()],
        "educator": wrapper.diagnostics() if wrapper is not None else {
            "mode": "official",
            "native_local_search_direct": True,
        },
        "performance_claim_allowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--iterations", type=int, required=True)
    parser.add_argument("--mode", choices=sorted(DECLARED_MODES), required=True)
    parser.add_argument("--disable-enhancement", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = run(
        args.instance,
        seed=args.seed,
        iterations=args.iterations,
        mode=args.mode,
        disable_enhancement=args.disable_enhancement,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if payload["feasible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

