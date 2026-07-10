"""Project-local ALNS operator selection for the ReSETP backend.

Adapted from N-Wouda/alns 7.0.0 (MIT License). Only AlphaUCB and its minimal
base validation are retained because that is the only selector used here.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

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
        self._legal_pairs = [
            (int(d_idx), int(r_idx))
            for d_idx in range(num_destroy)
            for r_idx in range(num_repair)
            if bool(op_coupling[d_idx, r_idx])
        ]
        self._last_selection_info = self._selection_info()

    @property
    def num_destroy(self) -> int:
        return self._num_destroy

    @property
    def num_repair(self) -> int:
        return self._num_repair

    @property
    def op_coupling(self) -> np.ndarray:
        return self._op_coupling

    @property
    def legal_pairs(self) -> list[tuple[int, int]]:
        return list(self._legal_pairs)

    def last_selection_info(self) -> dict[str, Any]:
        return dict(self._last_selection_info)

    def _selection_info(
        self,
        *,
        selector_type: str = "",
        selector_phase: str = "",
        selector_iter: int = 0,
        selector_pair_times: int = 0,
        selector_value: float = math.nan,
        selector_sample: float = math.nan,
        selector_probability: float = math.nan,
        selector_epsilon: float = math.nan,
        selector_temperature: float = math.nan,
    ) -> dict[str, Any]:
        return {
            "selector_type": selector_type,
            "selector_phase": selector_phase,
            "selector_iter": int(selector_iter),
            "selector_pair_times": int(selector_pair_times),
            "selector_value": float(selector_value),
            "selector_sample": float(selector_sample),
            "selector_probability": float(selector_probability),
            "selector_epsilon": float(selector_epsilon),
            "selector_temperature": float(selector_temperature),
        }

    def _record_selection(
        self,
        d_idx: int,
        r_idx: int,
        *,
        selector_type: str,
        selector_phase: str,
        selector_value: float = math.nan,
        selector_sample: float = math.nan,
        selector_probability: float = math.nan,
        selector_epsilon: float = math.nan,
        selector_temperature: float = math.nan,
    ) -> None:
        times = 0
        if hasattr(self, "_times"):
            times = int(self._times[int(d_idx), int(r_idx)])
        self._last_selection_info = self._selection_info(
            selector_type=selector_type,
            selector_phase=selector_phase,
            selector_iter=int(getattr(self, "_iter", 0)),
            selector_pair_times=times,
            selector_value=selector_value,
            selector_sample=selector_sample,
            selector_probability=selector_probability,
            selector_epsilon=selector_epsilon,
            selector_temperature=selector_temperature,
        )

    @staticmethod
    def _rng_random(rng: object) -> float:
        return float(rng.random()) if hasattr(rng, "random") else 1.0

    @staticmethod
    def _rng_integers(rng: object, high: int) -> int:
        return int(rng.integers(0, high)) if hasattr(rng, "integers") else 0

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
        return self._argmax_pair(selector_type="alpha_ucb")

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

    def _argmax_pair(self, *, selector_type: str, selector_phase: str = "exploit") -> tuple[int, int]:
        values = self._values()
        action = int(np.argmax(values))
        d_idx, r_idx = (int(value) for value in np.unravel_index(action, self.op_coupling.shape))
        self._record_selection(
            d_idx,
            r_idx,
            selector_type=selector_type,
            selector_phase=selector_phase,
            selector_value=float(values[d_idx, r_idx]),
        )
        return d_idx, r_idx


class BalancedAlphaUCB(AlphaUCB):
    """Diagnostic selector that prevents early pair starvation.

    It preserves AlphaUCB scoring and update semantics, but adds a deterministic
    warmup pass over all legal pairs plus a small uniform exploration rate.
    """

    def __init__(
        self,
        scores: Sequence[float],
        alpha: float,
        num_destroy: int,
        num_repair: int,
        op_coupling: np.ndarray | None = None,
        *,
        warmup_per_pair: int = 10,
        epsilon: float = 0.10,
    ) -> None:
        super().__init__(scores, alpha, num_destroy, num_repair, op_coupling)
        if warmup_per_pair < 0:
            raise ValueError("warmup_per_pair must be non-negative.")
        if not 0.0 <= float(epsilon) <= 1.0:
            raise ValueError("epsilon must be in [0, 1].")
        self._warmup_per_pair = int(warmup_per_pair)
        self._epsilon = float(epsilon)

    @property
    def warmup_per_pair(self) -> int:
        return self._warmup_per_pair

    @property
    def epsilon(self) -> float:
        return self._epsilon

    @property
    def current_epsilon(self) -> float:
        return self._epsilon

    def __call__(self, rng: object, best: object, curr: object) -> tuple[int, int]:
        for d_idx, r_idx in self._legal_pairs:
            if int(self._times[d_idx, r_idx]) < self._warmup_per_pair:
                self._record_selection(
                    d_idx,
                    r_idx,
                    selector_type="balanced",
                    selector_phase="warmup",
                    selector_value=float(self._values()[d_idx, r_idx]),
                    selector_epsilon=self.current_epsilon,
                )
                return d_idx, r_idx

        random_value = self._rng_random(rng)
        epsilon = self.current_epsilon
        if epsilon > 0.0 and random_value < epsilon:
            pick = self._rng_integers(rng, len(self._legal_pairs))
            d_idx, r_idx = self._legal_pairs[pick]
            self._record_selection(
                d_idx,
                r_idx,
                selector_type="balanced",
                selector_phase="explore",
                selector_value=float(self._values()[d_idx, r_idx]),
                selector_sample=random_value,
                selector_probability=1.0 / len(self._legal_pairs),
                selector_epsilon=epsilon,
            )
            return d_idx, r_idx

        return self._argmax_pair(selector_type="balanced", selector_phase="exploit")


class MinimumCoverageAlphaUCB(AlphaUCB):
    """AlphaUCB with one legal-pair warmup and a sparse family coverage floor.

    This diagnostic selector is deliberately cheaper than ``BalancedAlphaUCB``:
    it does not force every pair ten times and has no permanent random epsilon.
    A coupling matrix can remove semantically duplicate pairs, while selected
    destroy families are refreshed only after a declared maximum gap.
    """

    def __init__(
        self,
        scores: Sequence[float],
        alpha: float,
        num_destroy: int,
        num_repair: int,
        op_coupling: np.ndarray | None = None,
        *,
        protected_destroy_indices: Sequence[int] = (),
        warmup_per_pair: int = 1,
        max_family_gap: int = 50,
    ) -> None:
        super().__init__(scores, alpha, num_destroy, num_repair, op_coupling)
        if warmup_per_pair < 0:
            raise ValueError("warmup_per_pair must be non-negative.")
        if max_family_gap < 1:
            raise ValueError("max_family_gap must be positive.")
        protected = tuple(dict.fromkeys(int(value) for value in protected_destroy_indices))
        if any(value < 0 or value >= num_destroy for value in protected):
            raise ValueError("protected destroy index outside selector shape.")
        if any(not any(pair[0] == value for pair in self._legal_pairs) for value in protected):
            raise ValueError("protected destroy index has no legal pair.")
        self._protected_destroy_indices = protected
        self._warmup_per_pair = int(warmup_per_pair)
        self._max_family_gap = int(max_family_gap)
        self._last_destroy_selection = {value: -self._max_family_gap for value in protected}

    @property
    def warmup_per_pair(self) -> int:
        return self._warmup_per_pair

    @property
    def max_family_gap(self) -> int:
        return self._max_family_gap

    def __call__(self, rng: object, best: object, curr: object) -> tuple[int, int]:
        _ = rng, best, curr
        for d_idx, r_idx in self._legal_pairs:
            if int(self._times[d_idx, r_idx]) < self._warmup_per_pair:
                return self._select(d_idx, r_idx, phase="warmup")

        due = [
            d_idx
            for d_idx in self._protected_destroy_indices
            if self._iter - self._last_destroy_selection[d_idx] >= self._max_family_gap
        ]
        if due:
            d_idx = max(due, key=lambda value: (self._iter - self._last_destroy_selection[value], -value))
            legal_repairs = [r_idx for destroy, r_idx in self._legal_pairs if destroy == d_idx]
            r_idx = min(legal_repairs, key=lambda value: (int(self._times[d_idx, value]), value))
            return self._select(d_idx, r_idx, phase="family_floor")

        d_idx, r_idx = self._argmax_pair(selector_type="minimum_coverage", selector_phase="exploit")
        self._remember_destroy(d_idx)
        return d_idx, r_idx

    def _select(self, d_idx: int, r_idx: int, *, phase: str) -> tuple[int, int]:
        self._record_selection(
            d_idx,
            r_idx,
            selector_type="minimum_coverage",
            selector_phase=phase,
            selector_value=float(self._values()[d_idx, r_idx]),
        )
        self._remember_destroy(d_idx)
        return d_idx, r_idx

    def _remember_destroy(self, d_idx: int) -> None:
        if d_idx in self._last_destroy_selection:
            self._last_destroy_selection[d_idx] = int(self._iter)


class EpsilonDecayAlphaUCB(BalancedAlphaUCB):
    """Balanced AlphaUCB with linearly decaying uniform exploration."""

    def __init__(
        self,
        scores: Sequence[float],
        alpha: float,
        num_destroy: int,
        num_repair: int,
        op_coupling: np.ndarray | None = None,
        *,
        warmup_per_pair: int = 10,
        epsilon_start: float = 0.15,
        epsilon_end: float = 0.02,
        target_iterations: int = 4000,
    ) -> None:
        super().__init__(
            scores,
            alpha,
            num_destroy,
            num_repair,
            op_coupling,
            warmup_per_pair=warmup_per_pair,
            epsilon=epsilon_start,
        )
        if not 0.0 <= float(epsilon_end) <= 1.0:
            raise ValueError("epsilon_end must be in [0, 1].")
        self._epsilon_start = float(epsilon_start)
        self._epsilon_end = float(epsilon_end)
        self._target_iterations = max(1, int(target_iterations))

    @property
    def current_epsilon(self) -> float:
        progress = min(1.0, max(0.0, self._iter / self._target_iterations))
        return self._epsilon_start + (self._epsilon_end - self._epsilon_start) * progress

    def __call__(self, rng: object, best: object, curr: object) -> tuple[int, int]:
        pair = super().__call__(rng, best, curr)
        info = self.last_selection_info()
        info["selector_type"] = "epsilon_decay"
        info["selector_epsilon"] = self.current_epsilon
        self._last_selection_info = info
        return pair


class ThompsonPairSelector(OperatorSelectionScheme):
    """Diagnostic Thompson-sampling selector over legal destroy/repair pairs."""

    def __init__(
        self,
        num_destroy: int,
        num_repair: int,
        op_coupling: np.ndarray | None = None,
        *,
        warmup_per_pair: int = 5,
    ) -> None:
        super().__init__(num_destroy, num_repair, op_coupling)
        if warmup_per_pair < 0:
            raise ValueError("warmup_per_pair must be non-negative.")
        self._warmup_per_pair = int(warmup_per_pair)
        self._alpha = np.ones_like(self.op_coupling, dtype=float)
        self._beta = np.ones_like(self.op_coupling, dtype=float)
        self._times = np.zeros_like(self.op_coupling, dtype=int)
        self._iter = 0

    @property
    def warmup_per_pair(self) -> int:
        return self._warmup_per_pair

    def alpha_beta_for_pair(self, d_idx: int, r_idx: int) -> tuple[float, float]:
        return float(self._alpha[d_idx, r_idx]), float(self._beta[d_idx, r_idx])

    def __call__(self, rng: object, best: object, curr: object) -> tuple[int, int]:
        for d_idx, r_idx in self._legal_pairs:
            if int(self._times[d_idx, r_idx]) < self._warmup_per_pair:
                self._record_selection(
                    d_idx,
                    r_idx,
                    selector_type="thompson",
                    selector_phase="warmup",
                    selector_value=float(self._alpha[d_idx, r_idx] / (self._alpha[d_idx, r_idx] + self._beta[d_idx, r_idx])),
                )
                return d_idx, r_idx

        best_pair = self._legal_pairs[0]
        best_sample = -math.inf
        for d_idx, r_idx in self._legal_pairs:
            sample = float(rng.beta(self._alpha[d_idx, r_idx], self._beta[d_idx, r_idx])) if hasattr(rng, "beta") else 0.0
            if sample > best_sample:
                best_sample = sample
                best_pair = (d_idx, r_idx)
        d_idx, r_idx = best_pair
        self._record_selection(
            d_idx,
            r_idx,
            selector_type="thompson",
            selector_phase="sample",
            selector_value=float(self._alpha[d_idx, r_idx] / (self._alpha[d_idx, r_idx] + self._beta[d_idx, r_idx])),
            selector_sample=best_sample,
        )
        return best_pair

    def update(self, candidate: object, d_idx: int, r_idx: int, outcome: int) -> None:
        if int(outcome) in {0, 1}:
            self._alpha[d_idx, r_idx] += 1.0
        else:
            self._beta[d_idx, r_idx] += 1.0
        self._times[d_idx, r_idx] += 1
        self._iter += 1


class SoftmaxAlphaUCB(AlphaUCB):
    """Diagnostic selector that samples legal pairs from AlphaUCB values."""

    def __init__(
        self,
        scores: Sequence[float],
        alpha: float,
        num_destroy: int,
        num_repair: int,
        op_coupling: np.ndarray | None = None,
        *,
        temperature_start: float = 1.0,
        temperature_end: float = 0.1,
        target_iterations: int = 4000,
    ) -> None:
        super().__init__(scores, alpha, num_destroy, num_repair, op_coupling)
        if temperature_start <= 0.0 or temperature_end <= 0.0:
            raise ValueError("temperatures must be positive.")
        self._temperature_start = float(temperature_start)
        self._temperature_end = float(temperature_end)
        self._target_iterations = max(1, int(target_iterations))

    @property
    def current_temperature(self) -> float:
        progress = min(1.0, max(0.0, self._iter / self._target_iterations))
        return self._temperature_start + (self._temperature_end - self._temperature_start) * progress

    def __call__(self, rng: object, best: object, curr: object) -> tuple[int, int]:
        values = self._values()
        temperature = self.current_temperature
        logits = np.array([values[d_idx, r_idx] for d_idx, r_idx in self._legal_pairs], dtype=float) / temperature
        logits = logits - float(np.max(logits))
        weights = np.exp(logits)
        probabilities = weights / float(np.sum(weights))
        if hasattr(rng, "choice"):
            pick = int(rng.choice(len(self._legal_pairs), p=probabilities))
        else:
            pick = 0
        d_idx, r_idx = self._legal_pairs[pick]
        self._record_selection(
            d_idx,
            r_idx,
            selector_type="softmax",
            selector_phase="sample",
            selector_value=float(values[d_idx, r_idx]),
            selector_sample=float(pick),
            selector_probability=float(probabilities[pick]),
            selector_temperature=temperature,
        )
        return d_idx, r_idx
