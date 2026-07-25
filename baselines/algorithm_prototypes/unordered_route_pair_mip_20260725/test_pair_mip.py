#!/usr/bin/env python3
"""Tests for the residual-resource route-pair MIP."""

from __future__ import annotations

from mip_core import RouteColumn
from pair_mip import solve_pair_columns


def column(
    customers: tuple[str, ...],
    cost: float,
    *,
    fleet: tuple[int, ...] = (1,),
    slots: tuple[tuple[str, int, int, int], ...] = (),
) -> RouteColumn:
    return RouteColumn(
        customers=customers,
        cost=cost,
        fleet_delta=fleet,
        charger_use=slots,
        payload={"kind": "test"},
        source="test",
    )


def test_pair_mip_selects_better_new_boundary_cover() -> None:
    columns = (
        column(("C1", "C2"), 10.0),
        column(("C3", "C4"), 10.0),
        column(("C1",), 2.0),
        column(("C2", "C3"), 4.0),
        column(("C4",), 2.0),
    )
    result = solve_pair_columns(
        ("C1", "C2", "C3", "C4"),
        columns,
        residual_fleet_caps=(3,),
        residual_charger_caps={},
        time_limit_seconds=1.0,
    )
    assert result.status_class == "OPTIMAL"
    assert result.objective == 8.0
    assert tuple(row.customers for row in result.selected) == (
        ("C1",),
        ("C2", "C3"),
        ("C4",),
    )


def test_pair_mip_respects_residual_slot_capacity() -> None:
    slot = ("S1", 0, 4, 1)
    columns = (
        column(("C1",), 1.0, slots=(slot,)),
        column(("C2",), 1.0, slots=(slot,)),
        column(("C1",), 3.0),
        column(("C2",), 3.0),
    )
    result = solve_pair_columns(
        ("C1", "C2"),
        columns,
        residual_fleet_caps=(2,),
        residual_charger_caps={("S1", 0, 4): 1},
        time_limit_seconds=1.0,
    )
    assert result.status_class == "OPTIMAL"
    assert result.objective == 4.0
    assert sum(bool(row.charger_use) for row in result.selected) == 1
