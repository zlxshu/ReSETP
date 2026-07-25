#!/usr/bin/env python3
"""Tests for five-parent route-column pool construction helpers."""

from __future__ import annotations

from direct_gate_support import selected_new_boundaries
from mip_core import RouteColumn


def _column(customers: tuple[str, ...], source: str) -> RouteColumn:
    return RouteColumn(
        customers=customers,
        cost=1.0,
        fleet_delta=(1,),
        charger_use=(),
        payload={"kind": "test"},
        source=source,
    )


def test_selected_new_boundaries_compares_customer_boundaries() -> None:
    old_pool = (
        _column(("C1", "C2"), "incumbent"),
        _column(("C3",), "incumbent"),
    )
    selected = (
        _column(("C1",), "generated_segment"),
        _column(("C2", "C3"), "generated_segment"),
    )
    assert selected_new_boundaries(selected, old_pool) == (
        ("C1",),
        ("C2", "C3"),
    )


def test_same_boundary_is_not_misreported_as_new() -> None:
    old_pool = (_column(("C1", "C2"), "incumbent"),)
    selected = (_column(("C1", "C2"), "generated_segment"),)
    assert selected_new_boundaries(selected, old_pool) == ()
