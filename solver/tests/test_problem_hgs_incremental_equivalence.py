"""The per-vehicle incremental evaluation must equal the complete one.

2026-09-02 (D1): slices now carry each vehicle's certificate, local
violations and additive profit rows; combining them recomputes only the
cross-vehicle terms.  These tests replay real education candidates on the
formal instance and compare the incremental result with a fresh complete
evaluation: cost, breakdown, violation multiset, profits, margins,
certificate trips and prepared routes/actions.
"""

from __future__ import annotations

import dataclasses
import math
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
    _load_registered_initial_solution,
    _policy,
)
from setp_solver.algorithms.problem_hgs.charging import (  # noqa: E402
    repair_changed_duties_outcome,
)
from setp_solver.algorithms.problem_hgs.evaluation import (  # noqa: E402
    DutyFullEvaluator,
    DutyIncrementalEvaluator,
    assert_candidate_routes_single_shift,
)
from setp_solver.algorithms.problem_hgs.model import (  # noqa: E402
    assert_locks_preserved,
)
from setp_solver.algorithms.problem_hgs.operators import (  # noqa: E402
    WholeDutyTypeExchangeMove,
    generate_problem_moves,
)


SAMPLE_LIMIT = 120
ABS_TOL = 1.0e-9


@pytest.fixture(scope="module")
def formal():
    repo = Path(__file__).parents[2]
    bundle, initial, _neutral, context = _build_context(
        repo,
        DEPOT_SEARCH_INSTANCE_ID,
        fleet_parameters=FLEET_PARAMETER_CLASSES["endogenous"],
    )
    evaluator = DutyFullEvaluator(context)
    policy = _policy(evaluator)
    return bundle, initial, context, evaluator, policy


@pytest.fixture(scope="module")
def starting_points(formal):
    bundle, initial, context, evaluator, policy = formal
    points = [initial]
    saved = (
        Path(__file__).parents[2]
        / "solver/reports/cut4_admission_ab_20260902/old/run_1/best_solution.json"
    )
    if saved.exists():
        points.append(_load_registered_initial_solution(saved, bundle))
    return points


def _candidates(individual, evaluation, context, bundle, policy):
    """Repaired (charging-complete) candidates reachable by one education move."""

    moves = list(
        generate_problem_moves(
            individual,
            evaluation,
            bundle.instance,
            include_whole_duty_type_exchange=False,
            allowed_channels=frozenset({"depot_collaboration", "multi_trip"}),
            customer_shift_by_id=(
                None
                if context.rebuilt_route_constraints is None
                else context.rebuilt_route_constraints.customer_shift_by_id
            ),
            fairness_prescreen_enabled=True,
        )
    )
    duties = tuple(individual.duties)
    for left_index, left in enumerate(duties):
        for right in duties[left_index + 1 :]:
            if left.home_depot_id != right.home_depot_id:
                continue
            if {left.vehicle_type, right.vehicle_type} != {"ev", "cv"}:
                continue
            if not left.trips and not right.trips:
                continue
            moves.append(
                WholeDutyTypeExchangeMove(
                    action_id=(
                        f"tx:{left.physical_vehicle_id}<->{right.physical_vehicle_id}"
                    ),
                    channel="whole_duty_type_exchange",
                    left_duty_id=left.physical_vehicle_id,
                    right_duty_id=right.physical_vehicle_id,
                )
            )
    yielded = 0
    for move in moves:
        if yielded >= SAMPLE_LIMIT:
            return
        try:
            raw = move.apply(individual)
            assert_locks_preserved(individual, raw)
            assert_candidate_routes_single_shift(
                raw,
                context.rebuilt_route_constraints,
            )
        except (TypeError, ValueError):
            continue
        outcome = repair_changed_duties_outcome(
            individual,
            raw,
            changed_duty_ids=set(move.changed_duty_ids),
            context=context,
            policy=policy,
        )
        if outcome.candidate is None:
            continue
        yielded += 1
        yield move, outcome.candidate


def _violation_key(violation):
    return (violation.type, violation.vehicle_id, violation.location, violation.detail)


