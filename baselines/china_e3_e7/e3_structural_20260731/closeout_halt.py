#!/usr/bin/env python3
"""Fail-closed closeout for the structural E3 hard-lock candidate error."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
RUNNER_PATH = HERE / "run_e3_structural.py"
HALT = "HALT_TECHNICAL_ERROR_CROSS_SITE_CANDIDATE_UNDER_HARD_LOCK"
TECHNICAL_MESSAGE = (
    "hard home-depot control candidate contains cross-site service"
)
EXCLUDED_DIRS = {"__pycache__", ".pytest_cache", "monitor_runtime"}
THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def payload_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
    temporary.replace(path)


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("refusing to write empty CSV")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def load_runner() -> Any:
    spec = importlib.util.spec_from_file_location(
        "_e3_structural_halt_closeout_runner",
        RUNNER_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen structural E3 runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def require_no_live_formal_process() -> None:
    completed = subprocess.run(
        ["ps", "-axo", "pid=,pgid=,command="],
        check=True,
        capture_output=True,
        text=True,
    )
    offenders = [
        line.strip()
        for line in completed.stdout.splitlines()
        if (
            "run_e3_structural.py formal" in line
            or "run_e3_structural.py aggregate" in line
        )
        and str(os.getpid()) not in line.split(maxsplit=1)[0]
    ]
    if offenders:
        raise RuntimeError(f"HALT_FORMAL_PROCESS_STILL_LIVE:{offenders}")


def status_paths() -> list[Path]:
    return sorted(
        path
        for path in (HERE / "formal/task_status").glob("*.json")
        if path.is_file() and not path.name.startswith("._")
    )


def verify_and_build_rows(
    runner: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    statuses = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in status_paths()
    ]
    passed = [row for row in statuses if row["status"] == "PASS"]
    halted = [
        row
        for row in statuses
        if row["status"] == "TRACE_PERSISTED_PENDING_VALIDATION"
    ]
    if len(statuses) != 26 or len(passed) != 18 or len(halted) != 8:
        raise RuntimeError(
            "HALT_CLOSEOUT_DENOMINATOR:"
            f"{len(statuses)}:{len(passed)}:{len(halted)}"
        )
    keys = {
        (row["instance_id"], int(row["seed"]), row["arm"])
        for row in statuses
    }
    if len(keys) != 26:
        raise RuntimeError("HALT_CLOSEOUT_DUPLICATE_KEYS")

    e3 = runner.load_e3()
    verified_pass: list[dict[str, Any]] = []
    verified_halt: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    for status in sorted(
        statuses,
        key=lambda row: (
            row["instance_id"],
            int(row["seed"]),
            row["arm"],
        ),
    ):
        trace_path = REPO / status["search_trace_path"]
        if sha256(trace_path) != status["search_trace_sha256"]:
            raise RuntimeError("HALT_CLOSEOUT_TRACE_HASH")
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        errors = [
            row
            for row in trace["complete_candidate_evaluation_trace"]
            if row["failure_category"] == "TECHNICAL_ERROR"
        ]
        common = {
            "instance_id": status["instance_id"],
            "sample_role": status["sample_role"],
            "seed": int(status["seed"]),
            "arm": status["arm"],
            "hard_home_depot_lock": status["hard_home_depot_lock"],
            "complete_candidate_budget_cap":
                status["complete_candidate_budget_cap"],
            "complete_candidate_evaluations_consumed":
                status["complete_candidate_evaluations_consumed"],
            "termination_reason": status["termination_reason"],
            "elapsed_wall_seconds": status["elapsed_wall_seconds"],
            "feasible_candidates": status["feasible_candidates"],
            "infeasible_candidates": status["infeasible_candidates"],
            "error_candidates": status["error_candidates"],
            "total_cost_cny": "",
            "vehicle_count": "",
            "route_count": "",
            "cross_site_service_count": "",
            "violation_count": "",
            "solution_sha256": "",
            "status": HALT,
        }
        if status["status"] == "PASS":
            if errors or int(status["error_candidates"]) != 0:
                raise RuntimeError("HALT_CLOSEOUT_PASS_HAS_TECHNICAL_ERROR")
            plan_path = REPO / status["plan_path"]
            if sha256(plan_path) != status["plan_sha256"]:
                raise RuntimeError("HALT_CLOSEOUT_PLAN_FILE_HASH")
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan_payload = {
                key: value
                for key, value in plan.items()
                if key != "plan_sha256"
            }
            if plan["plan_sha256"] != payload_sha256(plan_payload):
                raise RuntimeError("HALT_CLOSEOUT_PLAN_PAYLOAD_HASH")
            input_map = json.loads(
                (
                    HERE
                    / "inputs"
                    / status["instance_id"]
                    / status["arm"]
                    / "responsibility_map.json"
                ).read_text(encoding="utf-8")
            )
            base = e3.load_bundle(status["instance_id"])
            bundle = e3.with_responsibility(
                base,
                input_map["mapping"],
            )
            solution = e3.solution_from_payload(plan["solution"])
            audit = runner.e3e6_state_audit(e3, solution, bundle)
            if audit["solution_sha256"] != status["solution_sha256"]:
                raise RuntimeError("HALT_CLOSEOUT_SOLUTION_HASH")
            if not math.isclose(
                audit["objective"],
                float(status["total_cost_cny"]),
                rel_tol=1.0e-12,
                abs_tol=1.0e-9,
            ):
                raise RuntimeError("HALT_CLOSEOUT_OBJECTIVE")
            common.update(
                {
                    "total_cost_cny": status["total_cost_cny"],
                    "vehicle_count": status["vehicle_count"],
                    "route_count": status["route_count"],
                    "cross_site_service_count":
                        status["cross_site_service_count"],
                    "violation_count": 0,
                    "solution_sha256": status["solution_sha256"],
                    "status": "PASS",
                }
            )
            verified_pass.append(
                {
                    "instance_id": status["instance_id"],
                    "seed": int(status["seed"]),
                    "arm": status["arm"],
                    "objective": audit["objective"],
                    "solution_sha256": audit["solution_sha256"],
                    "violation_count": 0,
                }
            )
        else:
            if not status["hard_home_depot_lock"]:
                raise RuntimeError("HALT_CLOSEOUT_ERROR_ON_UNLOCKED_ARM")
            if len(errors) != int(status["error_candidates"]):
                raise RuntimeError("HALT_CLOSEOUT_ERROR_COUNTER")
            if not errors or any(
                row.get("exception_type") != "ValueError"
                or row.get("exception_message") != TECHNICAL_MESSAGE
                for row in errors
            ):
                raise RuntimeError("HALT_CLOSEOUT_UNEXPECTED_TECHNICAL_ERROR")
            verified_halt.append(
                {
                    "instance_id": status["instance_id"],
                    "seed": int(status["seed"]),
                    "arm": status["arm"],
                    "technical_error_candidates": len(errors),
                    "exception_type": "ValueError",
                    "exception_message": TECHNICAL_MESSAGE,
                    "trace_sha256": sha256(trace_path),
                }
            )
        raw_rows.append(common)

    if sum(row["technical_error_candidates"] for row in verified_halt) != 14:
        raise RuntimeError("HALT_CLOSEOUT_TECHNICAL_ERROR_TOTAL")
    return raw_rows, {
        "passed": verified_pass,
        "halted": verified_halt,
    }


def render_report() -> str:
    return f"""# E3 结构性对照：技术 HALT 封存

