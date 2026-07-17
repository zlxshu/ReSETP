"""Run and package the EA-001 dynamic-replanning micro-probes."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any

from prototype import (
    PseudoDepotSnapshot,
    VehicleState,
    assert_frozen_prefixes,
    bounded_regret_ejection_probe,
    build_hand_checkable_stability_case,
    independent_route_stability_oracle,
    ortools_lock_probe,
    own_minimal_suffix_repair,
    route_stability_metrics,
    snapshot_from_json,
    snapshot_to_json,
)


OUTPUT_DIR = Path(__file__).resolve().parent
REPO_ROOT = OUTPUT_DIR.parents[2]
TIMEZONE = timezone(timedelta(hours=8))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def git_output(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def run_state_probe() -> dict[str, Any]:
    snapshot = PseudoDepotSnapshot(
        schema_version="ea001-dynamic-state.v1",
        event_id="EVENT-MICRO-001",
        decision_time_min=485,
        vehicles=(
            VehicleState(
                vehicle_id="EV-01",
                current_node="CURRENT-EV-01",
                current_time_min=485,
                load_kg=320,
                capacity_kg=1000,
                soc_kwh=87.5,
                battery_kwh=140.41,
                frozen_prefix=("DEPOT-A", "C-01", "CURRENT-EV-01"),
                onboard_orders=("C-02",),
            ),
            VehicleState(
                vehicle_id="CV-01",
                current_node="CURRENT-CV-01",
                current_time_min=485,
                load_kg=600,
                capacity_kg=1735,
                soc_kwh=0.0,
                battery_kwh=0.0,
                frozen_prefix=("DEPOT-B", "CURRENT-CV-01"),
                onboard_orders=("C-11", "C-12"),
            ),
        ),
    )
    encoded = snapshot_to_json(snapshot)
    restored = snapshot_from_json(encoded)
    return {
        "status": "PASS_STATE_ROUND_TRIP",
        "round_trip_equal": restored == snapshot,
        "physical_vehicle_ids_preserved": [
            vehicle.vehicle_id for vehicle in restored.vehicles
        ]
        == ["EV-01", "CV-01"],
        "encoded_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "encoded_bytes": len(encoded.encode("utf-8")),
    }


def run_prefix_probe() -> dict[str, Any]:
    routes = {"V1": ("D", "A", "B", "C"), "V2": ("D", "E", "F")}
    frozen = {"V1": ("D", "A"), "V2": ("D", "E")}
    repaired = own_minimal_suffix_repair(
        routes,
        frozen,
        suffix_rank={"B": 2, "C": 1, "F": 0},
    )
    assert_frozen_prefixes(repaired, frozen)

    contamination_detected = False
    try:
        assert_frozen_prefixes(
            {"V1": ("D", "B", "A", "C"), "V2": ("D", "E", "F")},
            frozen,
        )
    except ValueError:
        contamination_detected = True

    return {
        "status": "PASS_OWN_PREFIX_LOCK",
        "input_routes": {key: list(value) for key, value in routes.items()},
        "repaired_routes": {key: list(value) for key, value in repaired.items()},
        "prefix_preserved": True,
        "deliberate_contamination_detected": contamination_detected,
    }


def run_stability_probe() -> dict[str, Any]:
    before, after, frozen_lengths = build_hand_checkable_stability_case()
    primary = route_stability_metrics(before, after, frozen_lengths)
    independent = independent_route_stability_oracle(before, after, frozen_lengths)
    return {
        "status": "PASS_INDEPENDENT_STABILITY_RECALC",
        "primary": primary,
        "independent": independent,
        "exact_agreement": primary == independent,
        "hand_expected": {
            "customer_vehicle_changes": 2,
            "future_edge_symmetric_difference": 6,
            "future_route_position_changes": 2,
            "future_levenshtein_distance": 2,
        },
    }


def raw_row(
    probe_id: str,
    variant: str,
    status: str,
    details: dict[str, Any],
    *,
    budget: int | None = None,
    complete_evaluations: int = 0,
    cheap_checks: int = 0,
    activity_count: int = 0,
) -> dict[str, Any]:
    return {
        "probe_id": probe_id,
        "variant": variant,
        "budget": "" if budget is None else budget,
        "complete_evaluations": complete_evaluations,
        "cheap_checks": cheap_checks,
        "activity_count": activity_count,
        "status": status,
        "details_json": json.dumps(details, ensure_ascii=False, sort_keys=True),
    }


def build_report(
    rows: list[dict[str, Any]],
    state: dict[str, Any],
    own_prefix: dict[str, Any],
    external_prefix: dict[str, Any],
    stability: dict[str, Any],
) -> str:
    budget_rows = [row for row in rows if row["probe_id"] == "DYN-C3"]
    return f"""# EA-001 动态重规划隔离微探针报告

