from __future__ import annotations

import random

import pytest
import hybrid_orchestrator as orchestration
import run_g0_real_bundle_preflight as real_bundle_gate

from setp_solver.instance_loader import Instance, Node
from setp_solver.solution import ChargingAction, Route, Solution

from contracts import (
    AlgorithmArm,
    CandidateSource,
    CompleteEvaluationLedger,
    DecoderCacheKey,
    HybridLineageLedger,
    TransferDirection,
)
from decoder_labels import DecoderLabel, DominanceFrontier, dominates
from decoder_cache import (
    CachedRouteLocalResult,
    RouteLocalDecoderCache,
)
from evaluation import BudgetedCompleteEvaluator, ScoredCandidate
from fleet_assignment_dp import (
    AssignmentOption,
    solve_finite_fleet_assignment_dp,
)
from hybrid_orchestrator import (
    CooperativeConfig,
    HgsEpochResult,
    make_arm_budget_plan,
)
from operator_plans import (
    OperatorKind,
    bidirectional_cross_depot_segment_plan,
    charge_departure_retiming_plan,
    cross_depot_route_reassignment_plan,
    dynamic_unexecuted_tail_plan,
    time_window_pressure_string_plan,
    vehicle_type_flip_plan,
)
from operator_effects import verify_operator_effect
from reference_decoder import (
    RouteAssignment,
    decode_explicit_assignments,
)
from recreate import (
    recreate_removed_customers,
    remove_customers_from_skeleton,
)
from rr_engine import (
    RrConfig,
    RrRunResult,
    _accept_candidate,
    _bidirectional_exchange_skeleton,
    _temperature,
    _whole_route_reassignment_skeleton,
)


def _solution() -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id="CV1",
                vehicle_type="cv",
                home_depot_id="D_GZ",
                node_sequence=[
                    "D_GZ",
                    "C1",
                    "C2",
                    "C3",
                    "D_GZ",
                ],
            ),
            Route(
                vehicle_id="EV1",
                vehicle_type="ev",
                home_depot_id="D_SZ",
                node_sequence=[
                    "D_SZ",
                    "C4",
                    "C5",
                    "C6",
                    "D_SZ",
                ],
            ),
        ]
    )


def _instance() -> Instance:
    nodes = [
        Node("D_GZ", "d", 0, 0, 0, 0, 100, 0),
        Node("D_SZ", "d", 1, 1, 0, 0, 100, 0),
        Node("C1", "c", 0, 1, 1, 0, 80, 1),
        Node("C2", "c", 0, 2, 1, 10, 20, 1),
        Node("C3", "c", 0, 3, 1, 0, 70, 1),
        Node("C4", "c", 1, 2, 1, 0, 60, 1),
        Node("C5", "c", 1, 3, 1, 0, 50, 1),
        Node("C6", "c", 1, 4, 1, 0, 40, 1),
    ]
    size = len(nodes)
    matrix = [
        [0.0 if i == j else float(abs(i - j) + 1) for j in range(size)]
        for i in range(size)
    ]
    return Instance(nodes=nodes, distance_matrix=matrix)


def _customer_ids() -> frozenset[str]:
    return frozenset(
        node.node_id for node in _instance().nodes if node.node_type.lower() == "c"
    )


def test_budget_counts_infeasible_and_duplicate_candidates() -> None:
    ledger = CompleteEvaluationLedger(
        arm=AlgorithmArm.COOPERATIVE,
        limit=3,
    )
    ledger.register(
        signature="a",
        source=CandidateSource.HGS_ARCHIVE,
        feasible=True,
        objective=10.0,
        violation_count=0,
    )
    duplicate = ledger.register(
        signature="a",
        source=CandidateSource.RUIN_RECREATE,
        feasible=True,
        objective=10.0,
        violation_count=0,
    )
    ledger.register(
        signature="b",
        source=CandidateSource.RUIN_RECREATE,
        feasible=False,
        objective=None,
        violation_count=1,
    )
    assert duplicate.duplicate_of_index == 1
    assert ledger.consumed == 3
    ledger.assert_exactly_closed()
    with pytest.raises(RuntimeError):
        ledger.register(
            signature="c",
            source=CandidateSource.HGS_DESCENDANT,
            feasible=True,
            objective=9.0,
            violation_count=0,
        )


