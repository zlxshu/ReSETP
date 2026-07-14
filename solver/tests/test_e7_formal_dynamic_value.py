from __future__ import annotations

import argparse
import csv
import json
import sys

import pytest

from baselines.e7_dynamic import e7_formal_dynamic_value_20260714 as formal


def test_frozen_stream_and_batched_trigger_contract() -> None:
    events, owners, event_path, owner_path = formal.load_stream(1)

    ordered = sorted(events, key=lambda item: (float(item.t_appear), str(item.event_id)))
    assert len(events) == 55
    assert events == ordered
    assert len({event.event_id for event in events}) == len(events)
    assert len(owners) == 243
    assert formal.sha256(event_path) == "ae08f81e5b8efd93b6c2d95abc405623ae355926c4c23fd31681c0fa8824d6a9"
    assert formal.sha256(owner_path) == "66a6b7211192e69725d6fa76a3c747e8a855744570f9389229ca24fa804eebe1"
    assert [len(formal._validated_trigger_batches(seed, formal.load_stream(seed)[0])) for seed in range(1, 6)] == [7, 8, 7, 7, 7]
    for seed in range(1, 6):
        batches = formal._validated_trigger_batches(seed, formal.load_stream(seed)[0])
        observed = {
            event.event_id: float(batch["trigger_time"])
            for batch in batches
            for event in batch["events"]
        }
        assert observed == formal._frozen_trigger_times(seed)


def test_stage_application_rejects_ignored_or_mismatched_events() -> None:
    events = formal.load_stream(1)[0][:2]
    valid = formal.gate.StageConstruction(None, None, tuple(event.event_id for event in events), (), 0)
    assert formal._validate_stage_application(valid, events)[0] == [event.event_id for event in events]

    ignored = formal.gate.StageConstruction(None, None, (), (events[0].event_id,), 0)
    with pytest.raises(RuntimeError, match="must not be ignored"):
        formal._validate_stage_application(ignored, events)

    mismatched = formal.gate.StageConstruction(None, None, (events[0].event_id,), (), 0)
    with pytest.raises(RuntimeError, match="differ from the trigger batch"):
        formal._validate_stage_application(mismatched, events)


def test_stage_timing_gate_and_final_stage_exemption() -> None:
    assert formal._stage_timing(9.0, 10.0, 20.0) == (10.0, True)
    assert formal._stage_timing(11.0, 10.0, 20.0) == (10.0, False)
    assert formal._stage_timing(999.0, 10.0, None) == (None, None)


def test_cli_defaults_to_batched_and_accepts_eight_workers(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["e7"])
    defaults = formal.parse_args()
    assert defaults.trigger_mode == "batched"
    assert defaults.workers == 2

    monkeypatch.setattr(sys, "argv", ["e7", "--workers", "8"])
    args = formal.parse_args()
    assert args.trigger_mode == "batched"
    assert args.workers == 8


def test_failed_run_keeps_completed_stages_and_a_halt_record(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(formal, "ROOT", tmp_path)
    monkeypatch.setattr(formal, "source_commit", lambda: "test-commit")
    args = argparse.Namespace(
        streams=[1],
        evaluations=400,
        max_stages=13,
        all_stages=False,
        trigger_mode="batched",
        workers=1,
    )
    stage = {
        "arm": "cooperative",
        "stream_seed": 1,
        "stage": 1,
        "customer_accounting_pass": True,
        "next_trigger_second": None,
        "completed_before_next_trigger": None,
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
