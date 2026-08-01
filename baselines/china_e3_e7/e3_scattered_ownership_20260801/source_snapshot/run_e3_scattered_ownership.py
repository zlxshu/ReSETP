#!/usr/bin/env python3
"""E3: scattered historical ownership versus joint routing."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[3]
PROTOTYPE = REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
for path in (REPO, REPO / "solver/src", PROTOTYPE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from route_pool_sp import run_hgs_route_pool_recombination
from setp_solver.china81_completion import exact_china81_score

from baselines.china_e3_e7.e3_scattered_ownership_20260801.shared_runtime import (
    build_common_initial,
    canonical_sha256,
    load_bundle,
    solution_sha256,
    write_csv,
    write_json,
)

SOURCE = HERE / "source_p_sequences.csv"
PILOT = HERE / "pilot_existing_fleet_v1_20260801"
FAMILIES = ("Uniform_Balanced", "Uniform_Unbalanced")
INSTANCE = "cn-prd-150c-01-V2-LOCATIONS"
ARMS = ("HISTORICAL_STANDALONE", "JOINT_OPTIMIZED")
SEEDS = (1, 2, 3)
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
)


def sequences() -> dict[tuple[str, str], tuple[int, ...]]:
    with SOURCE.open(encoding="utf-8", newline="") as handle:
        rows = {
            (row["source_family"], row["replicate"]): tuple(
                map(int, row["p_sequence"].split())
            )
            for row in csv.DictReader(handle)
        }
    if len(rows) != 6 or any(len(values) != 200 for values in rows.values()):
        raise ValueError("source_p_sequences.csv must contain six 200-label rows")
    return rows


def replicate(instance_id: str) -> str:
    return next(rep for rep in ("01", "02", "03") if f"c-{rep}-" in instance_id)


def capacity_audit(bundle: Any) -> dict[str, dict[str, float]]:
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    cv_payload = bundle.instance.payload_capacity_kg(
        "cv", fallback=float(bundle.prices.Q_capacity)
    )
    ev_payload = bundle.instance.payload_capacity_kg(
        "ev", fallback=float(bundle.prices.Q_capacity)
    )
    rows: dict[str, dict[str, float]] = {}
    for depot, caps in sorted(bundle.fleet_caps_by_depot.items()):
        demand = sum(
            float(nodes[customer].demand)
            for customer, owner in bundle.customer_home_depot.items()
            if owner == depot
        )
        capacity = int(caps["num_cv"]) * cv_payload + int(caps["num_ev"]) * ev_payload
        rows[depot] = {
            "assigned_demand_kg": demand,
            "available_payload_kg": capacity,
            "capacity_shortfall_kg": max(0.0, demand - capacity),
        }
    return rows


def prepare(instance_id: str, family: str) -> tuple[Any, Any | None, dict[str, Any]]:
    base = load_bundle(instance_id)
    customers = sorted(base.customer_home_depot)
    depots = sorted(base.fleet_caps_by_depot)
    if family not in FAMILIES or len(depots) != 4 or len(customers) not in {150, 200}:
        raise ValueError("E3 transfer requires an approved family and 4-depot 150/200c input")

    labels = sequences()[(family, replicate(instance_id))][: len(customers)]
    mapping = {
        customer: depots[label]
        for customer, label in zip(customers, labels, strict=True)
    }
    bundle = replace(
        base,
        customer_home_depot=MappingProxyType(mapping),
        formal_search_allowed=True,
    )
    audit = capacity_audit(bundle)
    has_shortfall = any(row["capacity_shortfall_kg"] > 0 for row in audit.values())
    initial, route_counts = (None, {}) if has_shortfall else build_common_initial(bundle)
    caps = {depot: dict(values) for depot, values in bundle.fleet_caps_by_depot.items()}
    return bundle, initial, {
        "instance_id": instance_id,
        "source_family": family,
        "source_replicate": replicate(instance_id),
        "owner_counts": {
            depot: sum(owner == depot for owner in mapping.values()) for depot in depots
        },
        "fleet_caps_by_depot": caps,
        "available_cv_total": sum(int(row["num_cv"]) for row in caps.values()),
        "available_ev_total": sum(int(row["num_ev"]) for row in caps.values()),
        "capacity_audit": audit,
        "initial_route_counts": route_counts,
        "mapping_sha256": canonical_sha256(mapping),
        "initial_sha256": "" if initial is None else solution_sha256(initial),
    }


def run_arm(
    bundle: Any,
    initial: Any,
    arm: str,
    seed: int,
    iterations: int,
    archive: int,
) -> dict[str, Any]:
    run = run_hgs_route_pool_recombination(
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
    objective, breakdown, violations = exact_china81_score(run.solution, bundle)
    if violations or (
        arm == "HISTORICAL_STANDALONE" and run.solution.cross_site_services
    ):
        raise RuntimeError(f"invalid {arm} solution: violations={len(violations)}")
    return {
        "used_cv_total": int(breakdown["n_veh_cv"]),
        "used_ev_total": int(breakdown["n_veh_ev"]),
        "total_cost_cny": objective,
        "total_distance_km": float(breakdown["distance_total"]) / 1000.0,
        "total_emissions_kg": float(breakdown["E_total"]),
        "cross_contractor_service_count": len(run.solution.cross_site_services),
        "joint_relative_cost_change_pct": "",
        "complete_candidate_evaluations": run.stats[
            "complete_candidate_evaluation_attempts"
        ],
        "elapsed_seconds": run.elapsed_seconds,
        "solution_sha256": solution_sha256(run.solution),
        "status": "PASS",
        "status_reason": "",
    }


def _base_row(info: dict[str, Any], arm: str, seed: int) -> dict[str, Any]:
    caps = info["fleet_caps_by_depot"]
    audit = info["capacity_audit"]
    return {
        "instance_id": info["instance_id"],
        "source_family": info["source_family"],
        "seed": seed,
        "arm": arm,
        "available_cv_total": info["available_cv_total"],
        "available_ev_total": info["available_ev_total"],
        "available_cv_by_depot": json.dumps(
            {depot: row["num_cv"] for depot, row in caps.items()}, sort_keys=True
        ),
        "available_ev_by_depot": json.dumps(
            {depot: row["num_ev"] for depot, row in caps.items()}, sort_keys=True
        ),
        "used_cv_total": "",
        "used_ev_total": "",
        "assigned_demand_by_depot_kg": json.dumps(
            {depot: row["assigned_demand_kg"] for depot, row in audit.items()},
            sort_keys=True,
        ),
        "available_payload_by_depot_kg": json.dumps(
            {depot: row["available_payload_kg"] for depot, row in audit.items()},
            sort_keys=True,
        ),
        "capacity_shortfall_by_depot_kg": json.dumps(
            {depot: row["capacity_shortfall_kg"] for depot, row in audit.items()},
            sort_keys=True,
        ),
        "total_cost_cny": "",
        "total_distance_km": "",
        "total_emissions_kg": "",
        "cross_contractor_service_count": "",
        "joint_relative_cost_change_pct": "",
        "complete_candidate_evaluations": 0,
        "elapsed_seconds": 0.0,
        "mapping_sha256": info["mapping_sha256"],
        "initial_sha256": info["initial_sha256"],
        "solution_sha256": "",
        "status": "",
        "status_reason": "",
    }


def _run_pair(
    bundle: Any,
    initial: Any,
    info: dict[str, Any],
    seed: int,
    iterations: int,
    archive: int,
) -> list[dict[str, Any]]:
    rows = [
        {
            **_base_row(info, arm, seed),
            **run_arm(bundle, initial, arm, seed, iterations, archive),
        }
        for arm in ARMS
    ]
    costs = {row["arm"]: float(row["total_cost_cny"]) for row in rows}
    change = 100.0 * (
        costs["JOINT_OPTIMIZED"] - costs["HISTORICAL_STANDALONE"]
    ) / costs["HISTORICAL_STANDALONE"]
    for row in rows:
        row["joint_relative_cost_change_pct"] = change
    return rows


def _capacity_halt_rows(info: dict[str, Any], seed: int) -> list[dict[str, Any]]:
    reason = "assigned demand exceeds the original fleet's total payload capacity"
    standalone = _base_row(info, "HISTORICAL_STANDALONE", seed)
    standalone.update(status="PROVEN_INFEASIBLE_CAPACITY_LOWER_BOUND", status_reason=reason)
    joint = _base_row(info, "JOINT_OPTIMIZED", seed)
    joint.update(status="NOT_RUN_STOP_RULE", status_reason="standalone infeasibility triggered the user stop rule")
    return [standalone, joint]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report(decision: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# E3 existing-fleet pilot v1",
        "",
        f"**结论：{decision['status']}。**",
        "",
        "本轮保留 China81 原有的逐车场、逐车型最高数量，没有设置油电比例或新增车辆。",
        "当前 E3 静态 HGS-SP 中一条入选路线占用一个车辆名额。",
        "seed 1 的两种散乱客户分布都在搜索前触发容量下界：部分承包商名下客户总需求量已经超过其全部可用车辆的一次配送容量之和。",
        "因此单干方案不可能合法，按用户停止条件未启动联合优化，也未启动 seeds 2--3。",
        "",
        "| 分布 | 车场 | 客户需求/kg | 可用运力/kg | 硬缺口/kg |",
        "|---|---:|---:|---:|---:|",
    ]
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if row["arm"] != "HISTORICAL_STANDALONE":
            continue
        demand = json.loads(row["assigned_demand_by_depot_kg"])
        capacity = json.loads(row["available_payload_by_depot_kg"])
        shortfall = json.loads(row["capacity_shortfall_by_depot_kg"])
        for depot, gap in shortfall.items():
            if gap <= 0 or (row["source_family"], depot) in seen:
                continue
            seen.add((row["source_family"], depot))
            lines.append(
                f"| {row['source_family']} | {depot} | {demand[depot]:.0f} | "
                f"{capacity[depot]:.0f} | {gap:.0f} |"
            )
    lines.extend(
        [
            "",
            "`raw_runs.csv` 保留两种分布下的单干失败行和联合方案未运行行；成本、里程、排放与实际车型使用量为空，因为没有合法最终解。",
        ]
    )
    return "\n".join(lines) + "\n"


def run_pilot(output: Path, iterations: int = 100, archive: int = 8) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    inputs: dict[str, tuple[Any, Any | None, dict[str, Any]]] = {}
    capacity_halts: dict[str, Any] = {}
    for family in FAMILIES:
        bundle, initial, info = prepare(INSTANCE, family)
        inputs[family] = (bundle, initial, info)
        shortfalls = {
            depot: row
            for depot, row in info["capacity_audit"].items()
            if row["capacity_shortfall_kg"] > 0
        }
        if shortfalls:
            capacity_halts[family] = shortfalls
            rows.extend(_capacity_halt_rows(info, SEEDS[0]))

    if not capacity_halts:
        for family in FAMILIES:
            bundle, initial, info = inputs[family]
            rows.extend(_run_pair(bundle, initial, info, SEEDS[0], iterations, archive))
        for seed in SEEDS[1:]:
            for family in FAMILIES:
                bundle, initial, info = inputs[family]
                rows.extend(_run_pair(bundle, initial, info, seed, iterations, archive))

    status = (
        "HALT_ORIGINAL_FLEET_STANDALONE_CAPACITY_INFEASIBLE"
        if capacity_halts
        else "PASS_EXISTING_FLEET_PILOT_SEEDS_1_TO_3"
    )
    decision = {
        "status": status,
        "instance_id": INSTANCE,
        "families": list(FAMILIES),
        "attempted_seeds": [SEEDS[0]] if capacity_halts else list(SEEDS),
        "not_started_seeds": list(SEEDS[1:]) if capacity_halts else [],
        "iterations_per_view": iterations,
        "archive_candidates_per_view": archive,
        "capacity_bound_semantics": (
            "current static E3 HGS-SP: one selected route consumes one vehicle slot"
        ),
        "capacity_shortfalls": capacity_halts,
        "search_started": not capacity_halts,
        "all_candidate_rows_retained": True,
    }
    fleet_path = REPO / "baselines/china_e3_e7/e3e6_gates_01_20260729/gate1_d2a/fleet_caps.csv"
    metadata = {
        "schema": "resetp.e3-existing-fleet-pilot.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "comparison": list(ARMS),
        "fleet_rule": "use each China81 depot's existing CV and EV maxima",
        "vehicle_mix_rule": "optimizer chooses actual use; no ratio or type quota",
        "route_fleet_semantics": (
            "current static E3 HGS-SP: one selected route consumes one vehicle slot"
        ),
        "ownership_source": "Soriano public Uniform_Balanced and Uniform_Unbalanced p sequences",
        "source_hashes": {
            str(path.relative_to(REPO)): _sha256(path)
            for path in (Path(__file__), HERE / "shared_runtime.py", SOURCE, fleet_path, *PROTECTED)
        },
    }
    write_json(output / "metadata.json", metadata)
    write_csv(output / "raw_runs.csv", rows)
    write_json(output / "decision.json", decision)
    (output / "report.md").write_text(_report(decision, rows), encoding="utf-8")
    write_json(
        output / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "artifacts": {
                name: _sha256(output / name)
                for name in ("metadata.json", "raw_runs.csv", "decision.json", "report.md")
            },
        },
    )
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=PILOT)
    args = parser.parse_args()
    print(json.dumps(run_pilot(args.output), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