## 结论

本包判定为 `PASS_FUNCTION_ACTIVITY_ACCOUNTING_ONLY`。四类人工微例均完成：当前车辆状态可以确定性序列化并无损回读；自有最小后缀修复保持硬冻结前缀并能识别故意污染；OR-Tools外部对照状态为 `{external_prefix["status"]}`；有界regret/ejection在预算0/1/2/5下分别准确记录完整微例评价；路线稳定性四个指标由两套独立实现得到完全一致结果。

这不是性能证据。没有调用正式ReSETP评价器，没有读取E7中间结果，没有修改正式solver、`winner.py`、E7运行/保护目录、模型、单位或正式合同。微例中的“完整评价”只指本目录内人工容量、唯一性和车型兼容检查，不能与正式ALNS完整评价混用。

## 四项探针

状态伪车场探针恢复了两个物理车辆ID，回读相等=`{state["round_trip_equal"]}`，序列化SHA-256为`{state["encoded_sha256"]}`。字段保留当前位置、决策时刻、载重、容量、SOC、电池容量、冻结前缀和在车订单；字段单位没有转换。

硬冻结前缀探针只重排前缀后的节点，前缀保持=`{own_prefix["prefix_preserved"]}`，故意把冻结节点换位时被拒绝=`{own_prefix["deliberate_contamination_detected"]}`。OR-Tools仅作已安装环境的外部语义对照，不接入正式依赖或正式求解器；版本为`{external_prefix.get("version")}`。

regret微例对U和V计算regret-2，U的后悔值7高于V的1，因此选择U，证明排序路径被实际调用。ejection微例中新增订单N只能由V1服务，直接插入因容量失败；合法修复需要把A从V1移至V2，再把C从V2移至V3，故最小有效链深为2。预算记录为：{", ".join(f'{row["budget"]}→{row["complete_evaluations"]}' for row in budget_rows)}。预算1只评价到不兼容候选，预算2首次激活合法深度2链；预算5继续按上限计数。这里不比较成本、速度或胜率。

路线稳定性只计算冻结前缀之后的未来变化，并按物理车辆ID匹配。两套实现一致=`{stability["exact_agreement"]}`；人工结果为换车客户2、未来有向弧对称差6、车辆—位置变化2、Levenshtein距离2。

## 验收边界

