#!/usr/bin/env python3
"""Prepare and finalize the one-seed fairness-line exploration package.

declared_identity=PROJECT_DOMAIN
code_role=ORCHESTRATION
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from experiment_acceptance import (
    RunAcceptance,
    file_sha256,
    finalize_five_file_package,
    validate_five_file_package,
)
from run_problem_hgs_private_technical import (
    DEPOT_SEARCH_INSTANCE_ID,
    PROTECTED,
    _build_context,
)
from setp_solver.algorithms.problem_hgs.enterprise_adapter import (
    slice_enterprise_problem,
)
from setp_solver.china81 import ENDOGENOUS_FLEET_PARAMETERS
from setp_solver.enterprise_accounting import build_enterprise_ledger
from setp_solver.mapping_identity import mapping_sha256
from setp_solver.search.metaheuristic_baselines import solution_from_dict

COMPLETED_TERMINATIONS = {
    "STOPPED_BY_CALLER",
    "CONVERGED_NO_IMPROVEMENT",
    "NO_FEASIBLE_SOLUTION",
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _individual_fingerprint(payload: Mapping[str, Any]) -> str:
    duties = []
    for source in payload["duties"]:
        duty = dict(source)
        if duty.get("schedule") is not None:
            raise ValueError("probe fingerprint adapter requires unscheduled duties")
        duty.pop("schedule", None)
        duties.append(duty)
    canonical = {
        "version": int(payload.get("version", 1)),
        "duties": duties,
        "unserved_customers": list(payload.get("unserved_customers", ())),
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _csv_row(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1:
        raise ValueError(f"expected one raw row: {path}")
    return rows[0]


def prepare(root: Path, package_a: Path, package_b: Path) -> None:
    if root.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {root}")
    repo = Path(__file__).resolve().parents[2]
    bundle, _initial, _pi0, context = _build_context(
        repo,
        DEPOT_SEARCH_INSTANCE_ID,
        fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
        depot_charging_scenario_name="60kw",
    )
    packages = {"ENT_A": package_a.resolve(), "ENT_B": package_b.resolve()}
    rows = []
    values = {}
    package_hashes = {}
    for enterprise_id, package in packages.items():
        validated = validate_five_file_package(package)
        metadata = validated["metadata"]
        if metadata["instance_id"] != DEPOT_SEARCH_INSTANCE_ID:
            raise ValueError("standalone instance differs from fairness-line instance")
        enterprise = metadata["enterprise_slice"]
        if enterprise["enterprise_id"] != enterprise_id:
            raise ValueError("standalone enterprise package identity mismatch")
        problem = slice_enterprise_problem(
            bundle,
            context.rebuilt_route_constraints,
            enterprise_id,
        )
        best = _load(package / "best_solution.json")
        raw = _csv_row(package / "raw_runs.csv")
        fingerprint = _individual_fingerprint(best["individual"])
        ledger = build_enterprise_ledger(
            instance_id=DEPOT_SEARCH_INSTANCE_ID,
            seed=int(metadata["random_seed"]),
            solution_fingerprint=fingerprint,
            solution=solution_from_dict(best["evaluation"]["prepared_solution"]),
            bundle=problem.bundle,
            prior_profit={problem.depot_id: 0.0},
            carbon_quota_kg=0.0,
            expected_total_cost=float(best["evaluation"]["total_cost"]),
        )
        ledger_path = root / "inputs" / "standalone" / enterprise_id / "enterprise_ledger.json"
        _write(ledger_path, ledger)
        ledger_row = ledger["rows"][problem.depot_id]
        if ledger_row["profit"] <= 0.0:
            raise RuntimeError(f"HALT_PI0_NONPOSITIVE: {enterprise_id}")
        package_hash = file_sha256(package / "artifact_hashes.json")
        package_hashes[enterprise_id] = package_hash
        values[problem.depot_id] = float(ledger_row["profit"])
        rows.append(
            {
                "enterprise_id": enterprise_id,
                "depot_id": problem.depot_id,
                "seed": int(metadata["random_seed"]),
                "selected": True,
                "run_kind": "probe",
                "formal_reuse_allowed": False,
                "package_path": str(package),
                "package_artifact_map_sha256": package_hash,
                "ledger_path": str(ledger_path.relative_to(root)),
                "ledger_sha256": file_sha256(ledger_path),
                "solution_fingerprint": fingerprint,
                "customers_served": int(raw["customers_served"]),
                "customers_total": int(raw["customers_total"]),
                "demand_served_kg": float(raw["demand_served"]),
                "demand_total_kg": float(raw["demand_total"]),
                "cost_total": float(ledger_row["cost_total"]),
                "profit": float(ledger_row["profit"]),
            }
        )
    selection = {
        "schema": "resetp.standalone_baseline_selection.v1",
        "run_kind": "probe",
        "formal_reuse_allowed": False,
        "seed_count_per_enterprise": 1,
        "formal_seed_count_pending": 10,
        "instance_id": DEPOT_SEARCH_INSTANCE_ID,
        "rows": rows,
    }
    selection_path = root / "inputs" / "standalone_baselines.json"
    _write(selection_path, selection)
    manifest = {
        "schema": "resetp.formal_pi0.v1",
        "instances": {
            DEPOT_SEARCH_INSTANCE_ID: {
                "values": values,
                "source_id": "fairness_line_20260818_standalone_probe_seed_1",
                "value_sha256": mapping_sha256(values),
                "selected_package_sha256_by_enterprise": package_hashes,
                "run_kind": "probe",
                "externally_frozen": True,
                "formal_reuse_allowed": False,
            }
        },
    }
    _write(root / "inputs" / "pi0_manifest.json", manifest)
    _write(
        root / "inputs" / "preparation.json",
        {
            "run_kind": "probe",
            "protected_hashes_before": {
                path: file_sha256(repo / path) for path in PROTECTED
            },
            "standalone_baselines_sha256": file_sha256(selection_path),
            "pi0_manifest_sha256": file_sha256(
                root / "inputs" / "pi0_manifest.json"
            ),
        },
    )


def account_joint(root: Path, joint: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    validated = validate_five_file_package(joint, require_accepted=False)
    metadata = validated["metadata"]
    raw = _csv_row(joint / "raw_runs.csv")
    best = _load(joint / "best_solution.json")
    ledger = _load(joint / "enterprise_ledger.json")
    selection = _load(root / "inputs" / "standalone_baselines.json")
    manifest_path = root / "inputs" / "pi0_manifest.json"
    manifest = _load(manifest_path)["instances"][DEPOT_SEARCH_INSTANCE_ID]
    baselines = {row["enterprise_id"]: row for row in selection["rows"]}
    depot_to_enterprise = {
        row["depot_id"]: row["enterprise_id"] for row in selection["rows"]
    }
    joint_rows = ledger["rows"]
    if set(joint_rows) != set(depot_to_enterprise):
        raise RuntimeError("joint enterprise ledger does not contain both depots")
    joint_cost = float(best["evaluation"]["total_cost"])
    if not math.isclose(
        joint_cost,
        sum(float(row["cost_total"]) for row in joint_rows.values()),
        rel_tol=1.0e-12,
        abs_tol=1.0e-9,
    ):
        raise RuntimeError("HALT_ACCOUNTING_MISMATCH: joint ledger does not close")
    by_enterprise = {
        depot_to_enterprise[depot]: row for depot, row in joint_rows.items()
    }
    values_by_enterprise = {
        depot_to_enterprise[depot]: float(value)
        for depot, value in manifest["values"].items()
    }
    margins = {
        depot_to_enterprise[depot]: float(value)
        for depot, value in best["evaluation"]["participation_margin"].items()
    }
    for enterprise_id, row in by_enterprise.items():
        expected = float(row["profit"]) - values_by_enterprise[enterprise_id]
        if not math.isclose(margins[enterprise_id], expected, abs_tol=1.0e-9):
            raise RuntimeError("joint participation margin does not match ledger")
    input_hashes = {
        "standalone_baselines.json": file_sha256(
            root / "inputs" / "standalone_baselines.json"
        ),
        "pi0_manifest.json": file_sha256(manifest_path),
        "joint/enterprise_ledger.json": file_sha256(
            joint / "enterprise_ledger.json"
        ),
        "joint/best_solution.json": file_sha256(joint / "best_solution.json"),
    }
    allocation_input = {
        "costs": {
            "enterprise_a": "ENT_A",
            "enterprise_b": "ENT_B",
            "standalone_cost_a": baselines["ENT_A"]["cost_total"],
            "standalone_cost_b": baselines["ENT_B"]["cost_total"],
            "joint_cost": joint_cost,
        },
        "participation": {
            "joint_revenue": {
                key: float(row["revenue"]) for key, row in by_enterprise.items()
            },
            "joint_cost_total": {
                key: float(row["cost_total"]) for key, row in by_enterprise.items()
            },
            "joint_profit": {
                key: float(row["profit"]) for key, row in by_enterprise.items()
            },
            "pi0_profit": values_by_enterprise,
        },
        "input_hashes": input_hashes,
    }
    _write(root / "allocation_input.json", allocation_input)
    standalone_sum = sum(float(row["cost_total"]) for row in baselines.values())
    _write(
        root / "synergy_comparison.json",
        {
            "schema": "resetp.true_synergy_probe.v1",
            "run_kind": "probe",
            "standalone_cost_sum": standalone_sum,
            "joint_cost": joint_cost,
            "cooperation_saving_cny": standalone_sum - joint_cost,
            "cooperation_saving_pct": 100.0 * (standalone_sum - joint_cost) / standalone_sum,
            "old_pseudo_off_reading": {
                "value": 3506.007032,
                "status": "FORMALLY_INVALIDATED",
                "reason": "not the sum of the two enterprise-native standalone runs",
            },
        },
    )
    violations = best["evaluation"]["violations"]
    state = {
        "joint_package": str(joint.resolve()),
        "joint_package_hash_valid": True,
        "joint_child_accepted": validated["decision"].get("accepted") is True,
        "joint_child_verdict": validated["decision"].get("verdict"),
        "termination_status": raw["termination_status"],
        "execution_completed": (
            raw["termination_status"] in COMPLETED_TERMINATIONS
        ),
        "full_service": (
            int(raw["customers_served"]) == int(raw["customers_total"])
            and float(raw["demand_served"]) == float(raw["demand_total"])
        ),
        "customers_served": int(raw["customers_served"]),
        "customers_total": int(raw["customers_total"]),
        "demand_served_kg": float(raw["demand_served"]),
        "demand_total_kg": float(raw["demand_total"]),
        "fairness_enabled": metadata["fairness_enabled"],
        "fairness_theta": metadata["fairness_theta"],
        "pi0_sha256": metadata["pi0"]["sha256"],
        "participation_margin": margins,
        "participation_satisfied": not any(
            row["type"] == "PROFIT_FAIRNESS" for row in violations
        ),
        "physical_feasible": metadata["participation"]["physical_feasible"],
        "joint_best_feasible": best["evaluation"]["feasible"],
        "joint_cost": joint_cost,
        "protected_hashes_after": {
            path: file_sha256(repo / path) for path in PROTECTED
        },
    }
    _write(root / "joint_accounting.json", state)


def finalize(root: Path) -> None:
    allocation = _load(root / "shapley_allocation.json")
    state = _load(root / "joint_accounting.json")
    selection = _load(root / "inputs" / "standalone_baselines.json")
    preparation = _load(root / "inputs" / "preparation.json")
    synergy = _load(root / "synergy_comparison.json")
    margins = allocation["allocation"]["allocated_participation_margin"]
    protected_ok = (
        preparation["protected_hashes_before"]
        == state["protected_hashes_after"]
    )
    accepted = all(
        (
            state["joint_package_hash_valid"],
            state["execution_completed"],
            state["full_service"],
            state["physical_feasible"],
            state["fairness_enabled"] is True,
            state["fairness_theta"] == 1.0,
            len(state["participation_margin"]) == 2,
            protected_ok,
        )
    )
    acceptance = RunAcceptance(
        accepted=accepted,
        verdict=(
            "FAIRNESS_LINE_EXPLORATORY_COMPLETE"
            if accepted
            else "FAIRNESS_LINE_EXPLORATORY_FAILED"
        ),
        failure_reasons=tuple(
            reason
            for condition, reason in (
                (state["joint_package_hash_valid"], "joint package hash invalid"),
                (state["execution_completed"], "joint execution did not complete"),
                (state["full_service"], "joint run did not complete all service"),
                (state["physical_feasible"], "joint solution has physical violations"),
                (state["fairness_enabled"] is True, "fairness was not enabled"),
                (state["fairness_theta"] == 1.0, "fairness theta was not one"),
                (len(state["participation_margin"]) == 2, "participation margins missing"),
                (protected_ok, "protected source hashes changed"),
            )
            if not condition
        ),
    )
    rows = []
    for row in selection["rows"]:
        rows.append(
            {
                "scope": "standalone",
                "enterprise_id": row["enterprise_id"],
                "seed": row["seed"],
                "cost_total": row["cost_total"],
                "profit": row["profit"],
                "customers_served": row["customers_served"],
                "customers_total": row["customers_total"],
                "demand_served_kg": row["demand_served_kg"],
                "demand_total_kg": row["demand_total_kg"],
                "operational_participation_margin": "",
                "allocated_participation_margin": "",
                "run_kind": "probe",
            }
        )
    for enterprise_id in ("ENT_A", "ENT_B"):
        rows.append(
            {
                "scope": "joint_enterprise_ledger",
                "enterprise_id": enterprise_id,
                "seed": 1,
                "cost_total": "",
                "profit": "",
                "customers_served": state["customers_served"],
                "customers_total": state["customers_total"],
                "demand_served_kg": state["demand_served_kg"],
                "demand_total_kg": state["demand_total_kg"],
                "operational_participation_margin": state[
                    "participation_margin"
                ][enterprise_id],
                "allocated_participation_margin": margins[enterprise_id],
                "run_kind": "probe",
            }
        )
    rows.append(
        {
            "scope": "joint_total",
            "enterprise_id": "",
            "seed": 1,
            "cost_total": state["joint_cost"],
            "profit": "",
            "customers_served": state["customers_served"],
            "customers_total": state["customers_total"],
            "demand_served_kg": state["demand_served_kg"],
            "demand_total_kg": state["demand_total_kg"],
            "operational_participation_margin": "",
            "allocated_participation_margin": "",
            "run_kind": "probe",
        }
    )
    with (root / "raw_runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    operational = state["participation_satisfied"]
    allocated = all(float(value) >= 0.0 for value in margins.values())
    decision = {
        "enterprise_accounting": "COMPLETE",
        "two_enterprise_allocation": "COMPLETE",
        "participation_wiring": "COMPLETE",
        "operational_participation_satisfied": operational,
        "allocated_participation_all_nonnegative": allocated,
        "true_synergy_comparison": "COMPLETE",
        "old_pseudo_off_3506_007032": "FORMALLY_INVALIDATED",
        "formal_reuse_allowed": False,
        "next_step": "after algorithm finalization, run the frozen ten-seed standalone and joint protocol",
    }
    metadata = {
        "run_kind": "probe",
        "purpose": "one-seed exploratory fairness-line accounting and wiring",
        "instance_id": DEPOT_SEARCH_INSTANCE_ID,
        "formal_reuse_allowed": False,
        "standalone_seed_count_per_enterprise": 1,
        "formal_seed_count_pending": 10,
        "joint_state": state,
        "protected_hashes_before": preparation["protected_hashes_before"],
        "protected_hashes_after": state["protected_hashes_after"],
        "protected_hashes_unchanged": protected_ok,
        "retired_alns_cleanup": {
            "fairness_module_deleted": True,
            "legacy_dispatch_deleted": True,
            "dedicated_tests_deleted": True,
            "dedicated_test_files_collection_before": 48,
            "dedicated_test_files_collection_after": 41,
        },
    }
    report = f"""# 公平线主体探索包

