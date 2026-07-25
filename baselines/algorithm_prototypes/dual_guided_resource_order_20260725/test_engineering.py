"""Zero-objective tests for LP duals and the order DP."""

from __future__ import annotations

import math

from limited_displacement import (
    generate_limited_displacement_orders,
    is_material_order_and_membership_change,
)
from lp_duals import rank_route_pairs, solve_pool_lp_duals
from mip_core import RouteColumn


def _column(
    customers: tuple[str, ...],
    cost: float,
    fleet: tuple[int, ...],
) -> RouteColumn:
    return RouteColumn(
        customers=customers,
        cost=cost,
        fleet_delta=fleet,
        charger_use=(),
        payload=None,
        source="test",
    )


def test_lp_duals_close_and_select_resource_competing_pair() -> None:
    columns = (
        _column(("A",), 1.0, (1, 0)),
        _column(("B",), 1.0, (1, 0)),
        _column(("C",), 1.0, (0, 1)),
        _column(("A",), 4.0, (0, 1)),
        _column(("B",), 4.0, (0, 1)),
        _column(("C",), 4.0, (1, 0)),
    )
    result = solve_pool_lp_duals(
        ("A", "B", "C"),
        columns,
        fleet_caps=(1, 3),
        charger_caps={},
    )
    assert math.isclose(result.objective, result.dual_objective, abs_tol=1.0e-7)
    assert result.primal_residual <= 1.0e-7
    incumbent = (columns[0], columns[1], columns[2])
    pairs = rank_route_pairs(
        incumbent,
        (("A",), ("B",), ("C",)),
        result,
        limit=1,
    )
    assert pairs[0][:2] == (0, 1)


def test_dp_changes_order_and_movable_membership() -> None:
    order = ("A", "B", "C", "D", "E", "F")
    ready = {item: 0.0 for item in order}
    due = {item: 10_000.0 for item in order}
    service = {item: 0.0 for item in order}
    demands = {item: 1.0 for item in order}
    cheap = {("A", "C"), ("C", "B"), ("B", "D")}

    def cost(left: str, right: str, phase: int) -> float:
        del phase
        return 0.0 if (left, right) in cheap else 10.0

    rows, states = generate_limited_displacement_orders(
        order,
        direction=0,
        k=4,
        top_n=8,
        state_limit=100_000,
        demands=demands,
        max_payload=5.0,
        ready=ready,
        due=due,
        service=service,
        first_depot="D1",
        second_depot="D2",
        arc_cost=cost,
        travel_time=lambda left, right, phase: 0.0,
    )
    assert rows
    assert states > 0
    assert any(
        is_material_order_and_membership_change(
            row,
            ("A", "B", "C"),
            ("D", "E", "F"),
        )
        for row in rows
    )


def test_dp_enforces_state_limit() -> None:
    order = ("A", "B", "C", "D")
    scalar = {item: 0.0 for item in order}
    try:
        generate_limited_displacement_orders(
            order,
            direction=0,
            k=4,
            top_n=4,
            state_limit=1,
            demands=scalar,
            max_payload=10.0,
            ready=scalar,
            due={item: 100.0 for item in order},
            service=scalar,
            first_depot="D1",
            second_depot="D2",
            arc_cost=lambda left, right, phase: 1.0,
            travel_time=lambda left, right, phase: 0.0,
        )
    except RuntimeError as exc:
        assert "state cap exceeded" in str(exc)
    else:
        raise AssertionError("state cap was not enforced")

