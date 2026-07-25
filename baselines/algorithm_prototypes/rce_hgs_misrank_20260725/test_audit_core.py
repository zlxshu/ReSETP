"""Tests for the frozen non-iterative candidate panel."""

from setp_solver.solution import Route, Solution

from rce_hgs_misrank_20260725.audit_core import (
    ACTION_QUOTA,
    ACTION_TYPES,
    generate_candidates,
    solution_signature,
)


def _fixture_solution() -> Solution:
    routes = []
    customer = 1
    for route_index in range(4):
        depot = f"D{route_index % 2}"
        customers = [
            f"C{index:03d}"
            for index in range(customer, customer + 8)
        ]
        customer += 8
        routes.append(
            Route(
                vehicle_id=f"V{route_index}",
                vehicle_type="cv" if route_index % 2 == 0 else "ev",
                home_depot_id=depot,
                node_sequence=[depot, *customers, depot],
            )
        )
    return Solution(routes=routes)


def test_candidate_panel_is_deterministic_and_balanced() -> None:
    solution = _fixture_solution()
    first = generate_candidates(solution, "fixture", 1)
    second = generate_candidates(solution, "fixture", 1)
    assert len(first) == ACTION_QUOTA * len(ACTION_TYPES)
    assert [
        (descriptor, signature)
        for descriptor, _, signature in first
    ] == [
        (descriptor, signature)
        for descriptor, _, signature in second
    ]
    assert {
        action: sum(
            descriptor.action_type == action
            for descriptor, _, _ in first
        )
        for action in ACTION_TYPES
    } == {action: ACTION_QUOTA for action in ACTION_TYPES}


def test_candidates_preserve_customer_cover_and_do_not_mutate_parent() -> None:
    solution = _fixture_solution()
    parent_signature = solution_signature(solution)
    expected = sorted(
        node
        for route in solution.routes
        for node in route.node_sequence[1:-1]
    )
    for _, candidate, signature in generate_candidates(
        solution,
        "fixture",
        2,
    ):
        observed = sorted(
            node
            for route in candidate.routes
            for node in route.node_sequence[1:-1]
        )
        assert observed == expected
        assert signature != parent_signature
    assert solution_signature(solution) == parent_signature

