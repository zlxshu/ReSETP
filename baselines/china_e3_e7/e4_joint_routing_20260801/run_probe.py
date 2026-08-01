#!/usr/bin/env python3
"""Run the approved low-cost E4 joint-routing SOC probe."""

from __future__ import annotations

import csv
from dataclasses import asdict, replace
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[3]
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
for path in (REPO, REPO / "solver/src", PROTOTYPE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from route_pool_sp import run_hgs_route_pool_recombination
from setp_solver.china81 import load_china81_bundle
from setp_solver.solution import Route, Solution

from baselines.china_instances.build_china81_finite_fleet_authority_v1_20260723 import (
    _pack_depot,
)
from baselines.china_e3_e7.e4_joint_routing_20260801.joint_soc_wrapper import (
    COST_ONLY,
    COST_PLUS_CARBON,
    MODES,
    PURE_CARBON,
    complete_route_skeleton,
    physical_soc_prices,
    register_objective,
    route_pool_hooks,
    score_fixed_solution,
)


INSTANCE_ID = "cn-prd-50c-01-V2-LOCATIONS"
SEEDS = (1, 2, 3)
ITERATIONS = 100
ARCHIVE = 8
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
)
OLD_E4 = REPO / "baselines/china_e3_e7/e4_carbon_timing_20260729"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_bundle(instance_id: str = INSTANCE_ID) -> Any:
    data = REPO / "data/ChinaInstances"
    base = load_china81_bundle(
        REPO,
        instance_id,
        static_input_authority=data / "china81_stage2_static_inputs_corrected_v3_20260723",
        road_matrix_authority=data / "china81_local_directed_matrices_corrected_v10_20260723",
        runtime_parameter_authority=data / "china81_runtime_parameter_authority_v4_20260723",
        fleet_authority=data / "china81_finite_fleet_authority_v1_20260723",
    )
    return replace(
        base,
        prices=physical_soc_prices(base),
        formal_search_allowed=True,
    )


def initial_skeleton(bundle: Any) -> Solution:
    routes: list[Route] = []
    for depot_id in sorted(set(bundle.customer_home_depot.values())):
        for group in _pack_depot(bundle, depot_id):
            routes.append(
                Route(
                    f"E4-INIT-{len(routes) + 1:04d}",
                    "cv",
                    depot_id,
                    [depot_id, *group, depot_id],
                )
            )
    return Solution(routes=routes)


def route_signature(solution: Solution, *, typed: bool) -> list[Any]:
    rows = []
    for route in solution.routes:
        customers = [
            node_id
            for node_id in route.node_sequence
            if not node_id.startswith("D_") and not node_id.startswith("S_")
        ]
        rows.append(
            (
                route.home_depot_id,
                route.vehicle_type if typed else "*",
                tuple(customers),
            )
        )
    return sorted(rows)


def run_one(
    bundle: Any,
    initial: Solution,
    instance_id: str,
    seed: int,
    mode: str,
    iterations: int,
    archive: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    register_objective(bundle, mode)
    start = score_fixed_solution(
        complete_route_skeleton(initial, bundle).solution,
        bundle,
        validate_full=True,
    )
    if start.violations:
        raise RuntimeError(f"initial completion has {len(start.violations)} violations")
    run = run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=seed,
        hgs_seconds_per_view=None,
        exact_elites_per_view=archive,
        max_archive_candidates_per_view=archive,
        sp_time_limit_seconds=5.0,
        max_hgs_iterations_per_view=iterations,
        wallclock_safety_seconds_per_view=180.0,
        exact_checkpoint_interval_iterations=None,
    )
    final = score_fixed_solution(run.solution, bundle, validate_full=True)
    if final.violations:
        raise RuntimeError(f"final completion has {len(final.violations)} violations")
    breakdown = final.breakdown
    soc_min = min((float(row["minimum_soc"]) for row in final.soc_rows), default=0.60)
    soc_final = min((float(row["final_soc_after_terminal_charge"]) for row in final.soc_rows), default=0.60)
    path_hash = canonical_sha(route_signature(final.solution, typed=False))
    typed_hash = canonical_sha(route_signature(final.solution, typed=True))
    row = {
        "instance_id": instance_id,
        "seed": seed,
        "objective_mode": mode,
        "objective_value": final.objective,
        "objective_unit": "kgCO2e" if mode == PURE_CARBON else "CNY",
        "operating_cost_cny": breakdown["operating_cost_cny"],
        "cost_plus_carbon_cny": breakdown["cost_plus_carbon_cny"],
        "electricity_cost_cny": breakdown["cost_elec"],
        "carbon_cost_cny": breakdown["cost_carbon"],
        "system_emissions_kg": breakdown["E_total"],
        "charging_emissions_kg": breakdown["E_ev_indirect"],
        "charging_energy_kwh": breakdown["electricity_kwh"],
        "distance_km": breakdown["distance_total"] / 1000.0,
        "route_count": len(final.solution.routes),
        "used_cv": int(breakdown["n_veh_cv"]),
        "used_ev": int(breakdown["n_veh_ev"]),
        "public_station_charge_count": len(final.solution.charging_actions),
        "terminal_depot_charge_count": len(final.terminal_charges),
        "minimum_soc": soc_min,
        "minimum_final_soc": soc_final,
        "path_hash": path_hash,
        "typed_path_hash": typed_hash,
        "path_differs_from_cost_only": "",
        "types_differ_from_cost_only": "",
        "complete_candidate_evaluations": run.stats[
            "complete_candidate_evaluation_attempts"
        ],
        "elapsed_seconds": run.elapsed_seconds,
        "selected_source": run.stats["selected_source"],
        "solution_sha256": canonical_sha(asdict(final.solution)),
        "status": "PASS",
        "failure_reason": "",
    }
    payload = {
        "instance_id": instance_id,
        "seed": seed,
        "objective_mode": mode,
        "solution": asdict(final.solution),
        "terminal_charges": list(final.terminal_charges),
        "soc_rows": list(final.soc_rows),
        "breakdown": breakdown,
        "search_stats": run.stats,
        "initial_objective": start.objective,
        "final_objective": final.objective,
    }
    return row, payload


