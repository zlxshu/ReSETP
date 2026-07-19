from __future__ import annotations

from dataclasses import asdict, replace

import pytest

from setp_solver.charging_curve import L100_CONTROL, NL90_MILD
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.search.multitrip_schedule import (
    CONTRACT_ID,
    NONLINEAR_CONTRACT_ID,
    build_multitrip_certificate,
    multitrip_certificate_from_dict,
    prepare_multitrip_solution,
    route_timing,
    validate_multitrip_certificate,
)
from setp_solver.solution import Route, Solution


def _two_trip_instance(*, second_ready: float = 6_000.0) -> Instance:
    nodes = [
        Node("D0", "d", 0, 0, due_time=100_000),
        Node(
            "C1",
            "c",
            0,
            0,
            demand=10,
            ready_time=1_000,
            due_time=4_000,
            service_time=100,
        ),
        Node(
            "C2",
            "c",
            0,
            0,
            demand=10,
            ready_time=second_ready,
            due_time=second_ready + 3_000,
            service_time=100,
        ),
    ]
    matrix = [
        [0.0 if left == right else 1_000.0 for right in range(len(nodes))]
        for left in range(len(nodes))
    ]
    return Instance(nodes, matrix, num_cv=2, num_ev=2)


def _routes() -> list[Route]:
    return [
        Route("EV_A", "ev", "D0", ["D0", "C1", "D0"]),
        Route("EV_B", "ev", "D0", ["D0", "C2", "D0"]),
    ]


def _prices(spec, *, capacity_kwh: float) -> PriceParameters:
    return PriceParameters(
        B_battery_kwh=capacity_kwh,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=22.0,
        charging_curve_id=spec.curve_id,
        charging_soc_breakpoints=spec.soc_breakpoints,
        charging_relative_powers=spec.relative_powers,
    )


def test_nonlinear_short_gap_can_require_an_extra_physical_vehicle() -> None:
    instance = _two_trip_instance(second_ready=1_373.0)
    routes = _routes()
    probe = PriceParameters(B_battery_kwh=280.0)
    drive = route_timing(routes[0], instance, probe).drive_energy_kwh
    capacity = drive * 1.05

    linear = build_multitrip_certificate(
        routes,
        instance,
        _prices(L100_CONTROL, capacity_kwh=capacity),
    )
    nonlinear = build_multitrip_certificate(
        routes,
        instance,
        _prices(NL90_MILD, capacity_kwh=capacity),
    )

    assert linear.vehicle_counts["ev"] == 1
    assert nonlinear.vehicle_counts["ev"] == 2
    assert linear.contract_id == CONTRACT_ID
    assert nonlinear.contract_id == NONLINEAR_CONTRACT_ID


def test_nonlinear_certificate_and_actions_freeze_curve_and_energy_states() -> None:
    instance = _two_trip_instance()
    routes = _routes()
    probe = PriceParameters(B_battery_kwh=280.0)
    drive = route_timing(routes[0], instance, probe).drive_energy_kwh
    prices = _prices(NL90_MILD, capacity_kwh=drive * 1.05)

    prepared, certificate = prepare_multitrip_solution(
        Solution(routes=routes),
        instance,
        prices,
    )

    assert certificate.contract_id == NONLINEAR_CONTRACT_ID
    assert certificate.charging_curve_id == NL90_MILD.curve_id
    assert (
        certificate.charging_curve_parameter_sha256
        == NL90_MILD.parameter_sha256
    )
    assert prepared.charging_actions
    for action in prepared.charging_actions:
        assert action.charging_curve_id == NL90_MILD.curve_id
        assert action.start_energy_kwh is not None
        assert action.end_energy_kwh is not None
        assert action.end_energy_kwh - action.start_energy_kwh == pytest.approx(
            action.energy_kwh
        )
        curve = NL90_MILD.scale(
            capacity_kwh=prices.B_battery_kwh,
            reference_power_kw=prices.depot_charge_power_kw,
        )
        assert action.occupancy_minutes * 60.0 == pytest.approx(
            curve.duration_seconds(
                action.start_energy_kwh,
                action.end_energy_kwh,
            )
        )
    assert multitrip_certificate_from_dict(
        certificate.as_dict()
    ) == certificate

    repeated, repeated_certificate = prepare_multitrip_solution(
        prepared,
        instance,
        prices,
    )
    assert repeated == prepared
    assert repeated_certificate == certificate


def test_nonlinear_certificate_rejects_tampered_curve_identity() -> None:
    instance = _two_trip_instance()
    routes = _routes()
    probe = PriceParameters(B_battery_kwh=280.0)
    drive = route_timing(routes[0], instance, probe).drive_energy_kwh
    prices = _prices(NL90_MILD, capacity_kwh=drive * 1.05)
    certificate = build_multitrip_certificate(routes, instance, prices)

    with pytest.raises(ValueError, match="curve id disagrees"):
        validate_multitrip_certificate(
            replace(certificate, charging_curve_id=L100_CONTROL.curve_id),
            routes,
            prices,
        )
    with pytest.raises(ValueError, match="curve hash disagrees"):
        validate_multitrip_certificate(
            replace(certificate, charging_curve_parameter_sha256="0" * 64),
            routes,
            prices,
        )


def test_nonlinear_prepared_solution_rejects_missing_action_metadata() -> None:
    instance = _two_trip_instance()
    routes = _routes()
    probe = PriceParameters(B_battery_kwh=280.0)
    drive = route_timing(routes[0], instance, probe).drive_energy_kwh
    prices = _prices(NL90_MILD, capacity_kwh=drive * 1.05)
    prepared, _ = prepare_multitrip_solution(
        Solution(routes=routes),
        instance,
        prices,
    )
    first = prepared.charging_actions[0]
    tampered = replace(
        prepared,
        charging_actions=[
            replace(
                first,
                start_energy_kwh=None,
                end_energy_kwh=None,
                charging_curve_id=None,
            ),
            *prepared.charging_actions[1:],
        ],
    )

    with pytest.raises(ValueError, match="incomplete curve metadata"):
        prepare_multitrip_solution(tampered, instance, prices)


def test_new_parameter_mapping_cannot_omit_curve_fields() -> None:
    prices = asdict(PriceParameters())
    del prices["charging_curve_id"]

    with pytest.raises(ValueError, match="missing explicit fields"):
        build_multitrip_certificate(_routes(), _two_trip_instance(), prices)