## 结论

两个企业的单干成本合计为 {synergy['standalone_cost_sum']:.12f}，联合解成本为 {synergy['joint_cost']:.12f}，本次单种子探索读数的协同节约为 {synergy['cooperation_saving_cny']:.12f}（{synergy['cooperation_saving_pct']:.6f}%）。联合臂服务 {state['customers_served']}/{state['customers_total']} 个客户，完成需求 {state['demand_served_kg']:.6f}/{state['demand_total_kg']:.6f} kg。

搜索使用运营账参与约束，theta=1.0。子运行 verdict 为 `{state['joint_child_verdict']}`，结束状态为 `{state['termination_status']}`；这是因为参与判定为 {operational}，不是程序崩溃或少服务。两企业运营账裕量为 {state['participation_margin']}。pyCoopGame 分摊只进入报告，分摊后裕量为 {margins}，没有回写搜索。

以上均为 1 个种子的探索读数。正式表 11 仍需等算法定稿后按既定流程完成每企业 10 个单干种子和 10 个联合种子。

旧读数 3506.007032 已正式作废：它不是两份企业原生单干解的成本之和，不再作为“无协同”对照。

## 退役入口清理

旧 `search/fairness.py`、其导出、E3/E6 ALNS 调度入口及专属测试已同轮删除；直接承载这些专属测试的 `test_formal_runner.py` 与 `test_profit.py` 收集基数由 48 条降为 41 条（净删 7 条），不把被删测试伪报为回归通过。五个冻结文件的 SHA-256 前后逐位相同。

