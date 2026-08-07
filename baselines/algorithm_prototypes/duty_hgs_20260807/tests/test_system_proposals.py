"""System proposal and strong-route operator regressions."""

from __future__ import annotations

from dataclasses import dataclass, replace

import duty_hgs.charging as charging_module
import pytest
from duty_hgs.model import DutyIndividual, DutyTrip, PhysicalVehicleDuty
from duty_hgs.charging import (
    ChargingRepairPolicy,
    _repair_one_ev_duty_candidates,
    build_ev_duty_charging_candidates,
)
from duty_hgs.evaluation import (
    DutyEvaluationContext,
    DutyFullEvaluator,
    FrozenMappingIdentity,
    mapping_sha256,
)
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
from setp_solver.china81 import China81Bundle
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.search.multitrip_schedule import route_timing
from setp_solver.solution import Route


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


def test_whole_duty_charging_keeps_depot_and_public_route_options(
    evaluated_fixture,
    monkeypatch,
) -> None:
    individual, evaluator = evaluated_fixture
    duty = next(item for item in individual.duties if item.vehicle_type == "ev")
    original_trip = duty.trips[0]

    def fake_route_candidates(route, *args, **kwargs):
        del args, kwargs
        public = replace(
            route,
            node_sequence=[
                route.home_depot_id,
                original_trip.customer_ids[0],
                "S_beijing",
                *original_trip.customer_ids[1:],
                route.home_depot_id,
            ],
        )
        return [
            ("depot", route, []),
            ("public", public, []),
        ]

    def fake_rebuild(reference, candidate, routes, actions, **kwargs):
        del reference, actions, kwargs
        rebuilt_trip = replace(
            candidate.trips[0],
            route_visits=tuple(routes[0].node_sequence[1:-1]),
        )
        return replace(candidate, trips=(rebuilt_trip,))

    monkeypatch.setattr(
        charging_module,
        "repair_route_charging_candidates",
        fake_route_candidates,
    )
    monkeypatch.setattr(
        charging_module,
        "_rebuild_ev_duty",
        fake_rebuild,
    )
    policy = ChargingRepairPolicy(
        strategy="integrated",
        carbon_weight=1.0,
        depot_charge_window_mode=evaluator.context.depot_charge_window_mode,
        charge_timing_policy="cost_plus_carbon",
        charge_amount_strategy="just_enough",
        public_station_candidate_mode="parallel",
        carbon_profiles_by_day_offset=None,
    )

    candidates = tuple(
        _repair_one_ev_duty_candidates(
            duty,
            duty,
            context=evaluator.context,
            policy=policy,
            amount_strategies=("just_enough",),
        )
    )

    assert len(candidates) == 2
    assert {
        "S_beijing" in candidate.trips[0].effective_route_visits
        for candidate in candidates
    } == {False, True}


