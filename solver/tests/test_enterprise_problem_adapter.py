from __future__ import annotations

import sys
from dataclasses import replace
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
from setp_solver.algorithms.problem_hgs.evaluation import (  # noqa: E402
    FrozenMappingIdentity,
    mapping_sha256,
)
from setp_solver.algorithms.problem_hgs.fleet_registry import (  # noqa: E402
    register_all_vehicle_slots,
)
from setp_solver.algorithms.problem_hgs.kernel_proposals import (  # noqa: E402
    IndependentKernelDutyRouteProposalEngine,
)
from setp_solver.algorithms.problem_hgs.model import DutyIndividual  # noqa: E402
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
def test_enterprise_slice_preserves_sealed_shared_facts(
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
    sliced = slice_enterprise_problem(
        joint_bundle,
        joint_contract,
        enterprise_id,
    )
    instance = sliced.bundle.instance
    customers = tuple(
        node for node in instance.nodes if node.node_type.lower() == "c"
    )
    joint_stations = {
        node.node_id
        for node in joint_bundle.instance.nodes
        if node.node_type.lower() == "f"
    }
    sliced_stations = {
        node.node_id for node in instance.nodes if node.node_type.lower() == "f"
    }

    assert sliced.enterprise_id == enterprise_id
    assert sliced.depot_id == expected_depot
    assert sliced.seed_input.instance is instance
    assert set(sliced.seed_input.orders_by_customer) == set(sliced.customer_ids)
    assert dict(sliced.seed_input.customer_home_depot) == dict(
        sliced.bundle.customer_home_depot
    )
    assert len(customers) == 25
    assert sum(node.demand for node in customers) == demand_kg
    assert {node.node_id for node in instance.nodes if node.node_type == "d"} == {
        expected_depot
    }
    assert sliced_stations == joint_stations
    assert (instance.num_cv, instance.num_ev) == (num_cv, num_ev)
    assert dict(sliced.bundle.fleet_caps_by_depot[expected_depot]) == {
        "num_cv": num_cv,
        "num_ev": num_ev,
        "total_fleet_cap": num_cv + num_ev,
    }
    assert set(sliced.bundle.charger_scenario_by_node) == {
        expected_depot,
        *joint_stations,
    }
    for charger_id, row in sliced.bundle.charger_scenario_by_node.items():
        assert dict(row) == dict(joint_bundle.charger_scenario_by_node[charger_id])
    assert set(sliced.route_constraints.customer_shift_by_id) == set(
        sliced.customer_ids
    )
    assert set(sliced.route_constraints.customer_volume_m3_by_id) == set(
        sliced.customer_ids
    )
    assert (
        sliced.route_constraints.vehicle_volume_capacity_m3
        == joint_contract.vehicle_volume_capacity_m3
    )
    assert set(sliced.bundle.customer_home_depot.values()) == {expected_depot}
    assert set(sliced.bundle.enterprise_assignment_by_customer.values()) == {
        enterprise_id
    }
    assert len(joint_bundle.enterprise_assignment_by_customer) == 50

    assert instance.road_profiles is not None
    for profile in ("cv", "ev"):
        matrices = instance.road_profiles[profile]
        for matrix in (
            matrices.distance_m,
            matrices.duration_s,
            matrices.sum_v2d_m3_s2,
        ):
            assert len(matrix) == len(instance.nodes)
            assert all(len(row) == len(instance.nodes) for row in matrix)


def test_native_draw_uses_one_owned_stream_without_local_search(
    joint_problem,
) -> None:
    joint_bundle, joint_context = joint_problem
    joint_contract = joint_context.rebuilt_route_constraints
    assert joint_contract is not None
    sliced = slice_enterprise_problem(joint_bundle, joint_contract, "ENT_A")
    reference = register_all_vehicle_slots(
        DutyIndividual(
            duties=(),
            unserved_customers=sliced.customer_ids,
            source=f"native-init-reference/{sliced.source_id}",
        ),
        sliced.bundle,
    )
    neutral = {sliced.depot_id: 1.0}
    context = replace(
        joint_context,
        bundle=sliced.bundle,
        independent_profit=neutral,
        independent_profit_identity=FrozenMappingIdentity(
            source_id=f"enterprise-neutral/{sliced.source_id}",
            value_sha256=mapping_sha256(neutral),
            externally_frozen=False,
        ),
        prior_profit={sliced.depot_id: 0.0},
        rebuilt_route_constraints=sliced.route_constraints,
        fairness_enabled=False,
        theta=0.0,
    )
    engine = IndependentKernelDutyRouteProposalEngine(
        context,
        reference,
        random_seed=1,
    )

    assert engine.native_initialization_statistics == {
        "rng_stream_count": 1,
        "make_random_call_count": 0,
        "greedy_repair_call_count": 0,
        "prepopulation_local_search_call_count": 0,
    }
    move = engine.random_skeleton_move(reference, draw_index=0)
    assert move is not None
    candidate = move.apply(reference)
    assert not candidate.unserved_customers
    assert engine.native_initialization_statistics == {
        "rng_stream_count": 1,
        "make_random_call_count": 1,
        "greedy_repair_call_count": 0,
        "prepopulation_local_search_call_count": 0,
    }

    repair_engine = IndependentKernelDutyRouteProposalEngine(
        context,
        reference,
        random_seed=1,
    )
    repair_move = repair_engine.greedy_repair_skeleton_move(
        reference,
        draw_index=0,
    )
    assert repair_move is not None
    repair_candidate = repair_move.apply(reference)
    assert not repair_candidate.unserved_customers
    assert repair_engine.native_initialization_statistics == {
        "rng_stream_count": 1,
        "make_random_call_count": 1,
        "greedy_repair_call_count": 1,
        "prepopulation_local_search_call_count": 0,
    }
