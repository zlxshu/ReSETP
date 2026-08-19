import random
from types import SimpleNamespace

from setp_solver.algorithms.problem_hgs.crossover import (
    trip_assignment_exchange,
)
from setp_solver.algorithms.problem_hgs.model import (
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
)
from setp_solver.algorithms.problem_hgs.operators import (
    DutySkeletonMove,
    ExchangeUnservedMove,
)
from setp_solver.algorithms.problem_hgs.contracts import CandidateStatus
from setp_solver.algorithms.problem_hgs.initialization import (
    build_initial_population,
    build_dynamic_warm_start_population,
)


def _duty(customers: tuple[str, ...]) -> PhysicalVehicleDuty:
    return PhysicalVehicleDuty(
        physical_vehicle_id="CV_D0_1",
        vehicle_type="cv",
        home_depot_id="D0",
        trips=(DutyTrip(1, customers),) if customers else (),
    )


def test_complete_skeleton_reconciles_revealed_and_dropped_customers() -> None:
    before = DutyIndividual(
        duties=(_duty(("C1", "C2")),),
        unserved_customers=("C3",),
    )
    move = DutySkeletonMove(
        action_id="dynamic-reveal",
        channel="test",
        replacements=(("CV_D0_1", (("C3", "C1"),)),),
        dynamic_future_only=True,
    )

    after = move.apply(before)

    assert after.duties[0].trips[0].customer_ids == ("C3", "C1")
    assert after.unserved_customers == ("C2",)


def test_complete_skeleton_rejects_unknown_customer() -> None:
    before = DutyIndividual(duties=(_duty(("C1",)),))
    move = DutySkeletonMove(
        action_id="unknown",
        channel="test",
        replacements=(("CV_D0_1", (("C1", "C9"),)),),
    )

    try:
        move.apply(before)
    except ValueError as error:
        assert "outside the candidate universe" in str(error)
    else:
        raise AssertionError("unknown customer was accepted")


def test_fast_crossover_accepts_donor_routing_a_newly_revealed_customer() -> None:
    main = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                physical_vehicle_id="CV_D0_1",
                vehicle_type="cv",
                home_depot_id="D0",
                trips=(DutyTrip(1, ("C1",), locked_customer_prefix=("C1",)),),
            ),
            PhysicalVehicleDuty(
                physical_vehicle_id="CV_D0_2",
                vehicle_type="cv",
                home_depot_id="D0",
                trips=(),
            ),
        ),
        unserved_customers=("C2",),
    )
    donor = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                physical_vehicle_id="CV_D0_1",
                vehicle_type="cv",
                home_depot_id="D0",
                trips=(DutyTrip(1, ("C1",), locked_customer_prefix=("C1",)),),
            ),
            PhysicalVehicleDuty(
                physical_vehicle_id="CV_D0_2",
                vehicle_type="cv",
                home_depot_id="D0",
                trips=(DutyTrip(1, ("C2",)),),
            ),
        ),
    )

    crossed = trip_assignment_exchange(
        (main, donor),
        random.Random(1),
        {"C1": (0.0, 0.0), "C2": (1.0, 0.0)},
    )

    served = {
        customer
        for duty in crossed.child.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }
    assert served == {"C1", "C2"}
    assert crossed.child.unserved_customers == ()


def test_fast_crossover_can_reassign_across_vehicle_type_and_depot() -> None:
    parent = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                physical_vehicle_id="CV_D0_1",
                vehicle_type="cv",
                home_depot_id="D0",
                trips=(DutyTrip(1, ("C1",)),),
            ),
            PhysicalVehicleDuty(
                physical_vehicle_id="EV_D1_1",
                vehicle_type="ev",
                home_depot_id="D1",
                trips=(),
            ),
        ),
    )

    crossed = trip_assignment_exchange(
        (parent, parent),
        random.Random(1),
        {"C1": (0.0, 0.0)},
    )

    by_id = {
        duty.physical_vehicle_id: duty for duty in crossed.child.duties
    }
    assert by_id["CV_D0_1"].trips == ()
    assert by_id["EV_D1_1"].trips[0].customer_ids == ("C1",)
    assert by_id["EV_D1_1"].vehicle_type == "ev"
    assert by_id["EV_D1_1"].home_depot_id == "D1"
    assert crossed.child.unserved_customers == ()


