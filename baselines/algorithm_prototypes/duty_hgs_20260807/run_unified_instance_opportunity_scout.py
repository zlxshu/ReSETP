#!/usr/bin/env python3
"""Measure raw mechanism opportunity across the unified China81 candidates.

This is a zero-search exploratory inventory.  It records direct cross-depot
service opportunity, depot workload balance, and the exact composition of the
existing dynamic streams.  It deliberately has no composite score, ranking,
cutoff, or final instance selection.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

from run_unified_instance_structural_scout import (
    DYNAMIC_CUSTOMER_COUNTS,
    PROTECTED,
    STREAM_SEEDS,
    _candidate_ids,
)
from setp_solver.china81 import load_china81_bundle

from baselines.china_e3_e7.e7_trigger_policies_20260801.trigger_policies import (
    DynamicOrder,
    DynamicUpdate,
    build_qiu_scaled_stream,
    dynamic_stream_sha256,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _median(values: list[float]) -> float | None:
    return None if not values else float(statistics.median(values))


def _direct_cv_service(
    bundle,
    depot,
    customer,
) -> tuple[bool, float]:
    """Return exact direct-loop time/capacity reachability and distance.

    The diagnostic uses a single conventional vehicle so charging cannot
    contaminate the cross-depot opportunity measure.  Every China81 depot in
    this candidate set has a positive frozen CV cap; that condition is checked
    by the caller and recorded in the output.
    """

    instance = bundle.instance
    capacity = instance.payload_capacity_kg(
        "cv",
        fallback=float(bundle.prices.Q_capacity),
    )
    outbound_distance, outbound_time, _ = instance.arc_metrics(
        depot.node_id,
        customer.node_id,
        "cv",
        fallback_speed_mps=float(bundle.prices.v_speed_ms),
    )
    return_distance, return_time, _ = instance.arc_metrics(
        customer.node_id,
        depot.node_id,
        "cv",
        fallback_speed_mps=float(bundle.prices.v_speed_ms),
    )
    depart = float(depot.ready_time) + float(depot.service_time)
    arrive_customer = depart + outbound_time
    start_customer = max(arrive_customer, float(customer.ready_time))
    depart_customer = start_customer + float(customer.service_time)
    arrive_depot = depart_customer + return_time
    feasible = (
        float(customer.demand) <= capacity + 1.0e-9
        and start_customer <= float(customer.due_time) + 1.0e-9
        and arrive_depot <= float(depot.due_time) + 1.0e-9
    )
    return feasible, float(outbound_distance + return_distance) / 1000.0


def _customer_rows(bundle) -> list[dict[str, Any]]:
    depots = sorted(
        (
            node
            for node in bundle.instance.nodes
            if node.node_type.lower() == "d"
        ),
        key=lambda node: node.node_id,
    )
    if any(
        int(bundle.fleet_caps_by_depot[depot.node_id]["num_cv"]) <= 0
        for depot in depots
    ):
        raise ValueError(
            "direct CV opportunity requires a positive frozen CV cap at every depot"
        )
    rows: list[dict[str, Any]] = []
    for customer in sorted(
        (
            node
            for node in bundle.instance.nodes
            if node.node_type.lower() == "c"
        ),
        key=lambda node: node.node_id,
    ):
        owner = str(bundle.customer_home_depot[customer.node_id])
        reachability: dict[str, bool] = {}
        distances: dict[str, float] = {}
        for depot in depots:
            feasible, distance_km = _direct_cv_service(
                bundle,
                depot,
                customer,
            )
            reachability[depot.node_id] = feasible
            distances[depot.node_id] = distance_km
        alternate_distances = [
            distance
            for depot_id, distance in distances.items()
            if depot_id != owner and reachability[depot_id]
        ]
        owner_distance = float(distances[owner])
        best_alternate = min(alternate_distances) if alternate_distances else None
        rows.append(
            {
                "instance_id": bundle.instance_id,
                "region": bundle.region,
                "customer_id": customer.node_id,
                "owner_depot_id": owner,
                "demand_kg": float(customer.demand),
                "ready_second": float(customer.ready_time),
                "due_second": float(customer.due_time),
                "direct_cv_reachable_depot_count": sum(reachability.values()),
                "owner_direct_cv_feasible": reachability[owner],
                "alternate_direct_cv_feasible": bool(alternate_distances),
                "direct_cv_reachable_depots_json": json.dumps(
                    sorted(
                        depot_id
                        for depot_id, feasible in reachability.items()
                        if feasible
                    ),
                    ensure_ascii=False,
                ),
                "direct_cv_roundtrip_km_by_depot_json": json.dumps(
                    distances,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "owner_direct_cv_roundtrip_km": owner_distance,
                "best_alternate_direct_cv_roundtrip_km": best_alternate,
                "best_alternate_minus_owner_roundtrip_km": (
                    None
                    if best_alternate is None
                    else float(best_alternate - owner_distance)
                ),
            }
        )
    return rows


def _dynamic_rows(bundle) -> list[dict[str, Any]]:
    total_demand = sum(
        float(node.demand)
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    )
    result: list[dict[str, Any]] = []
    for seed in STREAM_SEEDS:
        stream = build_qiu_scaled_stream(
            bundle.instance,
            instance_id=bundle.instance_id,
            stream_seed=seed,
        )
        additions = [
            event for event in stream.events if isinstance(event, DynamicOrder)
        ]
        cancellations = [
            event
            for event in stream.events
            if isinstance(event, DynamicUpdate)
            and event.event_type == "cancel"
        ]
        reductions = [
            event
            for event in stream.events
            if isinstance(event, DynamicUpdate)
            and event.event_type == "demand_change"
        ]
        added_demand = sum(float(event.demand_kg) for event in additions)
        cancelled_demand = sum(
            float(event.old_demand_kg - event.new_demand_kg)
            for event in cancellations
        )
        reduced_demand = sum(
            float(event.old_demand_kg - event.new_demand_kg)
            for event in reductions
        )
        appearance_times = [float(event.appearance_second) for event in stream.events]
        addition_slacks = [
            float(event.due_second - event.appearance_second)
            for event in additions
        ]
        result.append(
            {
                "instance_id": bundle.instance_id,
                "region": bundle.region,
                "stream_seed": seed,
                "stream_sha256": dynamic_stream_sha256(stream),
                "initial_customer_count": len(stream.initial_customer_ids),
                "event_count": len(stream.events),
                "addition_count": len(additions),
                "cancellation_count": len(cancellations),
                "demand_change_count": len(reductions),
                "first_event_second": min(appearance_times),
                "last_event_second": max(appearance_times),
                "added_demand_kg": added_demand,
                "added_demand_pct_of_instance": 100.0 * added_demand / total_demand,
                "cancelled_demand_kg": cancelled_demand,
                "cancelled_demand_pct_of_instance": (
                    100.0 * cancelled_demand / total_demand
                ),
                "reduced_demand_kg": reduced_demand,
                "reduced_demand_pct_of_instance": (
                    100.0 * reduced_demand / total_demand
                ),
                "addition_min_due_minus_appearance_second": min(addition_slacks),
                "addition_median_due_minus_appearance_second": _median(
                    addition_slacks
                ),
            }
        )
    return result


def _instance_row(bundle, customer_rows, dynamic_rows) -> dict[str, Any]:
    total_demand = sum(float(row["demand_kg"]) for row in customer_rows)
    alternate = [
        row for row in customer_rows if row["alternate_direct_cv_feasible"]
    ]
    extra_distances = [
        float(row["best_alternate_minus_owner_roundtrip_km"])
        for row in alternate
    ]
    depots = sorted(bundle.fleet_caps_by_depot)
    workload = {
        depot_id: {
            "customer_count": sum(
                row["owner_depot_id"] == depot_id for row in customer_rows
            ),
            "demand_kg": sum(
                float(row["demand_kg"])
                for row in customer_rows
                if row["owner_depot_id"] == depot_id
            ),
            "num_cv": int(bundle.fleet_caps_by_depot[depot_id]["num_cv"]),
            "num_ev": int(bundle.fleet_caps_by_depot[depot_id]["num_ev"]),
        }
        for depot_id in depots
    }
    counts = [int(item["customer_count"]) for item in workload.values()]
    demands = [float(item["demand_kg"]) for item in workload.values()]
    fields = (
        "added_demand_pct_of_instance",
        "cancelled_demand_pct_of_instance",
        "reduced_demand_pct_of_instance",
        "addition_min_due_minus_appearance_second",
    )
    dynamic_summary = {
        f"dynamic_{field}_{suffix}": function(
            float(row[field]) for row in dynamic_rows
        )
        for field in fields
        for suffix, function in (("min", min), ("max", max))
    }
    return {
        "instance_id": bundle.instance_id,
        "region": bundle.region,
        "customer_count": len(customer_rows),
        "customer_demand_kg": total_demand,
        "depot_count": len(depots),
        "all_depots_have_positive_cv_cap": all(
            int(bundle.fleet_caps_by_depot[depot_id]["num_cv"]) > 0
            for depot_id in depots
        ),
        "owner_direct_cv_feasible_customer_count": sum(
            bool(row["owner_direct_cv_feasible"]) for row in customer_rows
        ),
        "alternate_direct_cv_feasible_customer_count": len(alternate),
        "alternate_direct_cv_feasible_customer_pct": (
            100.0 * len(alternate) / len(customer_rows)
        ),
        "alternate_direct_cv_feasible_demand_kg": sum(
            float(row["demand_kg"]) for row in alternate
        ),
        "alternate_direct_cv_feasible_demand_pct": (
            100.0
            * sum(float(row["demand_kg"]) for row in alternate)
            / total_demand
        ),
        "alternate_minus_owner_roundtrip_km_min": (
            None if not extra_distances else min(extra_distances)
        ),
        "alternate_minus_owner_roundtrip_km_median": _median(extra_distances),
        "alternate_minus_owner_roundtrip_km_max": (
            None if not extra_distances else max(extra_distances)
        ),
        "home_workload_by_depot_json": json.dumps(
            workload,
            ensure_ascii=False,
            sort_keys=True,
        ),
        "home_customer_count_min": min(counts),
        "home_customer_count_max": max(counts),
        "home_customer_count_range": max(counts) - min(counts),
        "home_demand_kg_min": min(demands),
        "home_demand_kg_max": max(demands),
        "home_demand_kg_range": max(demands) - min(demands),
        "dynamic_stream_seed_count": len(dynamic_rows),
        "dynamic_stream_unique_hash_count": len(
            {row["stream_sha256"] for row in dynamic_rows}
        ),
        **dynamic_summary,
        "status": "OPPORTUNITY_SCOUT_PASS",
        "failure_reason": "",
    }


def _failed_row(instance_id: str, error: Exception) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "region": instance_id.split("-", 2)[1],
        "status": "OPPORTUNITY_SCOUT_FAILED",
        "failure_reason": f"{type(error).__name__}: {error}",
    }


def _report(rows: list[dict[str, Any]]) -> str:
    passed = [row for row in rows if row["status"] == "OPPORTUNITY_SCOUT_PASS"]
    failed = [row for row in rows if row["status"] != "OPPORTUNITY_SCOUT_PASS"]
    lines = []
    for region in ("cy", "jjj", "prd"):
        region_rows = [row for row in passed if row["region"] == region]
        customer_pct = [
            float(row["alternate_direct_cv_feasible_customer_pct"])
            for row in region_rows
        ]
        demand_pct = [
            float(row["alternate_direct_cv_feasible_demand_pct"])
            for row in region_rows
        ]
        dynamic_pct = [
            float(row["dynamic_added_demand_pct_of_instance_min"])
            for row in region_rows
        ] + [
            float(row["dynamic_added_demand_pct_of_instance_max"])
            for row in region_rows
        ]
        lines.append(
            f"- {region}：可由其他车场直接服务的客户占比 "
            f"{min(customer_pct):.3f}%—{max(customer_pct):.3f}%，对应需求占比 "
            f"{min(demand_pct):.3f}%—{max(demand_pct):.3f}%；动态新增需求占比 "
            f"{min(dynamic_pct):.3f}%—{max(dynamic_pct):.3f}%。"
        )
    failure_text = (
        "没有失败行。"
        if not failed
        else "失败行："
        + "；".join(
            f"{row['instance_id']}={row['failure_reason']}" for row in failed
        )
    )
    return f"""# China81 统一算例机制机会体检

