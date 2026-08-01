from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


REPO = Path(__file__).resolve().parents[4]
PROTOTYPE = (
    REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
)
for entry in (REPO, REPO / "solver/src", PROTOTYPE):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from setp_solver.algorithms.resetp_alns.support import charging
from setp_solver.algorithms.resetp_alns.support.carbon_charging import (
    ChargeOption,
    score_charge_option,
)
from setp_solver.charging_curve import L100_CONTROL
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import complete_china81_route_skeleton
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.solution import Route, Solution

from baselines.china_e3_e7.e5_enroute_nonlinear_20260801 import (
    b2_low_cost_hook,
)
from baselines.china_e3_e7.e5_enroute_nonlinear_20260801.b2_low_cost_hook import (
    B2_CHARGE_AMOUNT_STRATEGIES,
    b2_completion_hook,
)
from baselines.china_e3_e7.e5_enroute_nonlinear_20260801.run_b2_low_cost import (
    run_b2_low_cost,
)
from baselines.china_e3_e7.e5_enroute_nonlinear_20260801.runtime_overlay import (
    M17_22KW_NORMAL_PWL,
    apply_b2_sensitivity_foundation,
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
                str(row["vehicle_id"]),
                str(row["vehicle_type"]),
                str(row["home_depot_id"]),
                [str(value) for value in row["node_sequence"]],
            )
            for row in payload["routes"]
        ]
    )


def test_default_completion_matches_frozen_pre_b2_result() -> None:
    bundle = apply_b2_sensitivity_foundation(
        load_china81_bundle(REPO, INSTANCE_ID),
        curve_id=M17_22KW_NORMAL_PWL.curve_id,
    )
    default = complete_china81_route_skeleton(_initial_solution(), bundle)
    explicit = complete_china81_route_skeleton(
        _initial_solution(),
        bundle,
        charge_amount_strategies=("just_enough",),
    )
    assert default.objective == explicit.objective
    assert default.breakdown == explicit.breakdown
    assert default.solution == explicit.solution
    assert default.objective == pytest.approx(3474.8171197061083)
    actions = default.solution.charging_actions
    assert [(item.vehicle_id, item.station_id) for item in actions] == [
        ("CH81-0002", "D_guangzhou"),
        ("CH81-0008", "D_shenzhen"),
        ("CH81-0007", "D_shenzhen"),
    ]
    assert [item.energy_kwh for item in actions] == pytest.approx(
        [37.28744531944286, 24.95925468822896, 23.112508451358252]
    )


def test_max_coverage_removes_a_later_public_stop(monkeypatch) -> None:
    nodes = [
        Node("D", "d", 0, 0, due_time=86_400),
        Node("C1", "c", 1, 0, ready_time=10_000, due_time=80_000),
        Node("C2", "c", 2, 0, due_time=80_000),
        Node("S1", "f", 0.5, 0, due_time=80_000, charge_power_kw=10),
        Node("S2", "f", 2.5, 0, due_time=80_000, charge_power_kw=10),
    ]
    instance = Instance(
        nodes,
        [[0 if left == right else 25 for right in range(5)] for left in range(5)],
    )
    energy = {
        ("D", "C1"): 6,
        ("C1", "C2"): 5,
        ("C2", "D"): 2,
        ("D", "S1"): 4,
        ("S1", "C1"): 3,
        ("D", "S2"): 20,
        ("S2", "C1"): 20,
        ("C2", "S1"): 20,
        ("C2", "S2"): 0,
        ("S2", "D"): 2,
    }
    monkeypatch.setattr(
        charging,
        "_ev_energy",
        lambda _instance, left, right, _load, _prices: float(
            energy.get((left, right), 20)
        ),
    )
    profile = [
        {
            "horizon_second_start": slot * 1800,
            "actual_gco2_per_kwh": 100.0,
            "forecast_gco2_per_kwh": 100.0,
        }
        for slot in range(48)
    ]
    prices = replace(
        DEFAULT_PRICES,
        B_battery_kwh=10.0,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=10.0,
    )
    route = Route("EV", "ev", "D", ["D", "C1", "C2", "D"])
    enough, enough_actions = charging.repair_route_charging(
        route,
        instance,
        profile,
        prices,
        depot_charge_window_mode="same_day_predeparture",
        charge_amount_strategy="just_enough",
    )
    coverage, coverage_actions = charging.repair_route_charging(
        route,
        instance,
        profile,
        prices,
        depot_charge_window_mode="same_day_predeparture",
        charge_amount_strategy="max_coverage",
    )
    assert enough.node_sequence == ["D", "S1", "C1", "C2", "S2", "D"]
    assert coverage.node_sequence == ["D", "S1", "C1", "C2", "D"]
    assert len(enough_actions) == 3
    assert len(coverage_actions) == 2


