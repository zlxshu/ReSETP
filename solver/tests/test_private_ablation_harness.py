from __future__ import annotations

import csv
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "run_private_ablation.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("private_ablation_harness", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = harness
SPEC.loader.exec_module(harness)


def test_arm_switches_change_the_participating_components() -> None:
    assert harness.ARM_DEFINITIONS["A0"].participating_components == (
        "independent_route_kernel",
        "route_level_trip_assignment_crossover",
        "deterministic_charging_completion",
    )
    assert tuple(harness.ARM_DEFINITIONS) == ("A0",)
    assert not harness.ARM_DEFINITIONS["A0"].include_propulsion_proxy

    captured = {}

    def runtime_type(**switches):
        captured.update(switches)
        return switches

    runtime = harness.runtime_treatment_for_arm("A0", runtime_type)
    assert runtime == captured == {
        "schedule_cross_repair_fallback": False,
        "schedule_all_changed_move_evaluation": False,
        "fleet_activation_enabled": False,
    }


def test_removed_oracle_arm_is_rejected_by_the_cli() -> None:
    with pytest.raises(SystemExit):
        harness._parse_args(
            (
                "unused-output",
                "--instance-id",
                "private-test",
                "--seeds",
                "11",
                "--wall-clock-seconds",
                "1",
                "--arms",
                "A2",
                "--dry-run",
            )
        )


def test_pair_validation_rejects_an_injected_context_mismatch() -> None:
    common = harness.PairIdentity(
        arm="A0",
        instance_id="private-test",
        seed=11,
        initial_population_sha256="a" * 64,
        main_rng_seed=11,
        evaluation_context_sha256="b" * 64,
        wall_clock_budget_seconds=1200.0,
    )
    harness.validate_pairing((common, replace(common, arm="FUTURE")))

    mismatched = replace(
        common,
        arm="FUTURE",
        evaluation_context_sha256="c" * 64,
    )
    with pytest.raises(harness.PairingMismatchError) as captured:
        harness.validate_pairing((common, mismatched))
    assert "evaluation_context_sha256" in str(captured.value)
    assert "refusing to run" in str(captured.value)


def test_result_package_contains_every_required_report_field(tmp_path: Path) -> None:
    def row(arm: str, cost: float) -> dict[str, object]:
        payload = {field: 0 for field in harness.REQUIRED_RAW_FIELDS}
        payload.update(
            {
                "instance_id": "private-test",
                "seed": 11,
                "arm": arm,
                "run_status": "STOPPED_BY_CALLER",
                "wall_clock_budget_seconds": 1200.0,
                "initial_population_sha256": "a" * 64,
                "main_rng_seed": 11,
                "evaluation_context_sha256": "b" * 64,
                "total_cost": cost,
                "total_emissions_kg": 50.0,
                "full_evaluation_feasible": True,
                "hard_violation_count": 0,
                "hard_violations_json": "[]",
                "customers_served": 10,
                "customers_total": 10,
                "demand_served": 100.0,
                "demand_total": 100.0,
                "demand_completion_ratio": 1.0,
                "completed_generations": 7,
                "time_to_best_seconds": 3.0,
                "total_algorithm_wall_seconds": 4.0,
                "dss_calls": 0,
                "dss_feasible": 0,
                "dss_infeasible": 0,
                "dss_search_exhausted": 0,
                "dss_wall_seconds_p50": None,
                "dss_wall_seconds_p95": None,
                "dss_wall_seconds_p99": None,
                "cost_breakdown_json": json.dumps({"total_cost": cost}),
            }
        )
        payload.update(harness._assess_row(payload).row_fields())
        return payload

    output = tmp_path / "package"
    overall = harness.assess_run(
        termination_ok=True,
        feasible_ok=True,
        customers_complete=True,
        demand_complete=True,
        success_verdict="PRIVATE_ABLATION_BATCH_COMPLETE",
        failure_verdict="PRIVATE_ABLATION_BATCH_FAILED",
    )
    harness.write_result_package(
        output,
        (row("A0", 100.0),),
        {"status": "COMPLETED", "pair_validation": "PASSED"},
        overall,
    )

    with (output / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert set(harness.REQUIRED_RAW_FIELDS).issubset(reader.fieldnames or ())
        assert len(list(reader)) == 1
    report = (output / "report.md").read_text(encoding="utf-8")
    assert "各臂 Best / Avg" in report
    assert "同种子配对差" in report
    assert "服务客户" in report
    assert "需求完成度" in report
    assert (output / "metadata.json").is_file()
    hashes = json.loads(
        (output / "artifact_hashes.json").read_text(encoding="utf-8")
    )
    assert set(hashes) == {
        "decision.json",
        "metadata.json",
        "raw_runs.csv",
        "report.md",
    }


def test_cost_does_not_make_rejected_ablation_rows_successful() -> None:
    complete = {
        "run_status": "STOPPED_BY_CALLER",
        "total_cost": 100.0,
        "full_evaluation_feasible": True,
        "hard_violation_count": 0,
        "customers_served": 10,
        "customers_total": 10,
        "demand_served": 100.0,
        "demand_total": 100.0,
    }
    complete.update(harness._assess_row(complete).row_fields())
    assert harness._successful_rows((complete,)) == [complete]

    for changed in (
        {"run_status": "INTERNAL_ERROR"},
        {"full_evaluation_feasible": False, "hard_violation_count": 1},
        {"customers_served": 9},
        {"demand_served": 99.0},
    ):
        row = {**complete, **changed}
        row.update(harness._assess_row(row).row_fields())
        assert row["total_cost"] == 100.0
        assert harness._successful_rows((row,)) == []
