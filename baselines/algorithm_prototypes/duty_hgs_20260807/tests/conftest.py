"""v1 2026-08-07: shared real-input technical fixture for Duty-HGS tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from duty_hgs.evaluation import (
    DutyEvaluationContext,
    DutyFullEvaluator,
    FrozenMappingIdentity,
    mapping_sha256,
)
from duty_hgs.model import DutyIndividual, DutyTrip, PhysicalVehicleDuty
from run_real_input_technical_trial import _build_context
from setp_solver.china81 import China81Bundle
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.profit import calculate_depot_profits
from setp_solver.search.multitrip_schedule import DEFAULT_DEPOT_CHARGE_WINDOW_MODE

REPO = Path(__file__).resolve().parents[4]
INSTANCE_ID = "cn-jjj-10c-01-V2-LOCATIONS"


@pytest.fixture(scope="session")
def evaluated_fixture():
    _bundle, individual, _pi0, context = _build_context(REPO, INSTANCE_ID)
    return individual, DutyFullEvaluator(context)


@pytest.fixture(scope="session")
def feedback_fixture():
    nodes = [
        Node("D0", "d", 0.0, 0.0, due_time=100_000.0),
        Node(
            "C1",
            "c",
            1.0,
            0.0,
            demand=6.0,
            ready_time=0.0,
            due_time=100_000.0,
        ),
        Node(
            "C2",
            "c",
            2.0,
            0.0,
            demand=6.0,
            ready_time=0.0,
            due_time=100_000.0,
        ),
        Node(
            "C3",
            "c",
            3.0,
            0.0,
            demand=1.0,
            ready_time=0.0,
            due_time=100_000.0,
        ),
    ]
    matrix = [
        [0.0 if left == right else 1_000.0 for right in range(len(nodes))]
        for left in range(len(nodes))
    ]
    instance = Instance(nodes, matrix, num_cv=2, num_ev=0)
    prices = PriceParameters(
        Q_capacity=10.0,
        revenue_per_kg=100.0,
        carbon_price=0.0,
        fairness_theta=1.0,
    )
    bundle = China81Bundle(
        instance_id="technical-capacity-fixture",
        region="technical",
        date="2025-02-12",
        instance=instance,
        time_profile=[],
        prices=prices,
        source_paths={},
        customer_home_depot={"C1": "D0", "C2": "D0", "C3": "D0"},
        price_area_by_city={},
        carbon_source_column_by_city={},
        diesel_zone_by_city={},
        diesel_price_by_city={},
        fleet_caps_by_depot={
            "D0": {"num_cv": 2, "num_ev": 0, "total_fleet_cap": 2}
        },
        charger_scenario_by_node={},
        fleet_cap_semantics="technical-fixture",
        diesel_price_source_id="technical-fixture",
        static_input_authority="technical-fixture",
        road_matrix_authority="technical-fixture",
        runtime_parameter_authority="technical-fixture",
        fleet_authority="technical-fixture",
        model_config={},
        formal_search_allowed=False,
    )
    individual = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "CV_D0_1",
                "cv",
                "D0",
                (DutyTrip(1, ("C1", "C2")),),
            ),
            PhysicalVehicleDuty(
                "CV_D0_2",
                "cv",
                "D0",
                (DutyTrip(1, ("C3",)),),
            ),
        ),
        source="technical-capacity-fixture",
    )
    prepared = individual.to_solution()
    profits = calculate_depot_profits(
        prepared,
        instance,
        [],
        prices,
        customer_home_depot=dict(bundle.customer_home_depot),
    )
    independent_profit = {"D0": profits["D0"].profit}
    assert independent_profit["D0"] > 0.0
    context = DutyEvaluationContext(
        bundle=bundle,
        independent_profit=independent_profit,
        independent_profit_identity=FrozenMappingIdentity(
            source_id="technical-capacity-fixture",
            value_sha256=mapping_sha256(independent_profit),
            externally_frozen=False,
        ),
        prior_profit={"D0": 0.0},
        theta=1.0,
        carbon_quota_kg=0.0,
        depot_charge_window_mode=DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
    )
    return individual, DutyFullEvaluator(context)


@pytest.fixture(scope="session")
def multi_step_infeasible_fixture():
    """One local move can reduce overload without restoring feasibility."""

    nodes = [
        Node("D0", "d", 0.0, 0.0, due_time=100_000.0),
        Node("C1", "c", 1.0, 0.0, demand=6.0, due_time=100_000.0),
        Node("C2", "c", 2.0, 0.0, demand=6.0, due_time=100_000.0),
        Node("C3", "c", 3.0, 0.0, demand=6.0, due_time=100_000.0),
        Node("C4", "c", 4.0, 0.0, demand=6.0, due_time=100_000.0),
    ]
    matrix = [
        [0.0 if left == right else 1_000.0 for right in range(len(nodes))]
        for left in range(len(nodes))
    ]
    instance = Instance(nodes, matrix, num_cv=2, num_ev=0)
    prices = PriceParameters(
        Q_capacity=10.0,
        revenue_per_kg=100.0,
        carbon_price=0.0,
        fairness_theta=0.0,
    )
    bundle = China81Bundle(
        instance_id="technical-multistep-infeasible-fixture",
        region="technical",
        date="2025-02-12",
        instance=instance,
        time_profile=[],
        prices=prices,
        source_paths={},
        customer_home_depot={customer: "D0" for customer in ("C1", "C2", "C3", "C4")},
        price_area_by_city={},
        carbon_source_column_by_city={},
        diesel_zone_by_city={},
        diesel_price_by_city={},
        fleet_caps_by_depot={
            "D0": {"num_cv": 2, "num_ev": 0, "total_fleet_cap": 2}
        },
        charger_scenario_by_node={},
        fleet_cap_semantics="technical-fixture",
        diesel_price_source_id="technical-fixture",
        static_input_authority="technical-fixture",
        road_matrix_authority="technical-fixture",
        runtime_parameter_authority="technical-fixture",
        fleet_authority="technical-fixture",
        model_config={},
        formal_search_allowed=False,
    )
    individual = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "CV_D0_1",
                "cv",
                "D0",
                (DutyTrip(1, ("C1", "C2", "C3")),),
            ),
            PhysicalVehicleDuty(
                "CV_D0_2",
                "cv",
                "D0",
                (DutyTrip(1, ("C4",)),),
            ),
        ),
        source="technical-multistep-infeasible-fixture",
    )
    independent_profit = {"D0": 1.0}
    context = DutyEvaluationContext(
        bundle=bundle,
        independent_profit=independent_profit,
        independent_profit_identity=FrozenMappingIdentity(
            source_id="technical-multistep-infeasible-fixture",
            value_sha256=mapping_sha256(independent_profit),
            externally_frozen=False,
        ),
        prior_profit={"D0": 0.0},
        theta=0.0,
        carbon_quota_kg=0.0,
        depot_charge_window_mode=DEFAULT_DEPOT_CHARGE_WINDOW_MODE,
    )
    return individual, DutyFullEvaluator(context)
