from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from baselines.e7_dynamic import e7_formal_dynamic_value_20260714 as formal
from setp_solver.instance_loader import Instance, Node
from setp_solver.search.dynamic_multitrip_schedule import DynamicAssetState
from setp_solver.search.evaluation import EvalBudget
from setp_solver.solution import Route, Solution


def _asset_aware_fixture() -> tuple[
    formal.gate.StageConstruction,
    dict[str, str],
    object,
    dict[str, DynamicAssetState],
]:
    nodes = [
        Node("D0", "d", 0.0, 0.0, due_time=30_000.0),
        Node("D1", "d", 10.0, 0.0, due_time=30_000.0),
        Node("C0", "c", 1.0, 0.0, demand=10.0, due_time=20_000.0),
        Node("C1", "c", 9.0, 0.0, demand=10.0, due_time=20_000.0),
    ]
    distances = [
        [0.0, 10_000.0, 1_000.0, 9_000.0],
        [10_000.0, 0.0, 9_000.0, 1_000.0],
        [1_000.0, 9_000.0, 0.0, 8_000.0],
        [9_000.0, 1_000.0, 8_000.0, 0.0],
    ]
    instance = Instance(nodes=nodes, distance_matrix=distances, num_cv=2, num_ev=0)
    construction = formal.gate.StageConstruction(
        solution=Solution(
            routes=[
                Route("old-0", "cv", "D1", ["D1", "C0", "D1"]),
                Route("old-1", "cv", "D0", ["D0", "C1", "D0"]),
            ]
        ),
        effective_instance=instance,
        applied_event_ids=(),
        ignored_locked_event_ids=(),
        feasibility_check_count=0,
    )
    owners = {"C0": "D0", "C1": "D1"}
    prices = replace(
        formal.legacy.prices_for("M1", 0.0),
        Q_capacity=100.0,
        B_battery_kwh=280.0,
        initial_ev_battery_kwh=280.0,
    )
    states = {
        "CV_D0_1": DynamicAssetState("CV_D0_1", "cv", "D0", 0.0, 0.0, 1),
        "CV_D1_1": DynamicAssetState("CV_D1_1", "cv", "D1", 0.0, 0.0, 1),
    }
    return construction, owners, prices, states


def _reciprocal_existing_fixture() -> tuple[
    formal.gate.StageConstruction,
    dict[str, str],
    object,
]:
    nodes = [
        Node("D0", "d", 0.0, 0.0, due_time=30_000.0),
        Node("D1", "d", 10.0, 0.0, due_time=30_000.0),
        Node("C0a", "c", 2.0, 0.0, demand=10.0, due_time=20_000.0),
        Node("C0b", "c", 4.0, 0.0, demand=10.0, due_time=20_000.0),
        Node("C1a", "c", 6.0, 0.0, demand=10.0, due_time=20_000.0),
        Node("C1b", "c", 8.0, 0.0, demand=10.0, due_time=20_000.0),
    ]
    distances = [
        [abs(float(left.x) - float(right.x)) * 1_000.0 for right in nodes]
        for left in nodes
    ]
    instance = Instance(nodes=nodes, distance_matrix=distances, num_cv=2, num_ev=0)
    construction = formal.gate.StageConstruction(
        solution=Solution(
            routes=[
                Route("CV_D0_1", "cv", "D0", ["D0", "C0a", "C0b", "D0"]),
                Route("CV_D1_1", "cv", "D1", ["D1", "C1a", "C1b", "D1"]),
            ]
        ),
        effective_instance=instance,
        applied_event_ids=(),
        ignored_locked_event_ids=(),
        feasibility_check_count=0,
    )
    owners = {"C0a": "D0", "C0b": "D0", "C1a": "D1", "C1b": "D1"}
    prices = replace(
        formal.legacy.prices_for("M1", 0.0),
        Q_capacity=100.0,
        B_battery_kwh=280.0,
        initial_ev_battery_kwh=280.0,
    )
    return construction, owners, prices


