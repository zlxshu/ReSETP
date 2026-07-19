from __future__ import annotations

from exact_route_pool_recombiner import PoolRoute, exact_recombine
from setp_solver.solution import Route


def record(customers: str, score: float, source: str) -> PoolRoute:
    visits = list(customers)
    return PoolRoute(
        route=Route(
            vehicle_id=f"{source}-{customers}",
            vehicle_type="cv",
            home_depot_id="D0",
            node_sequence=["D0", *visits, "D0"],
        ),
        customers=frozenset(visits),
        additive_score=score,
        source=source,
    )


def test_exact_pool_combines_routes_from_both_parents() -> None:
    records = [
        record("AB", 10.0, "HGS"),
        record("C", 20.0, "HGS"),
        record("D", 20.0, "HGS"),
        record("A", 20.0, "ALNS"),
        record("B", 20.0, "ALNS"),
        record("CD", 10.0, "ALNS"),
    ]
    result = exact_recombine(records, "ABCD")
    assert result is not None
    assert result.additive_score == 20.0
    assert set(result.selected_sources) == {"HGS", "ALNS"}
    assert {
        customer
        for route in result.solution.routes
        for customer in route.node_sequence
        if customer != "D0"
    } == set("ABCD")


def test_exact_pool_rejects_incomplete_cover() -> None:
    assert exact_recombine([record("AB", 1.0, "HGS")], "ABC") is None