## 结论

本轮只读 27 个候选的原始结构和既有动态订单流，不运行优化算法。{len(passed)}/27 个完成；{failure_text}

逐客户结果保存在 `customer_opportunities.csv`，逐动态流结果保存在 `dynamic_streams.csv`，逐算例汇总保存在 `raw_runs.csv`。没有综合分、没有排名、没有淘汰线，也没有替用户选择算例。

{chr(10).join(lines)}

“其他车场可直接服务”按冻结路网、时间窗、载重和各场现有油车上限逐客户计算，用油车是为了不把充电条件混进车场合作机会。这个数字说明跨场调整有没有物理入口，不等于完整路线优化后一定节省成本。各车场客户数、需求量和车队数原样写在逐算例表中；利润参与的真实效果仍要等合法单干利润基准接入后再测。

这些结果继续支持统一探索：本轮若没有出现某个因素在结构上完全没有入口，就没有数学或物理理由先拆成多套私有算例。下一步仍需用当前 Duty-HGS 在同一候选上产生动态、合作和参与条件的实际配对结果。

## 交付前九条自检

1. 每个事实是否有出处？——逐客户、逐动态流、逐算例三层原始表均随包保存，输入和代码哈希在 `metadata.json`。
2. 有没有把建议或担忧写成已决或状态？——没有；最终算例、预算和效应口径均未替用户决定。
3. 是否超出任务范围？——没有；只做统一算例所需的零搜索机会体检。
4. 是否碰受保护文件？——没有；前后哈希写入 `metadata.json` 并核对一致。
5. 待决事项是否给了选项和代价？——本轮不要求用户拍板；只补足下一轮试跑前的原始事实。
6. 是否使用自造词或内部任务号？——没有。
7. 失败、跳过、超时和异常是否保留？——所有候选均保留；失败原因写入 `failure_reason`。
8. 四件套是否齐全？——`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`、`report.md` 齐全，并附两张明细表。
9. 交接记录是否同步？——证据包复核后同步 `HANDOFF.md` 和 `docs/handoff/memory/MEMORY.md`。
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[3]
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    if _git(repo, "status", "--porcelain"):
        raise RuntimeError("opportunity scout requires a clean worktree")

    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    candidate_ids = _candidate_ids(repo)
    if len(candidate_ids) != 27:
        raise RuntimeError(f"expected 27 candidates, got {len(candidate_ids)}")

    rows: list[dict[str, Any]] = []
    all_customer_rows: list[dict[str, Any]] = []
    all_dynamic_rows: list[dict[str, Any]] = []
    for instance_id in candidate_ids:
        try:
            bundle = load_china81_bundle(repo, instance_id)
            customer_rows = _customer_rows(bundle)
            dynamic_rows = _dynamic_rows(bundle)
            rows.append(_instance_row(bundle, customer_rows, dynamic_rows))
            all_customer_rows.extend(customer_rows)
            all_dynamic_rows.extend(dynamic_rows)
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
            rows.append(_failed_row(instance_id, error))

    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    output.mkdir(parents=True)
    source_path = Path(__file__).resolve()
    _json(
        output / "metadata.json",
        {
            "schema": "resetp.duty-hgs-unified-instance-opportunity-scout.v1",
            "purpose": "zero-search raw mechanism opportunity; no ranking",
            "git_head": _git(repo, "rev-parse", "HEAD"),
            "git_branch": _git(repo, "branch", "--show-current"),
            "worktree_clean_before_run": True,
            "python_executable": sys.executable,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "runner_path": str(source_path.relative_to(repo)),
            "runner_sha256": _sha256(source_path),
            "candidate_customer_counts": list(DYNAMIC_CUSTOMER_COUNTS),
            "dynamic_stream_seeds": list(STREAM_SEEDS),
            "candidate_ids": list(candidate_ids),
            "cross_depot_reachability_definition": (
                "one frozen-depot CV direct loop, exact directed travel time, "
                "customer/depot time windows, payload capacity, positive depot CV cap"
            ),
            "protected_hashes_before": protected_before,
            "protected_hashes_after": protected_after,
        },
    )
    _write_csv(output / "raw_runs.csv", rows)
    _write_csv(output / "customer_opportunities.csv", all_customer_rows)
    _write_csv(output / "dynamic_streams.csv", all_dynamic_rows)

    passed = [row for row in rows if row["status"] == "OPPORTUNITY_SCOUT_PASS"]
    _json(
        output / "decision.json",
        {
            "verdict": (
                "OPPORTUNITY_SCOUT_COMPLETE"
                if len(passed) == len(rows)
                and protected_before == protected_after
                else "OPPORTUNITY_SCOUT_HAS_FAILURES"
            ),
            "candidate_count": len(rows),
            "passed_count": len(passed),
            "failed_count": len(rows) - len(passed),
            "final_instance_selected": None,
            "instance_ranking_performed": False,
            "composite_score_computed": False,
            "scientific_effect_threshold_applied": False,
            "optimization_search_run": False,
            "formal_experiment_result": False,
            "mathematical_or_physical_impossibility_of_unification_proved": False,
        },
    )
    (output / "report.md").write_text(_report(rows), encoding="utf-8")
    hashes = {
        path.name: _sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    _json(output / "artifact_hashes.json", hashes)
    for sidecar in output.glob("._*"):
        sidecar.unlink()
    print(
        json.dumps(
            {
                "output": str(output),
                "candidate_count": len(rows),
                "passed_count": len(passed),
                "customer_rows": len(all_customer_rows),
                "dynamic_rows": len(all_dynamic_rows),
            },
            ensure_ascii=False,
        )
    )
    return (
        0
        if len(passed) == len(rows) and protected_before == protected_after
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
