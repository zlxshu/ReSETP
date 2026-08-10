"""Independent public MDVRPTW solver using the SREX/DCREX portfolio.

The vanilla PyVRP 0.12.2 baseline remains in a different environment.  This
module imports only the independently copied ``setp_hgs_kernel`` foundation
and owns the crossover portfolio, multi-parent DCREX, five insertion actions,
control loop, trajectory, and complete problem connection.
"""

from __future__ import annotations

import importlib.metadata
import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

from setp_hgs_kernel import CostEvaluator, ProblemData, RandomNumberGenerator, Route, Solution
from setp_hgs_kernel.diversity import broken_pairs_distance
from setp_hgs_kernel.PenaltyManager import PenaltyManager
from setp_hgs_kernel.Population import Population
from setp_hgs_kernel.search import LocalSearch, compute_neighbours
from setp_hgs_kernel.search._search import Node as SearchNode
from setp_hgs_kernel.search._search import Route as SearchRoute
from setp_hgs_kernel.search._search import insert_cost
from setp_hgs_kernel.solve import SolveParams

from .crossover_control import (
    CrossoverAction,
    RuntimeAwareCrossoverController,
)
from .dcrex import (
    DISCOUNT_FACTOR,
    DCREXController,
    InsertionOperator,
    RouteGene,
    dcrex_exchange,
    percentage_reward,
    remove_redundant_customers,
)
from .srex import PUBLIC_SREX_WORK_UNITS, public_srex


@dataclass(frozen=True)
class PublicDCREXParameters:
    max_iterations: int
    stagnation_patience: int = 500
    max_runtime_seconds: float | None = None
    repair_probability: float = 0.8
    dcrex_discount_factor: float = DISCOUNT_FACTOR
    crossover_mode: Literal["hybrid", "fast_only"] = "fast_only"

    def __post_init__(self) -> None:
        if int(self.max_iterations) < 1:
            raise ValueError("public DCREX max_iterations must be positive")
        if int(self.stagnation_patience) < 1:
            raise ValueError("public DCREX stagnation patience must be positive")
        if (
            self.max_runtime_seconds is not None
            and float(self.max_runtime_seconds) <= 0
        ):
            raise ValueError("public DCREX max runtime must be positive")
        if not 0.0 <= float(self.repair_probability) <= 1.0:
            raise ValueError("public DCREX repair_probability must be in [0, 1]")
        if not 0.0 < float(self.dcrex_discount_factor) <= 1.0:
            raise ValueError("public DCREX discount factor must be in (0, 1]")
        if self.crossover_mode not in {"hybrid", "fast_only"}:
            raise ValueError("public crossover mode must be hybrid or fast_only")


@dataclass(frozen=True)
class PublicDCREXTrajectoryRow:
    iteration: int
    elapsed_seconds: float
    best_cost: int
    crossover_action: str
    deterministic_work_units: int
    diversity_level: int | None
    insertion_operator: str | None
    parent_penalised_cost: float
    pre_local_search_penalised_cost: float
    post_local_search_penalised_cost: float
    direct_crossover_reward: float
    reward: float
    controller_credit: float
    relative_execution_cost: float
    reward_per_relative_cost: float
    crossover_seconds: float
    repair_seconds: float
    local_search_seconds: float
    pipeline_seconds: float
    iteration_seconds: float
    route_pair_scores: int
    insertion_score_calls: int


@dataclass(frozen=True)
class PublicDCREXResult:
    best: Solution
    iterations: int
    runtime_seconds: float
    trajectory: tuple[PublicDCREXTrajectoryRow, ...]
    termination_status: str


@dataclass(frozen=True)
class _PublicInsertionMove:
    route_index: int | None
    replacement: RouteGene


@dataclass(frozen=True)
class _PublicInsertionChoices:
    existing_any: tuple[tuple[str, bool, int, _PublicInsertionMove, object], ...]
    existing_feasible: tuple[tuple[str, bool, int, _PublicInsertionMove, object], ...]
    new_any: tuple[tuple[str, bool, int, _PublicInsertionMove, object], ...]
    new_feasible: tuple[tuple[str, bool, int, _PublicInsertionMove, object], ...]


