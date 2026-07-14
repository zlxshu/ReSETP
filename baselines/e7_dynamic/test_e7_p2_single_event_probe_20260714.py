from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from baselines.e7_dynamic import e7_p2_single_event_probe_20260714 as probe


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def formal_sources():
    return probe.load_formal_sources()


@pytest.fixture(scope="module")
def selected(formal_sources):
    return probe.select_probe_event(formal_sources)


def test_formal_sources_are_the_frozen_221_customer_10_plus_10_case(formal_sources) -> None:
    bundle = formal_sources["bundle"]
    assert probe.sha256(formal_sources["instance_path"]) == probe.FORMAL_INSTANCE_SHA256
    assert sum(node.node_type.lower() == "c" for node in bundle.instance.nodes) == 221
    assert (bundle.instance.num_cv, bundle.instance.num_ev) == (10, 10)
    assert formal_sources["solution_path"].name == f"{probe.CASE}.json"
    assert formal_sources["certificate_path"].name == f"{probe.CASE}.json"


def test_event_choice_and_static_cut_are_result_blind_and_deterministic(selected) -> None:
    event = selected["event"]
    cut = selected["cut"]
    assert event.event_id == "24"
    assert event.customer_id == "N_S1_010"
    assert event.event_type == "add"
    assert selected["owner_depot_id"] == "D0"
    assert selected["trigger_second"] == pytest.approx(25060.40779036161)
    assert (len(cut.completed_route_ids), len(cut.in_progress_route_ids)) == (8, 18)
    assert len(cut.editable_route_ids) == 7
    assert len(cut.asset_states) == 20
    assert sum(state.vehicle_type == "cv" for state in cut.asset_states.values()) == 10
    assert sum(state.vehicle_type == "ev" for state in cut.asset_states.values()) == 10
    assert selected["orphan_started_charges"] == []


def test_irreversible_whole_trip_commitments_close_without_fragmenting_history(
    formal_sources,
    selected,
) -> None:
    history = probe.historical_commitment_summary(formal_sources, selected)
    cut = selected["cut"]
    expected_route_ids = set(cut.completed_route_ids) | set(cut.in_progress_route_ids)
    expected_customers = {
        node_id
        for route in formal_sources["solution"].routes
        if route.vehicle_id in expected_route_ids
        for node_id in route.node_sequence
        if formal_sources["bundle"].instance.nodes[
            formal_sources["bundle"].instance.node_index[node_id]
        ].node_type.lower()
        == "c"
    }
    assert history["committed_route_count"] == len(expected_route_ids) == 26
    assert history["committed_customer_count"] == len(expected_customers) == 171
    assert set(history["committed_route_ids"]) == expected_route_ids
    assert "irreversible operational commitment" in history["boundary"]
    assert "not a claim" in history["boundary"]


def test_missing_continuous_gate_keeps_the_probe_blocked(tmp_path: Path) -> None:
    gate = probe.continuous_gate_status(tmp_path / "missing" / "decision.json")
    assert gate["ready"] is False
    assert gate["gate_exists"] is False
    assert gate["required_api"] == {
        "cut_dynamic_certificate_at_trigger": True,
        "prepare_accepts_locked_charging_actions": True,
    }


def test_blocked_draft_writes_five_files_and_zero_search_evidence(tmp_path: Path) -> None:
    output = tmp_path / "p2_draft"
    decision = probe.build_draft(output, tmp_path / "absent_gate.json")
    assert decision["verdict"] == "HALT_E7_P2_PENDING_CONTINUOUS_TRIGGER_GATE"
    assert decision["passed"] is False
    assert decision["search_started"] is False
    assert decision["search_evaluations"] == 0

    expected_files = {
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "artifact_hashes.json",
        "report.md",
    }
    assert {path.name for path in output.iterdir()} == expected_files
    assert not list(output.glob("._*"))

    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["artifact_status"] == "DRAFT_BLOCKED"
    assert metadata["search_started"] is False
    assert metadata["search_evaluations"] == 0
    assert metadata["max_search_evaluations_when_unblocked"] == 100

    with (output / "raw_runs.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["actual_search_evaluations"] == "0"
    assert rows[0]["search_started"] == "False"
    assert rows[0]["status"] == "BLOCKED_PENDING_CONTINUOUS_TRIGGER_GATE"

    hashes = json.loads((output / "artifact_hashes.json").read_text(encoding="utf-8"))
    assert {Path(row["path"]).name for row in hashes["artifacts"]} == expected_files - {
        "artifact_hashes.json"
    }
    for row in hashes["artifacts"]:
        artifact = output / Path(row["path"]).name
        assert artifact.stat().st_size == row["bytes"]
        assert _sha256(artifact) == row["sha256"]


def test_small_alns_probe_changes_and_certifies_at_least_one_candidate() -> None:
    result = probe.run_alns_probe(5)
    assert result["evaluations"] == 5
    assert sum(row["changed"] for row in result["rows"]) >= 1
    assert result["dynamically_feasible_count"] >= 1
    assert result["accepted_count"] >= 1
    assert result["best_future_cost"] <= result["initial_future_cost"]
