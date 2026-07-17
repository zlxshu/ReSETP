from __future__ import annotations

import json
from pathlib import Path

import pytest

from prototype import (
    PseudoDepotSnapshot,
    ProbeContractError,
    VehicleState,
    assert_frozen_prefixes,
    bounded_regret_ejection_probe,
    build_hand_checkable_stability_case,
    independent_route_stability_oracle,
    ortools_lock_probe,
    own_minimal_suffix_repair,
    route_stability_metrics,
    snapshot_from_json,
    snapshot_to_json,
)


HERE = Path(__file__).resolve().parent


def test_state_snapshot_round_trip_is_exact_and_deterministic() -> None:
    snapshot = PseudoDepotSnapshot(
        schema_version="test.v1",
        event_id="E1",
        decision_time_min=60,
        vehicles=(
            VehicleState(
                vehicle_id="V1",
                current_node="N1",
                current_time_min=60,
                load_kg=2,
                capacity_kg=10,
                soc_kwh=4.5,
                battery_kwh=8.0,
                frozen_prefix=("D", "N1"),
                onboard_orders=("O1",),
            ),
        ),
    )
    first = snapshot_to_json(snapshot)
    second = snapshot_to_json(snapshot)
    assert first == second
    assert snapshot_from_json(first) == snapshot


def test_state_snapshot_rejects_impossible_load_and_soc() -> None:
    with pytest.raises(ProbeContractError):
        VehicleState("V1", "N1", 0, 11, 10, 1.0, 8.0, ("D",), ())
    with pytest.raises(ProbeContractError):
        VehicleState("V1", "N1", 0, 1, 10, 9.0, 8.0, ("D",), ())


def test_own_suffix_repair_preserves_prefix_and_changes_suffix_only() -> None:
    repaired = own_minimal_suffix_repair(
        {"V1": ("D", "A", "B", "C")},
        {"V1": ("D", "A")},
        {"B": 2, "C": 1},
    )
    assert repaired == {"V1": ("D", "A", "C", "B")}
    assert_frozen_prefixes(repaired, {"V1": ("D", "A")})


def test_frozen_prefix_checker_rejects_vehicle_or_node_changes() -> None:
    with pytest.raises(ProbeContractError):
        assert_frozen_prefixes({"V2": ("D", "A")}, {"V1": ("D", "A")})
    with pytest.raises(ProbeContractError):
        assert_frozen_prefixes({"V1": ("D", "B", "A")}, {"V1": ("D", "A")})


def test_ortools_comparison_preserves_locks_when_available() -> None:
    result = ortools_lock_probe()
    if not result["available"]:
        pytest.skip("OR-Tools is optional")
    assert result["status"] == "PASS_EXTERNAL_LOCK_COMPARISON"
    assert result["prefix_preserved"] is True
    assert result["routes"]["V1"][:3] == ["0", "1", "2"]
    assert result["routes"]["V2"][:2] == ["0", "4"]


@pytest.mark.parametrize("budget", [0, 1, 2, 5])
def test_regret_ejection_budget_counts_are_exact(budget: int) -> None:
    result = bounded_regret_ejection_probe(budget)
    assert result["complete_evaluations"] == budget
    assert result["budget_closed"] is True
    assert result["regret_selected"] == "U"
    assert result["regret_values"] == {"U": 7.0, "V": 1.0}
    assert result["direct_insertion_feasible"] is False


def test_depth_two_ejection_becomes_active_at_budget_two() -> None:
    budget_one = bounded_regret_ejection_probe(1)
    budget_two = bounded_regret_ejection_probe(2)
    assert budget_one["bounded_depth_two_active"] is False
    assert budget_two["bounded_depth_two_active"] is True
    assert budget_two["accepted_ejection_depths"] == [2]


def test_stability_metrics_match_independent_oracle_and_hand_values() -> None:
    before, after, frozen = build_hand_checkable_stability_case()
    primary = route_stability_metrics(before, after, frozen)
    independent = independent_route_stability_oracle(before, after, frozen)
    assert primary == independent
    assert primary == {
        "customer_vehicle_changes": 2,
        "future_edge_symmetric_difference": 6,
        "future_route_position_changes": 2,
        "future_levenshtein_distance": 2,
    }


def test_stability_metrics_reject_frozen_prefix_change() -> None:
    before, after, frozen = build_hand_checkable_stability_case()
    after["V1"] = ("X", "A", "E", "C")
    with pytest.raises(ProbeContractError):
        route_stability_metrics(before, after, frozen)
    with pytest.raises(ProbeContractError):
        independent_route_stability_oracle(before, after, frozen)


def test_packaged_decision_never_claims_performance() -> None:
    decision_path = HERE / "decision.json"
    if not decision_path.exists():
        pytest.skip("run_probes.py has not packaged records yet")
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    assert decision["decision"] == "PASS_FUNCTION_ACTIVITY_ACCOUNTING_ONLY"
    assert decision["formal_search_allowed"] is False
    assert decision["performance_claim_allowed"] is False
    assert decision["merge_into_formal_alns_allowed"] is False

