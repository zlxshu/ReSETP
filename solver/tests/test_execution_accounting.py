from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from setp_solver.cost import evaluate
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import UK_2025_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.certificate_execution import (
    COMPLETED,
    NodeExecution,
    TripExecution,
    build_certificate_execution_ledger,
)
from setp_solver.search.execution_accounting import ExecutionAccountingLedger
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
        physical_vehicle_id=physical_id,
        trip_index=int(trip_text),
        vehicle_type=route.vehicle_type,
        home_depot_id=route.home_depot_id,
        departure_second=departure,
        return_second=returned,
        drive_energy_kwh=0.0,
        nodes=tuple(
            NodeExecution(
                position=index,
                node_id=node_id,
                arrival_second=departure if index == 0 else returned,
                service_start_second=departure if index == 0 else returned,
                departure_second=departure if index == 0 else returned,
            )
            for index, node_id in enumerate(route.node_sequence)
        ),
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


def test_route_or_customer_revenue_rebooking_is_a_hard_error() -> None:
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

    changed_nodes = list(first_execution.nodes)
    changed_nodes[1] = replace(changed_nodes[1], node_id="C2")
    with pytest.raises(ValueError, match="whole-route node sequence"):
        ledger.register_trip(
            replace(first_execution, nodes=tuple(changed_nodes)),
            at_second=100.0,
        )
    with pytest.raises(ValueError, match="changed execution data"):
        ledger.register_trip(
            replace(first_execution, return_second=101.0),
            at_second=101.0,
        )
    with pytest.raises(ValueError, match="duplicate customer revenue claim"):
        ledger.register_trip(_execution(second), at_second=100.0)
