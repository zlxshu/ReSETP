from __future__ import annotations

from types import SimpleNamespace

from setp_solver.algorithms.problem_hgs.c0_witness_adapter import (
    adapt_witness_rows_to_duty,
)
from setp_solver.algorithms.problem_hgs.fleet_registry import (
    register_all_vehicle_slots,
)
from setp_solver.algorithms.problem_hgs.initialization import (
    build_initial_population,
    generate_witness_perturbation_moves,
)
from setp_solver.algorithms.problem_hgs.model import (
    DutyIndividual,
    DutyTrip,
    PhysicalVehicleDuty,
)
from setp_solver.solution import Route, Solution


def _bundle(*customer_ids: str):
    return SimpleNamespace(
        instance=SimpleNamespace(
            nodes=[
                SimpleNamespace(node_id=customer_id, node_type="c")
                for customer_id in customer_ids
            ]
        ),
        fleet_caps_by_depot={
            "D0": {"num_cv": 1, "num_ev": 1, "total_fleet_cap": 2}
        },
    )


def test_c0_witness_adapter_preserves_legacy_route_structure() -> None:
    bundle = _bundle("C1", "C2")
    rows = [
        {
            "instance_id": "case",
            "witness_status": "PASS",
            "physical_vehicle_id": "CV_D0_1",
            "route_vehicle_id": "CV_D0_1#T1",
            "depot_id": "D0",
            "shift_id": "AM",
            "customers": "C1|C2",
            "departure_minute": "480",
            "return_minute": "540",
        }
    ]

    adapted = adapt_witness_rows_to_duty(
        rows,
        instance_id="case",
        bundle=bundle,
        register_idle_duties=register_all_vehicle_slots,
    )
    legacy = register_all_vehicle_slots(
        DutyIndividual.from_solution(
            Solution(
                routes=[
                    Route(
                        vehicle_id="CV_D0_1#T1",
                        vehicle_type="cv",
                        home_depot_id="D0",
                        node_sequence=["D0", "C1", "C2", "D0"],
                    )
                ]
            )
        ),
        bundle,
    )

    assert adapted.duties == legacy.duties
    assert adapted.unserved_customers == legacy.unserved_customers
    assert adapted.to_solution().charging_actions == []
    assert [duty.physical_vehicle_id for duty in adapted.duties] == [
        "CV_D0_1",
        "EV_D0_1",
    ]


def test_c0_witness_adapter_rejects_incomplete_customer_coverage() -> None:
    bundle = _bundle("C1", "C2")
    row = {
        "instance_id": "case",
        "witness_status": "PASS",
        "physical_vehicle_id": "CV_D0_1",
        "route_vehicle_id": "CV_D0_1#T1",
        "depot_id": "D0",
        "shift_id": "AM",
        "customers": "C1",
        "departure_minute": "480",
        "return_minute": "540",
    }

    try:
        adapt_witness_rows_to_duty(
            [row],
            instance_id="case",
            bundle=bundle,
        )
    except ValueError as error:
        assert "cover customers exactly once" in str(error)
    else:
        raise AssertionError("incomplete witness coverage was accepted")


def test_witness_perturbations_are_shift_safe_and_include_three_allowed_paths() -> None:
    witness = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                physical_vehicle_id="CV_D0_1",
                vehicle_type="cv",
                home_depot_id="D0",
                trips=(DutyTrip(1, ("C1", "C2")),),
            ),
            PhysicalVehicleDuty(
                physical_vehicle_id="EV_D0_1",
                vehicle_type="ev",
                home_depot_id="D0",
                trips=(DutyTrip(1, ("C3",)),),
            ),
        )
    )
    shifts = {"C1": "AM", "C2": "AM", "C3": "AM"}

    moves = generate_witness_perturbation_moves(
        witness,
        customer_shift_by_id=shifts,
    )
    channels = {move.channel for move in moves}

    assert "witness_perturbation_reorder" in channels
    assert "witness_perturbation_relocate" in channels
    assert "witness_perturbation_type_exchange" in channels
    for move in moves:
        candidate = move.apply(witness)
        for duty in candidate.duties:
            for trip in duty.trips:
                assert {
                    shifts[customer] for customer in trip.customer_ids
                } <= {"AM"}


def _initialization_with_candidate(
    initial: DutyIndividual,
    candidate: DutyIndividual,
    *,
    mechanism_enabled: dict[str, bool],
):
    evaluation = SimpleNamespace(feasible=True, violations=())

    class _Evaluator:
        context = SimpleNamespace()

        @staticmethod
        def evaluate(_candidate):
            return evaluation

    class _Move:
        changed_duty_ids = tuple(
            duty.physical_vehicle_id for duty in candidate.duties
        )

        @staticmethod
        def apply(_initial):
            return candidate

    class _RouteEngine:
        @staticmethod
        def random_skeleton_move(_initial, *, draw_index):
            assert draw_index == 0
            return _Move()

    return build_initial_population(
        initial,
        evaluator=_Evaluator(),
        charging_policy=SimpleNamespace(),
        route_engine=_RouteEngine(),
        requested_size=2,
        max_random_attempts=1,
        mechanism_enabled=mechanism_enabled,
    )


def test_initial_population_rejects_type_change_when_type_exchange_sleeps() -> None:
    initial = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                physical_vehicle_id="CV_D0_1",
                vehicle_type="cv",
                home_depot_id="D0",
                trips=(DutyTrip(1, ("C1",)),),
            ),
            PhysicalVehicleDuty(
                physical_vehicle_id="EV_D0_1",
                vehicle_type="ev",
                home_depot_id="D0",
                trips=(),
            ),
        )
    )
    candidate = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                physical_vehicle_id="CV_D0_1",
                vehicle_type="cv",
                home_depot_id="D0",
                trips=(),
            ),
            PhysicalVehicleDuty(
                physical_vehicle_id="EV_D0_1",
                vehicle_type="ev",
                home_depot_id="D0",
                trips=(DutyTrip(1, ("C1",)),),
            ),
        )
    )

    result = _initialization_with_candidate(
        initial,
        candidate,
        mechanism_enabled={"type_exchange": False},
    )

    assert result.actual_size == 1
    assert result.attempts[0].status == "REJECTED"
    assert result.attempts[0].contract_type == "STRUCTURE_CLOSURE"
    assert "type_exchange:C1" in (result.attempts[0].error or "")


def test_initial_population_rejects_depot_change_when_cross_depot_sleeps() -> None:
    initial = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                physical_vehicle_id="CV_D0_1",
                vehicle_type="cv",
                home_depot_id="D0",
                trips=(DutyTrip(1, ("C1",)),),
            ),
            PhysicalVehicleDuty(
                physical_vehicle_id="CV_D1_1",
                vehicle_type="cv",
                home_depot_id="D1",
                trips=(),
            ),
        )
    )
    candidate = DutyIndividual(
        duties=(
            PhysicalVehicleDuty(
                physical_vehicle_id="CV_D0_1",
                vehicle_type="cv",
                home_depot_id="D0",
                trips=(),
            ),
            PhysicalVehicleDuty(
                physical_vehicle_id="CV_D1_1",
                vehicle_type="cv",
                home_depot_id="D1",
                trips=(DutyTrip(1, ("C1",)),),
            ),
        )
    )

    result = _initialization_with_candidate(
        initial,
        candidate,
        mechanism_enabled={"cross_depot": False},
    )

    assert result.actual_size == 1
    assert result.attempts[0].status == "REJECTED"
    assert result.attempts[0].contract_type == "STRUCTURE_CLOSURE"
    assert "cross_depot:C1" in (result.attempts[0].error or "")
