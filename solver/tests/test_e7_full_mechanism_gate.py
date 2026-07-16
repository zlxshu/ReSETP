from __future__ import annotations

from types import SimpleNamespace

import pytest

from baselines.e7_dynamic import e7_full_mechanism_probe_20260714 as gate
from setp_solver.instance_loader import Instance, Node
from setp_solver.solution import ChargingAction, Route, Solution


def test_participation_floor_rejects_one_depot_loss_and_accepts_two_nonlosses() -> None:
    baseline = {"D0": 100.0, "D1": 80.0}

    assert gate._meets_participation_floor(
        {"D0": 100.0, "D1": 81.0}, baseline
    )
    assert not gate._meets_participation_floor(
        {"D0": 99.0, "D1": 90.0}, baseline
    )


def test_participation_floor_stops_on_nonpositive_baseline() -> None:
    with pytest.raises(RuntimeError, match="non-positive"):
        gate._meets_participation_floor(
            {"D0": 1.0, "D1": 2.0},
            {"D0": 0.0, "D1": 2.0},
        )


def test_charging_strategy_uses_the_matching_timing_variant() -> None:
    assert gate._timing_variant_for_strategy("naive") == "immediate"
    assert gate._timing_variant_for_strategy("aware") == "aware"
    with pytest.raises(ValueError, match="unknown charging strategy"):
        gate._timing_variant_for_strategy("other")


def test_timing_comparison_counts_only_aware_vs_immediate_shift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gate, "route_hash", lambda _solution: "same-route")
    monkeypatch.setattr(gate, "energy_hash", lambda _solution: "same-energy")
    monkeypatch.setattr(gate, "_charging_emissions_kg", lambda *_args: 0.0)
    immediate = Solution(
        charging_actions=[
            ChargingAction("EV0#T2", "D0", 10.0, 30.0, 1_000.0)
        ]
    )
    aware_same = Solution(
        charging_actions=[
            ChargingAction("EV0#T2", "D0", 10.0, 30.0, 1_000.0)
        ]
    )
    aware_shifted = Solution(
        charging_actions=[
            ChargingAction("EV0#T2", "D0", 10.0, 30.0, 1_300.0)
        ]
    )

    same = gate._timing_comparison(immediate, aware_same, object(), {})
    shifted = gate._timing_comparison(immediate, aware_shifted, object(), {})

    assert same["aware_vs_immediate_moved_action_count"] == 0
    assert same["aware_vs_immediate_moved_energy_kwh"] == pytest.approx(0.0)
    assert shifted["aware_vs_immediate_moved_action_count"] == 1
    assert shifted["aware_vs_immediate_moved_energy_kwh"] == pytest.approx(10.0)


def test_execution_ledger_keeps_charge_locked_before_its_route() -> None:
    route = Route("EV_D0_1#T2", "ev", "D0", ["D0", "C1", "D0"])
    action = ChargingAction("EV_D0_1#T2", "D0", 10.0, 30.0, 1_000.0)

    merged = gate._merge_execution_plan(
        {},
        {gate.base.action_key(action): action},
        Solution(routes=[route]),
    )

    assert merged.routes == [route]
    assert merged.charging_actions == [action]


def test_execution_ledger_keeps_two_distinct_charges_before_one_trip() -> None:
    route = Route("EV_D0_1#T2", "ev", "D0", ["D0", "C1", "D0"])
    first = ChargingAction("EV_D0_1#T2", "D0", 10.0, 30.0, 1_000.0)
    second = ChargingAction("EV_D0_1#T2", "D0", 10.0, 30.0, 2_000.0)

    merged = gate._merge_execution_plan(
        {},
        {
            gate.base.action_key(first): first,
            gate.base.action_key(second): second,
        },
        Solution(routes=[route]),
    )

    assert merged.charging_actions == [first, second]


