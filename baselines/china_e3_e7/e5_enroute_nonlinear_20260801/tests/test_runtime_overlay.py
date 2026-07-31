from __future__ import annotations

from dataclasses import fields, replace
import json
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[4]
for entry in (REPO, REPO / "solver/src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from setp_solver.check import check_solution
from setp_solver.charging_curve import L100_CONTROL, curve_from_parameters
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import complete_china81_route_skeleton
from setp_solver.cost import evaluate
from setp_solver.solution import Route, Solution
from setp_solver.search.charging import _curve_aware_action

from baselines.china_e3_e7.e5_enroute_nonlinear_20260801.runtime_overlay import (
    M17_22KW_NORMAL_PWL,
    apply_runtime_overlay,
)


INSTANCE_ID = "cn-prd-50c-01-V2-LOCATIONS"
FLEET = REPO / "data/ChinaInstances/china81_finite_fleet_authority_v1_20260723"
def _initial_solution() -> Solution:
    payload = json.loads(
        (FLEET / "witnesses" / f"{INSTANCE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    return Solution(
        routes=[
            Route(
                vehicle_id=str(row["vehicle_id"]),
                vehicle_type=str(row["vehicle_type"]),
                home_depot_id=str(row["home_depot_id"]),
                node_sequence=list(row["node_sequence"]),
            )
            for row in payload["routes"]
        ]
    )
def test_overlay_changes_only_approved_runtime_fields() -> None:
    base = load_china81_bundle(REPO, INSTANCE_ID)
    linear = apply_runtime_overlay(
        base,
        capacity_kwh=20.0,
        curve_id=L100_CONTROL.curve_id,
    )
    nonlinear = apply_runtime_overlay(
        base,
        capacity_kwh=20.0,
        curve_id=M17_22KW_NORMAL_PWL.curve_id,
    )

    assert linear.prices.B_battery_kwh == 20.0
    assert linear.prices.initial_ev_battery_kwh == 20.0
    assert linear.instance.vehicle_parameters["ev"].battery_kwh == 20.0
    assert nonlinear.instance.battery_capacity_kwh(
        fallback=nonlinear.prices.B_battery_kwh
    ) == 20.0
    assert linear.prices.charging_soc_breakpoints == (0.0, 1.0)
    assert nonlinear.prices.charging_soc_breakpoints == (0.0, 0.85, 0.95, 1.0)
    assert linear.prices.charging_relative_powers != (
        nonlinear.prices.charging_relative_powers
    )

    allowed = {
        "B_battery_kwh",
        "initial_ev_battery_kwh",
        "charging_curve_id",
        "charging_soc_breakpoints",
        "charging_relative_powers",
    }
    assert {
        item.name
        for item in fields(base.prices)
        if getattr(base.prices, item.name) != getattr(nonlinear.prices, item.name)
    } <= allowed
    assert nonlinear.instance.road_profiles == base.instance.road_profiles
    assert nonlinear.instance.num_cv == base.instance.num_cv
    assert nonlinear.instance.num_ev == base.instance.num_ev
    assert nonlinear.time_profile == base.time_profile
    for original, current in zip(
        base.instance.nodes,
        nonlinear.instance.nodes,
        strict=True,
    ):
        expected = (
            replace(original, charge_power_kw=22.0)
            if original.node_type.lower() == "f"
            else original
        )
        assert current == expected


def test_public_power_reaches_node_and_actual_curve_reference() -> None:
    base = load_china81_bundle(REPO, INSTANCE_ID)
    durations = {}
    for power in (22.0, 60.0):
        bundle = apply_runtime_overlay(
            base,
            capacity_kwh=20.0,
            curve_id=M17_22KW_NORMAL_PWL.curve_id,
            public_charge_power_kw=power,
        )
        station = next(
            node for node in bundle.instance.nodes if node.node_type == "f"
        )
        assert station.charge_power_kw == power
        assert (
            bundle.charger_scenario_by_node[station.node_id][
                "charge_power_kw"
            ]
            == power
        )
        action = _curve_aware_action(
            vehicle_id="TEST_EV",
            station_id=station.node_id,
            start_energy_kwh=10.0,
            energy_kwh=8.0,
            reference_power_kw=float(station.charge_power_kw),
            prices=bundle.prices,
            instance=bundle.instance,
        )
        curve = curve_from_parameters(
            bundle.prices,
            capacity_kwh=20.0,
            reference_power_kw=power,
        )
        assert action.occupancy_minutes * 60.0 == curve.duration_seconds(
            10.0,
            18.0,
        )
        durations[power] = action.occupancy_minutes
    assert durations[22.0] > durations[60.0]


def test_capacity_reaches_repair_checker_and_cost_without_depot_precharge() -> None:
    bundle = apply_runtime_overlay(
        load_china81_bundle(REPO, INSTANCE_ID),
        capacity_kwh=16.0,
        curve_id=M17_22KW_NORMAL_PWL.curve_id,
    )
    completion = complete_china81_route_skeleton(
        _initial_solution(),
        bundle,
    )
    violations = check_solution(
        completion.solution,
        bundle.instance,
        bundle.prices,
    )
    metrics = evaluate(
        completion.solution,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    nodes = {node.node_id: node for node in bundle.instance.nodes}

    assert not violations
    assert metrics["total_cost"] == completion.objective
    assert completion.solution.charging_actions
    assert all(
        nodes[action.station_id].node_type.lower() == "f"
        for action in completion.solution.charging_actions
    )
    assert all(
        action.charging_curve_id == M17_22KW_NORMAL_PWL.curve_id
        and action.start_energy_kwh is not None
        and action.end_energy_kwh is not None
        and 0.0 <= action.start_energy_kwh <= action.end_energy_kwh <= 16.0
        for action in completion.solution.charging_actions
    )
    assert metrics["station_charging_kwh"] > 0.0
    assert metrics["depot_charging_kwh"] == 0.0
