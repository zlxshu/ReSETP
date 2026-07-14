from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from setp_solver.search.dynamic import _read_dynamic_events
from setp_solver.search.dynamic import DynamicEvent, _instance_after_events
from setp_solver.search.bundle import load_search_bundle
from baselines.e7_dynamic import e7_formal_dynamic_value_20260714 as formal
from baselines.e7_dynamic.generate_e7_event_streams_20260714 import (
    DONOR_BUNDLE,
    EVENT_IDENTITY_SHA256,
    event_identity_sha256,
)


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
        assert [row["new_service_time"] for row in payload] == [event.new_service_time for event in runtime]
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
    assert metadata["contract_id"] == "E7_EVENT_STREAM_FREEZE_V3_SERVICE_TIME"
    assert metadata["event_identity_sha256_excluding_v3_fields"] == EVENT_IDENTITY_SHA256
    assert metadata["formal_initial_plan_labels"] == ["no_loss_seed1", "independent_seed1"]
    assert decision["verdict"] == "E7_EVENT_STREAMS_FROZEN"
    assert decision["passed"] is True
    assert decision["all_existing_events_modifiable_in_both_fixed_seed1_plans"] is True
    assert decision["all_adds_directly_actionable_with_exact_service_time"] is True
    hashes = json.loads((OUT / "artifact_hashes.json").read_text(encoding="utf-8"))
    for row in hashes["artifacts"]:
        path = ROOT / row["path"]
        assert path.stat().st_size == row["bytes"]
        assert _sha256(path) == row["sha256"]


def test_event_identity_and_all_add_service_times_match_donors() -> None:
    streams = []
    donor_bundle = load_search_bundle(DONOR_BUNDLE)
    donors = {
        node.node_id: node
        for node in donor_bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    add_count = 0
    for seed in range(1, 6):
        rows = json.loads((OUT / f"stream_seed{seed}.events.json").read_text(encoding="utf-8"))
        events = [DynamicEvent(**row) for row in rows]
        streams.append(events)
        for event in events:
            if event.event_type == "add":
                add_count += 1
                assert event.new_service_time == donors[event.donor_customer_id].service_time
    assert add_count == 110
    assert event_identity_sha256(streams) == EVENT_IDENTITY_SHA256


def test_added_node_uses_event_service_time_and_old_format_falls_back() -> None:
    base = formal.load_arm("cooperative")["bundle"].instance
    event = DynamicEvent(
        event_id="service-time-test",
        event_type="add",
        t_appear=1.0,
        customer_id="NEW_SERVICE",
        old_demand=0.0,
        new_demand=1.0,
        x=0.0,
        y=0.0,
        new_ready_time=0.0,
        new_due_time=86_400.0,
        new_service_time=321.0,
    )
    effective = _instance_after_events(base, [event], 1.0, set())
    node = next(node for node in effective.nodes if node.node_id == "NEW_SERVICE")
    assert node.service_time == 321.0
    old = DynamicEvent(**{key: value for key, value in event.__dict__.items() if key != "new_service_time"})
    fallback = _instance_after_events(base, [old], 1.0, set())
    old_node = next(node for node in fallback.nodes if node.node_id == "NEW_SERVICE")
    assert old_node.service_time > 0.0


def test_formal_loader_rejects_missing_or_mismatched_add_service_time(tmp_path, monkeypatch) -> None:
    source = json.loads((OUT / "stream_seed1.events.json").read_text(encoding="utf-8"))
    for bad_value in (None, 1.0):
        rows = json.loads(json.dumps(source))
        add = next(row for row in rows if row["event_type"] == "add")
        if bad_value is None:
            add.pop("new_service_time")
        else:
            add["new_service_time"] = bad_value
        (tmp_path / "stream_seed1.events.json").write_text(json.dumps(rows), encoding="utf-8")
        (tmp_path / "stream_seed1.owners.csv").write_text(
            (OUT / "stream_seed1.owners.csv").read_text(encoding="utf-8"), encoding="utf-8"
        )
        monkeypatch.setattr(formal, "EVENT_ROOT", tmp_path)
        try:
            formal.load_stream(1)
        except RuntimeError as exc:
            assert "service time" in str(exc)
        else:
            raise AssertionError("formal loader accepted an invalid add service time")
