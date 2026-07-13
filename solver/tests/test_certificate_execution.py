from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.certificate_execution import (
    COMPLETED,
    IN_PROGRESS,
    NOT_STARTED,
    build_certificate_execution_ledger,
)
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.search.multitrip_schedule import MultiTripCertificate, ScheduledTrip
from setp_solver.prices import DEFAULT_PRICES


ROOT = Path(__file__).resolve().parents[2]
E3 = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713"
E6 = ROOT / "baselines/e6_fairness/e6_participation_formal_20260714"
CASE = "L-main-threeshift-50c-01__geographic__seed1__no_loss"


def _formal_114_customer_case():
    solution = solution_from_dict(json.loads((E6 / "solutions" / f"{CASE}.json").read_text(encoding="utf-8")))
    payload = json.loads((E6 / "certificates" / f"{CASE}.json").read_text(encoding="utf-8"))
    certificate = MultiTripCertificate(
        contract_id=str(payload["contract_id"]),
        status=str(payload["status"]),
        vehicle_counts={str(key): int(value) for key, value in payload["vehicle_counts"].items()},
        trips=tuple(ScheduledTrip(**row) for row in payload["trips"]),
        recharge_mode=str(payload["recharge_mode"]),
        depot_charge_power_kw=float(payload["depot_charge_power_kw"]),
        first_trip_charge_day_offset=int(payload["first_trip_charge_day_offset"]),
    )
    bundle = load_search_bundle(E3 / "assets" / "L-main-threeshift-50c-01" / "bundle")
    assert sum(node.node_type.lower() == "c" for node in bundle.instance.nodes) == 114
    return solution, certificate, bundle


def test_formal_114_customer_certificate_replays_absolute_clock_without_search() -> None:
    solution, certificate, bundle = _formal_114_customer_case()
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0, initial_ev_battery_kwh=0.0, carbon_price=0.0)
    ledger = build_certificate_execution_ledger(solution, certificate, bundle.instance, prices)

    second = ledger.routes["CV_D0_1#T2"]
    assert second.physical_vehicle_id == "CV_D0_1"
    assert second.trip_index == 2
    assert second.nodes[0].departure_second == pytest.approx(second.departure_second)
    assert second.nodes[-1].departure_second == pytest.approx(second.return_second)
    route = next(route for route in solution.routes if route.vehicle_id == second.route_id)
    first_customer = route.node_sequence[1]
    expected_arrival = (
        second.departure_second
        + bundle.instance.distance(route.home_depot_id, first_customer) / prices.v_speed_ms
    )
    assert second.nodes[1].arrival_second == pytest.approx(expected_arrival)
    assert ledger.trip_state_at(second.route_id, second.departure_second - 1.0) == NOT_STARTED
    assert ledger.trip_state_at(second.route_id, second.departure_second - 1e-9) == NOT_STARTED
    assert ledger.trip_state_at(second.route_id, second.departure_second) == IN_PROGRESS
    assert ledger.trip_state_at(second.route_id, second.return_second) == COMPLETED
    assert ledger.assets["CV_D0_1"].route_ids == ("CV_D0_1#T1", "CV_D0_1#T2")
    assert len(ledger.certificate_sha256) == 64


def test_replay_rejects_a_certificate_return_clock_drift() -> None:
    solution, certificate, bundle = _formal_114_customer_case()
    first = certificate.trips[0]
    tampered = replace(
        certificate,
        trips=(replace(first, return_second=first.return_second + 1.0), *certificate.trips[1:]),
    )

    with pytest.raises(ValueError, match="replay returns"):
        prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0, initial_ev_battery_kwh=0.0, carbon_price=0.0)
        build_certificate_execution_ledger(solution, tampered, bundle.instance, prices)


def test_replay_rejects_route_to_physical_vehicle_rebinding() -> None:
    solution, certificate, bundle = _formal_114_customer_case()
    counts = {
        trip.physical_vehicle_id: sum(
            other.physical_vehicle_id == trip.physical_vehicle_id for other in certificate.trips
        )
        for trip in certificate.trips
    }
    first = next(trip for trip in certificate.trips if counts[trip.physical_vehicle_id] == 1)
    tampered = replace(
        certificate,
        trips=tuple(
            replace(trip, physical_vehicle_id=f"{trip.vehicle_type.upper()}_D9_99")
            if trip.route_id == first.route_id
            else trip
            for trip in certificate.trips
        ),
    )

    with pytest.raises(ValueError, match="does not bind"):
        prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0, initial_ev_battery_kwh=0.0, carbon_price=0.0)
        build_certificate_execution_ledger(solution, tampered, bundle.instance, prices)


def test_execution_indexes_are_read_only() -> None:
    solution, certificate, bundle = _formal_114_customer_case()
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0, initial_ev_battery_kwh=0.0, carbon_price=0.0)
    ledger = build_certificate_execution_ledger(solution, certificate, bundle.instance, prices)

    with pytest.raises(TypeError):
        ledger.routes["fake"] = ledger.routes["CV_D0_1#T1"]  # type: ignore[index]
    with pytest.raises(TypeError):
        ledger.assets["fake"] = ledger.assets["CV_D0_1"]  # type: ignore[index]
