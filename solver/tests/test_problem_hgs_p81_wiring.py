"""Production wiring checks for P81 static near-feasible retention."""

from __future__ import annotations

import pytest

import setp_solver.algorithms.problem_hgs.integrated_private as integrated_module
from setp_solver.algorithms.problem_hgs.contracts import (
    CandidateStatus,
    ChargingCandidateStatus,
)
from setp_solver.algorithms.problem_hgs.crossover import DutyCrossoverResult
from setp_solver.algorithms.problem_hgs.education import evaluate_move
from setp_solver.algorithms.problem_hgs.hybrid_decoder import (
    HybridDecodeGap,
    HybridDecodeOutcome,
    HybridDecodeStatus,
    HybridGapKind,
)
from setp_solver.algorithms.problem_hgs.initialization import (
    build_initial_population,
)
from setp_solver.algorithms.problem_hgs.integrated_private import (
    build_integrated_private_hgs,
)
from setp_solver.algorithms.problem_hgs.model import DutyIndividual
from setp_solver.algorithms.problem_hgs.operators import (
    WholeDutyTypeExchangeMove,
)
from setp_hgs_kernel.stop import MaxIterations
from tests.test_problem_hgs_charging_gap import _penalties, sc3_case


class _SnapshotMove:
    action_id = "sc3-production-snapshot"
    channel = "sc3_production_test"

    def __init__(
        self,
        candidate: DutyIndividual,
        changed_duty_ids: frozenset[str],
    ) -> None:
        self.candidate = candidate
        self.changed_duty_ids = changed_duty_ids

    def apply(self, _individual: DutyIndividual) -> DutyIndividual:
        return self.candidate


class _KernelRng:
    @staticmethod
    def randint(_high: int) -> int:
        return 0

    @staticmethod
    def rand() -> float:
        return 1.0


class _RouteEngine:
    source_id = "sc3-production-test"
    identity_sha256 = "8" * 64
    data = object()
    penalty_manager = object()
    local_search = object()

    def __init__(self, move: _SnapshotMove | None = None) -> None:
        self.rng = _KernelRng()
        self._move = move

    def propose(self, *args, **kwargs):
        del args, kwargs
        return ()

    def random_skeleton_move(
        self,
        _initial: DutyIndividual,
        *,
        draw_index: int,
    ) -> _SnapshotMove | None:
        assert draw_index == 0
        return self._move


def _production_move(sc3_case) -> _SnapshotMove:
    move = WholeDutyTypeExchangeMove(
        action_id=(
            "whole-duty-type-exchange:"
            "CV_D_OSM_WAY_1071205721_3<->EV_D_OSM_WAY_1071205721_1"
        ),
        channel="whole_duty_type_exchange",
        left_duty_id="CV_D_OSM_WAY_1071205721_3",
        right_duty_id="EV_D_OSM_WAY_1071205721_1",
    )
    return _SnapshotMove(
        move.apply(sc3_case["initial"]),
        move.changed_duty_ids,
    )


def _private_bundle(sc3_case, *, route_layer_crossover_enabled: bool = False):
    reference = sc3_case["initial"]
    full = sc3_case["evaluator"].evaluate(reference)
    return build_integrated_private_hgs(
        (reference,),
        evaluator=sc3_case["evaluator"],
        charging_policy=sc3_case["policy_off"],
        route_engine=_RouteEngine(),
        penalty_parameters=_penalties(),
        stagnation_patience=10,
        include_mechanism_refinement=False,
        initial_evaluations=(full,),
        route_layer_crossover_enabled=route_layer_crossover_enabled,
    )


def _assert_infeasible_pool_and_best_boundary(bundle, parent, child) -> None:
    assert not child.evaluation.feasible
    assert bundle.population.add(child)
    assert any(
        candidate.solution.fingerprint == child.solution.fingerprint
        and not candidate.evaluation.feasible
        for candidate in bundle.population
    )
    assert not bundle.algorithm._better(child, parent)


def test_sc3_education_move_reaches_complete_evaluation(sc3_case) -> None:
    outcome = evaluate_move(
        sc3_case["initial"],
        _production_move(sc3_case),
        evaluator=sc3_case["evaluator"],
        charging_policy=sc3_case["policy_off"],
    )

    assert outcome.status == CandidateStatus.EVALUATED
    assert outcome.charging_candidate_status == (
        ChargingCandidateStatus.BEST_EFFORT
    )
    assert outcome.evaluation is not None
    assert not outcome.evaluation.feasible


