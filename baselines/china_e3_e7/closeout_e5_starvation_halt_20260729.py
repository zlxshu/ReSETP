#!/usr/bin/env python3
"""Close E5 at the blind-pilot starvation scheduling boundary."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "baselines/china_e3_e7/e5_nonlinear_20260729"
TASK_ID = "E5-NONLINEAR-CHARGING-01"
BUDGETS = (32, 56, 80, 160, 240)
ARMS = ("L100_control", "NL90_mild")
HALT_CODE = "HALT_PILOT_STARVATION_SCHEDULE_NOT_CONSTRUCTIBLE"
NOT_RUN = "NOT_RUN_UPSTREAM_PILOT_STARVATION_GATE_HALT"


def canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def payload_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_bytes(payload))
    temporary.replace(path)


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def atomic_text(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def read_pilot() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    allowed_blind_objective_attestation = {
        "strict_improvement_flags_without_objectives"
    }
    for budget in BUDGETS:
        task_dir = OUT / "pilot" / f"budget-{budget}" / "tasks"
        paths = sorted(
            path for path in task_dir.glob("*.json") if not path.name.startswith("._")
        )
        if len(paths) != 30:
            raise RuntimeError(
                f"HALT_CLOSEOUT_EXPECTED_30_PILOT_UNITS:{budget}:{len(paths)}"
            )
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            forbidden_keys = [
                key
                for key in payload
                if (
                    "cost" in key.lower()
                    or (
                        "objective" in key.lower()
                        and key not in allowed_blind_objective_attestation
                    )
                )
            ]
            if forbidden_keys:
                raise RuntimeError(
                    f"HALT_CLOSEOUT_PILOT_NOT_RESULT_BLIND:{path}:{forbidden_keys}"
                )
            if int(payload["budget"]) != budget or payload["status"] != "PASS":
                raise RuntimeError(f"HALT_CLOSEOUT_INVALID_PILOT_UNIT:{path}")
            rows.append(
                {
                    "task_id": TASK_ID,
                    "phase": "PILOT_BLIND",
                    "budget": budget,
                    "instance_id": payload["instance_id"],
                    "sample_role": payload["sample_role"],
                    "seed": payload["seed"],
                    "arm": payload["arm"],
                    "complete_candidate_evaluations_S": payload[
                        "complete_candidate_evaluations_S"
                    ],
                    "last_strict_improvement_evaluation_L": payload[
                        "last_strict_improvement_evaluation_L"
                    ],
                    "last_strict_improvement_fraction_L_over_S": payload[
                        "last_strict_improvement_fraction_L_over_S"
                    ],
                    "starved_L_over_S_gt_0_5": payload["starved_L_over_S_gt_0_5"],
                    "wallclock_safety_triggered": int(
                        payload["wallclock_safety_triggered"]
                    ),
                    "elapsed_wall_seconds": payload["elapsed_wall_seconds"],
                    "elapsed_cpu_seconds": payload["elapsed_cpu_seconds"],
                    "common_initial_solution_sha256": payload[
                        "common_initial_solution_sha256"
                    ],
                    "status": payload["status"],
                    "scientific_endpoints": NOT_RUN,
                }
            )
        decision_path = OUT / "pilot" / f"budget-{budget}" / "blind_decision.json"
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        if decision["objective_or_between_arm_cost_fields_present"]:
            raise RuntimeError("HALT_CLOSEOUT_BLIND_ATTESTATION_FAILED")
        decisions.append(decision)
    if (OUT / "pilot" / "budget-320" / "tasks").exists():
        non_sidecars = [
            path
            for path in (OUT / "pilot" / "budget-320" / "tasks").glob("*.json")
            if not path.name.startswith("._")
        ]
        if non_sidecars:
            raise RuntimeError("HALT_CLOSEOUT_320_UNIT_WAS_STARTED")
    return rows, decisions


def verify_locks() -> dict[str, Any]:
    source_lock = json.loads((OUT / "source_lock.json").read_text(encoding="utf-8"))
    drift: list[str] = []
    for group in ("source_sha256", "core_data_sha256"):
        for relative, expected in source_lock[group].items():
            path = REPO / relative
            if not path.is_file() or file_sha256(path) != expected:
                drift.append(relative)
    if drift:
        raise RuntimeError(f"HALT_CLOSEOUT_LOCK_DRIFT:{sorted(set(drift))}")
    return source_lock


def structural_boundary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    proof: dict[str, Any] = {}
    for budget in (160, 240):
        selected = [row for row in rows if int(row["budget"]) == budget]
        seeds_by_arm: dict[str, list[int]] = {}
        for arm in ARMS:
            seeds_by_arm[arm] = sorted(
                int(row["seed"])
                for row in selected
                if row["arm"] == arm
                and row["instance_id"] == "cn-prd-50c-01-V2-LOCATIONS"
                and int(row["last_strict_improvement_evaluation_L"])
                == int(row["complete_candidate_evaluations_S"]) - 1
            )
        proof[str(budget)] = {
            "L_equals_S_minus_1_50c_seeds_by_arm": seeds_by_arm,
            "common_seed_set": sorted(
                set(seeds_by_arm[ARMS[0]]).intersection(seeds_by_arm[ARMS[1]])
            ),
        }
    expected = [1, 2, 3, 4, 5, 6, 7, 8, 10]
    if any(proof[str(budget)]["common_seed_set"] != expected for budget in (160, 240)):
        raise RuntimeError("HALT_CLOSEOUT_STRUCTURAL_PROOF_NOT_REPRODUCED")
    return proof


def main() -> int:
    if (OUT / "execution_lock.json").exists():
        raise RuntimeError("HALT_CLOSEOUT_FORMAL_BUDGET_WAS_FROZEN")
    if (OUT / "formal").exists() and any((OUT / "formal").rglob("*.json")):
        raise RuntimeError("HALT_CLOSEOUT_FORMAL_ARTIFACT_EXISTS")
    source_lock = verify_locks()
    rows, pilot_decisions = read_pilot()
    proof = structural_boundary(rows)
    atomic_csv(OUT / "raw_runs.csv", rows)

    table_rows = []
    for item in pilot_decisions:
        by_arm = {row["arm"]: row for row in item["decisions"]}
        table_rows.append(
            {
                "budget": item["budget"],
                "L100_starved": by_arm[ARMS[0]]["starved_unit_count"],
                "NL90_starved": by_arm[ARMS[1]]["starved_unit_count"],
                "passes": all(
                    bool(row["passes_share_le_0_20"]) for row in item["decisions"]
                ),
            }
        )
    decision = {
        "schema_version": "E5-DECISION-v1",
        "task_id": TASK_ID,
        "status": "HALT",
        "halt_code": HALT_CODE,
        "verdict": "NOT_EVALUATED",
        "pilot_cost_blinding_preserved": True,
        "tested_budgets": list(BUDGETS),
        "pilot_summary": table_rows,
        "structural_boundary_proof": proof,
        "reason": (
            "The upward budget mapping adds complete evaluations before the "
            "mandatory final route-pool recombination. For nine 50c seeds in "
            "both arms, the final strict improvement remained at S-1 for "
            "S=160 and S=240. Increasing S under the same schedule cannot "
            "create post-improvement budget, so a passing tier is not "
            "constructible without a methodology change."
        ),
        "required_endpoints": {
            "nonlinear_feasibility_rate": NOT_RUN,
            "linear_plan_false_feasible_count_and_causes": NOT_RUN,
            "full_model_cost_effect": NOT_RUN,
            "charging_session_soc_and_duration_differences": NOT_RUN,
        },
        "forbidden_claims": [
            "no arm-to-arm cost comparison",
            "no nonlinear feasibility-rate claim",
            "no positive, near-zero, negative, or mixed scientific verdict",
        ],
        "approval_needed": (
            "A user-approved evaluation schedule that supplies deterministic "
            "post-recombination complete-candidate evaluations, or another "
            "explicit starvation definition, is required before formal E5."
        ),
    }
    decision["decision_id"] = payload_sha256(decision)
    atomic_json(OUT / "decision.json", decision)

    metadata = {
        "schema_version": "E5-METADATA-v1",
        "task_id": TASK_ID,
        "status": "HALT",
        "halt_code": HALT_CODE,
        "closed_at_utc": datetime.now(UTC).isoformat(),
        "pilot_budgets_completed": list(BUDGETS),
        "pilot_unit_count": len(rows),
        "pilot_units_per_budget": 30,
        "pilot_files_contain_objectives_or_arm_cost_differences": False,
        "formal_search_status": NOT_RUN,
        "independent_nonlinear_checker_status": NOT_RUN,
        "selected_common_formal_budget": None,
        "source_lock_id": source_lock["lock_id"],
        "protected_source_sha256": source_lock["protected_source_sha256"],
        "raw_runs_semantics": (
            "blind pilot convergence records only; not formal scientific runs"
        ),
    }
    atomic_json(OUT / "metadata.json", metadata)
    halt_certificate = {
        "schema_version": "E5-HALT-CERTIFICATE-v1",
        "task_id": TASK_ID,
        "status": "HALT",
        "halt_code": HALT_CODE,
        "decision_id": decision["decision_id"],
        "no_budget_320_unit_started": True,
        "no_formal_plan_started": True,
        "pilot_cost_blinding_preserved": True,
        "source_and_core_data_lock_verified": True,
        "structural_boundary_proof": proof,
    }
    halt_certificate["certificate_id"] = payload_sha256(halt_certificate)
    atomic_json(OUT / "halt_certificate.json", halt_certificate)

    pilot_table = "\n".join(
        "| {budget} | {L100_starved}/15 ({lrate:.1f}%) | "
        "{NL90_starved}/15 ({nrate:.1f}%) | 不通过 |".format(
            lrate=100.0 * row["L100_starved"] / 15,
            nrate=100.0 * row["NL90_starved"] / 15,
            **row,
        )
        for row in table_rows
    )
    report = f"""# E5-NONLINEAR-CHARGING-01 HALT 报告

