"""System proposal and strong-route operator regressions."""

from __future__ import annotations

from dataclasses import dataclass

from duty_hgs.model import DutyIndividual, DutyTrip, PhysicalVehicleDuty
from duty_hgs.charging import ChargingRepairPolicy
from duty_hgs.education import evaluate_move
from duty_hgs.initialization import build_initial_population
from duty_hgs.operators import (
    RelocateSegmentMove,
    ReverseSegmentMove,
    SwapTailsMove,
    WholeTripExchangeMove,
)
from duty_hgs.proposals import (
    InterleavedProposalEngine,
    MechanismProposalEngine,
)
from duty_hgs.pyvrp_proposals import (
    PyVRPDutyRouteProposalEngine,
    _distance_cost_units,
    _migration_components,
    _money_units,
)


def _two_trip_individual() -> DutyIndividual:
    return DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "CV_D0_1",
                "cv",
                "D0",
                (DutyTrip(1, ("A", "B", "C")),),
            ),
            PhysicalVehicleDuty(
                "CV_D0_2",
                "cv",
                "D0",
                (DutyTrip(1, ("D", "E")),),
            ),
        ),
        source="strong-route-test",
    )


def _customers(individual, duty_id):
    duty = next(
        duty for duty in individual.duties
        if duty.physical_vehicle_id == duty_id
    )
    return tuple(trip.customer_ids for trip in duty.trips)


def test_or_opt_moves_a_consecutive_segment_between_vehicle_slots() -> None:
    individual = _two_trip_individual()
    moved = RelocateSegmentMove(
        action_id="or-opt-test",
        channel="route_order",
        source_duty_id="CV_D0_1",
        source_trip_index=1,
        start=1,
        stop=3,
        target_duty_id="CV_D0_2",
        target_trip_index=1,
        target_position=1,
    ).apply(individual)

    assert _customers(moved, "CV_D0_1") == (("A",),)
    assert _customers(moved, "CV_D0_2") == (("D", "B", "C", "E"),)


def test_two_opt_star_exchanges_route_suffixes() -> None:
    individual = _two_trip_individual()
    moved = SwapTailsMove(
        action_id="two-opt-star-test",
        channel="route_order",
        left_duty_id="CV_D0_1",
        left_trip_index=1,
        left_cut=2,
        right_duty_id="CV_D0_2",
        right_trip_index=1,
        right_cut=1,
    ).apply(individual)

    assert _customers(moved, "CV_D0_1") == (("A", "B", "E"),)
    assert _customers(moved, "CV_D0_2") == (("D", "C"),)


def test_whole_trip_exchange_preserves_physical_vehicle_registry() -> None:
    individual = _two_trip_individual()
    moved = WholeTripExchangeMove(
        action_id="whole-trip-test",
        channel="depot_collaboration",
        left_duty_id="CV_D0_1",
        left_trip_index=1,
        right_duty_id="CV_D0_2",
        right_trip_index=1,
    ).apply(individual)

    assert _customers(moved, "CV_D0_1") == (("D", "E"),)
    assert _customers(moved, "CV_D0_2") == (("A", "B", "C"),)
    assert tuple(
        duty.physical_vehicle_id for duty in moved.duties
    ) == ("CV_D0_1", "CV_D0_2")


def test_route_kernel_diff_splits_by_customer_migration_connectivity() -> None:
    individual = DutyIndividual(
        duties=(
            PhysicalVehicleDuty("CV_D0_1", "cv", "D0", (DutyTrip(1, ("A", "B")),)),
            PhysicalVehicleDuty("CV_D0_2", "cv", "D0", (DutyTrip(1, ("C",)),)),
            PhysicalVehicleDuty("CV_D0_3", "cv", "D0", (DutyTrip(1, ("D", "E")),)),
        )
    )
    replacements = (
        ("CV_D0_1", (("A", "C"),)),
        ("CV_D0_2", (("B",),)),
        ("CV_D0_3", (("E", "D"),)),
    )

    components = _migration_components(individual, replacements)

    assert components == (
        (
            ("CV_D0_1", (("A", "C"),)),
            ("CV_D0_2", (("B",),)),
        ),
        (("CV_D0_3", (("E", "D"),)),),
    )


def test_route_kernel_uses_one_currency_scale_for_fixed_and_distance_costs() -> None:
    assert _money_units(170.0) == 17_000_000
    assert _distance_cost_units(1_000.0, 0.78) == 78_000
    assert _distance_cost_units(1_000.0, 0.67) == 67_000