def test_sc3_initialization_keeps_best_effort_candidate(sc3_case) -> None:
    move = _production_move(sc3_case)
    result = build_initial_population(
        sc3_case["initial"],
        evaluator=sc3_case["evaluator"],
        charging_policy=sc3_case["policy_off"],
        route_engine=_RouteEngine(move),
        requested_size=2,
        random_seed=11,
        max_random_attempts=1,
    )

    assert result.actual_size == 2
    assert result.attempts[0].status == "BEST_EFFORT"
    assert result.evaluations[-1].charging_candidate_status == (
        ChargingCandidateStatus.BEST_EFFORT
    )
    assert not result.evaluations[-1].feasible


def test_sc3_trip_assignment_child_enters_infeasible_population(
    sc3_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    move = _production_move(sc3_case)
    crossed = DutyCrossoverResult(
        child=move.candidate,
        changed_duty_ids=move.changed_duty_ids,
        donor_duty_ids=(),
        duplicate_customers_removed=(),
        unserved_customers=(),
    )
    monkeypatch.setattr(
        integrated_module,
        "trip_assignment_exchange_candidates",
        lambda *args, **kwargs: (crossed,),
    )
    bundle = _private_bundle(sc3_case)

    result = bundle.algorithm.run(MaxIterations(1))
    gap_children = tuple(
        candidate
        for candidate in bundle.population
        if candidate.evaluation.full.charging_candidate_status
        == ChargingCandidateStatus.BEST_EFFORT
    )

    assert gap_children
    assert all(not candidate.evaluation.feasible for candidate in gap_children)
    assert bundle.accounting.mechanism.charging_candidate_statuses[
        "BEST_EFFORT"
    ] >= 1
    assert bundle.accounting.mechanism.charging_gap_a2_evaluations >= 1
    assert result.best.evaluation.feasible
    assert result.best.solution.fingerprint == sc3_case["initial"].fingerprint


def test_sc3_route_layer_nonstructural_gap_reaches_infeasible_population(
    sc3_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    move = _production_move(sc3_case)
    decoded = HybridDecodeOutcome(
        status=HybridDecodeStatus.BEST_EFFORT,
        candidate=move.candidate,
        customer_order=(),
        segments=(),
        changed_duty_ids=move.changed_duty_ids,
        gaps=(
            HybridDecodeGap(
                HybridGapKind.CHARGING_WINDOW,
                "best-effort charging window",
            ),
        ),
        wall_seconds=0.0,
    )
    monkeypatch.setattr(
        integrated_module,
        "route_layer_order_from_parents",
        lambda *args, **kwargs: ((), {}),
    )
    monkeypatch.setattr(
        integrated_module,
        "decode_customer_order",
        lambda *args, **kwargs: decoded,
    )
    bundle = _private_bundle(
        sc3_case,
        route_layer_crossover_enabled=True,
    )
    parent = bundle.algorithm._adapter.evaluate(sc3_case["initial"])
    assert parent is not None

    child = bundle.algorithm._adapter.breed((parent, parent))

    assert child is not None
    assert bundle.accounting.mechanism.route_layer_entered_evaluation == 1
    _assert_infeasible_pool_and_best_boundary(bundle, parent, child)


def test_sc3_route_layer_structural_gap_still_rejects(
    sc3_case,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    move = _production_move(sc3_case)
    decoded = HybridDecodeOutcome(
        status=HybridDecodeStatus.BEST_EFFORT,
        candidate=move.candidate,
        customer_order=(),
        segments=(),
        changed_duty_ids=move.changed_duty_ids,
        gaps=(
            HybridDecodeGap(
                HybridGapKind.FLEET_SLOT,
                "no compatible physical slot",
            ),
        ),
        wall_seconds=0.0,
    )
    monkeypatch.setattr(
        integrated_module,
        "route_layer_order_from_parents",
        lambda *args, **kwargs: ((), {}),
    )
    monkeypatch.setattr(
        integrated_module,
        "decode_customer_order",
        lambda *args, **kwargs: decoded,
    )
    monkeypatch.setattr(
        integrated_module,
        "repair_changed_duties_outcome",
        lambda *args, **kwargs: pytest.fail(
            "structural gap reached charging repair"
        ),
    )
    bundle = _private_bundle(
        sc3_case,
        route_layer_crossover_enabled=True,
    )
    parent = bundle.algorithm._adapter.evaluate(sc3_case["initial"])
    assert parent is not None

    child = bundle.algorithm._adapter.breed((parent, parent))

    assert child is parent
    assert bundle.accounting.mechanism.route_layer_entered_evaluation == 0
