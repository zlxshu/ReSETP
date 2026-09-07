"""Round-one opening instant of the first-trip charging window (2026-09-06).

Under ``--first-trip-window prev_return`` a vehicle may plug in as soon as it
came back the preceding evening.  The route proxy is built before any route
exists, so it takes the median last return of the initial population -- the
same pooled order statistic the reload reservation uses -- instead of the
route-independent 19:00 fallback, which the exact settlement was measured to
beat by three hours on the beijing calendar.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from setp_solver.algorithms.problem_hgs.kernel_proposals import (
    FIRST_TRIP_WINDOW_OPEN_QUANTILE,
    population_first_trip_window_open_second,
)


@dataclass(frozen=True)
class _Trip:
    physical_vehicle_id: str
    trip_index: int
    vehicle_type: str
    return_second: float


@dataclass(frozen=True)
class _Certificate:
    trips: tuple[_Trip, ...]


@dataclass(frozen=True)
class _Evaluation:
    certificate: _Certificate | None


def _plan(rows: tuple[tuple[str, int, str, float], ...]) -> _Evaluation:
    return _Evaluation(_Certificate(tuple(_Trip(*row) for row in rows)))


def test_the_quantile_is_the_median() -> None:
    assert FIRST_TRIP_WINDOW_OPEN_QUANTILE == 0.50


def test_each_duty_contributes_its_own_last_return() -> None:
    """One value per electric duty per plan -- the duty's LAST trip."""

    plan = _plan(
        (
            ("EV_D_1", 1, "ev", 30_000.0),
            ("EV_D_1", 2, "ev", 53_400.0),
            ("EV_D_2", 1, "ev", 61_000.0),
            ("CV_D_1", 1, "cv", 70_000.0),  # combustion: not a charging duty
        )
    )
    # Two duties -> two values {53400, 61000}; the nearest-rank median of an
    # even sample is the lower of the two middle values.
    assert population_first_trip_window_open_second(
        (plan,)
    ) == pytest.approx(53_400.0)


def test_the_population_is_pooled_not_averaged_per_plan() -> None:
    plans = (
        _plan((("EV_D_1", 1, "ev", 10_000.0),)),
        _plan((("EV_D_1", 1, "ev", 20_000.0),)),
        _plan((("EV_D_1", 1, "ev", 30_000.0),)),
    )
    assert population_first_trip_window_open_second(
        plans
    ) == pytest.approx(20_000.0)
    assert population_first_trip_window_open_second(
        plans, quantile=1.0
    ) == pytest.approx(30_000.0)


def test_an_all_combustion_population_has_no_opening() -> None:
    """None, so the caller keeps the contract's last shift end."""

    plans = (_plan((("CV_D_1", 1, "cv", 70_000.0),)),)
    assert population_first_trip_window_open_second(plans) is None
    assert population_first_trip_window_open_second(()) is None
    assert population_first_trip_window_open_second((_Evaluation(None),)) is None


def test_a_return_past_midnight_is_read_on_the_representative_day() -> None:
    """The schedule is one repeating day, so the opening is a local second."""

    plans = (_plan((("EV_D_1", 1, "ev", 86_400.0 + 3_600.0),)),)
    assert population_first_trip_window_open_second(
        plans
    ) == pytest.approx(3_600.0)
