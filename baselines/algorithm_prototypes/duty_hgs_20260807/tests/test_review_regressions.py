"""v1 2026-08-07: adversarial regressions found before the first trial."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from duty_hgs.charging import ChargingRepairPolicy, repair_changed_duties
from duty_hgs.contracts import CandidateStatus, SearchAccounting
from duty_hgs.crossover import selective_duty_exchange
from duty_hgs.education import evaluate_move
from duty_hgs.evaluation import (
    DutyEvaluationContext,
    DutyFullEvaluator,
    FrozenMappingIdentity,
    mapping_sha256,
)
from duty_hgs.model import (
    DutyChargingSession,
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
)
from duty_hgs.operators import (
    ChargingRetimeMove,
    OpenTripMove,
    RelocateMove,
    ReverseSegmentMove,
    WholeDutyTypeExchangeMove,
    generate_problem_moves,
)
from run_real_input_technical_trial import _build_context
from setp_solver.china81 import China81Bundle
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import PriceParameters
from setp_solver.search.multitrip_schedule import prepare_multitrip_solution
from setp_solver.solution import ChargingAction, Route, Solution

REPO = Path(__file__).resolve().parents[4]


def _policy(evaluator, mode: str | None = None) -> ChargingRepairPolicy:
    return ChargingRepairPolicy(
        strategy="integrated",
        carbon_weight=1.0,
        depot_charge_window_mode=(
            evaluator.context.depot_charge_window_mode if mode is None else mode
        ),
        charge_timing_policy="cost_plus_carbon",
        charge_amount_strategy="just_enough",
        public_station_candidate_mode="parallel",
        carbon_profiles_by_day_offset=None,
    )


def _task_chain(duty: PhysicalVehicleDuty) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(trip.customer_ids) for trip in duty.trips)


def _same_depot_mixed_pair(
    individual: DutyIndividual,
) -> tuple[PhysicalVehicleDuty, PhysicalVehicleDuty]:
    for left_index, left in enumerate(individual.duties):
        for right in individual.duties[left_index + 1 :]:
            if (
                left.home_depot_id == right.home_depot_id
                and {left.vehicle_type, right.vehicle_type} == {"ev", "cv"}
                and _task_chain(left) != _task_chain(right)
            ):
                return left, right
    raise AssertionError("fixture has no same-depot EV/CV pair")


@pytest.mark.parametrize(
    "instance_id",
    (
        "cn-cy-50c-01-V2-LOCATIONS",
        "cn-jjj-50c-01-V2-LOCATIONS",
        "cn-prd-50c-01-V2-LOCATIONS",
    ),
)
def test_registered_mixed_fleet_initializes_all_three_regions(
    instance_id: str,
) -> None:
    bundle, individual, _pi0, context = _build_context(REPO, instance_id)
    evaluator = DutyFullEvaluator(context)
    evaluation = evaluator.evaluate(individual)

    assert evaluation.feasible
    assert sum(
        len(trip.customer_ids)
        for duty in individual.duties
        for trip in duty.trips
    ) == len(bundle.customer_home_depot)
    assert any(duty.vehicle_type == "ev" for duty in individual.duties)
    assert any(duty.vehicle_type == "cv" for duty in individual.duties)
    assert len(individual.duties) == sum(
        int(caps["total_fleet_cap"])
        for caps in bundle.fleet_caps_by_depot.values()
    )
    assert any(not duty.trips for duty in individual.duties)

    duties_by_id = {
        duty.physical_vehicle_id: duty for duty in individual.duties
    }
    idle_exchange = next(
        move
        for move in generate_problem_moves(
            individual,
            evaluation,
            bundle.instance,
        )
        if move.channel == "whole_duty_type_exchange"
        and (
            bool(duties_by_id[move.left_duty_id].trips)
            != bool(duties_by_id[move.right_duty_id].trips)
        )
    )
    left_before = duties_by_id[idle_exchange.left_duty_id]
    right_before = duties_by_id[idle_exchange.right_duty_id]
    changed = idle_exchange.apply(individual)
    changed_by_id = {
        duty.physical_vehicle_id: duty for duty in changed.duties
    }
    assert _task_chain(changed_by_id[idle_exchange.left_duty_id]) == _task_chain(
        right_before
    )
    assert _task_chain(changed_by_id[idle_exchange.right_duty_id]) == _task_chain(
        left_before
    )
    assert {
        (
            duty.physical_vehicle_id,
            duty.vehicle_type,
            duty.home_depot_id,
        )
        for duty in changed.duties
    } == {
        (
            duty.physical_vehicle_id,
            duty.vehicle_type,
            duty.home_depot_id,
        )
        for duty in individual.duties
    }


def test_whole_duty_type_exchange_preserves_registry_and_swaps_tasks(
    evaluated_fixture,
) -> None:
    individual, _evaluator = evaluated_fixture
    left, right = _same_depot_mixed_pair(individual)
    move = WholeDutyTypeExchangeMove(
        action_id="whole-duty-registry-regression",
        channel="whole_duty_type_exchange",
        left_duty_id=left.physical_vehicle_id,
        right_duty_id=right.physical_vehicle_id,
    )

    changed = move.apply(individual)
    changed_by_id = {
        duty.physical_vehicle_id: duty for duty in changed.duties
    }
    left_after = changed_by_id[left.physical_vehicle_id]
    right_after = changed_by_id[right.physical_vehicle_id]

    assert (
        left_after.vehicle_type,
        left_after.home_depot_id,
    ) == (left.vehicle_type, left.home_depot_id)
    assert (
        right_after.vehicle_type,
        right_after.home_depot_id,
    ) == (right.vehicle_type, right.home_depot_id)
    assert _task_chain(left_after) == _task_chain(right)
    assert _task_chain(right_after) == _task_chain(left)
    assert left_after.charging_sessions == ()
    assert right_after.charging_sessions == ()
    assert all(not trip.route_visits for trip in left_after.trips)
    assert all(not trip.route_visits for trip in right_after.trips)


def test_whole_duty_type_exchange_generation_is_switchable_and_lock_safe(
    evaluated_fixture,
) -> None:
    individual, evaluator = evaluated_fixture
    evaluation = evaluator.evaluate(individual)
    enabled = generate_problem_moves(
        individual,
        evaluation,
        evaluator.context.bundle.instance,
    )
    disabled = generate_problem_moves(
        individual,
        evaluation,
        evaluator.context.bundle.instance,
        include_whole_duty_type_exchange=False,
    )
    enabled_exchange = [
        move
        for move in enabled
        if move.channel == "whole_duty_type_exchange"
    ]

    assert enabled_exchange
    assert not any(
        move.channel == "whole_duty_type_exchange" for move in disabled
    )
    for move in enabled_exchange:
        left = next(
            duty
            for duty in individual.duties
            if duty.physical_vehicle_id == move.left_duty_id
        )
        right = next(
            duty
            for duty in individual.duties
            if duty.physical_vehicle_id == move.right_duty_id
        )
        assert left.home_depot_id == right.home_depot_id
        assert {left.vehicle_type, right.vehicle_type} == {"ev", "cv"}

    duties_by_id = {
        duty.physical_vehicle_id: duty for duty in individual.duties
    }
    locked_id = next(
        duty_id
        for move in enabled_exchange
        for duty_id in move.changed_duty_ids
        if duties_by_id[duty_id].trips
        and duties_by_id[duty_id].trips[0].customer_ids
    )
    locked_duty = next(
        duty
        for duty in individual.duties
        if duty.physical_vehicle_id == locked_id
    )
    first_trip = locked_duty.trips[0]
    locked = replace(
        locked_duty,
        trips=(
            replace(
                first_trip,
                locked_customer_prefix=(first_trip.customer_ids[0],),
            ),
            *locked_duty.trips[1:],
        ),
    )
    locked_individual = replace(
        individual,
        duties=tuple(
            locked if duty.physical_vehicle_id == locked_id else duty
            for duty in individual.duties
        ),
    )
    locked_moves = generate_problem_moves(
        locked_individual,
        evaluator.evaluate(locked_individual),
        evaluator.context.bundle.instance,
    )
    assert not any(
        move.channel == "whole_duty_type_exchange"
        and locked_id in move.changed_duty_ids
        for move in locked_moves
    )


def test_charging_retime_is_not_misreported_as_interface_failure(
    evaluated_fixture,
) -> None:
    individual, evaluator = evaluated_fixture
    ev_duty = next(duty for duty in individual.duties if duty.vehicle_type == "ev")
    move = ChargingRetimeMove(
        action_id=f"retime:{ev_duty.physical_vehicle_id}",
        channel="time_varying_carbon_charge",
        duty_id=ev_duty.physical_vehicle_id,
    )

    outcome = evaluate_move(
        individual,
        move,
        evaluator=evaluator,
        charging_policy=_policy(evaluator),
    )

    assert outcome.status in {CandidateStatus.EVALUATED, CandidateStatus.NO_CHANGE}
    assert outcome.error_type is None


def test_cv_reverse_does_not_erase_untouched_ev_charging(
    evaluated_fixture,
) -> None:
    individual, evaluator = evaluated_fixture
    cv_duty = next(duty for duty in individual.duties if duty.vehicle_type == "cv")
    ev_before = next(
        duty for duty in individual.duties if duty.vehicle_type == "ev"
    )
    move = ReverseSegmentMove(
        action_id="reverse-cv-with-untouched-ev",
        channel="route_order",
        duty_id=cv_duty.physical_vehicle_id,
        trip_index=cv_duty.trips[0].trip_index,
        start=0,
        stop=2,
    )

    changed = move.apply(individual)
    ev_after = next(duty for duty in changed.duties if duty.vehicle_type == "ev")
    outcome = evaluate_move(
        individual,
        move,
        evaluator=evaluator,
        charging_policy=_policy(evaluator),
    )

    assert ev_after == ev_before
    assert "changed duty scope" not in (outcome.error or "")


def test_full_gap_first_charge_uses_a_real_prehorizon_day(evaluated_fixture) -> None:
    individual, base = evaluated_fixture
    evaluator = type(base)(
        replace(base.context, depot_charge_window_mode="full_gap")
    )
    ev_duty = next(duty for duty in individual.duties if duty.vehicle_type == "ev")
    move = ChargingRetimeMove(
        action_id=f"retime-full-gap:{ev_duty.physical_vehicle_id}",
        channel="time_varying_carbon_charge",
        duty_id=ev_duty.physical_vehicle_id,
    )

    repaired = repair_changed_duties(
        individual,
        move.apply(individual),
        changed_duty_ids={ev_duty.physical_vehicle_id},
        context=evaluator.context,
        policy=_policy(evaluator, "full_gap"),
    )
    assert evaluator.evaluate(repaired).prepared_solution == repaired.to_solution()


class _OneDutyFromFirst:
    """Choose the first one-duty block in the canonical registry."""

    def __init__(self) -> None:
        self._answers = iter((0, 0))

    def randrange(self, _limit: int) -> int:
        return next(self._answers)


def test_crossover_duplicate_cleanup_cannot_touch_locked_charge_trip() -> None:
    locked = DutyChargingSession(
        trip_index=1,
        station_id="D0",
        energy_kwh=2.0,
        occupancy_minutes=6.0,
        charge_start_second=300.0,
        start_energy_kwh=1.0,
        end_energy_kwh=3.0,
        charging_curve_id="NL_TEST",
        locked=True,
    )
    first = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "EV_D0_1", "ev", "D0", (DutyTrip(1, ("C1",)),), (locked,)
            ),
            PhysicalVehicleDuty(
                "CV_D0_1", "cv", "D0", (DutyTrip(1, ("C2",)),)
            ),
        )
    )
    second = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "EV_D0_1", "ev", "D0", (DutyTrip(1, ("C2",)),), (locked,)
            ),
            PhysicalVehicleDuty(
                "CV_D0_1", "cv", "D0", (DutyTrip(1, ("C1",)),)
            ),
        )
    )

    with pytest.raises(ValueError, match="locked charging"):
        selective_duty_exchange((first, second), _OneDutyFromFirst())


def test_crossover_duplicate_cleanup_removes_an_empty_trip() -> None:
    first = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "CV_D0_1", "cv", "D0", (DutyTrip(1, ("C1",)),)
            ),
            PhysicalVehicleDuty(
                "EV_D0_1", "ev", "D0", (DutyTrip(1, ("C2",)),)
            ),
        )
    )
    second = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "CV_D0_1", "cv", "D0", (DutyTrip(1, ("C2",)),)
            ),
            PhysicalVehicleDuty(
                "EV_D0_1", "ev", "D0", (DutyTrip(1, ("C1",)),)
            ),
        )
    )

    crossed = selective_duty_exchange((first, second), _OneDutyFromFirst())

    emptied = next(
        duty for duty in crossed.child.duties
        if duty.physical_vehicle_id == "EV_D0_1"
    )
    assert emptied.trips == ()
    assert crossed.child.unserved_customers == ("C2",)


def test_crossover_preserves_untouched_non_donor_ev_charging() -> None:
    unlocked = DutyChargingSession(
        trip_index=1,
        station_id="D0",
        energy_kwh=2.0,
        occupancy_minutes=6.0,
        charge_start_second=300.0,
        locked=False,
    )
    parent = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                "CV_D0_1", "cv", "D0", (DutyTrip(1, ("C1",)),)
            ),
            PhysicalVehicleDuty(
                "EV_D0_1", "ev", "D0", (DutyTrip(1, ("C2",)),), (unlocked,)
            ),
            PhysicalVehicleDuty(
                "EV_D0_2", "ev", "D0", (DutyTrip(1, ("C3",)),), (unlocked,)
            ),
        )
    )

    crossed = selective_duty_exchange((parent, parent), _OneDutyFromFirst())

    child_by_id = {
        duty.physical_vehicle_id: duty for duty in crossed.child.duties
    }
    parent_by_id = {
        duty.physical_vehicle_id: duty for duty in parent.duties
    }
    assert child_by_id["EV_D0_1"] == parent_by_id["EV_D0_1"]
    assert child_by_id["EV_D0_2"] == parent_by_id["EV_D0_2"]


def test_solution_adapter_requires_customer_identity_for_station_routes() -> None:
    solution = Solution(
        routes=[
            Route("EV_D0_1#T1", "ev", "D0", ["D0", "F1", "C1", "D0"])
        ],
        charging_actions=[
            ChargingAction(
                vehicle_id="EV_D0_1#T1",
                station_id="F1",
                energy_kwh=2.0,
                occupancy_minutes=6.0,
                charge_start_second=500.0,
            )
        ],
    )

    with pytest.raises(ValueError, match="customer_node_ids"):
        DutyIndividual.from_solution(solution)


def test_accounting_keeps_noop_separate_from_interface_rejections() -> None:
    accounting = SearchAccounting()
    assert not accounting.rejected_actions
    assert not accounting.no_change_actions


def test_locked_first_charge_survives_change_to_later_trip() -> None:
    nodes = [
        Node("D0", "d", 0.0, 0.0, due_time=100_000.0),
        Node("C1", "c", 0.0, 0.0, demand=1.0, due_time=4_000.0),
        Node(
            "C2", "c", 0.0, 0.0, demand=1.0,
            ready_time=6_000.0, due_time=100_000.0,
        ),
        Node(
            "C3", "c", 0.0, 0.0, demand=1.0,
            ready_time=6_000.0, due_time=100_000.0,
        ),
    ]
    matrix = [
        [0.0 if left == right else 1_000.0 for right in range(len(nodes))]
        for left in range(len(nodes))
    ]
    instance = Instance(nodes, matrix, num_cv=0, num_ev=1)
    prices = PriceParameters(
        B_battery_kwh=20.0,
        initial_ev_battery_kwh=0.0,
        depot_charge_power_kw=22.0,
        Q_capacity=10.0,
    )
    initial, _ = prepare_multitrip_solution(
        Solution(
            routes=[
                Route("EV_A", "ev", "D0", ["D0", "C1", "D0"]),
                Route("EV_B", "ev", "D0", ["D0", "C2", "C3", "D0"]),
            ]
        ),
        instance,
        prices,
        depot_charge_window_mode="prev_night",
    )
    first_route_id = min(route.vehicle_id for route in initial.routes)
    reference = DutyIndividual.from_solution(
        initial,
        customer_node_ids={"C1", "C2", "C3"},
        locked_charging_routes={first_route_id},
    )
    changed = ReverseSegmentMove(
        action_id="reverse-later-trip",
        channel="route_order",
        duty_id=reference.duties[0].physical_vehicle_id,
        trip_index=2,
        start=0,
        stop=2,
    ).apply(reference)
    bundle = China81Bundle(
        instance_id="locked-charge-chain-fixture",
        region="technical",
        date="2025-02-12",
        instance=instance,
        time_profile=[],
        prices=prices,
        source_paths={},
        customer_home_depot={"C1": "D0", "C2": "D0", "C3": "D0"},
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
            source_id="locked-charge-chain-fixture",
            value_sha256=mapping_sha256(independent_profit),
            externally_frozen=False,
        ),
        prior_profit={"D0": 0.0},
        theta=0.0,
        carbon_quota_kg=0.0,
        depot_charge_window_mode="prev_night",
    )
    policy = ChargingRepairPolicy(
        strategy="integrated",
        carbon_weight=1.0,
        depot_charge_window_mode="prev_night",
        charge_timing_policy="asap",
        charge_amount_strategy="just_enough",
        public_station_candidate_mode="parallel",
        carbon_profiles_by_day_offset=None,
    )

    repaired = repair_changed_duties(
        reference,
        changed,
        changed_duty_ids={reference.duties[0].physical_vehicle_id},
        context=context,
        policy=policy,
    )

    locked_before = tuple(
        session for session in reference.duties[0].charging_sessions if session.locked
    )
    locked_after = tuple(
        session for session in repaired.duties[0].charging_sessions if session.locked
    )
    assert locked_after == locked_before


def test_relocating_last_customer_removes_the_empty_trip(
    feedback_fixture,
) -> None:
    individual, _ = feedback_fixture
    source = next(
        duty for duty in individual.duties
        if duty.physical_vehicle_id == "CV_D0_2"
    )
    assert source.trips[0].customer_ids == ("C3",)
    move = RelocateMove(
        action_id="remove-last-customer-from-trip",
        channel="relocate",
        source_duty_id="CV_D0_2",
        source_trip_index=1,
        customer_id="C3",
        target_duty_id="CV_D0_1",
        target_trip_index=1,
        target_position=0,
    )

    changed = move.apply(individual)

    emptied = next(
        duty for duty in changed.duties
        if duty.physical_vehicle_id == "CV_D0_2"
    )
    assert emptied.trips == ()
    assert all(
        route.vehicle_id != "CV_D0_2#T1"
        for route in changed.to_solution().routes
    )


def test_open_trip_can_insert_before_an_unlocked_trip(feedback_fixture) -> None:
    individual, _ = feedback_fixture
    move = OpenTripMove(
        action_id="open-first-trip",
        channel="multi_trip",
        duty_id="CV_D0_1",
        source_trip_index=1,
        customer_id="C2",
        new_trip_index=1,
    )

    changed = move.apply(individual)
    duty = next(
        item for item in changed.duties
        if item.physical_vehicle_id == "CV_D0_1"
    )

    assert [trip.trip_index for trip in duty.trips] == [1, 2]
    assert duty.trips[0].customer_ids == ("C2",)
    assert duty.trips[1].customer_ids == ("C1",)
