#!/usr/bin/env python3
"""Seal the E5-v3 convergence-probe halt without rerunning the experiment.

This closeout utility is intentionally separate from the frozen v3 runner.  It
only validates the preserved anomaly scene and writes the required terminal
artifacts.  It never imports or invokes solver/search code.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "baselines/china_e3_e7/e5_nonlinear_v3_20260730"
MONITOR = OUT / "monitor_runtime/probe"
PACKET = MONITOR / "latest_ai_packet.json"
MONITOR_DONE = MONITOR / "done.json"
SOURCE_LOCK = OUT / "source_lock.json"
TASK_CARD = OUT / "task_card.json"
PROBE_LOG = OUT / "probe_run.log"

STATUS = "HALT_PROBE_AMBIGUOUS_NULL_OBJECTIVE_TRACE"
PROBE_CAP = 1500
FAILED_UNIT = (
    "cn-prd-50c-01-V2-LOCATIONS__seed-01__L100_control"
)
REQUIRED_OUTPUTS = (
    "metadata.json",
    "raw_runs.csv",
    "decision.json",
    "artifact_hashes.json",
    "report.md",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_text(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, payload: Any) -> None:
    atomic_text(
        path,
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


def atomic_csv(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, Any]],
) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def current_source_hashes(
    expected: dict[str, str],
) -> tuple[dict[str, str], list[dict[str, str]]]:
    actual: dict[str, str] = {}
    drift: list[dict[str, str]] = []
    for relative, expected_hash in sorted(expected.items()):
        path = ROOT / relative
        actual_hash = sha256(path)
        actual[relative] = actual_hash
        if actual_hash != expected_hash:
            drift.append(
                {
                    "path": relative,
                    "expected_sha256": expected_hash,
                    "actual_sha256": actual_hash,
                }
            )
    return actual, drift


def remove_appledouble_sidecars() -> list[str]:
    removed: list[str] = []
    for path in sorted(OUT.rglob("._*")):
        if path.is_file():
            removed.append(path.relative_to(OUT).as_posix())
            path.unlink()
    return removed


def main() -> int:
    if (OUT / "done.json").exists():
        raise RuntimeError("scientific done.json already exists; refusing overwrite")

    for path in (PACKET, MONITOR_DONE, SOURCE_LOCK, TASK_CARD, PROBE_LOG):
        if not path.is_file():
            raise RuntimeError(f"required preserved evidence missing: {path}")

    packet = read_json(PACKET)
    monitor_done = read_json(MONITOR_DONE)
    source_lock = read_json(SOURCE_LOCK)
    task_card = read_json(TASK_CARD)
    current = packet["current_status"]
    process = current["process"]
    findings = current["findings"]

    if monitor_done.get("state") != "ANOMALY":
        raise RuntimeError("monitor terminal state is not ANOMALY")
    if current.get("state") != "ANOMALY" or process.get("alive"):
        raise RuntimeError("probe process is not safely terminal")
    finding_codes = {item["code"] for item in findings}
    required_findings = {
        "FATAL_LOG_PATTERN",
        "PROCESS_EXITED_WITHOUT_COMPLETION",
    }
    if not required_findings.issubset(finding_codes):
        raise RuntimeError("expected anomaly findings are incomplete")

    log_text = PROBE_LOG.read_text(encoding="utf-8")
    expected_error = (
        "HALT_E5_V3_INVALID_COMPLETE_TRACE:" + FAILED_UNIT
    )
    if expected_error not in log_text:
        raise RuntimeError("preserved probe log lacks expected halt signature")

    all_actual, all_drift = current_source_hashes(
        source_lock["source_sha256"]
    )
    protected_actual, protected_drift = current_source_hashes(
        source_lock["protected_source_sha256"]
    )
    if all_drift or protected_drift:
        raise RuntimeError(
            "source hash drift detected during closeout; "
            + json.dumps(
                {
                    "all_drift": all_drift,
                    "protected_drift": protected_drift,
                },
                ensure_ascii=False,
            )
        )

    forbidden_outputs = (
        OUT / "budget_lock.json",
        OUT / "probe/convergence_curve.csv",
        OUT / "probe/convergence_summary.csv",
        OUT / "probe/summary.json",
        OUT / "formal",
    )
    unexpectedly_present = [
        path.relative_to(OUT).as_posix()
        for path in forbidden_outputs
        if path.exists()
    ]
    if unexpectedly_present:
        raise RuntimeError(
            "unexpected post-probe scientific outputs exist: "
            + ", ".join(unexpectedly_present)
        )

    old_directories = {
        "e5_nonlinear_20260729": (
            ROOT / "baselines/china_e3_e7/e5_nonlinear_20260729"
        ).is_dir(),
        "e5_nonlinear_v2_20260730": (
            ROOT / "baselines/china_e3_e7/e5_nonlinear_v2_20260730"
        ).is_dir(),
    }
    if not all(old_directories.values()):
        raise RuntimeError("one or more required prior evidence directories missing")

    removed_sidecars = remove_appledouble_sidecars()
    closed_at = datetime.now(UTC).isoformat()
    scene_path = Path(current["scene_path"]).relative_to(ROOT).as_posix()

    metadata = {
        "schema_version": "E5-METADATA-v3-halt",
        "task_id": "E5-NONLINEAR-CHARGING-V3-20260730",
        "status": STATUS,
        "closed_at_utc": closed_at,
        "execution_authorized": True,
        "probe": {
            "instance_id": "cn-prd-50c-01-V2-LOCATIONS",
            "seed": 1,
            "arms_requested": ["L100_control", "NL90_mild"],
            "budget_cap": PROBE_CAP,
            "workers": 1,
            "failed_unit": FAILED_UNIT,
            "failed_arm": "L100_control",
            "failed_before_atomic_unit_persistence": True,
            "actual_evaluations_consumed": None,
            "actual_evaluations_consumed_status": (
                "NOT_PERSISTED_BEFORE_EXCEPTION"
            ),
            "convergence_curve_status": "NOT_WRITTEN",
            "common_formal_cap_status": "NOT_SELECTED",
        },
        "formal_experiment": {
            "status": "NOT_RUN_UPSTREAM_PROBE_HALT",
            "instances_completed": [],
            "units_completed": 0,
            "expected_rows": int(task_card["formal_expected_rows"]),
        },
        "budget_semantics": {
            "meaning": "UPPER_CAP_NOT_QUOTA",
            "normal": "consumed <= cap with explicit scientific termination",
            "true_fault": "consumed > cap",
            "exact_consumption_required": False,
        },
        "halt": {
            "runner_signature": expected_error,
            "classification": (
                "AMBIGUOUS_UNDER_USER_STOP_RULE_NO_RETRY"
            ),
            "evidence_gap": (
                "The runner rejected a trace containing at least one null "
                "complete_objective before atomically persisting the trace, "
                "so the preserved evidence cannot distinguish a legitimate "
                "infeasible candidate from a caught translation/data error."
            ),
            "upstream_schema_fact": (
                "epochal_hgs records caught candidate failures with "
                "complete_objective=null and status=INFEASIBLE_OR_ERROR, "
                "and includes those rows in the evaluation-attempt counter."
            ),
        },
        "monitor": {
            "state": current["state"],
            "runtime_seconds": current["runtime_seconds"],
            "finding_codes": sorted(finding_codes),
            "scene_path": scene_path,
            "memory_pressure_free_percent_at_anomaly": current["system"][
                "memory_pressure_free_percent"
            ],
            "process_alive": process["alive"],
        },
        "environment": task_card["environment"],
        "source_lock": {
            "path": SOURCE_LOCK.relative_to(ROOT).as_posix(),
            "all_source_hashes_verified": True,
            "protected_source_hashes_verified": True,
            "source_sha256": all_actual,
            "protected_source_sha256": protected_actual,
        },
        "prior_evidence_directories_preserved": old_directories,
        "appledouble_sidecars_removed_before_hashing": removed_sidecars,
    }
    atomic_json(OUT / "metadata.json", metadata)

    raw_fields = [
        "phase",
        "instance_id",
        "sample_role",
        "seed",
        "arm",
        "status",
        "complete_candidate_evaluations_consumed",
        "complete_candidate_evaluations_consumed_status",
        "complete_candidate_budget_cap",
        "termination_reason",
        "termination_reason_class",
        "objective",
        "feasible",
        "elapsed_wall_seconds",
        "evidence_path",
        "note",
    ]
    raw_rows = [
        {
            "phase": "convergence_probe",
            "instance_id": "cn-prd-50c-01-V2-LOCATIONS",
            "sample_role": "PROBE",
            "seed": 1,
            "arm": "L100_control",
            "status": STATUS,
            "complete_candidate_evaluations_consumed": "",
            "complete_candidate_evaluations_consumed_status": (
                "NOT_PERSISTED_BEFORE_EXCEPTION"
            ),
            "complete_candidate_budget_cap": PROBE_CAP,
            "termination_reason": (
                "HALT_AMBIGUOUS_NULL_OBJECTIVE_TRACE"
            ),
            "termination_reason_class": (
                "HALT_NOT_SCIENTIFIC_TERMINATION"
            ),
            "objective": "",
            "feasible": "",
            "elapsed_wall_seconds": "",
            "evidence_path": "probe_run.log",
            "note": (
                "No actual-consumption value is recoverable from the "
                "preserved v3 artifacts; blank is intentional, not zero."
            ),
        }
    ]
    atomic_csv(OUT / "raw_runs.csv", raw_fields, raw_rows)

    endpoints = {
        "nl90_complete_feasibility_rate": {
            "status": "NOT_RUN_UPSTREAM_PROBE_HALT",
            "value": None,
        },
        "l100_feasible_nl90_physics_infeasible_count_and_causes": {
            "status": "NOT_RUN_UPSTREAM_PROBE_HALT",
            "value": None,
        },
        "paired_complete_model_cost_change_percent": {
            "status": "NOT_RUN_UPSTREAM_PROBE_HALT",
            "value": None,
        },
        "session_soc_and_linear_nonlinear_duration_difference": {
            "status": "NOT_RUN_UPSTREAM_PROBE_HALT",
            "value": None,
        },
    }
    decision = {
        "schema_version": "E5-DECISION-v3-halt",
        "task_id": "E5-NONLINEAR-CHARGING-V3-20260730",
        "status": STATUS,
        "decision": "STOP_NO_REPAIR_NO_RETRY_NO_FORMAL_RUN",
        "budget_cap": PROBE_CAP,
        "budget_cap_role": "PROBE_CAP_ONLY",
        "budget_source": "convergence_probe",
        "formal_budget_selected": False,
        "median_evaluations_consumed": None,
        "median_evaluations_consumed_status": (
            "NA_NO_PERSISTED_COMPLETE_UNIT"
        ),
        "instances_completed": [],
        "formal_seeds_planned": 10,
        "endpoints_answered": 0,
        "endpoints": endpoints,
        "interpretations": [
            {
                "case": "LEGITIMATE_INFEASIBLE_CANDIDATE_ATTEMPT",
                "classification": "RUNNER_CRITERION_FALSE_POSITIVE",
                "consequence": (
                    "A future approved runner revision should retain the row "
                    "in the consumed-attempt count, exclude its null objective "
                    "from incumbent-curve updates, preserve the status/failure "
                    "reason, and rerun from a new version."
                ),
            },
            {
                "case": "CAUGHT_TRANSLATION_OR_DATA_ERROR",
                "classification": "TRUE_TECHNICAL_FAULT",
                "consequence": (
                    "The upstream cause must be independently diagnosed and "
                    "authorized before any rerun; continuing would contaminate "
                    "the experiment."
                ),
            },
        ],
        "why_unresolved": (
            "The upstream status INFEASIBLE_OR_ERROR conflates the two cases, "
            "and the runner raised before persisting the trace and failure "
            "strings."
        ),
    }
    atomic_json(OUT / "decision.json", decision)

    report = f"""# E5 非线性充电 v3：收敛探针 HALT 报告

