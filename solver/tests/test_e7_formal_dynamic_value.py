from __future__ import annotations

import argparse
import csv
import json

from baselines.e7_dynamic import e7_formal_dynamic_value_20260714 as formal


def test_frozen_stream_is_read_once_and_sorted_into_single_event_responses() -> None:
    events, owners, event_path, owner_path = formal.load_stream(1)

    ordered = sorted(events, key=lambda item: (float(item.t_appear), str(item.event_id)))
    assert len(events) == 55
    assert events == ordered
    assert len({event.event_id for event in events}) == len(events)
    assert len(owners) == 243
    assert formal.sha256(event_path) == "ae08f81e5b8efd93b6c2d95abc405623ae355926c4c23fd31681c0fa8824d6a9"
    assert formal.sha256(owner_path) == "66a6b7211192e69725d6fa76a3c747e8a855744570f9389229ca24fa804eebe1"


def test_failed_run_keeps_completed_stages_and_a_halt_record(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(formal, "ROOT", tmp_path)
    monkeypatch.setattr(formal, "source_commit", lambda: "test-commit")
    args = argparse.Namespace(
        streams=[1],
        evaluations=400,
        max_stages=13,
        all_stages=False,
        trigger_mode="event",
        workers=1,
    )
    stage = {
        "arm": "cooperative",
        "stream_seed": 1,
        "stage": 1,
        "customer_accounting_pass": True,
    }
    failure = {
        "stream_seed": 1,
        "arm": "cooperative",
        "completed_stage_count": 1,
        "error_type": "RuntimeError",
        "error": "deliberate test stop",
    }

    formal.write_artifacts(
        tmp_path,
        [],
        args,
        failures=[failure],
        partial_stage_rows=[stage],
    )

    decision = json.loads((tmp_path / "decision.json").read_text(encoding="utf-8"))
    assert decision["verdict"] == "HALT_E7_PAIRED_DYNAMIC_VALUE"
    assert decision["failure_count"] == 1
    with (tmp_path / "raw_runs.csv").open(newline="", encoding="utf-8") as handle:
        assert list(csv.DictReader(handle))[0]["stage"] == "1"
    with (tmp_path / "failures.csv").open(newline="", encoding="utf-8") as handle:
        assert list(csv.DictReader(handle))[0]["error"] == "deliberate test stop"
