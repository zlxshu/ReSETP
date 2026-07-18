from __future__ import annotations

import math

import pytest

from setp_solver.algorithms.resetp_alns.operators.true_swapstar import (
    TrueSwapStarConfig,
    _ranked_true_swapstar_moves,
    true_swapstar_intensify,
)
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    ROUTE_POOL_RECOMBINATION_FLAG,
    TRUE_SWAPSTAR_FLAG,
    e2_alns_variant_flags,
    structural_component_from_flags,
)
from setp_solver.algorithms.resetp_alns.runtime.budgeted_scoring import (
    score_reference_solution,
)
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import Route, Solution


COORDINATES = {
    "D0": (0.0, 0.0),
    "C1": (-18.0, -15.0),
    "C2": (7.0, 6.0),
    "C3": (-16.0, -5.0),
    "C4": (-15.0, 15.0),
    "C5": (7.0, -17.0),
    "C6": (16.0, -13.0),
}


def _fixture(budget: int) -> tuple[Solution, EvaluationContext]:
    node_ids = list(COORDINATES)
    nodes = [
        Node(
            node_id=node_id,
            node_type="d" if node_id == "D0" else "c",
            x=COORDINATES[node_id][0],
            y=COORDINATES[node_id][1],
            demand=0.0 if node_id == "D0" else 1.0,
            ready_time=0.0,
            due_time=10_000.0,
            service_time=0.0,
        )
        for node_id in node_ids
    ]
    matrix = [
        [
            math.dist(COORDINATES[left], COORDINATES[right])
            for right in node_ids
        ]
        for left in node_ids
    ]
    instance = Instance(
        nodes=nodes,
        distance_matrix=matrix,
        num_cv=2,
        num_ev=0,
    )
    prices = PriceParameters(
        Q_capacity=10.0,
        v_speed_ms=1.0,
        diesel_price=0.0,
        carbon_price=0.0,
        diesel_ef=0.0,
        vehicle_fixed_cost=0.0,
        occupancy_fee=0.0,
        cross_site_cost=0.0,
        revenue_per_kg=0.0,
        c_km=1000.0,
    )
    solution = Solution(
        routes=[
            Route(
                vehicle_id="CV1",
                vehicle_type="cv",
                home_depot_id="D0",
                node_sequence=["D0", "C1", "C2", "C3", "D0"],
            ),
            Route(
                vehicle_id="CV2",
                vehicle_type="cv",
                home_depot_id="D0",
                node_sequence=["D0", "C4", "C5", "C6", "D0"],
            ),
        ]
    )
    context = EvaluationContext(
        instance,
        [],
        prices=prices,
        budget=EvalBudget(limit=budget, target=budget),
    )
    return solution, context


def test_true_swapstar_uses_free_reinsertion_and_is_deterministic() -> None:
    solution, context = _fixture(5)
    config = TrueSwapStarConfig(overlap_tolerance=1.0)
    first = _ranked_true_swapstar_moves(solution, context, config=config)
    second = _ranked_true_swapstar_moves(solution, context, config=config)

    assert first == second
    assert first
    best = first[0]
    left_original_position = solution.routes[best.left_route_idx].node_sequence.index(
        best.left_customer
    ) - 1
    right_original_position = solution.routes[
        best.right_route_idx
    ].node_sequence.index(best.right_customer) - 1
    assert (
        best.left_insert_idx != left_original_position
        or best.right_insert_idx != right_original_position
    )


def test_true_swapstar_kernel_switch_is_default_off_and_exclusive() -> None:
    assert e2_alns_variant_flags()[TRUE_SWAPSTAR_FLAG] == "0"
    assert (
        structural_component_from_flags({TRUE_SWAPSTAR_FLAG: "1"})
        == "true_swapstar"
    )
    with pytest.raises(
        ValueError,
        match="HALT_CONFIG_CONFLICT_STRUCTURAL_FLAGS",
    ):
        structural_component_from_flags(
            {
                TRUE_SWAPSTAR_FLAG: "1",
                ROUTE_POOL_RECOMBINATION_FLAG: "1",
            }
        )


@pytest.mark.parametrize("budget", [0, 1, 2, 5])
def test_true_swapstar_closes_complete_score_budget(budget: int) -> None:
    solution, context = _fixture(budget)
    prepared, initial_objective = score_reference_solution(
        solution,
        context,
        phase="test_initial",
    )
    result = true_swapstar_intensify(
        prepared,
        context,
        incumbent_objective=initial_objective,
        max_evaluations=budget,
        config=TrueSwapStarConfig(overlap_tolerance=1.0),
    )

    assert context.budget is not None
    assert context.budget.count == result.evaluations_used
    assert result.evaluations_used <= budget
    assert result.objective <= initial_objective + 1e-9
    if budget == 0:
        assert result.stop_reason == "zero_evaluation_budget"
        assert not result.accepted_moves
    else:
        assert result.evaluations_used > 0
        assert result.accepted_moves
