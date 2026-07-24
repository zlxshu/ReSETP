from __future__ import annotations

import random

import pytest

from setp_solver.instance_loader import Instance, Node
from setp_solver.solution import Route, Solution

from contracts import (
    AlgorithmArm,
    CandidateSource,
    CompleteEvaluationLedger,
    DecoderCacheKey,
    HybridLineageLedger,
    TransferDirection,
)
from decoder_labels import DecoderLabel, DominanceFrontier, dominates
from evaluation import BudgetedCompleteEvaluator
from operator_plans import (
    OperatorKind,
    bidirectional_cross_depot_segment_plan,
    charge_departure_retiming_plan,
    cross_depot_route_reassignment_plan,
    dynamic_unexecuted_tail_plan,
    time_window_pressure_string_plan,
    vehicle_type_flip_plan,
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


def test_cache_key_changes_across_city_date_and_dynamic_state() -> None:
    base = dict(
        instance_id="cn-prd-50c-01",
        date="2025-02-12",
        region="prd",
        home_depot_id="D_GZ",
        vehicle_type="ev",
        node_sequence=("D_GZ", "C1", "D_GZ"),
        dynamic_state_hash="state-a",
        runtime_parameter_authority="runtime-v4",
        fleet_authority="fleet-v1",
    )
    first = DecoderCacheKey(**base)
    assert first.digest() != DecoderCacheKey(
        **{**base, "home_depot_id": "D_SZ"}
    ).digest()
    assert first.digest() != DecoderCacheKey(
        **{**base, "date": "2025-02-13"}
    ).digest()
    assert first.digest() != DecoderCacheKey(
        **{**base, "dynamic_state_hash": "state-b"}
    ).digest()


def test_all_six_problem_specific_operator_plans_are_distinct() -> None:
    solution = _solution()
    instance = _instance()
    plans = [
        cross_depot_route_reassignment_plan(
            solution,
            route_index=0,
            depot_ids=("D_GZ", "D_SZ"),
        ),
        bidirectional_cross_depot_segment_plan(
            solution,
            first_route_index=0,
            second_route_index=1,
            rng=random.Random(7),
        ),
        vehicle_type_flip_plan(solution, route_index=0),
        charge_departure_retiming_plan(solution, route_index=1),
        time_window_pressure_string_plan(solution, instance),
        dynamic_unexecuted_tail_plan(
            solution,
            route_index=0,
            executed_customer_ids=frozenset({"C1"}),
        ),
    ]
    assert {plan.kind for plan in plans} == set(OperatorKind)
    assert all(plan.reason for plan in plans)
    assert plans[3].removed_customer_ids == ()
    assert plans[3].preserved_customer_ids == ("C4", "C5", "C6")
    assert plans[5].preserved_customer_ids == ("C1",)
    assert plans[5].removed_customer_ids == ("C2", "C3")


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
