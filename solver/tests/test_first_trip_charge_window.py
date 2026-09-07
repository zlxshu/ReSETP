"""First-trip depot charging window: same-day vs previous-night return.

2026-09-06.  The baseline "charge whenever a slot is free" arm used to start
its first-trip depot charge at the simulation day's own 00:00, because that is
where the pre-departure window opened.  A real vehicle cannot be plugged in
before it is back at the depot, so the window now opens at the previous
evening's depot return (``--first-trip-window prev_return``); the historical
window stays the default so every other batch is unchanged.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from setp_solver.algorithms.problem_hgs.charging import (
    FIRST_TRIP_WINDOW_PREV_RETURN,
    FIRST_TRIP_WINDOW_SAME_DAY,
    ChargingRepairPolicy,
    repair_changed_duties,
)
from setp_solver.algorithms.problem_hgs.evaluation import (
    DutyEvaluationContext,
    RebuiltRouteConstraintContract,
)
from setp_solver.algorithms.problem_hgs.model import (
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
)
from setp_solver.china81 import China81Bundle
from setp_solver.instance_loader import Instance, Node
from solver.tests.china_test_prices import CHINA_TEST_PRICES


AM_START = 8 * 3600.0
AM_END = 11 * 3600.0
PM_START = 13 * 3600.0
PM_END = 19 * 3600.0
DAY = 86_400.0


def _profile() -> list[dict[str, float]]:
    """A 30-minute calendar with a deep night valley and an evening peak.

    Price and carbon are aligned (both worst in the evening) so that every
    cost-driven policy prefers the same-day night and only ``asap`` can be
    pulled onto the preceding evening by the wider window.
    """

    rows: list[dict[str, float]] = []
    for index in range(48):
        start = float(index * 1800)
        hour = start / 3600.0
        if hour < 7.0:
            price, gco2 = 0.50, 300.0
        elif hour < 18.0:
            price, gco2 = 0.90, 500.0
        else:
            price, gco2 = 1.30, 700.0
        rows.append(
            {
                "horizon_second_start": start,
                "actual_gco2_per_kwh": gco2,
                "depot_energy_cny_per_kwh": price,
                "public_total_cny_per_kwh": price + 0.4,
            }
        )
    return rows


def _prices():
    return replace(
        CHINA_TEST_PRICES,
        charging_curve_id="L100_control",
        charging_soc_breakpoints=(0.0, 1.0),
        charging_relative_powers=(1.0,),
        depot_charging_curve_id=None,
        depot_charging_soc_breakpoints=None,
        depot_charging_relative_powers=None,
        public_charging_curve_id=None,
        public_charging_soc_breakpoints=None,
        public_charging_relative_powers=None,
        v_speed_ms=10.0,
        B_battery_kwh=60.0,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=30.0,
        carbon_price=0.2,
    )


def _instance() -> Instance:
    nodes = [
        Node(
            "D",
            "d",
            0.0,
            0.0,
            city="beijing",
            ready_time=0.0,
            due_time=DAY,
            station_chargers=4,
        ),
        Node(
            "A",
            "c",
            0.0,
            0.0,
            demand=1.0,
            ready_time=AM_START,
            due_time=AM_END,
            service_time=600.0,
        ),
        Node(
            "P",
            "c",
            0.0,
            0.0,
            demand=1.0,
            ready_time=PM_START,
            due_time=PM_END - 3600.0,
            service_time=600.0,
        ),
    ]
    leg = 30_000.0
    return Instance(
        nodes=nodes,
        distance_matrix=[
            [0.0, leg, leg],
            [leg, 0.0, leg],
            [leg, leg, 0.0],
        ],
        num_cv=1,
        num_ev=1,
    )


def _context(*, depot_charge_window_mode: str) -> DutyEvaluationContext:
    instance = _instance()
    bundle = China81Bundle(
        instance_id="first-trip-window-unit",
        region="test",
        date="2026-09-06",
        instance=instance,
        time_profile=_profile(),
        prices=_prices(),
        source_paths={},
        customer_home_depot={"A": "D", "P": "D"},
        price_area_by_city={},
        carbon_source_column_by_city={},
        diesel_zone_by_city={},
        diesel_price_by_city={"beijing": 7.48},
        fleet_caps_by_depot={
            "D": {"num_cv": 1, "num_ev": 1, "total_fleet_cap": 2}
        },
        fleet_parameter_class_id="unit-test",
        has_additional_total_fleet_cap=True,
        charger_scenario_by_node={},
        fleet_cap_semantics="unit-test",
        diesel_price_source_id="unit-test",
        static_input_authority="unit-test",
        road_matrix_authority="unit-test",
        runtime_parameter_authority="unit-test",
        fleet_authority="unit-test",
        model_config={},
        formal_search_allowed=False,
        carbon_price_cny_per_kg=0.2,
    )
    return DutyEvaluationContext(
        bundle=bundle,
        independent_profit={"D": 1.0},
        prior_profit={"D": 0.0},
        theta=0.0,
        carbon_quota_kg=float("inf"),
        depot_charge_window_mode=depot_charge_window_mode,
        fairness_enabled=False,
        shift_aware_departure_enabled=True,
        rebuilt_route_constraints=RebuiltRouteConstraintContract(
            source_id="unit-test-shift-contract",
            customer_shift_by_id={"A": "AM", "P": "PM"},
            customer_volume_m3_by_id={"A": 1.0, "P": 1.0},
            shift_window_second_by_id={
                "AM": (AM_START, AM_END),
                "PM": (PM_START, PM_END),
            },
            vehicle_volume_capacity_m3=7.2,
        ),
    )


def _policy(
    context: DutyEvaluationContext,
    *,
    charge_timing_policy: str,
    first_trip_window: str,
) -> ChargingRepairPolicy:
    return ChargingRepairPolicy(
        strategy="integrated",
        carbon_weight=1.0,
        depot_charge_window_mode=context.depot_charge_window_mode,
        charge_timing_policy=charge_timing_policy,
        charge_amount_strategy="just_enough",
        public_station_candidate_mode="parallel",
        carbon_profiles_by_day_offset=None,
        first_trip_window=first_trip_window,
    )


def _duty(customer_ids: tuple[tuple[str, ...], ...]) -> DutyIndividual:
    return DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "EV_D_1",
                "ev",
                "D",
                tuple(
                    DutyTrip(index + 1, ids)
                    for index, ids in enumerate(customer_ids)
                ),
            ),
        ),
        source="first-trip-window-unit",
    )


def _first_trip_depot_charge(individual: DutyIndividual):
    duty = individual.duties[0]
    sessions = [
        session
        for session in duty.charging_sessions
        if session.trip_index == 1 and session.station_id == "D"
    ]
    assert len(sessions) == 1, sessions
    return sessions[0]


def _settle(
    customer_ids: tuple[tuple[str, ...], ...],
    *,
    charge_timing_policy: str,
    first_trip_window: str,
):
    context = _context(
        depot_charge_window_mode=(
            "full_gap"
            if first_trip_window == FIRST_TRIP_WINDOW_PREV_RETURN
            else "same_day_predeparture"
        )
    )
    policy = _policy(
        context,
        charge_timing_policy=charge_timing_policy,
        first_trip_window=first_trip_window,
    )
    individual = _duty(customer_ids)
    repaired = repair_changed_duties(
        individual,
        individual,
        changed_duty_ids={"EV_D_1"},
        context=context,
        policy=policy,
    )
    return _first_trip_depot_charge(repaired)


def _absolute_start(session) -> float:
    return float(session.charge_day_offset) * DAY + float(
        session.charge_start_second
    )


def test_same_day_window_keeps_the_first_trip_charge_on_the_route_day() -> None:
    """The default is unchanged: the window still opens at day 0 00:00."""

    for policy_name in ("asap", "cost_plus_carbon"):
        session = _settle(
            (("A",), ("P",)),
            charge_timing_policy=policy_name,
            first_trip_window=FIRST_TRIP_WINDOW_SAME_DAY,
        )
        assert int(session.charge_day_offset) == 0
    asap = _settle(
        (("A",), ("P",)),
        charge_timing_policy="asap",
        first_trip_window=FIRST_TRIP_WINDOW_SAME_DAY,
    )
    assert float(asap.charge_start_second) == pytest.approx(0.0)


def test_prev_return_window_moves_asap_to_last_nights_depot_return() -> None:
    """``asap`` now plugs in the evening before, not at the day's 00:00."""

    session = _settle(
        (("A",), ("P",)),
        charge_timing_policy="asap",
        first_trip_window=FIRST_TRIP_WINDOW_PREV_RETURN,
    )
    assert int(session.charge_day_offset) == -1
    # The duty's own last trip leaves at 13:00 and needs 2 x 3000 s of driving
    # plus 600 s of service, so it is back at 14:50; the window opens exactly
    # there, one day earlier, and ``asap`` takes the first instant.
    assert float(session.charge_start_second) == pytest.approx(53_400.0)
    assert _absolute_start(session) == pytest.approx(-DAY + 53_400.0)
    # It is now in the evening peak, so it costs strictly more than 00:00.
    same_day = _settle(
        (("A",), ("P",)),
        charge_timing_policy="asap",
        first_trip_window=FIRST_TRIP_WINDOW_SAME_DAY,
    )
    assert float(same_day.charge_start_second) == pytest.approx(0.0)


