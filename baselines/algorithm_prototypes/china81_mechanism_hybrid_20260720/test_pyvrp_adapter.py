from __future__ import annotations

from pathlib import Path

from pyvrp import Solution as PyVRPSolution
import pyvrp_adapter

from epochal_hgs import (
    _AuditedNoImprovementWallclock,
    _run_exact_epoch,
)
from pyvrp_adapter import (
    BUSINESS_HARD_INFEASIBLE,
    PROXY_FOUND_COMPLETION_FAILED,
    SEARCH_NOT_FOUND,
    _completion_failure_category,
    _project_initial_solution,
    _translate_solution,
    build_pyvrp_problem,
    run_pyvrp_hgs_skeleton,
)
from setp_solver.algorithms.resetp_alns.support.construction import (
    build_initial_solution,
)
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import exact_china81_score
from setp_solver.solution import Route, Solution


ROOT = Path(__file__).resolve().parents[3]
INSTANCE_ID = "cn-jjj-10c-01-V2-LOCATIONS"


def _fixture():
    bundle = load_china81_bundle(ROOT, INSTANCE_ID)
    initial = build_initial_solution(
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        introduce_ev=False,
        require_charging_signal=False,
    )
    return bundle, initial


def test_no_improvement_wallclock_resets_only_at_relative_threshold() -> None:
    timestamps = iter((0.0, 100.0, 200.0, 279.0, 280.0))
    criterion = _AuditedNoImprovementWallclock(
        180.0,
        minimum_relative_improvement=0.01,
        clock=lambda: next(timestamps),
    )

    assert criterion(100.0) is False
    assert criterion(90.0) is False
    assert criterion(89.5) is False
    assert criterion(89.5) is False
    assert criterion(89.5) is True
    assert criterion.triggered is True
    assert criterion.last_improvement_iteration == 1
    assert criterion.trigger_iteration == 4
    assert criterion.last_improvement_elapsed_seconds == 100.0
    assert criterion.trigger_elapsed_seconds == 280.0
    assert criterion.no_improvement_elapsed_seconds == 180.0
    assert criterion.timer_reset_count == 1
    assert criterion.ignored_strict_improvement_count == 1
    assert criterion.improvement_audit == (
        {
            "iteration": 1,
            "objective_before": 100.0,
            "objective_after": 90.0,
            "improvement_absolute": 10.0,
            "improvement_relative": 0.1,
            "timer_reset_threshold_relative": 0.01,
            "timer_reset": True,
            "elapsed_seconds": 100.0,
        },
        {
            "iteration": 2,
            "objective_before": 90.0,
            "objective_after": 89.5,
            "improvement_absolute": 0.5,
            "improvement_relative": 0.5 / 90.0,
            "timer_reset_threshold_relative": 0.01,
            "timer_reset": False,
            "elapsed_seconds": 200.0,
        },
    )


def test_initial_projection_round_trip_preserves_customer_service() -> None:
    bundle, initial = _fixture()
    problem = build_pyvrp_problem(bundle)
    data = problem.model.data()
    projection_source = pyvrp_adapter.complete_china81_route_skeleton(
        initial,
        bundle,
    ).solution

    projected = _project_initial_solution(
        projection_source,
        data,
        problem,
        bundle,
    )
    assert isinstance(projected, PyVRPSolution)
    restored = _translate_solution(projected, problem)

    expected = sorted(
        node.node_id
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    )
    observed = sorted(
        node_id
        for route in restored.routes
        for node_id in route.node_sequence[1:-1]
    )
    assert observed == expected


def test_warm_projection_preserves_ev_route_type() -> None:
    bundle, initial = _fixture()
    first, *remaining = initial.routes
    mixed = Solution(
        routes=[
            Route(
                vehicle_id=first.vehicle_id,
                vehicle_type="ev",
                home_depot_id=first.home_depot_id,
                node_sequence=list(first.node_sequence),
            ),
            *remaining,
        ]
    )
    problem = build_pyvrp_problem(
        bundle,
        route_proxy_mode="mechanism_ev",
    )
    projected = _project_initial_solution(
        mixed,
        problem.model.data(),
        problem,
        bundle,
    )
    restored = _translate_solution(projected, problem)

    assert sum(
        route.vehicle_type == "ev" for route in restored.routes
    ) == 1


