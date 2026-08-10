"""Independent public HGS builders.

The historical customer-reassignment builder is retained for old evidence but
is not the default.  ``build_integrated_public_hgs`` uses the common integrated
HGS loop and the newly approved Vidal-style joint assignment/rotation step.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from time import perf_counter

from setp_hgs_kernel import ProblemData, RandomNumberGenerator, Solution
from setp_hgs_kernel.crossover import ordered_crossover as ox
from setp_hgs_kernel.crossover import selective_route_exchange as srex
from setp_hgs_kernel.diversity import broken_pairs_distance
from setp_hgs_kernel.ExternalPopulation import (
    EvaluatedSolution,
)
from setp_hgs_kernel.GeneticAlgorithm import (
    GeneticAlgorithm,
    GeneticAlgorithmParams,
)
from setp_hgs_kernel.IntegratedGeneticAlgorithm import (
    IntegratedGeneticAlgorithm,
    IntegratedProblemAdapter,
)
from setp_hgs_kernel.NativePopulationAdapter import NativePopulationAdapter
from setp_hgs_kernel.PenaltyManager import PenaltyManager
from setp_hgs_kernel.Population import Population
from setp_hgs_kernel.search import LocalSearch, compute_neighbours
from setp_hgs_kernel.solve import SolveParams

from .public_assignment import improve_customer_depot_assignment
from .vidal_compound import (
    improve_implicit_assignment_rotation,
    improve_implicit_customer_relocation,
)


@dataclass(frozen=True)
class PublicIntegratedEvaluation:
    solution: Solution
    objective: int
    penalised: int
    feasible: bool


@dataclass
class VidalCompoundAccounting:
    calls: int = 0
    accepted_calls: int = 0
    customer_calls: int = 0
    customer_candidate_evaluations: int = 0
    customer_joint_evaluations: int = 0
    customer_moves_accepted: int = 0
    customer_joint_only_accepted_moves: int = 0
    route_slot_evaluations: int = 0
    rotations_evaluated: int = 0
    assignments_changed: int = 0
    rotations_changed: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    runtime_seconds: float = 0.0
    non_improving_outputs_rejected: int = 0


@dataclass(frozen=True)
class IntegratedPublicHGSBundle:
    algorithm: IntegratedGeneticAlgorithm[Solution, PublicIntegratedEvaluation]
    vidal_accounting: VidalCompoundAccounting


class _VidalCompoundRefiner:
    """Refine an already educated child without replacing that child."""

    def __init__(
        self,
        data: ProblemData,
        local_search: LocalSearch,
        accounting: VidalCompoundAccounting,
        enable_customer_relocation: bool,
    ) -> None:
        self._data = data
        self._local_search = local_search
        self._accounting = accounting
        self._enable_customer_relocation = enable_customer_relocation
        self._rotation_cache: dict[
            tuple[tuple[int, ...], int],
            tuple[int, int, tuple[int, ...]] | None,
        ] = {}

    def __call__(self, solution: Solution, cost_evaluator) -> Solution:
        current = solution
        while current.is_feasible():
            changed = False
            self._accounting.calls += 1
            result = improve_implicit_assignment_rotation(
                self._data,
                current,
                cost_evaluator,
                self._rotation_cache,
            )
            self._accounting.runtime_seconds += result.runtime_seconds
            self._accounting.route_slot_evaluations += (
                result.route_slot_evaluations
            )
            self._accounting.rotations_evaluated += (
                result.rotations_evaluated
            )
            self._accounting.assignments_changed += (
                result.assignments_changed
            )
            self._accounting.rotations_changed += result.rotations_changed
            self._accounting.cache_hits += result.cache_hits
            self._accounting.cache_misses += result.cache_misses
            if result.after_cost < result.before_cost:
                self._accounting.accepted_calls += 1
                current = result.solution
                changed = True

            if self._enable_customer_relocation:
                self._accounting.customer_calls += 1
                customer = improve_implicit_customer_relocation(
                    self._data,
                    current,
                    cost_evaluator,
                    self._local_search.neighbours,
                    self._rotation_cache,
                )
                self._accounting.runtime_seconds += customer.runtime_seconds
                self._accounting.customer_candidate_evaluations += (
                    customer.candidate_evaluations
                )
                self._accounting.customer_joint_evaluations += (
                    customer.joint_evaluations
                )
                self._accounting.customer_moves_accepted += (
                    customer.accepted_moves
                )
                self._accounting.customer_joint_only_accepted_moves += (
                    customer.joint_only_accepted_moves
                )
                self._accounting.route_slot_evaluations += (
                    customer.route_slot_evaluations
                )
                self._accounting.rotations_evaluated += (
                    customer.rotations_evaluated
                )
                self._accounting.cache_hits += customer.cache_hits
                self._accounting.cache_misses += customer.cache_misses
                if customer.after_cost < customer.before_cost:
                    self._accounting.accepted_calls += 1
                    current = customer.solution
                    changed = True

            if not changed:
                return current
            educated = self._local_search(current, cost_evaluator)
            if not educated.is_feasible():
                return current
            current = educated
        return current


@dataclass
class AssignmentSearchAccounting:
    calls: int = 0
    accepted_calls: int = 0
    accepted_moves: int = 0
    candidate_evaluations: int = 0
    runtime_seconds: float = 0.0
    total_cost_reduction: int = 0


class CustomerAssignmentHGS(GeneticAlgorithm):
    """Copied 0.12.2 HGS with assignment improvement on new incumbents."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.assignment_accounting = AssignmentSearchAccounting()

    def _assignment_refine(self, solution: Solution) -> Solution:
        if (
            not solution.is_feasible()
            or self._cost_evaluator.cost(solution)
            >= self._cost_evaluator.cost(self._best)
        ):
            return solution
        self.assignment_accounting.calls += 1
        started = perf_counter()
        result = improve_customer_depot_assignment(
            self._data,
            solution,
            self._cost_evaluator,
        )
        self.assignment_accounting.runtime_seconds += (
            perf_counter() - started
        )
        self.assignment_accounting.candidate_evaluations += (
            result.candidate_evaluations
        )
        if result.after_cost < result.before_cost:
            self.assignment_accounting.accepted_calls += 1
            self.assignment_accounting.accepted_moves += len(result.moves)
            self.assignment_accounting.total_cost_reduction += (
                result.before_cost - result.after_cost
            )
            return result.solution
        return solution

    def _improve_offspring(self, sol: Solution) -> None:
        """Copied upstream method with assignment refinement inserted."""

        def is_new_best(candidate: Solution) -> bool:
            return self._cost_evaluator.cost(
                candidate
            ) < self._cost_evaluator.cost(self._best)

        sol = self._search(sol, self._cost_evaluator)
        sol = self._assignment_refine(sol)
        self._pop.add(sol, self._cost_evaluator)
        self._pm.register(sol)

        if is_new_best(sol):
            self._best = sol

        if (
            not sol.is_feasible()
            and self._rng.rand() < self._params.repair_probability
        ):
            sol = self._search(sol, self._pm.booster_cost_evaluator())
            sol = self._assignment_refine(sol)

            if sol.is_feasible():
                self._pop.add(sol, self._cost_evaluator)
                self._pm.register(sol)

            if is_new_best(sol):
                self._best = sol