def test_asset_aware_repack_is_deterministic() -> None:
    construction, owners, prices, states = _asset_aware_fixture()
    first = formal.asset_aware_future_repack_candidate(
        construction,
        owners,
        prices,
        asset_states=states,
        stage_start_second=1_000.0,
        allow_cross_depot=False,
    )
    second = formal.asset_aware_future_repack_candidate(
        construction,
        owners,
        prices,
        asset_states=states,
        stage_start_second=1_000.0,
        allow_cross_depot=False,
    )
    assert first == second


def test_asset_aware_repack_independent_stays_home() -> None:
    construction, owners, prices, states = _asset_aware_fixture()
    first = formal.asset_aware_future_repack_candidate(
        construction,
        owners,
        prices,
        asset_states=states,
        stage_start_second=1_000.0,
        allow_cross_depot=False,
    )
    assert first is not None
    for route in first.routes:
        for customer_id in formal.p2.route_customers(route, construction.effective_instance):
            assert route.home_depot_id == owners[customer_id]
    assert first.cross_site_services == []


def test_asset_aware_repack_preserves_customers_and_route_feasibility() -> None:
    construction, owners, prices, states = _asset_aware_fixture()
    candidate = formal.asset_aware_future_repack_candidate(
        construction,
        owners,
        prices,
        asset_states=states,
        stage_start_second=1_000.0,
        allow_cross_depot=False,
    )
    assert candidate is not None
    customers = [
        customer_id
        for route in candidate.routes
        for customer_id in formal.p2.route_customers(route, construction.effective_instance)
    ]
    assert sorted(customers) == ["C0", "C1"]
    assert len(customers) == len(set(customers))
    for route in candidate.routes:
        assert formal.gate._route_load(route, construction.effective_instance) <= prices.Q_capacity
        formal.gate.route_timing(route, construction.effective_instance, prices)


def test_specialist_complete_candidate_has_one_budget_record_and_one_exact_check() -> None:
    context = SimpleNamespace(
        budget=EvalBudget(limit=1, target=1),
        score_counts={},
    )
    candidate = Solution(routes=[])
    calls: list[Solution] = []

    def exact_evaluator(solution: Solution) -> tuple[Solution, object, float]:
        calls.append(solution)
        return solution, object(), 1.0

    result, error = formal._evaluate_specialist_candidate_once(
        context,
        candidate,
        exact_evaluator,
    )
    assert error is None
    assert result is not None
    assert context.budget.count == 1
    assert context.score_counts == {"candidate": 1}
    assert calls == [candidate]


def test_missing_specialist_candidate_still_counts_budget_without_exact_check() -> None:
    context = SimpleNamespace(
        budget=EvalBudget(limit=1, target=1),
        score_counts={},
    )
    calls: list[Solution] = []

    def exact_evaluator(solution: Solution) -> tuple[Solution, object, float]:
        calls.append(solution)
        return solution, object(), 1.0

    result, error = formal._evaluate_specialist_candidate_once(
        context,
        None,
        exact_evaluator,
    )
    assert result is None
    assert error is None
    assert context.budget.count == 1
    assert context.score_counts == {"candidate": 1}
    assert calls == []


def test_existing_customer_cross_schedule_preserves_new_order_priority() -> None:
    assert formal.existing_customer_cross_slots(50, 0) == (1,)
    assert formal.existing_customer_cross_slots(50, 2) == (5,)
    assert formal.existing_customer_cross_slots(250, 6) == (7, 107, 207)