def finalize_hashes(output: Path) -> None:
    rows = {}
    for path in sorted(output.rglob("*")):
        if (
            not path.is_file()
            or path.name == "artifact_hashes.json"
            or path.name.startswith("._")
            or "__pycache__" in path.parts
            or ".pytest_cache" in path.parts
        ):
            continue
        rows[str(path.relative_to(output))] = sha256(path)
    write_json(output / "artifact_hashes.json", rows)


def report_text(
    decision: dict[str, Any], rows: list[dict[str, Any]], seeds: tuple[int, ...]
) -> str:
    capacity_text = "、".join(
        f"{depot} 最多 {values['ev_cap']} 辆电车/{values['chargers']} 支枪"
        for depot, values in decision["terminal_capacity_basis"].items()
    )
    lines = [
        "# E4 路线—车型—充电联合小试",
        "",
        f"**终态：`{decision['status']}`。**",
        "",
        f"本轮在 {decision['instance_id']} 上执行日初 60%、最低 20%、最高 80%、日末至少 60% 的电量循环。",
        "客户路径、车辆类型、途中充电站和充电时刻都进入同一候选评价；算法仍受原算例逐车场油车、电车上限约束，没有另设车型比例。",
        "",
        "| seed | 目标 | 运营成本/元 | 含碳成本/元 | 系统排放/kg | 电费/元 | 油车 | 电车 | 途中充电 | 最低SOC |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        if row["status"] != "PASS":
            continue
        lines.append(
            f"| {row['seed']} | {row['objective_mode']} | "
            f"{float(row['operating_cost_cny']):.2f} | "
            f"{float(row['cost_plus_carbon_cny']):.2f} | "
            f"{float(row['system_emissions_kg']):.2f} | "
            f"{float(row['electricity_cost_cny']):.2f} | "
            f"{row['used_cv']} | {row['used_ev']} | "
            f"{row['public_station_charge_count']} | "
            f"{100 * float(row['minimum_soc']):.1f}% |"
        )
    passed = [row for row in rows if row["status"] == "PASS"]
    by_seed = {
        seed: {
            row["objective_mode"]: row
            for row in passed
            if int(row["seed"]) == seed
        }
        for seed in seeds
    }
    lines.extend(
        [
            "",
            "## 三种目标实际差多少",
            "",
            "| seed | 含碳成本目标：排放变化 | 含碳成本目标：运营成本变化 | 纯碳目标：排放变化 | 纯碳目标：运营成本变化 |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for seed, modes in by_seed.items():
        if set(modes) != set(MODES):
            continue
        cost = modes[COST_ONLY]
        joint = modes[COST_PLUS_CARBON]
        carbon = modes[PURE_CARBON]

        def pct(candidate: dict[str, Any], base: dict[str, Any], key: str) -> float:
            return 100.0 * (
                float(candidate[key]) / float(base[key]) - 1.0
            )

        lines.append(
            f"| {seed} | {pct(joint, cost, 'system_emissions_kg'):+.2f}% | "
            f"{pct(joint, cost, 'operating_cost_cny'):+.2f}% | "
            f"{pct(carbon, cost, 'system_emissions_kg'):+.2f}% | "
            f"{pct(carbon, cost, 'operating_cost_cny'):+.2f}% |"
        )
    complete = [modes for modes in by_seed.values() if set(modes) == set(MODES)]
    joint_same_route_and_type = sum(
        modes[COST_PLUS_CARBON]["path_hash"] == modes[COST_ONLY]["path_hash"]
        and modes[COST_PLUS_CARBON]["typed_path_hash"]
        == modes[COST_ONLY]["typed_path_hash"]
        for modes in complete
    )
    pure_changed_route_or_type = sum(
        modes[PURE_CARBON]["path_hash"] != modes[COST_ONLY]["path_hash"]
        or modes[PURE_CARBON]["typed_path_hash"]
        != modes[COST_ONLY]["typed_path_hash"]
        for modes in complete
    )
    public_station_charges = sum(
        int(row["public_station_charge_count"]) for row in passed
    )
    lines.extend(
        [
            "",
            f"含碳成本目标在 {joint_same_route_and_type}/{len(complete)} 个种子中保留纯成本路线和车型，仅改变充电时刻。纯碳目标在 {pure_changed_route_or_type}/{len(complete)} 个种子中改变了路线或车型安排。",
            f"{len(passed)} 个最终方案共使用 {public_station_charges} 次途中公共站充电；公共站修复功能没有关闭。",
            f"返场补电不存在隐含排队冲突：{capacity_text}，且每辆车最多一个返场补电动作。",
            "",
            "## 约束是怎样真实执行的",
            "",
            "现有检查器把电量下界固定为零。本隔离实现把 20% 安全储备从电量账本中扣除：物理 20%--80% 对应检查器的 0%--60%，物理 60% 对应 40%。途中充电仍由原路线检查器核对；返回车场后的补电单独核算，并逐车验证充电窗口、功率、车场枪数和日末不低于 60%。",
            "",
            "现有 `check.py` 虽能识别“返回后充电”的时间窗口，但电量函数会把同一车场的全部充电动作先加到出发电量。把日末补电直接塞回原 `Solution` 会被当成日初补电，因此本轮没有伪装成原生支持，而是把日末补电留在独立终端账本。",
            "",
            "## 与旧 E4 的关系",
            "",
            "旧 E4 的固定路线纯碳择时结果保持原样：充电排放下降 54.9704%，系统排放下降 9.7463%，电费增加 134.8798%。本目录是新的联合优化小试，不覆盖旧文件。",
        ]
    )
    if decision.get("failure_reason"):
        lines.extend(["", "## 停止原因", "", str(decision["failure_reason"])])
    return "\n".join(lines) + "\n"


def run(
    output: Path,
    instance_id: str = INSTANCE_ID,
    seeds: tuple[int, ...] = SEEDS,
    iterations: int = ITERATIONS,
    archive: int = ARCHIVE,
    formal: bool = False,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    (output / "solutions").mkdir(exist_ok=True)
    protected_before = {str(path.relative_to(REPO)): sha256(path) for path in PROTECTED}
    rows: list[dict[str, Any]] = []
    failure = ""
    completed_seeds: list[int] = []
    with route_pool_hooks():
        bundle = load_bundle(instance_id)
        initial = initial_skeleton(bundle)
        for seed in seeds:
            seed_rows: list[dict[str, Any]] = []
            try:
                for mode in MODES:
                    row, payload = run_one(
                        bundle, initial, instance_id, seed, mode, iterations, archive
                    )
                    seed_rows.append(row)
                    rows.append(row)
                    write_json(output / "solutions" / f"seed{seed}_{mode.lower()}.json", payload)
                    write_csv(output / "raw_runs.csv", rows)
                cost_row = next(row for row in seed_rows if row["objective_mode"] == COST_ONLY)
                for row in seed_rows:
                    row["path_differs_from_cost_only"] = row["path_hash"] != cost_row["path_hash"]
                    row["types_differ_from_cost_only"] = row["typed_path_hash"] != cost_row["typed_path_hash"]
                completed_seeds.append(seed)
                write_csv(output / "raw_runs.csv", rows)
            except Exception as exc:
                failure = f"{type(exc).__name__}: {exc}"
                rows.append(
                    {
                        "instance_id": instance_id,
                        "seed": seed,
                        "objective_mode": mode,
                        **{key: "" for key in (
                            "objective_value", "objective_unit", "operating_cost_cny",
                            "cost_plus_carbon_cny", "electricity_cost_cny", "carbon_cost_cny",
                            "system_emissions_kg", "charging_emissions_kg", "charging_energy_kwh",
                            "distance_km", "route_count", "used_cv", "used_ev",
                            "public_station_charge_count", "terminal_depot_charge_count",
                            "minimum_soc", "minimum_final_soc", "path_hash", "typed_path_hash",
                            "path_differs_from_cost_only", "types_differ_from_cost_only",
                            "complete_candidate_evaluations", "elapsed_seconds", "selected_source",
                            "solution_sha256",
                        )},
                        "status": "HALT_TECHNICAL_ERROR",
                        "failure_reason": failure,
                    }
                )
                write_csv(output / "raw_runs.csv", rows)
                break

    protected_after = {str(path.relative_to(REPO)): sha256(path) for path in PROTECTED}
    protected_unchanged = protected_before == protected_after
    all_pass = len(rows) == 3 * len(seeds) and all(
        row["status"] == "PASS" for row in rows
    )
    if not all_pass or not protected_unchanged:
        status = "HALT_E4_JOINT_SOC_TECHNICAL"
    else:
        status = (
            "PASS_FORMAL_PANEL_MEMBER"
            if formal
            else "PASS_TECHNICAL_JOINT_SOC_WRAPPER"
        )
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    decision = {
        "status": status,
        "instance_id": instance_id,
        "formal_adoption": "USER_APPROVED" if formal else "TECHNICAL_PROBE",
        "completed_seeds": completed_seeds,
        "objective_modes": list(MODES),
        "failure_reason": failure,
        "protected_files_unchanged": protected_unchanged,
        "all_rows_retained": True,
        "old_e4_overwritten": False,
        "route_path_changed_against_cost_only_count": sum(
            row.get("path_differs_from_cost_only") is True for row in rows
        ),
        "typed_path_changed_against_cost_only_count": sum(
            row.get("types_differ_from_cost_only") is True for row in rows
        ),
        "terminal_capacity_basis": {
            depot: {
                "ev_cap": int(caps["num_ev"]),
                "chargers": int(nodes[depot].station_chargers or 1),
            }
            for depot, caps in sorted(bundle.fleet_caps_by_depot.items())
        },
    }
    old_decision = json.loads((OLD_E4 / "decision.json").read_text(encoding="utf-8"))
    metadata = {
        "schema": "resetp.e4-joint-routing-probe.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "python": sys.executable,
        "python_version": platform.python_version(),
        "command": (
            "PYTHONPATH=solver/src:baselines/algorithm_prototypes/"
            "china81_mechanism_hybrid_20260720:. "
            "build/python_envs/pyvrp-hgs-0.12.2/bin/python "
            "baselines/china_e3_e7/e4_joint_routing_20260801/run_probe.py"
        ),
        "instance_id": instance_id,
        "seeds": list(seeds),
        "evidence_role": "FORMAL_PANEL_MEMBER" if formal else "TECHNICAL_PROBE",
        "iterations_per_hgs_view": iterations,
        "archive_candidates_per_view": archive,
        "soc_contract": {"initial": 0.60, "minimum": 0.20, "maximum": 0.80, "final_minimum": 0.60},
        "fleet_caps_by_depot": {
            depot: dict(caps) for depot, caps in bundle.fleet_caps_by_depot.items()
        },
        "vehicle_ratio_constraint": None,
        "objective_modes": {
            COST_ONLY: "operating cost; carbon price exactly zero in the objective",
            COST_PLUS_CARBON: "operating cost plus current China81 carbon price",
            PURE_CARBON: "system kgCO2e only",
        },
        "old_fixed_route_reference": {
            "path": str(OLD_E4.relative_to(REPO)),
            "status": old_decision["evidence_status"],
            "charging_emissions_reduction_pct": old_decision["primary_endpoint_value"],
            "overwritten": False,
        },
        "native_engine_gap": {
            "time_window_support": "check.py recognizes post-route depot charging",
            "battery_ledger_gap": "check.py _check_battery applies every depot action before route travel",
            "implementation": "terminal restoration is kept in an isolated independently checked ledger",
        },
        "source_sha256": {
            str(path.relative_to(REPO)): sha256(path)
            for path in (
                Path(__file__),
                HERE / "joint_soc_wrapper.py",
                *PROTECTED,
                OLD_E4 / "decision.json",
            )
        },
        "protected_sha256_before": protected_before,
        "protected_sha256_after": protected_after,
    }
    write_json(output / "metadata.json", metadata)
    write_json(output / "decision.json", decision)
    (output / "report.md").write_text(
        report_text(decision, rows, seeds), encoding="utf-8"
    )
    finalize_hashes(output)
    return decision


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=HERE / "probe_v2_hook_restore_20260801"
    )
    parser.add_argument("--instance", default=INSTANCE_ID)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    parser.add_argument("--formal", action="store_true")
    args = parser.parse_args()
    decision = run(
        args.output,
        instance_id=args.instance,
        seeds=tuple(args.seeds),
        formal=args.formal,
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
