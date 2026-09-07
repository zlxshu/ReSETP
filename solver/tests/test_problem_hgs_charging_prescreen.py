"""Exact charging prescreen tests on the formal DEPOTSEARCH instance.

The prescreen may only reject a candidate that the full charging repair would
reject as well.  These tests sample real education moves from the formal
initial solution and check that contract move by move, for both the
standalone per-trip verdict and the chained bare-duty verdict added on
2026-09-02.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_problem_hgs_private_technical import (  # noqa: E402
    DEPOT_SEARCH_INSTANCE_ID,
    FLEET_PARAMETER_CLASSES,
    _build_context,
    _policy,
)
from setp_solver.algorithms.problem_hgs.charging import (  # noqa: E402
    CHARGING_REASON_PRESCREEN_REJECT,
    PRESCREEN_CHANNELS,
    ChargingFeasibilityPrescreen,
    repair_changed_duties_outcome,
)
from setp_solver.algorithms.problem_hgs.contracts import (  # noqa: E402
    CandidateStatus,
    ChargingCandidateStatus,
)
from setp_solver.algorithms.problem_hgs.education import _rejection  # noqa: E402
from setp_solver.algorithms.problem_hgs.evaluation import (  # noqa: E402
    DutyFullEvaluator,
    assert_candidate_routes_single_shift,
)
from setp_solver.algorithms.problem_hgs.fleet_registry import (  # noqa: E402
    assert_fleet_activation_allowed,
)
from setp_solver.algorithms.problem_hgs.model import (  # noqa: E402
    assert_locks_preserved,
)
from setp_solver.algorithms.problem_hgs.operators import (  # noqa: E402
    RelocateMove,
    generate_problem_moves,
)
from setp_solver.algorithms.problem_hgs.runner import (  # noqa: E402
    _TrajectoryRecorder,
)


SAMPLE_LIMIT = 320


@pytest.fixture(scope="module")
def formal_input():
    repo = Path(__file__).parents[2]
    bundle, initial, _neutral_profit, context = _build_context(
        repo,
        DEPOT_SEARCH_INSTANCE_ID,
        fleet_parameters=FLEET_PARAMETER_CLASSES["endogenous"],
    )
    evaluator = DutyFullEvaluator(context)
    policy = _policy(evaluator)
    evaluation = evaluator.evaluate(initial)
    assert evaluation.feasible, "formal initial solution must be feasible"
    return bundle, initial, evaluation, context, policy


def _sampled_candidates(initial, evaluation, context, instance):
    """Yield (move, raw candidate) pairs in the education engine's own order."""

    moves = generate_problem_moves(
        initial,
        evaluation,
        instance,
        include_whole_duty_type_exchange=False,
        allowed_channels=frozenset({"depot_collaboration", "multi_trip"}),
        customer_shift_by_id=(
            None
            if context.rebuilt_route_constraints is None
            else context.rebuilt_route_constraints.customer_shift_by_id
        ),
        fairness_prescreen_enabled=True,
    )
    yielded = 0
    for move in moves:
        if yielded >= SAMPLE_LIMIT:
            return
        try:
            raw = move.apply(initial)
            assert_locks_preserved(initial, raw)
            assert_fleet_activation_allowed(initial, raw, enabled=True)
            assert_candidate_routes_single_shift(
                raw,
                context.rebuilt_route_constraints,
            )
        except (TypeError, ValueError):
            continue
        yielded += 1
        yield move, raw


def test_prescreen_never_rejects_what_full_repair_accepts(formal_input):
    bundle, initial, evaluation, context, policy = formal_input
    prescreen = ChargingFeasibilityPrescreen(context, policy)
    screened_rejects = 0
    full_rejects = 0
    sampled = 0
    for move, raw in _sampled_candidates(
        initial, evaluation, context, bundle.instance
    ):
        sampled += 1
        verdict = prescreen.screen(
            raw,
            changed_duty_ids=move.changed_duty_ids,
            channel=move.channel,
        )
        outcome = repair_changed_duties_outcome(
            initial,
            raw,
            changed_duty_ids=set(move.changed_duty_ids),
            context=context,
            policy=policy,
        )
        if outcome.candidate is None:
            full_rejects += 1
        if verdict is not None:
            screened_rejects += 1
            assert outcome.candidate is None, (
                "prescreen rejected a candidate that full repair accepted: "
                f"{move.action_id}: {verdict}"
            )
            assert verdict.charging_rejection_reason_code == (
                CHARGING_REASON_PRESCREEN_REJECT
            )
    assert sampled > 0
    stats = prescreen.statistics()
    print(
        f"\nsampled={sampled} full_rejects={full_rejects} "
        f"screened_rejects={screened_rejects} "
        f"by_reason={ {k: v for k, v in prescreen.rejected_by_channel_and_reason.items()} } "
        f"chain_cache={prescreen.chain_cache_hits}/{prescreen.chain_cache_misses}"
    )
    assert stats["rejected_candidates"] == screened_rejects


