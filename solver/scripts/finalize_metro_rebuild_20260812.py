#!/usr/bin/env python3
"""Validate the specified METRO 20-cycle run and close its evidence package."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from feasibility_report_text import _format_full_evaluation_result


REPO = Path(__file__).resolve().parents[2]
REPORT = REPO / "solver/reports/metro_rebuild_20260812"
SUITE = REPO / "data/ChinaInstances/china81_metro_suite_v1_20260812"
RUN = REPORT / "cn-cy-50c-01_20cycles"
CONVERGENCE = REPORT / "cn-cy-50c-01_20cycles_convergence.csv"
PROTECTED = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    metadata = read_json(RUN / "metadata.json")
    trial_decision = read_json(RUN / "decision.json")
    best = read_json(RUN / "best_solution.json")
    raw = read_csv(RUN / "raw_runs.csv")
    convergence = read_csv(CONVERGENCE)
    build_decision = read_json(REPORT / "decision.json")
    if len(raw) != 1:
        raise RuntimeError("technical run raw_runs.csv must contain one row")
    run = raw[0]
    expected = {
        "instance_id": "cn-cy-50c-01-V3-TWO-SHIFT-METRO",
        "random_seed": 1,
        "iterations": 20,
        "requested_iteration_ceiling": 20,
        "population_mode": "copied_hgs_defaults",
        "proposal_config": "combat",
        "fleet_parameter_class": "endogenous",
        "trajectory_mode": "off",
    }
    mismatches = {
        key: {"expected": value, "observed": metadata.get(key)}
        for key, value in expected.items()
        if metadata.get(key) != value
    }
    if metadata.get("charging_prescreen", {}).get("enabled") is not True:
        mismatches["charging_prescreen.enabled"] = {
            "expected": True,
            "observed": metadata.get("charging_prescreen", {}).get("enabled"),
        }
    if metadata.get("charging_policy", {}).get("depot_charge_window_mode") != "full_gap":
        mismatches["charging_policy.depot_charge_window_mode"] = {
            "expected": "full_gap",
            "observed": metadata.get("charging_policy", {}).get(
                "depot_charge_window_mode"
            ),
        }
    argv = metadata.get("code_provenance", {}).get("command_argv", [])
    try:
        scenario = argv[argv.index("--depot-charging-scenario") + 1]
    except (ValueError, IndexError):
        scenario = None
    if scenario != "60kw":
        mismatches["depot_charging_scenario"] = {
            "expected": "60kw",
            "observed": scenario,
        }
    if mismatches:
        raise RuntimeError(f"20-cycle configuration mismatch: {mismatches}")
    if metadata.get("status") != "COMPLETE" or trial_decision.get("verdict") != "TECHNICAL_TRIAL_COMPLETE":
        raise RuntimeError("technical run did not complete successfully")
    if build_decision.get("status") != "PASS":
        raise RuntimeError("suite construction decision is not PASS")
    protected_after = {path: sha256(REPO / path) for path in PROTECTED}
    if metadata.get("protected_hashes_after") != protected_after:
        raise RuntimeError("protected hashes differ from the completed run metadata")
    accounting = best["accounting"]
    proposed = accounting["proposed_actions"]
    evaluated = accounting["evaluated_actions"]
    accepted = accounting["accepted_actions"]
    rejected = accounting["rejected_actions"]
    duty_proposed = int(proposed.get("duty_crossover", 0))
    duty_rejected = int(rejected.get("duty_crossover:REJECTED_CHARGING", 0))
    duty_evaluated = int(evaluated.get("duty_crossover", 0))
    duty_accepted = int(accepted.get("duty_crossover", 0))
    rejection_rate = duty_rejected / duty_proposed if duty_proposed else 0.0
    last = convergence[-1] if convergence else {
        "cycle": "",
        "wall_seconds": "",
        "best_total_cost": best["evaluation"]["total_cost"],
    }
    run_wall = float(run["run_wall_seconds"])
    iterations = int(run["iterations"])
    algorithm_wall = float(accounting["total_algorithm_wall_seconds"])
    summary = {
        "evidence_class": "FACT",
        "instance_id": run["instance_id"],
        "seed": int(run["seed"]),
        "iterations": iterations,
        "population_mode": metadata["population_mode"],
        "proposal_config": metadata["proposal_config"],
        "fleet_parameter_class": metadata["fleet_parameter_class"],
        "depot_charge_power_kw": 60.0,
        "charging_prescreen_enabled": True,
        "trajectory_mode": metadata["trajectory_mode"],
        "duty_crossover_proposed": duty_proposed,
        "duty_crossover_rejected_charging": duty_rejected,
        "duty_crossover_evaluated": duty_evaluated,
        "duty_crossover_accepted": duty_accepted,
        "duty_crossover_rejection_rate": rejection_rate,
        "depot_collaboration_proposed": int(
            proposed.get("depot_collaboration", 0)
        ),
        "fairness_cross_depot_proposed": int(
            proposed.get("fairness_cross_depot", 0)
        ),
        "final_cost": float(best["evaluation"]["total_cost"]),
        "last_improvement_cycle": int(last["cycle"]) if last["cycle"] else "",
        "last_improvement_seconds": (
            float(last["wall_seconds"]) if last["wall_seconds"] else ""
        ),
        "run_wall_seconds": run_wall,
        "seconds_per_main_loop_run_wall": run_wall / iterations,
        "total_algorithm_wall_seconds": algorithm_wall,
        "seconds_per_main_loop_algorithm_wall": algorithm_wall / iterations,
        "full_truth_feasible": bool(best["evaluation"]["feasible"]),
        "violation_count": len(best["evaluation"]["violations"]),
        "customers_served": int(run["customers_served"]),
        "customers_total": int(run["customers_total"]),
        "demand_served": float(run["demand_served"]),
        "demand_total": float(run["demand_total"]),
        "run_package": str(RUN.relative_to(REPO)),
        "run_manifest_sha256": sha256(RUN / "artifact_hashes.json"),
    }
    write_json(REPORT / "diagnostic_20cycles_summary.json", summary)
    overall_metadata = read_json(REPORT / "metadata.json")
    overall_metadata["diagnostic_20cycles"] = summary
    write_json(REPORT / "metadata.json", overall_metadata)
    build_decision["diagnostic_20cycles_status"] = "PASS"
    build_decision["diagnostic_20cycles_summary"] = summary
    build_decision["status"] = "METRO_DONE"
    write_json(REPORT / "decision.json", build_decision)

    report_path = REPORT / "report.md"
    report = report_path.read_text(encoding="utf-8")
    marker = "## 20 主循环\n"
    prefix, separator, _ = report.partition(marker)
    if not separator:
        raise RuntimeError("report has no 20-cycle section")
    full_evaluation_result = _format_full_evaluation_result(
        feasible=summary["full_truth_feasible"],
        violation_count=summary["violation_count"],
    )
    run_section = "\n".join(
        [
            marker.rstrip(),
            "",
            f"- `FACT`：指定运行完成：20 主循环、seed 1、`copied_hgs_defaults`、"
            "`combat`、内生车队、60 kW、预筛开、轨迹关。",
            f"- `FACT`：`duty_crossover` 提案/因充电被拒/评价/接受为 "
            f"{duty_proposed}/{duty_rejected}/{duty_evaluated}/{duty_accepted}，"
            f"拒绝率 {rejection_rate * 100:.6f}%。",
            f"- `FACT`：相对用户给定的旧空间基线 1550/1530/20/0，四项变化为 "
            f"{duty_proposed - 1550:+d}/{duty_rejected - 1530:+d}/"
            f"{duty_evaluated - 20:+d}/{duty_accepted:+d}；拒绝率变化 "
            f"{(rejection_rate - 1530 / 1550) * 100:+.6f} 个百分点。",
            f"- `FACT`：`depot_collaboration` 提案数为 "
            f"{summary['depot_collaboration_proposed']}；`fairness_cross_depot` 提案数为 "
            f"{summary['fairness_cross_depot_proposed']}；旧空间基线两者均为 0。",
            f"- `FACT`：最终成本 {summary['final_cost']:.12f}；最后一次改进在第 "
            f"{summary['last_improvement_cycle']} 循环、{summary['last_improvement_seconds']:.6f} 秒。",
            f"- `FACT`：运行段耗时 {run_wall:.6f} 秒，即 {run_wall / iterations:.6f} 秒/主循环；"
            f"含初始化的算法总耗时 {algorithm_wall:.6f} 秒，即 "
            f"{algorithm_wall / iterations:.6f} 秒/主循环。",
            f"- `FACT`：{full_evaluation_result}；"
            f"客户覆盖 {summary['customers_served']}/{summary['customers_total']}，"
            f"需求覆盖 {summary['demand_served']:.6f}/{summary['demand_total']:.6f}。",
            "- `FACT`：运行完整包为 `solver/reports/metro_rebuild_20260812/cn-cy-50c-01_20cycles/`；"
            "其 `metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`、`report.md` 齐全。",
            "",
        ]
    )
    report_path.write_text(prefix + run_section, encoding="utf-8")
    write_json(
        REPORT / "METRO_DONE",
        {
            "status": "METRO_DONE",
            "suite": str(SUITE.relative_to(REPO)),
            "report": str(report_path.relative_to(REPO)),
            "health": str((REPORT / "suite_health_metro.csv").relative_to(REPO)),
            "depot_pair_selection": str(
                (REPORT / "depot_pair_selection.csv").relative_to(REPO)
            ),
            "diagnostic_run": str(RUN.relative_to(REPO)),
            "protected_hashes": protected_after,
        },
    )
    files = {
        str(path.relative_to(REPORT)): sha256(path)
        for path in sorted(REPORT.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    write_json(
        REPORT / "artifact_hashes.json",
        {
            "schema": "resetp.metro-rebuild.artifact-hashes.v1",
            "hash_algorithm": "SHA-256",
            "excluded_self": "artifact_hashes.json",
            "files": files,
            "suite_manifest": str(
                (SUITE / "artifact_hashes.json").relative_to(REPO)
            ),
            "suite_manifest_sha256": sha256(SUITE / "artifact_hashes.json"),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
