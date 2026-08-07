from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy
from setp_solver.algorithms.resetp_alns.operators.feasible_repair import enumerate_feasible_insertions
from setp_solver.search.evaluation import EvaluationContext
from setp_solver.search.e3_multitrip_runtime import (
    complete_prepared_solution_violations,
    hard_violations as e3_hard_violations,
    prepare_and_score_reference,
)
from setp_solver.search.multitrip_schedule import (
    CHARGE_MODE_FULL,
    CHARGE_MODE_ON_DEMAND,
    CHARGE_MODE_PARTIAL,
    CONTRACT_ID,
    ContinuousSOCContract,
    E4_CONTINUOUS_SOC_CONTRACT_ID,
    STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET,
    STATIC_PREHORIZON_SECONDS,
    build_multitrip_certificate,
    certificate_charging_actions,
    prepare_multitrip_solution,
    reschedule_between_trip_charging,
    route_timing,
    validate_multitrip_certificate,
)
from setp_solver.solution import ChargingAction, Route, Solution
from setp_solver.check import BATTERY, check_solution


def _instance() -> Instance:
    nodes = [
        Node("D0", "d", 0, 0, due_time=100_000),
        Node("D1", "d", 0, 0, due_time=100_000),
        Node("C1", "c", 0, 0, demand=10, ready_time=1_000, due_time=4_000, service_time=100),
        Node("C2", "c", 0, 0, demand=10, ready_time=6_000, due_time=9_000, service_time=100),
        Node("C3", "c", 0, 0, demand=10, ready_time=1_000, due_time=4_000, service_time=100),
        Node("F1", "f", 0, 0, due_time=100_000),
    ]
    matrix = [[0.0 if i == j else 1_000.0 for j in range(len(nodes))] for i in range(len(nodes))]
    return Instance(nodes, matrix, num_cv=14, num_ev=14)


def test_two_separated_trips_share_one_physical_vehicle() -> None:
    routes = [
        Route("CV_A", "cv", "D0", ["D0", "C1", "D0"]),
        Route("CV_B", "cv", "D0", ["D0", "C2", "D0"]),
    ]
    cert = build_multitrip_certificate(routes, _instance())
    assert cert.contract_id == CONTRACT_ID
    assert cert.vehicle_counts == {"cv": 1, "ev": 0}
    assert {trip.physical_vehicle_id for trip in cert.trips} == {"CV_D0_1"}


def test_overlapping_trips_require_two_physical_vehicles() -> None:
    routes = [
        Route("CV_A", "cv", "D0", ["D0", "C1", "D0"]),
        Route("CV_B", "cv", "D0", ["D0", "C3", "D0"]),
    ]
    assert build_multitrip_certificate(routes, _instance()).vehicle_counts["cv"] == 2


def test_cross_depot_trips_cannot_share_vehicle() -> None:
    routes = [
        Route("CV_A", "cv", "D0", ["D0", "C1", "D0"]),
        Route("CV_B", "cv", "D1", ["D1", "C2", "D1"]),
    ]
    assert build_multitrip_certificate(routes, _instance()).vehicle_counts["cv"] == 2


def test_ev_recharge_time_participates_in_reuse() -> None:
    routes = [
        Route("EV_A", "ev", "D0", ["D0", "C1", "D0"]),
        Route("EV_B", "ev", "D0", ["D0", "C2", "D0"]),
    ]
    prices = PriceParameters(B_battery_kwh=280.0, initial_ev_battery_kwh=280.0)
    fast = build_multitrip_certificate(routes, _instance(), replace(prices, depot_charge_power_kw=600.0), recharge_mode=CHARGE_MODE_FULL)
    slow = build_multitrip_certificate(routes, _instance(), replace(prices, depot_charge_power_kw=0.01), recharge_mode=CHARGE_MODE_FULL)
    assert fast.vehicle_counts["ev"] == 1
    assert slow.vehicle_counts["ev"] == 2