def test_public_station_alternatives_reach_real_full_duty_evaluation() -> None:
    nodes = [
        Node("D0", "d", 0.0, 0.0, due_time=50_000.0),
        Node(
            "C1",
            "c",
            0.0,
            0.0,
            demand=100.0,
            ready_time=20_000.0,
            due_time=50_000.0,
        ),
        Node("F1", "f", 0.0, 0.0, due_time=50_000.0, charge_power_kw=60.0),
        Node("F2", "f", 0.0, 0.0, due_time=50_000.0, charge_power_kw=60.0),
    ]
    instance = Instance(
        nodes,
        [
            [0.0, 100_000.0, 20_000.0, 20_000.0],
            [100_000.0, 0.0, 20_000.0, 20_000.0],
            [20_000.0, 20_000.0, 0.0, 20_000.0],
            [20_000.0, 20_000.0, 20_000.0, 0.0],
        ],
        num_cv=0,
        num_ev=1,
    )
    prices = PriceParameters(
        B_battery_kwh=80.0,
        initial_ev_battery_kwh=0.0,
        revenue_per_kg=100.0,
        fairness_theta=0.0,
    )
    profile = [
        {
            "time_index": index,
            "horizon_second_start": float(index * 1800),
            "actual_gco2_per_kwh": 200.0,
            "forecast_gco2_per_kwh": 200.0,
        }
        for index in range(48)
    ]
    bundle = China81Bundle(
        instance_id="technical-public-alternatives",
        region="technical",
        date="2025-02-12",
        instance=instance,
        time_profile=profile,
        prices=prices,
        source_paths={},
        customer_home_depot={"C1": "D0"},
        price_area_by_city={},
        carbon_source_column_by_city={},
        diesel_zone_by_city={},
        diesel_price_by_city={},
        fleet_caps_by_depot={
            "D0": {"num_cv": 0, "num_ev": 1, "total_fleet_cap": 1}
        },
        charger_scenario_by_node={},
        fleet_cap_semantics="technical-fixture",
        diesel_price_source_id="technical-fixture",
        static_input_authority="technical-fixture",
        road_matrix_authority="technical-fixture",
        runtime_parameter_authority="technical-fixture",
        fleet_authority="technical-fixture",
        model_config={},
        formal_search_allowed=False,
    )
    independent_profit = {"D0": 1.0}
    context = DutyEvaluationContext(
        bundle=bundle,
        independent_profit=independent_profit,
        independent_profit_identity=FrozenMappingIdentity(
            source_id="technical-public-alternatives",
            value_sha256=mapping_sha256(independent_profit),
            externally_frozen=False,
        ),
        prior_profit={"D0": 0.0},
        theta=0.0,
        carbon_quota_kg=0.0,
        depot_charge_window_mode="same_day_predeparture",
        fairness_enabled=False,
    )
    duty = PhysicalVehicleDuty(
        "EV_D0_1",
        "ev",
        "D0",
        (DutyTrip(1, ("C1",)),),
    )
    policy = ChargingRepairPolicy(
        strategy="integrated",
        carbon_weight=1.0,
        depot_charge_window_mode="same_day_predeparture",
        charge_timing_policy="cost_plus_carbon",
        charge_amount_strategy="just_enough",
        public_station_candidate_mode="parallel",
        carbon_profiles_by_day_offset=None,
    )

    candidates = tuple(
        build_ev_duty_charging_candidates(
            duty,
            context=context,
            policy=policy,
            other_session_end_seconds_by_station={
                "F1": (5_000.0,),
                "F2": (6_000.0,),
            },
        )
    )
    assert candidates
    evaluator = DutyFullEvaluator(context)
    by_station = {}
    for candidate in candidates:
        stations = frozenset(
            session.station_id
            for session in candidate.charging_sessions
            if session.station_id in {"F1", "F2"}
        )
        result = evaluator.evaluate(DutyIndividual(duties=(candidate,)))
        if result.feasible and len(stations) == 1:
            by_station[next(iter(stations))] = (candidate, result)

    assert set(by_station) == {"F1", "F2"}
    assert all(result.feasible for _, result in by_station.values())
    assert len(
        {
            tuple(
                trip.effective_route_visits
                for trip in candidate.trips
            )
            for candidate, _ in by_station.values()
        }
    ) == 2
    assert any(
        any(
            session.station_id == "F1"
            and session.charge_start_second == pytest.approx(5_000.0)
            for session in candidate.charging_sessions
        )
        for candidate in candidates
    )
    assert any(
        any(
            session.station_id == "F2"
            and session.charge_start_second == pytest.approx(6_000.0)
            for session in candidate.charging_sessions
        )
        for candidate in candidates
    )

    for candidate, result in by_station.values():
        solution = DutyIndividual(duties=(candidate,)).to_solution()
        route = solution.routes[0]
        actions = list(solution.charging_actions)
        depot_action = next(
            action for action in actions if action.station_id == "D0"
        )
        public_action = next(
            action for action in actions if action.station_id in {"F1", "F2"}
        )
        trip = result.certificate.trips[0]
        depot_end = (
            float(depot_action.charge_start_second)
            + float(depot_action.occupancy_minutes) * 60.0
        )
        assert depot_end <= float(trip.departure_second) + 1e-6
        assert float(trip.departure_second) <= float(
            public_action.charge_start_second
        )

        after_public = replace(
            depot_action,
            charge_start_second=float(public_action.charge_start_second) + 1.0,
        )
        timing = route_timing(
            route,
            instance,
            prices,
            charging_actions=[after_public, public_action],
            validate_battery=False,
        )
        assert timing.earliest_departure_second < float(
            after_public.charge_start_second
        )