## 结论

本轮状态为 `{STATUS}`。预算语义已经在 runner 侧改为“上限而非配额”：实际完整候选评价次数小于等于上限属于正常，只有超过上限才触发预算控制故障；`route_pool_sp.py`、`epochal_hgs.py` 以及三个受保护求解/核查文件均未修改且哈希闭合。

1500 上限收敛探针在首个单元 `cn-prd-50c-01-V2-LOCATIONS / seed=1 / L100_control` 完成搜索返回后，触发 `HALT_E5_V3_INVALID_COMPLETE_TRACE`。runner 在原子写入该单元的 trace 与状态之前抛出异常，因此当前 v3 现场没有可恢复的实际评价次数、改善曲线或失败候选明细。正式共同预算未选出，50c 与 100c 正式实验均未启动，四个科学端点回答数为 0。没有把上一轮 v2 的 331 次冒充为本轮 v3 的已持久化计数。

## 预算语义修正

v3 runner 保留了 v2 的探针阶梯、并行框架、逐单元日志和原子落盘结构，只替换 runner 侧预算判据与账本字段。正常科学终止预定为 `BUDGET_CAP_REACHED`、`CANDIDATES_EXHAUSTED` 或 `NO_IMPROVEMENT`；`complete_candidate_evaluations_consumed > complete_candidate_budget_cap` 才是 `HALT_E5_V3_BUDGET_CAP_EXCEEDED`。本次停机不是“没有跑满 1500”触发的旧配额误报。