def test_prescreen_chain_verdict_is_a_certain_death(formal_input):
    """Every chain-only rejection must also die in full repair."""

    bundle, initial, evaluation, context, policy = formal_input
    prescreen = ChargingFeasibilityPrescreen(context, policy)
    chain_only = 0
    for move, raw in _sampled_candidates(
        initial, evaluation, context, bundle.instance
    ):
        standalone_failure = None
        for duty in raw.duties:
            if duty.physical_vehicle_id not in move.changed_duty_ids:
                continue
            for trip in duty.trips:
                if (
                    duty.vehicle_type == "ev"
                    and trip.trip_index in duty.locked_charging_trip_indices
                ):
                    continue
                standalone_failure = prescreen._screen_trip(duty, trip)
                if standalone_failure is not None:
                    break
            if standalone_failure is not None:
                break
        if standalone_failure is not None:
            continue
        chain_failure = None
        for duty in raw.duties:
            if duty.physical_vehicle_id in move.changed_duty_ids:
                chain_failure = prescreen._screen_duty_chain(duty)
                if chain_failure is not None:
                    break
        if chain_failure is None or chain_failure[0] == "uncertain":
            continue
        chain_only += 1
        outcome = repair_changed_duties_outcome(
            initial,
            raw,
            changed_duty_ids=set(move.changed_duty_ids),
            context=context,
            policy=policy,
        )
        assert outcome.candidate is None, (
            "chain prescreen rejected a candidate that full repair accepted: "
            f"{move.action_id}: {chain_failure}"
        )
    print(f"\nchain_only_rejections={chain_only}")


def test_prescreen_channels_cover_every_repair_entry():
    assert {
        "depot_collaboration",
        "multi_trip",
        "whole_duty_type_exchange",
        "route_kernel",
    } <= PRESCREEN_CHANNELS
    assert "route_kernel_crossover" not in PRESCREEN_CHANNELS


def test_rejection_outcome_carries_charging_status():
    move = RelocateMove(
        action_id="relocate:test",
        channel="multi_trip",
        source_duty_id="EV_1",
        source_trip_index=1,
        customer_id="C001",
        target_duty_id="EV_1",
        target_trip_index=2,
        target_position=0,
    )
    outcome = _rejection(
        move,
        CandidateStatus.REJECTED_CHARGING,
        ValueError("route EV_1#T1 misses C001's time window"),
        0.0,
    )
    assert outcome.charging_candidate_status is (
        ChargingCandidateStatus.REJECTED_CHARGING
    )
    interface = _rejection(
        move,
        CandidateStatus.REJECTED_INTERFACE,
        ValueError("mixes customer shifts"),
        0.0,
    )
    assert interface.charging_candidate_status is None


def test_trajectory_recorder_can_drop_all_rows():
    recorder = _TrajectoryRecorder(None, retain=False)

    recorder.emit_many(())

    assert recorder.retained == []


def _type_exchange_candidates(initial, context):
    """Yield whole-duty CV<->EV exchanges: the channel NO_FEASIBLE_WINDOW hits."""

    from setp_solver.algorithms.problem_hgs.operators import (
        WholeDutyTypeExchangeMove,
    )

    duties = tuple(initial.duties)
    yielded = 0
    for left_index, left in enumerate(duties):
        for right in duties[left_index + 1 :]:
            if left.home_depot_id != right.home_depot_id:
                continue
            if {left.vehicle_type, right.vehicle_type} != {"ev", "cv"}:
                continue
            if not left.trips and not right.trips:
                continue
            move = WholeDutyTypeExchangeMove(
                action_id=(
                    "whole-duty-type-exchange:"
                    f"{left.physical_vehicle_id}<->{right.physical_vehicle_id}"
                ),
                channel="whole_duty_type_exchange",
                left_duty_id=left.physical_vehicle_id,
                right_duty_id=right.physical_vehicle_id,
            )
            try:
                raw = move.apply(initial)
                assert_locks_preserved(initial, raw)
                assert_candidate_routes_single_shift(
                    raw,
                    context.rebuilt_route_constraints,
                )
            except (TypeError, ValueError):
                continue
            yielded += 1
            if yielded > SAMPLE_LIMIT:
                return
            yield move, raw