def test_random_route_skeletons_seed_distinct_evaluated_population(
    evaluated_fixture,
) -> None:
    individual, evaluator = evaluated_fixture
    policy = ChargingRepairPolicy(
        strategy="integrated",
        carbon_weight=1.0,
        depot_charge_window_mode=evaluator.context.depot_charge_window_mode,
        charge_timing_policy="cost_plus_carbon",
        charge_amount_strategy="just_enough",
        public_station_candidate_mode="parallel",
        carbon_profiles_by_day_offset=None,
    )
    engine = PyVRPDutyRouteProposalEngine(
        evaluator.context,
        individual,
        random_seed=11,
    )

    result = build_initial_population(
        individual,
        evaluator=evaluator,
        charging_policy=policy,
        route_engine=engine,
        requested_size=3,
        random_seed=101,
        max_random_attempts=20,
    )

    assert len(result.candidates) == 3
    assert result.actual_size == 3
    assert not result.attempts_exhausted
    assert result.full_evaluation_count >= 3
    assert result.wall_seconds >= 0.0
    assert len({candidate.fingerprint for candidate in result.candidates}) == 3
    assert len(result.evaluations) == 3
    assert all(evaluation.individual_fingerprint == candidate.fingerprint
               for candidate, evaluation in zip(
                   result.candidates, result.evaluations, strict=True
               ))
    assert sum(row.status == "ADMITTED" for row in result.attempts) == 2

    exhausted = build_initial_population(
        individual,
        evaluator=evaluator,
        charging_policy=policy,
        route_engine=engine,
        requested_size=3,
        random_seed=101,
        max_random_attempts=0,
    )
    assert exhausted.actual_size == 1
    assert exhausted.attempts_exhausted


@dataclass(frozen=True)
class _Provider:
    source_id: str
    moves: tuple

    @property
    def identity_sha256(self):
        return (self.source_id.encode("utf-8").hex() + "0" * 64)[:64]

    def propose(
        self,
        individual,
        evaluation,
        instance,
        *,
        include_whole_duty_type_exchange,
    ):
        del individual, evaluation, instance, include_whole_duty_type_exchange
        return self.moves


def test_interleaved_proposals_preserve_each_channel_without_a_cutoff(
    feedback_fixture,
) -> None:
    individual, evaluator = feedback_fixture
    evaluation = evaluator.evaluate(individual)
    route_moves = (
        ReverseSegmentMove("r1", "route", "CV_D0_1", 1, 0, 2),
        ReverseSegmentMove("r2", "route", "CV_D0_1", 1, 0, 2),
    )
    mechanism_moves = (
        WholeTripExchangeMove(
            "m1",
            "mechanism",
            "CV_D0_1",
            1,
            "CV_D0_2",
            1,
        ),
    )
    engine = InterleavedProposalEngine(
        (_Provider("route", route_moves), _Provider("mechanism", mechanism_moves))
    )

    proposed = tuple(
        engine.propose(
            individual,
            evaluation,
            evaluator.context.bundle.instance,
            include_whole_duty_type_exchange=True,
        )
    )

    assert [move.action_id for move in proposed] == ["r1", "m1", "r2"]


def test_pyvrp_route_kernel_proposes_through_unique_physical_slots(
    evaluated_fixture,
) -> None:
    individual, evaluator = evaluated_fixture
    before = evaluator.evaluate(individual)
    engine = PyVRPDutyRouteProposalEngine(
        evaluator.context,
        individual,
        random_seed=11,
    )

    moves = tuple(
        engine.propose(
            individual,
            before,
            evaluator.context.bundle.instance,
            include_whole_duty_type_exchange=True,
        )
    )

    assert len(moves) == 1
    candidate = moves[0].apply(individual)
    assert tuple(
        (duty.physical_vehicle_id, duty.vehicle_type, duty.home_depot_id)
        for duty in candidate.duties
    ) == tuple(
        (duty.physical_vehicle_id, duty.vehicle_type, duty.home_depot_id)
        for duty in individual.duties
    )
    outcome = evaluate_move(
        individual,
        moves[0],
        evaluator=evaluator,
        charging_policy=ChargingRepairPolicy(
            strategy="integrated",
            carbon_weight=1.0,
            depot_charge_window_mode=(
                evaluator.context.depot_charge_window_mode
            ),
            charge_timing_policy="cost_plus_carbon",
            charge_amount_strategy="just_enough",
            public_station_candidate_mode="parallel",
            carbon_profiles_by_day_offset=None,
        ),
    )
    assert outcome.evaluated
    assert outcome.evaluation is not None
    assert outcome.evaluation.feasible


def test_active_charging_candidates_use_the_same_full_acceptance_chain(
    evaluated_fixture,
) -> None:
    individual, evaluator = evaluated_fixture
    before = evaluator.evaluate(individual)
    policy = ChargingRepairPolicy(
        strategy="integrated",
        carbon_weight=1.0,
        depot_charge_window_mode=evaluator.context.depot_charge_window_mode,
        charge_timing_policy="cost_plus_carbon",
        charge_amount_strategy="just_enough",
        public_station_candidate_mode="parallel",
        carbon_profiles_by_day_offset=None,
    )
    engine = MechanismProposalEngine(evaluator.context, policy)
    charging_move = next(
        move
        for move in engine.propose(
            individual,
            before,
            evaluator.context.bundle.instance,
            include_whole_duty_type_exchange=True,
        )
        if move.channel == "time_varying_carbon_charge"
    )

    outcome = evaluate_move(
        individual,
        charging_move,
        evaluator=evaluator,
        charging_policy=policy,
    )

    assert outcome.evaluated
    assert outcome.evaluation is not None
    assert outcome.evaluation.feasible
