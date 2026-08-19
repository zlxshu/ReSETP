from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "solver/scripts/experiment_acceptance.py"
SPEC = importlib.util.spec_from_file_location("experiment_acceptance", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
acceptance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = acceptance
SPEC.loader.exec_module(acceptance)


def test_acceptance_requires_every_existing_contract_fact() -> None:
    common = {
        "termination_ok": True,
        "feasible_ok": True,
        "customers_complete": True,
        "demand_complete": True,
        "audit_ok": True,
    }
    assert acceptance.assess_run(**common).accepted is True

    for field in common:
        rejected = acceptance.assess_run(**{**common, field: False})
        assert rejected.accepted is False
        assert rejected.failure_reasons

    assert acceptance.assess_run(**{**common, "audit_ok": None}).accepted is False


def test_five_file_writer_keeps_failure_evidence_and_nonzero_exit(
    tmp_path: Path,
) -> None:
    output = tmp_path / "failed-package"
    output.mkdir()
    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("run_status", "error"))
        writer.writeheader()
        writer.writerow({"run_status": "INTERNAL_ERROR", "error": "boom"})
    rejected = acceptance.assess_run(
        termination_ok=False,
        feasible_ok=True,
        customers_complete=True,
        demand_complete=True,
        success_verdict="FORMAL_COMPLETE",
        failure_verdict="FORMAL_FAILED",
    )

    hashes = acceptance.finalize_five_file_package(
        output,
        acceptance=rejected,
        metadata={"purpose": "unit test"},
        decision={"detail": "preserve failure"},
        report_text="# Failed package\n",
    )

    assert acceptance.package_exit_code(rejected) == 2
    assert set(acceptance.FIVE_FILE_PACKAGE) <= {
        path.name for path in output.iterdir()
    }
    metadata = json.loads((output / "metadata.json").read_text("utf-8"))
    decision = json.loads((output / "decision.json").read_text("utf-8"))
    assert metadata["status"] == "FAILED"
    assert decision["accepted"] is False
    assert decision["verdict"] == "FORMAL_FAILED"
    assert "raw_runs.csv" in hashes
    assert "artifact_hashes.json" not in hashes
    checked = acceptance.validate_five_file_package(
        output,
        require_accepted=False,
    )
    assert checked["decision"]["verdict"] == "FORMAL_FAILED"


def _accepted_package(output: Path) -> None:
    output.mkdir()
    (output / "raw_runs.csv").write_text("status\nCOMPLETE\n", "utf-8")
    accepted = acceptance.assess_run(
        termination_ok=True,
        feasible_ok=True,
        customers_complete=True,
        demand_complete=True,
        success_verdict="TEST_COMPLETE",
    )
    acceptance.finalize_five_file_package(
        output,
        acceptance=accepted,
        metadata={"purpose": "hash-map fixture"},
        decision={"rows": 1},
        report_text="# Complete package\n",
    )


def test_validator_requires_exact_artifact_hash_key_set(tmp_path: Path) -> None:
    missing_key = tmp_path / "missing-key"
    _accepted_package(missing_key)
    hashes_path = missing_key / "artifact_hashes.json"
    hashes = json.loads(hashes_path.read_text("utf-8"))
    hashes.pop("raw_runs.csv")
    hashes_path.write_text(json.dumps(hashes), "utf-8")
    with pytest.raises(RuntimeError, match="artifact hash map mismatch"):
        acceptance.validate_five_file_package(missing_key)

    unexpected_file = tmp_path / "unexpected-file"
    _accepted_package(unexpected_file)
    (unexpected_file / "unregistered.txt").write_text("extra\n", "utf-8")
    with pytest.raises(RuntimeError, match="artifact hash map mismatch"):
        acceptance.validate_five_file_package(unexpected_file)


def test_done_is_an_operational_marker_outside_the_hash_map(tmp_path: Path) -> None:
    output = tmp_path / "done-marker"
    _accepted_package(output)
    (output / "DONE").write_text("TEST_COMPLETE\n", "utf-8")
    checked = acceptance.validate_five_file_package(
        output,
        expected_success_verdict="TEST_COMPLETE",
    )
    assert "DONE" not in checked["artifact_hashes"]