def test_existing_customer_pair_excludes_new_orders_and_reuses_both_arms() -> None:
    construction, owners, prices = _reciprocal_existing_fixture()
    cooperative, cooperative_evidence = formal.existing_customer_reciprocal_candidate(
        construction.solution,
        construction.effective_instance,
        owners,
        prices,
        [],
        stage_new_customer_ids=("C0b",),
        allow_cross_depot=True,
        rng=np.random.default_rng(17),
    )
    independent, independent_evidence = formal.existing_customer_reciprocal_candidate(
        construction.solution,
        construction.effective_instance,
        owners,
        prices,
        [],
        stage_new_customer_ids=("C0b",),
        allow_cross_depot=False,
        rng=np.random.default_rng(17),
    )

    assert cooperative is not None
    assert independent is not None
    assert cooperative_evidence["removed_customer_ids"] == independent_evidence[
        "removed_customer_ids"
    ]
    assert "C0b" not in cooperative_evidence["removed_customer_ids"]
    assert cooperative_evidence["forced_insertion_count"] == 2
    assert cooperative_evidence["candidate_changed"] is True
    assert independent_evidence["within_depot_reinserted"] is True
    assert independent_evidence["candidate_changed"] is True

    cooperative_cross = formal._cross_site_ids_for_routes(
        cooperative.routes,
        construction.effective_instance,
        owners,
    )
    assert set(cooperative_cross) == set(cooperative_evidence["removed_customer_ids"])
    assert formal._cross_site_ids_for_routes(
        independent.routes,
        construction.effective_instance,
        owners,
    ) == []
    for candidate in (cooperative, independent):
        customers = [
            customer_id
            for route in candidate.routes
            for customer_id in formal.p2.route_customers(
                route,
                construction.effective_instance,
            )
        ]
        assert sorted(customers) == sorted(owners)
        assert len(customers) == len(set(customers))


@pytest.mark.parametrize("allow_cross_depot", [False, True])
def test_existing_customer_candidate_uses_common_dynamic_check_and_gate(
    monkeypatch,
    allow_cross_depot: bool,
) -> None:
    construction, owners, prices = _reciprocal_existing_fixture()
    certificate = SimpleNamespace(status="PASS")
    monkeypatch.setattr(
        formal.gate,
        "prepare_stage_with_singleton_type_choices",
        lambda *args, **kwargs: (construction.solution, certificate, 0),
    )
    monkeypatch.setattr(
        formal,
        "evaluate_parts",
        lambda *args, **kwargs: {"total_cost": 100.0},
    )
    exact_calls: list[Solution] = []
    gate_calls: list[Solution] = []

    def exact(candidate: Solution, *args: object) -> tuple[Solution, object, float]:
        exact_calls.append(candidate)
        return candidate, certificate, 90.0

    def candidate_gate(candidate: Solution, *_args: object) -> bool:
        gate_calls.append(candidate)
        return True

    monkeypatch.setattr(formal, "exact_candidate", exact)
    result = formal.search_stage(
        construction,
        {"prices": prices, "bundle": SimpleNamespace(carbon_profile=[])},
        SimpleNamespace(asset_states={}, locked_charging_actions=()),
        owners,
        set(),
        trigger=0.0,
        seed=19,
        evaluations=1,
        allow_cross_depot=allow_cross_depot,
        stage_new_customer_ids=(),
        candidate_best_gate=candidate_gate,
    )

    assert len(exact_calls) == 1
    assert len(gate_calls) == 1
    assert result["evaluations"] == 1
    assert result["existing_cross_scheduled_slots"] == [1]
    assert result["existing_cross_actual_call_count"] == 1
    assert result["existing_cross_candidate_build_count"] == 1
    assert result["existing_cross_changed_candidate_count"] == 1
    assert result["existing_cross_dynamic_feasible_count"] == 1
    assert result["existing_cross_best_improved_count"] == 1
    if allow_cross_depot:
        assert result["existing_cross_forced_insertion_count"] == 2
        assert result["existing_cross_within_depot_reinsert_count"] == 0
        assert len(result["existing_cross_moved_customer_ids"]) == 2
    else:
        assert result["existing_cross_forced_insertion_count"] == 0
        assert result["existing_cross_within_depot_reinsert_count"] == 1
        assert result["existing_cross_moved_customer_ids"] == []