def build_customer_assignment_hgs(
    data: ProblemData,
    *,
    seed: int,
    solve_parameters: SolveParams | None = None,
) -> CustomerAssignmentHGS:
    """Build from the directly copied foundation without importing PyVRP."""

    parameters = solve_parameters or SolveParams()
    rng = RandomNumberGenerator(seed=int(seed))
    neighbours = compute_neighbours(data, parameters.neighbourhood)
    local_search = LocalSearch(data, rng, neighbours)
    for operator in parameters.node_ops:
        if operator.supports(data):
            local_search.add_node_operator(operator(data))
    for operator in parameters.route_ops:
        if operator.supports(data):
            local_search.add_route_operator(operator(data))
    penalty_manager = PenaltyManager.init_from(data, parameters.penalty)
    population = Population(broken_pairs_distance, parameters.population)
    initial_solutions = tuple(
        Solution.make_random(data, rng)
        for _ in range(parameters.population.min_pop_size)
    )
    crossover = srex if data.num_vehicles > 1 else ox
    return CustomerAssignmentHGS(
        data,
        penalty_manager,
        rng,
        population,
        local_search,
        crossover,
        initial_solutions,
        GeneticAlgorithmParams(
            repair_probability=(
                parameters.genetic.repair_probability
            ),
            num_iters_no_improvement=(
                parameters.genetic.num_iters_no_improvement
            ),
        ),
    )