def test_lineage_rejects_final_selection_pseudohybrid() -> None:
    lineage = HybridLineageLedger()
    lineage.add_transfer(
        direction=TransferDirection.HGS_TO_RR,
        parent_signature="hgs0",
        child_signature="rr0",
        parent_objective=100.0,
        child_objective=99.0,
        complete_evaluation_index=10,
        accepted_into_next_hgs_epoch=False,
        next_hgs_epoch=None,
    )
    with pytest.raises(RuntimeError, match="missing RR-to-HGS"):
        lineage.assert_genuine_cooperation()


def test_lineage_accepts_bidirectional_post_injection_gain() -> None:
    lineage = HybridLineageLedger()
    lineage.add_transfer(
        direction=TransferDirection.HGS_TO_RR,
        parent_signature="hgs0",
        child_signature="rr0",
        parent_objective=100.0,
        child_objective=99.0,
        complete_evaluation_index=10,
        accepted_into_next_hgs_epoch=False,
        next_hgs_epoch=None,
    )
    lineage.add_transfer(
        direction=TransferDirection.RR_TO_HGS,
        parent_signature="hgs0",
        child_signature="rr0",
        parent_objective=100.0,
        child_objective=99.0,
        complete_evaluation_index=11,
        accepted_into_next_hgs_epoch=True,
        next_hgs_epoch=2,
    )
    lineage.add_hgs_descendant(
        epoch=2,
        injected_rr_signature="rr0",
        descendant_signature="hgs1",
        injected_objective=99.0,
        descendant_objective=98.0,
        complete_evaluation_index=20,
    )
    lineage.assert_genuine_cooperation()
    assert lineage.cooperative_gain_evidence_count() == 1


def test_hgs_to_rr_handoff_may_keep_the_same_signature() -> None:
    lineage = HybridLineageLedger()
    transfer = lineage.add_transfer(
        direction=TransferDirection.HGS_TO_RR,
        parent_signature="hgs0",
        child_signature="hgs0",
        parent_objective=100.0,
        child_objective=100.0,
        complete_evaluation_index=8,
        accepted_into_next_hgs_epoch=False,
        next_hgs_epoch=None,
    )
    assert transfer.parent_signature == transfer.child_signature


@pytest.mark.parametrize(
    ("total", "expected_hgs", "expected_rr"),
    [
        (80, (16, 16, 16), (16, 15)),
        (280, (56, 56, 56), (56, 55)),
    ],
)
def test_cooperative_budget_split_closes_exactly(
    total,
    expected_hgs,
    expected_rr,
) -> None:
    plan = make_arm_budget_plan(
        AlgorithmArm.COOPERATIVE,
        total,
    )
    assert plan.hgs_epoch_evaluations == expected_hgs
    assert plan.rr_phase_evaluations == expected_rr
    assert (
        plan.initial_evaluations
        + sum(plan.hgs_epoch_evaluations)
        + sum(plan.rr_phase_evaluations)
        == total
    )