def test_certificate_reads_depot_power_from_the_shared_price_object() -> None:
    routes = [
        Route("EV_A", "ev", "D0", ["D0", "C1", "D0"]),
        Route("EV_B", "ev", "D0", ["D0", "C2", "D0"]),
    ]
    prices = PriceParameters(B_battery_kwh=280.0, initial_ev_battery_kwh=280.0, depot_charge_power_kw=22.0)
    certificate = build_multitrip_certificate(routes, _instance(), prices, recharge_mode=CHARGE_MODE_FULL)
    assert certificate.depot_charge_power_kw == 22.0


def test_certificate_has_no_hard_coded_60kw_depot_default() -> None:
    source = (Path(__file__).parents[1] / "src/setp_solver/search/multitrip_schedule.py").read_text(encoding="utf-8")
    assert "depot_charge_power_kw: float = 60.0" not in source
    assert '_price(prices, "depot_charge_power_kw")' in source


def test_partial_mode_keeps_a_continuous_battery_ledger() -> None:
    routes = [
        Route("EV_A", "ev", "D0", ["D0", "C1", "D0"]),
        Route("EV_B", "ev", "D0", ["D0", "C2", "D0"]),
    ]
    prices = PriceParameters(B_battery_kwh=280.0, initial_ev_battery_kwh=280.0, depot_charge_power_kw=22.0)
    certificate = build_multitrip_certificate(routes, _instance(), prices, recharge_mode=CHARGE_MODE_PARTIAL)
    by_index = sorted(certificate.trips, key=lambda trip: trip.trip_index)
    assert certificate.recharge_mode == CHARGE_MODE_PARTIAL
    assert len(by_index) == 2
    assert by_index[1].start_battery_kwh == pytest.approx(
        by_index[0].end_battery_kwh + (by_index[0].charge_energy_kwh or 0.0)
    )


def test_full_mode_certificate_must_replenish_the_energy_it_used() -> None:
    routes = [Route("EV_A", "ev", "D0", ["D0", "C1", "D0"])]
    prices = PriceParameters(B_battery_kwh=280.0, initial_ev_battery_kwh=280.0, depot_charge_power_kw=22.0)
    certificate = build_multitrip_certificate(routes, _instance(), prices, recharge_mode=CHARGE_MODE_FULL)
    trip = certificate.trips[0]
    tampered = replace(
        certificate,
        trips=(replace(trip, charge_energy_kwh=0.0, charge_start_second=None, recharge_end_second=trip.return_second),),
    )

    with pytest.raises(ValueError, match="full recharge does not replenish"):
        validate_multitrip_certificate(tampered, routes, prices)


def test_on_demand_mode_charges_only_what_the_next_trip_needs() -> None:
    routes = [
        Route("EV_A", "ev", "D0", ["D0", "C1", "D0"]),
        Route("EV_B", "ev", "D0", ["D0", "C2", "D0"]),
    ]
    prices = PriceParameters(B_battery_kwh=280.0, initial_ev_battery_kwh=280.0, depot_charge_power_kw=22.0)
    certificate = build_multitrip_certificate(routes, _instance(), prices, recharge_mode=CHARGE_MODE_ON_DEMAND)
    ordered = sorted(certificate.trips, key=lambda trip: trip.trip_index)
    expected = max(0.0, float(ordered[1].start_battery_kwh) - float(ordered[0].end_battery_kwh))
    assert float(ordered[0].charge_energy_kwh or 0.0) == pytest.approx(expected)


def test_between_trip_charge_is_exported_to_cost_and_carbon_ledger() -> None:
    routes = [
        Route("EV_A", "ev", "D0", ["D0", "C1", "D0"]),
        Route("EV_B", "ev", "D0", ["D0", "C2", "D0"]),
    ]
    base = PriceParameters(B_battery_kwh=280.0, initial_ev_battery_kwh=280.0, depot_charge_power_kw=22.0)
    one_trip_need = route_timing(routes[0], _instance(), base).drive_energy_kwh
    prices = replace(base, B_battery_kwh=one_trip_need * 1.5, initial_ev_battery_kwh=one_trip_need * 1.5)
    certificate = build_multitrip_certificate(routes, _instance(), prices, recharge_mode=CHARGE_MODE_ON_DEMAND)
    actions = certificate_charging_actions(certificate)
    assert actions
    assert sum(action.energy_kwh for action in actions) == pytest.approx(
        sum(float(trip.charge_energy_kwh or 0.0) for trip in certificate.trips)
    )


