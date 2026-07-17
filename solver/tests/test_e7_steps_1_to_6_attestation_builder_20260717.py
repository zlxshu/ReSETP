from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[2]
BUILDER_PATH = REPO / "baselines/e7_dynamic/build_e7_steps_1_to_6_attestation_20260717.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


BUILDER = load("test_e7_steps_attestation_builder", BUILDER_PATH)


def write_package(root: Path, metadata: dict, decision: dict) -> None:
    root.mkdir(parents=True)
    (root / "metadata.json").write_text(json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8")
    with (root / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["row"])
        writer.writeheader()
        writer.writerow({"row": 1})
    (root / "decision.json").write_text(json.dumps(decision, sort_keys=True) + "\n", encoding="utf-8")
    (root / "report.md").write_text("# fixture\n", encoding="utf-8")
    manifest = {
        name: BUILDER.sha256(root / name)
        for name in ("metadata.json", "raw_runs.csv", "decision.json", "report.md")
    }
    (root / "artifact_hashes.json").write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")


def passing_sources(tmp_path: Path) -> dict[str, Path]:
    sources = {
        "formal": tmp_path / "formal",
        "replay": tmp_path / "replay",
        "replay_invariants": tmp_path / "replay_invariants",
        "independent_audit": tmp_path / "independent_audit",
        "paper": tmp_path / "paper",
    }
    write_package(
        sources["formal"],
        {"task_count": 120, "child_contract_sha256": "a" * 64},
        {"verdict": "E7_FORMAL_EVIDENCE_COMPLETE_WITH_ARM_FAILURES", "failures": []},
    )
    write_package(
        sources["replay"],
        {"schema": "fixture"},
        {
            "status": "PASS_E7_28DAY_ZERO_SEARCH_CHARGING_REPLAY",
            "formal_task_count": 120,
            "replayed_full_day_task_count": 30,
            "operating_day_count": 28,
            "paired_day_row_count": 840,
            "route_hash_failures": 0,
            "energy_hash_failures": 0,
            "route_search_evaluations": 0,
        },
    )
    write_package(
        sources["replay_invariants"],
        {"schema": "fixture"},
        {
            "status": "PASS_E7_REPLAY_INVARIANTS_AUDIT",
            "checks": {"all": True},
            "full_task_count": 30,
            "task_day_row_count": 840,
            "window_violation_count": 0,
            "station_capacity_violation_count": 0,
            "route_hash_failure_count": 0,
            "energy_hash_failure_count": 0,
            "emissions_recalculation_failure_count": 0,
            "route_search_evaluations": 0,
        },
    )
    write_package(
        sources["independent_audit"],
        {"schema": "fixture"},
        {
            "verdict": "PASS_E7_MULTINETWORK_FORMAL_AND_REPLAY_INDEPENDENT_AUDIT",
            "checks": {"all": True},
            "formal_hash_failures": [],
            "replay_hash_failures": [],
            "replay_invariant_hash_failures": [],
            "replay_row_failures": [],
            "economic_closure_failures": [],
            "external_pause_timing_contamination": [],
        },
    )
    sources["paper"].mkdir()
    generated = {}
    for name in BUILDER.PAPER_EXHIBITS:
        path = sources["paper"] / name
        path.write_text(f"fixture {name}\n", encoding="utf-8")
        generated[name] = BUILDER.sha256(path)
    source_hashes = {
        "independent_audit/decision.json": BUILDER.sha256(sources["independent_audit"] / "decision.json"),
        "28day_replay/decision.json": BUILDER.sha256(sources["replay"] / "decision.json"),
    }
    paper_manifest = {
        "schema_version": "resetp.e7.paper-evidence.v1",
        "builder_sha256": BUILDER.sha256(BUILDER.PAPER_BUILDER),
        "source_hashes": source_hashes,
        "generated_hashes": generated,
        "coverage": {
            "formal_tasks": 120,
            "stream_pairs": 30,
            "network_condition_cells": 6,
            "replay_pairs": 840,
            "reader_facing_exhibits": 7,
        },
    }
    (sources["paper"] / BUILDER.PAPER_MANIFEST_NAME).write_text(
        json.dumps(paper_manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return sources


def test_missing_e7_package_halts_without_publishing_attestation(tmp_path):
    output = tmp_path / "attestation.json"
    sources = {name: tmp_path / name for name in BUILDER.DEFAULT_SOURCES}
    decision, payload = BUILDER.build_attestation(sources, output, publish=True)
    assert decision["verdict"] == "HALT_E7_STEPS_1_TO_6_ATTESTATION"
    assert decision["search_performed"] is False
    assert decision["route_search_evaluations"] == 0
    assert decision["formal_attestation_published"] is False
    assert payload is None
    assert not output.exists()


def test_passing_five_surface_fixture_publishes_closed_atomic_attestation(tmp_path):
    sources = passing_sources(tmp_path)
    output = tmp_path / "published" / "attestation.json"
    decision, payload = BUILDER.build_attestation(sources, output, publish=True)
    assert decision == {
        "verdict": "PASS_E7_STEPS_1_TO_6_ATTESTATION_READY",
        "failures": [],
        "search_performed": False,
        "route_search_evaluations": 0,
        "formal_attestation_published": True,
    }
    assert payload is not None
    assert payload["schema_version"] == "resetp.e7.steps-1-to-6-attestation.v1"
    assert payload["steps_1_to_6_complete"] is True
    assert payload["search_version_closed"] is True
    assert len(payload["search_version"]) == 64
    assert payload["formal_search_contract_hashes"] == {"child_contract_sha256": "a" * 64}
    assert payload["route_search_evaluations_during_attestation"] == 0
    assert json.loads(output.read_text(encoding="utf-8")) == payload
    assert not list(output.parent.glob(".*.tmp-*"))
    for path, expected in payload["evidence_hashes"].items():
        assert BUILDER.sha256(Path(path)) == expected


def test_failed_rebuild_does_not_overwrite_existing_attestation(tmp_path):
    sources = passing_sources(tmp_path)
    output = tmp_path / "attestation.json"
    output.write_text('{"existing":"preserved"}\n', encoding="utf-8")
    replay_decision = sources["replay"] / "decision.json"
    replay_decision.write_text('{"status":"HALT"}\n', encoding="utf-8")
    # Deliberately leave the old manifest, so the first failure is a sealed hash mismatch.
    decision, payload = BUILDER.build_attestation(sources, output, publish=True)
    assert decision["verdict"] == "HALT_E7_STEPS_1_TO_6_ATTESTATION"
    assert payload is None
    assert output.read_text(encoding="utf-8") == '{"existing":"preserved"}\n'


def test_pass_audit_without_publish_performs_zero_search_and_writes_nothing(tmp_path):
    sources = passing_sources(tmp_path)
    output = tmp_path / "attestation.json"
    decision, payload = BUILDER.build_attestation(sources, output, publish=False)
    assert decision["verdict"] == "PASS_E7_STEPS_1_TO_6_ATTESTATION_READY"
    assert decision["formal_attestation_published"] is False
    assert decision["search_performed"] is False
    assert payload["route_search_evaluations_during_attestation"] == 0
    assert not output.exists()