def test_existing_customer_candidate_cannot_become_best_when_gate_rejects(
    monkeypatch,
) -> None:
    construction, owners, prices = _reciprocal_existing_fixture()
    certificate = SimpleNamespace(status="PASS")
    monkeypatch.setattr(
        formal.gate,
        "prepare_stage_with_singleton_type_choices",
        lambda *args, **kwargs: (construction.solution, certificate, 0),
    )
    monkeypatch.setattr(
        formal,
        "evaluate_parts",
        lambda *args, **kwargs: {"total_cost": 100.0},
    )
    monkeypatch.setattr(
        formal,
        "exact_candidate",
        lambda candidate, *args: (candidate, certificate, 90.0),
    )
    result = formal.search_stage(
        construction,
        {"prices": prices, "bundle": SimpleNamespace(carbon_profile=[])},
        SimpleNamespace(asset_states={}, locked_charging_actions=()),
        owners,
        set(),
        trigger=0.0,
        seed=23,
        evaluations=1,
        allow_cross_depot=True,
        stage_new_customer_ids=(),
        candidate_best_gate=lambda *_args: False,
    )

    assert result["future_cost"] == 100.0
    assert result["existing_cross_gate_rejection_count"] == 1
    assert result["existing_cross_best_improved_count"] == 0


def test_existing_customer_candidate_keeps_dynamic_rejection(monkeypatch) -> None:
    construction, owners, prices = _reciprocal_existing_fixture()
    certificate = SimpleNamespace(status="PASS")
    monkeypatch.setattr(
        formal.gate,
        "prepare_stage_with_singleton_type_choices",
        lambda *args, **kwargs: (construction.solution, certificate, 0),
    )
    monkeypatch.setattr(
        formal,
        "evaluate_parts",
        lambda *args, **kwargs: {"total_cost": 100.0},
    )

    def reject(*_args: object) -> tuple[Solution, object, float]:
        raise ValueError("inherited battery conflict")

    monkeypatch.setattr(formal, "exact_candidate", reject)
    result = formal.search_stage(
        construction,
        {"prices": prices, "bundle": SimpleNamespace(carbon_profile=[])},
        SimpleNamespace(asset_states={}, locked_charging_actions=()),
        owners,
        set(),
        trigger=0.0,
        seed=29,
        evaluations=1,
        allow_cross_depot=True,
        stage_new_customer_ids=(),
    )

    assert result["future_cost"] == 100.0
    assert result["existing_cross_dynamic_feasible_count"] == 0
    assert result["existing_cross_rejections"] == {"inherited battery conflict": 1}
    assert result["dynamic_rejections"] == {"inherited battery conflict": 1}


def test_event_insertion_splits_shared_source_into_unique_singletons() -> None:
    construction, _, prices, _ = _asset_aware_fixture()
    prices = replace(prices, Q_capacity=15.0)
    event_construction = formal.gate.StageConstruction(
        solution=Solution(
            routes=[
                Route("EVENT_ADD_1", "cv", "D0", ["D0", "C0", "D0"]),
                Route("EVENT_ADD_2", "cv", "D0", ["D0", "C1", "D0"]),
            ]
        ),
        effective_instance=construction.effective_instance,
        applied_event_ids=(),
        ignored_locked_event_ids=(),
        feasibility_check_count=0,
    )
    base = Solution(
        routes=[Route("DYN_OPEN_001", "cv", "D0", ["D0", "C0", "C1", "D0"])]
    )

    candidate = formal.event_insertion_candidate(
        event_construction,
        {"C0": "D0", "C1": "D0"},
        prices,
        base,
        True,
        allow_cross_depot=False,
        rng=np.random.default_rng(7),
    )

    assert candidate is not None
    assert len({route.vehicle_id for route in candidate.routes}) == len(candidate.routes)
    customers = [
        customer_id
        for route in candidate.routes
        for customer_id in formal.p2.route_customers(
            route,
            event_construction.effective_instance,
        )
    ]
    assert sorted(customers) == ["C0", "C1"]
    assert len(customers) == len(set(customers))


def test_event_insertion_uses_explicit_customer_identity_after_route_renaming() -> None:
    construction, owners, prices, _ = _asset_aware_fixture()
    renamed = replace(
        construction,
        solution=Solution(
            routes=[
                Route("DYN_OPEN_001", "cv", "D1", ["D1", "C0", "D1"]),
                Route("DYN_OPEN_002", "cv", "D0", ["D0", "C1", "D0"]),
            ]
        ),
    )

    candidate = formal.event_insertion_candidate(
        renamed,
        owners,
        prices,
        renamed.solution,
        True,
        stage_new_customer_ids=("C0",),
        allow_cross_depot=True,
        rng=np.random.default_rng(11),
    )

    assert candidate is not None
    customers = [
        customer_id
        for route in candidate.routes
        for customer_id in formal.p2.route_customers(
            route,
            renamed.effective_instance,
        )
    ]
    assert sorted(customers) == ["C0", "C1"]
    assert len(customers) == len(set(customers))