## 结论

本任务在结果盲预算 pilot 处 HALT，未进入正式两臂求解，也未查看或计算任何臂间成本差。HALT 码为 `{HALT_CODE}`。这不是负向、接近零或正向的 E5 科学结果；四个强制端点全部记为 `{NOT_RUN}`，不得据此改写论文结论。

## 预算 pilot 结果

两臂在每一档都使用相同的完整候选评价数，15 个预定单元全部保留。饥饿判据严格使用 `L/S>0.5`，该类单元占比超过 20% 即不合格。

| 完整评价预算 S | L100_control 饥饿单元 | NL90_mild 饥饿单元 | 判定 |
|---:|---:|---:|:---|
{pilot_table}

32、56、80 三档全部失败后，执行器按用户硬条件向上运行了 160 和 240，未接受较低档。`raw_runs.csv` 含 5 档 × 30 单元 = 150 条结果盲收敛记录，只含 L、S、L/S、改进布尔序列的派生判定与资源信息，不含目标值或成本差。

## 真实方法边界

在 160 档，50c-01 的种子 1--8、10 对两臂都在第 159/160 次完整评价才出现最后一次严格改进；在 240 档，同一组种子对两臂都在第 239/240 次才严格改进。当前路线池程序把 `route_pool_candidate_or_parent` 固定放在倒数第二次评价，把 `final_independent_certificate` 放在最后一次评价。向上加档只扩大此前的三个视角档案候选数，最终路线池重组仍固定处于 `S−1`。因此，对这些由最终重组产生严格改进的单元，无论把 S 提到 320、400 或更高，现有调度都不会产生“改进后的剩余评价预算”，`L/S` 会继续接近 1。