def test_cooperative_orchestrator_requires_real_two_way_gain(
    monkeypatch,
) -> None:
    solutions = [
        Solution(
            routes=[
                Route(
                    vehicle_id=f"CV{index}",
                    vehicle_type="cv",
                    home_depot_id="D_GZ",
                    node_sequence=[
                        "D_GZ",
                        *order,
                        "D_GZ",
                    ],
                )
            ]
        )
        for index, order in enumerate(
            [
                ("C1", "C2", "C3"),
                ("C1", "C3", "C2"),
                ("C2", "C1", "C3"),
                ("C2", "C3", "C1"),
                ("C3", "C1", "C2"),
                ("C3", "C2", "C1"),
            ],
            start=1,
        )
    ]
    objectives = iter([100.0, 99.0, 98.0, 97.0, 96.0])

    def fake_initial(bundle, initial_solution, ledger):
        record = ledger.register(
            signature="initial",
            source=CandidateSource.SHARED_INITIAL,
            feasible=True,
            objective=110.0,
            violation_count=0,
        )
        return ScoredCandidate(
            initial_solution,
            110.0,
            {},
            (),
            record,
        )

    hgs_calls = 0

    def fake_hgs_epoch(
        bundle,
        *,
        epoch,
        ledger,
        candidate_source,
        evaluation_allowance,
        **kwargs,
    ):
        nonlocal hgs_calls
        assert evaluation_allowance == 1
        solution = solutions[hgs_calls + 1]
        objective = next(objectives)
        record = ledger.register(
            signature=orchestration.solution_signature_hash(solution),
            source=candidate_source,
            feasible=True,
            objective=objective,
            violation_count=0,
        )
        scored = ScoredCandidate(
            solution,
            objective,
            {},
            (),
            record,
        )
        hgs_calls += 2
        return HgsEpochResult(
            epoch=epoch,
            best_generated=scored,
            best_novel_generated=scored,
            archives=(),
            evaluated_candidates=1,
            feasible_candidates=1,
            unique_candidate_signatures=1,
            duplicate_evaluations=0,
            padding_rechecks=0,
            elapsed_seconds=0.0,
            decode_failures=(),
        )

    rr_calls = 0

    def fake_rr(
        bundle,
        initial_solution,
        *,
        ledger,
        max_additional_evaluations,
        **kwargs,
    ):
        nonlocal rr_calls
        assert max_additional_evaluations == 1
        solution = solutions[2 if rr_calls == 0 else 4]
        objective = next(objectives)
        record = ledger.register(
            signature=orchestration.solution_signature_hash(solution),
            source=CandidateSource.RUIN_RECREATE,
            feasible=True,
            objective=objective,
            violation_count=0,
        )
        rr_calls += 1
        return RrRunResult(
            best_solution=solution,
            best_objective=objective,
            current_solution=solution,
            current_objective=objective,
            best_generated_solution=solution,
            best_generated_objective=objective,
            best_generated_record_index=record.index,
            trace=(),
            elapsed_seconds=0.0,
            stop_reason="PHASE_EVALUATION_ALLOWANCE",
            operator_attempts={},
            operator_accepted={},
            operator_best_improvements={},
            route_local_cache_stats={},
        )

    monkeypatch.setattr(
        orchestration,
        "_score_initial",
        fake_initial,
    )
    monkeypatch.setattr(
        orchestration,
        "_run_hgs_epoch",
        fake_hgs_epoch,
    )
    monkeypatch.setattr(
        orchestration,
        "run_mechanism_aware_rr",
        fake_rr,
    )
    result = orchestration.run_cooperative_arm(
        bundle=object(),
        initial_solution=solutions[0],
        seed=1,
        config=CooperativeConfig(
            complete_evaluation_budget=6,
            hgs_iterations_for_a=3,
            hgs_wallclock_safety_seconds_per_mode=1.0,
        ),
    )
    assert result.best_objective == 96.0
    assert result.ledger.consumed == 6
    assert result.lineage.cooperative_gain_evidence_count() == 2


def test_cache_key_changes_across_city_date_and_dynamic_state() -> None:
    base = dict(
        instance_id="cn-prd-50c-01",
        date="2025-02-12",
        region="prd",
        city="guangzhou",
        price_area_id="guangdong_prd_five_city",
        carbon_source_column="Guangdong",
        diesel_zone="guangdong",
        home_depot_id="D_GZ",
        vehicle_type="ev",
        charge_strategy="integrated",
        carbon_weight=1.0,
        node_sequence=("D_GZ", "C1", "D_GZ"),
        dynamic_state_hash="state-a",
        runtime_parameter_authority="runtime-v4",
        fleet_authority="fleet-v1",
    )
    first = DecoderCacheKey(**base)
    assert (
        first.digest() != DecoderCacheKey(**{**base, "home_depot_id": "D_SZ"}).digest()
    )
    assert first.digest() != DecoderCacheKey(**{**base, "date": "2025-02-13"}).digest()
    assert (
        first.digest()
        != DecoderCacheKey(**{**base, "dynamic_state_hash": "state-b"}).digest()
    )
    assert (
        first.digest()
        != DecoderCacheKey(**{**base, "price_area_id": "shenzhen"}).digest()
    )
    assert (
        first.digest()
        != DecoderCacheKey(**{**base, "charge_strategy": "legacy"}).digest()
    )
    assert first.digest() != DecoderCacheKey(**{**base, "carbon_weight": 0.0}).digest()