def test_e4_continuous_soc_contract_retains_terminal_charge_in_trip_ledger() -> None:
    route = Route("EV_A", "ev", "D0", ["D0", "C1", "D0"])
    instance = _instance()
    prices = PriceParameters(
        B_battery_kwh=10.0,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=22.0,
    )
    drive = route_timing(route, instance, prices).drive_energy_kwh
    start_energy = 4.0 - drive
    duration = drive / prices.depot_charge_power_kw * 3_600.0
    return_second = route_timing(route, instance, prices).return_second
    next_departure = (
        route_timing(route, instance, prices).earliest_departure_second + 86_400.0
    )
    saved_start = return_second
    terminal = {
        "vehicle_id": route.vehicle_id,
        "station_id": route.home_depot_id,
        "energy_kwh": drive,
        "start_soc": 0.20 + start_energy / 10.0,
        "end_soc": 0.60,
        "occupancy_minutes": duration / 60.0,
        "start_second_absolute": saved_start,
        "end_second_absolute": saved_start + duration,
        "latest_second_absolute": next_departure - duration,
        "day_offset": 0,
        "electricity_cost_cny": 1.25,
        "emissions_kg": 2.5,
    }
    contract = ContinuousSOCContract(
        E4_CONTINUOUS_SOC_CONTRACT_ID,
        0.60,
        0.20,
        0.80,
        0.60,
        (terminal,),
    )

    prepared, certificate = prepare_multitrip_solution(
        Solution(routes=[route]),
        instance,
        prices,
        continuous_soc_contract=contract,
    )

    trip = certificate.trips[0]
    entry = certificate.depot_charge_ledger[0]
    assert prepared.charging_actions == []
    assert trip.start_battery_kwh == pytest.approx(4.0)
    assert trip.end_battery_kwh == pytest.approx(start_energy)
    assert entry.energy_kwh == pytest.approx(drive)
    assert entry.after_route_id == prepared.routes[0].vehicle_id
    assert entry.relation == "between_trip_next_day_cycle"
    assert entry.start_battery_kwh == pytest.approx(start_energy)
    assert entry.end_battery_kwh == pytest.approx(4.0)

    broken = replace(
        contract,
        terminal_charges=({**terminal, "energy_kwh": drive + 0.1},),
    )
    with pytest.raises(ValueError, match="terminal energy"):
        prepare_multitrip_solution(
            Solution(routes=[route]),
            instance,
            prices,
            continuous_soc_contract=broken,
        )


def test_complete_multitrip_checker_replaces_only_certified_residual_battery() -> None:
    from setp_solver.charging_curve import NL90_MILD

    source = _instance()
    nodes = [
        source.nodes[0],
        source.nodes[2],
        replace(source.nodes[3], ready_time=1_380.0, due_time=4_380.0),
    ]
    matrix = [[0.0 if i == j else 1_000.0 for j in range(3)] for i in range(3)]
    instance = Instance(nodes, matrix, num_cv=2, num_ev=2)
    routes = [
        Route("EV_A", "ev", "D0", ["D0", "C1", "D0"]),
        Route("EV_B", "ev", "D0", ["D0", "C2", "D0"]),
    ]
    probe = PriceParameters(B_battery_kwh=280.0)
    drive = route_timing(routes[0], instance, probe).drive_energy_kwh
    prices = PriceParameters(
        B_battery_kwh=drive * 1.05,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=22.0,
        charging_curve_id=NL90_MILD.curve_id,
        charging_soc_breakpoints=NL90_MILD.soc_breakpoints,
        charging_relative_powers=NL90_MILD.relative_powers,
    )
    prepared, certificate = prepare_multitrip_solution(
        Solution(routes=routes),
        instance,
        prices,
    )
    static_battery = [
        item for item in check_solution(prepared, instance, prices)
        if item.type == BATTERY
    ]
    assert static_battery
    assert complete_prepared_solution_violations(
        prepared,
        certificate,
        instance,
        prices,
    ) == []