def test_two_trip_amount_combinations_reach_full_duty_evaluation() -> None:
    nodes = [
        Node("D0", "d", 0.0, 0.0, due_time=100_000.0),
        Node(
            "C1",
            "c",
            0.0,
            0.0,
            demand=100.0,
            ready_time=20_000.0,
            due_time=30_000.0,
        ),
        Node(
            "C2",
            "c",
            0.0,
            0.0,
            demand=100.0,
            ready_time=50_000.0,
            due_time=70_000.0,
        ),
    ]
    instance = Instance(
        nodes,
        [
            [0.0, 20_000.0, 20_000.0],
            [20_000.0, 0.0, 20_000.0],
            [20_000.0, 20_000.0, 0.0],
        ],
        num_cv=0,
        num_ev=1,
    )
    prices = PriceParameters(
        B_battery_kwh=80.0,
        initial_ev_battery_kwh=0.0,
        revenue_per_kg=100.0,
        fairness_theta=0.0,
    )
    profile = [
        {
            "time_index": index,
            "horizon_second_start": float(index * 1800),
            "actual_gco2_per_kwh": 200.0,
            "forecast_gco2_per_kwh": 200.0,
        }
        for index in range(48)
    ]
    bundle = China81Bundle(
        instance_id="technical-two-trip-charge-combinations",
        region="technical",
        date="2025-02-12",
        instance=instance,
        time_profile=profile,
        prices=prices,
        source_paths={},
        customer_home_depot={"C1": "D0", "C2": "D0"},
        price_area_by_city={},
        carbon_source_column_by_city={},
        diesel_zone_by_city={},
        diesel_price_by_city={},
        fleet_caps_by_depot={
            "D0": {"num_cv": 0, "num_ev": 1, "total_fleet_cap": 1}
        },
        charger_scenario_by_node={},
        fleet_cap_semantics="technical-fixture",
        diesel_price_source_id="technical-fixture",
        static_input_authority="technical-fixture",
        road_matrix_authority="technical-fixture",
        runtime_parameter_authority="technical-fixture",
        fleet_authority="technical-fixture",
        model_config={},
        formal_search_allowed=False,
    )
    independent_profit = {"D0": 1.0}
    context = DutyEvaluationContext(
        bundle=bundle,
        independent_profit=independent_profit,
        independent_profit_identity=FrozenMappingIdentity(
            source_id="technical-two-trip-charge-combinations",
            value_sha256=mapping_sha256(independent_profit),
            externally_frozen=False,
        ),
        prior_profit={"D0": 0.0},
        theta=0.0,
        carbon_quota_kg=0.0,
        depot_charge_window_mode="same_day_predeparture",
        fairness_enabled=False,
    )
    duty = PhysicalVehicleDuty(
        "EV_D0_1",
        "ev",
        "D0",
        (
            DutyTrip(1, ("C1",)),
            DutyTrip(2, ("C2",)),
        ),
    )
    policy = ChargingRepairPolicy(
        strategy="integrated",
        carbon_weight=1.0,
        depot_charge_window_mode="same_day_predeparture",
        charge_timing_policy="cost_plus_carbon",
        charge_amount_strategy="just_enough",
        public_station_candidate_mode="parallel",
        carbon_profiles_by_day_offset=None,
    )

    candidates = tuple(
        _repair_one_ev_duty_candidates(
            duty,
            duty,
            context=context,
            policy=policy,
            amount_strategies=("just_enough", "full"),
        )
    )
    evaluator = DutyFullEvaluator(context)
    feasible = [
        evaluator.evaluate(DutyIndividual(duties=(candidate,)))
        for candidate in candidates
    ]
    feasible = [result for result in feasible if result.feasible]

    assert len(candidates) >= 2
    assert len(feasible) >= 2
    assert len({round(result.total_cost, 9) for result in feasible}) >= 2
    for result in feasible:
        trips = tuple(
            sorted(result.certificate.trips, key=lambda trip: trip.trip_index)
        )
        assert len(trips) == 2
        assert {trip.physical_vehicle_id for trip in trips} == {"EV_D0_1"}
        assert float(trips[1].start_battery_kwh) == pytest.approx(
            float(trips[0].end_battery_kwh)
            + float(trips[0].charge_energy_kwh or 0.0)
        )

    timing_candidates = tuple(
        build_ev_duty_charging_candidates(
            duty,
            context=context,
            policy=policy,
            other_session_end_seconds_by_station={"D0": (123.0,)},
        )
    )
    assert any(
        any(
            session.station_id == "D0"
            and session.charge_start_second == pytest.approx(123.0)
            for session in candidate.charging_sessions
        )
        for candidate in timing_candidates
    )
