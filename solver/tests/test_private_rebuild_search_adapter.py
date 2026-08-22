from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_problem_hgs_private_technical import _build_context  # noqa: E402
from setp_solver.algorithms.problem_hgs.evaluation import (  # noqa: E402
    DutyFullEvaluator,
    DutyIncrementalEvaluator,
    _rebuilt_route_constraint_violations,
)
from setp_solver.algorithms.problem_hgs.model import DutyChargingSession  # noqa: E402
from setp_solver.charging_curve import (  # noqa: E402
    M17_22KW_NORMAL_PWL,
    M17_FAST_SHAPE_SCALED_60KW_PWL,
    curve_for_charging_node,
    spec_for_charging_node,
)
from setp_solver.china81 import ENDOGENOUS_FLEET_PARAMETERS  # noqa: E402
from setp_solver.cost import evaluate  # noqa: E402
from setp_solver.private_instance_rebuild_20260811 import (  # noqa: E402
    DEPOT_CHARGING_22KW,
    load_private_instance_rebuild,
)
from setp_solver.solution import Route, Solution  # noqa: E402


INSTANCE_ID = "cn-prd-50c-01-V3-TWO-SHIFT-GZ-FS"
DEPOTSWAP_INSTANCE_ID = "cn-jjj-50c-01-V3-TWO-SHIFT-DEPOTSWAP"


@pytest.fixture(scope="module")
def rebuilt_context():
    repo = Path(__file__).parents[2]
    return _build_context(
        repo,
        INSTANCE_ID,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
    )






def test_rebuilt_depot_charging_defaults_to_registered_60kw_and_keeps_22kw() -> None:
    repo = Path(__file__).parents[2]
    default_bundle = load_private_instance_rebuild(repo)
    legacy_scenario_bundle = load_private_instance_rebuild(
        repo,
        depot_charging_scenario=DEPOT_CHARGING_22KW,
    )

    assert default_bundle.prices.depot_charge_power_kw == pytest.approx(60.0)
    assert default_bundle.prices.depot_charging_curve_id == (
        M17_FAST_SHAPE_SCALED_60KW_PWL.curve_id
    )
    default_ev = default_bundle.instance.vehicle_parameters["ev"]
    assert default_ev.non_energy_distance_cost_per_km == pytest.approx(0.9145)
    assert default_ev.source_ids.count(
        "BATTERY_DEPRECIATION_CHANGJIANG_2024_GOEKE_SCHNEIDER_2015"
    ) == 1
    assert {
        node.charge_power_kw
        for node in default_bundle.instance.nodes
        if node.node_type.lower() == "d"
    } == {60.0}
    assert legacy_scenario_bundle.prices.depot_charge_power_kw == pytest.approx(
        22.0
    )
    assert legacy_scenario_bundle.prices.depot_charging_curve_id == (
        M17_22KW_NORMAL_PWL.curve_id
    )