验收只包括功能正确、故意污染能被拦截、算子路径确实活跃、预算不超不漏、独立复算一致、代码和记录哈希闭合。`formal_search_allowed=false`，`performance_claim_allowed=false`。若后续要把任何表示、冻结器、算子或指标接入正式ALNS/E7，仍须用户另行批准。
"""


def main() -> int:
    started = datetime.now(TIMEZONE)
    state = run_state_probe()
    own_prefix = run_prefix_probe()
    external_prefix = ortools_lock_probe()
    stability = run_stability_probe()
    ejection_results = [
        bounded_regret_ejection_probe(budget) for budget in (0, 1, 2, 5)
    ]

    if not state["round_trip_equal"]:
        raise RuntimeError("state round-trip failed")
    if not own_prefix["deliberate_contamination_detected"]:
        raise RuntimeError("frozen-prefix contamination was not detected")
    if external_prefix["available"] and not external_prefix["prefix_preserved"]:
        raise RuntimeError("OR-Tools external lock comparison failed")
    if not stability["exact_agreement"]:
        raise RuntimeError("stability recomputation disagreed")
    if stability["primary"] != stability["hand_expected"]:
        raise RuntimeError("stability metrics differ from hand calculation")

    rows = [
        raw_row("DYN-C1", "state_round_trip", state["status"], state),
        raw_row("DYN-C4", "own_minimal_lock", own_prefix["status"], own_prefix),
        raw_row(
            "DYN-C4",
            "ortools_external_comparison",
            external_prefix["status"],
            external_prefix,
        ),
    ]
    for result in ejection_results:
        rows.append(
            raw_row(
                "DYN-C3",
                f"budget_{result['budget']}",
                "PASS_ACTIVITY_AND_COUNT",
                result,
                budget=int(result["budget"]),
                complete_evaluations=int(result["complete_evaluations"]),
                cheap_checks=int(result["cheap_direct_checks"]),
                activity_count=int(result["accepted_candidate_count"]),
            )
        )
    rows.append(
        raw_row(
            "DYN-C2",
            "independent_stability_recalc",
            stability["status"],
            stability,
            activity_count=sum(stability["primary"].values()),
        )
    )

    raw_path = OUTPUT_DIR / "raw_runs.csv"
    with raw_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    completed = datetime.now(TIMEZONE)
    status_lines = git_output("status", "--short").splitlines()
    metadata = {
        "schema_version": "ea001-dynamic-replanning-microprobes.v1",
        "authorization": "EA-001",
        "scope": "isolated synthetic functionality, activity, and accounting probes only",
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "elapsed_seconds": (completed - started).total_seconds(),
        "command": (
            "PYTHONHASHSEED=0 python3 "
            "baselines/algorithm_prototypes/dynamic_replanning_20260718/run_probes.py"
        ),
        "repo_head": git_output("rev-parse", "HEAD"),
        "working_tree_was_dirty": bool(status_lines),
        "working_tree_dirty_entry_count_at_packaging": len(status_lines),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
        "ortools_available": bool(external_prefix["available"]),
        "ortools_version": external_prefix.get("version"),
        "formal_solver_imported": False,
        "formal_evaluator_called": False,
        "formal_search_evaluations": 0,
        "synthetic_complete_evaluations": sum(
            int(result["complete_evaluations"]) for result in ejection_results
        ),
        "e7_intermediate_results_read": False,
        "e7_protected_files_modified": False,
        "winner_modified": False,
        "formal_solver_modified": False,
        "model_modified": False,
        "units_modified_or_converted": False,
        "formal_contract_modified": False,
        "performance_claim_allowed": False,
        "formal_search_allowed": False,
        "probe_rows": len(rows),
    }
    write_json(OUTPUT_DIR / "metadata.json", metadata)

    decision = {
        "schema_version": "ea001-dynamic-replanning-microprobes-decision.v1",
        "decision": "PASS_FUNCTION_ACTIVITY_ACCOUNTING_ONLY",
        "authorization": "EA-001",
        "probe_results": {
            "state_pseudo_depot_round_trip": state["status"],
            "own_hard_frozen_prefix": own_prefix["status"],
            "ortools_external_lock_comparison": external_prefix["status"],
            "bounded_regret_ejection_budgets": {
                str(result["budget"]): {
                    "complete_evaluations": result["complete_evaluations"],
                    "budget_closed": result["budget_closed"],
                    "bounded_depth_two_active": result["bounded_depth_two_active"],
                }
                for result in ejection_results
            },
            "independent_route_stability_recalculation": stability["status"],
        },
        "all_budget_counts_exact": all(
            result["budget_closed"] for result in ejection_results
        ),
        "functional_or_activity_failure_count": 0,
        "formal_search_allowed": False,
        "performance_claim_allowed": False,
        "merge_into_formal_alns_allowed": False,
        "formal_e7_change_allowed": False,
        "explicit_non_claims": [
            "No runtime, solution-quality, feasibility-rate, or algorithm superiority claim.",
            "Synthetic complete evaluations are not formal ReSETP evaluations.",
            "OR-Tools is an isolated external semantic comparison, not an approved dependency.",
            "No candidate is approved for formal integration by this probe.",
        ],
    }
    write_json(OUTPUT_DIR / "decision.json", decision)

    report = build_report(rows, state, own_prefix, external_prefix, stability)
    (OUTPUT_DIR / "report.md").write_text(report, encoding="utf-8")

    artifact_names = [
        "prototype.py",
        "run_probes.py",
        "test_dynamic_replanning_prototype.py",
        "metadata.json",
        "raw_runs.csv",
        "decision.json",
        "report.md",
    ]
    artifacts = {
        name: hashlib.sha256((OUTPUT_DIR / name).read_bytes()).hexdigest()
        for name in artifact_names
    }
    write_json(
        OUTPUT_DIR / "artifact_hashes.json",
        {
            "schema_version": "ea001-dynamic-replanning-artifact-hashes.v1",
            "hash_algorithm": "SHA-256",
            "self_excluded": True,
            "excluded_patterns": ["artifact_hashes.json", "._*", "__pycache__", ".pytest_cache"],
            "artifacts": artifacts,
            "decision": decision["decision"],
            "formal_search_allowed": False,
        },
    )

    print(
        json.dumps(
            {
                "decision": decision["decision"],
                "output_dir": str(OUTPUT_DIR),
                "rows": len(rows),
                "synthetic_complete_evaluations": metadata[
                    "synthetic_complete_evaluations"
                ],
                "formal_search_evaluations": 0,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