`raw_runs.csv` 同时保留 `complete_candidate_evaluations_consumed` 与 `complete_candidate_budget_cap`。首个单元的 cap 是 1500；consumed 因异常前未持久化而留空，并由 `complete_candidate_evaluations_consumed_status=NOT_PERSISTED_BEFORE_EXCEPTION` 明确区分于数值 0。

## 新停机的硬证据

监控器运行 120.486 秒后记录 `ANOMALY`，进程已退出；发现项为 `FATAL_LOG_PATTERN` 与 `PROCESS_EXITED_WITHOUT_COMPLETION`。异常现场为 `{scene_path}`，原始 traceback 在 `probe_run.log`。异常时系统 `memory_pressure` 可用比例为 {current["system"]["memory_pressure_free_percent"]:.0f}%，本轮按预检决定使用 1 个 worker。

静态只读核查表明，`epochal_hgs.py` 会在候选翻译或完整化抛出 `IndexError/KeyError/TypeError/ValueError` 时写入 `complete_objective=null, status=INFEASIBLE_OR_ERROR`，并把该行计入 `complete_candidate_evaluation_attempts`。v3 runner 的额外校验却把任何 null objective 一律视为无效 trace。两者的 schema 语义不一致。

但是，`INFEASIBLE_OR_ERROR` 同时覆盖“合法不可行候选”和“翻译/数据技术错误”，而本轮 runner 在持久化 trace 与 failure strings 之前停止。故现有现场无法可靠判断属于哪一类。依照任务规则“拿不准则停止并写明两种处理后果”，本轮没有修改冻结 runner、没有重试、没有启动正式实验。

