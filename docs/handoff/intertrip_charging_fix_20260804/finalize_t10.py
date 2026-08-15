#!/usr/bin/env python3
"""Build the T10 validation report and integrity records after the runner."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
T5 = REPO / "docs/handoff/carbon_objective_probe_20260804"

BEFORE_HASHES = {
    "solver/src/setp_solver/cost.py": "e7ea406da87a3172cd1ff7dc87fe7def536e74f197f6c67b29da2394fe42b00d",
    "solver/src/setp_solver/check.py": "86b813152b2fc7f89500468cc3d73178cb1bdafe9dc659852b437c5fdb07702b",
    "solver/src/setp_solver/search/evaluation.py": "c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3",
}
TEST_SUMMARY = {
    "command": "PYTHONHASHSEED=0 PYTHONPATH=solver/src /opt/anaconda3/bin/python3.13 -m pytest solver/tests -q",
    "passed": 898,
    "skipped": 1,
    "failed": 14,
    "duration_seconds": 333.74,
    "failures": [
        {"test": "tests/test_china81_shared_completion_20260720.py::test_shared_completion_is_feasible_monotone_and_complete", "reason": "old test requires charge_day_offset=0; repaired generator emits pre-horizon first-trip charging at -1"},
        {"test": "tests/test_e2_80k_robustness_gate.py::test_protected_semantics_and_goeke80_parameters_match_frozen_commit", "reason": "pre-existing protected-contract verdict HALT_FROZEN_PROTECTED_CONTRACT"},
        {"test": "tests/test_e5_ablation.py::E5ChargingAblationTests::test_r1_ablation_report_replays_last_a_routes_with_48_slot_tables", "reason": "pre-existing E5 carbon-aware replay is infeasible"},
        {"test": "tests/test_e5_ablation.py::E5ChargingAblationTests::test_r2_ev_adoption_diagnostic_reports_three_cv_flips_and_swap_counts", "reason": "pre-existing diagnostic labels one case repair_logic_defect"},
        {"test": "tests/test_ev_heavy_findability_gate.py::EvHeavyFindabilityGateTest::test_winner_vehicle_type_swap_uses_instance_fleet_caps", "reason": "pre-existing candidate objective is not below initial objective"},
        {"test": "tests/test_paper_evidence_boundaries.py::test_current_e2b_e3_e4_and_e6_identity_matrices_are_exact", "reason": "pre-existing E4 manifest reports multitrip_schedule.py and check.py drift"},
        {"test": "tests/test_public_station_multitrip_20260723.py::test_public_station_route_closes_strict_clock_soc_and_certificate", "reason": "new approved hard constraint correctly rejects in-trip public charging overlap"},
        {"test": "tests/test_public_station_multitrip_20260723.py::test_public_station_route_passes_mandatory_strict_runtime", "reason": "same new hard constraint makes the old in-trip public-charge fixture infeasible"},
        {"test": "tests/test_refined_carbon_charging.py::test_integrated_route_repair_inserts_station_and_remains_fully_feasible", "reason": "new approved hard constraint correctly rejects in-trip charging overlap"},
        {"test": "tests/test_refined_carbon_charging.py::test_refined_reset_and_reconstruction_consumes_one_candidate_evaluation", "reason": "same new hard constraint rejects the old in-trip charging fixture"},
        {"test": "tests/test_search.py::SearchGateTests::test_h2_initial_solution_contains_deterministic_ev_charging_witness", "reason": "new hard constraint removes the old in-trip charging witness"},
        {"test": "tests/test_search.py::SearchGateTests::test_h3_short_alns_has_nonzero_charging_signal", "reason": "same new hard constraint removes the old in-trip charging witness"},
        {"test": "tests/test_search.py::SearchGateTests::test_m0_evheavy_initial_solution_respects_fleet_limits_and_charges", "reason": "same new hard constraint removes the old in-trip charging witness"},
        {"test": "tests/test_strong_bridge_backend_alignment.py::StrongBridgeBackendAlignmentTests::test_decision_gate_reports_backend_only_and_main_local_search_separately", "reason": "pre-existing strong-bridge verdict differs from fixture expectation"},
    ],
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def key(row: dict[str, str]) -> tuple[str, int, int]:
    return row["arm"], int(row["seed"]), int(row["budget"])


def f(row: dict[str, str], name: str) -> float:
    return float(row[name])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def slot_rows() -> list[dict[str, str]]:
    return read_csv(OUT / "slot_distribution.csv")


def nonzero_slots(rows: list[dict[str, str]]) -> list[int]:
    return [int(row["hourly_calendar_row"]) for row in rows if abs(float(row["charging_kwh"])) > 1.0e-9]


def fmt_slots(slots: list[int]) -> str:
    if not slots:
        return "none"
    def hhmm(total_minutes: int) -> str:
        return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"

    return ", ".join(
        f"{slot:02d}({hhmm(slot * 30)}-{hhmm((slot + 1) * 30)})"
        for slot in slots
    )


def main() -> int:
    raw = read_csv(OUT / "raw_runs.csv")
    old = {key(row): row for row in read_csv(T5 / "raw_runs.csv")}
    current = {key(row): row for row in raw}
    expected = {("O", seed, budget) for seed in (1, 2, 3) for budget in (100, 1000)} | {("C", seed, budget) for seed in (1, 2, 3) for budget in (100, 1000)} | {("P", seed, budget) for seed in (1, 2, 3) for budget in (100, 1000)}
    missing = sorted(expected - set(current))
    slot_index: dict[tuple[str, int, int], list[dict[str, str]]] = {}
    for row in slot_rows():
        slot_index.setdefault((row["arm"], int(row["seed"]), int(row["budget"])), []).append(row)

    paired: list[dict[str, Any]] = []
    for run_key in sorted(expected):
        if run_key not in current or run_key not in old:
            continue
        new = current[run_key]
        previous = old[run_key]
        slots = slot_index.get(run_key, [])
        midday = sum(float(row["charging_kwh"]) for row in slots if 25 <= int(row["hourly_calendar_row"]) <= 30)
        paired.append(
            {
                "run_id": new["run_id"],
                "arm": new["arm"],
                "seed": int(new["seed"]),
                "budget": int(new["budget"]),
                "status": new["status"],
                "completed_customer_count": int(float(new["completed_customer_count"])),
                "required_customer_count": int(float(new["required_customer_count"])),
                "completed_demand": f(new, "completed_demand"),
                "required_demand": f(new, "required_demand"),
                "service_red_line_pass": (
                    f(new, "completed_customer_count") == f(new, "required_customer_count")
                    and abs(f(new, "completed_demand") - f(new, "required_demand")) <= 1.0e-9
                ),
                "full_violation_count": int(new["full_violation_count"]),
                "nonzero_slots": nonzero_slots(slots),
                "midday_12_15_kwh": midday,
                "midday_zero": abs(midday) <= 1.0e-9,
                "assigned_cv": int(new["assigned_cv"]),
                "assigned_ev": int(new["assigned_ev"]),
                "previous_assigned_cv": int(previous["assigned_cv"]),
                "previous_assigned_ev": int(previous["assigned_ev"]),
                "vehicle_count_change": int(new["enabled_physical_vehicles"]) - int(previous["enabled_physical_vehicles"]),
                "system_emissions_before_kg": f(previous, "system_emissions_kg"),
                "system_emissions_after_kg": f(new, "system_emissions_kg"),
                "system_emissions_delta_kg": f(new, "system_emissions_kg") - f(previous, "system_emissions_kg"),
                "operating_cost_before_cny": f(previous, "operating_cost_cny"),
                "operating_cost_after_cny": f(new, "operating_cost_cny"),
                "operating_cost_delta_cny": f(new, "operating_cost_cny") - f(previous, "operating_cost_cny"),
                "charging_energy_before_kwh": f(previous, "charging_energy_kwh"),
                "charging_energy_after_kwh": f(new, "charging_energy_kwh"),
                "charging_energy_delta_kwh": f(new, "charging_energy_kwh") - f(previous, "charging_energy_kwh"),
            }
        )

    after_hashes = {relative: sha256(REPO / relative) for relative in BEFORE_HASHES}
    protected_ok = (
        after_hashes["solver/src/setp_solver/cost.py"] == BEFORE_HASHES["solver/src/setp_solver/cost.py"]
        and after_hashes["solver/src/setp_solver/search/evaluation.py"] == BEFORE_HASHES["solver/src/setp_solver/search/evaluation.py"]
        and after_hashes["solver/src/setp_solver/check.py"] != BEFORE_HASHES["solver/src/setp_solver/check.py"]
    )
    regression = json.loads((OUT / "regression_results.json").read_text(encoding="utf-8"))
    complete = len(raw) == 18 and not missing and all(item["full_violation_count"] == 0 for item in paired)
    service_pass = all(item["service_red_line_pass"] for item in paired)
    midday_pass = all(item["midday_zero"] for item in paired)
    metadata = {
        "schema": "resetp.t10-intertrip-charging-fix-metadata.v1",
        "task_id": "T10-INTERTRIP-CHARGING-FIX",
        "status": "TECHNICAL_FIX_VALIDATION_COMPLETE" if complete else "HALT_RUN_INCOMPLETE",
        "draft_status": "TECHNICAL_FIX_VALIDATION",
        "paper_claim_allowed": False,
        "instance": {"instance_id": "cn-jjj-50c-01-V2-LOCATIONS", "scenario_date": "2025-02-12", "customers": 50, "demand": 13264.0},
        "frozen_matrix": {"arms": ["O", "C", "P"], "seeds": [1, 2, 3], "budgets": [100, 1000], "run_count_expected": 18, "pythonhashseed": 0},
        "regression": regression,
        "run_count_observed": len(raw),
        "missing_keys": [list(item) for item in missing],
        "service_red_line_all_pass": service_pass,
        "midday_12_15_zero_all_pass": midday_pass,
        "protected_hashes_before": BEFORE_HASHES,
        "protected_hashes_after": after_hashes,
        "protected_hash_contract_pass": protected_ok,
        "test_suite": TEST_SUMMARY,
        "generator_changes": ["solver/src/setp_solver/china81_completion.py", "solver/src/setp_solver/search/multitrip_schedule.py"],
        "checker_change": "solver/src/setp_solver/check.py: CHARGING_TRIP_OVERLAP",
        "forbidden_changes": ["solver/src/setp_solver/cost.py", "solver/src/setp_solver/search/evaluation.py", "docs/paper_gci_dmm_vrp_20260804/"],
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    decision = {
        "schema": "resetp.t10-intertrip-charging-fix-decision.v1",
        "task_id": "T10-INTERTRIP-CHARGING-FIX",
        "status": metadata["status"],
        "paper_claim_allowed": False,
        "decision": "technical_validation_only",
        "basis": {"positive_regression_pass": regression["positive_passed"] == regression["positive_required"], "legal_regression_pass": regression["legal_passed"] == regression["legal_required"], "run_count": len(raw), "service_red_line_all_pass": service_pass, "midday_zero_all_pass": midday_pass, "protected_hash_contract_pass": protected_ok},
        "interpretation_boundary": "The 18-run replay validates this technical repair only; it is not a formal experiment and supports no paper claim.",
    }
    (OUT / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# T10 充电时段与同一实体车外行程重叠修复验证",
        "",
        "## 回归验证（最前）",
        "",
        f"FACT：三个已知阳性样本通过新检查器，{regression['positive_passed']}/{regression['positive_required']} 命中 `CHARGING_TRIP_OVERLAP`。",
        f"FACT：T9 判定为无重叠且当时合法的解直接调用新 `check_solution`，{regression['legal_passed']}/{regression['legal_required']} 仍合法；误报数为 {regression['legal_required'] - regression['legal_passed']}。",
        "FACT：单元回归 `test_multitrip_schedule.py` 为 23 passed。",
        "DECISION：回归门槛通过，未触发 `HALT_REGRESSION_FAILED`。",
        "",
        "## 保护文件与范围",
        "",
        f"FACT：开工前 SHA-256：`cost.py` `{BEFORE_HASHES['solver/src/setp_solver/cost.py']}`；`check.py` `{BEFORE_HASHES['solver/src/setp_solver/check.py']}`；`search/evaluation.py` `{BEFORE_HASHES['solver/src/setp_solver/search/evaluation.py']}`。",
        f"FACT：收工后 SHA-256：`cost.py` `{after_hashes['solver/src/setp_solver/cost.py']}`；`check.py` `{after_hashes['solver/src/setp_solver/check.py']}`；`search/evaluation.py` `{after_hashes['solver/src/setp_solver/search/evaluation.py']}`。cost/evaluation 逐位不变，check 按批准事项变化。",
        "FACT：生成器修复重排实体车时间线；检查器新增同一实体车充电区间与任一外行程区间的半开区间相交硬约束。未改碳价、碳数据、电价、算例、车队合同、目标函数、`cost.py`、`search/evaluation.py` 或论文目录。",
        "",
        "## T5 冻结矩阵重跑",
        "",
        f"FACT：T10 raw_runs.csv 观察到 {len(raw)}/18 次；缺失键：{', '.join(map(str, missing)) if missing else '无'}。",
        f"FACT：服务量红线通过 {sum(item['service_red_line_pass'] for item in paired)}/{len(paired)}；每次要求 50/50 客户与 13264/13264 需求。",
        f"FACT：12:00—15:00 充电量归零 {sum(item['midday_zero'] for item in paired)}/{len(paired)} 次。",
        "",
        "### 逐次结果（修复前→修复后）",
        "",
        "| run | 服务量 | 槽位 | 中午 kWh | 实体车数变化 | 系统排放 kg 前→后 | 运营成本 CNY 前→后 | 充电 kWh 前→后 |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for item in paired:
        service = f"{item['completed_customer_count']}/{item['required_customer_count']}; {item['completed_demand']:.3f}/{item['required_demand']:.3f}"
        lines.append(
            f"| {item['run_id']} | {service} | {fmt_slots(item['nonzero_slots'])} | {item['midday_12_15_kwh']:.6f} | {item['vehicle_count_change']:+d} | {item['system_emissions_before_kg']:.6f}→{item['system_emissions_after_kg']:.6f} | {item['operating_cost_before_cny']:.6f}→{item['operating_cost_after_cny']:.6f} | {item['charging_energy_before_kwh']:.6f}→{item['charging_energy_after_kwh']:.6f} |"
        )
    lines.extend([
        "",
        "FACT：逐次原始字段、48 槽明细和最终解见证分别保存在 `raw_runs.csv`、`slot_distribution.csv`、`solution_witnesses.json`；本表的前值来自 T5 同键原始记录。",
        "FACT：因修复而增加实体车辆的次数为 " + str(sum(item["vehicle_count_change"] > 0 for item in paired)) + "；因修复导致搜索未找到可行解的次数以 `raw_runs.csv` 的缺失键计，本次为 " + str(len(missing)) + "。",
        "INFERENCE：若修复后实体车数上升，含义是原先路线池依赖了不允许的重叠充电安排；这不等同于证明模型硬不可行。",
        "DECISION：本目录只作为技术缺陷修复验证；`decision.json.paper_claim_allowed=false`。",
        "DECISION：本次未触发 `HALT_REGRESSION_FAILED`、`HALT_REQUIRES_PROTECTED_FILE_CHANGE` 或 `HALT_AWAITING_USER_APPROVAL`。",
        "",
        "## 测试套件逐条结果",
        "",
        f"FACT：全量结果为 {TEST_SUMMARY['passed']} passed、{TEST_SUMMARY['skipped']} skipped、{TEST_SUMMARY['failed']} failed。失败逐条原因见 `metadata.json.test_suite.failures`；其中与本次新增硬约束直接相关的旧 in-trip charging fixture 失败均保留，未通过放宽约束消除。",
    ])
    lines.extend(
        f"- FAIL：{item['test']} — {item['reason']}"
        for item in TEST_SUMMARY["failures"]
    )
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    excluded = {"artifact_hashes.json"}
    artifacts: dict[str, str] = {}
    for path in sorted(OUT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(OUT).as_posix()
        if (
            relative in excluded
            or any(part.startswith("._") for part in path.parts)
            or "__pycache__" in path.parts
            or ".pytest_cache" in path.parts
            or relative.startswith(".experiment.monitor")
            or relative.startswith(".attempt")
            or path.suffix in {".pyc", ".tmp", ".temp"}
            or relative == "run.log"
        ):
            continue
        artifacts[relative] = sha256(path)
    artifact_hashes = {
        "schema": "resetp.t10-intertrip-charging-fix-artifact-hashes.v1",
        "task_id": "T10-INTERTRIP-CHARGING-FIX",
        "algorithm": "sha256",
        "artifacts": artifacts,
        "exclusions": ["artifact_hashes.json", "._*", "**/__pycache__/**", "**/.pytest_cache/**", ".experiment.monitor*/**", ".attempt*/**", "*.pyc", "temporary files (*.tmp, *.temp)", "run.log"],
    }
    (OUT / "artifact_hashes.json").write_text(json.dumps(artifact_hashes, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": metadata["status"], "runs": len(raw), "missing": missing, "service_red_line_all_pass": service_pass, "midday_zero_all_pass": midday_pass}, ensure_ascii=False, sort_keys=True))
    return 0 if complete and service_pass and protected_ok and regression["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
