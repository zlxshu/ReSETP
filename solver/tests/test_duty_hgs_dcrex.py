"""Regression tests for the formal DCREX core."""

from __future__ import annotations

import random

import pytest
from setp_solver.algorithms.duty_hgs.crossover import (
    dcrex_duty_exchange,
    trip_assignment_exchange,
)
from setp_solver.algorithms.duty_hgs.crossover_control import (
    CostAwareCrossoverController,
)
from setp_solver.algorithms.duty_hgs.dcrex import (
    DCREXController,
    DiscountedUCB1,
    RouteGene,
    dcrex_exchange,
    percentage_reward,
    route_pair_metrics,
)
from setp_solver.algorithms.duty_hgs.independent import (
    IndependentProfitRun,
    freeze_best_independent_profit,
)
from setp_solver.algorithms.duty_hgs.model import (
    DutyChargingSession,
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
)
from setp_solver.algorithms.duty_hgs.runner import DutyHGSSearchState
from setp_solver.algorithms.duty_hgs.stopping import MaxIterations


def _figure_a1_main() -> tuple[RouteGene, ...]:
    return (
        RouteGene("R1a", (1, 3, 7), "A", "A"),
        RouteGene("R1b", (9, 5, 6), "A", "A"),
        RouteGene("R1c", (4, 8), "B", "B"),
        RouteGene("R1d", (2, 10), "B", "B"),
    )


def test_route_pair_metrics_reproduce_lei_hao_wu_figure_a1() -> None:
    universe = tuple(range(1, 11))
    main = _figure_a1_main()
    first_donor = RouteGene("R2b", (1, 3, 5, 8), "A", "A")
    step1 = route_pair_metrics(
        main,
        target_route_id="R1a",
        donor_route=first_donor,
        customer_universe=universe,
    )
    assert (
        step1.introduced_edges,
        step1.redundant_customers,
        step1.missing_customers,
        step1.conflicting_customers,
        step1.score,
        step1.diversity_delta,
    ) == (3, 2, 1, 0, 0, 6)

    after_step1 = (first_donor, *main[1:])
    second_donor = RouteGene("R3d", (4, 2), "B", "B")
    step2 = route_pair_metrics(
        after_step1,
        target_route_id="R1c",
        donor_route=second_donor,
        customer_universe=universe,
        previously_introduced_customers=first_donor.customer_ids,
    )
    assert (
        step2.introduced_edges,
        step2.redundant_customers,
        step2.missing_customers,
        step2.conflicting_customers,
        step2.score,
        step2.diversity_delta,
    ) == (1, 0, 0, 0, -1, 1)


def test_dcrex_is_multi_parent_and_keeps_private_route_terminals() -> None:
    main = _figure_a1_main()
    second = (
        RouteGene("R2a", (4, 2, 7), "A", "A"),
        RouteGene("R2b", (1, 3, 5, 8), "A", "A"),
        RouteGene("R2c", (6, 9, 10), "B", "B"),
    )
    third = (
        RouteGene("R3a", (1, 3, 5), "A", "A"),
        RouteGene("R3b", (6, 7), "A", "A"),
        RouteGene("R3c", (8, 9, 10), "B", "B"),
        RouteGene("R3d", (4, 2), "B", "B"),
    )
    result = dcrex_exchange(
        (main, second, third),
        customer_universe=range(1, 11),
        rng=random.Random(7),
        controller=DCREXController(),
        main_parent_index=0,
        preserve_target_terminals=True,
    )
    assert result.steps
    assert result.route_pair_scores >= len(result.steps)
    assert all(step.donor_parent_index in {1, 2} for step in result.steps)
    assert len({step.target_route_id for step in result.steps}) == len(result.steps)
    original_by_id = {route.route_id: route for route in main}
    for route in result.routes:
        assert route.start_depot == original_by_id[route.route_id].start_depot
        assert route.end_depot == original_by_id[route.route_id].end_depot