def test_chain_charge_bound_rejects_only_certain_window_deaths(formal_input):
    """The between-trip charge lower bound must never kill a repairable chain.

    2026-09-02 (D2): the chain screen now forces trip ``k+1`` to depart no
    earlier than the bare return of trip ``k`` plus the just-enough depot
    charge time of trip ``k+1``.  Every rejection it adds must coincide with
    a full-repair rejection, and it should catch a real share of the
    NO_FEASIBLE_WINDOW deaths that used to reach the repair.
    """

    from setp_solver.algorithms.problem_hgs.charging import (
        CHARGING_REASON_NO_FEASIBLE_WINDOW,
    )

    bundle, initial, _evaluation, context, policy = formal_input
    prescreen = ChargingFeasibilityPrescreen(context, policy)
    sampled = screened = full_rejects = window_rejects = caught_windows = 0
    for move, raw in _type_exchange_candidates(initial, context):
        sampled += 1
        verdict = prescreen.screen(
            raw,
            changed_duty_ids=move.changed_duty_ids,
            channel=move.channel,
        )
        outcome = repair_changed_duties_outcome(
            initial,
            raw,
            changed_duty_ids=set(move.changed_duty_ids),
            context=context,
            policy=policy,
        )
        if outcome.candidate is None:
            full_rejects += 1
            if outcome.reason_code == CHARGING_REASON_NO_FEASIBLE_WINDOW:
                window_rejects += 1
                if verdict is not None:
                    caught_windows += 1
        if verdict is not None:
            screened += 1
            assert outcome.candidate is None, (
                "charge-bound prescreen rejected a candidate that full repair "
                f"accepted: {move.action_id}: {verdict}"
            )
    assert sampled > 0
    assert prescreen.chain_charge_bound_applied > 0
    print(
        f"\ntype_exchange sampled={sampled} prescreen_rejects={screened} "
        f"full_rejects={full_rejects} window_rejects={window_rejects} "
        f"caught_by_prescreen={caught_windows}"
    )


@pytest.fixture(scope="module")
def tight_chain_input(formal_input):
    """A saved natural-stop best solution: tight EV chains, real window deaths.

    Skipped when the report artifact is absent (reports are not versioned).
    """

    from run_problem_hgs_private_technical import (
        _load_registered_initial_solution,
    )

    repo = Path(__file__).parents[2]
    saved = (
        repo
        / "solver/reports/cut4_admission_ab_20260902/old/run_1/best_solution.json"
    )
    if not saved.exists():
        pytest.skip("saved tight-chain solution not present")
    bundle, _initial, _evaluation, context, policy = formal_input
    individual = _load_registered_initial_solution(saved, bundle)
    evaluator = DutyFullEvaluator(context)
    evaluation = evaluator.evaluate(individual)
    return bundle, individual, evaluation, context, policy


def test_chain_charge_bound_on_tight_chains(tight_chain_input):
    """On a converged solution the bound catches real NO_FEASIBLE_WINDOW deaths."""

    from setp_solver.algorithms.problem_hgs.charging import (
        CHARGING_REASON_NO_FEASIBLE_WINDOW,
    )

    bundle, individual, evaluation, context, policy = tight_chain_input
    prescreen = ChargingFeasibilityPrescreen(context, policy)
    stats = {"sampled": 0, "screened": 0, "full_rejects": 0, "window": 0, "caught": 0}
    candidates = list(_type_exchange_candidates(individual, context)) + list(
        _sampled_candidates(individual, evaluation, context, bundle.instance)
    )
    for move, raw in candidates:
        stats["sampled"] += 1
        verdict = prescreen.screen(
            raw,
            changed_duty_ids=move.changed_duty_ids,
            channel=move.channel,
        )
        outcome = repair_changed_duties_outcome(
            individual,
            raw,
            changed_duty_ids=set(move.changed_duty_ids),
            context=context,
            policy=policy,
        )
        if outcome.candidate is None:
            stats["full_rejects"] += 1
            if outcome.reason_code == CHARGING_REASON_NO_FEASIBLE_WINDOW:
                stats["window"] += 1
                if verdict is not None:
                    stats["caught"] += 1
        if verdict is not None:
            stats["screened"] += 1
            assert outcome.candidate is None, (
                "charge-bound prescreen rejected a candidate that full repair "
                f"accepted: {move.action_id}: {verdict}"
            )
    print(f"\ntight chains: {stats} bound_applied={prescreen.chain_charge_bound_applied}")
    assert stats["sampled"] > 0
