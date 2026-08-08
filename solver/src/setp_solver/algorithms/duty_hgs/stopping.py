"""Stopping adapter for per-algorithm convergence calibration."""

from __future__ import annotations

from dataclasses import dataclass

from .runner import DutyHGSSearchState


@dataclass(frozen=True)
class MaxIterations:
    """Stop at the iteration limit frozen from this algorithm's trajectory."""

    value: int

    def __post_init__(self) -> None:
        if int(self.value) < 1:
            raise ValueError("calibrated iteration limit must be positive")

    def __call__(self, state: DutyHGSSearchState) -> bool:
        return int(state.iterations) >= int(self.value)
