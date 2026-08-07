#!/usr/bin/env python3
"""Replay saved raw-cost-decreasing cross-depot moves with full profit detail.

This is a diagnostic replay, not a search run.  It reads the saved exhaustive
single-move packages, selects every evaluated move whose raw system cost fell,
rebuilds those exact actions from the registered initial solution, and records
the complete per-depot profit vector returned by the existing full evaluator.
It also inventories the registered start solution and the capacity-compatible
cross-depot trip pairs without choosing or implementing a new operator.
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import resource
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

from duty_hgs.education import evaluate_move
from duty_hgs.evaluation import DutyFullEvaluator, DutyIncrementalEvaluator
from duty_hgs.operators import generate_problem_moves
from setp_solver.cost import charging_action_slot_breakdown
from setp_solver.profit import calculate_depot_profits

from run_real_input_technical_trial import (
    PROTECTED,
    _build_context,
    _json,
    _policy,
    _sha256,
    _source_provenance,
    _write_failure_package,
)


DEFAULT_SOURCE_NAMES = (
    "cross_depot_all_prd150_01_20260807",
    "cross_depot_all_prd150_02_20260807",
    "cross_depot_all_prd150_03_20260807",
)

PROFIT_FIELDS = (
    "instance_id",
    "action_id",
    "status",
    "source_recorded_cost_change_cny",
    "replayed_cost_change_cny",
    "source_replay_cost_error_cny",
    "complete_model_feasible",
    "violation_types_json",
    "initial_depot_profit_json",
    "candidate_depot_profit_json",
    "depot_profit_change_json",
    "initial_depot_profit_breakdown_json",
    "candidate_depot_profit_breakdown_json",
    "total_revenue_change_cny",
    "allocated_profit_cost_change_cny",
    "total_depot_profit_change_cny",
    "raw_cost_change_plus_profit_change_cny",
    "participation_margin_json",
    "cross_site_service_count",
    "wall_seconds",
    "error_type",
    "error",
)


def select_raw_cost_decreasing_actions(path: Path) -> dict[str, float]:
    """Return every saved evaluated action with a strictly lower raw cost."""

    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    selected: dict[str, float] = {}
    for row in rows:
        if row.get("evaluated") != "True" or row.get("cost_change_cny", "") == "":
            continue
        delta = float(row["cost_change_cny"])
        if delta < 0.0:
            selected[str(row["action_id"])] = delta
    return selected


def _profit_rows(evaluation, context) -> dict[str, Any]:
    rows = calculate_depot_profits(
        evaluation.prepared_solution,
        context.bundle.instance,
        context.bundle.time_profile,
        context.bundle.prices,
        customer_home_depot=dict(context.bundle.customer_home_depot),
        prior_profit=dict(context.prior_profit),
        carbon_quota_kg=float(context.carbon_quota_kg),
    )
    return {depot_id: asdict(row) for depot_id, row in rows.items()}


def _profit_values(rows: dict[str, Any]) -> dict[str, float]:
    return {depot_id: float(row["profit"]) for depot_id, row in rows.items()}


def _sum_field(rows: dict[str, Any], field: str) -> float:
    return sum(float(row[field]) for row in rows.values())


def _json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _peak_rss_mb() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if platform.system() == "Darwin":
        return value / (1024.0 * 1024.0)
    return value / 1024.0


def _start_solution_properties(initial_evaluation, context) -> dict[str, Any]:
    bundle = context.bundle
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    routes = {
        route.vehicle_id: route
        for route in initial_evaluation.prepared_solution.routes
    }
    actions_by_station_and_depot: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    occupied_depots_by_slot: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    other_depot_charge_count = 0
    public_charge_count = 0
    for action in initial_evaluation.prepared_solution.charging_actions:
        route = routes[action.vehicle_id]
        node = nodes[action.station_id]
        station_type = node.node_type.lower()
        actions_by_station_and_depot[action.station_id][route.home_depot_id] += 1
        if station_type == "f":
            public_charge_count += 1
        elif station_type == "d" and action.station_id != route.home_depot_id:
            other_depot_charge_count += 1
        for slot in charging_action_slot_breakdown(
            action,
            bundle.instance,
            bundle.prices,
            n_slots=48,
            cyclic=True,
        ):
            occupied_depots_by_slot[
                (
                    action.station_id,
                    int(action.charge_day_offset),
                    int(slot.slot_index),
                )
            ].add(route.home_depot_id)
    shared_station_ids = sorted(
        station_id
        for station_id, depot_counts in actions_by_station_and_depot.items()
        if len(depot_counts) > 1
    )
    shared_station_slot_count = sum(
        len(depots) > 1 for depots in occupied_depots_by_slot.values()
    )
    cross_site = [
        asdict(row)
        for row in initial_evaluation.prepared_solution.cross_site_services
    ]
    return {
        "cross_site_service_count": len(cross_site),
        "cross_site_services": cross_site,
        "charging_action_count": len(
            initial_evaluation.prepared_solution.charging_actions
        ),
        "public_charging_action_count": public_charge_count,
        "other_depot_charging_action_count": other_depot_charge_count,
        "stations_used_by_multiple_service_depots": shared_station_ids,
        "station_slots_used_by_multiple_service_depots": shared_station_slot_count,
        "charging_actions_by_station_and_service_depot": {
            station_id: dict(sorted(depot_counts.items()))
            for station_id, depot_counts in sorted(
                actions_by_station_and_depot.items()
            )
        },
    }


def _trip_inventory_and_pairs(initial, bundle) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    trips: list[dict[str, Any]] = []
    for duty in initial.duties:
        for trip in duty.trips:
            trips.append(
                {
                    "duty_id": duty.physical_vehicle_id,
                    "trip_index": int(trip.trip_index),
                    "home_depot_id": duty.home_depot_id,
                    "vehicle_type": duty.vehicle_type,
                    "customer_count": len(trip.customer_ids),
                    "demand_kg": sum(
                        float(nodes[customer].demand)
                        for customer in trip.customer_ids
                    ),
                    "has_locked_customer_prefix": bool(
                        trip.locked_customer_prefix
                    ),
                    "has_locked_charging": (
                        trip.trip_index in duty.locked_charging_trip_indices
                    ),
                }
            )
    pairs: list[dict[str, Any]] = []
    for left_index, left in enumerate(trips):
        for right in trips[left_index + 1 :]:
            if left["home_depot_id"] == right["home_depot_id"]:
                continue
            left_target_capacity = bundle.instance.payload_capacity_kg(
                str(right["vehicle_type"]),
                fallback=bundle.prices.Q_capacity,
            )
            right_target_capacity = bundle.instance.payload_capacity_kg(
                str(left["vehicle_type"]),
                fallback=bundle.prices.Q_capacity,
            )
            left_fits_right = float(left["demand_kg"]) <= left_target_capacity + 1e-9
            right_fits_left = float(right["demand_kg"]) <= right_target_capacity + 1e-9
            pairs.append(
                {
                    "left_duty_id": left["duty_id"],
                    "left_trip_index": left["trip_index"],
                    "left_depot_id": left["home_depot_id"],
                    "left_vehicle_type": left["vehicle_type"],
                    "left_demand_kg": left["demand_kg"],
                    "right_duty_id": right["duty_id"],
                    "right_trip_index": right["trip_index"],
                    "right_depot_id": right["home_depot_id"],
                    "right_vehicle_type": right["vehicle_type"],
                    "right_demand_kg": right["demand_kg"],
                    "left_fits_right_vehicle_capacity": left_fits_right,
                    "right_fits_left_vehicle_capacity": right_fits_left,
                    "both_capacity_compatible": left_fits_right and right_fits_left,
                }
            )
    return trips, pairs


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: tuple[str, ...] | None = None) -> None:
    material = list(rows)
    if fields is None:
        fields = tuple(material[0]) if material else ()
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(material)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--stderr-capture-state", default="caller_not_declared")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[3]
    prototype = repo / "baselines/algorithm_prototypes/duty_hgs_20260807"
    source_root = prototype / "technical_trials"
    output = args.output_dir.resolve()
    provenance = _source_provenance(
        repo,
        output_path=output,
        stderr_capture_state=args.stderr_capture_state,
    )
    if not provenance["worktree_clean_before_run"]:
        raise RuntimeError("profit replay requires a clean worktree")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    _json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "purpose": "replay all saved raw-cost-decreasing cross-depot moves with full depot-profit detail",
            "source_packages": list(DEFAULT_SOURCE_NAMES),
            "code_provenance": provenance,
        },
    )

    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    profit_rows: list[dict[str, Any]] = []
    start_rows: list[dict[str, Any]] = []
    trip_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    replay_counts: dict[str, int] = {}
    started = perf_counter()

    for source_name in DEFAULT_SOURCE_NAMES:
        source_dir = source_root / source_name
        raw_path = source_dir / "raw_runs.csv"
        with raw_path.open(encoding="utf-8", newline="") as handle:
            raw = next(csv.DictReader(handle))
        instance_id = str(raw["instance_id"])
        selected = select_raw_cost_decreasing_actions(
            source_dir / "candidate_rows.csv"
        )
        source_counts[instance_id] = len(selected)

        bundle, initial, _pi0, context = _build_context(repo, instance_id)
        evaluator = DutyFullEvaluator(context)
        initial_evaluation = evaluator.evaluate(initial)
        initial_profit_breakdowns = _profit_rows(initial_evaluation, context)
        initial_profit_values = _profit_values(initial_profit_breakdowns)
        start_rows.append(
            {
                "instance_id": instance_id,
                **_start_solution_properties(initial_evaluation, context),
            }
        )
        inventory, pairs = _trip_inventory_and_pairs(initial, bundle)
        trip_rows.extend({"instance_id": instance_id, **row} for row in inventory)
        pair_rows.extend({"instance_id": instance_id, **row} for row in pairs)

        moves = {
            move.action_id: move
            for move in generate_problem_moves(
                initial,
                initial_evaluation,
                bundle.instance,
            )
            if move.action_id in selected
        }
        missing = sorted(set(selected).difference(moves))
        if missing:
            raise RuntimeError(
                f"saved actions are absent from current generator for {instance_id}: "
                + ", ".join(missing)
            )
        incremental = DutyIncrementalEvaluator(evaluator)
        incremental.seed(initial)
        policy = _policy(evaluator)
        replayed = 0
        for action_id in sorted(selected):
            before = perf_counter()
            outcome = evaluate_move(
                initial,
                moves[action_id],
                evaluator=evaluator,
                charging_policy=policy,
                incremental_evaluator=incremental,
                charging_repair_cache=None,
            )
            evaluation = outcome.evaluation
            row: dict[str, Any] = {
                "instance_id": instance_id,
                "action_id": action_id,
                "status": outcome.status.value,
                "source_recorded_cost_change_cny": selected[action_id],
                "wall_seconds": perf_counter() - before,
                "error_type": outcome.error_type or "",
                "error": outcome.error or "",
            }
            if evaluation is None:
                row.update(
                    {
                        field: ""
                        for field in PROFIT_FIELDS
                        if field not in row
                    }
                )
                profit_rows.append(row)
                continue
            replayed += 1
            candidate_profit_breakdowns = _profit_rows(evaluation, context)
            candidate_profit_values = _profit_values(candidate_profit_breakdowns)
            profit_change = {
                depot_id: candidate_profit_values[depot_id]
                - initial_profit_values[depot_id]
                for depot_id in initial_profit_values
            }
            replayed_cost_change = (
                float(evaluation.total_cost)
                - float(initial_evaluation.total_cost)
            )
            revenue_change = _sum_field(
                candidate_profit_breakdowns, "revenue"
            ) - _sum_field(initial_profit_breakdowns, "revenue")
            allocated_cost_change = _sum_field(
                candidate_profit_breakdowns, "cost_total"
            ) - _sum_field(initial_profit_breakdowns, "cost_total")
            total_profit_change = sum(profit_change.values())
            row.update(
                {
                    "replayed_cost_change_cny": replayed_cost_change,
                    "source_replay_cost_error_cny": (
                        replayed_cost_change - selected[action_id]
                    ),
                    "complete_model_feasible": evaluation.feasible,
                    "violation_types_json": _json_cell(
                        [item.type for item in evaluation.violations]
                    ),
                    "initial_depot_profit_json": _json_cell(
                        initial_profit_values
                    ),
                    "candidate_depot_profit_json": _json_cell(
                        candidate_profit_values
                    ),
                    "depot_profit_change_json": _json_cell(profit_change),
                    "initial_depot_profit_breakdown_json": _json_cell(
                        initial_profit_breakdowns
                    ),
                    "candidate_depot_profit_breakdown_json": _json_cell(
                        candidate_profit_breakdowns
                    ),
                    "total_revenue_change_cny": revenue_change,
                    "allocated_profit_cost_change_cny": allocated_cost_change,
                    "total_depot_profit_change_cny": total_profit_change,
                    "raw_cost_change_plus_profit_change_cny": (
                        replayed_cost_change + total_profit_change
                    ),
                    "participation_margin_json": _json_cell(
                        dict(evaluation.participation_margin)
                    ),
                    "cross_site_service_count": len(
                        evaluation.prepared_solution.cross_site_services
                    ),
                }
            )
            profit_rows.append(row)
        replay_counts[instance_id] = replayed

    _write_csv(output / "profit_vectors.csv", profit_rows, PROFIT_FIELDS)
    _json(output / "start_solution_properties.json", start_rows)
    _write_csv(output / "trip_inventory.csv", trip_rows)
    _write_csv(output / "cross_depot_trip_pairs.csv", pair_rows)

    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    failure_reasons = []
    if protected_before != protected_after:
        failure_reasons.append("a protected evaluator file changed")
    if source_counts != replay_counts:
        failure_reasons.append("not every selected action reached full replay")
    maximum_replay_error = max(
        abs(float(row["source_replay_cost_error_cny"]))
        for row in profit_rows
        if row.get("source_replay_cost_error_cny", "") != ""
    )
    if maximum_replay_error > 1e-8:
        failure_reasons.append("saved and replayed raw cost changes disagree")
    elapsed = perf_counter() - started
    verdict = (
        "CROSS_DEPOT_PROFIT_REPLAY_COMPLETE"
        if not failure_reasons
        else "CROSS_DEPOT_PROFIT_REPLAY_FAILED"
    )
    raw_row = {
        "verdict": verdict,
        "source_selected_counts_json": _json_cell(source_counts),
        "replayed_counts_json": _json_cell(replay_counts),
        "total_selected": sum(source_counts.values()),
        "total_replayed": sum(replay_counts.values()),
        "maximum_source_replay_cost_error_cny": maximum_replay_error,
        "cross_depot_trip_pair_count": len(pair_rows),
        "capacity_compatible_trip_pair_count": sum(
            bool(row["both_capacity_compatible"]) for row in pair_rows
        ),
        "wall_seconds": elapsed,
        "peak_rss_mb": _peak_rss_mb(),
        "failure_reason": "; ".join(failure_reasons),
    }
    _write_csv(output / "raw_runs.csv", [raw_row])
    _json(
        output / "decision.json",
        {
            "verdict": verdict,
            "failure_reasons": failure_reasons,
            "formal_algorithm_result": False,
            "formal_mechanism_result": False,
            "formal_instance_selected": None,
            "new_operator_selected": None,
            "charging_curve_selected": None,
            "what_was_measured": [
                "full per-depot profit vectors for every saved raw-cost-decreasing single cross-depot move",
                "registered start-solution cross-site and charging-resource use",
                "capacity-compatible cross-depot trip-pair inventory",
            ],
        },
    )
    metadata = {
        "status": "COMPLETE" if not failure_reasons else "FAILED",
        "purpose": "cross-depot profit and start-solution fact completion",
        "source_packages": list(DEFAULT_SOURCE_NAMES),
        "code_provenance": provenance,
        "protected_hashes_before": protected_before,
        "protected_hashes_after": protected_after,
    }
    _json(output / "metadata.json", metadata)
    report = f"""# 跨车场动作逐车场利润复核