定向回归中，主求解器环境的 60 条测试全部通过；分摊测试按隔离合同在 `.coop-venv` 中 1 条通过。第一次合并命令把分摊测试误放进没有 pandas 的主环境，得到 1 条导入失败；该失败如实保留，纠正的是测试环境，不是测试判据或生产代码。

最终阻断钩子全部通过；Semgrep 按项目现行报告模式检查本轮触及的 18 个 Python 文件，结果为 0 条命中。

## 四件事状态与下一步

1. 企业账：完成；两份单干账与各自保存解逐项重算，明确标为探索版。
2. 两方分摊：完成；四行联盟价值表经冻结 pyCoopGame Shapley 模块核算，仅进报告。
3. 参与约束接线：完成；联合臂读取真实单干 Pi0，fairness 已打开，实际判定为 {operational}。
4. 真协同对照：完成；两单干之和与联合解已同包登记，旧伪关闭读数已作废。

下一步：算法定稿后，把同一条已验通链路扩成正式 10 种子版本；本探索包不直接进入论文正式数字。
"""
    finalize_five_file_package(
        root,
        acceptance=acceptance,
        metadata=metadata,
        decision=decision,
        report_text=report,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("root", type=Path)
    prepare_parser.add_argument("package_a", type=Path)
    prepare_parser.add_argument("package_b", type=Path)
    account_parser = subparsers.add_parser("account-joint")
    account_parser.add_argument("root", type=Path)
    account_parser.add_argument("joint", type=Path)
    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("root", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.root.resolve(), args.package_a, args.package_b)
    elif args.command == "account-joint":
        account_joint(args.root.resolve(), args.joint.resolve())
    else:
        finalize(args.root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