def test_forced_event_insertion_moves_selected_customer_to_other_depot() -> None:
    construction, owners, prices, _ = _asset_aware_fixture()
    owner_fixed = replace(
        construction,
        solution=Solution(
            routes=[
                Route("DYN_OPEN_001", "cv", "D0", ["D0", "C0", "D0"]),
                Route("DYN_OPEN_002", "cv", "D1", ["D1", "C1", "D1"]),
            ]
        ),
    )

    candidate = formal.event_insertion_candidate(
        owner_fixed,
        owners,
        prices,
        owner_fixed.solution,
        True,
        stage_new_customer_ids=("C0",),
        allow_cross_depot=True,
        rng=np.random.default_rng(5),
        force_cross_depot=True,
        deterministic_choice_index=0,
    )

    assert candidate is not None
    serving_routes = [
            route
            for route in candidate.routes
            if "C0" in formal.p2.route_customers(
                route,
                owner_fixed.effective_instance,
            )
    ]
    assert len(serving_routes) == 1
    assert serving_routes[0].home_depot_id == "D1"


def test_event_insertion_updates_only_the_selected_route() -> None:
    class FixedRng:
        @staticmethod
        def permutation(size: int) -> np.ndarray:
            return np.arange(size)

        @staticmethod
        def random() -> float:
            return 0.9

        @staticmethod
        def integers(_low: int, _high: int | None = None) -> int:
            return 0

    construction, _, prices, _ = _asset_aware_fixture()
    prices = replace(prices, Q_capacity=25.0)
    event_construction = formal.gate.StageConstruction(
        solution=Solution(
            routes=[
                Route("EVENT_ADD_1", "cv", "D0", ["D0", "C0", "D0"]),
                Route("EVENT_ADD_2", "cv", "D0", ["D0", "C1", "D0"]),
            ]
        ),
        effective_instance=construction.effective_instance,
        applied_event_ids=(),
        ignored_locked_event_ids=(),
        feasibility_check_count=0,
    )
    base = Solution(
        routes=[Route("DYN_OPEN_001", "cv", "D0", ["D0", "C0", "C1", "D0"])]
    )

    candidate = formal.event_insertion_candidate(
        event_construction,
        {"C0": "D0", "C1": "D0"},
        prices,
        base,
        True,
        allow_cross_depot=False,
        rng=FixedRng(),
    )

    assert candidate is not None
    assert len(candidate.routes) == 1
    assert len({route.vehicle_id for route in candidate.routes}) == 1
    customers = [
        customer_id
        for route in candidate.routes
        for customer_id in formal.p2.route_customers(
            route,
            event_construction.effective_instance,
        )
    ]
    assert sorted(customers) == ["C0", "C1"]
    assert len(customers) == len(set(customers))


def test_prepared_solution_becomes_clean_next_search_structure() -> None:
    construction, owners, _, _ = _asset_aware_fixture()
    prepared = Solution(
        routes=[
            Route("CV_D0_1#T3", "cv", "D0", ["D0", "C0", "D0"]),
            Route("CV_D1_1#T2", "cv", "D1", ["D1", "C1", "D1"]),
        ],
        charging_actions=[formal.ChargingAction("EV_D0_1#T2", "D0", 10.0, 30.0, 100.0)],
    )

    normalized = formal.normalized_search_solution(
        prepared,
        construction.effective_instance,
        owners,
    )

    assert [route.vehicle_id for route in normalized.routes] == [
        "DYN_OPEN_001",
        "DYN_OPEN_002",
    ]
    assert normalized.charging_actions == []
    assert len({route.vehicle_id for route in normalized.routes}) == len(normalized.routes)