## 两种解释及后果

若 null 行只是合法不可行候选评价，则这是 runner 判据误报。未来经用户批准的新版本应把该行继续计入实际消费次数，只在绘制 incumbent 改善曲线时跳过空目标值，同时持久化 status 与失败原因，再从新版本重跑探针。

若 null 行来自候选翻译、数据或完整化错误，则属于真正技术故障。必须先独立诊断上游原因并获得授权，不能把它当作正常早停继续，否则会污染正式证据。

当前证据不能在这两种解释之间作选择。

## 收敛探针与正式预算

| 探针臂 | 上限 | 实际消费 | 改善曲线 | 科学终止原因 |
|---|---:|---:|---|---|
| L100_control | 1500 | NA（异常前未持久化） | NOT_WRITTEN | HALT，不是科学终止 |
| NL90_mild | 1500 | NOT_RUN | NOT_RUN | NOT_RUN |

因此不能按“平台点向上取整到整百并留余量”的规则选出正式共同上限。`budget_cap=1500` 在本报告和 `done.json` 中仅指本次探针上限，不代表已经锁定的正式实验上限。

## 正式实验与四个端点

| 算例 | Best | Avg | Gap% | 车辆数 | 时间 | 实际评价数 | 状态 |
|---|---:|---:|---:|---:|---:|---:|---|
| cn-prd-50c-01-V2-LOCATIONS | NA | NA | NA | NA | NA | NA | NOT_RUN_UPSTREAM_PROBE_HALT |
| cn-prd-100c-02-V2-LOCATIONS | NA | NA | NA | NA | NA | NA | NOT_RUN_UPSTREAM_PROBE_HALT |

