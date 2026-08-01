#!/usr/bin/env python3
"""Run the approved symmetric E5-B nonlinear-charging pilot matrix."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


REPO = Path(__file__).resolve().parents[3]
PROTOTYPE = (
    REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
)
for entry in (REPO, REPO / "solver/src", PROTOTYPE):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from route_pool_sp import run_hgs_route_pool_recombination
from setp_solver.algorithms.resetp_alns.support.charging import (
    replay_fixed_route_charging,
)
from setp_solver.check import STATION_CAPACITY, check_solution
from setp_solver.charging_curve import L100_CONTROL
from setp_solver.china81 import China81Bundle, load_china81_bundle
from setp_solver.cost import evaluate
from setp_solver.solution import Route, Solution

from baselines.china_e3_e7.e5_enroute_nonlinear_20260801.runtime_overlay import (
    CAPACITY_SCENARIOS_KWH,
    CURVES,
    M17_22KW_NORMAL_PWL,
    PUBLIC_POWER_SCENARIOS_KW,
    apply_runtime_overlay,
)


DEFAULT_INSTANCE_IDS = (
    "cn-prd-50c-01-V2-LOCATIONS",
    "cn-prd-100c-02-V2-LOCATIONS",
)
DEFAULT_SEEDS = (1,)
ARCHIVE_PER_VIEW = 2
HGS_ITERATIONS_PER_VIEW = 40
WALLCLOCK_SECONDS_PER_VIEW = 120.0
SP_SECONDS = 2.0
FLEET = REPO / "data/ChinaInstances/china81_finite_fleet_authority_v1_20260723"


def _load_initial(instance_id: str) -> Solution:
    data = json.loads(
        (FLEET / "witnesses" / f"{instance_id}.json").read_text(
            encoding="utf-8"
        )
    )
    return Solution(
        routes=[
            Route(
                str(row["vehicle_id"]),
                str(row["vehicle_type"]),
                str(row["home_depot_id"]),
                [str(value) for value in row["node_sequence"]],
            )
            for row in data["routes"]
        ]
    )


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _route_hash(solution: Solution) -> str:
    payload = json.dumps(
        [asdict(route) for route in solution.routes],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _charging_summary(actions: list[Any], capacity_kwh: float) -> dict[str, Any]:
    end_soc = [
        100.0 * float(action.end_energy_kwh) / capacity_kwh
        for action in actions
        if action.end_energy_kwh is not None
    ]
    durations = [float(action.occupancy_minutes) for action in actions]
    return {
        "public_charging_session_count": len(actions),
        "public_charging_minutes_total": sum(durations),
        "public_charging_minutes_max": max(durations, default=0.0),
        "max_public_charge_end_soc_pct": max(end_soc, default=0.0),
        "taper_entered_session_count": sum(
            soc > 85.0 + 1e-9 for soc in end_soc
        ),
    }


def _run_unit(
    base_bundle: China81Bundle,
    initial_solution: Solution,
    seed: int,
    capacity_kwh: float,
    curve_id: str,
    public_power_kw: float,
) -> tuple[dict[str, Any], dict[str, Any], Solution]:
    bundle = apply_runtime_overlay(
        base_bundle,
        capacity_kwh=capacity_kwh,
        curve_id=curve_id,
        public_charge_power_kw=public_power_kw,
    )
    run = run_hgs_route_pool_recombination(
        bundle,
        initial_solution,
        seed=seed,
        hgs_seconds_per_view=None,
        exact_elites_per_view=ARCHIVE_PER_VIEW,
        max_archive_candidates_per_view=ARCHIVE_PER_VIEW,
        sp_time_limit_seconds=SP_SECONDS,
        hard_home_depot_lock=False,
        max_hgs_iterations_per_view=HGS_ITERATIONS_PER_VIEW,
        wallclock_safety_seconds_per_view=WALLCLOCK_SECONDS_PER_VIEW,
        exact_checkpoint_interval_iterations=None,
        preserve_base_pool_recombination=False,
    )
    violations = check_solution(run.solution, bundle.instance, bundle.prices)
    metrics = evaluate(
        run.solution, bundle.instance, bundle.time_profile, bundle.prices
    )
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    public_actions = [
        action for action in run.solution.charging_actions
        if nodes[action.station_id].node_type.lower() == "f"
    ]
    depot_actions = [
        action for action in run.solution.charging_actions
        if nodes[action.station_id].node_type.lower() == "d"
    ]
    if depot_actions:
        raise RuntimeError("full-battery departure produced depot precharging")
    row = {
        "instance_id": base_bundle.instance_id,
        "seed": seed,
        "capacity_kwh": capacity_kwh,
        "public_charge_power_kw": public_power_kw,
        "curve_id": curve_id,
        "feasible": not violations,
        "total_cost_cny": float(metrics["total_cost"]),
        "route_hash": _route_hash(run.solution),
        "route_count": len(run.solution.routes),
        "ev_route_count": sum(route.vehicle_type.lower() == "ev" for route in run.solution.routes),
        "depot_charging_session_count": len(depot_actions),
        **_charging_summary(public_actions, capacity_kwh),
        "station_charging_kwh": float(metrics["station_charging_kwh"]),
        "depot_charging_kwh": float(metrics["depot_charging_kwh"]),
        "complete_candidate_evaluations": int(run.stats["complete_candidate_evaluation_attempts"]),
        "elapsed_seconds": float(run.elapsed_seconds),
        "independent_check_completed": True,
        "violation_count": len(violations),
        "station_capacity_conflict_count": sum(
            item.type == STATION_CAPACITY for item in violations
        ),
    }
    detail = {
        "row": row,
        "violations": [asdict(item) for item in violations],
        "cost_breakdown": metrics,
        "completion_activity": run.completion.activity,
        "solution": asdict(run.solution),
    }
    return row, detail, run.solution


def _recheck_linear_routes_under_m17(
    base_bundle: China81Bundle,
    solution: Solution,
    *,
    capacity_kwh: float,
    public_power_kw: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle = apply_runtime_overlay(
        base_bundle,
        capacity_kwh=capacity_kwh,
        curve_id=M17_22KW_NORMAL_PWL.curve_id,
        public_charge_power_kw=public_power_kw,
    )
    replayed = replay_fixed_route_charging(
        replace(solution, charging_actions=[]),
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        strategy="aware",
    )
    violations = check_solution(replayed, bundle.instance, bundle.prices)
    metrics = evaluate(replayed, bundle.instance, bundle.time_profile, bundle.prices)
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    public_actions = [
        action for action in replayed.charging_actions
        if nodes[action.station_id].node_type.lower() == "f"
    ]
    depot_actions = [
        action for action in replayed.charging_actions
        if nodes[action.station_id].node_type.lower() == "d"
    ]
    if depot_actions:
        raise RuntimeError("full-battery nonlinear recheck produced depot precharging")
    charging = _charging_summary(public_actions, capacity_kwh)
    summary = {
        "linear_routes_m17_recheck_feasible": not violations,
        "linear_routes_m17_recheck_total_cost_cny": float(metrics["total_cost"]),
        "linear_routes_m17_recheck_violation_count": len(violations),
        "linear_routes_m17_recheck_violation_types": "|".join(item.type for item in violations),
        "linear_routes_m17_recheck_station_capacity_conflict_count": sum(
            item.type == STATION_CAPACITY for item in violations
        ),
        **{
            f"linear_routes_m17_recheck_{key}": value
            for key, value in charging.items()
        },
    }
    return summary, {
        "summary": summary,
        "violations": [asdict(item) for item in violations],
        "cost_breakdown": metrics,
        "solution": asdict(replayed),
    }


def _report_text(
    metadata: dict[str, Any],
    decision: dict[str, Any],
    comparisons: list[dict[str, Any]],
) -> str:
    lines = [
        "# E5-B 低成本对称试验",
        "",
        "容量轴 16/20/24/28/32 kWh 是实验车型的容量敏感性设置；"
        "本矩阵不使用福田量产车 77.28 kWh 电池参数。",
        "两种充电模型在同一算例、种子和搜索预算下独立求解；"
        "车辆满电离场，只记录途中公共站补电。",
        "",
        f"共 {decision['unit_count']} 个单元，"
        f"{decision['feasible_unit_count']} 个最终解通过独立检查；"
        f"28 kWh 已进入数据：{decision['contains_28_kwh']}。",
        "",
        "| 算例 | 种子 | 容量 | 线性成本 | 非线性成本 | 差额 | "
        "可行(L/M) | 充电次数(L/M) | 充电分钟(L/M) | "
        "最高结束SOC%(L/M) | 线性路线按M17复核 | 复核桩冲突 |",
        "|---|---:|---:|---:|---:|---:|---|---|---|---|---|---:|",
    ]
    for item in comparisons:
        lines.append(
            f"| {item['instance_id']} | {item['seed']} | "
            f"{item['capacity_kwh']:g} | {item['linear_cost_cny']:.6f} | "
            f"{item['nonlinear_cost_cny']:.6f} | "
            f"{item['nonlinear_minus_linear_cost_cny']:+.6f} | "
            f"{int(item['linear_feasible'])}/{int(item['nonlinear_feasible'])} | "
            f"{item['linear_public_charging_session_count']}/"
            f"{item['nonlinear_public_charging_session_count']} | "
            f"{item['linear_public_charging_minutes_total']:.3f}/"
            f"{item['nonlinear_public_charging_minutes_total']:.3f} | "
            f"{item['linear_max_public_charge_end_soc_pct']:.2f}/"
            f"{item['nonlinear_max_public_charge_end_soc_pct']:.2f} | "
            f"{int(item['linear_routes_m17_recheck_feasible'])} | "
            f"{item['linear_routes_m17_recheck_station_capacity_conflict_count']} |"
        )
    lines.extend(
        [
            "",
            "物理复核为：保留线性模型找到的路线，清空原充电动作，"
            "按 Montoya M17 非线性曲线重排充电后再做完整可行性检查。",
            "",
            f"搜索设置：{json.dumps(metadata['search'], ensure_ascii=False)}",
        ]
    )
    return "\n".join(lines) + "\n"


def run_pilot(
    instance_ids: tuple[str, ...],
    capacities: tuple[float, ...],
    public_powers: tuple[float, ...],
    seeds: tuple[int, ...],
    output_dir: Path,
) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    units = output_dir / "units"
    units.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    original_public_power: dict[str, dict[str, float]] = {}

    for instance_id in instance_ids:
        base_bundle = load_china81_bundle(REPO, instance_id)
        initial_solution = _load_initial(instance_id)
        original_public_power[instance_id] = {
            node.node_id: float(node.charge_power_kw)
            for node in base_bundle.instance.nodes
            if node.node_type.lower() == "f"
        }
        for seed in seeds:
            for power in public_powers:
                for capacity in capacities:
                    pair = {
                        curve_id: _run_unit(
                            base_bundle,
                            initial_solution,
                            seed,
                            capacity,
                            curve_id,
                            power,
                        )
                        for curve_id in CURVES
                    }
                    recheck, recheck_detail = _recheck_linear_routes_under_m17(
                        base_bundle,
                        pair[L100_CONTROL.curve_id][2],
                        capacity_kwh=capacity,
                        public_power_kw=power,
                    )
                    for curve_id, (row, detail, _) in pair.items():
                        row.update(recheck)
                        detail["linear_routes_m17_recheck"] = recheck_detail
                        rows.append(row)
                        _write_json(
                            units
                            / (
                                f"{instance_id}__seed{seed}__P{power:g}"
                                f"__B{capacity:g}__{curve_id}.json"
                            ),
                            detail,
                        )
                    linear = pair[L100_CONTROL.curve_id][0]
                    nonlinear = pair[M17_22KW_NORMAL_PWL.curve_id][0]
                    comparisons.append(
                        {
                            "instance_id": instance_id,
                            "seed": seed,
                            "public_charge_power_kw": power,
                            "capacity_kwh": capacity,
                            "same_search_budget": True,
                            "linear_feasible": bool(linear["feasible"]),
                            "nonlinear_feasible": bool(nonlinear["feasible"]),
                            "feasibility_differs": bool(linear["feasible"])
                            != bool(nonlinear["feasible"]),
                            "route_hash_differs": linear["route_hash"]
                            != nonlinear["route_hash"],
                            "linear_cost_cny": float(linear["total_cost_cny"]),
                            "nonlinear_cost_cny": float(
                                nonlinear["total_cost_cny"]
                            ),
                            "nonlinear_minus_linear_cost_cny": float(
                                nonlinear["total_cost_cny"]
                            )
                            - float(linear["total_cost_cny"]),
                            "linear_public_charging_session_count": int(
                                linear["public_charging_session_count"]
                            ),
                            "nonlinear_public_charging_session_count": int(
                                nonlinear["public_charging_session_count"]
                            ),
                            "linear_public_charging_minutes_total": float(
                                linear["public_charging_minutes_total"]
                            ),
                            "nonlinear_public_charging_minutes_total": float(
                                nonlinear["public_charging_minutes_total"]
                            ),
                            "linear_max_public_charge_end_soc_pct": float(
                                linear["max_public_charge_end_soc_pct"]
                            ),
                            "nonlinear_max_public_charge_end_soc_pct": float(
                                nonlinear["max_public_charge_end_soc_pct"]
                            ),
                            **recheck,
                        }
                    )

    with (output_dir / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    metadata = {
        "task_id": "E5-ENROUTE-NONLINEAR-SYMMETRIC-PILOT-20260801",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "evidence_role": "LOW_COST_SYMMETRIC_PILOT",
        "instance_ids": list(instance_ids),
        "seeds": list(seeds),
        "capacities_kwh": list(capacities),
        "public_power_kw": list(public_powers),
        "main_anchor": {"public_power_kw": 22.0, "capacity_kwh": 16.0},
        "vehicle_interpretation": (
            "experimental capacity-sensitivity vehicle; not a claim about "
            "the 77.28 kWh FOTON production vehicle"
        ),
        "power_roles": {
            "22.0": "Montoya/Froger absolute-power main scenario",
            "60.0": "unchanged China81 public-power sensitivity",
        },
        "curves": {name: asdict(spec) for name, spec in CURVES.items()},
        "full_battery_departure": True,
        "search": {
            "archive_per_view": ARCHIVE_PER_VIEW,
            "hgs_iterations_per_view": HGS_ITERATIONS_PER_VIEW,
            "wallclock_seconds_per_view": WALLCLOCK_SECONDS_PER_VIEW,
            "set_partitioning_seconds": SP_SECONDS,
        },
        "original_public_station_power_kw": original_public_power,
        "sources": [
            "Montoya et al. (2017), PDF pp.3-4 and 13",
            "Froger et al. (2019), author manuscript p.4 Fig.1",
            "Xiao (2021), p.18",
        ],
    }
    decision = {
        "status": "LOW_COST_SYMMETRIC_PILOT_COMPLETE",
        "expected_unit_count": (
            len(instance_ids)
            * len(seeds)
            * len(public_powers)
            * len(capacities)
            * len(CURVES)
        ),
        "unit_count": len(rows),
        "all_requested_units_recorded": len(rows)
        == len(instance_ids)
        * len(seeds)
        * len(public_powers)
        * len(capacities)
        * len(CURVES),
        "contains_28_kwh": any(row["capacity_kwh"] == 28.0 for row in rows),
        "feasible_unit_count": sum(bool(row["feasible"]) for row in rows),
        "independently_checked_unit_count": sum(
            bool(row["independent_check_completed"]) for row in rows
        ),
        "pairs_with_route_difference": sum(
            bool(item["route_hash_differs"]) for item in comparisons
        ),
        "pairs_with_feasibility_difference": sum(
            bool(item["feasibility_differs"]) for item in comparisons
        ),
        "m17_rows_entering_taper": sum(
            row["curve_id"] == M17_22KW_NORMAL_PWL.curve_id
            and int(row["taper_entered_session_count"]) > 0
            for row in rows
        ),
        "max_unit_elapsed_seconds": max(float(row["elapsed_seconds"]) for row in rows),
        "final_solution_station_capacity_conflicts": sum(
            int(row["station_capacity_conflict_count"]) for row in rows
        ),
        "linear_route_m17_recheck_feasible_pairs": sum(
            bool(item["linear_routes_m17_recheck_feasible"])
            for item in comparisons
        ),
        "linear_route_m17_recheck_station_capacity_conflicts": sum(
            int(item["linear_routes_m17_recheck_station_capacity_conflict_count"])
            for item in comparisons
        ),
        "pair_comparisons": comparisons,
    }
    _write_json(output_dir / "metadata.json", metadata)
    _write_json(output_dir / "decision.json", decision)
    (output_dir / "report.md").write_text(
        _report_text(metadata, decision, comparisons),
        encoding="utf-8",
    )
    hashes = {
        str(path.relative_to(output_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output_dir.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    _write_json(output_dir / "artifact_hashes.json", hashes)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-ids", nargs="+", default=list(DEFAULT_INSTANCE_IDS))
    parser.add_argument("--seeds", nargs="+", type=int, default=list(DEFAULT_SEEDS))
    parser.add_argument("--output-name", default="pilot06_seed1_symmetric")
    parser.add_argument("--capacities", nargs="+", type=float, default=list(CAPACITY_SCENARIOS_KWH))
    parser.add_argument(
        "--public-powers",
        nargs="+",
        type=float,
        default=[22.0],
    )
    args = parser.parse_args()
    instance_ids = tuple(str(value) for value in args.instance_ids)
    seeds = tuple(int(value) for value in args.seeds)
    capacities = tuple(float(value) for value in args.capacities)
    powers = tuple(float(value) for value in args.public_powers)
    for values, allowed, label in (
        (capacities, CAPACITY_SCENARIOS_KWH, "capacities"),
        (powers, PUBLIC_POWER_SCENARIOS_KW, "public powers"),
    ):
        if any(value not in allowed for value in values):
            parser.error(f"{label} must come from {allowed}")
    output_dir = Path(__file__).resolve().parent / args.output_name
    if not seeds or any(seed < 1 for seed in seeds):
        parser.error("seeds must be positive integers")
    rows = run_pilot(instance_ids, capacities, powers, seeds, output_dir)
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "unit_count": len(rows),
                "feasible_unit_count": sum(bool(row["feasible"]) for row in rows),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