class _PublicInsertionWorkspace:
    """Reuse copied compiled route objects throughout one DCREX repair."""

    def __init__(self, data: ProblemData, cost_evaluator: CostEvaluator) -> None:
        self.data = data
        self.cost_evaluator = cost_evaluator
        self.zero_penalty_evaluator = CostEvaluator(
            [0] * data.num_load_dimensions,
            0,
            0,
        )
        self.routes: list[SearchRoute] = []
        self.vehicle_types: list[int] = []
        self.current_costs: list[int] = []
        self.current_unpenalised_costs: list[int] = []
        self.insertion_score_calls = 0

    def _load_gene(self, index: int, gene: RouteGene) -> SearchRoute:
        vehicle_type = int(gene.vehicle_type)
        if index >= len(self.routes):
            self.routes.append(SearchRoute(self.data, index, vehicle_type))
            self.vehicle_types.append(vehicle_type)
        elif self.vehicle_types[index] != vehicle_type:
            self.routes[index].clear()
            self.routes[index] = SearchRoute(self.data, index, vehicle_type)
            self.vehicle_types[index] = vehicle_type
        else:
            self.routes[index].clear()
        route = self.routes[index]
        for customer in gene.customer_ids:
            route.append(SearchNode(int(customer)))
        route.update()
        return route

    def _route_costs(self, gene: RouteGene) -> tuple[int, int]:
        penalised = _public_route_penalised_cost(
            self.data,
            gene,
            self.cost_evaluator,
        )[1]
        unpenalised = _public_route_penalised_cost(
            self.data,
            gene,
            self.zero_penalty_evaluator,
        )[1]
        return penalised, unpenalised

    def reset(self, genes: tuple[RouteGene, ...]) -> None:
        self.insertion_score_calls = 0
        for index, gene in enumerate(genes):
            self._load_gene(index, gene)
        for route in self.routes[len(genes) :]:
            route.clear()
        costs = [self._route_costs(gene) for gene in genes]
        self.current_costs = [item[0] for item in costs]
        self.current_unpenalised_costs = [item[1] for item in costs]

    def apply_insertion(
        self,
        move: _PublicInsertionMove,
        customer: int,
    ) -> None:
        gene = move.replacement
        if move.route_index is None:
            index = len(self.current_costs)
            self._load_gene(index, gene)
            penalised, unpenalised = self._route_costs(gene)
            self.current_costs.append(penalised)
            self.current_unpenalised_costs.append(unpenalised)
            return

        index = int(move.route_index)
        position = gene.customer_ids.index(int(customer))
        route = self.routes[index]
        route.insert(position + 1, SearchNode(int(customer)))
        route.update()
        penalised, unpenalised = self._route_costs(gene)
        self.current_costs[index] = penalised
        self.current_unpenalised_costs[index] = unpenalised

    def close(self) -> None:
        for route in self.routes:
            route.clear()


