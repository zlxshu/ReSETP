from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Collection

from setp_hgs_kernel.ProgressPrinter import ProgressPrinter
from setp_hgs_kernel.Result import Result
from setp_hgs_kernel.Statistics import Statistics
from setp_hgs_kernel.HGSControl import HGSControl

if TYPE_CHECKING:
    from setp_hgs_kernel.PenaltyManager import PenaltyManager
    from setp_hgs_kernel.Population import Population
    from setp_hgs_kernel._setp_hgs_kernel import (
        CostEvaluator,
        ProblemData,
        RandomNumberGenerator,
        Solution,
    )
    from setp_hgs_kernel.search.SearchMethod import SearchMethod
    from setp_hgs_kernel.stop.StoppingCriterion import StoppingCriterion


@dataclass
class GeneticAlgorithmParams:
    """
    Parameters for the genetic algorithm.

    Parameters
    ----------
    repair_probability
        Probability (in :math:`[0, 1]`) of repairing an infeasible solution.
        If the reparation makes the solution feasible, it is also added to
        the population in the same iteration.
    num_iters_no_improvement
        Number of iterations without any improvement needed before a restart
        occurs.

    Attributes
    ----------
    repair_probability
        Probability of repairing an infeasible solution.
    num_iters_no_improvement
        Number of iterations without improvement before a restart occurs.

    Raises
    ------
    ValueError
        When ``repair_probability`` is not in :math:`[0, 1]`, or
        ``num_iters_no_improvement`` is negative.
    """

    repair_probability: float = 0.80
    num_iters_no_improvement: int = 20_000

    def __post_init__(self):
        if not 0 <= self.repair_probability <= 1:
            raise ValueError("repair_probability must be in [0, 1].")

        if self.num_iters_no_improvement < 0:
            raise ValueError("num_iters_no_improvement < 0 not understood.")


class GeneticAlgorithm:
    """
    Creates a GeneticAlgorithm instance.

    Parameters
    ----------
    data
        Data object describing the problem to be solved.
    penalty_manager
        Penalty manager to use.
    rng
        Random number generator.
    population
        Population to use.
    search_method
        Search method to use.
    crossover_op
        Crossover operator to use for generating offspring.
    initial_solutions
        Initial solutions to use to initialise the population.
    params
        Genetic algorithm parameters. If not provided, a default will be used.

    Raises
    ------
    ValueError
        When the population is empty.
    """

    def __init__(
        self,
        data: ProblemData,
        penalty_manager: PenaltyManager,
        rng: RandomNumberGenerator,
        population: Population,
        search_method: SearchMethod,
        crossover_op: Callable[
            [
                tuple[Solution, Solution],
                ProblemData,
                CostEvaluator,
                RandomNumberGenerator,
            ],
            Solution,
        ],
        initial_solutions: Collection[Solution],
        params: GeneticAlgorithmParams = GeneticAlgorithmParams(),
    ):
        if len(initial_solutions) == 0:
            raise ValueError("Expected at least one initial solution.")

        self._data = data
        self._pm = penalty_manager
        self._rng = rng
        self._pop = population
        self._search = search_method
        self._crossover = crossover_op
        self._initial_solutions = initial_solutions
        self._params = params

        # Find best feasible initial solution if any exist, else set a random
        # infeasible solution (with infinite cost) as the initial best.
        self._best = min(initial_solutions, key=self._cost_evaluator.cost)

    @property
    def _cost_evaluator(self) -> CostEvaluator:
        return self._pm.cost_evaluator()

    def run(
        self,
        stop: StoppingCriterion,
        collect_stats: bool = True,
        display: bool = False,
        display_interval: float = 5.0,
    ):
        """
        Runs the genetic algorithm with the provided stopping criterion.

        Parameters
        ----------
        stop
            Stopping criterion to use. The algorithm runs until the first time
            the stopping criterion returns ``True``.
        collect_stats
            Whether to collect statistics about the solver's progress. Default
            ``True``.
        display
            Whether to display information about the solver progress. Default
            ``False``. Progress information is only available when
            ``collect_stats`` is also set.
        display_interval
            Time (in seconds) between iteration logs. Defaults to 5s.

        Returns
        -------
        Result
            A Result object, containing statistics (if collected) and the best
            found solution.
        """
        print_progress = ProgressPrinter(display, display_interval)
        print_progress.start(self._data)

        stats = Statistics(collect_stats=collect_stats)

        for sol in self._initial_solutions:
            self._pop.add(sol, self._cost_evaluator)

        def restart() -> None:
            print_progress.restart()
            self._pop.clear()
            for sol in self._initial_solutions:
                self._pop.add(sol, self._cost_evaluator)

        control = HGSControl(
            should_stop=lambda _state: stop(
                self._cost_evaluator.cost(self._best)
            ),
            best_value=lambda: self._cost_evaluator.cost(self._best),
            restart_after_iterations_without_improvement=(
                self._params.num_iters_no_improvement
            ),
            restart=restart,
            initial_iterations_without_improvement=1,
        )
        for _iteration in control.iterations():
            parents = self._pop.select(self._rng, self._cost_evaluator)
            offspring = self._crossover(
                parents, self._data, self._cost_evaluator, self._rng
            )
            self._improve_offspring(offspring)

            stats.collect_from(self._pop, self._cost_evaluator)
            print_progress.iteration(stats)

        state = control.state
        res = Result(
            self._best,
            stats,
            state.iterations,
            state.elapsed_seconds,
        )

        print_progress.end(res)

        return res

    def _improve_offspring(self, sol: Solution):
        def is_new_best(sol):
            cost = self._cost_evaluator.cost(sol)
            best_cost = self._cost_evaluator.cost(self._best)
            return cost < best_cost

        sol = self._search(sol, self._cost_evaluator)
        self._pop.add(sol, self._cost_evaluator)
        self._pm.register(sol)

        if is_new_best(sol):
            self._best = sol

        # Possibly repair if current solution is infeasible. In that case, we
        # penalise infeasibility more using a penalty booster.
        if (
            not sol.is_feasible()
            and self._rng.rand() < self._params.repair_probability
        ):
            sol = self._search(sol, self._pm.booster_cost_evaluator())

            if sol.is_feasible():
                self._pop.add(sol, self._cost_evaluator)
                self._pm.register(sol)

            if is_new_best(sol):
                self._best = sol
