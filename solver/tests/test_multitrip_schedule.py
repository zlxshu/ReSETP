from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy
from setp_solver.algorithms.resetp_alns.operators.feasible_repair import enumerate_feasible_insertions
from setp_solver.search.evaluation import EvaluationContext
from setp_solver.search.multitrip_schedule import (
    CHARGE_MODE_PARTIAL,
    CONTRACT_ID,
    build_multitrip_certificate,
    route_timing,
    validate_multitrip_certificate,
)
from setp_solver.solution import Route, Solution


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
    fast = build_multitrip_certificate(routes, _instance(), replace(prices, depot_charge_power_kw=600.0))
    slow = build_multitrip_certificate(routes, _instance(), replace(prices, depot_charge_power_kw=0.01))
    assert fast.vehicle_counts["ev"] == 1
    assert slow.vehicle_counts["ev"] == 2


def test_certificate_reads_depot_power_from_the_shared_price_object() -> None:
    routes = [
        Route("EV_A", "ev", "D0", ["D0", "C1", "D0"]),
        Route("EV_B", "ev", "D0", ["D0", "C2", "D0"]),
    ]
    prices = PriceParameters(B_battery_kwh=280.0, initial_ev_battery_kwh=280.0, depot_charge_power_kw=22.0)
    certificate = build_multitrip_certificate(routes, _instance(), prices)
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
    certificate = build_multitrip_certificate(routes, _instance(), prices)
    trip = certificate.trips[0]
    tampered = replace(
        certificate,
        trips=(replace(trip, charge_energy_kwh=0.0, charge_start_second=None, recharge_end_second=trip.return_second),),
    )

    with pytest.raises(ValueError, match="full recharge does not replenish"):
        validate_multitrip_certificate(tampered, routes, prices)


def test_v1_stops_instead_of_silently_ignoring_public_charging() -> None:
    route = Route("EV_A", "ev", "D0", ["D0", "F1", "C1", "D0"])
    with pytest.raises(ValueError, match="public-station trips are unsupported"):
        route_timing(route, _instance())


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
