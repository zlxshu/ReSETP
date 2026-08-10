"""Public fast SREX arm from the independently copied foundation kernel.

Our controller calls the copied 0.12.2 compiled Nagata--Kobayashi SREX.  The
frozen open baseline is a separate environment and process.  Private and
dynamic search deliberately do not call
this route-only operator; their fast crossover exchanges complete multi-trip
assignments in :mod:`setp_solver.algorithms.problem_hgs.crossover`.
"""

from __future__ import annotations

from setp_hgs_kernel import CostEvaluator, ProblemData, RandomNumberGenerator, Solution
from setp_hgs_kernel.crossover import selective_route_exchange as kernel_srex

PUBLIC_SREX_WORK_UNITS = 2


def public_srex(
    parents: tuple[Solution, Solution],
    data: ProblemData,
    cost_evaluator: CostEvaluator,
    rng: RandomNumberGenerator,
) -> Solution:
    """Run copied compiled SREX as one arm of the project controller."""

    return kernel_srex(parents, data, cost_evaluator, rng)
