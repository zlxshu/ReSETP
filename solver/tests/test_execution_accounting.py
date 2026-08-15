from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from setp_solver.cost import evaluate
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import UK_2025_PRICES
from setp_solver.profit import calculate_depot_profits, infer_customer_home_depots
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.certificate_execution import (
    COMPLETED,
    TripExecution,
    build_certificate_execution_ledger,
)
from setp_solver.search.execution_accounting import (
    ExecutionAccountingLedger,
    whole_route_signature,
)
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.search.multitrip_schedule import MultiTripCertificate, ScheduledTrip
from setp_solver.solution import Route, Solution


ROOT = Path(__file__).resolve().parents[2]
E3 = ROOT / "baselines/e3_ablation/e3_paired_cost_formal_v2_20260713"
E6 = ROOT / "baselines/e6_fairness/e6_participation_formal_20260714"
CASE = "L-main-threeshift-50c-01__geographic__seed1__no_loss"


def _small_instance() -> Instance:
    nodes = [
        Node("D0", "d", 0.0, 0.0, due_time=100_000.0),
        Node("C1", "c", 1.0, 0.0, demand=100.0, due_time=100_000.0),
        Node("C2", "c", 2.0, 0.0, demand=200.0, due_time=100_000.0),
    ]
    # D0--C1--C2 are collinear.  The true trip is 4 km; closing each
    # customer back to D0 separately invents 2 km and another dispatch.
    matrix = [
        [0.0, 1_000.0, 2_000.0],
        [1_000.0, 0.0, 1_000.0],
        [2_000.0, 1_000.0, 0.0],
    ]
    return Instance(nodes=nodes, distance_matrix=matrix, num_cv=2, num_ev=0)


def _execution(route: Route, *, departure: float = 0.0, returned: float = 100.0) -> TripExecution:
    physical_id, trip_text = route.vehicle_id.split("#T", 1)
    return TripExecution(
        route_id=route.vehicle_id,
        route_signature=whole_route_signature(route),
        physical_vehicle_id=physical_id,
        trip_index=int(trip_text),
        vehicle_type=route.vehicle_type,
        home_depot_id=route.home_depot_id,
        departure_second=departure,
        return_second=returned,
        drive_energy_kwh=0.0,
        nodes=(),
    )


def _formal_114_customer_case():
    solution = solution_from_dict(
        json.loads((E6 / "solutions" / f"{CASE}.json").read_text(encoding="utf-8"))
    )
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
    prices = replace(
        UK_2025_PRICES,
        B_battery_kwh=280.0,
        initial_ev_battery_kwh=0.0,
        cross_site_cost=0.0,
        carbon_price=0.0,
    )
    assert sum(node.node_type.lower() == "c" for node in bundle.instance.nodes) == 114
    return solution, certificate, bundle, prices


def test_whole_trip_accounting_defeats_the_depot_fragment_overcount() -> None:
    instance = _small_instance()
    route = Route("CV_D0_1#T1", "cv", "D0", ["D0", "C1", "C2", "D0"])
    source = Solution(routes=[route])
    execution = _execution(route)
    ledger = ExecutionAccountingLedger(source, instance, [], UK_2025_PRICES)

    assert ledger.register_trip(execution, at_second=50.0) is True
    assert ledger.register_trip(execution, at_second=50.0) is False
    assert ledger.register_trip(execution, at_second=100.0) is False
    summary = ledger.summary()

    expected = evaluate(source, instance, [], UK_2025_PRICES)
    fragments = Solution(
        routes=[
            Route("CV_D0_1#T1", "cv", "D0", ["D0", "C1", "D0"]),
            Route("CV_D0_2#T1", "cv", "D0", ["D0", "C2", "D0"]),
        ]
    )
    old_fragmented = evaluate(fragments, instance, [], UK_2025_PRICES)

    assert summary.booked_route_count == 1
    assert summary.booked_customer_count == 2
    assert summary.trips[route.vehicle_id].execution_state == COMPLETED
    assert summary.system.distance_total == pytest.approx(4_000.0)
    assert summary.system.distance_total == pytest.approx(expected["distance_total"])
    assert summary.system.total_cost == pytest.approx(expected["total_cost"])
    assert summary.system.revenue == pytest.approx(
        (100.0 + 200.0) * UK_2025_PRICES.revenue_per_kg
    )
    assert summary.system.realized_profit == pytest.approx(
        summary.system.revenue - summary.system.total_cost
    )
    assert old_fragmented["distance_total"] == pytest.approx(6_000.0)
    assert old_fragmented["total_cost"] > summary.system.total_cost


