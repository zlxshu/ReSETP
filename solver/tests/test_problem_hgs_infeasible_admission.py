"""HGS admission of a child whose charging cannot be repaired.

A crossover child that fails charging repair used to be discarded, wasting
the whole iteration.  It is now evaluated with time warp / battery deficits
tolerated and admitted as a penalised infeasible member.  These tests pin the
contract: the tolerant evaluation returns violations instead of raising, the
penalty manager can price them, the strict evaluation still raises, and the
member is marked so the loop never repairs or reports it as an answer.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_problem_hgs_private_technical import (  # noqa: E402
    DEPOT_SEARCH_INSTANCE_ID,
    FLEET_PARAMETER_CLASSES,
    _build_context,
)
from setp_solver.algorithms.problem_hgs.contracts import (  # noqa: E402
    ChargingCandidateStatus,
)
from setp_solver.algorithms.problem_hgs.evaluation import (  # noqa: E402
    CONSTRAINT_AXES,
    DutyFullEvaluator,
)
from setp_solver.algorithms.problem_hgs.population import (  # noqa: E402
    SelfAdaptivePenalty,
    constraint_vector,
)
from setp_solver.check import BATTERY  # noqa: E402


@pytest.fixture(scope="module")
def stripped_ev_child():
    repo = Path(__file__).parents[2]
    _bundle, initial, _neutral_profit, context = _build_context(
        repo,
        DEPOT_SEARCH_INSTANCE_ID,
        fleet_parameters=FLEET_PARAMETER_CLASSES["endogenous"],
    )
    evaluator = DutyFullEvaluator(context)
    feasible = evaluator.evaluate(initial)
    assert feasible.feasible
    # The reference construction is all-CV.  Hand the busiest CV duty's whole
    # task chain to an idle EV of the same depot without any charging: the
    # customer partition is unchanged, but that EV cannot run the chain on one
    # battery -- exactly the child that used to be discarded.
    cv = max(
        (duty for duty in initial.duties if duty.vehicle_type == "cv" and duty.trips),
        key=lambda duty: sum(len(trip.customer_ids) for trip in duty.trips),
    )
    ev = next(
        duty for duty in initial.duties
        if duty.vehicle_type == "ev"
        and duty.home_depot_id == cv.home_depot_id
        and not duty.trips
    )
    moved = tuple(replace(trip, route_visits=()) for trip in cv.trips)
    duties = tuple(
        replace(duty, trips=moved, charging_sessions=(), schedule=None)
        if duty.physical_vehicle_id == ev.physical_vehicle_id
        else replace(duty, trips=(), charging_sessions=(), schedule=None)
        if duty.physical_vehicle_id == cv.physical_vehicle_id
        else duty
        for duty in initial.duties
    )
    child = replace(initial, duties=duties, source="test-stripped-ev")
    return evaluator, feasible, child


def test_strict_evaluation_still_raises(stripped_ev_child):
    evaluator, _feasible, child = stripped_ev_child
    with pytest.raises(ValueError):
        evaluator.evaluate(child)


def test_tolerant_evaluation_returns_penalised_violations(stripped_ev_child):
    evaluator, feasible, child = stripped_ev_child
    full = evaluator.evaluate(child, tolerate_infeasible=True)
    assert not full.feasible
    assert full.charging_candidate_status is ChargingCandidateStatus.REJECTED_CHARGING
    assert any(item.type == BATTERY for item in full.violations)
    vector = constraint_vector(full)
    assert vector[CONSTRAINT_AXES.index(f"{BATTERY}:kWh")] > 0.0
    # The stripped duty pays no electricity, so raw cost drops; the penalty
    # manager must rank the member below the feasible incumbent anyway.
    assert full.total_cost < feasible.total_cost
    # pagmo2's self-adaptive penalty lifts the best infeasible member to the
    # best feasible cost, then scales by the feasible population's spread;
    # give it a spread so the ordering is strict.
    worse = replace(feasible, total_cost=feasible.total_cost + 100.0)
    penalty = SelfAdaptivePenalty()
    penalty.update((feasible, worse, feasible, full))
    assert penalty.cost(full) > penalty.cost(feasible)
