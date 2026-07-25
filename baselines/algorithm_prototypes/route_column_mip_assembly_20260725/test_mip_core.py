from __future__ import annotations

from mip_core import RouteColumn, solve_route_columns


def column(
    customers: tuple[str, ...],
    cost: float,
    *,
    fleet: tuple[int, ...] = (1,),
    charger: tuple[tuple[str, int, int, int], ...] = (),
) -> RouteColumn:
    return RouteColumn(
        customers=customers,
        cost=cost,
        fleet_delta=fleet,
        charger_use=charger,
        payload=customers,
        source="test",
    )


def test_mip_matches_small_exhaustive_cover() -> None:
    columns = (
        column(("A",), 4),
        column(("B",), 4),
        column(("C",), 4),
        column(("A", "B"), 5),
        column(("C",), 1),
    )
    result = solve_route_columns(
        ("A", "B", "C"),
        columns,
        fleet_caps=(3,),
        charger_caps={},
        time_limit_seconds=2.0,
    )
    assert result.status_class == "OPTIMAL"
    assert result.objective == 6
    assert {item.customers for item in result.selected} == {
        ("A", "B"),
        ("C",),
    }


def test_charger_capacity_changes_selected_cover() -> None:
    slot = (("S", 0, 8, 1),)
    columns = (
        column(("A",), 1, fleet=(1, 0), charger=slot),
        column(("B",), 1, fleet=(1, 0), charger=slot),
        column(("A",), 3, fleet=(0, 1)),
        column(("B",), 3, fleet=(0, 1)),
    )
    result = solve_route_columns(
        ("A", "B"),
        columns,
        fleet_caps=(2, 2),
        charger_caps={"S": 1},
        time_limit_seconds=2.0,
    )
    assert result.status_class == "OPTIMAL"
    assert result.objective == 4
    assert result.charger_feasible is True