class PublicDCREXHGS:
    """Independent public-benchmark control loop for the project algorithm."""

    def __init__(
        self,
        *,
        data: ProblemData,
        penalty_manager: PenaltyManager,
        population: Population,
        search_method: Callable[[Solution, CostEvaluator], Solution],
        initial_solutions: tuple[Solution, ...],
        kernel_rng: RandomNumberGenerator,
        random_seed: int,
        parameters: PublicDCREXParameters,
    ) -> None:
        version = importlib.metadata.version("setp_hgs_kernel")
        if version != "0.12.2":
            raise RuntimeError(
                f"independent public solver requires kernel 0.12.2, got {version}"
            )
        if len(initial_solutions) < 2:
            raise ValueError("public DCREX requires at least two initial solutions")
        self.data = data
        self.penalty_manager = penalty_manager
        self.population = population
        self.search_method = search_method
        self.initial_solutions = tuple(initial_solutions)
        self.kernel_rng = kernel_rng
        self.rng = random.Random(int(random_seed))
        self.parameters = parameters
        self.controller = DCREXController(gamma=float(parameters.dcrex_discount_factor))
        self.crossover_controller = RuntimeAwareCrossoverController(
            gamma=float(parameters.dcrex_discount_factor)
        )
        self.insertion_workspace = _PublicInsertionWorkspace(
            data,
            self.cost_evaluator,
        )
        self.customer_universe = _customer_universe(data, initial_solutions)
        self._gene_cache: dict[
            int,
            tuple[Solution, tuple[RouteGene, ...]],
        ] = {}

    @property
    def cost_evaluator(self) -> CostEvaluator:
        return self.penalty_manager.cost_evaluator()

    def run(self) -> PublicDCREXResult:
        try:
            return self._run()
        finally:
            self.insertion_workspace.close()

    def _population_genes(
        self,
        solutions: tuple[Solution, ...],
    ) -> tuple[tuple[RouteGene, ...], ...]:
        """Convert only population members not already seen at the last DCREX.

        The cache is pruned to the current population on every DCREX call, so
        its size follows the actual population instead of the iteration count.
        """

        active: dict[int, tuple[Solution, tuple[RouteGene, ...]]] = {}
        genes: list[tuple[RouteGene, ...]] = []
        for solution in solutions:
            key = id(solution)
            cached = self._gene_cache.get(key)
            if cached is None or cached[0] is not solution:
                cached = (solution, _solution_genes(solution))
            active[key] = cached
            genes.append(cached[1])
        self._gene_cache = active
        return tuple(genes)

    def _run(self) -> PublicDCREXResult:
        started = perf_counter()
        educated_initial = []
        for solution in self.initial_solutions:
            solution = self.search_method(solution, self.cost_evaluator)
            self.penalty_manager.register(solution)
            if not solution.is_feasible():
                repaired = self.search_method(
                    solution,
                    self.penalty_manager.booster_cost_evaluator(),
                )
                if repaired.is_feasible():
                    solution = repaired
                    self.penalty_manager.register(solution)
            educated_initial.append(solution)
        self.initial_solutions = tuple(educated_initial)
        for solution in self.initial_solutions:
            self.population.add(solution, self.cost_evaluator)
        best = min(self.initial_solutions, key=self.cost_evaluator.cost)
        no_improvement = 0
        trajectory: list[PublicDCREXTrajectoryRow] = []

        termination_status = "MAX_ITERATIONS"
        for iteration in range(1, self.parameters.max_iterations + 1):
            if (
                self.parameters.max_runtime_seconds is not None
                and perf_counter() - started
                >= self.parameters.max_runtime_seconds
            ):
                termination_status = "MAX_RUNTIME"
                break
            if no_improvement > self.parameters.stagnation_patience:
                termination_status = "CONVERGED_NO_IMPROVEMENT"
                break

            iteration_started = perf_counter()
            parent_solutions = tuple(self.population)
            if len(parent_solutions) < 2:
                for solution in self.initial_solutions:
                    self.population.add(solution, self.cost_evaluator)
                parent_solutions = tuple(self.population)
            crossover_action = (
                CrossoverAction.FAST
                if self.parameters.crossover_mode == "fast_only"
                else self.crossover_controller.select(self.rng)
            )
            pipeline_started = perf_counter()
            crossed = None
            route_pair_scores = 0
            insertion_score_calls = 0
            if crossover_action == CrossoverAction.FAST:
                crossover_started = perf_counter()
                selected = self.population.select(
                    self.kernel_rng,
                    self.cost_evaluator,
                )
                main_parent = selected[0]
                offspring = public_srex(
                    selected,
                    self.data,
                    self.cost_evaluator,
                    self.kernel_rng,
                )
                crossover_seconds = perf_counter() - crossover_started
                repair_seconds = 0.0
                deterministic_work_units = PUBLIC_SREX_WORK_UNITS
                crossover_action_label = "SREX"
                diversity_level = None
                insertion_operator = None
            else:
                crossover_started = perf_counter()
                parent_genes = self._population_genes(parent_solutions)
                crossed = dcrex_exchange(
                    parent_genes,
                    customer_universe=self.customer_universe,
                    rng=self.rng,
                    controller=self.controller,
                    preserve_target_terminals=False,
                )
                crossover_seconds = perf_counter() - crossover_started
                route_pair_scores = crossed.route_pair_scores
                main_parent = parent_solutions[crossed.main_parent_index]
                repair_started = perf_counter()
                routes, missing = _remove_public_duplicates(
                    crossed.routes,
                    self.customer_universe,
                )
                routes = _repair_public_vehicle_assignment(
                    self.data,
                    routes,
                    self.cost_evaluator,
                )
                self.insertion_workspace.insertion_score_calls = 0
                routes = _insert_public_customers(
                    self.data,
                    routes,
                    missing,
                    crossed.insertion_operator,
                    self.rng,
                    self.cost_evaluator,
                    workspace=self.insertion_workspace,
                )
                offspring = _solution_from_genes(self.data, routes)
                repair_seconds = perf_counter() - repair_started
                insertion_score_calls = (
                    self.insertion_workspace.insertion_score_calls
                )
                deterministic_work_units = 1
                crossover_action_label = "DCREX"
                diversity_level = crossed.diversity_level
                insertion_operator = crossed.insertion_operator.value
            main_cost = self.cost_evaluator.penalised_cost(main_parent)
            pre_local_search_cost = self.cost_evaluator.penalised_cost(offspring)
            direct_crossover_reward = percentage_reward(
                main_cost,
                pre_local_search_cost,
            )
            local_search_started = perf_counter()
            offspring = self.search_method(offspring, self.cost_evaluator)
            local_search_seconds = perf_counter() - local_search_started
            self.population.add(offspring, self.cost_evaluator)
            self.penalty_manager.register(offspring)
            if (
                not offspring.is_feasible()
                and self.rng.random() < self.parameters.repair_probability
            ):
                repair_search_started = perf_counter()
                repaired = self.search_method(
                    offspring,
                    self.penalty_manager.booster_cost_evaluator(),
                )
                local_search_seconds += (
                    perf_counter() - repair_search_started
                )
                if repaired.is_feasible():
                    offspring = repaired
                    self.population.add(offspring, self.cost_evaluator)
                    self.penalty_manager.register(offspring)
            offspring_cost = self.cost_evaluator.penalised_cost(offspring)
            reward = percentage_reward(main_cost, offspring_cost)
            pipeline_seconds = perf_counter() - pipeline_started
            if crossed is not None:
                self.controller.update(
                    crossed.diversity_level,
                    crossed.insertion_operator,
                    direct_crossover_reward,
                )
            crossover_reward = self.crossover_controller.update(
                crossover_action,
                direct_crossover_reward,
                crossover_seconds + repair_seconds,
            )
            if self.cost_evaluator.cost(offspring) < self.cost_evaluator.cost(best):
                best = offspring
                no_improvement = 0
            else:
                no_improvement += 1
            trajectory.append(
                PublicDCREXTrajectoryRow(
                    iteration=iteration,
                    elapsed_seconds=perf_counter() - started,
                    best_cost=int(self.cost_evaluator.cost(best)),
                    crossover_action=crossover_action_label,
                    deterministic_work_units=deterministic_work_units,
                    diversity_level=diversity_level,
                    insertion_operator=insertion_operator,
                    parent_penalised_cost=float(main_cost),
                    pre_local_search_penalised_cost=float(pre_local_search_cost),
                    post_local_search_penalised_cost=float(offspring_cost),
                    direct_crossover_reward=direct_crossover_reward,
                    reward=reward,
                    controller_credit=crossover_reward.credited_reward,
                    relative_execution_cost=(
                        crossover_reward.relative_execution_cost
                    ),
                    reward_per_relative_cost=(
                        crossover_reward.reward_per_relative_cost
                    ),
                    crossover_seconds=crossover_seconds,
                    repair_seconds=repair_seconds,
                    local_search_seconds=local_search_seconds,
                    pipeline_seconds=pipeline_seconds,
                    iteration_seconds=perf_counter() - iteration_started,
                    route_pair_scores=route_pair_scores,
                    insertion_score_calls=insertion_score_calls,
                )
            )

        return PublicDCREXResult(
            best=best,
            iterations=len(trajectory),
            runtime_seconds=perf_counter() - started,
            trajectory=tuple(trajectory),
            termination_status=termination_status,
        )


