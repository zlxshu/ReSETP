"""Execution-cost-aware control of the fast/DCREX portfolio.

Maturana et al. (2009, Sections II-A and III-A, Figure 2) describe two
properties used here: an application that does not improve the measured
quality normally receives zero credit, and positive credit is divided by the
operator execution time before selection.  The two pipelines here differ by
more than an order of magnitude, so counting both as one nominal generation
is not a faithful cost measure.  Clipping non-improvements to zero is also
essential mathematically: dividing a negative reward by a larger cost would
move it closer to zero and accidentally favour the slower damaging action.

The controller keeps discounted mean execution times and expresses each arm's
cost relative to the fastest observed arm.  This makes the cost ratio
unit-free: changing the clock from seconds to milliseconds cannot change the
selection process.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import StrEnum

from .dcrex import DISCOUNT_FACTOR, DiscountedUCB1


class CrossoverAction(StrEnum):
    FAST = "FAST"
    DCREX = "DCREX"


CROSSOVER_ACTIONS = tuple(CrossoverAction)


@dataclass(frozen=True)
class CrossoverReward:
    action: CrossoverAction
    raw_reward: float
    credited_reward: float
    execution_seconds: float
    relative_execution_cost: float
    reward_per_relative_cost: float


class RuntimeAwareCrossoverController:
    """Choose between fast crossover and DCREX by improvement per cost."""

    def __init__(self, *, gamma: float = DISCOUNT_FACTOR) -> None:
        if not 0.0 < float(gamma) <= 1.0:
            raise ValueError("crossover discount factor must be in (0, 1]")
        self.gamma = float(gamma)
        self.bandit = DiscountedUCB1(len(CROSSOVER_ACTIONS), gamma=gamma)
        self._time_counts = [0.0] * len(CROSSOVER_ACTIONS)
        self._time_totals = [0.0] * len(CROSSOVER_ACTIONS)

    def select(self, rng: random.Random) -> CrossoverAction:
        return CROSSOVER_ACTIONS[self.bandit.select(rng)]

    @property
    def mean_execution_seconds(self) -> tuple[float | None, ...]:
        return tuple(
            total / count if count > 0.0 else None
            for total, count in zip(
                self._time_totals,
                self._time_counts,
                strict=True,
            )
        )

    def update(
        self,
        action: CrossoverAction,
        raw_reward: float,
        execution_seconds: float,
    ) -> CrossoverReward:
        if not math.isfinite(float(raw_reward)):
            raise ValueError("crossover reward must be finite")
        elapsed = float(execution_seconds)
        if not math.isfinite(elapsed) or elapsed <= 0.0:
            raise ValueError("crossover execution time must be positive and finite")

        action = CrossoverAction(action)
        action_index = CROSSOVER_ACTIONS.index(action)
        self._time_counts = [
            self.gamma * value for value in self._time_counts
        ]
        self._time_totals = [
            self.gamma * value for value in self._time_totals
        ]
        self._time_counts[action_index] += 1.0
        self._time_totals[action_index] += elapsed

        means = self.mean_execution_seconds
        observed = [value for value in means if value is not None]
        fastest = min(observed)
        action_mean = means[action_index]
        if action_mean is None:
            raise AssertionError("updated crossover arm has no time estimate")
        relative_cost = action_mean / fastest
        credited = max(0.0, float(raw_reward))
        adjusted = credited / relative_cost
        self.bandit.update(action_index, adjusted)
        return CrossoverReward(
            action=action,
            raw_reward=float(raw_reward),
            credited_reward=credited,
            execution_seconds=elapsed,
            relative_execution_cost=relative_cost,
            reward_per_relative_cost=adjusted,
        )
