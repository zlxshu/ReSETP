"""Late-stage native route VNS for the isolated MDA-ILS-VNS prototype."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from pyvrp import Solution
from pyvrp.search import LocalSearch


LATE_START_FRACTION = 0.70


@dataclass(frozen=True)
class LateStageArm:
    name: str
    period: int | None


LATE_STAGE_ARMS: dict[str, LateStageArm] = {
    "foundation": LateStageArm("foundation", None),
    "late_vns_500": LateStageArm("late_vns_500", 500),
    "late_vns_250": LateStageArm("late_vns_250", 250),
}


def should_run_scheduled_vns(
    call: int,
    progress: float,
    period: int | None,
) -> bool:
    """Returns whether the frozen late-stage schedule fires."""
    if period is None:
        return False
    if call <= 0 or period <= 0:
        raise ValueError("call and period must be positive")
    return progress >= LATE_START_FRACTION and call % period == 0


class ScheduledRouteVNS:
    """Runs SwapStar on records and at a sparse late-stage cadence."""

    def __init__(
        self,
        node_search: LocalSearch,
        record_route_search: LocalSearch,
        scheduled_route_search: LocalSearch,
        arm: LateStageArm,
        *,
        runtime_budget: float | None,
        iteration_budget: int | None,
    ):
        if arm.period is None:
            raise ValueError("scheduled wrapper requires a period")
        if (runtime_budget is None) == (iteration_budget is None):
            raise ValueError("provide exactly one progress budget")
        self._node_search = node_search
        self._record_route_search = record_route_search
        self._scheduled_route_search = scheduled_route_search
        self._arm = arm
        self._runtime_budget = runtime_budget
        self._iteration_budget = iteration_budget
        self._started = time.perf_counter()
        self._regular_calls = 0
        self._exhaustive_calls = 0
        self._record_route_calls = 0
        self._scheduled_route_calls = 0
        self._record_improvements = 0
        self._scheduled_improvements = 0
        self._route_seconds = 0.0
        self._record_gain = 0
        self._scheduled_gain = 0

    def progress(self) -> float:
        if self._runtime_budget is not None:
            value = (time.perf_counter() - self._started) / self._runtime_budget
        else:
            value = self._regular_calls / int(self._iteration_budget)
        return min(1.0, max(0.0, value))

    def _intensify(
        self,
        candidate: Solution,
        cost_evaluator: Any,
        *,
        scheduled: bool,
    ) -> Solution:
        before = int(cost_evaluator.penalised_cost(candidate))
        started = time.perf_counter()
        search = (
            self._scheduled_route_search if scheduled else self._record_route_search
        )
        intensified = search.intensify(
            candidate,
            cost_evaluator,
        )
        self._route_seconds += time.perf_counter() - started
        after = int(cost_evaluator.penalised_cost(intensified))
        gain = max(0, before - after)
        if scheduled:
            self._scheduled_route_calls += 1
            self._scheduled_improvements += int(after < before)
            self._scheduled_gain += gain
        else:
            self._record_route_calls += 1
            self._record_improvements += int(after < before)
            self._record_gain += gain
        return intensified

    def __call__(
        self,
        solution: Solution,
        cost_evaluator: Any,
        exhaustive: bool = False,
    ) -> Solution:
        candidate = self._node_search(
            solution,
            cost_evaluator,
            exhaustive=exhaustive,
        )
        if exhaustive:
            self._exhaustive_calls += 1
            return self._intensify(
                candidate,
                cost_evaluator,
                scheduled=False,
            )

        self._regular_calls += 1
        if should_run_scheduled_vns(
            self._regular_calls,
            self.progress(),
            self._arm.period,
        ):
            return self._intensify(
                candidate,
                cost_evaluator,
                scheduled=True,
            )
        return candidate

    def diagnostics(self) -> dict[str, Any]:
        def operator_stats(search: LocalSearch) -> list[dict[str, Any]]:
            rows = []
            for operator in search.route_operators:
                stats = operator.statistics
                rows.append(
                    {
                        "operator": type(operator).__name__,
                        "evaluations": int(stats.num_evaluations),
                        "applications": int(stats.num_applications),
                    }
                )
            return rows

        return {
            "regular_calls": self._regular_calls,
            "exhaustive_calls": self._exhaustive_calls,
            "late_start_fraction": LATE_START_FRACTION,
            "period": self._arm.period,
            "record_route_calls": self._record_route_calls,
            "scheduled_route_calls": self._scheduled_route_calls,
            "record_improvements": self._record_improvements,
            "scheduled_improvements": self._scheduled_improvements,
            "record_gain": self._record_gain,
            "scheduled_gain": self._scheduled_gain,
            "route_seconds": self._route_seconds,
            "record_route_operator_statistics": operator_stats(
                self._record_route_search
            ),
            "scheduled_route_operator_statistics": operator_stats(
                self._scheduled_route_search
            ),
        }