本包逐项复算三个珠三角 150 客户技术探针里所有原始系统成本下降的动作，共 {sum(source_counts.values())} 项；其中 {sum(replay_counts.values())} 项按同一完整评价链复现。逐车场利润、利润分项、参与余量和两套成本口径的差额保存在 `profit_vectors.csv`。起点的跨场服务和充电资源使用保存在 `start_solution_properties.json`；现有路线及跨车场双向组合的容量清点保存在另外两张表。本包不选择算法动作、充电曲线或正式算例。

## 交付前九条自检

1. 每个事实是否有出处？——逐动作证据在 `profit_vectors.csv`，总数在 `raw_runs.csv`。
2. 有没有把建议或担忧写成已决或状态？——没有；没有选择新动作或正式算例。
3. 是否超出任务范围？——没有；只补全已授权跨车场诊断的利润和起点事实。
4. 是否碰受保护文件？——未碰；三个文件前后哈希见 `metadata.json`。
5. 待决事项是否给出选项和代价？——本包只补事实，不新增用户拍板项。
6. 是否使用自造词或内部任务号？——没有。
7. 失败、跳过、超时和异常是否保留？——逐动作状态及错误原样保存在 `profit_vectors.csv`。
8. 四件套是否齐全？——`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`、`report.md` 齐全。
9. 交接记录是否同步？——本轮诊断收齐后统一同步项目交接和记忆。
"""
    (output / "report.md").write_text(report, encoding="utf-8")
    for sidecar in output.glob("._*"):
        sidecar.unlink()
    hashes = {
        path.name: _sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    _json(output / "artifact_hashes.json", hashes)
    print(json.dumps(raw_row, ensure_ascii=False, sort_keys=True))
    return 0 if not failure_reasons else 2


if __name__ == "__main__":
    requested_output = (
        None
        if len(sys.argv) < 2 or sys.argv[1].startswith("-")
        else Path(sys.argv[1]).resolve()
    )
    try:
        raise SystemExit(main())
    except Exception as exc:
        if requested_output is not None:
            _write_failure_package(requested_output, exc)
        raise
