from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import route_pool_sp
from route_pool_sp import (
    RoutePoolRecord,
    _accepted_mip_completion,
    _route_pool_records,
    _solve_set_partitioning,
    run_hgs_route_pool_recombination,
)
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import _single_route_cost
from setp_solver.solution import Route
from setp_solver.solution import Solution


ROOT = Path(__file__).resolve().parents[3]
INSTANCE_ID = "cn-prd-10c-01-V2-LOCATIONS"
FLEET = (
    ROOT
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v1_20260723"
)


def _fixture() -> tuple[object, tuple[RoutePoolRecord, ...]]:
    bundle = load_china81_bundle(ROOT, INSTANCE_ID)
    payload = json.loads(
        (FLEET / "witnesses" / f"{INSTANCE_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    records = []
    for rank, row in enumerate(payload["routes"]):
        route = Route(
            vehicle_id=row["vehicle_id"],
            vehicle_type=row["vehicle_type"],
            home_depot_id=row["home_depot_id"],
            node_sequence=list(row["node_sequence"]),
        )
        records.append(
            RoutePoolRecord(
                route=route,
                actions=(),
                customers=tuple(route.node_sequence[1:-1]),
                route_cost=_single_route_cost(route, (), bundle),
                source_view="fixture",
                source_rank=rank,
            )
        )
    return bundle, tuple(records)


def _initial_solution(records: tuple[RoutePoolRecord, ...]) -> Solution:
    return Solution(routes=[record.route for record in records])


def test_time_limited_mip_reports_status_bound_gap_and_incumbent() -> None:
    bundle, records = _fixture()

    solution, stats = _solve_set_partitioning(
        bundle,
        records,
        time_limit_seconds=5.0,
        hard_home_depot_lock=True,
    )

    assert solution is not None
    assert stats["status_class"] == "OPTIMAL"
    assert stats["optimality_proven"] is True
    assert stats["incumbent_available"] is True
    assert stats["objective"] is not None
    assert stats["dual_bound"] is not None
    assert stats["mip_gap"] is not None
    assert stats["incumbent_vector_integral"] is True
    assert stats["incumbent_cover_exact"] is True
    assert stats["independent_violation_count"] == 0
    assert stats["objective_closes_under_complete_model"] is False
    assert stats["objective_is_search_surrogate"] is True

    completion = _accepted_mip_completion(
        solution,
        bundle,
        stats,
    )
    assert completion.solution.routes == solution.routes
    assert (
        completion.solution.charging_actions
        == solution.charging_actions
    )
    assert completion.objective == stats["independent_exact_objective"]
    assert completion.activity["complete_model_recheck"] == "PASS"


def test_time_limit_incumbent_is_accepted_without_optimality_claim(
    monkeypatch,
) -> None:
    bundle, records = _fixture()
    costs = np.array([record.route_cost for record in records])
    monkeypatch.setattr(
        route_pool_sp,
        "milp",
        lambda **_: SimpleNamespace(
            success=False,
            status=1,
            message="Time limit reached",
            x=np.ones(len(records)),
            fun=float(costs.sum()),
            mip_dual_bound=float(costs.sum() - 1.0),
            mip_gap=0.01,
            mip_node_count=7,
        ),
    )

    solution, stats = _solve_set_partitioning(
        bundle,
        records,
        time_limit_seconds=0.01,
        hard_home_depot_lock=True,
    )

    assert solution is not None
    assert stats["status_class"] == "LIMIT_WITH_INCUMBENT"
    assert stats["optimality_proven"] is False
    assert stats["incumbent_vector_integral"] is True
    assert stats["incumbent_cover_exact"] is True
    assert stats["independent_violation_count"] == 0


def test_nonintegral_or_absent_incumbent_is_rejected(monkeypatch) -> None:
    bundle, records = _fixture()
    monkeypatch.setattr(
        route_pool_sp,
        "milp",
        lambda **_: SimpleNamespace(
            success=False,
            status=1,
            message="Time limit reached",
            x=np.full(len(records), 0.5),
            fun=1.0,
            mip_dual_bound=0.0,
            mip_gap=1.0,
            mip_node_count=0,
        ),
    )
    solution, stats = _solve_set_partitioning(
        bundle,
        records,
        time_limit_seconds=0.01,
    )
    assert solution is None
    assert stats["status_class"] == "REJECTED_NONINTEGRAL_INCUMBENT"
    assert stats["optimality_proven"] is False

    monkeypatch.setattr(
        route_pool_sp,
        "milp",
        lambda **_: SimpleNamespace(
            success=False,
            status=1,
            message="Time limit reached without incumbent",
            x=None,
            fun=None,
            mip_dual_bound=0.0,
            mip_gap=None,
            mip_node_count=0,
        ),
    )
    solution, stats = _solve_set_partitioning(
        bundle,
        records,
        time_limit_seconds=0.01,
    )
    assert solution is None
    assert stats["status_class"] == "NO_INCUMBENT"
    assert stats["optimality_proven"] is False


def test_paired_arms_register_the_same_complete_candidate_budget() -> None:
    bundle, records = _fixture()
    initial = _initial_solution(records)
    observed = []
    for hard_lock in (True, False):
        run = run_hgs_route_pool_recombination(
            bundle,
            initial,
            seed=1,
            hgs_seconds_per_view=None,
            exact_elites_per_view=8,
            max_archive_candidates_per_view=24,
            sp_time_limit_seconds=2.0,
            hard_home_depot_lock=hard_lock,
            max_hgs_iterations_per_view=100,
            wallclock_safety_seconds_per_view=30.0,
        )
        assert run.stats["wallclock_safety_triggered"] is False
        assert run.stats["complete_candidate_budget_expected"] == 80
        assert (
            run.stats["complete_candidate_evaluation_attempts"]
            <= run.stats["complete_candidate_budget_expected"]
        )
        observed.append(
            run.stats["complete_candidate_budget_expected"]
        )
    assert observed == [80, 80]


def test_uncapped_views_stop_only_after_no_improvement_wallclock() -> None:
    bundle, records = _fixture()
    run = run_hgs_route_pool_recombination(
        bundle,
        _initial_solution(records),
        seed=1,
        hgs_seconds_per_view=None,
        exact_elites_per_view=2,
        max_archive_candidates_per_view=4,
        sp_time_limit_seconds=0.1,
        hard_home_depot_lock=True,
        max_hgs_iterations_per_view=None,
        wallclock_safety_seconds_per_view=None,
        hgs_no_improvement_seconds_per_view=0.01,
        exact_checkpoint_interval_iterations=20,
    )

    assert run.stats["max_hgs_iterations_per_view"] == {
        "cv_only": None,
        "naive_ev": None,
        "mechanism_ev": None,
    }
    for view in ("cv_only", "naive_ev", "mechanism_ev"):
        audit = run.stats["view_search_instrumentation"][view]
        assert audit["hgs_stop_reason"] == "NO_IMPROVEMENT_WALLCLOCK"
        assert audit["no_improvement_wallclock_triggered"] is True
        assert audit["no_improvement_elapsed_seconds_at_trigger"] >= 0.01


def test_route_pool_uses_all_already_scored_archive_completions() -> None:
    bundle, records = _fixture()
    routes_a = [record.route for record in records]
    routes_b = list(routes_a)
    first = routes_b[0]
    routes_b[0] = Route(
        vehicle_id=first.vehicle_id,
        vehicle_type=first.vehicle_type,
        home_depot_id=first.home_depot_id,
        node_sequence=[
            first.node_sequence[0],
            *reversed(first.node_sequence[1:-1]),
            first.node_sequence[-1],
        ],
    )
    epoch = SimpleNamespace(
        elite_completions=(
            SimpleNamespace(solution=Solution(routes=routes_a)),
        ),
        archive_completions=(
            SimpleNamespace(solution=Solution(routes=routes_a)),
            SimpleNamespace(solution=Solution(routes=routes_b)),
        ),
    )

    pooled = _route_pool_records(
        bundle,
        {"mechanism_ev": epoch},
    )

    route_sequences = {
        tuple(record.route.node_sequence) for record in pooled
    }
    assert tuple(first.node_sequence) in route_sequences
    assert tuple(routes_b[0].node_sequence) in route_sequences