def test_prev_return_window_leaves_cost_plus_carbon_on_the_night_valley()\
        -> None:
    """The merged window is a superset, so a cost policy cannot get worse."""

    widened = _settle(
        (("A",), ("P",)),
        charge_timing_policy="cost_plus_carbon",
        first_trip_window=FIRST_TRIP_WINDOW_PREV_RETURN,
    )
    narrow = _settle(
        (("A",), ("P",)),
        charge_timing_policy="cost_plus_carbon",
        first_trip_window=FIRST_TRIP_WINDOW_SAME_DAY,
    )
    # The preceding evening is the most expensive and dirtiest part of the
    # calendar, so the argmin stays exactly where the narrow window put it.
    assert int(widened.charge_day_offset) == int(narrow.charge_day_offset) == 0
    assert float(widened.charge_start_second) == pytest.approx(
        float(narrow.charge_start_second)
    )


def test_single_trip_duty_falls_back_to_the_last_shift_end() -> None:
    """With no previous trip the contract's last shift end (19:00) is used."""

    session = _settle(
        (("P",),),
        charge_timing_policy="asap",
        first_trip_window=FIRST_TRIP_WINDOW_PREV_RETURN,
    )
    assert int(session.charge_day_offset) == -1
    assert float(session.charge_start_second) == pytest.approx(PM_END)


