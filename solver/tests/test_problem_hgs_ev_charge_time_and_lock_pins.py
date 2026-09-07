"""2026-09-02: EV charge-time in the kernel and pinned mechanism-lock penalties.

The route kernel's EV profiles carry travel + arc energy / P_eff so the local
search sees the between-trip depot charging it used to be blind to; the lock
dimensions that encode a disabled mechanism never adapt.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_problem_hgs_private_technical import (  # noqa: E402
    DEPOT_SEARCH_INSTANCE_ID,
    FLEET_PARAMETER_CLASSES,
    _build_context,
    _policy,
)
from setp_solver.algorithms.problem_hgs.evaluation import (  # noqa: E402
    DutyFullEvaluator,
)
from setp_solver.algorithms.problem_hgs.kernel_proposals import (  # noqa: E402
    IndependentKernelDutyRouteProposalEngine,
)
from setp_solver.cost import ev_instance_arc_energy_kwh  # noqa: E402


@pytest.fixture(scope="module")
def formal():
    repo = Path(__file__).parents[2]
    bundle, initial, _neutral, context = _build_context(
        repo,
        DEPOT_SEARCH_INSTANCE_ID,
        fleet_parameters=FLEET_PARAMETER_CLASSES["endogenous"],
    )
    evaluator = DutyFullEvaluator(context)
    return bundle, initial, context, evaluator, _policy(evaluator)


def _engine(context, initial, **options):
    return IndependentKernelDutyRouteProposalEngine(
        context,
        initial,
        stream_role="test",
        rebuilt_volume_capacity_enabled=True,
        rebuilt_shift_neighbours_only=True,
        shift_aware_ev_unit_cost_enabled=True,
        **options,
    )


def test_ev_profiles_carry_charge_time_and_cv_profiles_do_not(formal):
    bundle, initial, context, _evaluator, _policy_ = formal
    on = _engine(context, initial, ev_charge_time_proxy_enabled=True)
    off = _engine(context, initial, ev_charge_time_proxy_enabled=False)
    assert on.ev_charge_time_proxy is not None
    assert off.ev_charge_time_proxy is None
    assert "ev-charge-time:" in on.source_id
    assert "ev-charge-time:" not in off.source_id
    power = on.ev_charge_time_proxy["effective_power_kw"]
    # 60 kW depot scenario on the M17 fast shape: ~59.8 kW from empty to
    # half battery.
    assert 55.0 < power <= 60.5
    seconds_per_kwh = on.ev_charge_time_proxy["seconds_per_kwh"]
    instance = bundle.instance
    prices = bundle.prices
    ev_profiles = set()
    cv_profiles = set()
    for index in range(on.data.num_vehicle_types):
        vehicle_type = on.data.vehicle_type(index)
        assert off.data.vehicle_type(index).name == vehicle_type.name
        (ev_profiles if vehicle_type.name.startswith("EV_") else cv_profiles).add(
            int(vehicle_type.profile)
        )
    assert ev_profiles and cv_profiles
    for profile in cv_profiles:
        assert np.array_equal(
            on.data.duration_matrix(profile), off.data.duration_matrix(profile)
        )
        assert np.array_equal(
            on.data.distance_matrix(profile), off.data.distance_matrix(profile)
        )
    location_by_node = on._location_by_node_id
    customers = [
        node.node_id for node in instance.nodes if node.node_type.lower() == "c"
    ]
    half_load = on.ev_charge_time_proxy["ev_half_load_kg"]
    checked = 0
    for profile in ev_profiles:
        delta = on.data.duration_matrix(profile) - off.data.duration_matrix(profile)
        assert (delta >= 0).all()
        assert np.array_equal(
            on.data.distance_matrix(profile), off.data.distance_matrix(profile)
        )
        for left, right in zip(customers[:12], customers[1:13]):
            energy = ev_instance_arc_energy_kwh(
                instance, left, right, half_load, prices
            )
            expected = energy * seconds_per_kwh
            got = float(delta[location_by_node[left], location_by_node[right]])
            assert abs(got - expected) <= 1.0, (left, right, got, expected)
            checked += 1
    assert checked > 0
    # Physical sanity for this instance: ~0.34 kWh/km at ~66 km/h means the
    # EV clock runs roughly a third slower than travel alone.
    ev_profile = next(iter(ev_profiles))
    travel = off.data.duration_matrix(ev_profile).astype(float)
    total = on.data.duration_matrix(ev_profile).astype(float)
    mask = travel > 0
    ratio = float((total[mask] / travel[mask]).mean())
    assert 1.2 < ratio < 1.6, ratio


def test_mechanism_lock_penalties_never_adapt(formal):
    """Disabled-mechanism lock dimensions stay at the maximum penalty.

    2026-09-02: with the penalty manager adapting again, the type lock of the
    no-type-exchange arm decayed within a run and the arm ended up with EVs
    (closure failure on M-HGS run_01..03).  Pinned dimensions must survive
    any number of feasible registrations while ordinary dimensions adapt.
    """

    _bundle, initial, context, _evaluator, _policy_ = formal
    locked = _engine(context, initial, type_exchange_enabled=False)
    open_ = _engine(context, initial, type_exchange_enabled=True)
    assert locked.locked_load_dimensions
    assert not open_.locked_load_dimensions
    pm = locked.penalty_manager
    maximum = pm._params.max_penalty
    for index in locked.locked_load_dimensions:
        assert pm._penalties[index] == maximum
    native = locked.project(initial)
    assert native.is_feasible()
    before = list(pm._penalties)
    for _ in range(200):
        pm.register(native)
    after = list(pm._penalties)
    for index in locked.locked_load_dimensions:
        assert after[index] == maximum
    # The ordinary payload dimension adapts downwards after all-feasible
    # registrations, proving adaptation itself still works.
    assert after[0] < before[0]


# ---------------------------------------------------------------------------
# 2026-09-06: the first-trip window opening reaches the built engine
#
# ``_rebuilt_shift_aware_ev_unit_costs`` is unit-tested on its own in
# ``test_policy_aware_shift_proxy.py``; these pin the plumbing -- the engine
# keyword must survive ``_build_unique_asset_problem`` and land in the proxy
# metadata the run records, and it must tag the engine lineage so a run with a
# different opening is never mistaken for the same engine.
# ---------------------------------------------------------------------------


def test_the_first_trip_window_opening_reaches_the_shift_aware_proxy(formal):
    _bundle, initial, context, _evaluator, _policy_ = formal
    afternoon = 15 * 3600.0
    engine = _engine(
        context,
        initial,
        charge_timing_policy_for_proxy="asap",
        first_trip_window="prev_return",
        first_trip_window_open_second=afternoon,
    )
    assert engine.first_trip_window_open_second == afternoon
    for depot_rates in engine.shift_aware_ev_proxy.values():
        first_shift = min(
            depot_rates.values(),
            key=lambda row: float(row["window_end_second"]),
        )
        assert first_shift["window_start_second"] == pytest.approx(
            afternoon - 86_400.0
        )
        assert first_shift["selected_slot_start_second"] == pytest.approx(
            afternoon
        )


def test_a_different_window_opening_is_a_different_engine(formal):
    _bundle, initial, context, _evaluator, _policy_ = formal
    tagged = _engine(
        context,
        initial,
        first_trip_window="prev_return",
        first_trip_window_open_second=15 * 3600.0,
    )
    fallback = _engine(context, initial, first_trip_window="prev_return")
    # The opening is read by the shift-aware proxy's first window and by
    # nothing else, so an engine without that proxy keeps its old lineage.
    without_proxy = IndependentKernelDutyRouteProposalEngine(
        context,
        initial,
        stream_role="test",
        first_trip_window="prev_return",
        first_trip_window_open_second=15 * 3600.0,
    )
    assert "first-trip-open-" not in without_proxy.source_id
    assert "first-trip-open-54000:" in tagged.source_id
    assert "first-trip-open-" not in fallback.source_id
    assert tagged.source_id != fallback.source_id
    # Under the historical window the opening is dead weight and must not
    # change the engine's identity.
    same_day = _engine(
        context,
        initial,
        first_trip_window="same_day",
        first_trip_window_open_second=15 * 3600.0,
    )
    assert "first-trip-open-" not in same_day.source_id
    assert same_day.source_id == _engine(context, initial).source_id
