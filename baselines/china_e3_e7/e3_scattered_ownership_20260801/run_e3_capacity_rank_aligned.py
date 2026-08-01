#!/usr/bin/env python3
"""Candidate E3 pilot: align public owner labels with existing depot capacity."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from setp_solver.solution import physical_vehicle_id

from baselines.china_e3_e7.e3_scattered_ownership_20260801 import (
    run_e3_scattered_ownership as base,
)

HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[3]
OUTPUT = HERE / "pilot_capacity_rank_aligned_v1_20260801"
FAMILY = "Uniform_Unbalanced_Capacity_Rank_Aligned"
SOURCE_FAMILY = "Uniform_Unbalanced"
INSTANCE = "cn-prd-150c-01-V2-LOCATIONS"
ARMS = base.ARMS
SEEDS = base.SEEDS


def capacity_rank_alignment(
    bundle: Any, customers: list[str], labels: tuple[int, ...]
) -> tuple[dict[int, str], dict[int, dict[str, float]], dict[str, float]]:
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    label_stats = {
        label: {
            "customer_count": sum(value == label for value in labels),
            "demand_kg": sum(
                float(nodes[customer].demand)
                for customer, value in zip(customers, labels, strict=True)
                if value == label
            ),
        }
        for label in sorted(set(labels))
    }
    cv_payload = bundle.instance.payload_capacity_kg(
        "cv", fallback=float(bundle.prices.Q_capacity)
    )
    ev_payload = bundle.instance.payload_capacity_kg(
        "ev", fallback=float(bundle.prices.Q_capacity)
    )
    depot_capacity = {
        depot: int(caps["num_cv"]) * cv_payload + int(caps["num_ev"]) * ev_payload
        for depot, caps in bundle.fleet_caps_by_depot.items()
    }
    label_order = sorted(
        label_stats, key=lambda label: (-label_stats[label]["demand_kg"], label)
    )
    depot_order = sorted(
        depot_capacity, key=lambda depot: (-depot_capacity[depot], depot)
    )
    return (
        dict(zip(label_order, depot_order, strict=True)),
        label_stats,
        depot_capacity,
    )


def prepare(instance_id: str = INSTANCE) -> tuple[Any, dict[str, Any]]:
    original = base.load_bundle(instance_id)
    customers = sorted(original.customer_home_depot)
    labels = base.sequences()[(SOURCE_FAMILY, base.replicate(instance_id))][
        : len(customers)
    ]
    label_to_depot, label_stats, depot_capacity = capacity_rank_alignment(
        original, customers, labels
    )
    mapping = {
        customer: label_to_depot[label]
        for customer, label in zip(customers, labels, strict=True)
    }
    bundle = replace(
        original,
        customer_home_depot=MappingProxyType(mapping),
        formal_search_allowed=True,
    )
    caps = {depot: dict(values) for depot, values in bundle.fleet_caps_by_depot.items()}
    depot_to_label = {depot: label for label, depot in label_to_depot.items()}
    depot_stats = {
        depot: {
            "source_label": depot_to_label[depot],
            "customer_count": label_stats[depot_to_label[depot]]["customer_count"],
            "demand_kg": label_stats[depot_to_label[depot]]["demand_kg"],
            "payload_capacity_kg": depot_capacity[depot],
            "capacity_shortfall_kg": max(
                0.0,
                label_stats[depot_to_label[depot]]["demand_kg"] - depot_capacity[depot],
            ),
            "num_cv": int(caps[depot]["num_cv"]),
            "num_ev": int(caps[depot]["num_ev"]),
        }
        for depot in sorted(caps)
    }
    return bundle, {
        "instance_id": instance_id,
        "source_family": SOURCE_FAMILY,
        "candidate_family": FAMILY,
        "source_replicate": base.replicate(instance_id),
        "label_to_depot": label_to_depot,
        "depot_stats": depot_stats,
        "mapping_sha256": base.canonical_sha256(mapping),
        "source_labels_sha256": base.canonical_sha256(labels),
        "available_cv_total": sum(row["num_cv"] for row in depot_stats.values()),
        "available_ev_total": sum(row["num_ev"] for row in depot_stats.values()),
    }


def _base_row(info: dict[str, Any], seed: int, arm: str) -> dict[str, Any]:
    stats = info["depot_stats"]
    field = lambda name: json.dumps(
        {depot: row[name] for depot, row in stats.items()}, sort_keys=True
    )
    return {
        "instance_id": info["instance_id"],
        "candidate_family": info["candidate_family"],
        "source_family": info["source_family"],
        "seed": seed,
        "arm": arm,
        "label_to_depot": json.dumps(info["label_to_depot"], sort_keys=True),
        "source_label_by_depot": field("source_label"),
        "customer_count_by_depot": field("customer_count"),
        "demand_kg_by_depot": field("demand_kg"),
        "payload_capacity_kg_by_depot": field("payload_capacity_kg"),
        "available_cv_by_depot": field("num_cv"),
        "available_ev_by_depot": field("num_ev"),
        "used_cv_by_depot": "",
        "used_ev_by_depot": "",
        "used_cv_total": "",
        "used_ev_total": "",
        "total_cost_cny": "",
        "total_distance_km": "",
        "total_emissions_kg": "",
        "cross_contractor_customer_count": "",
        "joint_relative_cost_change_pct": "",
        "complete_candidate_evaluations": 0,
        "elapsed_seconds": 0.0,
        "mapping_sha256": info["mapping_sha256"],
        "initial_sha256": info.get("initial_sha256", ""),
        "solution_sha256": "",
        "status": "",
        "status_reason": "",
    }


def run_arm(
    bundle: Any,
    initial: Any,
    info: dict[str, Any],
    seed: int,
    arm: str,
    iterations: int,
    archive: int,
) -> dict[str, Any]:
    result = base.run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=seed,
        hgs_seconds_per_view=None,
        exact_elites_per_view=min(8, archive),
        max_archive_candidates_per_view=archive,
        sp_time_limit_seconds=5.0,
        hard_home_depot_lock=arm == "HISTORICAL_STANDALONE",
        max_hgs_iterations_per_view=iterations,
        wallclock_safety_seconds_per_view=max(180.0, iterations * 0.5),
        exact_checkpoint_interval_iterations=None,
    )
    objective, breakdown, violations = base.exact_china81_score(result.solution, bundle)
    if violations or (
        arm == "HISTORICAL_STANDALONE" and result.solution.cross_site_services
    ):
        raise RuntimeError(f"invalid {arm} solution: violations={len(violations)}")

    used: dict[tuple[str, str], set[str]] = defaultdict(set)
    for route in result.solution.routes:
        used[(route.home_depot_id, route.vehicle_type.lower())].add(
            physical_vehicle_id(route.vehicle_id)
        )
    used_cv = {depot: len(used[(depot, "cv")]) for depot in info["depot_stats"]}
    used_ev = {depot: len(used[(depot, "ev")]) for depot in info["depot_stats"]}
    for depot, stats in info["depot_stats"].items():
        if used_cv[depot] > stats["num_cv"] or used_ev[depot] > stats["num_ev"]:
            raise RuntimeError(f"fleet cap exceeded at {depot}")
    return {
        "used_cv_by_depot": json.dumps(used_cv, sort_keys=True),
        "used_ev_by_depot": json.dumps(used_ev, sort_keys=True),
        "used_cv_total": int(breakdown["n_veh_cv"]),
        "used_ev_total": int(breakdown["n_veh_ev"]),
        "total_cost_cny": objective,
        "total_distance_km": float(breakdown["distance_total"]) / 1000.0,
        "total_emissions_kg": float(breakdown["E_total"]),
        "cross_contractor_customer_count": len(
            {item.customer_id for item in result.solution.cross_site_services}
        ),
        "complete_candidate_evaluations": result.stats[
            "complete_candidate_evaluation_attempts"
        ],
        "elapsed_seconds": result.elapsed_seconds,
        "solution_sha256": base.solution_sha256(result.solution),
        "status": "PASS",
        "status_reason": "",
    }


def _report(
    decision: dict[str, Any], info: dict[str, Any], rows: list[dict[str, Any]]
) -> str:
    lines = [
        "# E3 capacity-rank-aligned candidate pilot",
        "",
        f"**状态：{decision['status']}。**",
        "",
        "映射在搜索前固定：源标签按其承接的 China81 总需求量从大到小排序，",
        "原车场按 CV/EV 原始上限形成的总载重从大到小排序，再一一对应；",
        "同值分别按标签号和 depot_id 排序。客户、需求、时窗、车型和车辆上限均未改变。",
        "",
        "| 车场 | 源标签 | 客户数 | 需求/kg | 原运力/kg | CV上限 | EV上限 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for depot, row in info["depot_stats"].items():
        lines.append(
            f"| {depot} | {row['source_label']} | {row['customer_count']} | "
            f"{row['demand_kg']:.0f} | {row['payload_capacity_kg']:.0f} | "
            f"{row['num_cv']} | {row['num_ev']} |"
        )
    lines.extend(
        [
            "",
            "| seed | 方案 | 实际CV | 实际EV | 成本/元 | 里程/km | 排放/kg | 跨承包商客户 | 联合相对单干/% | 状态 |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in rows:
        values = [
            str(row["seed"]),
            row["arm"],
            str(row["used_cv_total"]),
            str(row["used_ev_total"]),
            str(row["total_cost_cny"]),
            str(row["total_distance_km"]),
            str(row["total_emissions_kg"]),
            str(row["cross_contractor_customer_count"]),
            str(row["joint_relative_cost_change_pct"]),
            row["status"],
        ]
        lines.append("| " + " | ".join(values) + " |")
    lines.extend(
        [
            "",
            "这是候选小试；是否作为正式 E3 设计由用户决定。旧排序与 Uniform_Balanced 的 v1 容量失败证据保持原样。",
        ]
    )
    return "\n".join(lines) + "\n"


def run_pilot(
    output: Path = OUTPUT, iterations: int = 100, archive: int = 8
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    bundle, info = prepare()
    rows: list[dict[str, Any]] = []
    attempted: list[int] = []
    completed: list[int] = []
    search_started = False
    failure = ""

    shortfalls = {
        depot: row["capacity_shortfall_kg"]
        for depot, row in info["depot_stats"].items()
        if row["capacity_shortfall_kg"] > 0
    }
    if shortfalls:
        failure = f"capacity lower bound failed: {shortfalls}"
    else:
        try:
            initial, route_counts = base.build_common_initial(bundle)
            info["initial_route_counts"] = route_counts
            info["initial_sha256"] = base.solution_sha256(initial)
        except Exception as exc:  # noqa: BLE001 - preserve the failed pilot row
            failure = f"initial route construction failed: {type(exc).__name__}: {exc}"
        else:
            for seed in SEEDS:
                attempted.append(seed)
                pair: list[dict[str, Any]] = []
                for arm in ARMS:
                    row = _base_row(info, seed, arm)
                    try:
                        search_started = True
                        row.update(
                            run_arm(
                                bundle, initial, info, seed, arm, iterations, archive
                            )
                        )
                    except Exception as exc:  # noqa: BLE001 - preserve the failed pilot row
                        row.update(
                            status="HALT_ROUTE_OR_TECHNICAL_ERROR",
                            status_reason=f"{type(exc).__name__}: {exc}",
                        )
                        failure = row["status_reason"]
                    rows.append(row)
                    pair.append(row)
                    if failure:
                        break
                if failure:
                    if len(pair) == 1:
                        row = _base_row(info, seed, ARMS[1])
                        row.update(
                            status="NOT_RUN_STOP_RULE",
                            status_reason="paired run stopped after preceding failure",
                        )
                        rows.append(row)
                    break
                costs = {row["arm"]: float(row["total_cost_cny"]) for row in pair}
                change = (
                    100.0
                    * (costs["JOINT_OPTIMIZED"] - costs["HISTORICAL_STANDALONE"])
                    / costs["HISTORICAL_STANDALONE"]
                )
                for row in pair:
                    row["joint_relative_cost_change_pct"] = change
                completed.append(seed)

    if failure and not rows:
        for arm in ARMS:
            row = _base_row(info, SEEDS[0], arm)
            row.update(status="NOT_RUN_INPUT_OR_INITIAL_HALT", status_reason=failure)
            rows.append(row)

    status = (
        "PASS_CANDIDATE_PILOT_SEEDS_1_TO_3"
        if completed == list(SEEDS)
        else "HALT_CAPACITY_RANK_ALIGNED_CANDIDATE"
    )
    decision = {
        "status": status,
        "candidate_only": True,
        "formal_adoption": "AWAITING_USER_DECISION",
        "instance_id": INSTANCE,
        "family": FAMILY,
        "attempted_seeds": attempted,
        "completed_seeds": completed,
        "not_started_seeds": [seed for seed in SEEDS if seed not in attempted],
        "iterations_per_view": iterations,
        "archive_candidates_per_view": archive,
        "search_started": search_started,
        "failure": failure,
    }
    fleet_path = (
        REPO / "baselines/china_e3_e7/e3e6_gates_01_20260729/gate1_d2a/fleet_caps.csv"
    )
    metadata = {
        "schema": "resetp.e3-capacity-rank-aligned-candidate.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "comparison": list(ARMS),
        "mapping_rule": "descending source-label China81 demand aligned one-to-one with descending original depot payload capacity; ties by label/depot_id",
        "unchanged_inputs": [
            "customers",
            "demand",
            "time_windows",
            "fleet_caps",
            "vehicle_types",
        ],
        "optimizer_vehicle_choice": "actual CV/EV use within each original per-depot type cap",
        "source_hashes": {
            str(path.relative_to(REPO)): base._sha256(path)
            for path in (
                Path(__file__),
                HERE / "run_e3_scattered_ownership.py",
                HERE / "shared_runtime.py",
                base.SOURCE,
                fleet_path,
                *base.PROTECTED,
            )
        },
    }
    base.write_json(output / "metadata.json", metadata)
    base.write_csv(output / "raw_runs.csv", rows)
    base.write_json(output / "decision.json", decision)
    (output / "report.md").write_text(_report(decision, info, rows), encoding="utf-8")
    base.write_json(
        output / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "artifacts": {
                name: base._sha256(output / name)
                for name in (
                    "metadata.json",
                    "raw_runs.csv",
                    "decision.json",
                    "report.md",
                )
            },
        },
    )
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run_pilot(args.output), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