def build_public_dcrex_hgs(
    data: ProblemData,
    *,
    seed: int,
    max_iterations: int,
    stagnation_patience: int = 500,
    max_runtime_seconds: float | None = None,
    solve_parameters: SolveParams | None = None,
    crossover_mode: Literal["hybrid", "fast_only"] = "fast_only",
) -> PublicDCREXHGS:
    """Build the project algorithm from its independently copied kernel."""

    solve_parameters = solve_parameters or SolveParams()
    kernel_rng = RandomNumberGenerator(seed=int(seed))
    neighbours = compute_neighbours(data, solve_parameters.neighbourhood)
    local_search = LocalSearch(data, kernel_rng, neighbours)
    for node_operator in solve_parameters.node_ops:
        if node_operator.supports(data):
            local_search.add_node_operator(node_operator(data))
    for route_operator in solve_parameters.route_ops:
        if route_operator.supports(data):
            local_search.add_route_operator(route_operator(data))
    penalty_manager = PenaltyManager.init_from(
        data,
        solve_parameters.penalty,
    )
    population = Population(
        broken_pairs_distance,
        solve_parameters.population,
    )
    initial_solutions = tuple(
        Solution.make_random(data, kernel_rng)
        for _ in range(solve_parameters.population.min_pop_size)
    )
    return PublicDCREXHGS(
        data=data,
        penalty_manager=penalty_manager,
        population=population,
        search_method=local_search,
        initial_solutions=initial_solutions,
        kernel_rng=kernel_rng,
        random_seed=seed,
        parameters=PublicDCREXParameters(
            max_iterations=max_iterations,
            stagnation_patience=stagnation_patience,
            max_runtime_seconds=max_runtime_seconds,
            repair_probability=solve_parameters.genetic.repair_probability,
            crossover_mode=crossover_mode,
        ),
    )


def _solution_genes(solution: Solution) -> tuple[RouteGene, ...]:
    return tuple(
        RouteGene(
            route_id=index,
            customer_ids=tuple(route.visits()),
            start_depot=int(route.start_depot()),
            end_depot=int(route.end_depot()),
            vehicle_type=int(route.vehicle_type()),
        )
        for index, route in enumerate(solution.routes())
    )


def _customer_universe(
    data: ProblemData,
    solutions: Iterable[Solution],
) -> tuple[int, ...]:
    visited = {
        int(client)
        for solution in solutions
        for route in solution.routes()
        for client in route.visits()
    }
    required = {
        index
        for index in range(data.num_depots, data.num_locations)
        if data.location(index).required
    }
    return tuple(sorted(visited.union(required)))


