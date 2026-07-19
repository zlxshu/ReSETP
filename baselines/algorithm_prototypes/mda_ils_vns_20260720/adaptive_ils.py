"""AILS-II-inspired adaptive control for the isolated MDA-ILS-VNS prototype.

This is a clean-room Python implementation of the frozen project contract. It
uses PyVRP's native perturbation and local-search machinery, but adjusts the
perturbation strength from sparsely sampled, post-search structural distances.
No AILS-II source code is copied.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
import time
from typing import Any, Sequence

from pyvrp import ProblemData, RandomNumberGenerator, Solution, SolveParams
from pyvrp.IteratedLocalSearch import IteratedLocalSearchParams
from pyvrp.ProgressPrinter import ProgressPrinter
from pyvrp.Result import Result
from pyvrp.RingBuffer import RingBuffer
from pyvrp.Statistics import Statistics
from pyvrp.search import (
    LocalSearch,
    PerturbationManager,
    PerturbationParams,
    compute_neighbours,
)

from selective_route_vns import SelectiveRouteVNS


STRENGTH_LEVELS = (4, 8, 12, 16, 20, 25, 30, 40)
GAMMA = 30
SAMPLE_POSITIONS = (10, 20, 30)


@dataclass(frozen=True)
class AdaptiveArm:
    name: str
    d_max: float | None
    d_min: float | None
    adaptive_acceptance: bool = False


ADAPTIVE_ARMS: dict[str, AdaptiveArm] = {
    "foundation": AdaptiveArm("foundation", None, None),
    "adaptive_d20_10": AdaptiveArm(
        "adaptive_d20_10",
        20.0,
        10.0,
    ),
    "adaptive_d30_15": AdaptiveArm(
        "adaptive_d30_15",
        30.0,
        15.0,
    ),
    "adaptive_da30_15": AdaptiveArm(
        "adaptive_da30_15",
        30.0,
        15.0,
        adaptive_acceptance=True,
    ),
}


def structural_distance_from_neighbours(
    reference: Sequence[tuple[int, int] | None],
    candidate: Sequence[tuple[int, int] | None],
    num_depots: int,
) -> int:
    """Returns the frozen multi-depot AILS-style structural distance."""
    if len(reference) != len(candidate):
        raise ValueError("neighbour vectors must have equal length")
    if not 0 <= num_depots <= len(reference):
        raise ValueError("invalid number of depots")

    distance = 0
    for client in range(num_depots, len(reference)):
        ref_neighbours = reference[client]
        cand_neighbours = candidate[client]
        if ref_neighbours is None or cand_neighbours is None:
            if ref_neighbours != cand_neighbours:
                distance += 1
            continue

        cand_successor = cand_neighbours[1]
        if cand_successor not in ref_neighbours:
            distance += 1

        cand_touches_depot = any(
            neighbour < num_depots for neighbour in cand_neighbours
        )
        ref_touches_depot = any(neighbour < num_depots for neighbour in ref_neighbours)
        if cand_touches_depot and not ref_touches_depot:
            distance += 1

    return distance


def structural_distance(
    reference: Solution,
    candidate: Solution,
    num_depots: int,
) -> int:
    """Returns structural distance between two complete PyVRP solutions."""
    return structural_distance_from_neighbours(
        reference.neighbours(),
        candidate.neighbours(),
        num_depots,
    )


def nearest_strength(value: float) -> int:
    """Snaps a continuous strength to a frozen level; ties go lower."""
    return min(STRENGTH_LEVELS, key=lambda level: (abs(level - value), level))


def updated_strength(
    current: int,
    target_distance: float,
    actual_average_distance: float,
) -> int:
    """Applies the frozen feedback update and clips to available levels."""
    if target_distance <= 0:
        raise ValueError("target distance must be positive")
    if actual_average_distance < 0:
        raise ValueError("actual distance cannot be negative")
    if actual_average_distance == 0:
        return STRENGTH_LEVELS[-1]
    return nearest_strength(current * target_distance / actual_average_distance)


def _build_fixed_search(
    data: ProblemData,
    rng: RandomNumberGenerator,
    params: SolveParams,
    neighbours: list[list[int]],
    strength: int,
) -> LocalSearch:
    """Builds one PyVRP search with a fixed perturbation strength."""
    search = LocalSearch(
        data,
        rng,
        neighbours,
        PerturbationManager(PerturbationParams(strength, strength)),
    )
    for operator in params.node_ops:
        if operator.supports(data):
            search.add_node_operator(operator(data))
    return search


class AdaptiveSearch:
    """Selects native PyVRP perturbation strength using distance feedback."""

    def __init__(
        self,
        data: ProblemData,
        rng: RandomNumberGenerator,
        params: SolveParams,
        record_search: SelectiveRouteVNS,
        arm: AdaptiveArm,
        *,
        runtime_budget: float | None,
        iteration_budget: int | None,
    ):
        if arm.d_max is None or arm.d_min is None:
            raise ValueError("adaptive search requires distance targets")
        if (runtime_budget is None) == (iteration_budget is None):
            raise ValueError("provide exactly one progress budget")

        self._data = data
        self._record_search = record_search
        self._arm = arm
        self._runtime_budget = runtime_budget
        self._iteration_budget = iteration_budget
        self._started = time.perf_counter()
        neighbours = compute_neighbours(data, params.neighbourhood)
        self._searches = {
            level: _build_fixed_search(
                data,
                rng,
                params,
                neighbours,
                level,
            )
            for level in STRENGTH_LEVELS
        }
        self._strength = nearest_strength(arm.d_max)
        self._calls = 0
        self._samples: list[int] = []
        self._sample_seconds = 0.0
        self._strength_usage: Counter[int] = Counter()
        self._updates: list[dict[str, float | int]] = []

    def progress(self) -> float:
        """Returns bounded run progress for target scheduling."""
        if self._runtime_budget is not None:
            progress = (time.perf_counter() - self._started) / self._runtime_budget
        else:
            progress = self._calls / int(self._iteration_budget)
        return min(1.0, max(0.0, progress))

    def target_distance(self) -> float:
        """Returns the linearly tightening target frozen in the contract."""
        progress = self.progress()
        return float(self._arm.d_max + (self._arm.d_min - self._arm.d_max) * progress)

    def __call__(
        self,
        solution: Solution,
        cost_evaluator: Any,
        exhaustive: bool = False,
    ) -> Solution:
        if exhaustive:
            return self._record_search(
                solution,
                cost_evaluator,
                exhaustive=True,
            )

        self._calls += 1
        self._strength_usage[self._strength] += 1
        candidate = self._searches[self._strength](
            solution,
            cost_evaluator,
            exhaustive=False,
        )

        block_position = (self._calls - 1) % GAMMA + 1
        if block_position in SAMPLE_POSITIONS:
            started = time.perf_counter()
            self._samples.append(
                structural_distance(
                    solution,
                    candidate,
                    self._data.num_depots,
                )
            )
            self._sample_seconds += time.perf_counter() - started

        if block_position == GAMMA:
            actual = sum(self._samples) / len(self._samples)
            target = self.target_distance()
            old = self._strength
            self._strength = updated_strength(old, target, actual)
            self._updates.append(
                {
                    "call": self._calls,
                    "progress": self.progress(),
                    "target_distance": target,
                    "actual_average_distance": actual,
                    "old_strength": old,
                    "new_strength": self._strength,
                }
            )
            self._samples.clear()

        return candidate

    def diagnostics(self) -> dict[str, Any]:
        """Returns an auditable adaptive-control ledger."""
        return {
            "calls": self._calls,
            "gamma": GAMMA,
            "sample_positions": list(SAMPLE_POSITIONS),
            "sample_seconds": self._sample_seconds,
            "current_strength": self._strength,
            "strength_usage": {
                str(level): int(self._strength_usage[level])
                for level in STRENGTH_LEVELS
            },
            "num_updates": len(self._updates),
            "updates": self._updates,
            "record_search": self._record_search.diagnostics(),
        }


class AdaptiveAcceptance:
    """Recent-block threshold acceptance frozen for one candidate arm."""

    def __init__(self, initial_cost: int, block_size: int = GAMMA):
        self._previous_block_best = int(initial_cost)
        self._block_size = block_size
        self._block_costs: list[int] = []
        self._recent: deque[int] = deque(maxlen=block_size)
        self._accepted = 0
        self._evaluated = 0
        self._last_eta = 1.0
        self._last_threshold = float(initial_cost)

    def accept(
        self,
        candidate_cost: int,
        current_cost: int,
        progress: float,
    ) -> bool:
        """Records a candidate and applies the pre-registered threshold."""
        progress = min(1.0, max(0.0, progress))
        eta = (0.01) ** progress
        self._recent.append(int(candidate_cost))
        self._block_costs.append(int(candidate_cost))
        recent_mean = sum(self._recent) / len(self._recent)
        threshold = self._previous_block_best + eta * (
            recent_mean - self._previous_block_best
        )
        accepted = (
            int(candidate_cost) < int(current_cost) or int(candidate_cost) <= threshold
        )

        self._evaluated += 1
        self._accepted += int(accepted)
        self._last_eta = eta
        self._last_threshold = threshold

        if len(self._block_costs) == self._block_size:
            self._previous_block_best = min(self._block_costs)
            self._block_costs.clear()

        return accepted

    def diagnostics(self) -> dict[str, float | int]:
        return {
            "evaluated": self._evaluated,
            "accepted": self._accepted,
            "acceptance_rate": (
                self._accepted / self._evaluated if self._evaluated else 0.0
            ),
            "last_eta": self._last_eta,
            "last_threshold": self._last_threshold,
            "previous_block_best": self._previous_block_best,
        }


class AdaptiveIteratedLocalSearch:
    """PyVRP ILS control flow with frozen adaptive acceptance as an option."""

    def __init__(
        self,
        data: ProblemData,
        penalty_manager: Any,
        search_method: AdaptiveSearch,
        initial_solution: Solution,
        params: IteratedLocalSearchParams,
        *,
        adaptive_acceptance: bool,
    ):
        self._data = data
        self._pm = penalty_manager
        self._search = search_method
        self._init = initial_solution
        self._params = params
        self._adaptive_acceptance = adaptive_acceptance
        self._acceptance: AdaptiveAcceptance | None = None

    def run(
        self,
        stop: Any,
        collect_stats: bool = True,
        display: bool = False,
        display_interval: float = 5.0,
    ) -> Result:
        """Runs the adaptive ILS while preserving PyVRP's native search."""
        print_progress = ProgressPrinter(display, display_interval)
        print_progress.start(self._data)
        history: RingBuffer[Solution] = RingBuffer(self._params.history_length)
        stats = Statistics(collect_stats=collect_stats)

        start = time.perf_counter()
        iters = iters_no_improvement = 0
        best = curr = self._init
        cost_eval = self._pm.cost_evaluator()
        initial_penalised = int(cost_eval.penalised_cost(self._init))
        self._acceptance = AdaptiveAcceptance(initial_penalised)

        while not stop(cost_eval.cost(best)):
            iters += 1
            if iters_no_improvement == self._params.num_iters_no_improvement:
                print_progress.restart()
                history.clear()
                curr = best
                iters_no_improvement = 0

            cost_eval = self._pm.cost_evaluator()
            cand = self._search(curr, cost_eval, exhaustive=False)
            self._pm.register(cand)

            iters_no_improvement += 1
            if cost_eval.cost(cand) < cost_eval.cost(best):
                best = cand
                iters_no_improvement = 0
                if self._params.exhaustive_on_best:
                    cand = self._search(
                        cand,
                        cost_eval,
                        exhaustive=True,
                    )
                    if cand.is_feasible():
                        best = cand

            cand_cost = int(cost_eval.penalised_cost(cand))
            curr_cost = int(cost_eval.penalised_cost(curr))
            if self._adaptive_acceptance:
                if self._acceptance.accept(
                    cand_cost,
                    curr_cost,
                    self._search.progress(),
                ):
                    curr = cand
                    curr_cost = cand_cost
            else:
                late_cost = int(cost_eval.penalised_cost(self._init))
                if (late := history.peek()) is not None:
                    late_cost = int(cost_eval.penalised_cost(late))
                if cand_cost < late_cost or cand_cost < curr_cost:
                    curr = cand
                    curr_cost = cand_cost
                if curr_cost < late_cost or late is None:
                    history.append(curr)
                else:
                    history.skip()

            stats.collect(curr, cand, best, cost_eval)
            print_progress.iteration(stats)

        result = Result(
            best,
            stats,
            iters,
            time.perf_counter() - start,
        )
        print_progress.end(result)
        return result

    def diagnostics(self) -> dict[str, Any]:
        return {
            "adaptive_acceptance": self._adaptive_acceptance,
            "acceptance": (
                self._acceptance.diagnostics() if self._acceptance is not None else None
            ),
        }