def _two_trip_solution_and_prices() -> tuple[Solution, PriceParameters]:
    routes = [
        Route("EV_A", "ev", "D0", ["D0", "C1", "D0"]),
        Route("EV_B", "ev", "D0", ["D0", "C2", "D0"]),
    ]
    base = PriceParameters(B_battery_kwh=280.0, initial_ev_battery_kwh=0.0, depot_charge_power_kw=22.0)
    need = route_timing(routes[0], _instance(), base).drive_energy_kwh
    prices = replace(base, B_battery_kwh=need * 1.5)
    actions = [
        ChargingAction(route.vehicle_id, "D0", need * 1.5, need * 1.5 / 22.0 * 60.0, 10_000.0)
        for route in routes
    ]
    return Solution(routes=routes, charging_actions=actions), prices


def test_prepare_multitrip_solution_replaces_route_level_recharge_with_gap_ledger() -> None:
    solution, prices = _two_trip_solution_and_prices()
    prepared, certificate = prepare_multitrip_solution(solution, _instance(), prices)
    ordered = sorted(certificate.trips, key=lambda trip: trip.trip_index)
    assert len({trip.physical_vehicle_id for trip in ordered}) == 1
    assert len(prepared.charging_actions) == 2
    assert prepared.charging_actions[1].energy_kwh == pytest.approx(
        float(ordered[1].start_battery_kwh) - float(ordered[0].end_battery_kwh)
    )


def test_prepare_multitrip_solution_is_idempotent() -> None:
    solution, prices = _two_trip_solution_and_prices()
    first, first_certificate = prepare_multitrip_solution(
        solution,
        _instance(),
        prices,
    )
    second, second_certificate = prepare_multitrip_solution(
        first,
        _instance(),
        prices,
        depot_charge_window_mode="full_gap",
    )
    assert second == first
    assert first_certificate.first_trip_charge_day_offset == -1
    assert second_certificate.first_trip_charge_day_offset == -1


def test_repeated_preparation_preserves_same_day_first_trip_charging() -> None:
    solution, prices = _two_trip_solution_and_prices()
    first, first_certificate = prepare_multitrip_solution(
        solution,
        _instance(),
        prices,
        depot_charge_window_mode="same_day_predeparture",
    )
    second, second_certificate = prepare_multitrip_solution(
        first,
        _instance(),
        prices,
        depot_charge_window_mode="full_gap",
    )

    assert second == first
    assert first_certificate.first_trip_charge_day_offset == 0
    assert second_certificate.first_trip_charge_day_offset == 0


def test_prepare_multitrip_solution_accounts_first_trip_precharge_from_zero() -> None:
    base_solution, prices = _two_trip_solution_and_prices()
    solution = replace(base_solution, charging_actions=[])
    prepared, certificate = prepare_multitrip_solution(solution, _instance(), prices)
    drive = sum(route_timing(route, _instance(), prices).drive_energy_kwh for route in solution.routes)
    last_by_vehicle = {}
    for trip in certificate.trips:
        previous = last_by_vehicle.get(trip.physical_vehicle_id)
        if previous is None or trip.trip_index > previous.trip_index:
            last_by_vehicle[trip.physical_vehicle_id] = trip
    residual = sum(float(trip.end_battery_kwh or 0.0) for trip in last_by_vehicle.values())
    assert sum(action.energy_kwh for action in prepared.charging_actions) == pytest.approx(drive + residual)
    assert any(trip.trip_index == 1 for trip in certificate.trips)
    assert certificate.first_trip_charge_day_offset == STATIC_FIRST_TRIP_CHARGE_DAY_OFFSET
    first = min(certificate.trips, key=lambda trip: trip.trip_index)
    first_action = next(action for action in prepared.charging_actions if action.vehicle_id == first.route_id)
    absolute_end = (
        first_action.charge_start_second
        + certificate.first_trip_charge_day_offset * STATIC_PREHORIZON_SECONDS
        + first_action.occupancy_minutes * 60.0
    )
    assert 0.0 <= first_action.charge_start_second < STATIC_PREHORIZON_SECONDS
    assert absolute_end <= first.departure_second + 1e-6


