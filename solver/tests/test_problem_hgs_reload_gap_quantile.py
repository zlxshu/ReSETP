"""Reload-gap reservation quantile (D1) and kernel seed feasibility (D2).

2026-09-05.  The reload-gap proxy used to reserve the *longest* between-trip
charge of the previous round's exact best.  Measured on the P=0.2
midday-valley batch that booked 2380-2642 s against a real median of 1348 s,
and at 2614.1 s the kernel judged 25 of 33 exactly-feasible solutions
infeasible -- where ``GeneticAlgorithm._best`` can never reach them.  The
reservation is now an order statistic (``RELOAD_GAP_QUANTILE``), and the
number of projected seeds the kernel rejects is recorded per round.

The 33-solution feasibility sweep behind those numbers lives outside the
suite: it needs the dumped batch artefacts, not synthetic plans.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_problem_hgs_private_technical import (  # noqa: E402
    DEPOT_SEARCH_INSTANCE_ID,
    FLEET_PARAMETER_CLASSES,
    _build_context,
)
from setp_solver.algorithms.problem_hgs.contracts import (  # noqa: E402
    SearchAccounting,
)
from setp_solver.algorithms.problem_hgs.kernel_proposals import (  # noqa: E402
    RELOAD_GAP_QUANTILE,
    _order_statistic,
    inter_trip_reload_seconds,
    max_inter_trip_reload_seconds,
    reference_trip_energy_kwh,
)


def _session(trip: int, minutes: float):
    return SimpleNamespace(trip_index=trip, occupancy_minutes=minutes)


def _plan(*session_groups):
    return SimpleNamespace(
        duties=tuple(
            SimpleNamespace(charging_sessions=tuple(group))
            for group in session_groups
        )
    )


# ---------------------------------------------------------------------------
# order statistic
# ---------------------------------------------------------------------------
def test_order_statistic_is_nearest_rank_and_1_0_is_the_maximum():
    values = [5.0, 1.0, 4.0, 2.0, 3.0]
    # ceil(q * 5) - 1 on the sorted values.
    assert _order_statistic(values, 0.2) == 1.0
    assert _order_statistic(values, 0.5) == 3.0
    assert _order_statistic(values, 0.75) == 4.0
    assert _order_statistic(values, 1.0) == 5.0
    assert _order_statistic(values, 1.0) == max(values)
    # Out-of-range levels clamp instead of raising.
    assert _order_statistic(values, 0.0) == 1.0
    assert _order_statistic(values, 2.0) == 5.0


def test_order_statistic_1_0_equals_max_on_every_prefix():
    values = [631.2, 1109.0, 1348.0, 1875.3, 2614.1, 2641.9]
    for size in range(1, len(values) + 1):
        prefix = values[:size]
        assert _order_statistic(prefix, 1.0) == max(prefix)


# ---------------------------------------------------------------------------
# D1 (a): the session-duration reservation
# ---------------------------------------------------------------------------
def test_inter_trip_reload_seconds_skips_the_first_trip():
    plan = _plan(
        (_session(1, 60.0), _session(2, 10.0)),
        (_session(1, 50.0),),
        (_session(2, 20.0), _session(3, 30.0)),
    )
    # Between-trip sessions only: 10, 20, 30 minutes.  The 60-minute
    # first-trip charge happens before the day starts.
    assert inter_trip_reload_seconds(plan, quantile=1.0) == 30.0 * 60.0
    assert inter_trip_reload_seconds(plan, quantile=0.75) == 30.0 * 60.0
    assert inter_trip_reload_seconds(plan, quantile=0.5) == 20.0 * 60.0
    only_first = _plan((_session(1, 60.0),))
    assert inter_trip_reload_seconds(only_first, quantile=0.75) is None
    assert inter_trip_reload_seconds(_plan()) is None


def test_quantile_1_0_reproduces_the_historic_maximum_reservation():
    """V2 regression: the pre-2026-09-05 value is still reachable, bit for bit."""

    plans = [
        _plan((_session(2, 22.5),)),
        _plan(
            (_session(1, 61.3), _session(2, 22.47), _session(3, 43.6)),
            (_session(2, 31.9),),
        ),
        _plan(
            (_session(2, 10.52),),
            (_session(2, 43.568), _session(3, 43.5681)),
            (_session(1, 99.0),),
        ),
        _plan((_session(1, 12.0),)),
    ]
    for plan in plans:
        assert inter_trip_reload_seconds(plan, quantile=1.0) == (
            max_inter_trip_reload_seconds(plan)
        )


def test_the_default_quantile_never_exceeds_the_maximum():
    plan = _plan(
        (_session(2, 18.7), _session(3, 24.1)),
        (_session(2, 43.57), _session(3, 31.2), _session(4, 12.9)),
    )
    default = inter_trip_reload_seconds(plan)
    assert default == inter_trip_reload_seconds(plan, quantile=RELOAD_GAP_QUANTILE)
    assert default <= max_inter_trip_reload_seconds(plan)
    # And it is drawn from the plan, not interpolated between sessions.
    observed = {
        float(session.occupancy_minutes) * 60.0
        for duty in plan.duties
        for session in duty.charging_sessions
        if session.trip_index >= 2
    }
    assert default in observed


def test_the_default_quantile_stays_at_or_above_the_batch_median():
    """V3 floor: the 2026-09-03 mean-reservation crash set 1348 s as the floor.

    Replayed on the 101 real between-trip sessions of the P=0.2 midday-valley
    batch (p50 1348.0 s, p75 1875.3 s, p90 2614.1 s); a level that dropped the
    reservation below the median would repeat the free-fleet round that had no
    repairable EV member and an 8-CV best.
    """

    batch_p50 = 1348.0
    # One duty carrying the batch's measured deciles as between-trip sessions.
    deciles_seconds = [
        631.2, 950.0, 1109.0, 1225.0, 1348.0,
        1500.0, 1875.3, 2117.4, 2614.1, 2641.9,
    ]
    plan = _plan(
        tuple(
            _session(index + 2, seconds / 60.0)
            for index, seconds in enumerate(deciles_seconds)
        )
    )
    reserved = inter_trip_reload_seconds(plan, quantile=RELOAD_GAP_QUANTILE)
    assert reserved >= batch_p50
    assert reserved == pytest.approx(2117.4)


# ---------------------------------------------------------------------------
# D1 (b): the trip-energy reference, and the round-one decision
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def formal():
    repo = Path(__file__).parents[2]
    bundle, initial, _neutral, _context = _build_context(
        repo,
        DEPOT_SEARCH_INSTANCE_ID,
        fleet_parameters=FLEET_PARAMETER_CLASSES["endogenous"],
    )
    return bundle, initial


def test_reference_trip_energy_quantile_1_0_is_the_max_bit_for_bit(formal):
    bundle, initial = formal
    largest = reference_trip_energy_kwh(
        bundle.instance, bundle.prices, initial.duties, reference="max"
    )
    assert reference_trip_energy_kwh(
        bundle.instance,
        bundle.prices,
        initial.duties,
        reference="quantile",
        quantile=1.0,
    ) == largest
    p75 = reference_trip_energy_kwh(
        bundle.instance, bundle.prices, initial.duties, reference="p75"
    )
    assert p75 == reference_trip_energy_kwh(
        bundle.instance,
        bundle.prices,
        initial.duties,
        reference="quantile",
        quantile=RELOAD_GAP_QUANTILE,
    )
    assert p75 < largest


def test_reference_trip_energy_rejects_an_unknown_or_levelless_reference(formal):
    bundle, initial = formal
    with pytest.raises(ValueError):
        reference_trip_energy_kwh(
            bundle.instance, bundle.prices, initial.duties, reference="p99"
        )
    with pytest.raises(ValueError):
        reference_trip_energy_kwh(
            bundle.instance, bundle.prices, initial.duties, reference="quantile"
        )
    assert reference_trip_energy_kwh(
        bundle.instance, bundle.prices, (), reference="quantile", quantile=0.75
    ) == 0.0


def test_round_one_still_reserves_the_witness_maximum(formal):
    """The quantile drives the feedback path only.

    Taking ``RELOAD_GAP_QUANTILE`` of the witness's 16 trip energies converts
    to 1177.20 s, below the 1348 s floor; the neighbouring rungs of that
    coarse grid are 1240.80 s (also below) and 1692.94 s (already 4 of 33
    exactly-feasible solutions infeasible), while the window that clears both
    constraints is [1348, ~1560) s.  Round one therefore keeps the maximum
    until a different reference distribution is chosen upstream.
    """

    bundle, initial = formal
    largest = reference_trip_energy_kwh(
        bundle.instance, bundle.prices, initial.duties, reference="max"
    )
    assert largest == 33.76187876229928
    quantile_energy = reference_trip_energy_kwh(
        bundle.instance,
        bundle.prices,
        initial.duties,
        reference="quantile",
        quantile=RELOAD_GAP_QUANTILE,
    )
    assert quantile_energy == 19.5624326944426


def test_the_quantile_reaches_the_runner_and_the_command_line():
    import inspect

    from setp_solver.algorithms.problem_hgs.runner import (
        run_kernel_native_problem_hgs,
    )

    signature = inspect.signature(run_kernel_native_problem_hgs)
    assert (
        signature.parameters["reload_gap_quantile"].default == RELOAD_GAP_QUANTILE
    )
    source = (SCRIPTS / "run_problem_hgs_private_technical.py").read_text()
    # The private runner exposes it and passes it through; ``1.0`` restores
    # the pre-2026-09-05 reservation without touching the source.
    assert '"--reload-gap-quantile",' in source
    assert "reload_gap_quantile=args.reload_gap_quantile," in source
    assert '"reload_gap_quantile": float(args.reload_gap_quantile),' in source


# ---------------------------------------------------------------------------
# D2: kernel seed feasibility is recorded, not re-derived offline
# ---------------------------------------------------------------------------
def test_accounting_publishes_the_kernel_seed_feasibility_counters():
    accounting = SearchAccounting()
    assert accounting.kernel_seed_infeasible_by_round == []
    assert accounting.kernel_seed_count_by_round == []
    published = accounting.to_dict()
    assert published["kernel_seed_infeasible_by_round"] == []
    assert published["kernel_seed_count_by_round"] == []

    accounting.kernel_seed_count_by_round.extend([4, 4])
    accounting.kernel_seed_infeasible_by_round.extend([0, 3])
    published = accounting.to_dict()
    assert published["kernel_seed_count_by_round"] == [4, 4]
    assert published["kernel_seed_infeasible_by_round"] == [0, 3]
    assert all(
        isinstance(value, int)
        for value in published["kernel_seed_infeasible_by_round"]
    )
    # The reservation that produced each round's count is published beside it.
    assert "reload_gap_seconds_by_round" in published