def _assert_same(full, incremental):
    assert math.isclose(full.total_cost, incremental.total_cost, abs_tol=ABS_TOL)
    assert set(full.breakdown) == set(incremental.breakdown)
    for key, value in full.breakdown.items():
        assert math.isclose(
            float(value), float(incremental.breakdown[key]), abs_tol=1.0e-7
        ), key
    assert sorted(map(_violation_key, full.violations)) == sorted(
        map(_violation_key, incremental.violations)
    )
    assert sorted(zip(full.violation_axes, full.violation_magnitudes)) == sorted(
        zip(incremental.violation_axes, incremental.violation_magnitudes)
    )
    assert set(full.depot_profit) == set(incremental.depot_profit)
    for depot_id, value in full.depot_profit.items():
        assert math.isclose(
            float(value), float(incremental.depot_profit[depot_id]), abs_tol=1.0e-7
        )
    for depot_id, value in full.participation_margin.items():
        assert math.isclose(
            float(value),
            float(incremental.participation_margin[depot_id]),
            abs_tol=1.0e-7,
        )
    def _trip_rows(certificate):
        return sorted(
            (trip.route_id, tuple(sorted(dataclasses.asdict(trip).items())))
            for trip in certificate.trips
        )

    assert _trip_rows(full.certificate) == _trip_rows(incremental.certificate)
    assert full.certificate.vehicle_counts == incremental.certificate.vehicle_counts
    assert sorted(full.certificate.time_warp_by_route) == sorted(
        incremental.certificate.time_warp_by_route
    )
    assert (
        full.certificate.first_trip_charge_day_offset
        == incremental.certificate.first_trip_charge_day_offset
    )
    # 2026-09-06: the per-duty first-trip charge days too.  The two sides
    # reach this field by different routes -- the full path through
    # ``prepare_multitrip_solution``, the incremental one through
    # ``_combine_certificates`` -- so their agreement here is the single
    # sharpest check that the per-duty map is built the same way on both.
    assert sorted(
        full.certificate.first_trip_charge_day_offset_by_route
    ) == sorted(incremental.certificate.first_trip_charge_day_offset_by_route)
    assert sorted(
        (route.vehicle_id, tuple(route.node_sequence))
        for route in full.prepared_solution.routes
    ) == sorted(
        (route.vehicle_id, tuple(route.node_sequence))
        for route in incremental.prepared_solution.routes
    )
    assert sorted(
        (a.vehicle_id, a.station_id, round(a.charge_start_second, 6), round(a.energy_kwh, 9))
        for a in full.prepared_solution.charging_actions
    ) == sorted(
        (a.vehicle_id, a.station_id, round(a.charge_start_second, 6), round(a.energy_kwh, 9))
        for a in incremental.prepared_solution.charging_actions
    )


def test_incremental_matches_complete_evaluation(formal, starting_points):
    bundle, _initial, context, evaluator, policy = formal
    compared = 0
    for individual in starting_points:
        evaluation = evaluator.evaluate(individual)
        incremental = DutyIncrementalEvaluator(evaluator)
        incremental.seed(individual)
        for move, candidate in _candidates(
            individual, evaluation, context, bundle, policy
        ):
            full = evaluator.evaluate(candidate)
            fast = incremental.evaluate_after_change(
                individual,
                candidate,
                changed_duty_ids=set(move.changed_duty_ids),
            )
            assert fast.source == "incremental"
            assert fast.individual_fingerprint == candidate.fingerprint
            _assert_same(full, fast)
            compared += 1
    assert compared > 0
    print(f"\nincremental==complete on {compared} candidates")


def test_slice_memo_is_shared_across_incremental_evaluators(formal):
    _bundle, initial, _context, evaluator, _policy = formal
    first = DutyIncrementalEvaluator(evaluator)
    first.seed(initial)
    misses_after_first = evaluator.slice_memo_misses
    second = DutyIncrementalEvaluator(evaluator)
    second.seed(initial)
    assert evaluator.slice_memo_misses == misses_after_first
    assert second.slice_memo_hits == len(initial.duties)