def test_route_local_cache_is_visible_and_fail_closed() -> None:
    key = DecoderCacheKey(
        instance_id="cn-prd-50c-01",
        date="2025-02-12",
        region="prd",
        city="shenzhen",
        price_area_id="shenzhen",
        carbon_source_column="Guangdong",
        diesel_zone="guangdong",
        home_depot_id="D_SZ",
        vehicle_type="ev",
        charge_strategy="integrated",
        carbon_weight=1.0,
        node_sequence=("D_SZ", "C1", "D_SZ"),
        dynamic_state_hash="static",
        runtime_parameter_authority="runtime-v4",
        fleet_authority="fleet-v1",
    )
    cache = RouteLocalDecoderCache()
    assert cache.get(key) is None
    cache.put(
        key,
        CachedRouteLocalResult(
            feasible=True,
            route_local_cost=12.5,
        ),
    )
    assert cache.get(key).route_local_cost == 12.5
    assert cache.as_dict() == {
        "entries": 1,
        "hits": 1,
        "misses": 1,
        "requests": 2,
        "hit_rate": 0.5,
    }


def test_all_six_problem_specific_operator_plans_are_distinct() -> None:
    solution = _solution()
    instance = _instance()
    plans = [
        cross_depot_route_reassignment_plan(
            solution,
            route_index=0,
            depot_ids=("D_GZ", "D_SZ"),
            customer_ids=_customer_ids(),
        ),
        bidirectional_cross_depot_segment_plan(
            solution,
            first_route_index=0,
            second_route_index=1,
            rng=random.Random(7),
            customer_ids=_customer_ids(),
        ),
        vehicle_type_flip_plan(
            solution,
            route_index=0,
            customer_ids=_customer_ids(),
        ),
        charge_departure_retiming_plan(
            solution,
            route_index=1,
            customer_ids=_customer_ids(),
        ),
        time_window_pressure_string_plan(solution, instance),
        dynamic_unexecuted_tail_plan(
            solution,
            route_index=0,
            executed_customer_ids=frozenset({"C1"}),
            customer_ids=_customer_ids(),
        ),
    ]
    assert {plan.kind for plan in plans} == set(OperatorKind)
    assert all(plan.reason for plan in plans)
    assert plans[3].removed_customer_ids == ()
    assert plans[3].preserved_customer_ids == ("C4", "C5", "C6")
    assert plans[5].preserved_customer_ids == ("C1",)
    assert plans[5].removed_customer_ids == ("C2", "C3")


def test_operator_plans_never_treat_charging_stations_as_customers() -> None:
    solution = Solution(
        routes=[
            Route(
                vehicle_id="EV1",
                vehicle_type="ev",
                home_depot_id="D_GZ",
                node_sequence=[
                    "D_GZ",
                    "C1",
                    "S1",
                    "C2",
                    "D_GZ",
                ],
            )
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id="EV1",
                station_id="S1",
                energy_kwh=10.0,
                occupancy_minutes=20.0,
                charge_start_second=25_000.0,
            )
        ],
    )
    plan = cross_depot_route_reassignment_plan(
        solution,
        route_index=0,
        depot_ids=("D_GZ", "D_SZ"),
        customer_ids=frozenset({"C1", "C2"}),
    )
    assert plan.removed_customer_ids == ("C1", "C2")
    partial = remove_customers_from_skeleton(
        solution,
        ("C2",),
        known_customer_ids=frozenset({"C1", "C2"}),
    )
    assert partial.routes[0].node_sequence == [
        "D_GZ",
        "C1",
        "D_GZ",
    ]