def test_exchange_unserved_keeps_ejected_customer_explicit_for_repair() -> None:
    before = DutyIndividual(
        duties=(_duty(("C1", "C2")),),
        unserved_customers=("C3",),
    )
    move = ExchangeUnservedMove(
        action_id="exchange-C3-C2",
        channel="test",
        duty_id="CV_D0_1",
        trip_index=1,
        served_customer_id="C2",
        unserved_customer_id="C3",
    )

    after = move.apply(before)

    assert after.duties[0].trips[0].customer_ids == ("C1", "C3")
    assert after.unserved_customers == ("C2",)


def test_dynamic_warm_start_keeps_looking_until_one_candidate_is_feasible(
    monkeypatch,
) -> None:
    initial = DutyIndividual(
        duties=(_duty(("C1",)),),
        unserved_customers=("C2",),
    )
    complete_but_infeasible = DutyIndividual(
        duties=(_duty(("C1", "C2")),),
    )
    later_feasible = DutyIndividual(
        duties=(_duty(("C2", "C1")),),
    )
    infeasible_evaluation = SimpleNamespace(feasible=False, violations=())
    feasible_evaluation = SimpleNamespace(feasible=True, violations=())

    class _Evaluator:
        full_calls = 0

        def evaluate(self, candidate):
            self.full_calls += 1
            return infeasible_evaluation

    monkeypatch.setattr(
        "setp_solver.algorithms.problem_hgs.initialization.regret2_repair",
        lambda *args, **kwargs: (
            complete_but_infeasible,
            infeasible_evaluation,
            (),
        ),
    )
    move = SimpleNamespace(action_id="late-feasible")
    monkeypatch.setattr(
        "setp_solver.algorithms.problem_hgs.initialization.insertion_moves",
        lambda *args, **kwargs: (move,),
    )
    monkeypatch.setattr(
        "setp_solver.algorithms.problem_hgs.initialization.evaluate_move",
        lambda *args, **kwargs: SimpleNamespace(
            status=CandidateStatus.EVALUATED,
            candidate=later_feasible,
            evaluation=feasible_evaluation,
            error_type=None,
            error=None,
        ),
    )

    result = build_dynamic_warm_start_population(
        initial,
        evaluator=_Evaluator(),
        charging_policy=SimpleNamespace(),
        penalized_cost=lambda evaluation: 0.0,
        requested_size=2,
    )

    assert result.actual_size == 2
    assert any(evaluation.feasible for evaluation in result.evaluations)
    assert later_feasible in result.candidates


def test_random_population_stays_bounded_but_keeps_looking_for_feasible_seed(
    monkeypatch,
) -> None:
    initial = DutyIndividual(
        duties=(_duty(("C1",)),),
        unserved_customers=("C2",),
    )
    complete_but_infeasible = DutyIndividual(
        duties=(_duty(("C1", "C2")),),
        source="infeasible-random",
    )
    later_feasible = DutyIndividual(
        duties=(_duty(("C2", "C1")),),
        source="feasible-random",
    )
    incomplete_evaluation = SimpleNamespace(feasible=False, violations=())
    infeasible_evaluation = SimpleNamespace(feasible=False, violations=())
    feasible_evaluation = SimpleNamespace(feasible=True, violations=())

    class _Evaluator:
        full_calls = 0
        context = SimpleNamespace()

        def evaluate(self, candidate):
            self.full_calls += 1
            if candidate is later_feasible:
                return feasible_evaluation
            if candidate is complete_but_infeasible:
                return infeasible_evaluation
            return incomplete_evaluation

    class _Move:
        def __init__(self, candidate):
            self.candidate = candidate
            self.changed_duty_ids = ("CV_D0_1",)

        def apply(self, _initial):
            return self.candidate

    class _RouteEngine:
        def random_skeleton_move(self, _initial, *, draw_index):
            return _Move(
                complete_but_infeasible
                if draw_index == 0
                else later_feasible
            )

    monkeypatch.setattr(
        "setp_solver.algorithms.problem_hgs.initialization.repair_changed_duties",
        lambda _initial, candidate, **_kwargs: candidate,
    )

    result = build_initial_population(
        initial,
        evaluator=_Evaluator(),
        charging_policy=SimpleNamespace(),
        route_engine=_RouteEngine(),
        requested_size=2,
        random_seed=7,
        max_random_attempts=None,
        require_complete_feasible=True,
        stop_requested=lambda: False,
    )

    assert result.actual_size == 2
    assert len(result.candidates) == 2
    assert len(result.attempts) == 2
    assert later_feasible in result.candidates
    assert not result.attempts_exhausted
