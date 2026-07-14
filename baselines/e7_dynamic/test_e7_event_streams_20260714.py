from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from setp_solver.search.dynamic import _read_dynamic_events


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "baselines/e7_dynamic/e7_v2_20260714/event_streams"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_five_exact_streams_round_trip_through_runtime_schema() -> None:
    for seed in range(1, 6):
        stem = f"stream_seed{seed}"
        payload = json.loads((OUT / f"{stem}.events.json").read_text(encoding="utf-8"))
        runtime = _read_dynamic_events(OUT / f"{stem}.dynamic_events.tsv")
        assert len(payload) == len(runtime) == 55
        assert [row["event_id"] for row in payload] == [event.event_id for event in runtime]
        assert sum(row["event_type"] == "add" for row in payload) == 22
        assert sum(row["event_type"] == "cancel" for row in payload) == 11
        assert sum(row["event_type"] == "demand_change" for row in payload) == 22
        with (OUT / f"{stem}.owners.csv").open(newline="", encoding="utf-8") as handle:
            owners = list(csv.DictReader(handle))
        assert len(owners) == 243
        assert len({row["customer_id"] for row in owners}) == 243


def test_actionability_and_provenance_gates_pass_without_search() -> None:
    with (OUT / "raw_runs.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 275
    assert all(row["search_evaluations"] == "0" for row in rows)
    assert all(row["status"] == "PASS" for row in rows)
    existing = [row for row in rows if row["event_type"] != "add"]
    additions = [row for row in rows if row["event_type"] == "add"]
    assert len(existing) == 165
    assert len(additions) == 110
    assert all(row["modifiable_in_both_fixed_seed1_plans"] == "True" for row in existing)
    assert min(float(row["minimum_uncommitted_margin_seconds"]) for row in existing) > 60.0
    assert all(row["donor_fields_inherited_exactly"] == "True" for row in additions)
    assert all(row["owner_rule_verified"] == "True" for row in rows)


def test_formal_asset_and_artifact_hashes_are_frozen() -> None:
    metadata = json.loads((OUT / "metadata.json").read_text(encoding="utf-8"))
    decision = json.loads((OUT / "decision.json").read_text(encoding="utf-8"))
    assert metadata["formal_instance_sha256"] == "59696be304ad9f3c484820439e1cbdb027945e20ad7ecbdb8542dfde7e0d6225"
    assert (metadata["formal_num_cv"], metadata["formal_num_ev"]) == (10, 10)
    assert (metadata["rejected_active_num_cv"], metadata["rejected_active_num_ev"]) == (7, 7)
    assert metadata["contract_id"] == "E7_EVENT_STREAM_FREEZE_V2_DEPARTURE_LOCK"
    assert metadata["formal_initial_plan_labels"] == ["no_loss_seed1", "independent_seed1"]
    assert decision["verdict"] == "E7_EVENT_STREAMS_FROZEN"
    assert decision["passed"] is True
    assert decision["all_existing_events_modifiable_in_both_fixed_seed1_plans"] is True
    hashes = json.loads((OUT / "artifact_hashes.json").read_text(encoding="utf-8"))
    for row in hashes["artifacts"]:
        path = ROOT / row["path"]
        assert path.stat().st_size == row["bytes"]
        assert _sha256(path) == row["sha256"]