def _remove_public_duplicates(
    routes: tuple[RouteGene, ...],
    customer_universe: Iterable[int],
) -> tuple[tuple[RouteGene, ...], tuple[int, ...]]:
    removal = remove_redundant_customers(routes)
    cleaned = [route for route in removal.routes if route.customer_ids]
    seen = {int(customer) for route in cleaned for customer in route.customer_ids}
    missing = tuple(customer for customer in customer_universe if customer not in seen)
    return tuple(cleaned), missing


def _repair_public_vehicle_assignment(
    data: ProblemData,
    routes: tuple[RouteGene, ...],
    cost_evaluator: CostEvaluator,
) -> tuple[RouteGene, ...]:
    """Repair fleet counts while preserving the cheapest donor route structure."""

    capacities = {
        vehicle_type: int(data.vehicle_type(vehicle_type).num_available)
        for vehicle_type in range(data.num_vehicle_types)
    }
    counts = {vehicle_type: 0 for vehicle_type in capacities}
    for route in routes:
        counts[int(route.vehicle_type)] += 1
    repaired = list(routes)
    while any(counts[item] > capacities[item] for item in capacities):
        overloaded = {item for item in capacities if counts[item] > capacities[item]}
        available = [item for item in capacities if counts[item] < capacities[item]]
        if not available:
            raise ValueError("DCREX offspring exceeds the public fleet")
        candidates = []
        for route_index, route in enumerate(repaired):
            current_type = int(route.vehicle_type)
            if current_type not in overloaded:
                continue
            current_cost = _public_route_penalised_cost(
                data,
                route,
                cost_evaluator,
            )[1]
            for replacement_type in available:
                specification = data.vehicle_type(replacement_type)
                replacement = RouteGene(
                    route_id=route.route_id,
                    customer_ids=route.customer_ids,
                    start_depot=int(specification.start_depot),
                    end_depot=int(specification.end_depot),
                    vehicle_type=replacement_type,
                )
                replacement_cost = _public_route_penalised_cost(
                    data,
                    replacement,
                    cost_evaluator,
                )[1]
                candidates.append(
                    (
                        replacement_cost - current_cost,
                        repr(route.route_id),
                        replacement_type,
                        route_index,
                        replacement,
                    )
                )
        if not candidates:
            raise ValueError("DCREX cannot repair the public fleet assignment")
        _delta, _route_id, replacement_type, route_index, replacement = min(
            candidates,
            key=lambda item: item[:4],
        )
        current_type = int(repaired[route_index].vehicle_type)
        repaired[route_index] = replacement
        counts[current_type] -= 1
        counts[replacement_type] += 1
    return tuple(repaired)


