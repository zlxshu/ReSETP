from __future__ import annotations

import math
import random
from pathlib import Path

import pytest

from dr_alns_ppo.operator_manual import (
    RouletteStats,
    apply_destroy,
    apply_repair,
    removal_count,
    sa_accept,
)
from setp_solver.check import check_solution
from setp_solver.instance_loader import Instance, Node
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.construction import build_initial_solution
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.solution import Route, Solution


FIXTURE_DIR = Path("models/data_bundle/generated_instances/verify_20251113")


def test_removal_count_clips_ratio_and_handles_empty_customer_set() -> None:
    assert removal_count(0, 0.4) == 0
    assert removal_count(-5, 0.4) == 0
    assert removal_count(25, 0.01) == 3
    assert removal_count(25, 0.4) == 10
    assert removal_count(25, 0.9) == 10
    assert removal_count(1, 0.1) == 1


def test_sa_accept_always_accepts_non_worse_and_metropolis_for_worse() -> None:
    assert sa_accept(-1.0, 0.0, 0.99)
    assert sa_accept(0.0, 0.0, 0.99)
    assert not sa_accept(1.0, 0.0, 0.0)

    threshold = math.exp(-2.0 / 4.0)
    assert sa_accept(2.0, 4.0, threshold - 1e-12)
    assert not sa_accept(2.0, 4.0, threshold)


def test_roulette_stats_records_rewards_and_updates_used_operators_only() -> None:
    stats = RouletteStats.create(["D1", "D2"])
    stats.record("D1", "global_best")
    stats.record("D1", "accepted_worse")
    stats.record("D2", "unknown")

    assert stats.scores == {"D1": 7.0, "D2": 0.0}
    assert stats.uses == {"D1": 2, "D2": 1}

    stats.update_segment()

    assert stats.weights["D1"] == pytest.approx(0.8 * 1.0 + 0.2 * 3.5)
    assert stats.weights["D2"] == pytest.approx(0.8)
    assert stats.scores == {"D1": 0.0, "D2": 0.0}
    assert stats.uses == {"D1": 0, "D2": 0}


@pytest.fixture()
def fixture_context_and_solution():
    bundle = load_search_bundle(FIXTURE_DIR)
    solution = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        introduce_ev=True,
        require_charging_signal=False,
    )
    assert check_solution(solution, bundle.instance) == []
    return EvaluationContext(bundle.instance, bundle.carbon_profile), solution


def test_destroy_operators_remove_at_least_ten_percent_on_fixture(fixture_context_and_solution) -> None:
    context, solution = fixture_context_and_solution
    customer_count = sum(1 for node in context.instance.nodes if node.node_type.lower() == "c")
    expected = math.ceil(0.1 * customer_count)

    for destroy_id in ["D1", "D2", "D3", "D5"]:
        partial, removed, trace = apply_destroy(solution, context, random.Random(7), destroy_id, 0.1)

        assert len(removed) >= expected, destroy_id
        assert trace["removed_count"] == len(removed)
        remaining = {
            node_id
            for route in partial.routes
            for node_id in route.node_sequence
            if node_id.startswith("C")
        }
        assert not (remaining & set(removed))


def test_d2_worst_removal_does_not_consume_full_candidate_evals(fixture_context_and_solution) -> None:
    context, solution = fixture_context_and_solution
    context.budget = EvalBudget(limit=1, target=1)

    partial, removed, trace = apply_destroy(solution, context, random.Random(7), "D2", 0.4)

    assert removed
    assert trace["destroy_id"] == "D2"
    assert context.budget.count == 0
    assert context.score_counts.get("candidate", 0) == 0
    assert context.score_counts.get("repair_delta", 0) == 0
    assert len(partial.routes) <= len(solution.routes)


