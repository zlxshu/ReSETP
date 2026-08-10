from __future__ import annotations

from dataclasses import dataclass

from setp_solver.algorithms.problem_hgs.model import (
    DutyChargingSession,
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
)
from setp_solver.algorithms.problem_hgs.population import (
    AdaptivePenaltyManager,
    DutyPopulation,
    PenaltyParameters,
    PopulationParameters,
    broken_pairs_distance,
)


@dataclass(frozen=True)
class _Evaluation:
    total_cost: float
    violations: tuple = ()
    violation_magnitudes: tuple[float, ...] = ()

    @property
    def feasible(self) -> bool:
        return not self.violations


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


def _penalties() -> PenaltyParameters:
    return PenaltyParameters(
        initial_penalty_per_unit=100.0,
        solutions_between_updates=50,
        penalty_increase=1.34,
        penalty_decrease=0.32,
        target_feasible=0.43,
        feasibility_tolerance=0.05,
        minimum_penalty=0.1,
        maximum_penalty=100_000.0,
    )


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


def test_population_admission_does_not_register_initial_penalties() -> None:
    manager = AdaptivePenaltyManager(_penalties())
    population = DutyPopulation(
        PopulationParameters.copied_hgs_defaults(),
        manager,
    )

    population.add(_individual(0.0), _Evaluation(total_cost=10.0))

    assert manager.penalties == {}
    assert manager._history == {}


def test_population_matches_copied_hgs_duplicate_survivor_semantics() -> None:
    manager = AdaptivePenaltyManager(_penalties())
    population = DutyPopulation(
        PopulationParameters(
            min_pop_size=2,
            generation_size=1,
            num_elite=1,
            num_close=1,
            tournament_size=2,
            lb_diversity=0.0,
            ub_diversity=1.0,
        ),
        manager,
    )
    individual = _individual(0.0)

    first = population.add(individual, _Evaluation(total_cost=10.0))
    second = population.add(individual, _Evaluation(total_cost=10.0))
    third = population.add(individual, _Evaluation(total_cost=10.0))

    assert first.inserted
    assert second.inserted
    assert third.inserted
    assert len(population) == 3

    fourth = population.add(individual, _Evaluation(total_cost=10.0))

    assert fourth.inserted
    assert len(population) == 2
    assert all(
        member.fingerprint == individual.fingerprint
        for member in population.members()
    )
