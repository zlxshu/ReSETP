from __future__ import annotations

from dataclasses import replace

import pytest

from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.search.multitrip_schedule import CONTRACT_ID, build_multitrip_certificate, route_timing
from setp_solver.solution import Route


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
    fast = build_multitrip_certificate(routes, _instance(), prices, depot_charge_power_kw=600.0)
    slow = build_multitrip_certificate(routes, _instance(), prices, depot_charge_power_kw=0.01)
    assert fast.vehicle_counts["ev"] == 1
    assert slow.vehicle_counts["ev"] == 2


def test_v1_stops_instead_of_silently_ignoring_public_charging() -> None:
    route = Route("EV_A", "ev", "D0", ["D0", "F1", "C1", "D0"])
    with pytest.raises(ValueError, match="public-station trips are unsupported"):
        route_timing(route, _instance())


def test_route_must_return_to_same_home_depot() -> None:
    route = Route("CV_A", "cv", "D0", ["D0", "C1", "D1"])
    with pytest.raises(ValueError, match="does not return"):
        route_timing(route, _instance())