def test_charging_window_witness_preserves_trigger_state() -> None:
    certificate = SimpleNamespace(
        trips=(
            SimpleNamespace(
                route_id="EV_D0_1#T1",
                physical_vehicle_id="EV_D0_1",
                trip_index=1,
                return_second=1_000.0,
                departure_second=0.0,
            ),
            SimpleNamespace(
                route_id="EV_D0_1#T2",
                physical_vehicle_id="EV_D0_1",
                trip_index=2,
                return_second=4_000.0,
                departure_second=3_000.0,
            ),
        )
    )
    completed = ChargingAction("EV_D0_1#T2", "D0", 10.0, 10.0, 1_200.0)
    in_progress = ChargingAction("EV_D0_1#T2", "D0", 10.0, 10.0, 1_700.0)

    completed_witness = gate._charging_window_witness(
        completed, certificate, capture_stage=1, trigger_second=2_000.0
    )
    in_progress_witness = gate._charging_window_witness(
        in_progress, certificate, capture_stage=1, trigger_second=2_000.0
    )

    assert completed_witness["earliest_start_second"] == pytest.approx(1_000.0)
    assert completed_witness["latest_start_second"] == pytest.approx(1_400.0)
    assert completed_witness["lock_state"] == "completed_before_trigger"
    assert in_progress_witness["earliest_start_second"] == pytest.approx(1_700.0)
    assert in_progress_witness["latest_start_second"] == pytest.approx(1_700.0)
    assert in_progress_witness["lock_state"] == "in_progress_at_trigger_fixed"


def test_charging_window_witness_treats_exact_trigger_start_as_locked() -> None:
    """The cut contract freezes a charge whose start is at the trigger."""

    certificate = SimpleNamespace(
        trips=(
            SimpleNamespace(
                route_id="EV_D0_1#T1",
                physical_vehicle_id="EV_D0_1",
                trip_index=1,
                return_second=1_000.0,
                departure_second=0.0,
            ),
            SimpleNamespace(
                route_id="EV_D0_1#T2",
                physical_vehicle_id="EV_D0_1",
                trip_index=2,
                return_second=4_000.0,
                departure_second=3_000.0,
            ),
        )
    )
    action = ChargingAction("EV_D0_1#T2", "D0", 10.0, 10.0, 2_000.0)

    witness = gate._charging_window_witness(
        action,
        certificate,
        capture_stage=2,
        trigger_second=2_000.0,
    )

    assert witness["earliest_start_second"] == pytest.approx(2_000.0)
    assert witness["latest_start_second"] == pytest.approx(2_000.0)
    assert witness["lock_state"] == "in_progress_at_trigger_fixed"


def test_full_day_execution_summary_closes_workload_and_cross_depot_service() -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0),
            Node("D1", "d", 10.0, 0.0),
            Node("C0", "c", 1.0, 0.0, demand=2.5),
            Node("C1", "c", 9.0, 0.0, demand=3.5),
        ],
        distance_matrix=[[0.0] * 4 for _ in range(4)],
    )
    solution = Solution(
        routes=[
            Route("CV0#T1", "cv", "D0", ["D0", "C0", "D0"]),
            Route("CV1#T1", "cv", "D0", ["D0", "C1", "D0"]),
        ]
    )

    result = gate._full_day_execution_summary(
        solution,
        instance,
        {"C0": "D0", "C1": "D1"},
    )

    assert result["schema"] == gate.FULL_DAY_EXECUTION_SCHEMA
    assert result["completed_customer_ids"] == ["C0", "C1"]
    assert result["completed_customer_count"] == 2
    assert result["completed_demand"] == pytest.approx(6.0)
    assert result["cross_site_customer_ids"] == ["C1"]
    assert result["cross_site_customer_count"] == 1


def test_full_day_execution_summary_rejects_duplicate_service() -> None:
    instance = Instance(
        nodes=[
            Node("D0", "d", 0.0, 0.0),
            Node("C0", "c", 1.0, 0.0, demand=2.5),
        ],
        distance_matrix=[[0.0] * 2 for _ in range(2)],
    )
    duplicated = Solution(
        routes=[
            Route("CV0#T1", "cv", "D0", ["D0", "C0", "D0"]),
            Route("CV1#T1", "cv", "D0", ["D0", "C0", "D0"]),
        ]
    )

    with pytest.raises(RuntimeError, match="more than once"):
        gate._full_day_execution_summary(duplicated, instance, {"C0": "D0"})
