#!/usr/bin/env python3
"""Read-only forensic audit for the E3 paper story.

The audit does not rerun search and does not modify any sealed evidence.  It
checks whether the current paper claims, saved schedules, ownership-mismatch
experiments, and proposed rectification tasks are measuring the same thing.
"""

from __future__ import annotations

import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.multitrip_schedule import (
    _certificate_from_prepared_solution,
    route_timing,
)
from setp_solver.solution import (
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
    physical_vehicle_id,
)


V11 = ROOT / "baselines/e3_ablation/e3_v11_clean_20260713"
MISMATCH = {
    "25": ROOT / "baselines/e3_ablation/e3_mismatch_formal_20260713_25",
    "50": ROOT / "baselines/e3_ablation/e3_mismatch_formal_20260713_50",
}
OUT = ROOT / "baselines/e3_ablation/e3_story_forensic_audit_20260713"
SOURCE_COMMIT = "9df03fe85d6f0b3fd7a925b2a4b86a0b35b31b35"
SCHEDULE_SOURCE = "solver/src/setp_solver/search/multitrip_schedule.py"
PAPER = ROOT / "docs/paper_submission_final/RETIRED_paper_main.tex"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"refusing to write empty audit table: {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_solution(path: Path) -> Solution:
    payload = read_json(path)
    return Solution(
        routes=[Route(**row) for row in payload.get("routes", [])],
        charging_actions=[ChargingAction(**row) for row in payload.get("charging_actions", [])],
        cross_site_services=[CrossSiteService(**row) for row in payload.get("cross_site_services", [])],
    )


def max_overlap(intervals: list[tuple[float, float]]) -> int:
    events: list[tuple[float, int]] = []
    for start, end in intervals:
        events.extend(((start, 1), (end, -1)))
    # At an exact tie, a returning vehicle is released before another departs.
    events.sort(key=lambda item: (item[0], item[1]))
    active = 0
    peak = 0
    for _, delta in events:
        active += delta
        peak = max(peak, active)
    return peak