def _insert_public_customers(
    data: ProblemData,
    routes: tuple[RouteGene, ...],
    missing: tuple[int, ...],
    operator: InsertionOperator,
    rng: random.Random,
    cost_evaluator: CostEvaluator,
    *,
    workspace: _PublicInsertionWorkspace | None = None,
) -> tuple[RouteGene, ...]:
    current = tuple(routes)
    pending = list(missing)
    rng.shuffle(pending)
    owns_workspace = workspace is None
    active_workspace = None
    if operator != InsertionOperator.RI:
        active_workspace = workspace or _PublicInsertionWorkspace(
            data,
            cost_evaluator,
        )
        active_workspace.cost_evaluator = cost_evaluator
        active_workspace.reset(current)
    regret_cache: dict[int, _PublicInsertionChoices] = {}
    changed_route_index: int | None = None
    try:
        while pending:
            if operator == InsertionOperator.RI:
                customer = pending[0]
                moves = _public_insertion_moves(
                    data,
                    current,
                    customer,
                    allow_new=False,
                )
                rng.shuffle(moves)
                if not moves:
                    moves = _public_insertion_moves(
                        data,
                        current,
                        customer,
                        allow_new=True,
                    )
                if not moves:
                    raise ValueError("RI cannot insert a missing public customer")
                chosen = moves[0]
            elif operator in {InsertionOperator.FBI, InsertionOperator.IBI}:
                customer = pending[0]
                choices = _best_public_insertion_choices(
                    data,
                    current,
                    customer,
                    cost_evaluator,
                    include_new=(operator == InsertionOperator.FBI),
                    workspace=active_workspace,
                )
                if operator == InsertionOperator.FBI:
                    if choices.existing_feasible:
                        chosen = min(
                            choices.existing_feasible,
                            key=lambda row: (row[2], row[0]),
                        )[3]
                    else:
                        pool = choices.new_any or choices.existing_any
                        if not pool:
                            raise ValueError(
                                "FBI cannot insert a missing public customer"
                            )
                        chosen = min(
                            pool,
                            key=lambda row: (row[2], row[0]),
                        )[3]
                else:
                    if not choices.existing_any:
                        raise ValueError("IBI cannot insert a missing public customer")
                    chosen = min(
                        choices.existing_any,
                        key=lambda row: (row[2], row[0]),
                    )[3]
            else:
                feasible_only = operator == InsertionOperator.FRI
                customer_choices = []
                for customer in pending:
                    choices = regret_cache.get(customer)
                    if choices is None:
                        choices = _best_public_insertion_choices(
                            data,
                            current,
                            customer,
                            cost_evaluator,
                            include_new=feasible_only,
                            workspace=active_workspace,
                        )
                    elif changed_route_index is not None:
                        refreshed = _best_public_insertion_choices(
                            data,
                            current,
                            customer,
                            cost_evaluator,
                            include_new=feasible_only,
                            workspace=active_workspace,
                            route_indices=(changed_route_index,),
                        )
                        choices = _refresh_public_insertion_cache(
                            choices,
                            refreshed,
                            changed_route_index,
                        )
                    regret_cache[customer] = choices
                    ranked = sorted(
                        (
                            (*choices.existing_feasible, *choices.new_feasible)
                            if feasible_only
                            else choices.existing_any
                        ),
                        key=lambda row: (row[2], row[0]),
                    )
                    if not ranked:
                        continue
                    regret = (
                        ranked[1][2] - ranked[0][2] if len(ranked) > 1 else float("inf")
                    )
                    customer_choices.append((regret, customer, ranked[0][3]))
                if not customer_choices:
                    customer = pending[0]
                    choices = _best_public_insertion_choices(
                        data,
                        current,
                        customer,
                        cost_evaluator,
                        include_new=True,
                        workspace=active_workspace,
                    )
                    rows = (*choices.existing_any, *choices.new_any)
                    if not rows:
                        raise ValueError(
                            f"{operator.value} cannot insert a missing public customer"
                        )
                    chosen = min(rows, key=lambda row: (row[2], row[0]))[3]
                else:
                    _regret, customer, chosen = max(
                        customer_choices,
                        key=lambda item: (item[0], item[1]),
                    )
            current = _apply_public_insertion_move(current, chosen)
            if active_workspace is not None:
                active_workspace.apply_insertion(chosen, customer)
            pending.remove(customer)
            regret_cache.pop(customer, None)
            changed_route_index = (
                int(chosen.route_index)
                if chosen.route_index is not None
                else len(current) - 1
            )
    finally:
        if owns_workspace and active_workspace is not None:
            active_workspace.close()
    return current


def _best_public_insertion_choices(
    data: ProblemData,
    routes: tuple[RouteGene, ...],
    customer: int,
    cost_evaluator: CostEvaluator,
    *,
    include_new: bool,
    workspace: _PublicInsertionWorkspace | None = None,
    route_indices: Iterable[int] | None = None,
) -> _PublicInsertionChoices:
    """Return only each route's best exact insertion, as in ARIX/DCREX."""

    owns_workspace = workspace is None
    if workspace is None:
        workspace = _PublicInsertionWorkspace(data, cost_evaluator)
        workspace.reset(routes)
    zero_penalty_evaluator = workspace.zero_penalty_evaluator
    inserted = SearchNode(int(customer))
    existing_any = []
    existing_feasible = []
    usage: dict[int, int] = {}
    for gene in routes:
        vehicle_type = int(gene.vehicle_type)
        usage[vehicle_type] = usage.get(vehicle_type, 0) + 1
    selected_indices = (
        tuple(range(len(routes)))
        if route_indices is None
        else tuple(int(index) for index in route_indices)
    )
    route_offsets = []
    offset = 0
    for gene in routes:
        route_offsets.append(offset)
        offset += len(gene.customer_ids) + 1
    for route_index in selected_indices:
        gene = routes[route_index]
        search_route = workspace.routes[route_index]
        current_cost = workspace.current_costs[route_index]
        current_unpenalised = workspace.current_unpenalised_costs[route_index]
        best_any = None
        best_feasible = None
        for position in range(len(gene.customer_ids) + 1):
            workspace.insertion_score_calls += 2
            delta = int(
                insert_cost(
                    inserted,
                    search_route[position],
                    data,
                    cost_evaluator,
                )
            )
            unpenalised_delta = int(
                insert_cost(
                    inserted,
                    search_route[position],
                    data,
                    zero_penalty_evaluator,
                )
            )
            candidate_penalty = (
                current_cost - current_unpenalised + delta - unpenalised_delta
            )
            row = (
                f"{route_offsets[route_index] + position:08d}",
                candidate_penalty == 0,
                delta,
                position,
            )
            if best_any is None or (row[2], row[0]) < (
                best_any[2],
                best_any[0],
            ):
                best_any = row
            if row[1] and (
                best_feasible is None
                or (row[2], row[0])
                < (
                    best_feasible[2],
                    best_feasible[0],
                )
            ):
                best_feasible = row
        if best_any is not None:
            existing_any.append(
                _materialise_public_insertion_choice(
                    gene,
                    route_index,
                    customer,
                    best_any,
                )
            )
        if best_feasible is not None:
            existing_feasible.append(
                _materialise_public_insertion_choice(
                    gene,
                    route_index,
                    customer,
                    best_feasible,
                )
            )

    new_any = []
    new_feasible = []
    if include_new:
        move_index = offset
        for vehicle_type in range(data.num_vehicle_types):
            specification = data.vehicle_type(vehicle_type)
            if usage.get(vehicle_type, 0) >= specification.num_available:
                continue
            gene = RouteGene(
                route_id=("new", len(routes), vehicle_type),
                customer_ids=(customer,),
                start_depot=int(specification.start_depot),
                end_depot=int(specification.end_depot),
                vehicle_type=vehicle_type,
            )
            feasible, cost = _public_route_penalised_cost(
                data,
                gene,
                cost_evaluator,
            )
            move = _PublicInsertionMove(None, gene)
            row = (
                f"{move_index:08d}",
                feasible,
                int(cost),
                move,
                gene.route_id,
            )
            move_index += 1
            new_any.append(row)
            if feasible:
                new_feasible.append(row)

    result = _PublicInsertionChoices(
        existing_any=tuple(existing_any),
        existing_feasible=tuple(existing_feasible),
        new_any=tuple(new_any),
        new_feasible=tuple(new_feasible),
    )
    if owns_workspace:
        workspace.close()
    return result