def test_first_trip_aware_replay_uses_only_the_pre_horizon_day(monkeypatch: pytest.MonkeyPatch) -> None:
    solution, prices = _two_trip_solution_and_prices()
    prepared, certificate = prepare_multitrip_solution(solution, _instance(), prices)
    profile = [
        {"slot_index": i, "horizon_second_start": i * 1800.0, "actual_gco2_per_kwh": 300.0 if i < 4 else 50.0}
        for i in range(48)
    ]
    naive = reschedule_between_trip_charging(
        prepared,
        certificate,
        _instance(),
        profile,
        strategy="naive",
        prices=prices,
    )
    aware = reschedule_between_trip_charging(
        prepared,
        certificate,
        _instance(),
        profile,
        strategy="aware",
        prices=prices,
    )
    naive_first = next(action for action in naive.charging_actions if "#T1" in action.vehicle_id)
    aware_first = next(action for action in aware.charging_actions if "#T1" in action.vehicle_id)
    assert naive_first.charge_start_second == pytest.approx(0.0)
    assert aware_first.charge_start_second > naive_first.charge_start_second
    assert aware_first.charge_start_second + aware_first.occupancy_minutes * 60.0 <= STATIC_PREHORIZON_SECONDS + 1e-6
    source = _instance()
    instance = Instance(source.nodes[:4], [row[:4] for row in source.distance_matrix[:4]], num_cv=14, num_ev=14)
    context = EvaluationContext(instance, profile, prices=prices)
    monkeypatch.setenv("SETP_E3_STRICT_MULTITRIP", "1")
    assert e3_hard_violations(aware, context) == []


def test_calendar_aware_replay_uses_previous_day_forecast_for_first_trip() -> None:
    solution, prices = _two_trip_solution_and_prices()
    prepared, certificate = prepare_multitrip_solution(solution, _instance(), prices)
    operating_day = [
        {
            "slot_index": i,
            "horizon_second_start": i * 1800.0,
            "actual_gco2_per_kwh": 10.0 if i == 2 else 300.0,
            "forecast_gco2_per_kwh": 10.0 if i == 2 else 300.0,
        }
        for i in range(48)
    ]
    previous_day = [
        {
            "slot_index": i,
            "horizon_second_start": i * 1800.0,
            "actual_gco2_per_kwh": 10.0 if i == 3 else 300.0,
            "forecast_gco2_per_kwh": 10.0 if i == 30 else 300.0,
        }
        for i in range(48)
    ]

    forecast_timed = reschedule_between_trip_charging(
        prepared,
        certificate,
        _instance(),
        operating_day,
        strategy="aware",
        prices=prices,
        carbon_profiles_by_day_offset={-1: previous_day, 0: operating_day},
        intensity_field="forecast_gco2_per_kwh",
    )
    actual_oracle = reschedule_between_trip_charging(
        prepared,
        certificate,
        _instance(),
        operating_day,
        strategy="aware",
        prices=prices,
        carbon_profiles_by_day_offset={-1: previous_day, 0: operating_day},
        intensity_field="actual_gco2_per_kwh",
    )
    forecast_first = next(action for action in forecast_timed.charging_actions if "#T1" in action.vehicle_id)
    oracle_first = next(action for action in actual_oracle.charging_actions if "#T1" in action.vehicle_id)
    assert forecast_first.charge_start_second > 12 * 3600.0
    assert oracle_first.charge_start_second < 4 * 3600.0
    assert forecast_first.charge_start_second != pytest.approx(oracle_first.charge_start_second)


def test_calendar_aware_replay_rejects_missing_previous_day_profile() -> None:
    solution, prices = _two_trip_solution_and_prices()
    prepared, certificate = prepare_multitrip_solution(solution, _instance(), prices)
    profile = [
        {
            "slot_index": i,
            "horizon_second_start": i * 1800.0,
            "actual_gco2_per_kwh": 100.0,
            "forecast_gco2_per_kwh": 100.0,
        }
        for i in range(48)
    ]
    with pytest.raises(ValueError, match="charge_day_offset=-1"):
        reschedule_between_trip_charging(
            prepared,
            certificate,
            _instance(),
            profile,
                strategy="aware",
                prices=prices,
                carbon_profiles_by_day_offset={0: profile},
            intensity_field="forecast_gco2_per_kwh",
        )


