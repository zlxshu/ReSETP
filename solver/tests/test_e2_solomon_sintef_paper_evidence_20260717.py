from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder = load_script(
    "test_e2_solomon_sintef_paper_builder",
    "baselines/paper_story/build_e2_solomon_sintef_paper_evidence_20260717.py",
)


def test_display_instances_are_predeclared_two_per_class() -> None:
    assert builder.DISPLAY_INSTANCES == (
        "C101", "C109", "C201", "C208", "R101", "R112",
        "R201", "R211", "RC101", "RC108", "RC201", "RC208",
    )
    assert len(builder.DISPLAY_INSTANCES) == 12


def test_instance_table_uses_hierarchical_bks_and_conditional_gap_count() -> None:
    rows = []
    for name in builder.DISPLAY_INSTANCES:
        rows.append(
            {
                "instance": name,
                "bks_vehicle_count": "10",
                "bks_distance": "800.00",
                "best_route_count": "10",
                "best_distance": "810.00",
                "avg_route_count": "10.2",
                "avg_distance": "820.00",
                "avg_gap_pct": "2.5",
                "gap_valid_runs": "8",
                "avg_process_cpu_seconds": "12.3",
                "bks_hits": "1",
                "runs": "10",
                "valid_runs": "9",
            }
        )
    rendered = builder.render_instance_table(rows)
    assert "BKS$(K,D)$" in rendered
    assert "Avg Gap/\\%" in rendered
    assert "2.50(8)" in rendered
    assert "BKS命中" in rendered
    assert all(name in rendered for name in builder.DISPLAY_INSTANCES)
    data_rows = [line for line in rendered.splitlines() if line.startswith(builder.DISPLAY_INSTANCES)]
    assert len(data_rows) == 12
    assert all(line.endswith(r"\\") for line in data_rows)


def test_class_table_rows_have_valid_latex_line_terminators() -> None:
    classes = [
        {
            "class": name,
            "instance_count": "8",
            "complete_instance_count": "8",
            "avg_best_route_count": "10.0",
            "avg_best_distance": "800.0",
            "CNV": "80",
            "CTD": "6400.0",
            "avg_process_cpu_seconds": "12.3",
            "avg_elapsed_seconds": "13.4",
            "avg_time_to_best_seconds": "4.5",
            "valid_runs": "80",
            "Runs": "80",
        }
        for name in ("C1", "C2", "R1", "R2", "RC1", "RC2")
    ]
    rendered = builder.render_class_table(classes)
    data_rows = [
        line for line in rendered.splitlines()
        if line.startswith(("C1", "C2", "R1", "R2", "RC1", "RC2", "合计"))
    ]
    assert len(data_rows) == 7
    assert all(line.endswith(r"\\") for line in data_rows)


def test_interpretation_preserves_failures_and_limits_claim_scope() -> None:
    rows = [
        {
            "status": "OK" if index < 559 else "ALGORITHM_FAILURE",
            "reached_bks_vehicle_count": "True" if index < 400 else "False",
            "full_bks_hit": "True" if index < 20 else "False",
        }
        for index in range(560)
    ]
    instances = [
        {"instance": "C101", "avg_gap_pct": "1.0"},
        {"instance": "R101", "avg_gap_pct": "4.0"},
    ]
    rendered = builder.render_interpretation(rows, instances)
    assert "1次失败或无效" in rendered
    assert "任务身份和失败代码" in rendered
    assert "不替代" in rendered


