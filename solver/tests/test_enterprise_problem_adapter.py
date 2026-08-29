from __future__ import annotations

import sys
from pathlib import Path

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


def _joint_problem():
    bundle, _initial, _pi0, context = _build_context(
        REPO,
        DEPOT_SEARCH_INSTANCE_ID,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
        depot_charging_scenario_name="60kw",
    )
    assert context.rebuilt_route_constraints is not None
    return bundle, context


def test_single_enterprise_keeps_own_resources_and_serves_full_market() -> None:
    joint_bundle, joint_context = _joint_problem()
    joint_contract = joint_context.rebuilt_route_constraints
    assert joint_contract is not None
    assert dict(joint_bundle.customer_home_depot) == {}
    for enterprise_id, expected_depot, num_cv, num_ev in (
        ("ENT_A", "D_OSM_WAY_1003511503", 3, 3),
        ("ENT_B", "D_OSM_WAY_1071205721", 7, 7),
    ):
        sliced = slice_enterprise_problem(
            joint_bundle,
            joint_contract,
            enterprise_id,
        )
        customers = tuple(
            node
            for node in sliced.bundle.instance.nodes
            if node.node_type.lower() == "c"
        )
        assert len(customers) == 50
        assert sum(float(node.demand) for node in customers) == 13264.0
        assert set(sliced.bundle.customer_home_depot.values()) == {expected_depot}
        assert sliced.bundle.instance.num_cv == num_cv
        assert sliced.bundle.instance.num_ev == num_ev
        assert set(sliced.route_constraints.customer_shift_by_id) == {
            node.node_id for node in customers
        }