def test_between_trip_aware_replay_moves_only_within_the_legal_gap() -> None:
    solution, prices = _two_trip_solution_and_prices()
    prepared, certificate = prepare_multitrip_solution(solution, _instance(), prices)
    profile = [
        {"slot_index": i, "horizon_second_start": i * 1800.0, "actual_gco2_per_kwh": 300.0 if i == 0 else 50.0}
        for i in range(48)
    ]
    naive = reschedule_between_trip_charging(
        prepared,
        certificate,
        _instance(),
        profile,
        strategy="naive",
        prices=prices,
    )
    aware = reschedule_between_trip_charging(
        prepared,
        certificate,
        _instance(),
        profile,
        strategy="aware",
        prices=prices,
    )
    naive_gap = [action for action in naive.charging_actions if "#T2" in action.vehicle_id][0]
    aware_gap = [action for action in aware.charging_actions if "#T2" in action.vehicle_id][0]
    previous = min(certificate.trips, key=lambda trip: trip.trip_index)
    current = max(certificate.trips, key=lambda trip: trip.trip_index)
    assert naive_gap.charge_start_second == pytest.approx(previous.return_second)
    assert previous.return_second <= aware_gap.charge_start_second
    assert aware_gap.charge_start_second + aware_gap.occupancy_minutes * 60.0 <= current.departure_second + 1e-6


def test_e3_runtime_carries_previous_trip_battery_without_changing_legacy_checker(monkeypatch: pytest.MonkeyPatch) -> None:
    solution, prices = _two_trip_solution_and_prices()
    source = _instance()
    instance = Instance(source.nodes[:4], [row[:4] for row in source.distance_matrix[:4]], num_cv=14, num_ev=14)
    profile = [
        {"slot_index": i, "horizon_second_start": i * 1800.0, "actual_gco2_per_kwh": 100.0}
        for i in range(48)
    ]
    context = EvaluationContext(instance, profile, prices=prices)
    monkeypatch.setenv("SETP_E3_STRICT_MULTITRIP", "1")
    prepared, objective = prepare_and_score_reference(solution, context)
    assert objective < 1_000_000_000.0
    assert e3_hard_violations(prepared, context) == []


def test_strict_schedule_stops_instead_of_ignoring_unbound_public_charge() -> None:
    route = Route("EV_A", "ev", "D0", ["D0", "F1", "C1", "D0"])
    action = ChargingAction(
        "EV_A",
        "F1",
        1.0,
        1.0,
        1_000.0,
    )
    with pytest.raises(ValueError, match="charging"):
        route_timing(
            route,
            _instance(),
            charging_actions=[action],
        )


def test_route_must_return_to_same_home_depot() -> None:
    route = Route("CV_A", "cv", "D0", ["D0", "C1", "D1"])
    with pytest.raises(ValueError, match="does not return"):
        route_timing(route, _instance())


def test_strict_e3_new_route_gate_counts_physical_vehicles_not_route_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    nodes = [Node("D0", "d", 0, 0, due_time=100_000)]
    nodes.extend(
        Node(f"C{index}", "c", 0, 0, demand=10, ready_time=float(index * 600), due_time=float(index * 600 + 120), service_time=10)
        for index in range(1, 16)
    )
    matrix = [[0.0 if i == j else 1_000.0 for j in range(len(nodes))] for i in range(len(nodes))]
    instance = Instance(nodes, matrix, num_cv=14, num_ev=14)
    solution = Solution(routes=[Route(f"CV{index}", "cv", "D0", ["D0", f"C{index}", "D0"]) for index in range(1, 15)])
    context = EvaluationContext(instance, [])
    policy = SearchPolicy(max_cv=14, max_ev=14)
    monkeypatch.setenv("SETP_E3_STRICT_MULTITRIP", "1")

    options = enumerate_feasible_insertions(solution, "C15", context, policy)

    assert any(option.opened_new_route for option in options)
    assert context.score_counts["strict_multitrip_new_route_admissible"] >= 1