def test_summary_values_must_recompute_from_raw_rows() -> None:
    references = builder.runner.read_references()
    raw = []
    for name in builder.runner.FORMAL_INSTANCES:
        reference = references[name]
        raw.append(
            {
                "instance": name,
                "class": reference["class"],
                "seed": "1",
                "route_count": str(reference["bks_vehicle_count"]),
                "distance_double": str(reference["bks_distance_published_2dp"] + 1.0),
                "distance_rounded_2": str(reference["bks_distance_published_2dp"] + 1.0),
                "bks_vehicle_count": str(reference["bks_vehicle_count"]),
                "bks_distance": str(reference["bks_distance_published_2dp"]),
                "distance_gap_pct": "0.1",
                "eval_budget": "4000",
                "evaluations": "4000",
                "candidate_scores": "4000",
                "repair_delta_count": "0",
                "violation_count": "0",
                "process_cpu_seconds": "1.0",
                "elapsed_seconds": "2.0",
                "task_elapsed_seconds": "2.1",
                "time_to_best_seconds": "0.5",
                "reached_bks_vehicle_count": "True",
                "full_bks_hit": "False",
                "bks_conflict_candidate": "False",
                "algorithm_reported_feasible": "True",
                "feasible": "True",
                "independent_recompute_pass": "True",
                "timeout": "False",
                "status": "OK",
            }
        )
    normalized = builder.normalized_raw_rows(raw)
    instances = builder.runner.build_instance_summary(normalized)
    classes = builder.runner.build_class_summary(instances)
    instance_csv = [{key: str(value) for key, value in row.items()} for row in instances]
    class_csv = [{key: str(value) for key, value in row.items()} for row in classes]
    builder.assert_summary_rows_match_raw(raw, instance_csv, class_csv)
    instance_csv[0]["avg_distance"] = "999999"
    with pytest.raises(builder.E2SolomonEvidenceError, match="differs from raw rows"):
        builder.assert_summary_rows_match_raw(raw, instance_csv, class_csv)


def test_required_sources_include_contract_and_final_run_state() -> None:
    assert "contract.json" in builder.REQUIRED_SOURCE_FILES
    assert "run_state.json" in builder.REQUIRED_SOURCE_FILES


def test_solution_validation_rejects_rounded_distance_tamper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    solution = {"routes": []}
    record = {
        "task_key": "C101__seed1",
        "instance": "C101",
        "seed": 1,
        "status": "OK",
        "solution_sha256": builder.runner.canonical_sha256(solution),
        "solution": solution,
        "independent_recomputation": {
            "passed": True,
            "failures": [],
            "route_count": 0,
            "distance_double": 1.234,
            "distance_rounded_2": 1.23,
        },
    }
    (tmp_path / "solutions.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    monkeypatch.setattr(builder.runner, "FORMAL_INSTANCES", ("C101",))
    monkeypatch.setattr(builder.runner, "FORMAL_SEEDS", (1,))
    monkeypatch.setattr(
        builder.runner,
        "pure_vrptw_recompute",
        lambda *_args, **_kwargs: record["independent_recomputation"],
    )
    raw = [{
        "task_key": "C101__seed1",
        "instance": "C101",
        "seed": "1",
        "status": "OK",
        "solution_sha256": record["solution_sha256"],
        "independent_recompute_pass": "True",
        "route_count": "0",
        "distance_double": "1.234",
        "distance_rounded_2": "9.99",
        "violation_count": "0",
        "algorithm_reported_feasible": "True",
        "feasible": "True",
    }]
    with pytest.raises(builder.E2SolomonEvidenceError, match="rounded solution distance differs"):
        builder.validate_solution_records(tmp_path, raw, {"C101__seed1"})


def test_decision_failure_list_must_recompute_from_raw_rows() -> None:
    rows = [
        {"task_key": "C101__seed1", "status": "OK"},
        {"task_key": "C101__seed2", "status": "ALGORITHM_FAILURE"},
    ]
    valid = {
        "verdict": "FORMAL_COMPLETE_WITH_ALGORITHM_FAILURES",
        "failures": ["C101__seed2"],
        "failure_count": 1,
        "bks_conflict_candidate_count": 0,
        "all_unfavorable_results_retained": True,
    }
    builder.assert_decision_matches_raw(valid, rows)
    invalid = {**valid, "failures": []}
    with pytest.raises(builder.E2SolomonEvidenceError, match="decision failures differ"):
        builder.assert_decision_matches_raw(invalid, rows)


def test_task_artifact_manifest_rejects_incident_tamper(tmp_path: Path) -> None:
    incident = tmp_path / ".tasks/attempts/C101__seed1/attempt-1/incident.json"
    incident.parent.mkdir(parents=True)
    incident.write_text("preserved", encoding="utf-8")
    (tmp_path / "task_artifact_hashes.json").write_text(
        json.dumps({str(incident.relative_to(tmp_path)): builder.sha256(incident)}),
        encoding="utf-8",
    )
    builder.verify_task_artifact_manifest(tmp_path)
    incident.write_text("tampered", encoding="utf-8")
    with pytest.raises(builder.E2SolomonEvidenceError, match="task-artifact hash drift"):
        builder.verify_task_artifact_manifest(tmp_path)
