"""Public fast SREX arm kept separate from the frozen PyVRP baseline.

Our controller calls PyVRP 0.12.2's compiled Nagata--Kobayashi SREX without
modifying baseline code.  Private and dynamic search deliberately do not call
this route-only operator; their fast crossover exchanges complete multi-trip
assignments in :mod:`setp_solver.algorithms.duty_hgs.crossover`.
"""

from __future__ import annotations

from pyvrp import CostEvaluator, ProblemData, RandomNumberGenerator, Solution
from pyvrp.crossover import selective_route_exchange as pyvrp_srex

PUBLIC_SREX_WORK_UNITS = 2


def public_srex(
    parents: tuple[Solution, Solution],
    data: ProblemData,
    cost_evaluator: CostEvaluator,
    rng: RandomNumberGenerator,
) -> Solution:
    """Run the unmodified compiled SREX as one arm of our own controller."""

    return pyvrp_srex(parents, data, cost_evaluator, rng)
