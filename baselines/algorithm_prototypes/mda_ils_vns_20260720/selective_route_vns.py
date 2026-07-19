"""Selective native route-level VNS for PyVRP 0.13.4.

The regular PyVRP local search remains the sole per-iteration search method.
Expensive native route operators are consulted only on exhaustive calls, which
the upstream ILS uses for the initial solution and newly found global records.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from pyvrp import ProblemData, RandomNumberGenerator, Solution, SolveParams
from pyvrp.search import (
    LocalSearch,
    PerturbationManager,
    PerturbationParams,
    SwapRoutes,
    SwapStar,
    compute_neighbours,
)


@dataclass(frozen=True)
class SearchConfig:
    name: str
    route_operators: tuple[str, ...] = ()
    weight_wait_time: float = 0.2
    weight_time_warp: float = 1.0
    num_neighbours: int = 50
    symmetric_neighbours: bool = False
    num_iters_no_improvement: int = 150_000
    history_length: int = 300
    min_perturbations: int = 1
    max_perturbations: int = 25


CONFIGS: dict[str, SearchConfig] = {
    "default": SearchConfig("default"),
    "swapstar_best": SearchConfig(
        "swapstar_best",
        route_operators=("SwapStar",),
    ),
    "swaproutes_best": SearchConfig(
        "swaproutes_best",
        route_operators=("SwapRoutes",),
    ),
    "route_vns_best": SearchConfig(
        "route_vns_best",
        route_operators=("SwapStar", "SwapRoutes"),
    ),
    "route_vns_k80": SearchConfig(
        "route_vns_k80",
        route_operators=("SwapStar", "SwapRoutes"),
        num_neighbours=80,
    ),
    "route_vns_tw_k80": SearchConfig(
        "route_vns_tw_k80",
        route_operators=("SwapStar", "SwapRoutes"),
        weight_wait_time=0.5,
        weight_time_warp=2.0,
        num_neighbours=80,
        symmetric_neighbours=True,
    ),
    "route_vns_restart75k": SearchConfig(
        "route_vns_restart75k",
        route_operators=("SwapStar", "SwapRoutes"),
        num_iters_no_improvement=75_000,
        history_length=600,
    ),
    "route_vns_perturb5_40": SearchConfig(
        "route_vns_perturb5_40",
        route_operators=("SwapStar", "SwapRoutes"),
        min_perturbations=5,
        max_perturbations=40,
    ),
}

ROUTE_OPERATOR_TYPES = {
    "SwapStar": SwapStar,
    "SwapRoutes": SwapRoutes,
}


def solve_params(config: SearchConfig) -> SolveParams:
    """Build immutable PyVRP parameters for a pre-registered configuration."""
    from pyvrp.IteratedLocalSearch import IteratedLocalSearchParams
    from pyvrp.search import NeighbourhoodParams

    defaults = SolveParams()
    return SolveParams(
        ils=IteratedLocalSearchParams(
            num_iters_no_improvement=config.num_iters_no_improvement,
            history_length=config.history_length,
            exhaustive_on_best=True,
        ),
        penalty=defaults.penalty,
        neighbourhood=NeighbourhoodParams(
            weight_wait_time=config.weight_wait_time,
            weight_time_warp=config.weight_time_warp,
            num_neighbours=config.num_neighbours,
            symmetric_proximity=True,
            symmetric_neighbours=config.symmetric_neighbours,
        ),
        node_ops=defaults.node_ops,
        route_ops=[],
        display_interval=defaults.display_interval,
        perturbation=PerturbationParams(
            config.min_perturbations,
            config.max_perturbations,
        ),
    )


def build_node_search(
    data: ProblemData,
    rng: RandomNumberGenerator,
    params: SolveParams,
) -> LocalSearch:
    neighbours = compute_neighbours(data, params.neighbourhood)
    search = LocalSearch(
        data,
        rng,
        neighbours,
        PerturbationManager(params.perturbation),
    )
    for operator in params.node_ops:
        if operator.supports(data):
            search.add_node_operator(operator(data))
    return search


def build_route_search(
    data: ProblemData,
    rng: RandomNumberGenerator,
    params: SolveParams,
    names: tuple[str, ...],
) -> LocalSearch | None:
    if not names:
        return None

    neighbours = compute_neighbours(data, params.neighbourhood)
    search = LocalSearch(
        data,
        rng,
        neighbours,
        PerturbationManager(PerturbationParams(0, 0)),
    )
    for name in names:
        operator = ROUTE_OPERATOR_TYPES[name]
        if operator.supports(data):
            search.add_route_operator(operator(data))
    return search


class SelectiveRouteVNS:
    """Search wrapper that reserves route VNS for exhaustive record events."""

    def __init__(
        self,
        node_search: LocalSearch,
        route_search: LocalSearch | None,
    ):
        self._node_search = node_search
        self._route_search = route_search
        self._calls = 0
        self._exhaustive_calls = 0
        self._route_calls = 0
        self._route_improvements = 0
        self._route_seconds = 0.0
        self._route_gain = 0

    def __call__(
        self,
        solution: Solution,
        cost_evaluator: Any,
        exhaustive: bool = False,
    ) -> Solution:
        self._calls += 1
        candidate = self._node_search(
            solution,
            cost_evaluator,
            exhaustive=exhaustive,
        )
        if not exhaustive:
            return candidate

        self._exhaustive_calls += 1
        if self._route_search is None:
            return candidate

        before = int(cost_evaluator.penalised_cost(candidate))
        started = time.perf_counter()
        intensified = self._route_search.intensify(candidate, cost_evaluator)
        self._route_seconds += time.perf_counter() - started
        self._route_calls += 1
        after = int(cost_evaluator.penalised_cost(intensified))
        if after < before:
            self._route_improvements += 1
            self._route_gain += before - after
        return intensified

    def diagnostics(self) -> dict[str, Any]:
        operator_stats: list[dict[str, Any]] = []
        if self._route_search is not None:
            for operator in self._route_search.route_operators:
                stats = operator.statistics
                operator_stats.append(
                    {
                        "operator": type(operator).__name__,
                        "evaluations": int(stats.num_evaluations),
                        "applications": int(stats.num_applications),
                    }
                )
        return {
            "calls": self._calls,
            "exhaustive_calls": self._exhaustive_calls,
            "route_calls": self._route_calls,
            "route_improvements": self._route_improvements,
            "route_gain": self._route_gain,
            "route_seconds": self._route_seconds,
            "route_operator_statistics": operator_stats,
        }
