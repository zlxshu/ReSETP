from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "solver/scripts"))

from run_problem_hgs_private_technical import (  # noqa: E402
    DEPOT_SEARCH_INSTANCE_ID,
    _build_context,
)
from setp_solver.algorithms.problem_hgs.enterprise_adapter import (  # noqa: E402
    slice_enterprise_problem,
)
from setp_solver.china81 import ENDOGENOUS_FLEET_PARAMETERS  # noqa: E402


@pytest.fixture(scope="module")
def joint_problem():
    bundle, _initial, _pi0, context = _build_context(
        REPO,
        DEPOT_SEARCH_INSTANCE_ID,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
        depot_charging_scenario_name="60kw",
    )
    assert context.rebuilt_route_constraints is not None
    return bundle, context


@pytest.mark.parametrize(
    ("enterprise_id", "expected_depot", "num_cv", "num_ev", "demand_kg"),
    (
        ("ENT_A", "D_OSM_WAY_1003511503", 3, 3, 6597.0),
        ("ENT_B", "D_OSM_WAY_1071205721", 7, 7, 6667.0),
    ),
)
def test_joint_problem_has_no_customer_enterprise_preassignment(
    joint_problem,
    enterprise_id: str,
    expected_depot: str,
    num_cv: int,
    num_ev: int,
    demand_kg: float,
) -> None:
    joint_bundle, joint_context = joint_problem
    joint_contract = joint_context.rebuilt_route_constraints
    assert joint_contract is not None
    _ = expected_depot, num_cv, num_ev, demand_kg

    assert dict(joint_bundle.customer_home_depot) == {}
    assert dict(joint_bundle.enterprise_assignment_by_customer) == {}
    with pytest.raises(ValueError, match="enterprise assignment is unavailable"):
        slice_enterprise_problem(
            joint_bundle,
            joint_contract,
            enterprise_id,
        )
