"""Event-driven PyVRP 0.13.4 ILS loop for MPILS-MVNS-C2-R1.

This file is a modified copy of PyVRP 0.13.4's
``pyvrp/IteratedLocalSearch.py``.  The upstream file SHA-256, release
identity, copyright notice, and MIT license are preserved in ``UPSTREAM.md``
and ``LICENSE-PYVRP.md`` beside this file.

ReSETP modification:

* add an optional before-search hook that may request one replacement
  perturbation;
* add an optional after-iteration event that exposes the real ILS acceptance
  and best-improvement outcomes;
* leave the upstream restart, late-acceptance, penalty, statistics, and
  exhaustive-on-best semantics unchanged.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol, TYPE_CHECKING

from pyvrp.ProgressPrinter import ProgressPrinter
from pyvrp.Result import Result
from pyvrp.RingBuffer import RingBuffer
from pyvrp.Statistics import Statistics

if TYPE_CHECKING:
    from pyvrp.IteratedLocalSearch import IteratedLocalSearchParams
    from pyvrp.PenaltyManager import PenaltyManager
    from pyvrp._pyvrp import (
        CostEvaluator,
        ProblemData,
        RandomNumberGenerator,
        Solution,
    )
    from pyvrp.search.SearchMethod import SearchMethod
    from pyvrp.stop.StoppingCriterion import StoppingCriterion


@dataclass(frozen=True)
class SearchDirective:
    """Decision made before one ordinary ILS search call."""

    use_replacement: bool = False
    strength: int = 1


@dataclass(frozen=True)
class IterationEvent:
    """Truth observed after PyVRP's normal acceptance decision."""

    iteration: int
    previous_current: Solution
    candidate: Solution
    current: Solution
    best: Solution
    cost_evaluator: CostEvaluator
    candidate_accepted: bool
    best_improved: bool
    used_replacement: bool
    search_seconds: float


class EventHooks(Protocol):
    """Optional event interface used by the C2 controller."""

    def before_search(
        self,
        *,
        iteration: int,
        iterations_without_improvement: int,
        current: Solution,
        best: Solution,
        cost_evaluator: CostEvaluator,
    ) -> SearchDirective:
        ...

    def after_iteration(self, event: IterationEvent) -> None:
        ...


class EventDrivenIteratedLocalSearch:
    """PyVRP 0.13.4 ILS with optional, auditable event hooks."""

    def __init__(
        self,
        data: ProblemData,
        penalty_manager: PenaltyManager,
        rng: RandomNumberGenerator,
        search_method: SearchMethod,
        initial_solution: Solution,
        params: IteratedLocalSearchParams,
        *,
        event_hooks: EventHooks | None = None,
    ):
        self._data = data
        self._pm = penalty_manager
        self._rng = rng
        self._search = search_method
        self._init = initial_solution
        self._params = params
        self._events = event_hooks

    def _search_once(
        self,
        solution: Solution,
        cost_evaluator: CostEvaluator,
        *,
        exhaustive: bool,
        directive: SearchDirective | None = None,
    ) -> Solution:
        if directive is not None and directive.use_replacement:
            method = getattr(self._search, "search_with_directive", None)
            if method is None:
                raise TypeError(
                    "replacement directive requires search_with_directive()"
                )
            return method(
                solution,
                cost_evaluator,
                exhaustive=exhaustive,
                directive=directive,
            )

        return self._search(
            solution,
            cost_evaluator,
            exhaustive=exhaustive,
        )

    def run(
        self,
        stop: StoppingCriterion,
        collect_stats: bool = True,
        display: bool = False,
        display_interval: float = 5.0,
    ) -> Result:
        """Runs the upstream ILS semantics plus optional C2 events."""

        print_progress = ProgressPrinter(display, display_interval)
        print_progress.start(self._data)

        history: RingBuffer[Solution] = RingBuffer(
            self._params.history_length
        )
        stats = Statistics(collect_stats=collect_stats)

        start = time.perf_counter()
        iters = iters_no_improvement = 0
        best = curr = self._init

        cost_eval = self._pm.cost_evaluator()
        while not stop(cost_eval.cost(best)):
            iters += 1

            if (
                iters_no_improvement
                == self._params.num_iters_no_improvement
            ):
                print_progress.restart()
                history.clear()

                curr = best
                iters_no_improvement = 0

            cost_eval = self._pm.cost_evaluator()
            previous_current = curr
            directive = None
            best_cost_before = None
            search_started = 0.0
            if self._events is not None:
                directive = self._events.before_search(
                    iteration=iters,
                    iterations_without_improvement=(
                        iters_no_improvement
                    ),
                    current=curr,
                    best=best,
                    cost_evaluator=cost_eval,
                )
                best_cost_before = cost_eval.cost(best)
                search_started = time.perf_counter()

            cand = self._search_once(
                curr,
                cost_eval,
                exhaustive=False,
                directive=directive,
            )
            used_replacement = bool(
                getattr(self._search, "last_used_replacement", False)
            )
            search_seconds = (
                time.perf_counter() - search_started
                if self._events is not None
                else 0.0
            )
            self._pm.register(cand)

            iters_no_improvement += 1
            if cost_eval.cost(cand) < cost_eval.cost(best):
                best = cand
                iters_no_improvement = 0

                if self._params.exhaustive_on_best:
                    cand = self._search_once(
                        cand,
                        cost_eval,
                        exhaustive=True,
                    )
                    if cand.is_feasible():
                        best = cand

            cand_cost = cost_eval.penalised_cost(cand)
            curr_cost = cost_eval.penalised_cost(curr)

            late_cost = cost_eval.penalised_cost(self._init)
            if (late := history.peek()) is not None:
                late_cost = cost_eval.penalised_cost(late)

            candidate_accepted = False
            if cand_cost < late_cost or cand_cost < curr_cost:
                curr = cand
                curr_cost = cand_cost
                candidate_accepted = True

            if curr_cost < late_cost or late is None:
                history.append(curr)
            else:
                history.skip()

            if self._events is not None:
                assert best_cost_before is not None
                self._events.after_iteration(
                    IterationEvent(
                        iteration=iters,
                        previous_current=previous_current,
                        candidate=cand,
                        current=curr,
                        best=best,
                        cost_evaluator=cost_eval,
                        candidate_accepted=candidate_accepted,
                        best_improved=(
                            cost_eval.cost(best) < best_cost_before
                        ),
                        used_replacement=used_replacement,
                        search_seconds=search_seconds,
                    )
                )

            stats.collect(curr, cand, best, cost_eval)
            print_progress.iteration(stats)

        runtime = time.perf_counter() - start
        res = Result(best, stats, iters, runtime)

        print_progress.end(res)
        return res
