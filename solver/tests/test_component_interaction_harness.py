from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "run_component_interaction.py"
SPEC = importlib.util.spec_from_file_location("component_interaction_harness", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = harness
SPEC.loader.exec_module(harness)


def _row(
    arm_id: str,
    components: tuple[str, ...],
    cost: float,
    emissions: float = 50.0,
) -> dict[str, object]:
    return {
        "instance_id": "private-test",
        "seed": 11,
        "arm_id": arm_id,
        "enabled_components": json.dumps(components),
        "run_status": "STOPPED_BY_CALLER",
        "total_cost": cost,
        "total_emissions_kg": emissions,
        "customers_served": 10,
        "customers_total": 10,
        "demand_served": 100.0,
        "demand_total": 100.0,
    }


def test_interaction_is_combination_gain_minus_single_gain_sum() -> None:
    rows = [
        _row("F00", (), 100.0, 50.0),
        _row("F01", ("route_local_search",), 90.0, 48.0),
        _row("F10", ("charging_timing",), 85.0, 47.0),
        _row(
            "F11",
            ("route_local_search", "charging_timing"),
            70.0,
            42.0,
        ),
    ]

    harness.annotate_interactions(rows)

    combined = rows[-1]
    assert combined["cost_gain"] == pytest.approx(30.0)
    assert combined["sum_single_cost_gains"] == pytest.approx(25.0)
    assert combined["cost_interaction"] == pytest.approx(5.0)
    assert combined["emissions_gain_kg"] == pytest.approx(8.0)
    assert combined["sum_single_emissions_gains_kg"] == pytest.approx(5.0)
    assert combined["emissions_interaction_kg"] == pytest.approx(3.0)
    assert combined["interaction_service_comparable"] is True


def test_pair_validation_rejects_an_injected_context_mismatch() -> None:
    common = harness.PairIdentity(
        arm_id="F00",
        instance_id="private-test",
        seed=11,
        initial_population_sha256="a" * 64,
        main_rng_seed=11,
        evaluation_context_sha256="b" * 64,
        wall_clock_budget_seconds=1200.0,
        fleet_parameter_class_id="endogenous",
    )
    harness.validate_pairing((common, replace(common, arm_id="F01")))

    mismatched = replace(
        common,
        arm_id="F01",
        evaluation_context_sha256="c" * 64,
    )
    with pytest.raises(harness.PairingMismatchError) as captured:
        harness.validate_pairing((common, mismatched))
    assert "evaluation_context_sha256" in str(captured.value)
    assert "refusing to run" in str(captured.value)


def test_best_clock_records_iteration_checkpoints_and_last_improvement() -> None:
    clock = harness._BestClock(1800.0)
    for iteration, cost in ((0, 100.0), (10, 90.0), (50, 90.0), (100, 80.0)):
        assert not clock.stop(
            SimpleNamespace(
                iterations=iteration,
                best_cost=cost,
                elapsed_seconds=float(iteration),
            )
        )

    assert clock.cost_at(10) == 90.0
    assert clock.cost_at(50) == 90.0
    assert clock.cost_at(100) == 80.0
    assert clock.cost_at(200) is None
    assert clock.last_improvement_iteration == 100


def test_switches_change_the_actual_selected_proposal_stream() -> None:
    route_move = SimpleNamespace(channel="route_kernel")
    charge_move = SimpleNamespace(channel="time_varying_carbon_charge")
    type_move = SimpleNamespace(channel="whole_duty_type_exchange")
    background_move = SimpleNamespace(channel="depot_collaboration")

    route_only = harness.select_component_moves(
        ("route_local_search",),
        (route_move,),
        (charge_move, type_move, background_move),
    )
    charge_and_type = harness.select_component_moves(
        ("charging_timing", "vehicle_type_exchange"),
        (route_move,),
        (charge_move, type_move, background_move),
    )

    assert route_only == (route_move,)
    assert charge_and_type == (charge_move, type_move)
    assert harness.build_factorial_arms(harness.EXECUTABLE_COMPONENTS)[-1].enabled_components == (
        "route_local_search",
        "charging_timing",
        "vehicle_type_exchange",
    )


def test_all_on_uses_the_reference_system_path_and_partial_streams_are_lazy() -> None:
    calls = []

    class Engine:
        source_id = "test"
        identity_sha256 = "a" * 64

        def __init__(self, channel: str) -> None:
            self.channel = channel

        def propose(self, *_args, **_kwargs):
            calls.append(self.channel)
            yield SimpleNamespace(channel=self.channel)

    route = Engine("route_kernel")
    mechanism = Engine("time_varying_carbon_charge")
    assert (
        harness._proposal_engine_for_arm(
            route,
            mechanism,
            harness.EXECUTABLE_COMPONENTS,
        )
        is None
    )

    partial = harness._proposal_engine_for_arm(
        route,
        mechanism,
        ("route_local_search", "charging_timing"),
    )
    proposed = iter(
        partial.propose(
            object(),
            object(),
            object(),
            include_whole_duty_type_exchange=True,
        )
    )
    assert calls == []
    assert next(proposed).channel == "route_kernel"
    assert calls == ["route_kernel"]


def test_fleet_fields_record_each_active_duty_distance_and_type() -> None:
    class Instance:
        def arc_metrics(self, left, right, profile, *, fallback_speed_mps):
            del fallback_speed_mps
            distance = {
                ("D", "C1", "cv"): 1000.0,
                ("C1", "D", "cv"): 2000.0,
                ("D", "C2", "ev"): 3000.0,
                ("C2", "D", "ev"): 4000.0,
            }[(left, right, profile)]
            return distance, 0.0, 0.0

    cv_trip = SimpleNamespace(effective_route_visits=("C1",))
    ev_trip = SimpleNamespace(effective_route_visits=("C2",))
    result = SimpleNamespace(
        best=SimpleNamespace(
            duties=(
                SimpleNamespace(
                    physical_vehicle_id="CV_D_1",
                    vehicle_type="cv",
                    home_depot_id="D",
                    trips=(cv_trip,),
                ),
                SimpleNamespace(
                    physical_vehicle_id="EV_D_1",
                    vehicle_type="ev",
                    home_depot_id="D",
                    trips=(ev_trip,),
                ),
                SimpleNamespace(
                    physical_vehicle_id="EV_D_2",
                    vehicle_type="ev",
                    home_depot_id="D",
                    trips=(),
                ),
            )
        )
    )

    fields = harness._fleet_fields(
        result,
        SimpleNamespace(instance=Instance()),
    )

    assert fields["active_vehicle_count"] == 2
    assert fields["active_cv_count"] == 1
    assert fields["active_ev_count"] == 1
    vehicles = json.loads(fields["vehicle_daily_distance_json"])
    assert [item["daily_distance_km"] for item in vehicles] == [3.0, 7.0]