def test_whole_route_and_bidirectional_effects_are_semantic() -> None:
    before = _solution()
    customers = _customer_ids()
    route_plan = cross_depot_route_reassignment_plan(
        before,
        route_index=0,
        depot_ids=("D_GZ", "D_SZ"),
        customer_ids=customers,
    )
    reassigned = _whole_route_reassignment_skeleton(
        before,
        route_plan,
        customer_ids=customers,
    )
    effect = verify_operator_effect(
        before,
        reassigned,
        route_plan,
        customer_ids=customers,
    )
    assert effect.passed

    exchange_plan = bidirectional_cross_depot_segment_plan(
        before,
        first_route_index=0,
        second_route_index=1,
        rng=random.Random(3),
        customer_ids=customers,
        max_segment_length=1,
    )
    exchanged = _bidirectional_exchange_skeleton(
        before,
        exchange_plan,
        customer_ids=customers,
    )
    exchange_effect = verify_operator_effect(
        before,
        exchanged,
        exchange_plan,
        customer_ids=customers,
    )
    assert exchange_effect.passed
    assert not verify_operator_effect(
        before,
        before,
        exchange_plan,
        customer_ids=customers,
    ).passed


def test_dynamic_tail_rejects_physical_vehicle_or_depot_drift() -> None:
    before = _solution()
    customers = _customer_ids()
    plan = dynamic_unexecuted_tail_plan(
        before,
        route_index=0,
        executed_customer_ids=frozenset({"C1"}),
        customer_ids=customers,
    )
    changed_tail = Solution(
        routes=[
            Route(
                vehicle_id="OTHER",
                vehicle_type="cv",
                home_depot_id="D_SZ",
                node_sequence=[
                    "D_SZ",
                    "C1",
                    "C3",
                    "C2",
                    "D_SZ",
                ],
            ),
            before.routes[1],
        ]
    )
    assert not verify_operator_effect(
        before,
        changed_tail,
        plan,
        customer_ids=customers,
    ).passed


def test_complete_evaluator_has_one_visible_entry_per_score() -> None:
    ledger = CompleteEvaluationLedger(
        arm=AlgorithmArm.HGS,
        limit=2,
    )

    def fake_score(solution, bundle):
        assert bundle == "bundle"
        return 12.5, {"total_cost": 12.5}, []

    evaluator = BudgetedCompleteEvaluator(
        bundle="bundle",
        ledger=ledger,
        score_function=fake_score,
    )
    evaluator.score(
        _solution(),
        source=CandidateSource.HGS_ARCHIVE,
    )
    evaluator.score(
        _solution(),
        source=CandidateSource.HGS_ARCHIVE,
    )
    assert ledger.consumed == 2
    assert ledger.records[1].duplicate_of_index == 1


def _label(**updates) -> DecoderLabel:
    values = {
        "prefix_index": 2,
        "current_node_id": "C2",
        "home_depot_id": "D_GZ",
        "vehicle_type": "ev",
        "city_id": "guangzhou",
        "date": "2025-02-12",
        "price_area_id": "guangdong_prd_five_city",
        "carbon_source_column": "Guangdong",
        "diesel_zone": "guangdong",
        "time_second": 30_000.0,
        "remaining_capacity_kg": 1_000.0,
        "remaining_energy_kwh": 80.0,
        "cv_fleet_used": 0,
        "ev_fleet_used": 1,
        "variable_cost_cny": 100.0,
        "carbon_kg": 10.0,
        "objective_cost_cny": 120.0,
    }
    values.update(updates)
    return DecoderLabel(**values)


