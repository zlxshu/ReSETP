from __future__ import annotations

from .common import (
    adjacency_signature,
    canonical_route_signature,
    route_signatures,
)


def _route(home: str, customers: list[str]) -> dict[str, object]:
    return {
        "home_depot_id": home,
        "node_sequence": [home, *customers, home],
    }


def test_route_signature_ignores_direction_depot_and_vehicle() -> None:
    left = _route("D_A", ["C001", "C002", "C003"])
    right = _route("D_B", ["C003", "C002", "C001"])
    assert route_signatures([left]) == route_signatures([right])
    assert canonical_route_signature(
        ("C001", "C002", "C003")
    ) == ("C001", "C002", "C003")


def test_single_customer_route_does_not_count_as_order_novelty() -> None:
    assert route_signatures([_route("D_A", ["C001"])]) == set()


def test_adjacency_excludes_depot_edges_and_is_undirected() -> None:
    forward = adjacency_signature(
        [_route("D_A", ["C001", "C002", "C003"])]
    )
    reverse = adjacency_signature(
        [_route("D_B", ["C003", "C002", "C001"])]
    )
    assert forward == reverse
    assert forward == {("C001", "C002"), ("C002", "C003")}