NL90 完整可行率、L100 可行但 NL90 物理下不可行的数量与成因、双臂均可行单元的完整模型成本变化、逐会话起止 SOC 与充电时长差均未生成。任何正、负或零效应结论在本轮都不受支持。

## 完整性与边界

`cost.py`、`check.py`、`search/evaluation.py`、`route_pool_sp.py` 与 `epochal_hgs.py` 的当前哈希均与 `source_lock.json` 一致。旧目录 `e5_nonlinear_20260729/` 和 `e5_nonlinear_v2_20260730/` 均保留。哈希清单排除了 AppleDouble、`__pycache__`、`.pytest_cache`、监控运行态和最后写入的 `done.json`；本目录内发现的 AppleDouble sidecar 已在清单生成前删除。
"""
    atomic_text(OUT / "report.md", report)

    artifact_paths = [
        OUT / "metadata.json",
        OUT / "raw_runs.csv",
        OUT / "decision.json",
        OUT / "report.md",
        OUT / "monitor_probe.json",
        OUT / "source_lock.json",
        OUT / "task_card.json",
        OUT / "probe_run.log",
        Path(__file__).resolve(),
        ROOT / "baselines/china_e3_e7/run_e5_nonlinear_v3_20260730.py",
        ROOT / "baselines/china_e3_e7/check_e5_nonlinear_v3_20260730.py",
    ]
    artifacts = {
        path.relative_to(ROOT).as_posix(): sha256(path)
        for path in artifact_paths
    }
    manifest = {
        "schema_version": "E5-ARTIFACT-HASHES-v3-halt",
        "task_id": "E5-NONLINEAR-CHARGING-V3-20260730",
        "status": STATUS,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "algorithm": "sha256",
        "artifacts": artifacts,
        "protected_source_sha256": protected_actual,
        "search_semantics_sha256": {
            path: all_actual[path]
            for path in (
                "baselines/algorithm_prototypes/"
                "china81_mechanism_hybrid_20260720/epochal_hgs.py",
                "baselines/algorithm_prototypes/"
                "china81_mechanism_hybrid_20260720/route_pool_sp.py",
            )
        },
        "exclusions": [
            "._*",
            "**/__pycache__/**",
            "**/.pytest_cache/**",
            "monitor_runtime/**",
            "artifact_hashes.json (self-reference)",
            "done.json (written last)",
        ],
    }
    atomic_json(OUT / "artifact_hashes.json", manifest)

    for name in REQUIRED_OUTPUTS:
        if not (OUT / name).is_file():
            raise RuntimeError(f"required output was not written: {name}")

    done = {
        "schema_version": "E5-DONE-v3-halt",
        "task_id": "E5-NONLINEAR-CHARGING-V3-20260730",
        "status": STATUS,
        "budget_cap": PROBE_CAP,
        "budget_cap_role": "PROBE_CAP_ONLY_NOT_FORMAL_LOCK",
        "budget_source": "convergence_probe",
        "median_evaluations_consumed": None,
        "median_evaluations_consumed_status": (
            "NA_NO_PERSISTED_COMPLETE_UNIT"
        ),
        "instances_completed": [],
        "seeds": 10,
        "endpoints_answered": 0,
        "formal_budget_selected": False,
        "scientific_results_generated": False,
        "done_written_last": True,
        "finished_at_utc": datetime.now(UTC).isoformat(),
    }
    atomic_json(OUT / "done.json", done)
    print(
        "CLOSEOUT_COMPLETE "
        f"status={STATUS} required_outputs={len(REQUIRED_OUTPUTS)} "
        "done_written_last=true",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