def test_decoder_dominance_prunes_only_same_city_date_and_state() -> None:
    good = _label()
    worse = _label(
        time_second=31_000.0,
        remaining_energy_kwh=70.0,
        variable_cost_cny=110.0,
        carbon_kg=11.0,
        objective_cost_cny=130.0,
    )
    assert dominates(good, worse)
    assert not dominates(
        good,
        _label(
            date="2025-02-13",
            time_second=31_000.0,
            objective_cost_cny=130.0,
        ),
    )
    frontier = DominanceFrontier()
    assert frontier.add(worse)
    assert frontier.add(good)
    assert frontier.labels == (good,)


def test_reference_decoder_jointly_changes_depot_and_vehicle_type() -> None:
    class Bundle:
        instance = _instance()
        time_profile = []
        prices = object()
        customer_home_depot = {
            "C1": "D_GZ",
            "C2": "D_GZ",
            "C3": "D_GZ",
            "C4": "D_SZ",
            "C5": "D_SZ",
            "C6": "D_SZ",
        }
        fleet_caps_by_depot = {
            "D_GZ": {"num_cv": 2, "num_ev": 2},
            "D_SZ": {"num_cv": 2, "num_ev": 2},
        }

    def fake_charge(route, instance, profile, prices, **kwargs):
        assert route.vehicle_type == "ev"
        assert kwargs["depot_charge_window_mode"] == ("same_day_predeparture")
        return route, []

    def fake_score(solution, bundle):
        assert len(solution.routes) == 2
        return 50.0, {"total_cost": 50.0}, []

    ledger = CompleteEvaluationLedger(
        arm=AlgorithmArm.RUIN_RECREATE,
        limit=1,
    )
    evaluator = BudgetedCompleteEvaluator(
        bundle=Bundle(),
        ledger=ledger,
        score_function=fake_score,
    )
    result = decode_explicit_assignments(
        _solution(),
        Bundle(),
        assignments={
            0: RouteAssignment("D_SZ", "ev"),
            1: RouteAssignment("D_GZ", "cv"),
        },
        evaluator=evaluator,
        source=CandidateSource.RUIN_RECREATE,
        charge_repair_function=fake_charge,
    )
    assert result.scored.feasible
    assert result.charging_route_count == 1
    assert [
        (route.home_depot_id, route.vehicle_type)
        for route in result.scored.solution.routes
    ] == [("D_SZ", "ev"), ("D_GZ", "cv")]
    assert result.fleet_used == {
        "D_GZ": {"num_cv": 1, "num_ev": 0},
        "D_SZ": {"num_cv": 0, "num_ev": 1},
    }


def test_finite_fleet_dp_jointly_assigns_routes_without_overflow() -> None:
    options = {
        0: (
            AssignmentOption(
                0,
                RouteAssignment("D_GZ", "cv"),
                10.0,
                ("D_GZ", "cv", 0),
            ),
            AssignmentOption(
                0,
                RouteAssignment("D_SZ", "ev"),
                12.0,
                ("D_SZ", "ev", 0),
            ),
        ),
        1: (
            AssignmentOption(
                1,
                RouteAssignment("D_GZ", "cv"),
                9.0,
                ("D_GZ", "cv", 1),
            ),
            AssignmentOption(
                1,
                RouteAssignment("D_SZ", "ev"),
                8.0,
                ("D_SZ", "ev", 1),
            ),
        ),
    }
    candidates = solve_finite_fleet_assignment_dp(
        options,
        {
            "D_GZ": {"num_cv": 1, "num_ev": 0},
            "D_SZ": {"num_cv": 0, "num_ev": 1},
        },
        beam_per_state=2,
        max_candidates=4,
    )
    assert len(candidates) == 2
    assert candidates[0].route_local_cost == 18.0
    assert [
        (
            route_index,
            assignment.home_depot_id,
            assignment.vehicle_type,
        )
        for route_index, assignment in candidates[0].assignments
    ] == [
        (0, "D_GZ", "cv"),
        (1, "D_SZ", "ev"),
    ]
    assert all(candidate.fleet_use == (1, 0, 0, 1) for candidate in candidates)


