"""Project-local ALNS operator selection for the ReSETP backend.

Adapted from N-Wouda/alns 7.0.0 (MIT License). Only AlphaUCB and its minimal
base validation are retained because that is the only selector used here.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np


class OperatorSelectionScheme:
    def __init__(self, num_destroy: int, num_repair: int, op_coupling: np.ndarray | None = None) -> None:
        if op_coupling is not None:
            op_coupling = np.asarray(op_coupling, dtype=bool)
            op_coupling = np.atleast_2d(op_coupling)
        else:
            op_coupling = np.ones((num_destroy, num_repair), dtype=bool)

        self._validate_arguments(num_destroy, num_repair, op_coupling)
        self._num_destroy = num_destroy
        self._num_repair = num_repair
        self._op_coupling = op_coupling

    @property
    def num_destroy(self) -> int:
        return self._num_destroy

    @property
    def num_repair(self) -> int:
        return self._num_repair

    @property
    def op_coupling(self) -> np.ndarray:
        return self._op_coupling

    @staticmethod
    def _validate_arguments(num_destroy: int, num_repair: int, op_coupling: np.ndarray) -> None:
        if num_destroy <= 0 or num_repair <= 0:
            raise ValueError("Missing destroy or repair operators.")
        if op_coupling.shape != (num_destroy, num_repair):
            raise ValueError(
                f"Coupling matrix of shape {op_coupling.shape}, expected {(num_destroy, num_repair)}."
            )

        d_idcs = np.flatnonzero(np.count_nonzero(op_coupling, axis=1) == 0)
        if d_idcs.size != 0:
            raise ValueError(f"Destroy op. {d_idcs[0]} has no coupled repair operators.")


class AlphaUCB(OperatorSelectionScheme):
    def __init__(
        self,
        scores: Sequence[float],
        alpha: float,
        num_destroy: int,
        num_repair: int,
        op_coupling: np.ndarray | None = None,
    ) -> None:
        super().__init__(num_destroy, num_repair, op_coupling)
        if not (0 <= alpha <= 1):
            raise ValueError(f"Alpha {alpha:} outside [0, 1] not understood.")
        if any(score < 0 for score in scores):
            raise ValueError("Negative scores are not understood.")
        if len(scores) < 4:
            raise ValueError(f"Expected four scores, found {len(scores)}")

        self._scores = list(scores)
        self._alpha = alpha
        self._avg_rewards = np.ones_like(self._op_coupling, dtype=float)
        self._times = np.zeros_like(self._op_coupling, dtype=int)
        self._iter = 0

    @property
    def scores(self) -> list[float]:
        return self._scores

    @property
    def alpha(self) -> float:
        return self._alpha

    def __call__(self, rng: object, best: object, curr: object) -> tuple[int, int]:
        action = np.argmax(self._values())
        return tuple(int(value) for value in np.unravel_index(action, self.op_coupling.shape))

    def update(self, candidate: object, d_idx: int, r_idx: int, outcome: int) -> None:
        t_a = self._times[d_idx, r_idx]
        reward = self._avg_rewards[d_idx, r_idx]
        avg_reward = (t_a * reward + self.scores[outcome]) / (t_a + 1)

        self._avg_rewards[d_idx, r_idx] = avg_reward
        self._times[d_idx, r_idx] += 1
        self._iter += 1

    def _values(self) -> np.ndarray:
        value = self._avg_rewards
        explore_bonus = np.sqrt((self.alpha * np.log(1 + self._iter)) / (self._times + 1))
        values = value + explore_bonus
        values[~self._op_coupling] = -1
        return values
