# declared_identity=PROJECT_DOMAIN
# provenance_status=UNKNOWN
# first_seen_commit=15ea9919006a53909745caa8f669f1c68aee0641
# git_commit_author=Leixishu Zhou (not evidence of content authorship)
# original_author=UNKNOWN
# pre_move_sha256=de2102b985cce83a31a4ec1f5d401c8bab9ba0d62dc91bdce4cdd0f855065b10
"""Shared HGS iteration control derived from PyVRP 0.12.2.

This module keeps the upstream control semantics in one place while allowing
different individual representations to provide one iteration of work.  The
upstream copyright and MIT licence are preserved in this copied package's
``LICENSE.md`` and ``UPSTREAM_COMMIT`` files.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HGSControlState:
    iterations: int
    iterations_without_improvement: int
    elapsed_seconds: float


@dataclass
class HGSIteration:
    """One caller-owned HGS iteration.

    ``improved`` may be left as ``None`` when improvement can be inferred from
    ``best_value``.  Full-problem adapters can set it explicitly when their
    incumbent rule includes more than one comparable value.
    """

    iteration: int
    improved: bool | None = None


class HGSControl:
    """The copied HGS stop/restart/improvement loop with adapter callbacks."""

    def __init__(
        self,
        *,
        should_stop: Callable[[HGSControlState], bool],
        best_value: Callable[[], Any],
        restart_after_iterations_without_improvement: int | None,
        restart: Callable[[], None] | None = None,
        initial_iterations_without_improvement: int = 1,
    ) -> None:
        if restart_after_iterations_without_improvement is not None and (
            restart_after_iterations_without_improvement < 0
        ):
            raise ValueError("restart interval must be non-negative")
        if initial_iterations_without_improvement < 0:
            raise ValueError("initial no-improvement count must be non-negative")
        if restart_after_iterations_without_improvement is not None and restart is None:
            raise ValueError("restart callback is required when restart is enabled")

        self._should_stop = should_stop
        self._best_value = best_value
        self._restart_after = restart_after_iterations_without_improvement
        self._restart = restart
        self._initial_without_improvement = initial_iterations_without_improvement
        self._started = time.perf_counter()
        self._iterations = 0
        self._iterations_without_improvement = initial_iterations_without_improvement

    @property
    def state(self) -> HGSControlState:
        return HGSControlState(
            iterations=self._iterations,
            iterations_without_improvement=self._iterations_without_improvement,
            elapsed_seconds=time.perf_counter() - self._started,
        )

    def iterations(self) -> Iterator[HGSIteration]:
        while not self._should_stop(self.state):
            if (
                self._restart_after is not None
                and self._iterations_without_improvement == self._restart_after
            ):
                assert self._restart is not None
                self._restart()
                self._iterations_without_improvement = (
                    self._initial_without_improvement
                )

            previous_best = self._best_value()
            token = HGSIteration(iteration=self._iterations)
            yield token

            improved = token.improved
            if improved is None:
                improved = self._best_value() < previous_best

            self._iterations += 1
            if improved:
                self._iterations_without_improvement = (
                    self._initial_without_improvement
                )
            else:
                self._iterations_without_improvement += 1
