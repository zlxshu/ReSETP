from dataclasses import replace
from types import SimpleNamespace

from setp_solver.algorithms.problem_hgs.charging import (
    ChargingRepairPolicy,
    build_dynamic_ev_duty_charging_candidates,
)
from setp_solver.algorithms.problem_hgs.model import (
    DutyTrip,
    PhysicalVehicleDuty,
)
from setp_solver.charging_curve import L100_CONTROL
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.solution import ChargingAction, Route


def test_dynamic_public_candidate_reaches_duty_move_input(monkeypatch) -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0, due_time=10_000.0),
            Node(
                "F1",
                "f",
                1.0,
                0.0,
                due_time=10_000.0,
                charge_power_kw=60.0,
            ),
            Node("C1", "c", 2.0, 0.0, demand=1.0, due_time=10_000.0),
        ],
        distance_matrix=[
            [0.0, 100.0, 200.0],
            [100.0, 0.0, 100.0],
            [200.0, 100.0, 0.0],
        ],
    )
    public = ChargingAction(
        vehicle_id="EV_D0_1#T1",
        station_id="F1",
        energy_kwh=2.0,
        occupancy_minutes=2.0,
        charge_start_second=1_000.0,
        start_energy_kwh=1.0,
        end_energy_kwh=3.0,
        charging_curve_id=L100_CONTROL.curve_id,
    )

    def candidates(route, *_args, **_kwargs):
        return [
            (
                "public_path_F1",
                replace(
                    route,
                    node_sequence=["D0", "F1", "C1", "D0"],
                ),
                [public],
            )
        ]

    monkeypatch.setattr(
        "setp_solver.algorithms.problem_hgs.charging."
        "repair_route_charging_candidates",
        candidates,
    )
    context = SimpleNamespace(
        dynamic_state=SimpleNamespace(
            cut=SimpleNamespace(trigger_second=100.0)
        ),
        bundle=SimpleNamespace(
            instance=instance,
            time_profile=[],
            prices=DEFAULT_PRICES,
        ),
    )
    policy = ChargingRepairPolicy(
        strategy="aware",
        carbon_weight=1.0,
        depot_charge_window_mode="same_day_predeparture",
        charge_timing_policy="carbon_aware",
        charge_amount_strategy="just_enough",
        public_station_candidate_mode="parallel",
        carbon_profiles_by_day_offset=None,
    )
    duty = PhysicalVehicleDuty(
        physical_vehicle_id="EV_D0_1",
        vehicle_type="ev",
        home_depot_id="D0",
        trips=(DutyTrip(1, ("C1",)),),
    )

    generated = tuple(
        build_dynamic_ev_duty_charging_candidates(
            duty,
            context=context,
            policy=policy,
        )
    )

    assert len(generated) == 1
    assert generated[0].trips[0].effective_route_visits == (
        "F1",
        "C1",
    )
    assert generated[0].charging_sessions[0].station_id == "F1"
    assert generated[0].charging_sessions[0].energy_kwh == 2.0
