#!/usr/bin/env python3
"""Run Montoya FS/L1/L2/PL approximations on the approved E5 inputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PROTOTYPE = (
    REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
)
for entry in (REPO, REPO / "solver/src", PROTOTYPE):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import setp_solver.algorithms.resetp_alns.support.charging as charging_support
from route_pool_sp import run_hgs_route_pool_recombination
from setp_solver.charging_curve import (
    ChargingCurveSpec,
    PiecewiseChargingCurve,
    curve_from_parameters,
)
from setp_solver.check import BATTERY, STATION_CAPACITY, TIME_WINDOW, check_solution
from setp_solver.china81 import China81Bundle, load_china81_bundle
from setp_solver.cost import evaluate
from setp_solver.solution import Route, Solution

from baselines.china_e3_e7.e5_enroute_nonlinear_20260801.run_fixed_schedule_execution_replay import (
    ALLOWED_ACTION_CHANGES,
    frozen_action_hash,
    retime_action,
    route_hash,
)
from baselines.china_e3_e7.e5_enroute_nonlinear_20260801.runtime_overlay import (
    CAPACITY_SCENARIOS_KWH,
    M17_22KW_NORMAL_PWL,
    apply_runtime_overlay,
)


DEFAULT_INSTANCE_IDS = (
    "cn-prd-50c-01-V2-LOCATIONS",
    "cn-prd-100c-02-V2-LOCATIONS",
)
DEFAULT_SEEDS = (1, 2, 3)
DEFAULT_OUTPUT = HERE / "pilot12_montoya_fs_l1_l2_pl_20260801"
FLEET = REPO / "data/ChinaInstances/china81_finite_fleet_authority_v1_20260723"

REFERENCE_CAPACITY_KWH = 16.0
REFERENCE_POWER_KW = 22.0
M17_POINTS_H_KWH = (
    (0.0, 0.0),
    (0.62, 13.6),
    (0.77, 15.2),
    (1.01, 16.0),
)
L1_POWER_KW = 13.6 / 0.62
L2_POWER_KW = 16.0 / 1.01
FS_PUBLIC_SOC_CAP = 0.85

FS_FIRST_SEGMENT = ChargingCurveSpec(
    "M17_FS_FIRST_SEGMENT_TO_85PCT",
    (0.0, 1.0),
    (L1_POWER_KW / REFERENCE_POWER_KW,),
)
L1_FIRST_SEGMENT = ChargingCurveSpec(
    "M17_L1_FIRST_SEGMENT_LINEAR",
    (0.0, 1.0),
    (L1_POWER_KW / REFERENCE_POWER_KW,),
)
L2_ENDPOINT = ChargingCurveSpec(
    "M17_L2_ENDPOINT_LINEAR",
    (0.0, 1.0),
    (L2_POWER_KW / REFERENCE_POWER_KW,),
)
APPROXIMATIONS: dict[str, ChargingCurveSpec] = {
    "FS": FS_FIRST_SEGMENT,
    "L1": L1_FIRST_SEGMENT,
    "L2": L2_ENDPOINT,
    "PL": M17_22KW_NORMAL_PWL,
}

ARCHIVE_PER_VIEW = 2
HGS_ITERATIONS_PER_VIEW = 40
WALLCLOCK_SECONDS_PER_VIEW = 120.0
SP_SECONDS = 2.0

ROW_FIELDS = (
    "instance_id",
    "seed",
    "capacity_kwh",
    "public_charge_power_kw",
    "approximation",
    "curve_id",
    "departure_energy_kwh_configured",
    "public_station_energy_cap_kwh",
    "public_station_cap_compliant",
    "public_station_cap_violation_count",
    "optimization_status",
    "error_type",
    "error_message",
    "optimization_legal",
    "optimization_violation_count",
    "optimization_violation_types",
    "total_cost_cny",
    "route_count",
    "ev_route_count",
    "depot_charging_session_count",
    "public_charging_session_count",
    "public_charging_minutes_total",
    "max_public_charge_end_soc_pct",
    "complete_candidate_evaluations",
    "elapsed_seconds",
    "route_hash",
    "action_hash",
    "fixed_pl_execution_legal",
    "fixed_pl_violation_count",
    "fixed_pl_violation_types",
    "fixed_pl_battery_violation_count",
    "fixed_pl_time_window_violation_count",
    "fixed_pl_station_capacity_conflict_count",
    "fixed_pl_total_cost_cny",
    "fixed_pl_charging_minutes_total",
    "fixed_pl_duration_change_minutes",
    "fixed_pl_route_hash_unchanged",
    "fixed_pl_action_hash_unchanged",
    "fixed_pl_only_duration_and_curve_changed",
    "own_cost_minus_pl_cny",
    "own_cost_minus_pl_pct",
    "fixed_pl_cost_minus_pl_cny",
    "fixed_pl_cost_minus_pl_pct",
    "route_differs_from_pl",
    "route_count_minus_pl",
)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_hash(payload: Any) -> str:
    data = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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


def _bundle_for(
    base: China81Bundle,
    *,
    capacity_kwh: float,
    approximation: str,
) -> China81Bundle:
    bundle = apply_runtime_overlay(
        base,
        capacity_kwh=capacity_kwh,
        curve_id=M17_22KW_NORMAL_PWL.curve_id,
        public_charge_power_kw=REFERENCE_POWER_KW,
    )
    spec = APPROXIMATIONS[approximation]
    return replace(
        bundle,
        prices=replace(
            bundle.prices,
            charging_curve_id=spec.curve_id,
            charging_soc_breakpoints=spec.soc_breakpoints,
            charging_relative_powers=spec.relative_powers,
        ),
    )


def _public_station_cap_kwh(capacity_kwh: float, approximation: str) -> float:
    return (
        FS_PUBLIC_SOC_CAP * float(capacity_kwh)
        if approximation == "FS"
        else float(capacity_kwh)
    )


def _instance_with_ev_capacity(instance: Any, capacity_kwh: float) -> Any:
    vehicle_parameters = dict(instance.vehicle_parameters or {})
    vehicle_parameters["ev"] = replace(
        vehicle_parameters["ev"],
        battery_kwh=float(capacity_kwh),
    )
    return replace(instance, vehicle_parameters=vehicle_parameters)


@contextmanager
def _fs_station_cap(capacity_kwh: float, approximation: str):
    """Limit only public-station charge targets while retaining full departure."""

    if approximation != "FS":
        yield
        return

    public_cap = _public_station_cap_kwh(capacity_kwh, approximation)
    original = charging_support._best_station_insert

    def capped_station_insert(*args: Any, **kwargs: Any) -> Any:
        call_args = list(args)
        call_args[10] = _instance_with_ev_capacity(call_args[10], public_cap)
        result = original(*call_args, **kwargs)
        if result is not None:
            action = result[1]
            if float(action.end_energy_kwh or 0.0) > public_cap + 1.0e-9:
                raise RuntimeError("FS public-station charge exceeds its 85% cap")
        return result

    charging_support._best_station_insert = capped_station_insert
    try:
        yield
    finally:
        charging_support._best_station_insert = original


def _station_cap_violations(
    solution: Solution,
    bundle: China81Bundle,
    cap_kwh: float,
) -> list[Any]:
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    return [
        action
        for action in solution.charging_actions
        if nodes[action.station_id].node_type.lower() == "f"
        and float(action.end_energy_kwh or 0.0) > float(cap_kwh) + 1.0e-9
    ]


def _curve_for_action(action: Any, bundle: China81Bundle) -> PiecewiseChargingCurve:
    station = next(
        node for node in bundle.instance.nodes if node.node_id == action.station_id
    )
    power = (
        float(bundle.prices.depot_charge_power_kw)
        if station.node_type.lower() == "d"
        else float(station.charge_power_kw)
    )
    return curve_from_parameters(
        bundle.prices,
        capacity_kwh=bundle.instance.battery_capacity_kwh(
            fallback=bundle.prices.B_battery_kwh
        ),
        reference_power_kw=power,
    )


def _fixed_pl_replay(
    base: China81Bundle,
    solution: Solution,
    *,
    capacity_kwh: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    pl_bundle = _bundle_for(
        base,
        capacity_kwh=capacity_kwh,
        approximation="PL",
    )
    actions = [
        retime_action(action, _curve_for_action(action, pl_bundle))
        for action in solution.charging_actions
    ]
    replay = replace(solution, charging_actions=actions)
    route_unchanged = route_hash(replay) == route_hash(solution)
    action_unchanged = frozen_action_hash(replay) == frozen_action_hash(solution)
    only_allowed = all(
        {
            key
            for key, value in asdict(before).items()
            if value != asdict(after)[key]
        }
        <= ALLOWED_ACTION_CHANGES
        for before, after in zip(
            solution.charging_actions,
            replay.charging_actions,
            strict=True,
        )
    )
    violations = check_solution(replay, pl_bundle.instance, pl_bundle.prices)
    metrics = evaluate(
        replay,
        pl_bundle.instance,
        pl_bundle.time_profile,
        pl_bundle.prices,
    )
    source_minutes = sum(
        float(action.occupancy_minutes) for action in solution.charging_actions
    )
    replay_minutes = sum(
        float(action.occupancy_minutes) for action in replay.charging_actions
    )
    summary = {
        "fixed_pl_execution_legal": not violations,
        "fixed_pl_violation_count": len(violations),
        "fixed_pl_violation_types": "|".join(item.type for item in violations),
        "fixed_pl_battery_violation_count": sum(
            item.type == BATTERY for item in violations
        ),
        "fixed_pl_time_window_violation_count": sum(
            item.type == TIME_WINDOW for item in violations
        ),
        "fixed_pl_station_capacity_conflict_count": sum(
            item.type == STATION_CAPACITY for item in violations
        ),
        "fixed_pl_total_cost_cny": float(metrics["total_cost"]),
        "fixed_pl_charging_minutes_total": replay_minutes,
        "fixed_pl_duration_change_minutes": replay_minutes - source_minutes,
        "fixed_pl_route_hash_unchanged": route_unchanged,
        "fixed_pl_action_hash_unchanged": action_unchanged,
        "fixed_pl_only_duration_and_curve_changed": only_allowed,
    }
    detail = {
        "summary": summary,
        "violations": [asdict(item) for item in violations],
        "cost_breakdown": metrics,
        "solution": asdict(replay),
    }
    return summary, detail


def _empty_row(
    instance_id: str,
    seed: int,
    capacity_kwh: float,
    approximation: str,
) -> dict[str, Any]:
    row = {field: "" for field in ROW_FIELDS}
    row.update(
        {
            "instance_id": instance_id,
            "seed": seed,
            "capacity_kwh": capacity_kwh,
            "public_charge_power_kw": REFERENCE_POWER_KW,
            "approximation": approximation,
            "curve_id": APPROXIMATIONS[approximation].curve_id,
            "departure_energy_kwh_configured": capacity_kwh,
            "public_station_energy_cap_kwh": _public_station_cap_kwh(
                capacity_kwh,
                approximation,
            ),
            "optimization_status": "ERROR",
        }
    )
    return row


def _run_unit(task: tuple[str, int, float, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    instance_id, seed, capacity_kwh, approximation = task
    row = _empty_row(instance_id, seed, capacity_kwh, approximation)
    try:
        base = load_china81_bundle(REPO, instance_id)
        bundle = _bundle_for(
            base,
            capacity_kwh=capacity_kwh,
            approximation=approximation,
        )
        with _fs_station_cap(capacity_kwh, approximation):
            run = run_hgs_route_pool_recombination(
                bundle,
                _load_initial(instance_id),
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
        station_cap_violations = _station_cap_violations(
            run.solution,
            bundle,
            _public_station_cap_kwh(capacity_kwh, approximation),
        )
        metrics = evaluate(
            run.solution,
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
        )
        nodes = {node.node_id: node for node in bundle.instance.nodes}
        public_actions = [
            action
            for action in run.solution.charging_actions
            if nodes[action.station_id].node_type.lower() == "f"
        ]
        depot_actions = [
            action
            for action in run.solution.charging_actions
            if nodes[action.station_id].node_type.lower() == "d"
        ]
        end_soc = [
            100.0 * float(action.end_energy_kwh) / capacity_kwh
            for action in public_actions
            if action.end_energy_kwh is not None
        ]
        replay_summary, replay_detail = _fixed_pl_replay(
            base,
            run.solution,
            capacity_kwh=capacity_kwh,
        )
        row.update(
            {
                "optimization_status": "SUCCESS",
                "public_station_cap_compliant": not station_cap_violations,
                "public_station_cap_violation_count": len(station_cap_violations),
                "optimization_legal": not violations and not station_cap_violations,
                "optimization_violation_count": len(violations)
                + len(station_cap_violations),
                "optimization_violation_types": "|".join(
                    [
                        *(item.type for item in violations),
                        *(
                            "PUBLIC_STATION_SOC_CAP"
                            for _ in station_cap_violations
                        ),
                    ]
                ),
                "total_cost_cny": float(metrics["total_cost"]),
                "route_count": len(run.solution.routes),
                "ev_route_count": sum(
                    route.vehicle_type.lower() == "ev"
                    for route in run.solution.routes
                ),
                "depot_charging_session_count": len(depot_actions),
                "public_charging_session_count": len(public_actions),
                "public_charging_minutes_total": sum(
                    float(action.occupancy_minutes) for action in public_actions
                ),
                "max_public_charge_end_soc_pct": max(end_soc, default=0.0),
                "complete_candidate_evaluations": int(
                    run.stats["complete_candidate_evaluation_attempts"]
                ),
                "elapsed_seconds": float(run.elapsed_seconds),
                "route_hash": route_hash(run.solution),
                "action_hash": _json_hash(
                    [asdict(action) for action in run.solution.charging_actions]
                ),
                **replay_summary,
            }
        )
        detail = {
            "row": row,
            "optimization_violations": [asdict(item) for item in violations],
            "public_station_cap_violations": [
                asdict(item) for item in station_cap_violations
            ],
            "optimization_cost_breakdown": metrics,
            "completion_activity": run.completion.activity,
            "search_stats": run.stats,
            "solution": asdict(run.solution),
            "fixed_pl_execution": replay_detail,
        }
        return row, detail
    except Exception as exc:  # noqa: BLE001 - every failed unit stays in raw_runs.csv
        row.update(
            {
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
        )
        return row, {"row": row}


def _paired_fields(rows: list[dict[str, Any]]) -> None:
    groups: dict[tuple[str, int, float], dict[str, dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row["instance_id"]),
            int(row["seed"]),
            float(row["capacity_kwh"]),
        )
        groups.setdefault(key, {})[str(row["approximation"])] = row
    for group in groups.values():
        pl = group.get("PL")
        if pl is None or pl["optimization_status"] != "SUCCESS":
            continue
        pl_cost = float(pl["total_cost_cny"])
        pl_execution_cost = float(pl["fixed_pl_total_cost_cny"])
        for row in group.values():
            if row["optimization_status"] != "SUCCESS":
                continue
            delta = float(row["total_cost_cny"]) - pl_cost
            execution_delta = (
                float(row["fixed_pl_total_cost_cny"]) - pl_execution_cost
            )
            row["own_cost_minus_pl_cny"] = delta
            row["own_cost_minus_pl_pct"] = 100.0 * delta / pl_cost
            row["fixed_pl_cost_minus_pl_cny"] = execution_delta
            row["fixed_pl_cost_minus_pl_pct"] = (
                100.0 * execution_delta / pl_execution_cost
            )
            row["route_differs_from_pl"] = row["route_hash"] != pl["route_hash"]
            row["route_count_minus_pl"] = int(row["route_count"]) - int(
                pl["route_count"]
            )


def _mean(values: Sequence[float]) -> float | None:
    return None if not values else sum(values) / len(values)


def _decision(rows: list[dict[str, Any]], *, expected_unit_count: int) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for approximation in APPROXIMATIONS:
        group = [row for row in rows if row["approximation"] == approximation]
        successful = [row for row in group if row["optimization_status"] == "SUCCESS"]
        deltas = [float(row["own_cost_minus_pl_pct"]) for row in successful]
        execution_deltas = [
            float(row["fixed_pl_cost_minus_pl_pct"]) for row in successful
        ]
        summaries[approximation] = {
            "recorded_units": len(group),
            "successful_units": len(successful),
            "optimization_legal_units": sum(
                bool(row["optimization_legal"]) for row in successful
            ),
            "fixed_pl_execution_legal_units": sum(
                bool(row["fixed_pl_execution_legal"]) for row in successful
            ),
            "fixed_pl_execution_illegal_units": sum(
                not bool(row["fixed_pl_execution_legal"]) for row in successful
            ),
            "routes_differing_from_pl": sum(
                bool(row["route_differs_from_pl"]) for row in successful
            ),
            "public_station_cap_violation_count": sum(
                int(row["public_station_cap_violation_count"])
                for row in successful
            ),
            "max_public_charge_end_soc_pct": max(
                (
                    float(row["max_public_charge_end_soc_pct"])
                    for row in successful
                ),
                default=0.0,
            ),
            "depot_charging_session_count": sum(
                int(row["depot_charging_session_count"])
                for row in successful
            ),
            "mean_own_cost_minus_pl_pct": _mean(deltas),
            "min_own_cost_minus_pl_pct": min(deltas, default=None),
            "max_own_cost_minus_pl_pct": max(deltas, default=None),
            "mean_fixed_pl_cost_minus_pl_pct": _mean(execution_deltas),
            "min_fixed_pl_cost_minus_pl_pct": min(execution_deltas, default=None),
            "max_fixed_pl_cost_minus_pl_pct": max(execution_deltas, default=None),
        }
    return {
        "status": "FOUR_MONTOYA_APPROXIMATIONS_COMPLETE",
        "formal_result": False,
        "requested_approximations": ["FS", "L1", "L2", "PL"],
        "executed_approximations": list(APPROXIMATIONS),
        "not_run_approximations": {},
        "expected_executed_unit_count": expected_unit_count,
        "recorded_unit_count": len(rows),
        "error_unit_count": sum(row["optimization_status"] == "ERROR" for row in rows),
        "all_rows_retained": len(rows) == expected_unit_count,
        "all_fixed_replays_kept_routes": all(
            bool(row["fixed_pl_route_hash_unchanged"])
            for row in rows
            if row["optimization_status"] == "SUCCESS"
        ),
        "all_fixed_replays_kept_action_decisions": all(
            bool(row["fixed_pl_action_hash_unchanged"])
            for row in rows
            if row["optimization_status"] == "SUCCESS"
        ),
        "all_public_station_caps_respected": all(
            bool(row["public_station_cap_compliant"])
            for row in rows
            if row["optimization_status"] == "SUCCESS"
        ),
        "summaries": summaries,
    }


def _report(metadata: Mapping[str, Any], decision: Mapping[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# E5 Montoya 四种充电近似小试",
        "",
        "Montoya 等（2017）第2--4页定义 FS、L1、L2 与分段线性近似；其中对 FS 的一般说明是只使用第一段、充到约 0.8Q。本文所用 22 kW、16 kWh 曲线的第一折点实际是 13.6 kWh，即 85%。第13--15页分别优化四种近似，并把线性方案放回分段线性曲线检查实际可行性。本次在获批的两个 China81 算例上照这个比较顺序执行。",
        "",
        f"FS 与 L1 都采用首段斜率 13.6/0.62={L1_POWER_KW:.12f} kW；FS 另把公共站充电上限设为电池容量的85%，车辆仍以100%电量从车场出发。L2 采用首尾连线斜率 16/1.01={L2_POWER_KW:.12f} kW；PL 使用现有 M17 三段曲线。每种近似独立优化，随后固定路线、车型、充电站、开始时刻和充电量，只把占用时间改按 PL 计算。",
        "",
        "16 kWh 时，FS 的车场出发电量为16 kWh、公共站上限为13.6 kWh；其余容量按同一85%断点同比例换算。该上限只作用于途中公共站，不改变电池容量、车场离场电量或其他三种近似。",
        "",
        "## 全矩阵汇总",
        "",
        "| 近似 | 记录单元 | 自身优化合法 | 固定方案按PL执行合法 | 执行不合法 | 路线不同于PL | 公共站最高SOC% | 站点上限违约 | 自身成本相对PL均值% | 按PL执行成本相对PL均值% | 执行最小% | 执行最大% |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for approximation in APPROXIMATIONS:
        item = decision["summaries"][approximation]
        lines.append(
            f"| {approximation} | {item['recorded_units']} | "
            f"{item['optimization_legal_units']} | "
            f"{item['fixed_pl_execution_legal_units']} | "
            f"{item['fixed_pl_execution_illegal_units']} | "
            f"{item['routes_differing_from_pl']} | "
            f"{item['max_public_charge_end_soc_pct']:.6f} | "
            f"{item['public_station_cap_violation_count']} | "
            f"{item['mean_own_cost_minus_pl_pct']:.6f} | "
            f"{item['mean_fixed_pl_cost_minus_pl_pct']:.6f} | "
            f"{item['min_fixed_pl_cost_minus_pl_pct']:.6f} | "
            f"{item['max_fixed_pl_cost_minus_pl_pct']:.6f} |"
        )
    lines.extend(
        [
            "",
            "## 16 kWh 主参数逐单元",
            "",
            "| 算例 | 种子 | 近似 | 自身成本(元) | 自身相对PL% | 按PL执行相对PL% | 路线不同 | 按PL执行合法 | 执行违约 |",
            "|---|---:|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    main_rows = [
        row
        for row in rows
        if float(row["capacity_kwh"]) == REFERENCE_CAPACITY_KWH
    ]
    for row in main_rows:
        lines.append(
            f"| {row['instance_id']} | {row['seed']} | {row['approximation']} | "
            f"{float(row['total_cost_cny']):.6f} | "
            f"{float(row['own_cost_minus_pl_pct']):+.6f} | "
            f"{float(row['fixed_pl_cost_minus_pl_pct']):+.6f} | "
            f"{int(bool(row['route_differs_from_pl']))} | "
            f"{int(bool(row['fixed_pl_execution_legal']))} | "
            f"{row['fixed_pl_violation_types'] or '-'} |"
        )
    lines.extend(
        [
            "",
            "`raw_runs.csv` 保留两个算例、3个种子、5个容量和4种近似的全部记录；未按方向删行。自身成本是本项目完整运营成本，不是 Montoya 的“行驶时间+充电时间”目标值。",
            "",
            "与 pilot07 的区别：pilot07 的旧复核清空充电动作后重新选择时刻，制造了伪冲突；本次固定执行复核不重新排充电，只改变曲线决定的占用时间。",
            "",
            f"搜索设置：{json.dumps(metadata['search'], ensure_ascii=False)}",
        ]
    )
    return "\n".join(lines) + "\n"


def run(
    output: Path,
    *,
    instance_ids: Sequence[str],
    seeds: Sequence[int],
    capacities: Sequence[float],
    workers: int,
) -> None:
    if output.exists():
        raise RuntimeError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    units = output / "units"
    units.mkdir()
    tasks = [
        (str(instance_id), int(seed), float(capacity), approximation)
        for instance_id in instance_ids
        for seed in seeds
        for capacity in capacities
        for approximation in APPROXIMATIONS
    ]
    results: list[tuple[dict[str, Any], dict[str, Any]]] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run_unit, task): task for task in tasks}
        for index, future in enumerate(as_completed(futures), start=1):
            row, detail = future.result()
            results.append((row, detail))
            print(f"[{index}/{len(tasks)}] {row['instance_id']} seed={row['seed']} B={row['capacity_kwh']} {row['approximation']} {row['optimization_status']}", flush=True)

    results.sort(
        key=lambda item: (
            item[0]["instance_id"],
            int(item[0]["seed"]),
            float(item[0]["capacity_kwh"]),
            ("FS", "L1", "L2", "PL").index(str(item[0]["approximation"])),
        )
    )
    rows = [item[0] for item in results]
    _paired_fields(rows)
    for row, detail in results:
        detail["row"] = row
        unit_name = (
            f"{row['instance_id']}__seed{row['seed']}__B{float(row['capacity_kwh']):g}"
            f"__{row['approximation']}.json"
        )
        _write_json(units / unit_name, detail)

    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ROW_FIELDS))
        writer.writeheader()
        writer.writerows(rows)

    metadata = {
        "task_id": "E5-MONTOYA-FS-4APPROX-01",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "evidence_role": "LOW_COST_SYMMETRIC_PILOT",
        "run_command": (
            "OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 "
            "VECLIB_MAXIMUM_THREADS=1 PYTHONPATH=solver/src:models/src:. "
            "build/python_envs/pyvrp-hgs-0.12.2/bin/python "
            "baselines/china_e3_e7/e5_enroute_nonlinear_20260801/"
            "run_montoya_fs_approximations.py "
            f"--output {output} --workers {workers}"
        ),
        "instance_ids": list(instance_ids),
        "seeds": list(seeds),
        "capacities_kwh": list(capacities),
        "public_charge_power_kw": REFERENCE_POWER_KW,
        "approximations": {
            key: asdict(spec) for key, spec in APPROXIMATIONS.items()
        },
        "published_reference_points_h_kwh": M17_POINTS_H_KWH,
        "parameter_derivation": {
            "L1_power_kw": L1_POWER_KW,
            "L1_formula": "13.6 kWh / 0.62 h",
            "L2_power_kw": L2_POWER_KW,
            "L2_formula": "16 kWh / 1.01 h",
            "FS_public_station_soc_cap": FS_PUBLIC_SOC_CAP,
            "FS_public_station_energy_cap_formula": (
                "0.85 * capacity_kwh; 13.6 kWh when capacity_kwh=16"
            ),
            "FS_departure_energy_formula": "1.00 * capacity_kwh",
        },
        "literature": [
            {
                "item": "Montoya et al. (2017)",
                "zotero_item_key": "GJB373Y4",
                "pages": "PDF 2-4, 13-15",
                "use": (
                    "FS generic wording around 0.8Q; actual 22 kW curve first "
                    "breakpoint 13.6/16=85%; full-departure assumption; four "
                    "independent optimizations and PL execution recheck"
                ),
            },
            {
                "item": "Froger et al. author manuscript",
                "page": "PDF 4, Figure 1",
                "use": "exact 22 kW normal-curve points already used by M17",
            },
        ],
        "search": {
            "archive_per_view": ARCHIVE_PER_VIEW,
            "hgs_iterations_per_view": HGS_ITERATIONS_PER_VIEW,
            "wallclock_seconds_per_view": WALLCLOCK_SECONDS_PER_VIEW,
            "set_partitioning_seconds": SP_SECONDS,
            "workers": workers,
        },
        "fixed_pl_replay": {
            "frozen": [
                "routes",
                "vehicle_type",
                "station_id",
                "charge_start_second",
                "charge_day_offset",
                "energy_kwh",
                "start_energy_kwh",
                "end_energy_kwh",
            ],
            "changed": ["occupancy_minutes", "charging_curve_id"],
        },
        "fs_isolated_implementation": {
            "scope": "public charging-station target only",
            "unchanged": [
                "nominal battery capacity",
                "depot departure energy",
                "customer data",
                "time windows",
                "fleet caps",
                "RMB objective",
            ],
        },
        "history_difference": (
            "pilot07 optimized L100 and PL but its old recheck cleared and "
            "rescheduled actions. pilot08 overturned that strong claim. This "
            "pilot independently optimizes FS/L1/L2/PL and keeps every fixed "
            "charging decision during PL execution replay."
        ),
        "runner_sha256": _file_hash(Path(__file__)),
        "source_sha256": {
            "runtime_overlay.py": _file_hash(HERE / "runtime_overlay.py"),
            "charging_curve.py": _file_hash(REPO / "solver/src/setp_solver/charging_curve.py"),
            "cost.py": _file_hash(REPO / "solver/src/setp_solver/cost.py"),
            "check.py": _file_hash(REPO / "solver/src/setp_solver/check.py"),
            "search/evaluation.py": _file_hash(REPO / "solver/src/setp_solver/search/evaluation.py"),
        },
    }
    decision = _decision(rows, expected_unit_count=len(tasks))
    _write_json(output / "metadata.json", metadata)
    _write_json(output / "decision.json", decision)
    (output / "report.md").write_text(
        _report(metadata, decision, rows), encoding="utf-8"
    )
    hashes = {
        str(path.relative_to(output)): _file_hash(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    }
    _write_json(output / "artifact_hashes.json", hashes)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--instance-ids", nargs="+", default=list(DEFAULT_INSTANCE_IDS))
    parser.add_argument("--seeds", nargs="+", type=int, default=list(DEFAULT_SEEDS))
    parser.add_argument(
        "--capacities",
        nargs="+",
        type=float,
        default=list(CAPACITY_SCENARIOS_KWH),
    )
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    capacities = [float(value) for value in args.capacities]
    if any(value not in CAPACITY_SCENARIOS_KWH for value in capacities):
        parser.error(f"capacities must come from {CAPACITY_SCENARIOS_KWH}")
    if args.workers < 1:
        parser.error("workers must be positive")
    run(
        args.output.resolve(),
        instance_ids=args.instance_ids,
        seeds=args.seeds,
        capacities=capacities,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