def test_dcrex_consumes_each_main_parent_target_at_most_once() -> None:
    class HighDiversityController:
        def select(self, _rng: random.Random):
            from setp_solver.algorithms.duty_hgs.dcrex import InsertionOperator

            return 19, InsertionOperator.FBI

    main = (RouteGene("target", (1, 2, 3, 4), "A", "A"),)
    donor_one = (RouteGene("d1", (4, 3, 2, 1), "A", "A"),)
    donor_two = (RouteGene("d2", (2, 1, 4, 3), "A", "A"),)
    result = dcrex_exchange(
        (main, donor_one, donor_two),
        customer_universe=(1, 2, 3, 4),
        rng=random.Random(0),
        controller=HighDiversityController(),
        main_parent_index=0,
    )
    assert len(result.steps) == 1
    assert result.steps[0].target_route_id == "target"


def test_dcrex_does_not_count_an_identity_pair_as_an_exchange() -> None:
    route = RouteGene("same", (1, 2, 3), "A", "A", vehicle_type="cv")
    result = dcrex_exchange(
        ((route,), (route,)),
        customer_universe=(1, 2, 3),
        rng=random.Random(0),
        controller=DCREXController(),
        main_parent_index=0,
    )
    assert result.steps == ()
    assert result.achieved_diversity == 0
    assert result.route_pair_scores == 0


def test_discounted_ucb1_and_percentage_reward_are_observable() -> None:
    bandit = DiscountedUCB1(2, gamma=0.99)
    rng = random.Random(1)
    first = bandit.select(rng)
    bandit.update(first, 4.0)
    second = bandit.select(rng)
    assert first != second
    bandit.update(second, -2.0)
    assert sum(bandit.counts) == pytest.approx(1.99)
    assert percentage_reward(100.0, 97.5) == pytest.approx(2.5)


def test_crossover_controller_uses_deterministic_work_normalisation() -> None:
    controller = CostAwareCrossoverController()
    rng = random.Random(3)
    first = controller.select(rng)
    first_reward = controller.update(first, 10.0, 5)
    second = controller.select(rng)
    assert second != first
    second_reward = controller.update(second, 10.0, 2)
    assert first_reward.reward_per_work_unit == pytest.approx(2.0)
    assert second_reward.reward_per_work_unit == pytest.approx(5.0)


def test_private_dcrex_preserves_vehicle_slots_and_clears_stale_charge() -> None:
    def parent(order: tuple[str, str], source: str) -> DutyIndividual:
        return DutyIndividual(
            duties=(
                PhysicalVehicleDuty(
                    "CV_D0_1",
                    "cv",
                    "D0",
                    (DutyTrip(1, ("C1",), locked_customer_prefix=("C1",)),),
                ),
                PhysicalVehicleDuty(
                    "EV_D0_1",
                    "ev",
                    "D0",
                    (DutyTrip(1, order),),
                    charging_sessions=(
                        DutyChargingSession(
                            trip_index=1,
                            station_id="D0",
                            energy_kwh=5.0,
                            occupancy_minutes=15.0,
                            charge_start_second=0.0,
                        ),
                    ),
                ),
            ),
            source=source,
        )

    parents = (
        parent(("C2", "C3"), "p1"),
        parent(("C3", "C2"), "p2"),
        parent(("C2", "C3"), "p3"),
    )
    changed = None
    for seed in range(20):
        result = dcrex_duty_exchange(
            parents,
            random.Random(seed),
            DCREXController(),
        )
        if "EV_D0_1" in result.changed_duty_ids:
            changed = result
            break
    assert changed is not None
    assert [
        (duty.physical_vehicle_id, duty.vehicle_type, duty.home_depot_id)
        for duty in changed.child.duties
    ] == [
        ("CV_D0_1", "cv", "D0"),
        ("EV_D0_1", "ev", "D0"),
    ]
    assert changed.child.duties[0].trips[0].locked_customer_prefix == ("C1",)
    assert changed.child.duties[1].charging_sessions == ()
    represented = {
        customer
        for duty in changed.child.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }.union(changed.child.unserved_customers)
    assert represented == {"C1", "C2", "C3"}


