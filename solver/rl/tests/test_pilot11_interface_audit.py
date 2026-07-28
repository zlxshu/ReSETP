from __future__ import annotations

from dr_alns_ppo.pilot11_interface_audit import (
    CURRENT_BLOCK_INTERFACE,
    REQUIRED_LITERATURE_SIGNALS,
    build_gap_rows,
    classify_gate,
)


def test_current_block_interface_names_existing_heads() -> None:
    assert CURRENT_BLOCK_INTERFACE["obs_dim"] == 24
    assert CURRENT_BLOCK_INTERFACE["action_heads"] == [
        "destroy",
        "repair",
        "q_ratio",
        "threshold_ratio",
        "exploration_ratio",
        "search_control",
    ]
    assert "charging_strategy" not in CURRENT_BLOCK_INTERFACE["action_heads"]


def test_required_literature_signals_include_domain_state_and_control() -> None:
    names = {row["name"] for row in REQUIRED_LITERATURE_SIGNALS}
    assert "route_sequence_state" in names
    assert "customer_time_window_state" in names
    assert "vehicle_energy_state" in names
    assert "charging_strategy_control" in names
    assert "acceptance_or_stop_control" in names


def test_gap_rows_mark_missing_route_and_charging_controls() -> None:
    rows = build_gap_rows()
    by_name = {row["name"]: row for row in rows}
    assert by_name["route_sequence_state"]["status"] == "missing"
    assert by_name["charging_strategy_control"]["status"] == "missing"
    assert by_name["q_threshold_exploration_control"]["status"] == "present"


def test_gate_requires_feasible_action_control_point() -> None:
    rows = build_gap_rows()
    gate = classify_gate(rows)
    assert gate["status"] == "NEEDS_INTERFACE_REDESIGN"
    assert "charging_strategy_control" in gate["recommended_first_audit"]
