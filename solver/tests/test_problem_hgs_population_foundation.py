from __future__ import annotations

from dataclasses import dataclass
from math import isclose, isinf

from setp_solver.algorithms.problem_hgs.model import (
    DutyChargingSession,
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
)
from setp_solver.algorithms.problem_hgs.population import (
    PopulationParameters,
    SelfAdaptivePenalty,
    broken_pairs_distance,
    constraint_vector,
)
from setp_solver.algorithms.problem_hgs.evaluation import (
    CONSTRAINT_AXES,
    _payload_capacity_magnitude,
)


@dataclass(frozen=True)
class _Evaluation:
    total_cost: float
    violation_axes: tuple[str, ...] = ()
    violation_magnitudes: tuple[float, ...] = ()


def _individual(charge_start_second: float) -> DutyIndividual:
    return DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                physical_vehicle_id="EV_D0_1",
                vehicle_type="ev",
                home_depot_id="D0",
                trips=(DutyTrip(1, ("C1", "C2")),),
                charging_sessions=(
                    DutyChargingSession(
                        trip_index=1,
                        station_id="D0",
                        energy_kwh=10.0,
                        occupancy_minutes=30.0,
                        charge_start_second=charge_start_second,
                    ),
                ),
            ),
        ),
    )


def _ordered_individual(customers: tuple[str, ...]) -> DutyIndividual:
    return DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                physical_vehicle_id="CV_D0_1",
                vehicle_type="cv",
                home_depot_id="D0",
                trips=(DutyTrip(1, customers),),
            ),
        ),
    )


def _evaluation(
    objective: float,
    capacity: float = 0.0,
    time_window: float = 0.0,
) -> _Evaluation:
    values = ((CONSTRAINT_AXES[0], capacity), (CONSTRAINT_AXES[2], time_window))
    active = tuple((axis, value) for axis, value in values if value > 0.0)
    return _Evaluation(objective, tuple(axis for axis, _ in active), tuple(value for _, value in active))


def test_copied_population_defaults_match_hgs_0122() -> None:
    params = PopulationParameters.copied_hgs_defaults()

    assert params == PopulationParameters(
        min_pop_size=25,
        generation_size=40,
        num_elite=4,
        num_close=5,
        tournament_size=2,
        lb_diversity=0.1,
        ub_diversity=0.5,
    )


def test_duty_diversity_leaves_continuous_charging_to_complete_cost() -> None:
    assert broken_pairs_distance(_individual(0.0), _individual(3600.0)) == 0.0


def test_duty_diversity_sees_vehicle_type_with_the_same_route() -> None:
    cv = _ordered_individual(("C1", "C2"))
    ev = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                physical_vehicle_id="EV_D0_1",
                vehicle_type="ev",
                home_depot_id="D0",
                trips=(DutyTrip(1, ("C1", "C2")),),
            ),
        ),
    )

    assert broken_pairs_distance(cv, ev) == 2 / 3


def test_duty_diversity_ignores_interchangeable_static_asset_labels() -> None:
    first = _ordered_individual(("C1", "C2"))
    second = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                physical_vehicle_id="CV_D0_2",
                vehicle_type="cv",
                home_depot_id="D0",
                trips=(DutyTrip(1, ("C1", "C2")),),
            ),
        ),
    )

    assert broken_pairs_distance(first, second) == 0.0


def test_duty_diversity_sees_committed_physical_asset_identity() -> None:
    first = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                physical_vehicle_id="CV_D0_1",
                vehicle_type="cv",
                home_depot_id="D0",
                trips=(DutyTrip(1, ("C1", "C2"), ("C1",)),),
                has_dynamic_commitment=True,
            ),
        ),
    )
    second = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                physical_vehicle_id="CV_D0_2",
                vehicle_type="cv",
                home_depot_id="D0",
                trips=(DutyTrip(1, ("C1", "C2"), ("C1",)),),
                has_dynamic_commitment=True,
            ),
        ),
    )

    assert broken_pairs_distance(first, second) == 2 / 3


def test_route_diversity_uses_copied_predecessor_successor_formula() -> None:
    assert broken_pairs_distance(
        _ordered_individual(("C1", "C2")),
        _ordered_individual(("C2", "C1")),
    ) == 2 / 3


