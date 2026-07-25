"""Focused structural tests for the tailored DP-VNS neighbourhoods."""

from __future__ import annotations

from dataclasses import dataclass

from neighborhoods import (
    NEIGHBORHOOD_ORDER,
    customer_multiset,
    generate_ranked_candidates,
)
from setp_solver.solution import Route, Solution


@dataclass(frozen=True)
class _Node:
    node_id: str
    node_type: str


class _Instance:
    nodes = [
        _Node("D1", "d"),
        _Node("D2", "d"),
        *[_Node(f"C{index}", "c") for index in range(1, 7)],
    ]

    @staticmethod
    def distance(left: str, right: str) -> float:
        order = {
            "D1": 0,
            "C1": 1,
            "C2": 2,
            "C3": 3,
            "D2": 10,
            "C4": 9,
            "C5": 8,
            "C6": 7,
        }
        return abs(order[left] - order[right]) + 1.0


@dataclass(frozen=True)
class _Bundle:
    instance: _Instance = _Instance()


def _solution() -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id="CV1",
                vehicle_type="cv",
                home_depot_id="D1",
                node_sequence=["D1", "C1", "C3", "C2", "D1"],
            ),
            Route(
                vehicle_id="EV1",
                vehicle_type="ev",
                home_depot_id="D2",
                node_sequence=["D2", "C4", "C6", "C5", "D2"],
            ),
        ]
    )


def test_all_registered_neighborhoods_are_active_and_preserve_customers() -> None:
    baseline = customer_multiset(_solution(), _Bundle())
    for neighborhood in NEIGHBORHOOD_ORDER:
        candidates = generate_ranked_candidates(
            _solution(),
            _Bundle(),
            neighborhood=neighborhood,
            limit=5,
        )
        assert candidates
        assert all(
            customer_multiset(candidate.skeleton, _Bundle()) == baseline
            for candidate in candidates
        )


def test_ranked_candidates_are_deterministic() -> None:
    for neighborhood in NEIGHBORHOOD_ORDER:
        first = generate_ranked_candidates(
            _solution(),
            _Bundle(),
            neighborhood=neighborhood,
            limit=5,
        )
        second = generate_ranked_candidates(
            _solution(),
            _Bundle(),
            neighborhood=neighborhood,
            limit=5,
        )
        assert first == second

