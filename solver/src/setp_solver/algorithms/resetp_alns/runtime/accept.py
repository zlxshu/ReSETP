"""Project-local ALNS acceptance criteria for the ReSETP backend.

Adapted from N-Wouda/alns 7.0.0 (MIT License). The formulas, validation rules,
and temperature/threshold updates are intentionally kept equivalent for the
criteria used by this repository.  The upstream copyright notice and complete
MIT text are retained in ``runtime/LICENSE-N-WOUDA-ALNS.md``.
"""

from __future__ import annotations

import logging

import numpy as np


logger = logging.getLogger(__name__)


def update(current: float, step: float, method: str) -> float:
    if method == "linear":
        return current - step
    if method == "exponential":
        return current * step
    raise ValueError("Method must be one of ['linear', 'exponential']")


class HillClimbing:
    def __call__(self, rng: object, best: object, current: object, candidate: object) -> bool:
        return candidate.objective() <= current.objective()


class RecordToRecordTravel:
    def __init__(
        self,
        start_threshold: float,
        end_threshold: float,
        step: float,
        method: str = "linear",
        cmp_best: bool = True,
    ) -> None:
        if start_threshold < 0 or end_threshold < 0 or step < 0:
            raise ValueError("Thresholds and step must be non-negative.")
        if start_threshold < end_threshold:
            raise ValueError("start_threshold < end_threshold not understood.")
        if method == "exponential" and step > 1:
            raise ValueError("Exponential updating cannot have step > 1.")
        if method not in ["linear", "exponential"]:
            raise ValueError("Method must be one of ['linear', 'exponential']")

        self._start_threshold = start_threshold
        self._end_threshold = end_threshold
        self._step = step
        self._method = method
        self._cmp_best = cmp_best
        self._threshold = start_threshold

    @property
    def start_threshold(self) -> float:
        return self._start_threshold

    @property
    def end_threshold(self) -> float:
        return self._end_threshold

    @property
    def step(self) -> float:
        return self._step

    @property
    def method(self) -> str:
        return self._method

    def __call__(self, rng: object, best: object, current: object, candidate: object) -> bool:
        baseline = best if self._cmp_best else current
        accepted = candidate.objective() - baseline.objective() <= self._threshold
        self._threshold = max(self.end_threshold, update(self._threshold, self.step, self.method))
        return accepted

    @classmethod
    def autofit(
        cls,
        init_obj: float,
        start_gap: float,
        end_gap: float,
        num_iters: int,
        method: str = "linear",
    ) -> "RecordToRecordTravel":
        if not (0 <= end_gap <= start_gap):
            raise ValueError("Must have 0 <= end_gap <= start_gap")
        if num_iters <= 0:
            raise ValueError("Non-positive num_iters not understood.")
        if method not in ["linear", "exponential"]:
            raise ValueError("Method must be one of ['linear', 'exponential']")

        start_threshold = start_gap * init_obj
        end_threshold = end_gap * init_obj
        if method == "linear":
            step = (start_threshold - end_threshold) / num_iters
        else:
            step = (end_threshold / start_threshold) ** (1 / num_iters)

        logger.info(
            "Autofit %s RRT: start_threshold %.2f, end_threshold %.2f, step %.2f.",
            method,
            start_threshold,
            end_threshold,
            step,
        )
        return cls(start_threshold, end_threshold, step, method=method)


class SimulatedAnnealing:
    def __init__(
        self,
        start_temperature: float,
        end_temperature: float,
        step: float,
        method: str = "exponential",
    ) -> None:
        if start_temperature <= 0 or end_temperature <= 0 or step < 0:
            raise ValueError("Temperatures must be strictly positive.")
        if start_temperature < end_temperature:
            raise ValueError("start_temperature < end_temperature not understood.")
        if method == "exponential" and step > 1:
            raise ValueError("Exponential updating cannot have step > 1.")

        self._start_temperature = start_temperature
        self._end_temperature = end_temperature
        self._step = step
        self._method = method
        self._temperature = start_temperature

    @property
    def start_temperature(self) -> float:
        return self._start_temperature

    @property
    def end_temperature(self) -> float:
        return self._end_temperature

    @property
    def step(self) -> float:
        return self._step

    @property
    def method(self) -> str:
        return self._method

    def __call__(self, rng: object, best: object, current: object, candidate: object) -> bool:
        # Better candidates have acceptance probability one.  Clamping their
        # positive exponent preserves that exact behaviour without overflowing
        # NumPy when a penalised candidate differs by a large BIG_M value.
        exponent = (
            current.objective() - candidate.objective()
        ) / self._temperature
        probability = np.exp(min(0.0, float(exponent)))
        self._temperature = max(
            self.end_temperature,
            update(self._temperature, self.step, self.method),
        )
        return probability >= rng.random()

    @classmethod
    def autofit(
        cls,
        init_obj: float,
        worse: float,
        accept_prob: float,
        num_iters: int,
        method: str = "exponential",
    ) -> "SimulatedAnnealing":
        if not (0 <= worse <= 1):
            raise ValueError("worse outside [0, 1] not understood.")
        if not (0 < accept_prob < 1):
            raise ValueError("accept_prob outside (0, 1) not understood.")
        if num_iters <= 0:
            raise ValueError("Non-positive num_iters not understood.")
        if method not in ["linear", "exponential"]:
            raise ValueError("Method must be one of ['linear', 'exponential']")

        start_temp = -worse * init_obj / np.log(accept_prob)
        if method == "linear":
            step = (start_temp - 1) / num_iters
        else:
            step = (1 / start_temp) ** (1 / num_iters)

        logger.info("Autofit %s SA: start_temp %.2f, step %.2f.", method, start_temp, step)
        return cls(start_temp, 1, step, method=method)