def test_cv_only_projection_intentionally_maps_ev_route_to_cv() -> None:
    bundle, initial = _fixture()
    first, *remaining = initial.routes
    mixed = Solution(
        routes=[
            Route(
                vehicle_id=first.vehicle_id,
                vehicle_type="ev",
                home_depot_id=first.home_depot_id,
                node_sequence=list(first.node_sequence),
            ),
            *remaining,
        ]
    )
    problem = build_pyvrp_problem(bundle, route_proxy_mode="cv_only")
    projected = _project_initial_solution(
        mixed,
        problem.model.data(),
        problem,
        bundle,
    )
    restored = _translate_solution(projected, problem)

    assert all(route.vehicle_type == "cv" for route in restored.routes)


def test_exact_epoch_collects_quality_diverse_history_without_extra_calls(
) -> None:
    bundle, initial = _fixture()
    problem = build_pyvrp_problem(
        bundle,
        route_proxy_mode="mechanism_ev",
    )
    epoch = _run_exact_epoch(
        bundle,
        problem,
        initial,
        seed=7,
        runtime_seconds=None,
        warm_elites=(),
        exact_elite_count=2,
        max_archive_candidates=8,
        max_hgs_iterations=100,
        wallclock_safety_seconds=30.0,
        exact_checkpoint_interval_iterations=10,
        collect_historical_population_archive=True,
    )

    assert epoch.stats["historical_population_archive_enabled"] is True
    assert epoch.stats["historical_population_snapshot_count"] == 10
    assert epoch.stats["historical_population_candidate_references"] > 0
    assert epoch.stats["archive_quality_selected_count"] == 4
    assert epoch.stats["archive_diversity_selected_count"] == 4
    assert epoch.stats["archive_completion_attempts"] == 8
    assert epoch.stats["complete_candidate_evaluation_attempts"] == 20
    required_trace_fields = {
        "candidate_id",
        "completion_succeeded",
        "exception_type",
        "exception_message",
        "failure_category",
    }
    for row in epoch.stats["complete_candidate_evaluation_trace"]:
        assert required_trace_fields <= row.keys()
        assert len(row["candidate_id"]) == 64


def test_pyvrp_result_passes_shared_full_completion() -> None:
    bundle, initial = _fixture()

    run = run_pyvrp_hgs_skeleton(
        bundle,
        initial,
        seed=1,
        runtime_seconds=0.10,
    )

    objective, breakdown, violations = exact_china81_score(
        run.completion.solution,
        bundle,
    )
    assert run.pyvrp_feasible
    assert not violations
    assert objective == run.completion.objective
    assert breakdown == run.completion.breakdown
    assert run.stats["shared_completion_schema"] == (
        "resetp.china81-shared-completion.v1"
    )


def test_pyvrp_result_retains_initial_when_proxy_best_fails_full_model(
    monkeypatch,
) -> None:
    bundle, initial = _fixture()
    real_completion = (
        pyvrp_adapter.complete_china81_route_skeleton
    )

    def reject_searched(skeleton, active_bundle):
        if skeleton is initial:
            return real_completion(skeleton, active_bundle)
        raise ValueError("forced complete-model rejection")

    monkeypatch.setattr(
        pyvrp_adapter,
        "complete_china81_route_skeleton",
        reject_searched,
    )
    run = run_pyvrp_hgs_skeleton(
        bundle,
        initial,
        seed=1,
        runtime_seconds=0.05,
    )

    assert run.skeleton is initial
    assert run.stats["selected_source"] == "common_initial_incumbent"
    assert (
        run.stats["searched_complete_model_status"]
        == "INFEASIBLE_OR_ERROR"
    )
    assert run.stats["searched_exact_objective"] is None
    assert "forced complete-model rejection" in (
        run.stats["searched_complete_model_failure"]
    )
    trace = run.stats["complete_candidate_evaluation_trace"]
    assert len(trace) == run.stats["complete_candidate_evaluation_attempts"]
    failed = trace[-1]
    assert len(failed["candidate_id"]) == 64
    assert failed["completion_succeeded"] is False
    assert failed["exception_type"] == "ValueError"
    assert failed["exception_message"] == "forced complete-model rejection"
    assert failed["failure_category"] == PROXY_FOUND_COMPLETION_FAILED