def archived_source_hash() -> str:
    content = subprocess.run(
        ["git", "show", f"{SOURCE_COMMIT}:{SCHEDULE_SOURCE}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.sha256(content).hexdigest()


def v11_rows() -> list[dict[str, Any]]:
    bundle = load_search_bundle(V11 / "assets/200c/derived_bundles/actual_gamma")
    prices = replace(
        DEFAULT_PRICES,
        B_battery_kwh=280.0,
        initial_ev_battery_kwh=0.0,
        carbon_price=0.0,
        cross_site_cost=0.0,
    )
    output: list[dict[str, Any]] = []
    for layer, kind in (("M0", "adopted"), ("M1", "search"), ("M3", "search")):
        for seed in range(1, 11):
            run_id = f"E3__200c__{layer}__seed{seed}__fee0__eval4000"
            solution = read_solution(V11 / "solutions" / f"{run_id}__{kind}.json")
            certificate = _certificate_from_prepared_solution(solution, bundle.instance, prices)

            trip_groups: dict[str, list[Any]] = {}
            for trip in certificate.trips:
                trip_groups.setdefault(trip.physical_vehicle_id, []).append(trip)
            action_groups: dict[str, list[ChargingAction]] = {}
            for action in solution.charging_actions:
                action_groups.setdefault(physical_vehicle_id(action.vehicle_id), []).append(action)

            ev_chains = 0
            multitrip_ev_chains = 0
            literal_first_charge_later_trip_overlap = 0
            literal_same_vehicle_charge_overlap = 0
            recurring_last_return_window_infeasible = 0
            recurring_last_return_slack_hours: list[float] = []
            for vehicle_id, raw_trips in trip_groups.items():
                trips = sorted(raw_trips, key=lambda item: item.trip_index)
                if trips[0].vehicle_type != "ev":
                    continue
                ev_chains += 1
                multitrip_ev_chains += int(len(trips) > 1)
                first_action = next(
                    (
                        action
                        for action in action_groups.get(vehicle_id, [])
                        if action.vehicle_id == trips[0].route_id
                        and action.station_id == trips[0].home_depot_id
                    ),
                    None,
                )
                if first_action is None:
                    continue
                first_start = float(first_action.charge_start_second)
                first_end = first_start + float(first_action.occupancy_minutes) * 60.0
                if any(
                    max(first_start, float(trip.departure_second))
                    < min(first_end, float(trip.return_second)) - 1e-6
                    for trip in trips[1:]
                ):
                    literal_first_charge_later_trip_overlap += 1

                intervals = sorted(
                    (
                        float(action.charge_start_second),
                        float(action.charge_start_second) + float(action.occupancy_minutes) * 60.0,
                    )
                    for action in action_groups.get(vehicle_id, [])
                )
                if any(left[1] > right[0] + 1e-6 for left, right in zip(intervals, intervals[1:])):
                    literal_same_vehicle_charge_overlap += 1

                duration = float(first_action.occupancy_minutes) * 60.0
                available = float(trips[0].departure_second) + 86_400.0 - float(trips[-1].return_second)
                slack = available - duration
                recurring_last_return_slack_hours.append(slack / 3600.0)
                recurring_last_return_window_infeasible += int(slack < -1e-6)

            route_groups: dict[tuple[str, str], list[tuple[float, float]]] = {}
            for route in solution.routes:
                timing = route_timing(route, bundle.instance, prices)
                route_groups.setdefault((route.home_depot_id, route.vehicle_type.lower()), []).append(
                    (timing.earliest_departure_second, timing.return_second)
                )
            lower_bounds = {
                f"{depot}_{vehicle_type}": max_overlap(intervals)
                for (depot, vehicle_type), intervals in sorted(route_groups.items())
            }
            output.append(
                {
                    "layer": layer,
                    "seed": seed,
                    "saved_physical_vehicles": sum(certificate.vehicle_counts.values()),
                    "time_overlap_vehicle_lower_bound": sum(lower_bounds.values()),
                    "time_overlap_lower_bound_by_depot_type": json.dumps(lower_bounds, sort_keys=True),
                    "ev_chains": ev_chains,
                    "multitrip_ev_chains": multitrip_ev_chains,
                    "literal_first_charge_later_trip_overlap_chains": literal_first_charge_later_trip_overlap,
                    "literal_same_vehicle_charge_overlap_chains": literal_same_vehicle_charge_overlap,
                    "recurring_last_return_window_infeasible_chains": recurring_last_return_window_infeasible,
                    "mean_recurring_last_return_slack_hours": statistics.fmean(recurring_last_return_slack_hours),
                }
            )
    return output


def mismatch_rows(bundle: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    moved_sets: dict[str, set[str]] = {}
    for label, directory in MISMATCH.items():
        metadata = read_json(directory / "metadata.json")
        ownership_file = directory / f"ownership_{label}.csv"
        with ownership_file.open(newline="", encoding="utf-8") as handle:
            ownership = list(csv.DictReader(handle))
        moved = {row["customer_id"] for row in ownership if int(row["moved"]) == 1}
        moved_sets[label] = moved
        ratios: list[float] = []
        extra_one_way_km: list[float] = []
        for row in ownership:
            if int(row["moved"]) != 1:
                continue
            customer = row["customer_id"]
            base = row["base_home_depot_id"]
            assigned = row["home_depot_id"]
            base_distance = float(bundle.instance.distance(customer, base))
            assigned_distance = float(bundle.instance.distance(customer, assigned))
            ratios.append(assigned_distance / max(base_distance, 1e-9))
            extra_one_way_km.append((assigned_distance - base_distance) / 1000.0)

        artifact_hashes = read_json(directory / "artifact_hashes.json")
        apple_double = sum(Path(path).name.startswith("._") for path in artifact_hashes)
        output.append(
            {
                "ownership_case": label,
                "declared_share": metadata["share"],
                "moved_customers": len(moved),
                "customer_count": len(ownership),
                "actual_moved_share": len(moved) / len(ownership),
                "independent_budget_total": int(metadata["m0_budget_per_depot"]) * 2,
                "cooperation_budget": int(metadata["cooperation_budget"]),
                "budget_ratio_cooperation_to_independent": int(metadata["cooperation_budget"])
                / (int(metadata["m0_budget_per_depot"]) * 2),
                "median_assigned_to_nearest_distance_ratio": statistics.median(ratios),
                "p90_assigned_to_nearest_distance_ratio": sorted(ratios)[int(0.9 * (len(ratios) - 1))],
                "mean_extra_one_way_km": statistics.fmean(extra_one_way_km),
                "ownership_map_count": 1,
                "artifact_hash_entries": len(artifact_hashes),
                "appledouble_hash_entries": apple_double,
                "metadata_has_source_commit": "source_commit" in metadata,
                "metadata_has_source_hashes": "source_hashes" in metadata,
            }
        )
    overlap = moved_sets["25"] & moved_sets["50"]
    union = moved_sets["25"] | moved_sets["50"]
    for row in output:
        row["moved_set_overlap_count"] = len(overlap)
        row["moved_set_jaccard"] = len(overlap) / len(union)
        row["larger_case_is_superset"] = moved_sets["25"] <= moved_sets["50"]
    return output


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    bundle = load_search_bundle(V11 / "assets/200c/derived_bundles/actual_gamma")
    schedule_rows = v11_rows()
    ownership_rows = mismatch_rows(bundle)
    write_csv(OUT / "strict_schedule_audit.csv", schedule_rows)
    write_csv(OUT / "ownership_mismatch_audit.csv", ownership_rows)

    archived_hash = archived_source_hash()
    current_hash = sha256(ROOT / SCHEDULE_SOURCE)
    if archived_hash != current_hash:
        raise RuntimeError("current multitrip source no longer matches the v11 archived source")

    decision = {
        "schema": "setp.e3.story_forensic_audit.decision.v1",
        "status": "HALT_CURRENT_RECTIFICATION_SEQUENCE",
        "v11_cooperation_cost": "RETAIN_AS_DESCRIPTIVE_ALIGNED_OWNERSHIP_EVIDENCE_ONLY",
        "v11_vehicle_reduction": "HARD_NO_FOR_ALL_SAVED_M0_AND_M1_ROUTE_SETS",
        "v11_carbon_timing": "FREEZE_UNTIL_FIRST_TRIP_CLOCK_CONTRACT_MATCHES_THE_PAPER",
        "mismatch_25_50": "REJECT_AS_PAPER_EFFECT_SIZE_OR_VEHICLE_EVIDENCE",
        "cancelled_tasks": ["e3_rectification_master_plan:T1", "e3_rectification_master_plan:T2"],
        "reasons": [
            "The saved strict schedules and current paper do not use the same first-trip charging clock anchor.",
            "All saved M0 and M1 route sets have a hard time-overlap lower bound of 28 vehicles, so those routes cannot exhibit fleet reduction.",
            "The ownership cases compare 4000 cooperative evaluations with only 400 independent evaluations in total.",
            "Each ownership level has one non-nested random map with severe assignment-distance penalties, so the levels are stress cases rather than a dose-response curve.",
            "The ownership artifact hashes contain AppleDouble entries and the metadata lacks executable source identity.",
            "The current T1/T2 tasks repair only the independent budget and leave start asymmetry, map replication, vehicle-minimum semantics, source identity, and charging-clock mismatch unresolved.",
        ],
        "next_comparison_contract": {
            "question": "How does initial customer ownership affect the incremental cost value of collaboration?",
            "start": "same independently optimized solution for both continuation arms",
            "budget": "same continuation budget for owner-locked and cross-depot arms",
            "fairness": "off in E3 cost mechanism; tested separately in E6",
            "ownership_cases": "geographically aligned case plus several pre-registered balanced legacy-territory maps",
            "fleet_claim": "feasible within the same fixed assets; no minimum-fleet claim without an exact proof",
            "carbon_claim": "moved to E4 after the first-trip charging clock is made explicit and tested",
        },
    }
    write_json(OUT / "decision.json", decision)

    metadata = {
        "schema": "setp.e3.story_forensic_audit.metadata.v1",
        "audit_type": "read_only_no_search",
        "source_commit": SOURCE_COMMIT,
        "archived_multitrip_source_sha256": archived_hash,
        "current_multitrip_source_sha256": current_hash,
        "paper_sha256": sha256(PAPER),
        "sealed_v11_metadata_sha256": sha256(V11 / "final100/metadata.json"),
        "inputs": [
            str((V11 / "final100").relative_to(ROOT)),
            str(MISMATCH["25"].relative_to(ROOT)),
            str(MISMATCH["50"].relative_to(ROOT)),
        ],
    }
    write_json(OUT / "metadata.json", metadata)

    totals = {
        layer: {
            "saved_rows": sum(row["layer"] == layer for row in schedule_rows),
            "all_vehicle_lower_bounds_equal_28": all(
                row["time_overlap_vehicle_lower_bound"] == 28
                for row in schedule_rows
                if row["layer"] == layer
            ),
            "literal_first_charge_overlap_chains": sum(
                row["literal_first_charge_later_trip_overlap_chains"]
                for row in schedule_rows
                if row["layer"] == layer
            ),
            "recurring_last_return_infeasible_chains": sum(
                row["recurring_last_return_window_infeasible_chains"]
                for row in schedule_rows
                if row["layer"] == layer
            ),
        }
        for layer in ("M0", "M1", "M3")
    }
    report = f"""# E3 论文故事法医审计

## 判决

当前整改总计划的 T1/T2 停止执行。原因不是结果不好看，而是这两步只补了独立经营一侧的计算次数，仍没有修复共同起点、归属情境重复、车辆最少数证明、源码身份和首趟充电时间账五个问题。继续跑会得到更多台账，得不到可写进论文的因果比较。

## 哪些旧结果还能保留

零错配情境下的合作成本结果可以保留为描述性证据：在“客户本来就归最近车场”的情境中，合作搜索 6/10 次严格降低成本，平均 0.353%，但不能写成稳定、显著或普遍效果。它也不能单独证明合作的净增量价值，因为独立经营与合作搜索不是从同一方案继续搜索。

公平门实际拒绝伤害单方收益的候选，这可作为程序机制证据留给公平实验；它不等于已经量出公平的因果成本。

## 哪些主张必须冻结

车辆减少主张在现有保存路线中已经被硬证据否定。独立经营和合作两组的每一个种子，仅按同时运行的趟数计算就至少需要 28 辆车；这个下界还没有考虑电池，所以任何更精细的电池排班都不可能把这些保存路线压到 27 辆。

充电减排数字暂时冻结。论文写的是“末趟回场后至下一运营日首趟出发前充电”，源码却用“首趟回场后”作为首趟充电窗口起点，并且保存的时间没有日期编号。按字面当作同一天，首趟充电会和后续行程重叠；若解释为前一天，数据又没有把这个日期偏移写出来。现有碳账的算术复算是闭合的，但物理时间解释没有闭合。

25%/50% 随机错配结果不能作为论文效应量，也不能作为车辆结论。合作侧用了 4000 次方案评价，独立侧两场合计只有 400 次；每档只有一张随机归属表，两张表互不嵌套；被调换客户到新车场的距离中位数约为 {ownership_rows[0]['median_assigned_to_nearest_distance_ratio']:.2f} 倍和 {ownership_rows[1]['median_assigned_to_nearest_distance_ratio']:.2f} 倍，属于压力情境，不是一般企业历史归属的代表样本。

## 现有数字摘要

```json
{json.dumps(totals, ensure_ascii=False, indent=2)}
```

## 下一步只做什么

E3 只回答一个问题：客户原有归属怎样影响合作的增量成本价值。新的干净比较必须让两组从同一份独立经营方案出发、继续搜索相同次数；一组禁止跨车场，另一组允许跨车场。E3 不同时加入公平，公平单独由后续实验回答。客户归属只保留“地理已对齐”与“多个预先生成、负荷平衡、距离不过分的历史辖区”两类，不再把一张 25% 图和一张 50% 图连成趋势。

车辆只报告“同一固定资产内是否可行”。若要声称减少车辆，必须另做精确最少车辆证明；现有贪心见证不够。充电主张移交专门碳实验，前提是先把首趟充电发生在哪一天、从什么时候开始、是否与行程重叠写进数据并加最小回归测试。
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")

    hashes = {
        str(path.relative_to(ROOT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    write_json(OUT / "artifact_hashes.json", hashes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