def test_frozen_stream_and_batched_trigger_contract() -> None:
    events, owners, event_path, owner_path = formal.load_stream(1)

    ordered = sorted(events, key=lambda item: (float(item.t_appear), str(item.event_id)))
    assert len(events) == 55
    assert events == ordered
    assert len({event.event_id for event in events}) == len(events)
    assert len(owners) == 243
    assert formal.sha256(event_path) == "ae08f81e5b8efd93b6c2d95abc405623ae355926c4c23fd31681c0fa8824d6a9"
    assert formal.sha256(owner_path) == "66a6b7211192e69725d6fa76a3c747e8a855744570f9389229ca24fa804eebe1"
    assert [len(formal._validated_trigger_batches(seed, formal.load_stream(seed)[0])) for seed in range(1, 6)] == [7, 8, 7, 7, 7]
    for seed in range(1, 6):
        batches = formal._validated_trigger_batches(seed, formal.load_stream(seed)[0])
        observed = {
            event.event_id: float(batch["trigger_time"])
            for batch in batches
            for event in batch["events"]
        }
        assert observed == formal._frozen_trigger_times(seed)


def test_stage_application_partitions_applied_and_locked_events() -> None:
    events = formal.load_stream(1)[0][:2]
    valid = formal.gate.StageConstruction(None, None, tuple(event.event_id for event in events), (), 0)
    assert formal._validate_stage_application(valid, events)[0] == [event.event_id for event in events]

    cancellable = next(event for event in formal.load_stream(1)[0] if event.event_type == "cancel")
    locked = formal.gate.StageConstruction(None, None, (), (cancellable.event_id,), 0)
    assert formal._validate_stage_application(locked, [cancellable])[3] == [cancellable.event_id]

    added = next(event for event in formal.load_stream(1)[0] if event.event_type == "add")
    invalid_locked = formal.gate.StageConstruction(None, None, (), (added.event_id,), 0)
    with pytest.raises(RuntimeError, match="must never be ignored"):
        formal._validate_stage_application(invalid_locked, [added])

    mismatched = formal.gate.StageConstruction(None, None, (events[0].event_id,), (), 0)
    with pytest.raises(RuntimeError, match="do not partition"):
        formal._validate_stage_application(mismatched, events)


def test_stage_timing_gate_and_final_stage_exemption() -> None:
    assert formal._stage_timing(9.0, 10.0, 20.0) == (10.0, True)
    assert formal._stage_timing(11.0, 10.0, 20.0) == (10.0, False)
    assert formal._stage_timing(999.0, 10.0, None) == (None, None)


def test_cli_defaults_to_batched_and_accepts_eight_workers(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["e7"])
    defaults = formal.parse_args()
    assert defaults.trigger_mode == "batched"
    assert defaults.workers == 2

    monkeypatch.setattr(sys, "argv", ["e7", "--workers", "8"])
    args = formal.parse_args()
    assert args.trigger_mode == "batched"
    assert args.workers == 8


def test_both_arms_load_the_same_frozen_independent_start() -> None:
    cooperative = formal.load_arm("cooperative")
    independent = formal.load_arm("independent")
    assert cooperative["case"] == independent["case"]
    assert cooperative["case"].endswith("__independent")
    assert formal.sha256(cooperative["solution_path"]) == formal.sha256(
        independent["solution_path"]
    )
    assert formal.sha256(cooperative["certificate_path"]) == formal.sha256(
        independent["certificate_path"]
    )
    assert cooperative["solution"].cross_site_services == []


def test_common_operator_menu_does_not_change_with_strict_environment(monkeypatch) -> None:
    baseline = formal.common_operator_pairs()
    monkeypatch.setenv("SETP_E3_STRICT_MULTITRIP", "1")
    assert formal.common_operator_pairs() == baseline
    assert len(baseline) == 18


def test_paired_contract_rejects_different_start_hashes() -> None:
    cooperative = {
        "initial_solution_sha256": "same-solution",
        "initial_certificate_sha256": "same-certificate",
        "event_sha256": "same-events",
        "owner_sha256": "same-owners",
    }
    independent = dict(cooperative)
    stages = [
        {
            "stage": 1,
            "stage_search_seed": 1001,
            "evaluations": 8,
            "operator_pairs": "a+b",
        }
    ]
    assert formal.paired_contract_matches(cooperative, independent, stages, stages)
    independent["initial_solution_sha256"] = "different"
    assert not formal.paired_contract_matches(cooperative, independent, stages, stages)


