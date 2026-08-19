"""Independent public HGS builder for the canonical clean-ruler path."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from setp_hgs_kernel import ProblemData, RandomNumberGenerator, Solution, read
from setp_hgs_kernel.crossover import ordered_crossover as ox
from setp_hgs_kernel.crossover import selective_route_exchange as srex
from setp_hgs_kernel.diversity import broken_pairs_distance
from setp_hgs_kernel.PenaltyManager import PenaltyManager
from setp_hgs_kernel.search import LocalSearch, compute_neighbours
from setp_hgs_kernel.solve import SolveParams

from .external_population import EvaluatedSolution
from .integrated_genetic_algorithm import (
    IntegratedGeneticAlgorithm,
    IntegratedProblemAdapter,
)
from .native_population_adapter import NativePopulationAdapter
from .patched_genetic_algorithm import GeneticAlgorithmParams


PUBLIC_INSTANCE_SCALE = 1_000
PUBLIC_INSTANCE_ROUND_FUNC = "exact"


def read_public_instance(where: str | Path) -> ProblemData:
    """Compile a public instance using the verified certificate ruler.

    The copied kernel's ``exact`` reader applies ``np.round(1000 * value)``
    to distances, travel durations, service durations, and time windows so
    that every time-related quantity remains in the same integer unit.
    """

    return read(where, round_func=PUBLIC_INSTANCE_ROUND_FUNC)


@dataclass(frozen=True)
class PublicIntegratedEvaluation:
    solution: Solution
    objective: int
    feasible: bool


@dataclass(frozen=True)
class IntegratedPublicHGSBundle:
    algorithm: IntegratedGeneticAlgorithm[Solution, PublicIntegratedEvaluation]


def build_integrated_public_hgs(
    data: ProblemData,
    *,
    seed: int,
    solve_parameters: SolveParams | None = None,
) -> IntegratedPublicHGSBundle:
    """Build the one common HGS loop with public native evaluation."""

    parameters = solve_parameters or SolveParams()
    rng = RandomNumberGenerator(seed=int(seed))

    def make_local_search(search_rng: RandomNumberGenerator) -> LocalSearch:
        search = LocalSearch(
            data,
            search_rng,
            compute_neighbours(data, parameters.neighbourhood),
        )
        for operator in parameters.node_ops:
            if operator.supports(data):
                search.add_node_operator(operator(data))
        for operator in parameters.route_ops:
            if operator.supports(data):
                search.add_route_operator(operator(data))
        return search

    local_search = make_local_search(rng)
    penalty_manager = PenaltyManager.init_from(data, parameters.penalty)

    def evaluate(solution: Solution) -> EvaluatedSolution[
        Solution,
        PublicIntegratedEvaluation,
    ]:
        cost_evaluator = penalty_manager.cost_evaluator()
        evaluation = PublicIntegratedEvaluation(
            solution=solution,
            objective=int(cost_evaluator.cost(solution)),
            feasible=bool(solution.is_feasible()),
        )
        return EvaluatedSolution(solution, evaluation)

    adapter = IntegratedProblemAdapter(
        evaluate=evaluate,
        refine=lambda candidate: (candidate,),
        is_feasible=lambda evaluation: evaluation.feasible,
        objective=lambda evaluation: float(evaluation.objective),
        penalised_cost=lambda evaluation: float(
            penalty_manager.cost_evaluator().penalised_cost(
                evaluation.solution
            )
        ),
        register=lambda evaluation: penalty_manager.register(
            evaluation.solution
        ),
        fingerprint=_public_solution_fingerprint,
    )
    population = NativePopulationAdapter(
        broken_pairs_distance,
        evaluate=evaluate,
        cost_evaluator=penalty_manager.cost_evaluator,
        params=parameters.population,
    )
    initial_solutions = tuple(
        Solution.make_random(data, rng)
        for _ in range(parameters.population.min_pop_size)
    )
    crossover = srex if data.num_vehicles > 1 else ox
    algorithm = IntegratedGeneticAlgorithm(
        data,
        penalty_manager,
        rng,
        population,
        local_search,
        crossover,
        initial_solutions,
        adapter,
        GeneticAlgorithmParams(
            repair_probability=parameters.genetic.repair_probability,
            num_iters_no_improvement=(
                parameters.genetic.num_iters_no_improvement
            ),
        ),
    )
    return IntegratedPublicHGSBundle(algorithm)


def _public_solution_fingerprint(solution: Solution) -> str:
    routes = sorted(
        (
            int(route.vehicle_type()),
            tuple(
                tuple(int(client) for client in trip.visits())
                for trip in route.trips()
            ),
        )
        for route in solution.routes()
    )
    return hashlib.sha256(repr(routes).encode("utf-8")).hexdigest()