def _materialise_public_insertion_choice(
    gene: RouteGene,
    route_index: int,
    customer: int,
    scored: tuple[str, bool, int, int],
) -> tuple[str, bool, int, _PublicInsertionMove, object]:
    row_id, feasible, delta, position = scored
    customers = list(gene.customer_ids)
    customers.insert(position, customer)
    move = _PublicInsertionMove(
        route_index=route_index,
        replacement=RouteGene(
            gene.route_id,
            tuple(customers),
            gene.start_depot,
            gene.end_depot,
            gene.vehicle_type,
        ),
    )
    return row_id, feasible, delta, move, gene.route_id


def _refresh_public_insertion_cache(
    previous: _PublicInsertionChoices,
    refreshed: _PublicInsertionChoices,
    changed_route_index: int,
) -> _PublicInsertionChoices:
    def existing_rows(
        old_rows: tuple[tuple[str, bool, int, _PublicInsertionMove, object], ...],
        new_rows: tuple[tuple[str, bool, int, _PublicInsertionMove, object], ...],
    ) -> tuple[tuple[str, bool, int, _PublicInsertionMove, object], ...]:
        rows = [row for row in old_rows if row[3].route_index != changed_route_index]
        rows.extend(new_rows)
        rekeyed = []
        for row_id, feasible, delta, move, route_id in rows:
            route_index = int(move.route_index)
            rekeyed.append(
                (
                    f"{int(row_id) + int(route_index > changed_route_index):08d}",
                    feasible,
                    delta,
                    move,
                    route_id,
                )
            )
        return tuple(sorted(rekeyed, key=lambda row: int(row[3].route_index)))

    return _PublicInsertionChoices(
        existing_any=existing_rows(
            previous.existing_any,
            refreshed.existing_any,
        ),
        existing_feasible=existing_rows(
            previous.existing_feasible,
            refreshed.existing_feasible,
        ),
        new_any=refreshed.new_any,
        new_feasible=refreshed.new_feasible,
    )


def _public_insertion_moves(
    data: ProblemData,
    routes: tuple[RouteGene, ...],
    customer: int,
    *,
    allow_new: bool,
    new_only: bool = False,
) -> list[_PublicInsertionMove]:
    moves: list[_PublicInsertionMove] = []
    if not new_only:
        for index, route in enumerate(routes):
            for position in range(len(route.customer_ids) + 1):
                customers = list(route.customer_ids)
                customers.insert(position, customer)
                moves.append(
                    _PublicInsertionMove(
                        route_index=index,
                        replacement=RouteGene(
                            route.route_id,
                            tuple(customers),
                            route.start_depot,
                            route.end_depot,
                            route.vehicle_type,
                        ),
                    )
                )
    if allow_new:
        usage = {}
        for route in routes:
            usage[int(route.vehicle_type)] = usage.get(int(route.vehicle_type), 0) + 1
        for vehicle_type in range(data.num_vehicle_types):
            specification = data.vehicle_type(vehicle_type)
            if usage.get(vehicle_type, 0) >= specification.num_available:
                continue
            new_route = RouteGene(
                route_id=("new", len(routes), vehicle_type),
                customer_ids=(customer,),
                start_depot=int(specification.start_depot),
                end_depot=int(specification.end_depot),
                vehicle_type=vehicle_type,
            )
            moves.append(
                _PublicInsertionMove(
                    route_index=None,
                    replacement=new_route,
                )
            )
    return moves