状态：`{HALT}`。

## 结论

旧 PGID 7965 在接手时已经不存在，随后再次确认无对应进程组；旧输入目录的 106 个权威终态、13 个严格 `INFEASIBLE_INPUT` 和 56/56 First-Fit 等价证据均未删除或覆盖。旧设计剩余 8 个活动单元和 21 个排队单元共 29 个，已在本目录登记为 `NOT_BUILT_SUPERSEDED_DESIGN`，明确不是不可行、也不是失败。

China81 实例没有字面名为 `registered_depot` 的列，但有现成的客户 `city` 行政归属；装载器把客户城市确定性映射到同城唯一车场，形成 `customer_home_depot`。因此没有为 IND 新造参数。两个预定算例中，这个行政映射与有向道路最近车场完全重合：50c 为 0/50，100c 为 0/100。IND 和 ZONE 的责任映射与加锁问题因此相同；这个输入身份事实不依赖正式搜索结果。

IND、ZONE、JOINT 各 2 份输入均成功构造，C++ 冻结 First-Fit 与 Python `_pack_depot` 逐组一致，完整初解复算违规 0，构造无组合爆炸。1500-cap 的 JOINT 主算例 seed-1 收敛探针实际消费 331 个完整候选后自然耗尽，技术错误 0；按预注册规则向上取整留余量，将正式共同预算上限冻结为 400。