def test_recreate_restores_each_removed_customer_exactly_once() -> None:
    class Profile:
        payload_capacity_kg = 10.0

    class RecreateInstance:
        def __init__(self):
            self._base = _instance()
            self.nodes = self._base.nodes

        def node(self, node_id):
            return next(node for node in self.nodes if node.node_id == node_id)

        def distance(self, left, right):
            return self._base.distance(left, right)

        def vehicle_profile(self, vehicle_type):
            return Profile()

    class Bundle:
        instance = RecreateInstance()
        customer_home_depot = {
            "C1": "D_GZ",
            "C2": "D_GZ",
            "C3": "D_GZ",
            "C4": "D_SZ",
            "C5": "D_SZ",
            "C6": "D_SZ",
        }
        fleet_caps_by_depot = {
            "D_GZ": {"num_cv": 2, "num_ev": 1},
            "D_SZ": {"num_cv": 2, "num_ev": 1},
        }

    removed = ("C2", "C5")
    partial = remove_customers_from_skeleton(
        _solution(),
        removed,
        known_customer_ids=_customer_ids(),
    )
    result = recreate_removed_customers(
        partial,
        removed,
        Bundle(),
        rng=random.Random(17),
    )
    customers = [
        customer_id
        for route in result.skeleton.routes
        for customer_id in route.node_sequence[1:-1]
    ]
    assert sorted(customers) == [
        "C1",
        "C2",
        "C3",
        "C4",
        "C5",
        "C6",
    ]
    assert len(customers) == len(set(customers))
    assert {step.customer_id for step in result.steps} == set(removed)


def test_rr_temperature_is_result_independent_and_cools() -> None:
    config = RrConfig()
    start = _temperature(
        initial_objective=1_000.0,
        consumed=0,
        limit=80,
        config=config,
    )
    middle = _temperature(
        initial_objective=1_000.0,
        consumed=40,
        limit=80,
        config=config,
    )
    end = _temperature(
        initial_objective=1_000.0,
        consumed=79,
        limit=80,
        config=config,
    )
    assert start > middle > end > 0.0
    assert _accept_candidate(
        delta=-1.0,
        temperature=end,
        rng=random.Random(1),
    )


def test_real_bundle_preregistration_is_result_blind() -> None:
    preregistration = real_bundle_gate.load_preregistration()
    assert preregistration["status"] == "REGISTERED_NOT_EXECUTED"
    assert [row["stratum"] for row in preregistration["instances"]] == [
        "small",
        "medium",
        "large",
    ]
    serialized = str(preregistration).lower()
    for forbidden in ("best_cost", "winning_arm", "hybrid_gain"):
        assert forbidden not in serialized


def test_real_bundle_preregistration_inputs_are_hash_closed() -> None:
    preregistration = real_bundle_gate.load_preregistration()
    verified = real_bundle_gate.verify_preregistration_inputs(
        preregistration,
    )
    assert verified["verified_file_count"] == 55
    assert verified["authority_selected_file_counts"] == {
        "static_inputs": 7,
        "road_matrices": 30,
        "runtime_parameters": 6,
        "finite_fleet": 7,
    }


def test_real_bundle_manifest_selection_is_instance_scoped() -> None:
    selected = real_bundle_gate._selected_manifest_paths(
        "road_matrices",
        ("registered",),
        {
            "instances/registered/cv/road.csv": "a",
            "instances/other/cv/road.csv": "b",
        },
    )
    assert selected == ("instances/registered/cv/road.csv",)


def test_real_bundle_gate_refuses_to_overlap_formal_e2(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        real_bundle_gate,
        "formal_resource_state",
        lambda: {
            "progress_status": "RUNNING",
            "completed_tasks": 68,
            "updated_at_utc": "registered",
            "blocking_processes": [
                {
                    "pid": "123",
                    "token": (
                        "run_corrected_china81_d6_staged_portfolio_"
                        "v7_small_archive_ledger.py"
                    ),
                }
            ],
            "formal_running": True,
        },
    )
    with pytest.raises(
        RuntimeError,
        match="HALT_G0_RESOURCE_ISOLATION_FORMAL_E2_RUNNING",
    ):
        real_bundle_gate.require_resource_isolation()