def _apply_public_insertion_move(
    routes: tuple[RouteGene, ...],
    move: _PublicInsertionMove,
) -> tuple[RouteGene, ...]:
    if move.route_index is None:
        return (*routes, move.replacement)
    updated = list(routes)
    updated[move.route_index] = move.replacement
    return tuple(updated)


def _evaluate_public_moves(
    data: ProblemData,
    moves: Iterable[_PublicInsertionMove],
    inserted_customer: int,
    current_routes: tuple[RouteGene, ...],
    cost_evaluator: CostEvaluator,
) -> list[tuple[str, bool, int, _PublicInsertionMove, object]]:
    rows = []
    current_by_id = {route.route_id: route for route in current_routes}
    current_cost = {
        route_id: _public_route_penalised_cost(data, route, cost_evaluator)[1]
        for route_id, route in current_by_id.items()
    }
    zero_penalty_evaluator = CostEvaluator(
        [0] * data.num_load_dimensions,
        0,
        0,
    )
    current_unpenalised_cost = {
        route_id: _public_route_penalised_cost(
            data,
            route,
            zero_penalty_evaluator,
        )[1]
        for route_id, route in current_by_id.items()
    }
    search_routes = {
        route_id: _public_search_route(data, route, index)
        for index, (route_id, route) in enumerate(current_by_id.items())
    }
    inserted = SearchNode(int(inserted_customer))
    for index, move in enumerate(moves):
        changed = move.replacement
        if inserted_customer not in changed.customer_ids:
            raise ValueError("public insertion move does not contain its customer")
        route_id = changed.route_id
        if route_id in current_by_id:
            original = current_by_id[route_id]
            position = changed.customer_ids.index(inserted_customer)
            without_inserted = (
                changed.customer_ids[:position] + changed.customer_ids[position + 1 :]
            )
            if without_inserted != original.customer_ids:
                raise ValueError("public insertion move changes another customer")
            route = search_routes[route_id]
            score = int(
                insert_cost(
                    inserted,
                    route[position],
                    data,
                    cost_evaluator,
                )
            )
            unpenalised_delta = int(
                insert_cost(
                    inserted,
                    route[position],
                    data,
                    zero_penalty_evaluator,
                )
            )
            candidate_penalty = (
                current_cost[route_id]
                - current_unpenalised_cost[route_id]
                + score
                - unpenalised_delta
            )
            feasible = candidate_penalty == 0
        else:
            feasible, candidate_cost = _public_route_penalised_cost(
                data,
                changed,
                cost_evaluator,
            )
            score = int(candidate_cost)
        rows.append(
            (
                f"{index:08d}",
                feasible,
                int(score),
                move,
                route_id,
            )
        )
    for route in search_routes.values():
        route.clear()
    return rows


def _public_search_route(
    data: ProblemData,
    gene: RouteGene,
    index: int,
) -> SearchRoute:
    """Build one IndependentKernel search route for exact compiled insertion deltas."""

    route = SearchRoute(data, int(index), int(gene.vehicle_type))
    for customer in gene.customer_ids:
        route.append(SearchNode(int(customer)))
    route.update()
    return route


def _public_route_penalised_cost(
    data: ProblemData,
    gene: RouteGene,
    cost_evaluator: CostEvaluator,
) -> tuple[bool, int]:
    route = Route(
        data,
        [int(customer) for customer in gene.customer_ids],
        int(gene.vehicle_type),
    )
    vehicle_type = data.vehicle_type(int(gene.vehicle_type))
    cost = (
        int(vehicle_type.fixed_cost)
        + int(route.distance_cost())
        + int(route.duration_cost())
        + int(vehicle_type.unit_overtime_cost) * int(route.overtime())
        - int(route.prizes())
        + int(cost_evaluator.tw_penalty(route.time_warp()))
        + int(
            cost_evaluator.dist_penalty(
                route.distance(),
                vehicle_type.max_distance,
            )
        )
    )
    for dimension, excess in enumerate(route.excess_load()):
        capacity = int(vehicle_type.capacity[dimension])
        cost += int(
            cost_evaluator.load_penalty(
                capacity + int(excess),
                capacity,
                dimension,
            )
        )
    return bool(route.is_feasible()), int(cost)


def _solution_from_genes(
    data: ProblemData,
    routes: Iterable[RouteGene],
) -> Solution:
    return Solution(
        data,
        [
            Route(
                data,
                [int(customer) for customer in route.customer_ids],
                int(route.vehicle_type),
            )
            for route in routes
            if route.customer_ids
        ],
    )