## 正式批停止原因

正式矩阵原定 2 算例 × 3 臂 × 10 种子，共 60 单元，最多 2 workers。批次运行到 26 个单元形成完整 trace 时，18 个达到 PASS，8 个处于“trace 已持久化、最终验证前 HALT”。这 8 个全部是 50c 的硬锁 IND/ZONE 单元（种子 3、5、6、7），累计出现 14 个技术错误候选；异常原文为：

```text
hard home-depot control candidate contains cross-site service
```

这些候选不是 `null objective` 的合法容量/时间窗不可行，也不在白名单内。它们表示硬车场责任控制下仍进入了跨场候选，是搜索/控制链的真技术错误。按合同“合法不可行继续，真技术错误 HALT”，监控进程组已先暂停、保存现场，再停止；其余 34 个单元未启动或未形成权威 trace。未删除异常候选，未将其改写成 `INFEASIBLE_INPUT`，未修算法后重跑。

## 结果边界

由于 60 单元全分母未完成，三臂期刊式 Best/Avg/Gap%、车辆数、时间和实际评价数主表没有生成；IND→ZONE、ZONE→JOINT、IND→JOINT 三个正式效应均为 `NOT_AGGREGATED_DUE_TO_TECHNICAL_HALT`。18 个 PASS 解只作为故障前现场保存，不用于论文效应、显著性或方向判断。旧 L-main 的 16.55%/24.72% 没有进入本次判决，也没有迁移为论文证据。

`raw_runs.csv` 保存 26 个实际运行单元的状态：18 个 PASS 行带完整目标/解证书，8 个 HALT 行保留空目标并链接相应 trace。独立 HALT checker 在单独进程中重新验证 18/18 PASS 解的完整目标、客户覆盖、违规和解哈希，并复核 8/8 HALT trace 中的 14 个技术错误字符串及计数。四个受保护源文件哈希未漂移。

## IND 调查的备选边界

本任务没有采用合成 IND。若未来放弃现有行政城市归属，客观备选包括按距离次近车场（依据明确但人为制造错配强度）、按更细行政区划映射（需新增可靠边界与车场对应来源）、按容量均分（可平衡资源但不是历史/行政登记）。这属于新的科学定义，需要用户另行裁决，不能作为本次技术 HALT 的自动修复。

## 文件与完成信号