def test_both_curves_receive_the_same_five_candidates() -> None:
    base = load_china81_bundle(REPO, INSTANCE_ID)
    observed = []
    for curve_id in (
        L100_CONTROL.curve_id,
        M17_22KW_NORMAL_PWL.curve_id,
    ):
        bundle = apply_b2_sensitivity_foundation(base, curve_id=curve_id)
        result = complete_china81_route_skeleton(
            _initial_solution(),
            bundle,
            charge_amount_strategies=B2_CHARGE_AMOUNT_STRATEGIES,
        )
        observed.append(result.activity["charge_amount_strategies"])
    assert observed == [
        list(B2_CHARGE_AMOUNT_STRATEGIES),
        list(B2_CHARGE_AMOUNT_STRATEGIES),
    ]


def test_p1_counts_public_time_but_not_depot_precharge_time() -> None:
    bundle = load_china81_bundle(REPO, INSTANCE_ID)
    station = next(node for node in bundle.instance.nodes if node.node_type == "f")
    depot = next(node for node in bundle.instance.nodes if node.node_type == "d")
    zero_prices = replace(
        bundle.prices,
        charging_curve_id=L100_CONTROL.curve_id,
        charging_soc_breakpoints=L100_CONTROL.soc_breakpoints,
        charging_relative_powers=L100_CONTROL.relative_powers,
    )
    prices = replace(zero_prices, route_time_cost_per_hour=75.0)
    common = dict(
        earliest_start_second=0.0,
        latest_start_second=0.0,
        energy_kwh=1.0,
        power_kw=22.0,
        occupancy_seconds_override=3600.0,
        detour_seconds=600.0,
    )
    public = score_charge_option(
        ChargeOption(station_id=station.node_id, node_type="f", **common),
        bundle.instance,
        bundle.time_profile,
        prices,
        carbon_weight=0.0,
    )
    depot_score = score_charge_option(
        ChargeOption(station_id=depot.node_id, node_type="d", **common),
        bundle.instance,
        bundle.time_profile,
        prices,
        carbon_weight=0.0,
    )
    assert public.time_cost == pytest.approx(87.5)
    assert depot_score.time_cost == 0.0
    assert score_charge_option(
        ChargeOption(station_id=station.node_id, node_type="f", **common),
        bundle.instance,
        bundle.time_profile,
        zero_prices,
        carbon_weight=0.0,
    ).time_cost == 0.0


def test_hook_restores_all_three_completion_bindings(monkeypatch) -> None:
    sentinels = {
        name: SimpleNamespace(complete_china81_route_skeleton=object())
        for name in ("pyvrp_adapter", "epochal_hgs", "route_pool_sp")
    }
    originals = {
        name: module.complete_china81_route_skeleton
        for name, module in sentinels.items()
    }
    monkeypatch.setattr(
        b2_low_cost_hook,
        "import_module",
        lambda name: sentinels[name],
    )
    with b2_completion_hook() as hooked:
        assert all(
            module.complete_china81_route_skeleton is hooked
            for module in sentinels.values()
        )
    assert all(
        sentinels[name].complete_china81_route_skeleton is original
        for name, original in originals.items()
    )


def test_runner_refuses_to_overwrite_existing_output(tmp_path) -> None:
    with pytest.raises(FileExistsError):
        run_b2_low_cost(tmp_path)