def build_integrated_public_hgs(
    data: ProblemData,
    *,
    seed: int,
    solve_parameters: SolveParams | None = None,
    enable_vidal_compound: bool = True,
    enable_customer_relocation: bool = True,
    refinement_scope: str = "new_incumbent",
) -> IntegratedPublicHGSBundle:
    """Build the one common HGS loop with public native evaluation."""

    parameters = solve_parameters or SolveParams()
    if refinement_scope not in {"every_feasible", "new_incumbent"}:
        raise ValueError("unknown public compound refinement scope")
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
    route_refinement_local_search = make_local_search(
        RandomNumberGenerator(seed=int(seed))
    )
    archive_local_search = make_local_search(
        RandomNumberGenerator(seed=int(seed))
    )
    penalty_manager = PenaltyManager.init_from(data, parameters.penalty)
    accounting = VidalCompoundAccounting()

    def evaluate(solution: Solution) -> EvaluatedSolution[
        Solution,
        PublicIntegratedEvaluation,
    ]:
        cost_evaluator = penalty_manager.cost_evaluator()
        evaluation = PublicIntegratedEvaluation(
            solution=solution,
            objective=int(cost_evaluator.cost(solution)),
            penalised=int(cost_evaluator.penalised_cost(solution)),
            feasible=bool(solution.is_feasible()),
        )
        return EvaluatedSolution(solution, evaluation)

    route_refiner = _VidalCompoundRefiner(
        data,
        route_refinement_local_search,
        accounting,
        False,
    )
    customer_refiner = _VidalCompoundRefiner(
        data,
        archive_local_search,
        accounting,
        True,
    )
    best_refinement_input_objective: int | None = None

    def refine(
        candidate: EvaluatedSolution[
            Solution,
            PublicIntegratedEvaluation,
        ],
    ) -> tuple[
        EvaluatedSolution[Solution, PublicIntegratedEvaluation],
        ...,
    ]:
        nonlocal best_refinement_input_objective
        if not enable_vidal_compound or not candidate.evaluation.feasible:
            return (candidate,)
        if (
            refinement_scope == "new_incumbent"
            and best_refinement_input_objective is not None
            and candidate.evaluation.objective
            >= best_refinement_input_objective
        ):
            return (candidate,)

        route_solution = route_refiner(
            candidate.solution,
            penalty_manager.cost_evaluator(),
        )
        best_refinement_input_objective = (
            candidate.evaluation.objective
            if best_refinement_input_objective is None
            else min(
                candidate.evaluation.objective,
                best_refinement_input_objective,
            )
        )
        base = candidate
        if _public_solution_fingerprint(
            route_solution
        ) != _public_solution_fingerprint(candidate.solution):
            route_refined = evaluate(route_solution)
            if (
                route_refined.evaluation.feasible
                and route_refined.evaluation.objective
                < candidate.evaluation.objective
            ):
                base = route_refined
            else:
                accounting.non_improving_outputs_rejected += 1

        if not enable_customer_relocation:
            best_refinement_input_objective = min(
                base.evaluation.objective,
                best_refinement_input_objective,
            )
            return (base,)

        customer_solution = customer_refiner(
            base.solution,
            penalty_manager.cost_evaluator(),
        )
        if _public_solution_fingerprint(
            customer_solution
        ) == _public_solution_fingerprint(base.solution):
            best_refinement_input_objective = min(
                base.evaluation.objective,
                best_refinement_input_objective,
            )
            return (base,)

        customer_refined = evaluate(customer_solution)
        if (
            not customer_refined.evaluation.feasible
            or customer_refined.evaluation.objective
            >= base.evaluation.objective
        ):
            accounting.non_improving_outputs_rejected += 1
        else:
            base = customer_refined
        best_refinement_input_objective = min(
            base.evaluation.objective,
            best_refinement_input_objective,
        )
        return (base,)

    adapter = IntegratedProblemAdapter(
        evaluate=evaluate,
        refine=refine,
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
    return IntegratedPublicHGSBundle(algorithm, accounting)


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