继续跑更高档并不能检验用户定义的防饥饿要求，只会重复一个结构上不可通过的调度。要继续 E5，必须先由用户批准一种能在最终重组之后提供确定性完整候选评价的调度，或明确批准另一种饥饿定义。这属于方法与预算口径变更，不能由执行代理自行决定。

## 强制端点状态

共同非线性检查器下的两臂可行率：`{NOT_RUN}`。

线性计划假可行数、占比与原因分类：`{NOT_RUN}`。

共同可行单元上的完整模型成本效应：`{NOT_RUN}`。

逐充电会话的起止 SOC、线性与非线性持续时间差：`{NOT_RUN}`。

不可行单元没有从任何科学分母中被剔除；更准确地说，正式科学样本尚未产生，因此没有可报告的正式分母、可行率或成本条件样本。

## 完整性与监控

240 档完成后，监控器在 320 档任何单元落盘前暂停并安全停止进程组。正式预算未冻结，`execution_lock.json` 不存在，`formal/` 中没有方案或证书。`cost.py`、`check.py`、`search/evaluation.py` 的关闭哈希与跑前锁一致。任务使用独立 `monitor.json`，`ai.enabled=false`；未扫描或等待全局 Codex 作业池，也未等待 E3/E6。
"""
    atomic_text(OUT / "report.md", report)

    excluded_names = {"artifact_hashes.json", "done.json"}
    artifact_rows = []
    for path in sorted(item for item in OUT.rglob("*") if item.is_file()):
        relative = str(path.relative_to(OUT))
        if (
            relative in excluded_names
            or relative.startswith("monitor_runtime/")
            or path.name.startswith("._")
        ):
            continue
        artifact_rows.append(
            {
                "path": relative,
                "sha256": file_sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    manifest = {
        "schema_version": "E5-ARTIFACT-HASHES-v1",
        "task_id": TASK_ID,
        "status": "HALT",
        "halt_code": HALT_CODE,
        "hash_algorithm": "sha256",
        "excluded": [
            "artifact_hashes.json",
            "done.json",
            "monitor_runtime/**",
            "._* AppleDouble sidecars",
        ],
        "artifacts": artifact_rows,
        "protected_source_sha256_at_closeout": source_lock["protected_source_sha256"],
    }
    manifest["manifest_id"] = payload_sha256(manifest)
    atomic_json(OUT / "artifact_hashes.json", manifest)
    required = (
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "artifact_hashes.json",
        "report.md",
    )
    done = {
        "schema_version": "E5-DONE-v1",
        "task_id": TASK_ID,
        "status": "HALT",
        "halt_code": HALT_CODE,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "required_artifacts": list(required),
        "required_artifact_sha256": {
            name: file_sha256(OUT / name) for name in required
        },
        "manifest_id": manifest["manifest_id"],
        "decision_id": decision["decision_id"],
        "halt_certificate_id": halt_certificate["certificate_id"],
    }
    done["done_id"] = payload_sha256(done)
    atomic_json(OUT / "done.json", done)
    print(f"HALT_READY {OUT / 'done.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
