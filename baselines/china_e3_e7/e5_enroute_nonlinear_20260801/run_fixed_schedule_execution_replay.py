#!/usr/bin/env python3
"""Recheck pilot07 linear schedules under M17 without rescheduling anything."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for entry in (REPO, REPO / "solver/src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from baselines.china_e3_e7.e5_enroute_nonlinear_20260801.runtime_overlay import (
    M17_22KW_NORMAL_PWL,
    apply_runtime_overlay,
)
from setp_solver.charging_curve import PiecewiseChargingCurve, curve_from_parameters
from setp_solver.check import BATTERY, STATION_CAPACITY, TIME_WINDOW, check_solution
from setp_solver.china81 import load_china81_bundle
from setp_solver.solution import (
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
    charging_action_from_dict,
)


SOURCE = HERE / "pilot07_seeds1to3_symmetric"
DEFAULT_OUT = HERE / "pilot08_fixed_schedule_execution_replay_20260801"
ALLOWED_ACTION_CHANGES = frozenset({"occupancy_minutes", "charging_curve_id"})


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def route_hash(solution: Solution) -> str:
    return _json_hash([asdict(route) for route in solution.routes])


def frozen_action_hash(solution: Solution) -> str:
    return _json_hash(
        [
            {
                key: value
                for key, value in asdict(action).items()
                if key not in ALLOWED_ACTION_CHANGES
            }
            for action in solution.charging_actions
        ]
    )


def retime_action(
    action: ChargingAction, curve: PiecewiseChargingCurve
) -> ChargingAction:
    if action.start_energy_kwh is None or action.end_energy_kwh is None:
        raise ValueError("pilot07 action lacks its energy ledger")
    duration = curve.duration_seconds(
        float(action.start_energy_kwh), float(action.end_energy_kwh)
    )
    return replace(
        action,
        occupancy_minutes=duration / 60.0,
        charging_curve_id=curve.curve_id,
    )


def _solution(payload: Mapping[str, Any]) -> Solution:
    return Solution(
        routes=[Route(**row) for row in payload["routes"]],
        charging_actions=[
            charging_action_from_dict(row) for row in payload["charging_actions"]
        ],
        cross_site_services=[
            CrossSiteService(**row) for row in payload.get("cross_site_services", [])
        ],
    )


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(
    path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        writer.writerows(rows)


def _curve_for_action(action: ChargingAction, bundle: Any) -> PiecewiseChargingCurve:
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


def run(output: Path) -> None:
    if output.exists():
        raise RuntimeError(f"refusing to overwrite {output}")
    manifest = json.loads((SOURCE / "artifact_hashes.json").read_text(encoding="utf-8"))
    source_paths = sorted((SOURCE / "units").glob("*__L100_control.json"))
    if len(source_paths) != 30:
        raise RuntimeError(f"expected 30 L100 units, found {len(source_paths)}")

    output.mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    input_hashes: dict[str, str] = {}

    for source_path in source_paths:
        relative = str(source_path.relative_to(SOURCE))
        source_sha = _file_hash(source_path)
        if manifest.get(relative) != source_sha:
            raise RuntimeError(f"pilot07 source hash mismatch: {relative}")
        input_hashes[relative] = source_sha
        detail = json.loads(source_path.read_text(encoding="utf-8"))
        source_row = detail["row"]
        source_solution = _solution(detail["solution"])
        if (
            source_row["curve_id"] != "L100_control"
            or not source_row["feasible"]
            or detail["violations"]
            or route_hash(source_solution) != source_row["route_hash"]
        ):
            raise RuntimeError(f"pilot07 linear source is not sealed legal evidence: {relative}")

        base = load_china81_bundle(REPO, str(source_row["instance_id"]))
        bundle = apply_runtime_overlay(
            base,
            capacity_kwh=float(source_row["capacity_kwh"]),
            curve_id=M17_22KW_NORMAL_PWL.curve_id,
            public_charge_power_kw=float(source_row["public_charge_power_kw"]),
        )
        replay_actions = [
            retime_action(action, _curve_for_action(action, bundle))
            for action in source_solution.charging_actions
        ]
        replay = replace(source_solution, charging_actions=replay_actions)
        route_unchanged = route_hash(replay) == route_hash(source_solution)
        frozen_unchanged = frozen_action_hash(replay) == frozen_action_hash(
            source_solution
        )
        only_allowed = all(
            {
                key
                for key, value in asdict(before).items()
                if value != asdict(after)[key]
            }
            <= ALLOWED_ACTION_CHANGES
            for before, after in zip(
                source_solution.charging_actions, replay.charging_actions, strict=True
            )
        )
        if not (route_unchanged and frozen_unchanged and only_allowed):
            raise RuntimeError(f"frozen execution fields changed: {relative}")

        found = check_solution(replay, bundle.instance, bundle.prices)
        unit_id = source_path.stem.removesuffix("__L100_control")
        original_minutes = sum(
            float(action.occupancy_minutes)
            for action in source_solution.charging_actions
        )
        replay_minutes = sum(
            float(action.occupancy_minutes) for action in replay.charging_actions
        )
        rows.append(
            {
                "unit_id": unit_id,
                "instance_id": source_row["instance_id"],
                "seed": source_row["seed"],
                "capacity_kwh": source_row["capacity_kwh"],
                "public_charge_power_kw": source_row["public_charge_power_kw"],
                "source_unit_sha256": source_sha,
                "charging_action_count": len(replay_actions),
                "source_charging_minutes": original_minutes,
                "m17_execution_charging_minutes": replay_minutes,
                "duration_increase_minutes": replay_minutes - original_minutes,
                "route_hash_unchanged": route_unchanged,
                "frozen_action_hash_unchanged": frozen_unchanged,
                "only_duration_and_curve_changed": only_allowed,
                "execution_legal": not found,
                "violation_count": len(found),
                "violation_types": "|".join(item.type for item in found),
                "battery_violation_count": sum(item.type == BATTERY for item in found),
                "time_window_violation_count": sum(
                    item.type == TIME_WINDOW for item in found
                ),
                "station_capacity_conflict_count": sum(
                    item.type == STATION_CAPACITY for item in found
                ),
            }
        )
        for index, (before, after) in enumerate(
            zip(source_solution.charging_actions, replay.charging_actions, strict=True),
            start=1,
        ):
            actions.append(
                {
                    "unit_id": unit_id,
                    "action_index": index,
                    "vehicle_id": before.vehicle_id,
                    "station_id": before.station_id,
                    "charge_start_second": before.charge_start_second,
                    "charge_day_offset": before.charge_day_offset,
                    "energy_kwh": before.energy_kwh,
                    "start_energy_kwh": before.start_energy_kwh,
                    "end_energy_kwh": before.end_energy_kwh,
                    "source_occupancy_minutes": before.occupancy_minutes,
                    "m17_occupancy_minutes": after.occupancy_minutes,
                    "duration_increase_seconds": 60.0
                    * (after.occupancy_minutes - before.occupancy_minutes),
                    "source_curve_id": before.charging_curve_id,
                    "execution_curve_id": after.charging_curve_id,
                    "enters_taper": float(before.end_energy_kwh)
                    > 0.85 * float(source_row["capacity_kwh"]) + 1.0e-9,
                }
            )
        for index, item in enumerate(found, start=1):
            violations.append(
                {
                    "unit_id": unit_id,
                    "violation_index": index,
                    **asdict(item),
                }
            )

    raw_fields = list(rows[0])
    action_fields = list(actions[0]) if actions else ["unit_id"]
    violation_fields = [
        "unit_id",
        "violation_index",
        "type",
        "vehicle_id",
        "location",
        "detail",
        "severity",
    ]
    _write_csv(output / "raw_runs.csv", rows, raw_fields)
    _write_csv(output / "action_details.csv", actions, action_fields)
    _write_csv(output / "violation_details.csv", violations, violation_fields)

    counts: dict[str, int] = {}
    for item in violations:
        counts[item["type"]] = counts.get(item["type"], 0) + 1
    metadata = {
        "task_id": "E5-EXEC-REPLAY-01",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "evidence_role": "LOW_COST_DEFECT_REPAIR_EXECUTION_REPLAY",
        "source_pilot": str(SOURCE.relative_to(REPO)),
        "source_artifact_manifest_sha256": _file_hash(
            SOURCE / "artifact_hashes.json"
        ),
        "source_unit_count": len(source_paths),
        "source_unit_sha256": input_hashes,
        "route_search_started": False,
        "frozen_fields": [
            "routes",
            "vehicle_type",
            "station_id",
            "charge_start_second",
            "charge_day_offset",
            "energy_kwh",
            "start_energy_kwh",
            "end_energy_kwh",
        ],
        "changed_fields": ["occupancy_minutes", "charging_curve_id"],
        "execution_curve": M17_22KW_NORMAL_PWL.curve_id,
        "runner_sha256": _file_hash(Path(__file__)),
    }
    decision = {
        "status": "FIXED_SCHEDULE_EXECUTION_REPLAY_COMPLETE",
        "formal_result": False,
        "unit_count": len(rows),
        "all_routes_unchanged": all(row["route_hash_unchanged"] for row in rows),
        "all_frozen_actions_unchanged": all(
            row["frozen_action_hash_unchanged"] for row in rows
        ),
        "all_changes_limited_to_duration_and_curve": all(
            row["only_duration_and_curve_changed"] for row in rows
        ),
        "legal_unit_count": sum(row["execution_legal"] for row in rows),
        "illegal_unit_count": sum(not row["execution_legal"] for row in rows),
        "violation_count": len(violations),
        "violation_type_counts": counts,
        "old_clear_then_independent_reschedule_strong_claim_overturned": True,
    }
    _write_json(output / "metadata.json", metadata)
    _write_json(output / "decision.json", decision)
    by_case: dict[tuple[str, float], list[dict[str, Any]]] = {}
    for row in rows:
        by_case.setdefault(
            (str(row["instance_id"]), float(row["capacity_kwh"])), []
        ).append(row)
    lines = [
        "# E5 固定执行计划的 M17 复核",
        "",
        "本次直接读取 pilot07 的30个线性最终解。路线、车型、充电站、充电开始时刻和充电量全部冻结；只按M17曲线延长占用时间，再交给完整检查器。没有启动路线搜索，也没有重新安排充电时刻。",
        "",
        f"共检查30个方案；合法 {decision['legal_unit_count']} 个，不合法 {decision['illegal_unit_count']} 个。",
        "",
        "| 算例 | 容量(kWh) | 方案数 | 不合法 | 充电动作 | 合计延长(min) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for (instance_id, capacity), group in sorted(by_case.items()):
        lines.append(
            f"| {instance_id} | {capacity:g} | {len(group)} | "
            f"{sum(not row['execution_legal'] for row in group)} | "
            f"{sum(int(row['charging_action_count']) for row in group)} | "
            f"{sum(float(row['duration_increase_minutes']) for row in group):.6f} |"
        )
    lines.extend(
        [
            "",
            "旧 pilot07 的复核先清空充电动作，再逐车选择新的低碳充电时刻；该做法同时改变了充电时刻且没有联合协调充电枪，因此不能证明线性路线在M17下不可行。旧强结论已推翻，本报告只解释冻结执行计划后的实际检查结果。",
            "",
            "本结果仍是获批范围内的低成本缺陷修复小试，不是正式实验结果。",
        ]
    )
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    artifact_hashes = {
        path.name: _file_hash(path)
        for path in sorted(output.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    _write_json(output / "artifact_hashes.json", artifact_hashes)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    run(args.output.resolve())


if __name__ == "__main__":
    main()