def test_d4_removes_shortest_route_from_top_half_by_route_contribution() -> None:
    nodes = [
        Node("D0", "d", 0.0, 0.0, due_time=50_000.0),
        Node("C1", "c", 100.0, 0.0, due_time=50_000.0),
        Node("C2", "c", 1000.0, 0.0, due_time=50_000.0),
        Node("C3", "c", 1001.0, 0.0, due_time=50_000.0),
        Node("C4", "c", 1002.0, 0.0, due_time=50_000.0),
        Node("C5", "c", 900.0, 0.0, due_time=50_000.0),
        Node("C6", "c", 901.0, 0.0, due_time=50_000.0),
        Node("C7", "c", 300.0, 0.0, due_time=50_000.0),
    ]
    distance_matrix = [
        [math.hypot(left.x - right.x, left.y - right.y) for right in nodes]
        for left in nodes
    ]
    context = EvaluationContext(Instance(nodes=nodes, distance_matrix=distance_matrix), [])
    solution = Solution(
        routes=[
            Route("CV_LOW", "cv", "D0", ["D0", "C1", "D0"]),
            Route("CV_EXPENSIVE_LONG", "cv", "D0", ["D0", "C2", "C3", "C4", "D0"]),
            Route("CV_EXPENSIVE_SHORT", "cv", "D0", ["D0", "C5", "C6", "D0"]),
            Route("CV_MID", "cv", "D0", ["D0", "C7", "D0"]),
        ]
    )

    partial, removed, trace = apply_destroy(solution, context, random.Random(99), "D4", 0.1)

    assert removed == ["C5", "C6"]
    assert trace["removed_count"] == 2
    remaining_route_ids = {route.vehicle_id for route in partial.routes}
    assert "CV_EXPENSIVE_SHORT" not in remaining_route_ids
    assert all("C5" not in route.node_sequence and "C6" not in route.node_sequence for route in partial.routes)


@pytest.mark.parametrize("repair_id", ["R2", "R3"])
def test_regret_repairs_produce_feasible_solution_and_record_delta_scores(
    fixture_context_and_solution,
    repair_id: str,
) -> None:
    context, solution = fixture_context_and_solution
    partial, removed, _ = apply_destroy(solution, context, random.Random(3), "D1", 0.1)

    before = int(context.score_counts.get("repair_delta", 0))
    candidate, trace = apply_repair(partial, removed, context, repair_id)

    assert check_solution(candidate, context.instance, context.prices) == []
    assert int(context.score_counts.get("repair_delta", 0)) > before
    assert trace["repair_delta_count"] == int(context.score_counts.get("repair_delta", 0))


def test_selected_ev_insertion_is_charging_repaired_and_feasible() -> None:
    nodes = [
        Node("D0", "d", 0.0, 0.0, due_time=50_000.0, station_chargers=4),
        Node("C1", "c", 10_000.0, 0.0, demand=100.0, due_time=50_000.0),
        Node("C2", "c", 11_000.0, 0.0, demand=100.0, due_time=50_000.0),
        Node("F1", "f", 5_000.0, 0.0, due_time=50_000.0, charge_power_kw=60.0, station_chargers=1),
    ]
    distance_matrix = [
        [math.hypot(left.x - right.x, left.y - right.y) for right in nodes]
        for left in nodes
    ]
    profile = [
        {
            "time_index": idx,
            "datetime_utc": f"2025-11-13T{idx:02d}:00:00Z",
            "actual_gco2_per_kwh": 100.0,
            "forecast_gco2_per_kwh": 100.0,
            "index_label": str(idx),
            "index_code": idx,
            "horizon_second_start": float(idx * 1800),
        }
        for idx in range(48)
    ]
    context = EvaluationContext(Instance(nodes=nodes, distance_matrix=distance_matrix), profile)
    partial = Solution(routes=[Route("EV1", "ev", "D0", ["D0", "C1", "D0"])])

    candidate, trace = apply_repair(partial, ["C2"], context, "R2")

    assert trace["insertions"] == [
        {
            "customer_id": "C2",
            "score": pytest.approx(2000.0),
            "route_index": 0,
            "insert_at": 0,
            "vehicle_type": "ev",
        }
    ]
    assert candidate.charging_actions
    assert all(action.vehicle_id == "EV1" for action in candidate.charging_actions)
    assert candidate.routes == [Route("EV1", "ev", "D0", ["D0", "C2", "C1", "D0"])]
    assert check_solution(candidate, context.instance, context.prices) == []