def test_private_trip_assignment_changes_trip_structure_and_preserves_locks() -> None:
    locked_ev_charge = DutyChargingSession(
        trip_index=1,
        station_id="D0",
        energy_kwh=2.0,
        occupancy_minutes=6.0,
        charge_start_second=300.0,
        locked=True,
    )

    def parent(
        ev_trips: tuple[DutyTrip, ...],
        cv_trips: tuple[DutyTrip, ...],
        source: str,
    ) -> DutyIndividual:
        return DutyIndividual(
            duties=(
                PhysicalVehicleDuty(
                    "CV_D0_1",
                    "cv",
                    "D0",
                    (DutyTrip(1, ("C1",), locked_customer_prefix=("C1",)),),
                ),
                PhysicalVehicleDuty(
                    "EV_D0_1",
                    "ev",
                    "D0",
                    ev_trips,
                    (locked_ev_charge,),
                ),
                PhysicalVehicleDuty(
                    "EV_D0_2",
                    "ev",
                    "D0",
                    cv_trips,
                ),
            ),
            source=source,
        )

    first = parent(
        (DutyTrip(1, ("C2",)), DutyTrip(2, ("C3",))),
        (DutyTrip(1, ("C4", "C5")),),
        "p1",
    )
    second = parent(
        (DutyTrip(1, ("C2",)), DutyTrip(2, ("C3",))),
        (DutyTrip(1, ("C4", "C5")),),
        "p2",
    )
    coordinates = {
        f"C{index}": (float(index), float(index % 2))
        for index in range(1, 6)
    }
    result = trip_assignment_exchange(
        (first, second),
        random.Random(5),
        coordinates,
    )
    assert result.deterministic_work_units == 1
    assert [
        (duty.physical_vehicle_id, duty.vehicle_type, duty.home_depot_id)
        for duty in result.child.duties
    ] == [
        ("CV_D0_1", "cv", "D0"),
        ("EV_D0_1", "ev", "D0"),
        ("EV_D0_2", "ev", "D0"),
    ]
    assert result.child.duties[0].trips[0].locked_customer_prefix == ("C1",)
    assert result.child.duties[1].charging_sessions == (locked_ev_charge,)
    assert len(result.child.duties[1].trips) == 3
    assert result.child.duties[1].trips[2].customer_ids == ("C4", "C5")
    assert result.child.duties[2].trips == ()
    assert result.changed_duty_ids == frozenset({"EV_D0_1", "EV_D0_2"})
    represented = {
        customer
        for duty in result.child.duties
        for trip in duty.trips
        for customer in trip.customer_ids
    }.union(result.child.unserved_customers)
    assert represented == {"C1", "C2", "C3", "C4", "C5"}


def test_per_algorithm_iteration_stop_and_best_of_ten_profit() -> None:
    state = DutyHGSSearchState(
        iterations=50,
        iterations_without_improvement=0,
        best_cost=1.0,
        full_evaluations=0,
        incremental_evaluations=0,
        sentinel_evaluations=0,
        actual_full_model_evaluations=0,
        duty_slice_preparations=0,
        candidate_assemblies=0,
    )
    assert MaxIterations(50)(state)
    runs = [
        IndependentProfitRun(
            depot_id="D0",
            seed=seed,
            profit=100.0 + seed,
            feasible=True,
            result_id=f"D0-seed-{seed}",
        )
        for seed in range(1, 11)
    ]
    frozen = freeze_best_independent_profit(runs)
    assert frozen.values["D0"] == 110.0
    assert frozen.selected_result_by_depot["D0"] == "D0-seed-10"