def test_unknown_first_trip_window_is_refused() -> None:
    context = _context(depot_charge_window_mode="same_day_predeparture")
    with pytest.raises(ValueError, match="unknown first-trip charging window"):
        _policy(
            context,
            charge_timing_policy="asap",
            first_trip_window="whenever",
        )


def test_the_runner_default_is_the_papers_formal_window() -> None:
    """2026-09-06: ``prev_return`` is the default; ``same_day`` is opt-in.

    The parser is built inside ``main()``, so it is captured by interrupting
    ``parse_args`` rather than by running anything.
    """

    import argparse
    import sys
    from pathlib import Path

    scripts = Path(__file__).parents[1] / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import run_problem_hgs_private_technical as runner

    captured: dict[str, argparse.ArgumentParser] = {}

    class _Stop(Exception):
        pass

    def _capture(self, *args, **kwargs):
        captured["parser"] = self
        raise _Stop

    original = argparse.ArgumentParser.parse_args
    argparse.ArgumentParser.parse_args = _capture
    try:
        with pytest.raises(_Stop):
            runner.main()
    finally:
        argparse.ArgumentParser.parse_args = original

    parser = captured["parser"]
    assert parser.get_default("first_trip_window") == (
        FIRST_TRIP_WINDOW_PREV_RETURN
    )
    action = next(
        item
        for item in parser._actions
        if item.dest == "first_trip_window"
    )
    assert set(action.choices) == {
        FIRST_TRIP_WINDOW_SAME_DAY,
        FIRST_TRIP_WINDOW_PREV_RETURN,
    }
