"""Deterministic-work control of the final fast/DCREX portfolio.

The controller never uses wall-clock time or incomparable implementation
internals.  Each crossover reports how many complete offspring it scored
before handing one child to the shared downstream search; discounted-UCB1
learns improvement per reported offspring.
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
    deterministic_work_units: int
    reward_per_work_unit: float


class CostAwareCrossoverController:
    """Choose between a fast crossover and full DCREX by scored offspring."""

    def __init__(self, *, gamma: float = DISCOUNT_FACTOR) -> None:
        self.bandit = DiscountedUCB1(len(CROSSOVER_ACTIONS), gamma=gamma)

    def select(self, rng: random.Random) -> CrossoverAction:
        return CROSSOVER_ACTIONS[self.bandit.select(rng)]

    def update(
        self,
        action: CrossoverAction,
        raw_reward: float,
        deterministic_work_units: int,
    ) -> CrossoverReward:
        work = int(deterministic_work_units)
        if work < 1:
            raise ValueError("crossover work units must be positive")
        if not math.isfinite(float(raw_reward)):
            raise ValueError("crossover reward must be finite")
        adjusted = float(raw_reward) / work
        action = CrossoverAction(action)
        self.bandit.update(CROSSOVER_ACTIONS.index(action), adjusted)
        return CrossoverReward(action, float(raw_reward), work, adjusted)