def test_hard_home_depot_lock_is_encoded_in_capacity_dimensions() -> None:
    bundle = load_china81_bundle(
        ROOT,
        "cn-prd-50c-01-V2-LOCATIONS",
    )
    unlocked = build_pyvrp_problem(
        bundle,
        hard_home_depot_lock=False,
    ).model.data()
    locked = build_pyvrp_problem(
        bundle,
        hard_home_depot_lock=True,
    ).model.data()
    depots = list(locked.depots())
    depot_index = {
        depot.name: index
        for index, depot in enumerate(depots)
    }

    assert unlocked.num_load_dimensions == 1
    assert locked.num_load_dimensions == 1 + len(depots)
    for client in locked.clients():
        owner = bundle.customer_home_depot[client.name]
        owner_dimension = 1 + depot_index[owner]
        assert client.delivery[owner_dimension] == 1
        assert sum(client.delivery[1:]) == 1

    for vehicle_type in locked.vehicle_types():
        home_depot = depots[vehicle_type.start_depot].name
        assert vehicle_type.start_depot == vehicle_type.end_depot
        for depot_id, index in depot_index.items():
            capacity = vehicle_type.capacity[1 + index]
            assert (capacity > 0) == (depot_id == home_depot)


def test_strict_multitrip_proxy_encodes_registered_physical_caps() -> None:
    bundle = load_china81_bundle(
        ROOT,
        "cn-prd-50c-01-V2-LOCATIONS",
    )
    mixed = build_pyvrp_problem(
        bundle,
        route_proxy_mode="mechanism_ev",
    ).model.data()
    mixed_types = {item.name: item for item in mixed.vehicle_types()}

    assert set(mixed_types) == {
        "CV@D_guangzhou",
        "EV@D_guangzhou",
        "CV@D_shenzhen",
        "EV@D_shenzhen",
    }
    for depot_id in ("D_guangzhou", "D_shenzhen"):
        assert mixed_types[f"CV@{depot_id}"].num_available == 3
        assert mixed_types[f"EV@{depot_id}"].num_available == 1
        for vehicle_type in ("CV", "EV"):
            item = mixed_types[f"{vehicle_type}@{depot_id}"]
            assert item.reload_depots == [item.start_depot]
            assert item.max_reloads == 49

    cv_only = build_pyvrp_problem(
        bundle,
        route_proxy_mode="cv_only",
    ).model.data()
    cv_types = {item.name: item for item in cv_only.vehicle_types()}
    assert set(cv_types) == {
        "CV@D_guangzhou",
        "CV@D_shenzhen",
    }
    assert all(item.num_available == 4 for item in cv_types.values())


def test_multitrip_projection_and_translation_preserve_trip_boundaries() -> None:
    bundle, initial = _fixture()
    completion = pyvrp_adapter.complete_china81_route_skeleton(
        initial,
        bundle,
    )
    problem = build_pyvrp_problem(bundle)
    projected = _project_initial_solution(
        completion.solution,
        problem.model.data(),
        problem,
        bundle,
    )
    restored = _translate_solution(projected, problem)

    assert projected.num_trips() == len(completion.solution.routes)
    assert len(restored.routes) == projected.num_trips()
    assert len({route.vehicle_id for route in restored.routes}) == len(
        restored.routes
    )
    assert all("#T" in route.vehicle_id for route in restored.routes)


def test_completion_failure_classification_is_message_deterministic() -> None:
    assert _completion_failure_category(
        "China81 route skeleton cannot satisfy the registered physical "
        "fleet caps"
    ) == PROXY_FOUND_COMPLETION_FAILED
    assert _completion_failure_category(
        "SEARCH_NOT_FOUND:no candidate"
    ) == SEARCH_NOT_FOUND
    assert _completion_failure_category(
        "BUSINESS_HARD_INFEASIBLE:capacity contradiction"
    ) == BUSINESS_HARD_INFEASIBLE
