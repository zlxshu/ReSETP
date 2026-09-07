"""Split charging candidates: depot carries part of a trip, a station the rest.

The model lets one trip charge partly at the depot and partly at a public
station (paper_main.tex lines 412-424); before the ``split`` candidate mode the
repair layer only built the two extremes, "all at the depot" and "just enough
depot energy to reach one station, that station covers the whole remaining
trip".  These tests pin the new interior candidates.

The first calendar below is constructed, not observed: it gives the depot one
cheap half hour and makes public energy cheaper than depot energy outside it,
so the split has to win.  The real China81 calendars never look like this --
there the depot pays a time-of-use tariff around 0.3 / 0.7 / 1.1 CNY/kWh and
the public price is that same depot price plus a flat 0.40 CNY/kWh service fee.
The last two tests use that realistic shape and differ only in the service fee,
so that they isolate what actually keeps the depot plan on top.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

import setp_solver.algorithms.resetp_alns.support.charging as charging_module
from setp_solver.algorithms.resetp_alns.support.charging import (
    repair_route_charging_candidates,
)
from setp_solver.algorithms.resetp_alns.operators.repair_scoring import (
    route_model_cost_delta,
)
from setp_solver.charging_curve import (
    M17_FAST_SHAPE_SCALED_60KW_PWL,
    curve_for_charging_node,
)
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.search.evaluation import EvaluationContext
from setp_solver.solution import ChargingAction, Route
from solver.tests.china_test_prices import CHINA_TEST_PRICES

# One cheap depot half hour, early enough to be inside the launch window.
_CHEAP_DEPOT_SLOT = 10
_BATTERY_KWH = 77.28
_ROUTE = ("D0", "C1", "C2", "C3", "D0")


def _prices() -> PriceParameters:
    curve = M17_FAST_SHAPE_SCALED_60KW_PWL
    return replace(
        CHINA_TEST_PRICES,
        B_battery_kwh=_BATTERY_KWH,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=60.0,
        charging_curve_id=curve.curve_id,
        charging_soc_breakpoints=curve.soc_breakpoints,
        charging_relative_powers=curve.relative_powers,
        depot_charging_curve_id=curve.curve_id,
        depot_charging_soc_breakpoints=curve.soc_breakpoints,
        depot_charging_relative_powers=curve.relative_powers,
        public_charging_curve_id=curve.curve_id,
        public_charging_soc_breakpoints=curve.soc_breakpoints,
        public_charging_relative_powers=curve.relative_powers,
    )


def _instance() -> Instance:
    """One depot, one station exactly on the depot-C1 line, three customers."""

    return Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=86_000.0, city="gz"),
            Node(
                "F1",
                "f",
                0.0,
                0.0,
                due_time=86_000.0,
                charge_power_kw=60.0,
                city="gz",
            ),
            Node(
                "C1",
                "c",
                0.0,
                0.0,
                demand=100.0,
                due_time=70_000.0,
                service_time=60.0,
                city="gz",
            ),
            Node(
                "C2",
                "c",
                0.0,
                0.0,
                demand=100.0,
                due_time=70_000.0,
                service_time=60.0,
                city="gz",
            ),
            Node(
                "C3",
                "c",
                0.0,
                0.0,
                demand=100.0,
                due_time=70_000.0,
                service_time=60.0,
                city="gz",
            ),
        ],
        # F1 sits halfway along D0->C1, so inserting it costs no extra metres.
        distance_matrix=[
            [0.0, 30_000.0, 60_000.0, 62_000.0, 64_000.0],
            [30_000.0, 0.0, 30_000.0, 32_000.0, 34_000.0],
            [60_000.0, 30_000.0, 0.0, 2_000.0, 4_000.0],
            [62_000.0, 32_000.0, 2_000.0, 0.0, 2_000.0],
            [64_000.0, 34_000.0, 4_000.0, 2_000.0, 0.0],
        ],
        num_ev=1,
        num_cv=0,
    )


def _profile(
    *,
    depot_cheap: float,
    depot_dear: float,
    station: float,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for slot in range(48):
        depot_price = depot_cheap if slot == _CHEAP_DEPOT_SLOT else depot_dear
        public_price = station
        rows.append(
            {
                "city": "gz",
                "time_index": slot,
                "horizon_second_start": float(slot * 1_800),
                "actual_gco2_per_kwh": 400.0,
                "forecast_gco2_per_kwh": 400.0,
                "depot_energy_cny_per_kwh": float(depot_price),
                "public_total_cny_per_kwh": float(public_price),
            }
        )
    return rows


def _tou_profile(service_fee: float) -> list[dict[str, object]]:
    """A China-shaped depot time-of-use tariff plus a flat station service fee.

    Valley 23:00-07:00 at 0.30, peak 10:00-15:00 and 18:00-21:00 at 1.10,
    flat 0.70 elsewhere -- the magnitudes of the China81 calendars, unlike the
    3.00 CNY/kWh straw depot price of the fixture above.
    """

    rows: list[dict[str, object]] = []
    for slot in range(48):
        if slot < 14 or slot >= 46:
            depot_price = 0.30
        elif 20 <= slot < 30 or 36 <= slot < 42:
            depot_price = 1.10
        else:
            depot_price = 0.70
        rows.append(
            {
                "city": "gz",
                "time_index": slot,
                "horizon_second_start": float(slot * 1_800),
                "actual_gco2_per_kwh": 400.0,
                "forecast_gco2_per_kwh": 400.0,
                "depot_energy_cny_per_kwh": depot_price,
                "public_total_cny_per_kwh": depot_price + service_fee,
            }
        )
    return rows


def _scored(
    mode: str,
    instance: Instance,
    profile: list[dict[str, object]],
    prices: PriceParameters,
) -> list[tuple[float, str, Route, list[ChargingAction]]]:
    charging_module._CHARGING_REPAIR_RUNTIMES.clear()
    candidates = repair_route_charging_candidates(
        Route("EV1", "ev", "D0", list(_ROUTE)),
        instance,
        profile,
        prices,
        strategy="integrated",
        charge_timing_policy="cost_plus_carbon",
        public_station_candidate_mode=mode,
    )
    context = EvaluationContext(
        instance=instance,
        carbon_profile=profile,
        prices=prices,
        carbon_weight=1.0,
    )
    scored = [
        (route_model_cost_delta(route, actions, context), label, route, actions)
        for label, route, actions in candidates
    ]
    scored.sort(key=lambda item: item[0])
    return scored


def _energy_at(actions: list[ChargingAction], node_id: str) -> float:
    return sum(
        float(action.energy_kwh)
        for action in actions
        if action.station_id == node_id
    )


@pytest.fixture(name="split_case")
def _split_case() -> tuple[Instance, list[dict[str, object]], PriceParameters]:
    return (
        _instance(),
        _profile(depot_cheap=0.30, depot_dear=3.00, station=0.80),
        _prices(),
    )


def test_split_beats_both_endpoints_with_a_real_public_session(
    split_case: tuple[Instance, list[dict[str, object]], PriceParameters],
) -> None:
    instance, profile, prices = split_case
    depot_only = _scored("fallback", instance, profile, prices)
    parallel = _scored("parallel", instance, profile, prices)
    split = _scored("split", instance, profile, prices)

    assert len(depot_only) == 1
    assert "F1" not in depot_only[0][2].node_sequence
    assert split[0][0] < parallel[0][0] < depot_only[0][0]

    _, _, best_route, best_actions = split[0]
    assert "F1" in best_route.node_sequence
    depot_share = _energy_at(best_actions, "D0")
    station_share = _energy_at(best_actions, "F1")
    assert station_share > 0.0
    # Strictly interior: more depot energy than the "just reach the station"
    # endpoint, less than the "depot covers everything" endpoint.
    assert (
        _energy_at(parallel[0][3], "D0")
        < depot_share
        < _energy_at(depot_only[0][3], "D0")
    )


def test_winning_split_level_is_one_of_the_enumerated_breakpoints(
    split_case: tuple[Instance, list[dict[str, object]], PriceParameters],
) -> None:
    instance, profile, prices = split_case
    parallel = _scored("parallel", instance, profile, prices)
    reference = next(
        actions for _, label, _, actions in parallel if label != "depot_fallback"
    )
    launch_target = _energy_at(reference, "D0")

    levels = charging_module._split_depot_launch_levels(
        reference,
        launch_target_kwh=launch_target,
        initial_battery_kwh=0.0,
        battery_capacity_kwh=_BATTERY_KWH,
        instance=instance,
        prices=prices,
    )
    assert levels, "a split trip must expose at least one interior level"

    split = _scored("split", instance, profile, prices)
    winner_level = _energy_at(split[0][3], "D0")
    assert any(abs(level - winner_level) <= 1e-6 for level in levels)


def test_fallback_and_parallel_candidates_survive_unchanged_under_split(
    split_case: tuple[Instance, list[dict[str, object]], PriceParameters],
) -> None:
    instance, profile, prices = split_case

    def plans(mode: str) -> list[tuple[tuple[str, ...], tuple[object, ...]]]:
        return [
            (tuple(route.node_sequence), tuple(actions))
            for _, _, route, actions in _scored(mode, instance, profile, prices)
        ]

    split_plans = plans("split")
    for plan in plans("fallback") + plans("parallel"):
        assert plan in split_plans


def _best_station_plan(
    scored: list[tuple[float, str, Route, list[ChargingAction]]],
) -> tuple[float, float]:
    """Cheapest plan that really charges at the station: (cost, station kWh)."""

    station_plans = [
        (cost, _energy_at(actions, "F1"))
        for cost, _, _, actions in scored
        if _energy_at(actions, "F1") > 0.0
    ]
    assert station_plans, "split must still build plans that use the station"
    return min(station_plans)


def test_real_tariff_shape_with_a_service_fee_keeps_the_depot_plan_on_top(
    split_case: tuple[Instance, list[dict[str, object]], PriceParameters],
) -> None:
    """Realistic depot ToU, station = depot + 0.40 CNY/kWh: the depot wins.

    Paired with the zero-fee test below, which uses the identical calendar.
    """

    instance, _, prices = split_case
    profile = _tou_profile(service_fee=0.40)
    depot_only = _scored("fallback", instance, profile, prices)
    split = _scored("split", instance, profile, prices)

    station_cost, station_kwh = _best_station_plan(split)
    assert station_cost > depot_only[0][0] + 1e-6
    # The whole gap is the service fee on the energy the station would sell.
    assert station_cost - depot_only[0][0] == pytest.approx(
        0.40 * station_kwh, abs=1e-6
    )
    # So the plan that wins buys nothing at the station.
    assert _energy_at(split[0][3], "F1") == 0.0


def test_real_tariff_shape_without_a_service_fee_leaves_the_split_no_worse(
    split_case: tuple[Instance, list[dict[str, object]], PriceParameters],
) -> None:
    """Same calendar, service fee 0: the split ties the depot-only plan.

    Only the fee differs from the test above, so the pair shows the fee -- not
    the depot's timing freedom -- is what keeps the depot plan on top.
    """

    instance, _, prices = split_case
    profile = _tou_profile(service_fee=0.0)
    depot_only = _scored("fallback", instance, profile, prices)
    split = _scored("split", instance, profile, prices)

    station_cost, station_kwh = _best_station_plan(split)
    assert station_kwh >= charging_module.SPLIT_MIN_STATION_ENERGY_KWH
    assert station_cost <= depot_only[0][0] + 1e-6


def test_enumerated_levels_cover_every_slot_boundary_and_curve_knee(
    split_case: tuple[Instance, list[dict[str, object]], PriceParameters],
) -> None:
    """The levels are a superset of the interior kinks of the cost function.

    The boundary *times* are derived here from plain half-hour arithmetic on
    the two observed session windows, not by calling the helper the
    implementation uses; only the curve's time/energy inverses are shared,
    because they are the definition of the mapping under test.
    """

    instance, profile, prices = split_case
    parallel = _scored("parallel", instance, profile, prices)
    reference = next(
        actions for _, label, _, actions in parallel if label != "depot_fallback"
    )
    launch_target = _energy_at(reference, "D0")

    node_lookup = instance.node_lookup
    depot_action = next(
        action
        for action in reference
        if node_lookup[action.station_id].node_type.lower() == "d"
    )
    station_action = next(
        action
        for action in reference
        if node_lookup[action.station_id].node_type.lower() == "f"
    )
    energy_to_station = launch_target - float(station_action.start_energy_kwh)
    station_target = float(station_action.end_energy_kwh)
    upper = min(
        _BATTERY_KWH,
        station_target
        + energy_to_station
        - charging_module.SPLIT_MIN_STATION_ENERGY_KWH,
    )

    depot_curve = curve_for_charging_node(
        prices,
        node_type="d",
        capacity_kwh=_BATTERY_KWH,
        reference_power_kw=float(prices.depot_charge_power_kw),
    )
    station_node = node_lookup[station_action.station_id]
    station_curve = curve_for_charging_node(
        prices,
        node_type=station_node.node_type,
        capacity_kwh=_BATTERY_KWH,
        reference_power_kw=float(station_node.charge_power_kw),
    )

    # Half-hour boundaries strictly inside each session, spelled out here.
    expected: list[float] = []
    depot_start = float(depot_action.charge_start_second)
    depot_span = depot_curve.duration_seconds(0.0, upper)
    station_start = float(station_action.charge_start_second)
    station_span = float(station_action.occupancy_minutes) * 60.0
    for index in range(0, 200):
        boundary = float(index) * 1_800.0
        if depot_start < boundary <= depot_start + depot_span:
            expected.append(
                depot_curve.reachable_energy_kwh(0.0, boundary - depot_start)
            )
        if station_start < boundary <= station_start + station_span:
            expected.append(
                station_curve.minimum_energy_before_gap_kwh(
                    station_target, boundary - station_start
                )
                + energy_to_station
            )
    # Charging-curve knees on both sides.
    expected.extend(float(e) for e in depot_curve.energy_breakpoints_kwh)
    expected.extend(
        float(e) + energy_to_station
        for e in station_curve.energy_breakpoints_kwh
    )

    tolerance = charging_module.SPLIT_DEPOT_LEVEL_TOLERANCE_KWH
    interior = sorted(
        level
        for level in expected
        if launch_target + tolerance < level < upper - tolerance
    )
    # Guard against a vacuous pass and against the dedup silently merging two
    # distinct kinks: this fixture must expose several well-separated ones.
    assert len(interior) >= 3
    assert all(
        second - first > 10.0 * tolerance
        for first, second in zip(interior, interior[1:])
    )

    levels = charging_module._split_depot_launch_levels(
        reference,
        launch_target_kwh=launch_target,
        initial_battery_kwh=0.0,
        battery_capacity_kwh=_BATTERY_KWH,
        instance=instance,
        prices=prices,
    )
    for kink in interior:
        assert any(
            abs(level - kink) <= tolerance for level in levels
        ), f"enumerated levels miss the kink at {kink:.6f} kWh"