四件套 `metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json` 与本报告同目录。外置卷产生的 AppleDouble 旁车在封存前按精确 `._*` 范围清理，记录为 `HASH_CONTAMINATED_APPLEDOUBLE_CLEANED_BEFORE_SEAL`；真实证据文件不变。哈希枚举排除 `._*`、`__pycache__`、`.pytest_cache`、临时文件和目录外监控运行态。`done.json` 最后写入，状态为 `{HALT}`，不是 `COMPLETE`。
"""


def closeout() -> None:
    if (HERE / "done.json").exists():
        raise RuntimeError("done.json already exists")
    require_no_live_formal_process()
    runner = load_runner()
    runner.verify_source_lock()
    protected = runner.verify_protected()
    raw_rows, verified = verify_and_build_rows(runner)
    atomic_csv(HERE / "raw_runs.csv", raw_rows)
    halt_rows = verified["halted"]
    atomic_csv(HERE / "technical_error_units.csv", halt_rows)
    verification = {
        "schema": "resetp.e3-structural.halt-verification.v1",
        "status": "PASS_INDEPENDENT_HALT_VERIFICATION",
        "created_at_utc": now_iso(),
        "formal_units_with_trace_checked": len(raw_rows),
        "pass_solutions_recomputed": len(verified["passed"]),
        "halt_traces_recomputed": len(halt_rows),
        "technical_error_candidates": sum(
            row["technical_error_candidates"] for row in halt_rows
        ),
        "technical_error_message": TECHNICAL_MESSAGE,
        "objective_mismatches": 0,
        "solution_hash_mismatches": 0,
        "violations": 0,
        "protected_hashes": protected,
        "source_lock_id": runner.verify_source_lock()["source_lock_id"],
        "checked_pass_sha256": payload_sha256(verified["passed"]),
        "checked_halt_sha256": payload_sha256(verified["halted"]),
    }
    verification["verification_id"] = payload_sha256(verification)
    atomic_json(HERE / "independent_halt_verification.json", verification)
    decision = {
        "schema": "resetp.e3-structural.decision.v1",
        "task_id": runner.TASK_ID,
        "verdict": HALT,
        "created_at_utc": now_iso(),
        "reason": TECHNICAL_MESSAGE,
        "formal_units_expected": 60,
        "formal_units_run": 26,
        "formal_units_passed": 18,
        "formal_units_halted": 8,
        "formal_units_not_run": 34,
        "technical_error_candidates": 14,
        "affected_arms": ["IND", "ZONE"],
        "affected_seeds": [3, 5, 6, 7],
        "affected_instance": "cn-prd-50c-01-V2-LOCATIONS",
        "formal_effects_status":
            "NOT_AGGREGATED_DUE_TO_TECHNICAL_HALT",
        "registered_depot_field_found": True,
        "literal_registered_depot_column_found": False,
        "ind_zone_mapping_identical_on_both_instances": True,
        "historical_l_main_numbers_used_as_evidence": False,
        "no_error_reclassification": True,
        "no_search_rerun_after_halt": True,
        "source_lock_id": runner.verify_source_lock()["source_lock_id"],
    }
    decision["decision_id"] = payload_sha256(decision)
    atomic_json(HERE / "decision.json", decision)
    metadata = {
        "schema": "resetp.e3-structural.metadata.v1",
        "task_id": runner.TASK_ID,
        "created_at_utc": now_iso(),
        "status": HALT,
        "contract": runner.relative(runner.CONTRACT),
        "instances": [instance for instance, _role in runner.INSTANCES],
        "arms": list(runner.ARMS),
        "seeds": list(runner.SEEDS),
        "formal_units_expected": 60,
        "formal_units_run": 26,
        "formal_units_passed": 18,
        "formal_units_halted": 8,
        "formal_units_not_run": 34,
        "budget_cap": 400,
        "budget_semantics": "UPPER_CAP_NOT_QUOTA",
        "workers": 2,
        "probe": {
            "long_cap": 1500,
            "actual_consumption": 331,
            "termination_reason": "CANDIDATES_EXHAUSTED",
            "selected_formal_cap": 400,
            "technical_error_candidates": 0,
        },
        "protected_hashes": protected,
        "source_lock_id": runner.verify_source_lock()["source_lock_id"],
        "first_fit_equivalence_units": 56,
        "first_fit_equivalence_mismatches": 0,
        "registered_depot_field_found": True,
        "literal_registered_depot_column_found": False,
        "ind_inputs_built": 2,
        "zone_inputs_built": 2,
        "joint_inputs_built": 2,
        "registered_nearest_mismatch": {
            "cn-prd-50c-01-V2-LOCATIONS": "0/50",
            "cn-prd-100c-02-V2-LOCATIONS": "0/100",
        },
        "superseded_units_registered": 29,
        "pgid_7965_stopped": True,
        "formal_process_group_stopped": True,
        "formal_process_group_pgid": 24515,
        "hash_contamination_status":
            "HASH_CONTAMINATED_APPLEDOUBLE_CLEANED_BEFORE_SEAL",
        "appledouble_cleanup_scope":
            "only ._* files under the new E3 structural delivery directory",
        "real_artifact_files_changed_by_cleanup": False,
        "file_enumeration_exclusions": [
            "._*",
            "__pycache__",
            ".pytest_cache",
            "monitor_runtime",
            "*.tmp",
        ],
    }
    atomic_json(HERE / "metadata.json", metadata)
    formal_halt = {
        "schema": "resetp.e3-structural.formal-halt.v1",
        "status": HALT,
        "created_at_utc": now_iso(),
        "formal_pgid": 24515,
        "monitor_action_sequence": [
            "PAUSE_AND_PRESERVE_SCENE",
            "STOP_AFTER_TECHNICAL_ERROR_CONFIRMED",
        ],
        "process_group_confirmed_absent": True,
        "formal_units_with_trace": 26,
        "formal_units_passed": 18,
        "formal_units_halted": 8,
        "formal_units_not_run": 34,
        "technical_error_candidates": 14,
        "technical_error_message": TECHNICAL_MESSAGE,
        "technical_error_units_path":
            "baselines/china_e3_e7/e3_structural_20260731/"
            "technical_error_units.csv",
        "old_input_files_deleted_or_overwritten": False,
    }
    formal_halt["halt_id"] = payload_sha256(formal_halt)
    atomic_json(HERE / "formal_halt_evidence.json", formal_halt)
    (HERE / "report.md").write_text(render_report(), encoding="utf-8")
    print(
        f"{HALT} pass=18 halt=8 not_run=34 technical_candidates=14",
        flush=True,
    )


def is_real_artifact(path: Path) -> bool:
    return (
        path.is_file()
        and not path.name.startswith("._")
        and not any(part in EXCLUDED_DIRS for part in path.parts)
        and not path.name.endswith(".tmp")
    )


def seal() -> None:
    if (HERE / "done.json").exists():
        raise RuntimeError("done.json already exists")
    require_no_live_formal_process()
    runner = load_runner()
    runner.verify_source_lock()
    runner.verify_protected()
    required = (
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "report.md",
        "independent_halt_verification.json",
        "formal_halt_evidence.json",
        "superseded_units.csv",
        "depot_field_investigation.json",
        "budget_lock.json",
    )
    missing = [name for name in required if not (HERE / name).is_file()]
    if missing:
        raise RuntimeError(f"HALT_SEAL_MISSING:{missing}")
    verification = json.loads(
        (HERE / "independent_halt_verification.json").read_text(
            encoding="utf-8"
        )
    )
    if verification["status"] != "PASS_INDEPENDENT_HALT_VERIFICATION":
        raise RuntimeError("HALT_SEAL_VERIFICATION")
    excluded = {"artifact_hashes.json", "done.json"}
    files = sorted(
        path
        for path in HERE.rglob("*")
        if is_real_artifact(path) and path.name not in excluded
    )
    artifact_hashes = {
        "schema": "resetp.e3-structural.artifact-hashes.v1",
        "created_at_utc": now_iso(),
        "exclusions": [
            "artifact_hashes.json",
            "done.json",
            "._*",
            "__pycache__",
            ".pytest_cache",
            "monitor_runtime",
            "*.tmp",
        ],
        "files": {
            path.relative_to(REPO).as_posix(): sha256(path)
            for path in files
        },
    }
    artifact_hashes["manifest_id"] = payload_sha256(artifact_hashes)
    atomic_json(HERE / "artifact_hashes.json", artifact_hashes)
    decision = json.loads(
        (HERE / "decision.json").read_text(encoding="utf-8")
    )
    done = {
        "status": HALT,
        "pgid_7965_stopped": True,
        "superseded_units_registered": 29,
        "registered_depot_field_found": True,
        "zone_inputs_built": 2,
        "joint_inputs_built": 2,
        "ind_inputs_built": 2,
        "formal_units_run": 26,
        "budget_cap": 400,
        "formal_units_passed": 18,
        "formal_units_halted": 8,
        "formal_units_not_run": 34,
        "technical_error_candidates": 14,
        "formal_effects_status":
            "NOT_AGGREGATED_DUE_TO_TECHNICAL_HALT",
        "formal_process_group_stopped": True,
        "decision_id": decision["decision_id"],
        "manifest_id": artifact_hashes["manifest_id"],
        "done_written_last": True,
        "created_at_utc": now_iso(),
    }
    done["done_id"] = payload_sha256(done)
    atomic_json(HERE / "done.json", done)
    print(json.dumps(done, ensure_ascii=False, sort_keys=True), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("closeout", "seal"))
    args = parser.parse_args()
    for name, value in THREAD_ENV.items():
        if os.environ.get(name) != value:
            raise RuntimeError(f"HALT_THREAD_ENV_NOT_FROZEN:{name}")
    if args.command == "closeout":
        closeout()
    else:
        seal()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
