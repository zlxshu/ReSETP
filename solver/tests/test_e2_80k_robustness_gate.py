from __future__ import annotations

import csv
from pathlib import Path

from baselines.e2_alns import e2_80k_robustness_gate as gate
from baselines.e2_alns import e2_80k_robustness_verify as verify
from baselines.e2_alns import e2_80k_watchdog as watchdog


def test_manifest_is_exactly_24_search_tasks_and_uses_frozen_identity(tmp_path: Path) -> None:
    tasks = gate.build_tasks(
        tmp_path,
        tmp_path / "frozen",
        gate.FORMAL_INSTANCES,
        [1, 2, 3],
        4000,
        "formal",
    )

    assert len(tasks) == 24
    assert len({task["run_id"] for task in tasks}) == 24
    assert {task["algorithm"] for task in tasks} == {"staged_hybrid_carbon_pair", "LNS"}
    assert {task["scenario_type"] for task in tasks} == {"formal_goeke80"}
    assert {task["head"] for task in tasks} == {gate.FROZEN_COMMIT}
    assert {task["eval_budget"] for task in tasks} == {4000}
    assert all(Path(task["bundle_dir"]).is_absolute() for task in tasks)


def test_resume_contract_counts_search_tasks_not_expanded_evidence_rows() -> None:
    pair_task = {
        "run_id": "pair",
        "algorithm": "staged_hybrid_carbon_pair",
        "eval_budget": 4000,
    }
    pair_row = {
        "run_id": "pair",
        "gate_status": "OK",
        "actual_evals": 4000,
        "violation_count": 0,
        "solution_json": "{}",
        "charging_ablation_json": '{"solution": {}}',
        "head": gate.FROZEN_COMMIT,
    }
    assert gate.task_row_complete(pair_row, pair_task)

    pair_row["charging_ablation_json"] = "{}"
    assert not gate.task_row_complete(pair_row, pair_task)


def test_appledouble_is_ignored_without_hiding_real_changes() -> None:
    assert gate.apple_double_status("?? models/src/._setp_instance_lab")
    assert gate.apple_double_status("?? models/src/setp_instance_lab/.___init__.py")
    assert not gate.apple_double_status(" M solver/src/setp_solver/search/evaluation.py")
    assert not gate.apple_double_status("?? real_new_file.py")


def test_watchdog_reads_24_task_ledger_not_36_row_evidence_table(tmp_path: Path) -> None:
    healthy = {
        "run_id": "task",
        "gate_status": "OK",
        "actual_evals": 4000,
        "eval_budget": 4000,
        "violation_count": 0,
    }
    write_rows(tmp_path / "task_runs.csv", [healthy, healthy | {"run_id": "task2"}])
    write_rows(tmp_path / "raw_runs.csv", [healthy | {"run_id": f"evidence{i}"} for i in range(36)])

    result = watchdog.snapshot(tmp_path, expected=24, stale_seconds=7200)

    assert result["completed_search_tasks"] == 2
    assert result["remaining_search_tasks"] == 22
    assert not result["complete"]


def test_formal_decision_excludes_structural_15c_from_mechanism_gate() -> None:
    metadata = {
        "phase": "formal",
        "scenario_type": "formal_goeke80",
        "battery_kwh": 80.0,
        "frozen_execution_commit": gate.FROZEN_COMMIT,
        "expected_tasks": 24,
        "expected_evidence_rows": 36,
        "eval_budget": 4000,
        "instances": list(gate.FORMAL_INSTANCES),
        "seeds": [1, 2, 3],
    }
    task_rows = [
        {
            "run_id": f"task{i}",
            "gate_status": "OK",
            "actual_evals": 4000,
            "violation_count": 0,
            "head": gate.FROZEN_COMMIT,
        }
        for i in range(24)
    ]
    raw_rows = []
    verified_rows = []
    for algorithm in verify.EXPECTED_ALGORITHMS:
        for index in range(12):
            run_id = f"{algorithm}-{index}"
            raw_rows.append({"run_id": run_id, "algorithm": algorithm})
            verified_rows.append({"run_id": run_id, "algorithm": algorithm, "verification_status": "OK"})
    pairs = [
        {
            "instance": gate.FORMAL_INSTANCES[index // 3],
            "seed": index % 3 + 1,
            "aware_gain_pct": 1.0,
        }
        for index in range(12)
    ]
    scale_summary = [
        {
            "instance": instance,
            "size": int(instance.split("-")[-2].removesuffix("c")),
            "pairs": 3,
            "mean_gain_pct": 1.0,
            "median_gain_pct": 1.0,
            "wins": 3,
            "ties": 0,
            "losses": 0,
        }
        for instance in gate.FORMAL_INSTANCES
    ]
    mechanism_summary = [
        {
            "instance": instance,
            "size": int(instance.split("-")[-2].removesuffix("c")),
            "rows": 3,
            "structural_no_ev": instance.endswith("-15c-01"),
            "majority_seed_signal": not instance.endswith("-15c-01"),
        }
        for instance in gate.FORMAL_INSTANCES
    ]

    decision = verify.decide(
        metadata,
        task_rows,
        raw_rows,
        verified_rows,
        {"failure_count": 0},
        pairs,
        scale_summary,
        mechanism_summary,
        {
            "verdict": "LMAIN_V3_INSTANCE_CONTRACT_OK",
            "failure_count": 0,
            "manifest_sha256": "manifest",
        },
    )

    assert decision["technical_contract_ok"]
    assert decision["algorithm_stability_supported"]
    assert decision["mechanism_visibility_supported"]
    assert decision["mechanism_eligible_scale_count"] == 3
    assert decision["fifteen_customer_mechanism_status"] == "STRUCTURAL_NO_EV_AVAILABLE"


def test_active_lmain_v3_bundle_hashes_match_activation_contract() -> None:
    metadata = {
        "instances": ["L-main-threeshift-50c-01"],
        "instance_manifest_sha256": gate.sha256_file(gate.ACTIVE_INSTANCE_MANIFEST),
    }

    result = verify.verify_instance_contract(metadata)

    assert result["verdict"] == "LMAIN_V3_INSTANCE_CONTRACT_OK"
    assert result["activation_verdict"] == "LMAIN_V3_READY"
    assert result["checked_instances"] == 1
    assert result["checked_bundle_files"] >= 9
    assert result["failure_count"] == 0


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
