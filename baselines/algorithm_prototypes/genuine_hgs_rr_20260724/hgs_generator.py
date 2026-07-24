"""Proxy HGS archive generation without hidden complete-model evaluation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import pyvrp
from pyvrp.GeneticAlgorithm import GeneticAlgorithm
from pyvrp.PenaltyManager import PenaltyManager
from pyvrp.Population import Population
from pyvrp._pyvrp import RandomNumberGenerator
from pyvrp._pyvrp import Solution as NativeSolution
from pyvrp.crossover import ordered_crossover
from pyvrp.crossover import selective_route_exchange
from pyvrp.diversity import broken_pairs_distance
from pyvrp.search import LocalSearch, compute_neighbours
from pyvrp.solve import SolveParams
from pyvrp.stop import MaxIterations, MaxRuntime, MultipleCriteria

from baselines.algorithm_prototypes.china81_mechanism_hybrid_20260720.pyvrp_adapter import (
    _native_solution_key,
    _project_initial_solution,
    _translate_solution,
    build_pyvrp_problem,
)
from setp_solver.china81 import China81Bundle
from setp_solver.china81_completion import (
    annotate_cross_site_services,
)
from setp_solver.solution import Solution
from setp_solver.algorithms.resetp_alns.operators.strong_bridge import (
    solution_signature_hash,
)


@dataclass(frozen=True)
class HgsArchiveCandidate:
    skeleton: Solution
    proxy_cost: int
    signature: str
    proxy_rank: int
    generation_kind: str = "population_archive"
    warm_parent_signature: str | None = None


@dataclass(frozen=True)
class HgsGeneratedArchive:
    candidates: tuple[HgsArchiveCandidate, ...]
    elapsed_seconds: float
    iterations: int
    route_proxy_mode: str
    seed: int
    warm_signatures: tuple[str, ...]
    stats: dict[str, Any]


def generate_hgs_archive(
    bundle: China81Bundle,
    warm_solutions: tuple[Solution, ...],
    *,
    seed: int,
    max_iterations: int,
    wallclock_safety_seconds: float,
    route_proxy_mode: str,
    max_archive_candidates: int = 24,
) -> HgsGeneratedArchive:
    """Run HGS and expose route skeletons only.

    No candidate is completed or scored by the full ReSETP model here.
    """

    if not hasattr(pyvrp, "GeneticAlgorithm"):
        raise RuntimeError("HGS generation requires PyVRP 0.12.2")
    if max_iterations < 1:
        raise ValueError("HGS iteration budget must be positive")
    if wallclock_safety_seconds <= 0.0:
        raise ValueError("HGS safety cap must be positive")
    if max_archive_candidates < 1:
        raise ValueError("HGS archive limit must be positive")
    started = perf_counter()
    problem = build_pyvrp_problem(
        bundle,
        route_proxy_mode=route_proxy_mode,
    )
    data = problem.model.data()
    params = SolveParams()
    rng = RandomNumberGenerator(seed=int(seed))
    neighbours = compute_neighbours(data, params.neighbourhood)
    local_search = LocalSearch(data, rng, neighbours)
    active_node_operators: list[str] = []
    for node_op in params.node_ops:
        if node_op.supports(data):
            local_search.add_node_operator(node_op(data))
            active_node_operators.append(node_op.__name__)
    active_route_operators: list[str] = []
    for route_op in params.route_ops:
        if route_op.supports(data):
            local_search.add_route_operator(route_op(data))
            active_route_operators.append(route_op.__name__)
    penalty_manager = PenaltyManager.init_from(
        data,
        params.penalty,
    )
    population = Population(
        broken_pairs_distance,
        params.population,
    )
    warm_native = [
        _project_initial_solution(item, data, problem) for item in warm_solutions
    ]
    direct_warm_descendants: list[
        tuple[
            str,
            Any,
        ]
    ] = []
    if warm_native:
        parent_signature = solution_signature_hash(warm_solutions[0])
        educated = local_search.search(
            warm_native[0],
            penalty_manager.cost_evaluator(),
        )
        if _native_solution_key(educated) != _native_solution_key(warm_native[0]):
            direct_warm_descendants.append((parent_signature, educated))
    injected_native = [native for _, native in direct_warm_descendants]
    random_count = max(
        0,
        int(params.population.min_pop_size) - len(warm_native) - len(injected_native),
    )
    initial_solutions = [
        *warm_native,
        *injected_native,
        *[NativeSolution.make_random(data, rng) for _ in range(random_count)],
    ]
    crossover = selective_route_exchange if data.num_vehicles > 1 else ordered_crossover
    algorithm = GeneticAlgorithm(
        data,
        penalty_manager,
        rng,
        population,
        local_search,
        crossover,
        initial_solutions,
        params.genetic,
    )
    result = algorithm.run(
        MultipleCriteria(
            [
                MaxIterations(int(max_iterations)),
                MaxRuntime(float(wallclock_safety_seconds)),
            ]
        ),
        collect_stats=True,
        display=False,
        display_interval=params.display_interval,
    )
    cost_evaluator = penalty_manager.cost_evaluator()
    initial_native_keys = {
        _native_solution_key(solution) for solution in initial_solutions
    }
    native_candidates = [
        *list(population),
        result.best,
    ]
    unique: dict[tuple[Any, ...], Any] = {}
    for native in native_candidates:
        unique.setdefault(_native_solution_key(native), native)
    proxy_ranked = sorted(
        unique.values(),
        key=lambda item: (
            int(cost_evaluator.cost(item)),
            repr(_native_solution_key(item)),
        ),
    )
    archive: list[HgsArchiveCandidate] = []
    translation_failures: list[str] = []
    seen_project_signatures: set[str] = set()
    for parent_signature, native in direct_warm_descendants:
        try:
            skeleton = annotate_cross_site_services(
                _translate_solution(native, problem),
                bundle.customer_home_depot,
            )
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            translation_failures.append(f"direct_warm_local_search:{exc}")
            continue
        signature = solution_signature_hash(skeleton)
        if signature == parent_signature or signature in seen_project_signatures:
            continue
        seen_project_signatures.add(signature)
        archive.append(
            HgsArchiveCandidate(
                skeleton=skeleton,
                proxy_cost=int(cost_evaluator.cost(native)),
                signature=signature,
                proxy_rank=len(archive) + 1,
                generation_kind="direct_warm_local_search",
                warm_parent_signature=parent_signature,
            )
        )
    for native in proxy_ranked:
        if len(archive) >= max_archive_candidates:
            break
        if _native_solution_key(native) in initial_native_keys:
            continue
        try:
            skeleton = annotate_cross_site_services(
                _translate_solution(native, problem),
                bundle.customer_home_depot,
            )
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            translation_failures.append(str(exc))
            continue
        signature = solution_signature_hash(skeleton)
        if signature in seen_project_signatures:
            continue
        seen_project_signatures.add(signature)
        archive.append(
            HgsArchiveCandidate(
                skeleton=skeleton,
                proxy_cost=int(cost_evaluator.cost(native)),
                signature=signature,
                proxy_rank=len(archive) + 1,
            )
        )
    if not archive:
        raise RuntimeError("HGS produced no translatable archive candidate")
    elapsed = perf_counter() - started
    return HgsGeneratedArchive(
        candidates=tuple(archive),
        elapsed_seconds=elapsed,
        iterations=int(result.num_iterations),
        route_proxy_mode=route_proxy_mode,
        seed=int(seed),
        warm_signatures=tuple(solution_signature_hash(item) for item in warm_solutions),
        stats={
            "schema": "resetp.hgs-proxy-archive.v1",
            "full_model_evaluations": 0,
            "seed": int(seed),
            "route_proxy_mode": route_proxy_mode,
            "max_iterations": int(max_iterations),
            "actual_iterations": int(result.num_iterations),
            "wallclock_safety_seconds": float(wallclock_safety_seconds),
            "elapsed_seconds": elapsed,
            "warm_solution_count": len(warm_solutions),
            "direct_warm_local_search_attempts": (1 if warm_native else 0),
            "direct_warm_local_search_changed": len(direct_warm_descendants),
            "direct_warm_descendant_archive_count": sum(
                candidate.generation_kind == "direct_warm_local_search"
                for candidate in archive
            ),
            "warm_route_type_counts": [
                dict(
                    sorted(
                        Counter(
                            route.vehicle_type.lower() for route in solution.routes
                        ).items()
                    )
                )
                for solution in warm_solutions
            ],
            "native_unique_count": len(unique),
            "unchanged_initial_native_count": sum(
                key in initial_native_keys for key in unique
            ),
            "archive_count": len(archive),
            "translation_failures": translation_failures,
            "active_node_operators": active_node_operators,
            "active_route_operators": active_route_operators,
        },
    )