def test_pagmo_self_adaptive_penalty_all_feasible() -> None:
    population = tuple(_evaluation(value) for value in (2.0, 3.0, 5.0, 7.0))
    penalty = SelfAdaptivePenalty()

    penalty.update(population)

    assert penalty.scaling_factor == 0.0
    assert penalty.i_hat_up == 0.0
    assert penalty.i_hat_down == 0.0
    assert not penalty.apply_penalty_1
    assert penalty.c_max == (0.0,) * len(CONSTRAINT_AXES)


def test_payload_capacity_magnitude_uses_each_violation_fact() -> None:
    details = (
        "initial load 12.000000 exceeds Q=10.000000",
        "inherited remaining load 12.000000 exceeds Q=10.000000",
        "customer demand 5.000000 exceeds inherited remaining load 3.000000",
        "remaining load is negative: -2.000000",
        "arc load is negative: -2.000000",
        "arc load increases from 3.000000 to 5.000000",
        "delivered 3.000000, expected demand 5.000000",
    )

    assert all(_payload_capacity_magnitude(detail) == 2.0 for detail in details)


def test_pagmo_self_adaptive_penalty_better_infeasible_reference() -> None:
    population = (
        _evaluation(2.0),
        _evaluation(1.0, time_window=1.0),
        _evaluation(0.0, time_window=1.0),
        _evaluation(7.0, time_window=600.0),
    )
    penalty = SelfAdaptivePenalty()

    penalty.update(population)

    assert penalty.f_hat_up == 0.0
    assert penalty.f_hat_down == 2.0
    assert penalty.apply_penalty_1
    assert isinf(penalty.cost(population[-1]))


def test_pagmo_self_adaptive_penalty_worse_infeasible_reference() -> None:
    population = (
        _evaluation(2.0),
        _evaluation(3.0, capacity=21.0, time_window=10.0),
        _evaluation(3.0, capacity=22.0, time_window=10.0),
        _evaluation(4.0, capacity=22.0, time_window=10.0),
        _evaluation(7.0, capacity=3.4, time_window=23.0),
    )
    penalty = SelfAdaptivePenalty()

    penalty.update(population)

    assert penalty.f_hat_up == 4.0
    assert penalty.f_hat_down == 2.0
    assert not penalty.apply_penalty_1


def test_pagmo_self_adaptive_penalty_all_infeasible() -> None:
    population = (
        _evaluation(2.0, capacity=1.0, time_window=1.0),
        _evaluation(1.0, capacity=1.0, time_window=1.0),
        _evaluation(4.0, capacity=22.0, time_window=10.0),
        _evaluation(7.0, capacity=22.0, time_window=10.0),
    )
    penalty = SelfAdaptivePenalty()

    penalty.update(population)

    assert penalty.f_hat_up == 7.0
    assert penalty.f_hat_down == 1.0
    assert penalty.apply_penalty_1


def test_constraint_axes_separate_units_and_preserve_relative_penalty() -> None:
    vector = constraint_vector(
        _Evaluation(1.0, CONSTRAINT_AXES[:2], (100.0, 2.0))
    )
    assert vector[:2] == (100.0, 2.0)

    objectives = (10.0, 5.0, 6.0, 20.0)
    kilograms = tuple(_Evaluation(cost, (CONSTRAINT_AXES[0],), (magnitude,)) for cost, magnitude in zip(objectives, (0.0, 100.0, 200.0, 300.0)))
    cubic_metres = tuple(_Evaluation(cost, (CONSTRAINT_AXES[1],), (magnitude,)) for cost, magnitude in zip(objectives, (0.0, 0.1, 0.2, 0.3)))
    kg_penalty = SelfAdaptivePenalty()
    volume_penalty = SelfAdaptivePenalty()
    kg_penalty.update(kilograms)
    volume_penalty.update(cubic_metres)

    assert all(
        isclose(kg_penalty.cost(left), volume_penalty.cost(right))
        for left, right in zip(kilograms, cubic_metres, strict=True)
    )
    assert kg_penalty.cost(kilograms[-1]) != kilograms[-1].total_cost
