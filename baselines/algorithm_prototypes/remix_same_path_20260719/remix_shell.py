"""Minimal ReMIX shell for the disabled-path equivalence gate.

No performance component is implemented here.  The active modes are
deliberately limited to the mother path and two logically equivalent ways of
disabling all future enhancements.
"""

from __future__ import annotations

from dataclasses import dataclass

import pyvrp
from pyvrp.stop import MaxIterations


@dataclass(frozen=True)
class ReMixConfig:
    enabled: bool
    component_budget: int

    @property
    def enhancements_active(self) -> bool:
        return self.enabled and self.component_budget > 0


@dataclass
class ReMixCounters:
    alns_calls: int = 0
    vns_calls: int = 0
    route_pool_calls: int = 0
    mechanism_calls: int = 0

    @property
    def total_component_calls(self) -> int:
        return (
            self.alns_calls
            + self.vns_calls
            + self.route_pool_calls
            + self.mechanism_calls
        )


def solve_mother(
    data: pyvrp.ProblemData,
    *,
    seed: int,
    iterations: int,
) -> pyvrp.Result:
    return pyvrp.solve(
        data,
        stop=MaxIterations(iterations),
        seed=seed,
        collect_stats=True,
        display=False,
    )


def solve_remix(
    data: pyvrp.ProblemData,
    *,
    seed: int,
    iterations: int,
    config: ReMixConfig,
) -> tuple[pyvrp.Result, ReMixCounters]:
    counters = ReMixCounters()
    if config.enhancements_active:
        raise RuntimeError(
            "Performance enhancements are not authorised in the foundation gate."
        )
    result = solve_mother(data, seed=seed, iterations=iterations)
    return result, counters

