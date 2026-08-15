#!/usr/bin/env python3
"""Fixed-witness Step C for the 2026-08-11 mechanism validation.

This script does not invoke a search algorithm.  It replays the saved health
witness routes, computes exact EV traction energy for each physical vehicle,
and calls the four registered charge-timing policies on an identical
return-to-next-dispatch charging window.  It also compares each witnessed
daily distance with the three pre-registered CV/EV break-even distances.
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
import subprocess
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from setp_solver.charge_timing import select_charge_timing_start
from setp_solver.charging_curve import (
    curve_for_charging_node,
    spec_for_charging_node,
)
from setp_solver.cost import (
    charging_action_electricity_cost,
    charging_action_emissions_kg,
    evaluate,
    time_profile_rows_for_node,
)
from setp_solver.private_instance_rebuild_20260811 import (
    INSTANCE_ID,
    load_private_instance_rebuild,
)
from setp_solver.solution import ChargingAction, Route, Solution


CARBON_PRICE_CNY_PER_KG = 0.07502
POLICIES = ("asap", "cost_min", "carbon_min", "cost_plus_carbon")
THRESHOLDS_KM = (
    ("valley", 68.1),
    ("flat", 86.8),
    ("peak", 125.5),
)
PROTECTED = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    fields: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _clock(minute: float) -> str:
    day = int(minute // 1440.0)
    within = minute - day * 1440.0
    hour = int(within // 60.0)
    minute_part = int(round(within - hour * 60.0))
    if minute_part == 60:
        hour += 1
        minute_part = 0
    prefix = "" if day == 0 else f"D+{day} "
    return f"{prefix}{hour:02d}:{minute_part:02d}"


def _percent_change(value: float, baseline: float) -> float:
    return 100.0 * (float(value) - float(baseline)) / float(baseline)


def _git_commit(repo_root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _route_as_ev(row: Mapping[str, str]) -> Route:
    return Route(
        vehicle_id=str(row["route_vehicle_id"]).replace("CV_", "EV_", 1),
        vehicle_type="ev",
        home_depot_id=str(row["depot_id"]),
        node_sequence=[
            str(row["depot_id"]),
            *str(row["customers"]).split("|"),
            str(row["depot_id"]),
        ],
    )


def _group_by_vehicle(
    rows: Iterable[Mapping[str, str]],
) -> dict[str, list[Mapping[str, str]]]:
    grouped: dict[str, list[Mapping[str, str]]] = {}
    for row in rows:
        grouped.setdefault(str(row["physical_vehicle_id"]), []).append(row)
    return {
        vehicle: sorted(items, key=lambda item: float(item["departure_minute"]))
        for vehicle, items in sorted(grouped.items())
    }


def _render_report(
    charge_rows: Sequence[Mapping[str, Any]],
    threshold_rows: Sequence[Mapping[str, Any]],
    protected_hashes: Mapping[str, str],
) -> str:
    vehicles = sorted({str(row["physical_vehicle_id"]) for row in charge_rows})
    return_by_vehicle = {
        vehicle: float(
            next(
                row["final_return_minute"]
                for row in charge_rows
                if row["physical_vehicle_id"] == vehicle
            )
        )
        for vehicle in vehicles
    }
    returns = list(return_by_vehicle.values())
    favourable = sum(880.0 <= value <= 1040.0 for value in returns)
    at_or_after_1900 = sum(value >= 1140.0 - 1.0e-9 for value in returns)
    summaries: dict[str, dict[str, float]] = {}
    for policy in POLICIES:
        selected = [row for row in charge_rows if row["policy"] == policy]
        summaries[policy] = {
            "electricity_cost_cny": sum(float(row["electricity_cost_cny"]) for row in selected),
            "emissions_kg": sum(float(row["emissions_kgco2e"]) for row in selected),
            "monetary_total_cny": sum(float(row["monetary_total_cny"]) for row in selected),
        }
    baseline = summaries["asap"]

    lines = [
        "STEP_C_DONE",
        "",
        "# 新算例三机制验证 v3（2026-08-11）",
        "",
        "## 当前状态",
        "",
        "`FACT`：第一步 C 已完成；本步只复算冻结健康见证路线，没有启动搜索。第二步接线和第三步短测尚未开始。",
        "",
        "## 本步只查的两个问题",
        "",
        "1. `FACT`：冻结见证车队的实际返场时刻与可充窗口，是否让四种登记充电策略产生可观察差异。",
        "2. `FACT`：按每辆车的实际日里程和三个冻结临界点，成本最优车型是否与见证实际车型一致。",
        "",
        "## 复算口径",
        "",
        f"- `FACT`：算例为 `{INSTANCE_ID}`；输入路线为 `solver/reports/instance_rebuild_20260811/health_witness_routes.csv`。",
        "- `FACT`：每辆见证车均保持原客户顺序、车场和趟次不变；仅为充电复算把相同路线按 EV 道路/能耗合同逐弧重放。",
        "- `FACT`：充电量等于该物理车辆当天精确牵引耗电；起止 SOC 为“当天耗电后的 SOC → 77.28 kWh 满电”。",
        "- `FACT`：可充窗口采用仓库既有 S0 定义，即“当天最后返场—次日首次出车”；本算例次日首次出车为 08:00。起充时刻由 `charge_timing.py` 的四种登记策略直接选择。",
        "- `FACT`：车场使用登记的 `M17_22KW_NORMAL_PWL` 非线性 22 kW 曲线；四臂的路线、电量、曲线和窗口完全相同。",
        f"- `FACT`：货币总账＝电费＋{CARBON_PRICE_CNY_PER_KG:.5f} 元/kg × 充电排放。",
        "",
        "## 全车队实际返场时刻分布",
        "",
        f"`FACT`：8 辆车最终返场范围为 **{_clock(min(returns))}–{_clock(max(returns))}**，中位数 **{_clock(statistics.median(returns))}**；{favourable}/8 辆落在预注册先验的 14:40–17:20 区间，{at_or_after_1900}/8 辆在 19:00 或之后返场。",
        "",
        "| 物理车 | 车场 | 趟数 | 日里程 km | 最终返场 | 可充窗口 | 充电量 kWh | 非线性充电时长 min |",
        "|---|---|---:|---:|---:|---|---:|---:|",
    ]
    for vehicle in vehicles:
        row = next(row for row in charge_rows if row["physical_vehicle_id"] == vehicle)
        lines.append(
            "| {physical_vehicle_id} | {depot_id} | {trip_count} | {daily_distance_km:.3f} | {return_clock} | {window_start_clock}–{window_end_clock} | {charge_energy_kwh:.3f} | {charge_duration_minute:.3f} |".format(
                **row
            )
        )

    lines.extend(
        [
            "",
            "## 四种充电策略：全车队货币总账",
            "",
            "| 策略 | 电费 元 | 排放 kgCO2e | 货币总账 元 | 相对 asap 总账 | 相对 asap 排放 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for policy in POLICIES:
        item = summaries[policy]
        lines.append(
            f"| `{policy}` | {item['electricity_cost_cny']:.3f} | {item['emissions_kg']:.3f} | {item['monetary_total_cny']:.3f} | {_percent_change(item['monetary_total_cny'], baseline['monetary_total_cny']):+.2f}% | {_percent_change(item['emissions_kg'], baseline['emissions_kg']):+.2f}% |"
        )

    lines.extend(
        [
            "",
            "`FACT`：主口径按货币总账读取；排放列保留为机制诊断，不把结果摆成两个目标让读者选点。",
            "",
            "## 四种策略逐车结果",
            "",
            "| 物理车 | 策略 | 起充 | 充完 | 电费 元 | 排放 kgCO2e | 货币总账 元 |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in charge_rows:
        lines.append(
            "| {physical_vehicle_id} | `{policy}` | {selected_start_clock} | {selected_end_clock} | {electricity_cost_cny:.3f} | {emissions_kgco2e:.3f} | {monetary_total_cny:.3f} |".format(
                **row
            )
        )

    lines.extend(
        [
            "",
            "## 油电临界日里程复算",
            "",
            "`FACT`：判定规则为日里程低于临界值选 CV、高于临界值选 EV；见证路线实际车辆均为 CV，因此下表同时报告不一致项。",
            "",
            "| 物理车 | 日里程 km | 实际车型 | 谷 68.1 km | 平 86.8 km | 峰 125.5 km |",
            "|---|---:|---|---|---|---|",
        ]
    )
    for vehicle in vehicles:
        selected = [row for row in threshold_rows if row["physical_vehicle_id"] == vehicle]
        by_scenario = {str(row["tariff_scenario"]): row for row in selected}
        distance = float(selected[0]["daily_distance_km"])
        cells = []
        for scenario in ("valley", "flat", "peak"):
            row = by_scenario[scenario]
            marker = "一致" if int(row["matches_witness"]) else "不一致"
            cells.append(f"{row['cost_optimal_vehicle_type'].upper()}（{marker}）")
        lines.append(
            f"| {vehicle} | {distance:.3f} | CV | {cells[0]} | {cells[1]} | {cells[2]} |"
        )

    lines.extend(["", "`FACT`：三个时段下的成本最优车型数量如下：", ""])
    for scenario, threshold in THRESHOLDS_KM:
        selected = [row for row in threshold_rows if row["tariff_scenario"] == scenario]
        ev_count = sum(row["cost_optimal_vehicle_type"] == "ev" for row in selected)
        lines.append(
            f"- `{scenario}`（临界 {threshold:.1f} km）：EV {ev_count}/8，CV {8 - ev_count}/8；与全 CV 见证不一致 {ev_count}/8。"
        )

    lines.extend(
        [
            "",
            "## 证据边界与下一步",
            "",
            "- `FACT`：本步是固定见证路线复算，不是最优车队或搜索结果。",
            "- `INFERENCE`：返场分布没有退化为“多数 19:00 才收车”，但只有 2/8 辆落在旧单车先验的双向有利区间；是否能在完整候选中形成系统级双向改善，须以后续短测读取，不能由本步替代。",
            "- `FACT`：下一步只做用户批准的最小接线；利润公平和 pi0 在本轮保持关闭。",
            "",
            "## 原始产物",
            "",
            "- `raw_runs.csv`：本步全部逐车充电与车型阈值原始行。",
            "- `charge_strategy_by_vehicle.csv`：四策略逐车明细。",
            "- `vehicle_threshold_by_vehicle.csv`：三个临界时段逐车判定。",
            "- `metadata.json`、`decision.json`、`artifact_hashes.json`：运行身份、当前状态与产物哈希。",
            "",
            "## 受保护文件哈希",
            "",
        ]
    )
    for path, digest in protected_hashes.items():
        lines.append(f"- `{path}`：`{digest}`")
    return "\n".join(lines) + "\n"


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    input_path = (
        repo_root
        / "solver/reports/instance_rebuild_20260811/health_witness_routes.csv"
    )
    report_root = repo_root / "solver/reports/mechanism_validation_v3_20260811"
    witness_rows = _read_csv(input_path)
    grouped = _group_by_vehicle(witness_rows)
    bundle = load_private_instance_rebuild(repo_root)
    if not grouped:
        raise ValueError("health witness has no physical vehicles")
    if not abs(float(bundle.prices.carbon_price) - CARBON_PRICE_CNY_PER_KG) < 1.0e-12:
        raise ValueError("runtime carbon price disagrees with P43-H")

    charge_rows: list[dict[str, Any]] = []
    threshold_rows: list[dict[str, Any]] = []
    next_dispatch_minute = 24.0 * 60.0 + 8.0 * 60.0
    battery_capacity = bundle.instance.battery_capacity_kwh(
        fallback=float(bundle.prices.B_battery_kwh)
    )

    for physical_vehicle_id, rows in grouped.items():
        routes = [_route_as_ev(row) for row in rows]
        exact_ev = evaluate(
            Solution(routes=routes),
            bundle.instance,
            bundle.time_profile,
            bundle.prices,
            carbon_quota_kg=0.0,
        )
        energy = float(exact_ev["ev_drive_kwh"])
        if energy > battery_capacity + 1.0e-9:
            raise ValueError(
                f"{physical_vehicle_id} daily energy exceeds one battery: "
                f"{energy} > {battery_capacity}"
            )
        depot_id = str(rows[0]["depot_id"])
        station = bundle.instance.nodes[bundle.instance.node_index[depot_id]]
        spec = spec_for_charging_node(
            bundle.prices,
            node_type=station.node_type,
        )
        curve = curve_for_charging_node(
            bundle.prices,
            node_type=station.node_type,
            capacity_kwh=battery_capacity,
            reference_power_kw=float(bundle.prices.depot_charge_power_kw),
        )
        start_energy = battery_capacity - energy
        duration_second = curve.duration_seconds(start_energy, battery_capacity)
        final_return_minute = max(float(row["return_minute"]) for row in rows)
        earliest_start_second = final_return_minute * 60.0
        latest_start_second = next_dispatch_minute * 60.0 - duration_second
        if latest_start_second < earliest_start_second - 1.0e-9:
            raise ValueError(
                f"{physical_vehicle_id} cannot recharge before next dispatch"
            )
        profile = time_profile_rows_for_node(
            bundle.instance,
            depot_id,
            bundle.time_profile,
        )
        action = ChargingAction(
            vehicle_id=routes[-1].vehicle_id,
            station_id=depot_id,
            energy_kwh=energy,
            occupancy_minutes=duration_second / 60.0,
            charge_start_second=earliest_start_second,
            start_energy_kwh=start_energy,
            end_energy_kwh=battery_capacity,
            charging_curve_id=spec.curve_id,
        )
        common = {
            "evidence_label": "FACT",
            "instance_id": INSTANCE_ID,
            "physical_vehicle_id": physical_vehicle_id,
            "actual_witness_vehicle_type": "cv",
            "depot_id": depot_id,
            "trip_count": len(rows),
            "daily_distance_km": sum(float(row["distance_km"]) for row in rows),
            "final_return_minute": final_return_minute,
            "return_clock": _clock(final_return_minute),
            "window_start_minute": final_return_minute,
            "window_start_clock": _clock(final_return_minute),
            "window_end_minute": next_dispatch_minute,
            "window_end_clock": _clock(next_dispatch_minute),
            "latest_start_minute": latest_start_second / 60.0,
            "latest_start_clock": _clock(latest_start_second / 60.0),
            "charge_energy_kwh": energy,
            "start_energy_kwh": start_energy,
            "end_energy_kwh": battery_capacity,
            "charging_curve_id": spec.curve_id,
            "charge_duration_minute": duration_second / 60.0,
        }
        for policy in POLICIES:
            selected_start = select_charge_timing_start(
                action,
                earliest_start_second=earliest_start_second,
                latest_start_second=latest_start_second,
                instance=bundle.instance,
                carbon_profile=profile,
                prices=bundle.prices,
                charge_timing_policy=policy,
            )
            selected_action = replace(
                action,
                charge_start_second=float(selected_start),
            )
            electricity_cost = charging_action_electricity_cost(
                selected_action,
                bundle.instance,
                profile,
                bundle.prices,
            )
            emissions = charging_action_emissions_kg(
                selected_action,
                bundle.instance,
                profile,
                bundle.prices,
            )
            charge_rows.append(
                {
                    **common,
                    "policy": policy,
                    "selected_start_minute": selected_start / 60.0,
                    "selected_start_clock": _clock(selected_start / 60.0),
                    "selected_end_minute": (selected_start + duration_second) / 60.0,
                    "selected_end_clock": _clock(
                        (selected_start + duration_second) / 60.0
                    ),
                    "electricity_cost_cny": electricity_cost,
                    "emissions_kgco2e": emissions,
                    "carbon_price_cny_per_kg": CARBON_PRICE_CNY_PER_KG,
                    "carbon_cost_cny": CARBON_PRICE_CNY_PER_KG * emissions,
                    "monetary_total_cny": (
                        electricity_cost + CARBON_PRICE_CNY_PER_KG * emissions
                    ),
                }
            )

        for scenario, threshold in THRESHOLDS_KM:
            optimal = (
                "ev"
                if float(common["daily_distance_km"]) > threshold + 1.0e-9
                else "cv"
            )
            threshold_rows.append(
                {
                    "evidence_label": "FACT",
                    "instance_id": INSTANCE_ID,
                    "physical_vehicle_id": physical_vehicle_id,
                    "actual_witness_vehicle_type": "cv",
                    "depot_id": depot_id,
                    "trip_count": len(rows),
                    "daily_distance_km": common["daily_distance_km"],
                    "tariff_scenario": scenario,
                    "critical_daily_km": threshold,
                    "cost_optimal_vehicle_type": optimal,
                    "matches_witness": int(optimal == "cv"),
                }
            )

    report_root.mkdir(parents=True, exist_ok=True)
    _write_csv(
        report_root / "charge_strategy_by_vehicle.csv",
        charge_rows,
        list(charge_rows[0]),
    )
    _write_csv(
        report_root / "vehicle_threshold_by_vehicle.csv",
        threshold_rows,
        list(threshold_rows[0]),
    )
    raw_rows: list[dict[str, Any]] = []
    raw_fields = [
        "record_type",
        "evidence_label",
        "instance_id",
        "physical_vehicle_id",
        "depot_id",
        "trip_count",
        "daily_distance_km",
        "actual_witness_vehicle_type",
        "policy",
        "final_return_minute",
        "return_clock",
        "window_start_minute",
        "window_start_clock",
        "window_end_minute",
        "window_end_clock",
        "latest_start_minute",
        "latest_start_clock",
        "charge_energy_kwh",
        "start_energy_kwh",
        "end_energy_kwh",
        "charging_curve_id",
        "charge_duration_minute",
        "selected_start_minute",
        "selected_start_clock",
        "selected_end_minute",
        "selected_end_clock",
        "electricity_cost_cny",
        "emissions_kgco2e",
        "carbon_price_cny_per_kg",
        "carbon_cost_cny",
        "monetary_total_cny",
        "tariff_scenario",
        "critical_daily_km",
        "cost_optimal_vehicle_type",
        "matches_witness",
    ]
    for row in charge_rows:
        raw_rows.append({"record_type": "step_c_charge_strategy", **row})
    for row in threshold_rows:
        raw_rows.append({"record_type": "step_c_vehicle_threshold", **row})
    _write_csv(report_root / "raw_runs.csv", raw_rows, raw_fields)

    protected_hashes = {
        path: _sha256(repo_root / path)
        for path in PROTECTED
    }
    metadata = {
        "schema": "resetp.mechanism-validation-v3.step-c.v1",
        "status": "STEP_C_DONE",
        "run_kind": "fixed_witness_recalculation_no_search",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(repo_root),
        "instance_id": INSTANCE_ID,
        "input": str(input_path.relative_to(repo_root)),
        "input_sha256": _sha256(input_path),
        "carbon_price_cny_per_kg": CARBON_PRICE_CNY_PER_KG,
        "charge_policies": list(POLICIES),
        "critical_daily_km": {key: value for key, value in THRESHOLDS_KM},
        "search_evaluations": 0,
        "protected_file_hashes": protected_hashes,
    }
    _write_json(report_root / "metadata.json", metadata)
    _write_json(
        report_root / "decision.json",
        {
            "status": "STEP_C_DONE",
            "search_started": False,
            "next_authorized_step": "minimal_runtime_adapter_B",
            "final_mechanism_decision": "PENDING",
        },
    )
    (report_root / "report.md").write_text(
        _render_report(charge_rows, threshold_rows, protected_hashes),
        encoding="utf-8",
    )
    artifact_hashes = {
        path.name: _sha256(path)
        for path in sorted(report_root.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    _write_json(report_root / "artifact_hashes.json", artifact_hashes)


if __name__ == "__main__":
    main()
