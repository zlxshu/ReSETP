from __future__ import annotations

from types import SimpleNamespace

from baselines.e7_dynamic import e7_replay_invariants_20260715 as invariants


def _witness(**overrides):
    row = {
        "capture_stage": 2,
        "lock_state": "completed_before_trigger",
        "charge_day_offset": 0,
        "observed_start_second": 1_600.0,
        "earliest_start_second": 1_500.0,
        "latest_start_second": 1_800.0,
        "occupancy_minutes": 5.0,
        "energy_kwh": 10.0,
    }
    row.update(overrides)
    return row


def test_completed_window_stays_between_adjacent_triggers() -> None:
    assert invariants.charging_window_boundary_violations(
        [_witness()], [1_400.0, 2_200.0]
    ) == []

    failures = invariants.charging_window_boundary_violations(
        [_witness(earliest_start_second=1_300.0)], [1_400.0, 2_200.0]
    )
    assert failures == ["witness[0]: charging window crosses previous trigger"]

    failures = invariants.charging_window_boundary_violations(
        [_witness(latest_start_second=2_000.0)], [1_400.0, 2_200.0]
    )
    assert failures == ["witness[0]: charging window ends after current trigger"]


def test_in_progress_action_must_remain_fixed() -> None:
    witness = _witness(
        capture_stage=1,
        lock_state="in_progress_at_trigger_fixed",
        observed_start_second=900.0,
        earliest_start_second=900.0,
        latest_start_second=901.0,
    )
    assert invariants.charging_window_boundary_violations(witnesses=[witness], trigger_seconds=[1_000.0]) == [
        "witness[0]: in-progress action is not fixed"
    ]


def test_station_capacity_wrapper_uses_shared_checker(monkeypatch) -> None:
    calls = []

    def fake_checker(solution, node_lookup, instance):
        calls.append((solution, node_lookup, instance))
        return [object(), object()]

    monkeypatch.setattr(invariants, "_check_station_capacity", fake_checker)
    instance = SimpleNamespace(nodes=[SimpleNamespace(node_id="D0")])
    solution = object()

    assert invariants.station_capacity_violation_count(solution, instance) == 2
    assert calls == [(solution, {"D0": instance.nodes[0]}, instance)]
