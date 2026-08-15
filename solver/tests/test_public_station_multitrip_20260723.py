from __future__ import annotations

from dataclasses import replace

import pytest

from setp_solver.charging_curve import NL90_MILD
from setp_solver.check import check_solution
from setp_solver.cost import _arc_loads, ev_instance_arc_energy_kwh
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters, UK_2025_PRICES
from setp_solver.search.certificate_execution import (
    build_certificate_execution_ledger,
)
from setp_solver.search.e3_multitrip_runtime import (
    hard_violations,
    prepare_and_score_reference,
)
from setp_solver.search.evaluation import BIG_M, EvaluationContext
from setp_solver.search.multitrip_schedule import (
    prepare_multitrip_solution,
)
from setp_solver.solution import ChargingAction, Route, Solution


def _public_charge_case() -> tuple[Solution, Instance, PriceParameters]:
    nodes = [
        Node(
            "D0",
            "d",
            0.0,
            0.0,
            ready_time=0.0,
            due_time=100_000.0,
            charge_power_kw=22.0,
            station_chargers=2,
        ),
        Node(
            "F1",
            "f",
            1.0,
            0.0,
            ready_time=0.0,
            due_time=100_000.0,
            charge_power_kw=60.0,
            station_chargers=1,
        ),
        Node(
            "C1",
            "c",
            2.0,
            0.0,
            demand=100.0,
            ready_time=0.0,
            due_time=100_000.0,
            service_time=120.0,
        ),
    ]
    distance = 10_000.0
    matrix = [
        [
            0.0 if left == right else distance
            for right in range(len(nodes))
        ]
        for left in range(len(nodes))
    ]
    instance = Instance(nodes, matrix, num_cv=1, num_ev=1)
    route = Route(
        "EV_A",
        "ev",
        "D0",
        ["D0", "F1", "C1", "D0"],
    )
    probe = replace(
        UK_2025_PRICES,
        charging_curve_id=NL90_MILD.curve_id,
        charging_soc_breakpoints=NL90_MILD.soc_breakpoints,
        charging_relative_powers=NL90_MILD.relative_powers,
    )
    node_lookup = {node.node_id: node for node in nodes}
    loads = _arc_loads(route.node_sequence, node_lookup)
    arc_energy = [
        ev_instance_arc_energy_kwh(
            instance,
            from_id,
            to_id,
            loads[index],
            probe,
        )
        for index, (from_id, to_id) in enumerate(
            zip(route.node_sequence, route.node_sequence[1:])
        )
    ]
    station_start_energy = 0.25
    departure_energy = arc_energy[0] + station_start_energy
    station_energy = arc_energy[1] + arc_energy[2]
    station_end_energy = station_start_energy + station_energy
    capacity = max(departure_energy, station_end_energy) + 0.5
    assert capacity < sum(arc_energy)
    prices = replace(
        probe,
        B_battery_kwh=capacity,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=22.0,
    )
    station_curve = NL90_MILD.scale(
        capacity_kwh=capacity,
        reference_power_kw=60.0,
    )
    occupancy = (
        station_curve.duration_seconds(
            station_start_energy,
            station_end_energy,
        )
        / 60.0
    )
    travel_to_station = distance / prices.v_speed_ms
    action = ChargingAction(
        vehicle_id=route.vehicle_id,
        station_id="F1",
        energy_kwh=station_energy,
        occupancy_minutes=occupancy,
        charge_start_second=travel_to_station + 300.0,
        charge_day_offset=0,
        start_energy_kwh=station_start_energy,
        end_energy_kwh=station_end_energy,
        charging_curve_id=NL90_MILD.curve_id,
    )
    return Solution(routes=[route], charging_actions=[action]), instance, prices


def test_public_station_route_closes_strict_clock_soc_and_certificate() -> None:
    source, instance, prices = _public_charge_case()

    prepared, certificate = prepare_multitrip_solution(
        source,
        instance,
        prices,
    )
    public_actions = [
        action
        for action in prepared.charging_actions
        if action.station_id == "F1"
    ]
    assert len(public_actions) == 1
    assert certificate.trips[0].in_route_charge_energy_kwh == pytest.approx(
        public_actions[0].energy_kwh
    )
    assert certificate.trips[0].fixed_departure_battery_kwh == pytest.approx(
        public_actions[0].start_energy_kwh
        + ev_instance_arc_energy_kwh(
            instance,
            "D0",
            "F1",
            _arc_loads(
                source.routes[0].node_sequence,
                {node.node_id: node for node in instance.nodes},
            )[0],
            prices,
        )
    )
    assert check_solution(prepared, instance, prices) == []
    ledger = build_certificate_execution_ledger(
        prepared,
        certificate,
        instance,
        prices,
    )
    assert ledger.routes[certificate.trips[0].route_id].return_second == (
        pytest.approx(certificate.trips[0].return_second)
    )


def test_public_station_route_passes_mandatory_strict_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, instance, prices = _public_charge_case()
    profile = [
        {
            "slot_index": slot,
            "horizon_second_start": slot * 1800.0,
            "actual_gco2_per_kwh": 100.0,
        }
        for slot in range(48)
    ]
    context = EvaluationContext(instance, profile, prices=prices)
    monkeypatch.setenv("SETP_E3_STRICT_MULTITRIP", "1")

    prepared, objective = prepare_and_score_reference(source, context)

    assert objective < BIG_M
    assert hard_violations(prepared, context) == []
    assert context.score_breakdowns[id(prepared)][
        "strict_multitrip_ledger"
    ] is True


def test_public_station_certificate_rejects_missing_or_shifted_soc() -> None:
    source, instance, prices = _public_charge_case()
    prepared, certificate = prepare_multitrip_solution(
        source,
        instance,
        prices,
    )
    public = next(
        action
        for action in prepared.charging_actions
        if action.station_id == "F1"
    )
    without_public = replace(
        prepared,
        charging_actions=[
            action
            for action in prepared.charging_actions
            if action.station_id != "F1"
        ],
    )
    with pytest.raises(
        ValueError,
        match="replay returns|public-charge energy disagrees",
    ):
        build_certificate_execution_ledger(
            without_public,
            certificate,
            instance,
            prices,
        )

    shifted = replace(
        prepared,
        charging_actions=[
            (
                replace(
                    action,
                    start_energy_kwh=float(action.start_energy_kwh) + 0.1,
                    end_energy_kwh=float(action.end_energy_kwh) + 0.1,
                )
                if action == public
                else action
            )
            for action in prepared.charging_actions
        ],
    )
    with pytest.raises(
        ValueError,
        match="SOC|occupancy disagrees with the charging curve",
    ):
        build_certificate_execution_ledger(
            shifted,
            certificate,
            instance,
            prices,
        )