def test_signature_or_customer_revenue_rebooking_is_a_hard_error() -> None:
    instance = _small_instance()
    first = Route("CV_D0_1#T1", "cv", "D0", ["D0", "C1", "D0"])
    second = Route("CV_D0_2#T1", "cv", "D0", ["D0", "C1", "C2", "D0"])
    ledger = ExecutionAccountingLedger(
        Solution(routes=[first, second]),
        instance,
        [],
        UK_2025_PRICES,
    )
    first_execution = _execution(first)
    assert ledger.register_trip(first_execution, at_second=100.0) is True

    with pytest.raises(ValueError, match="whole-route signature"):
        ledger.register_trip(
            replace(first_execution, route_signature="0" * 64),
            at_second=100.0,
        )
    with pytest.raises(ValueError, match="changed accounting evidence"):
        ledger.register_trip(
            replace(first_execution, return_second=101.0),
            at_second=101.0,
        )
    with pytest.raises(ValueError, match="duplicate customer revenue claim"):
        ledger.register_trip(_execution(second), at_second=100.0)


def test_real_114_customer_completed_trips_close_cost_emissions_and_depot_profit() -> None:
    solution, certificate, bundle, prices = _formal_114_customer_case()
    clock = build_certificate_execution_ledger(
        solution,
        certificate,
        bundle.instance,
        prices,
    )
    chosen = []
    for depot_id in ("D0", "D1"):
        for vehicle_type in ("cv", "ev"):
            depot_trips = sorted(
                (
                    trip
                    for trip in clock.routes.values()
                    if trip.home_depot_id == depot_id and trip.vehicle_type == vehicle_type
                ),
                key=lambda trip: (trip.return_second, trip.route_id),
            )
            assert depot_trips
            chosen.append(depot_trips[0])
    assert len(chosen) == 4

    ledger = ExecutionAccountingLedger(
        solution,
        bundle.instance,
        bundle.carbon_profile,
        prices,
        carbon_quota_kg=0.0,
    )
    for execution in chosen:
        assert ledger.register_trip(execution, at_second=execution.return_second) is True
        assert ledger.register_trip(execution, at_second=execution.return_second) is False
    summary = ledger.summary()

    chosen_ids = {trip.route_id for trip in chosen}
    chosen_customers = {
        node_id
        for route in solution.routes
        if route.vehicle_id in chosen_ids
        for node_id in route.node_sequence
        if bundle.instance.nodes[bundle.instance.node_index[node_id]].node_type.lower() == "c"
    }
    subset = Solution(
        routes=[route for route in solution.routes if route.vehicle_id in chosen_ids],
        charging_actions=[
            action for action in solution.charging_actions if action.vehicle_id in chosen_ids
        ],
        cross_site_services=[
            service
            for service in solution.cross_site_services
            if service.customer_id in chosen_customers
        ],
    )
    expected = evaluate(
        subset,
        bundle.instance,
        bundle.carbon_profile,
        prices,
        carbon_quota_kg=0.0,
    )
    for field in (
        "cost_fix",
        "cost_km",
        "cost_fuel",
        "cost_elec",
        "cost_occ",
        "cost_transship",
        "cost_carbon",
        "total_cost",
        "distance_total",
        "distance_cv",
        "distance_ev",
        "fuel_liters",
        "electricity_kwh",
        "depot_charging_kwh",
        "station_charging_kwh",
        "ev_drive_kwh",
        "E_total",
        "E_cv_direct",
        "E_ev_indirect",
    ):
        assert getattr(summary.system, field) == pytest.approx(expected[field], abs=1e-6)

    owners = infer_customer_home_depots(bundle.instance)
    expected_profit = calculate_depot_profits(
        subset,
        bundle.instance,
        bundle.carbon_profile,
        prices,
        customer_home_depot=owners,
        carbon_quota_kg=0.0,
    )
    for depot_id, actual in summary.by_depot.items():
        reference = expected_profit[depot_id]
        assert actual.cost_fix == pytest.approx(reference.cost_fixed, abs=1e-6)
        assert actual.cost_km == pytest.approx(reference.cost_km, abs=1e-6)
        assert actual.cost_fuel == pytest.approx(reference.cost_fuel, abs=1e-6)
        assert actual.cost_elec == pytest.approx(reference.cost_electricity, abs=1e-6)
        assert actual.cost_occ == pytest.approx(reference.cost_occupancy, abs=1e-6)
        assert actual.cost_transship == pytest.approx(reference.cost_transship, abs=1e-6)
        assert actual.cost_carbon == pytest.approx(reference.cost_carbon, abs=1e-6)
        assert actual.total_cost == pytest.approx(reference.cost_total, abs=1e-6)
        assert actual.revenue == pytest.approx(reference.revenue, abs=1e-6)
        assert actual.realized_profit == pytest.approx(reference.profit, abs=1e-6)
        assert actual.E_total == pytest.approx(reference.emissions_kg, abs=1e-6)

    assert summary.system.total_cost == pytest.approx(
        sum(row.total_cost for row in summary.by_depot.values()),
        abs=1e-6,
    )
    assert summary.system.realized_profit == pytest.approx(
        sum(row.realized_profit for row in summary.by_depot.values()),
        abs=1e-6,
    )