def test_paired_contract_rejects_different_existing_customer_call_schedules() -> None:
    session = {
        "initial_solution_sha256": "same-solution",
        "initial_certificate_sha256": "same-certificate",
        "event_sha256": "same-events",
        "owner_sha256": "same-owners",
    }
    cooperative_stages = [
        {
            "stage": 1,
            "stage_search_seed": 1001,
            "evaluations": 50,
            "operator_pairs": "a+b",
            "existing_cross_operator_id": formal.EXISTING_CROSS_OPERATOR_ID,
            "existing_cross_scheduled_slots": "5",
            "existing_cross_scheduled_call_count": 1,
            "existing_cross_actual_call_count": 1,
        }
    ]
    independent_stages = [dict(cooperative_stages[0])]
    assert formal.paired_contract_matches(
        session,
        session,
        cooperative_stages,
        independent_stages,
    )
    independent_stages[0]["existing_cross_scheduled_slots"] = "6"
    assert not formal.paired_contract_matches(
        session,
        session,
        cooperative_stages,
        independent_stages,
    )


def test_stage_evidence_round_trip_contains_asset_and_customer_hashes() -> None:
    construction, owners, _, states = _asset_aware_fixture()
    solution = construction.solution
    certificate = SimpleNamespace(
        as_dict=lambda: {
            "status": "PASS",
            "vehicle_counts": {"cv": 2, "ev": 0},
            "trips": [],
        }
    )
    cut = SimpleNamespace(
        asset_states=states,
        completed_route_ids=("old-0",),
        in_progress_route_ids=(),
        editable_route_ids=("old-1",),
        locked_charging_actions=(),
    )
    payload = formal._stage_evidence_payload(
        arm="independent",
        stream_seed=1,
        stage_index=1,
        trigger=1000.0,
        cut=cut,
        locked_routes=solution.routes[:1],
        committed_customers={"C0"},
        future_customers=["C1"],
        active_customers={"C0", "C1"},
        solution=solution,
        certificate=certificate,
        cost_parts={"total_cost": 1.0, "E_total": 2.0},
        dynamic_added_customer_ids=set(),
        dynamic_added_cross_site_ids=set(),
    )
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    restored = json.loads(encoded)
    assert len(restored["asset_states"]) == 2
    assert restored["active_customer_ids"] == ["C0", "C1"]
    assert restored["certificate_status"] == "PASS"
    assert restored["asset_states_sha256"] == formal.canonical_sha256(
        restored["asset_states"]
    )


def test_failed_run_keeps_completed_stages_and_a_halt_record(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(formal, "ROOT", tmp_path)
    monkeypatch.setattr(formal, "source_commit", lambda: "test-commit")
    args = argparse.Namespace(
        streams=[1],
        evaluations=400,
        max_stages=13,
        all_stages=False,
        trigger_mode="batched",
        workers=1,
    )
    stage = {
        "arm": "cooperative",
        "stream_seed": 1,
        "stage": 1,
        "customer_accounting_pass": True,
        "next_trigger_second": None,
        "completed_before_next_trigger": None,
    }
    failure = {
        "stream_seed": 1,
        "arm": "cooperative",
        "completed_stage_count": 1,
        "error_type": "RuntimeError",
        "error": "deliberate test stop",
    }

    formal.write_artifacts(
        tmp_path,
        [],
        args,
        failures=[failure],
        partial_stage_rows=[stage],
        run_start_commit="test-commit",
    )

    decision = json.loads((tmp_path / "decision.json").read_text(encoding="utf-8"))
    assert decision["verdict"] == "HALT_E7_PAIRED_DYNAMIC_VALUE"
    assert decision["failure_count"] == 1
    with (tmp_path / "raw_runs.csv").open(newline="", encoding="utf-8") as handle:
        assert list(csv.DictReader(handle))[0]["stage"] == "1"
    with (tmp_path / "failures.csv").open(newline="", encoding="utf-8") as handle:
        assert list(csv.DictReader(handle))[0]["error"] == "deliberate test stop"
