"""Two vehicles of one plan may charge on different days (2026-09-06).

Under ``--first-trip-window prev_return`` a first-trip depot charge may start
the preceding evening, and each vehicle then chooses between that evening and
the simulation day's own hours on its own merits: the two halves of the merged
window are bounded by that vehicle's own latest departure, so an AM vehicle
and a PM vehicle do not see the same choice.  One plan therefore mixes day
offsets.

Until today the multi-trip certificate recorded ONE first-trip charge day for
the whole plan and refused a mixed one outright ("first-trip depot charges use
inconsistent day offsets"), which left 7/10 and 10/10 of the carbon-price-1.0
solutions unscoreable in the 2026-09-06 projection.  Each duty now carries its
own day; the plan-wide scalar is the earliest day the plan reaches.
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
    DutyFullEvaluator,
    RebuiltRouteConstraintContract,
)
from setp_solver.algorithms.problem_hgs.model import (
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
)
from setp_solver.china81 import China81Bundle
from setp_solver.instance_loader import Instance, Node
from setp_solver.search.multitrip_schedule import prepare_multitrip_solution
from solver.tests.china_test_prices import CHINA_TEST_PRICES


AM_START = 8 * 3600.0
AM_END = 11 * 3600.0
PM_START = 13 * 3600.0
PM_END = 19 * 3600.0
DAY = 86_400.0
CLEAN_START = 15 * 3600.0
CLEAN_END = 16 * 3600.0 + 1800.0
EVENING_START = 18 * 3600.0
NIGHT_END = 7 * 3600.0


def _profile() -> list[dict[str, float]]:
    """A calendar with a clean afternoon, a clean evening and a fair night.

    Shaped like the beijing calendar the 2026-09-06 projection ran on, where
    the afternoon is the grid's cleanest window.  The three tiers are ordered
    so that the choice between "the preceding evening" and "the day's own
    hours" depends on how late the vehicle is allowed to leave:

    * 15:00-16:30 is the best price and the least carbon -- reachable only by
      a vehicle whose own departure is late enough;
    * 18:00-24:00 is second best -- the whole preceding-evening half of the
      merged window sits inside it;
    * 00:00-07:00 is the night valley, worse than either.
    """

    rows: list[dict[str, float]] = []
    for index in range(48):
        start = float(index * 1800)
        if CLEAN_START <= start < CLEAN_END:
            price, gco2 = 0.10, 20.0
        elif start >= EVENING_START:
            price, gco2 = 0.20, 50.0
        elif start < NIGHT_END:
            price, gco2 = 0.50, 300.0
        else:
            price, gco2 = 0.90, 500.0
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
            "Q",
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
    size = len(nodes)
    matrix = [
        [0.0 if row == col else leg for col in range(size)]
        for row in range(size)
    ]
    return Instance(nodes=nodes, distance_matrix=matrix, num_cv=0, num_ev=2)


def _context(*, depot_charge_window_mode: str = "full_gap"):
    instance = _instance()
    bundle = China81Bundle(
        instance_id="mixed-first-trip-day-unit",
        region="test",
        date="2026-09-06",
        instance=instance,
        time_profile=_profile(),
        prices=_prices(),
        source_paths={},
        customer_home_depot={"A": "D", "Q": "D"},
        price_area_by_city={},
        carbon_source_column_by_city={},
        diesel_zone_by_city={},
        diesel_price_by_city={"beijing": 7.48},
        fleet_caps_by_depot={
            "D": {"num_cv": 0, "num_ev": 2, "total_fleet_cap": 2}
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
            customer_shift_by_id={"A": "AM", "Q": "PM"},
            customer_volume_m3_by_id={"A": 1.0, "Q": 1.0},
            shift_window_second_by_id={
                "AM": (AM_START, AM_END),
                "PM": (PM_START, PM_END),
            },
            vehicle_volume_capacity_m3=7.2,
        ),
    )


def _policy(context, *, first_trip_window: str) -> ChargingRepairPolicy:
    return ChargingRepairPolicy(
        strategy="integrated",
        carbon_weight=1.0,
        depot_charge_window_mode=context.depot_charge_window_mode,
        charge_timing_policy="cost_plus_carbon",
        charge_amount_strategy="just_enough",
        public_station_candidate_mode="parallel",
        carbon_profiles_by_day_offset=None,
        first_trip_window=first_trip_window,
    )


def _individual() -> DutyIndividual:
    return DutyIndividual(
        duties=(
            # Morning duty: it must be back inside the AM shift, so its own
            # day cannot reach the clean afternoon and the preceding evening
            # beats the night valley.
            PhysicalVehicleDuty("EV_D_1", "ev", "D", (DutyTrip(1, ("A",)),)),
            # Afternoon duty: it may leave as late as 17:10, so the clean
            # afternoon of its OWN day beats the preceding evening.
            PhysicalVehicleDuty("EV_D_2", "ev", "D", (DutyTrip(1, ("Q",)),)),
        ),
        source="mixed-first-trip-day-unit",
    )


def _settled(*, first_trip_window: str = FIRST_TRIP_WINDOW_PREV_RETURN):
    context = _context(
        depot_charge_window_mode=(
            "full_gap"
            if first_trip_window == FIRST_TRIP_WINDOW_PREV_RETURN
            else "same_day_predeparture"
        )
    )
    individual = _individual()
    repaired = repair_changed_duties(
        individual,
        individual,
        changed_duty_ids={"EV_D_1", "EV_D_2"},
        context=context,
        policy=_policy(context, first_trip_window=first_trip_window),
    )
    return context, repaired


def _first_trip_charges(individual) -> dict[str, tuple[int, float]]:
    return {
        duty.physical_vehicle_id: (
            int(session.charge_day_offset),
            float(session.charge_start_second),
        )
        for duty in individual.duties
        for session in duty.charging_sessions
        if int(session.trip_index) == 1 and session.station_id == "D"
    }


def test_the_two_vehicles_really_do_charge_on_different_days() -> None:
    """The premise of every assertion below, stated as its own check."""

    _unused, repaired = _settled()
    charges = _first_trip_charges(repaired)
    assert set(charges) == {"EV_D_1", "EV_D_2"}
    # The morning duty takes the preceding evening.
    assert charges["EV_D_1"][0] == -1
    assert charges["EV_D_1"][1] >= EVENING_START
    # The afternoon duty stays on its own day, in the clean afternoon.
    assert charges["EV_D_2"][0] == 0
    assert CLEAN_START <= charges["EV_D_2"][1] < CLEAN_END


def test_a_mixed_plan_can_be_evaluated_at_all() -> None:
    """It used to raise ``inconsistent day offsets`` and score nothing."""

    context, repaired = _settled()
    evaluation = DutyFullEvaluator(context).evaluate(repaired)
    assert evaluation.feasible, evaluation.violations
    assert evaluation.breakdown["total_cost"] > 0.0


def test_the_certificate_records_each_duty_s_own_day() -> None:
    context, repaired = _settled()
    certificate = DutyFullEvaluator(context).evaluate(repaired).certificate
    by_route = dict(certificate.first_trip_charge_day_offset_by_route)
    assert by_route == {"EV_D_1#T1": -1, "EV_D_2#T1": 0}
    # Sorted by route id, so the field is stable across runs.
    assert list(certificate.first_trip_charge_day_offset_by_route) == sorted(
        certificate.first_trip_charge_day_offset_by_route
    )
    assert certificate.first_trip_charge_day_offset_for("EV_D_1#T1") == -1
    assert certificate.first_trip_charge_day_offset_for("EV_D_2#T1") == 0
    # A duty the map does not mention falls back to the plan-wide scalar.
    assert certificate.first_trip_charge_day_offset_for("EV_D_9#T1") == int(
        certificate.first_trip_charge_day_offset
    )
    # The scalar summary is the earliest day the plan reaches, so every gate
    # that only asks "does this plan reach before the simulation day" (the
    # dynamic contract, for one) still sees the pre-horizon day.
    assert certificate.first_trip_charge_day_offset == -1


def test_the_mixed_plan_replays_through_the_prepared_certificate() -> None:
    """Re-preparing an already prepared mixed solution keeps every day."""

    context, repaired = _settled()
    prepared = DutyFullEvaluator(context).evaluate(repaired).prepared_solution
    replayed, certificate = prepare_multitrip_solution(
        prepared,
        context.bundle.instance,
        context.bundle.prices,
        depot_charge_window_mode="full_gap",
    )
    assert dict(certificate.first_trip_charge_day_offset_by_route) == {
        "EV_D_1#T1": -1,
        "EV_D_2#T1": 0,
    }
    replayed_days = {
        (action.vehicle_id, int(action.charge_day_offset))
        for action in replayed.charging_actions
    }
    original_days = {
        (action.vehicle_id, int(action.charge_day_offset))
        for action in prepared.charging_actions
    }
    assert replayed_days == original_days


def test_the_mixed_plan_costs_what_each_vehicle_s_own_day_costs() -> None:
    """The bill is per action, so the two days are priced separately."""

    context, repaired = _settled()
    evaluation = DutyFullEvaluator(context).evaluate(repaired)
    charges = _first_trip_charges(repaired)
    rows = {
        float(row["horizon_second_start"]): row for row in _profile()
    }

    def _slot(second: float):
        return rows[max(key for key in rows if key <= second)]

    energy = {
        duty.physical_vehicle_id: sum(
            float(session.energy_kwh)
            for session in duty.charging_sessions
            if int(session.trip_index) == 1 and session.station_id == "D"
        )
        for duty in repaired.duties
    }
    expected_elec = sum(
        energy[vehicle]
        * float(_slot(start)["depot_energy_cny_per_kwh"])
        for vehicle, (_offset, start) in charges.items()
    )
    assert evaluation.breakdown["cost_elec"] == pytest.approx(
        expected_elec, rel=1e-9
    )
    # Priced on two different tiers, so the two vehicles cannot be collapsed
    # onto one day without changing the bill.
    assert _slot(charges["EV_D_1"][1])["depot_energy_cny_per_kwh"] != _slot(
        charges["EV_D_2"][1]
    )["depot_energy_cny_per_kwh"]


def test_a_uniform_plan_keeps_the_scalar_it_always_had() -> None:
    """Every artefact written before today has one day; nothing moves."""

    context, repaired = _settled(first_trip_window=FIRST_TRIP_WINDOW_SAME_DAY)
    certificate = DutyFullEvaluator(context).evaluate(repaired).certificate
    assert set(_first_trip_charges(repaired)) == {"EV_D_1", "EV_D_2"}
    assert {
        offset for offset, _start in _first_trip_charges(repaired).values()
    } == {0}
    assert certificate.first_trip_charge_day_offset == 0
    assert dict(certificate.first_trip_charge_day_offset_by_route) == {
        "EV_D_1#T1": 0,
        "EV_D_2#T1": 0,
    }
