#!/usr/bin/env python3
"""Measure cross-depot opportunity on the registered route skeletons.

The earlier opportunity inventory compared depot-to-customer direct loops.
That proves basic reachability, but it is not the marginal cost of moving a
customer between existing routes.  This zero-search screen therefore records
the exact distance change on the current customer sequences for every
cross-depot relocate and swap.  It keeps every customer in the output and does
not use the measurements to rank or select an instance.
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from run_real_input_technical_trial import (
    PROTECTED,
    _build_context,
    _json,
    _sha256,
    _write_failure_package,
)
from run_unified_instance_structural_scout import _candidate_ids, _git


Distance = Callable[[str, str], float]


@dataclass(frozen=True)
class CustomerPosition:
    customer_id: str
    home_depot_id: str
    duty_id: str
    trip_index: int
    position: int
    vehicle_type: str
    customer_ids: tuple[str, ...]
    demand_kg: float
    route_load_kg: float
    route_capacity_kg: float


def _remove_saving(
    home_depot_id: str,
    customer_ids: tuple[str, ...],
    position: int,
    distance: Distance,
) -> float:
    customer_id = customer_ids[position]
    previous_id = (
        home_depot_id if position == 0 else customer_ids[position - 1]
    )
    next_id = (
        home_depot_id
        if position + 1 == len(customer_ids)
        else customer_ids[position + 1]
    )
    return (
        distance(previous_id, customer_id)
        + distance(customer_id, next_id)
        - distance(previous_id, next_id)
    )


def _insertion_delta(
    home_depot_id: str,
    customer_ids: tuple[str, ...],
    position: int,
    customer_id: str,
    distance: Distance,
) -> float:
    previous_id = (
        home_depot_id if position == 0 else customer_ids[position - 1]
    )
    next_id = (
        home_depot_id
        if position == len(customer_ids)
        else customer_ids[position]
    )
    return (
        distance(previous_id, customer_id)
        + distance(customer_id, next_id)
        - distance(previous_id, next_id)
    )


def _replacement_delta(
    home_depot_id: str,
    customer_ids: tuple[str, ...],
    position: int,
    replacement_id: str,
    distance: Distance,
) -> float:
    original_id = customer_ids[position]
    previous_id = (
        home_depot_id if position == 0 else customer_ids[position - 1]
    )
    next_id = (
        home_depot_id
        if position + 1 == len(customer_ids)
        else customer_ids[position + 1]
    )
    return (
        distance(previous_id, replacement_id)
        + distance(replacement_id, next_id)
        - distance(previous_id, original_id)
        - distance(original_id, next_id)
    )


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


def _direct_opportunities(repo: Path) -> dict[tuple[str, str], float]:
    path = (
        repo
        / "baselines/algorithm_prototypes/duty_hgs_20260807/"
        "unified_instance_scout/opportunity_27_20260807/"
        "customer_opportunities.csv"
    )
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            (row["instance_id"], row["customer_id"]): float(
                row["best_alternate_minus_owner_roundtrip_km"]
            )
            for row in csv.DictReader(handle)
        }


def _positions(bundle, individual) -> list[CustomerPosition]:
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    rows: list[CustomerPosition] = []
    for duty in individual.duties:
        capacity = bundle.instance.payload_capacity_kg(
            duty.vehicle_type,
            fallback=float(bundle.prices.Q_capacity),
        )
        for trip in duty.trips:
            customer_ids = tuple(trip.customer_ids)
            route_load = sum(float(nodes[item].demand) for item in customer_ids)
            for position, customer_id in enumerate(customer_ids):
                rows.append(
                    CustomerPosition(
                        customer_id=customer_id,
                        home_depot_id=duty.home_depot_id,
                        duty_id=duty.physical_vehicle_id,
                        trip_index=int(trip.trip_index),
                        position=position,
                        vehicle_type=duty.vehicle_type,
                        customer_ids=customer_ids,
                        demand_kg=float(nodes[customer_id].demand),
                        route_load_kg=route_load,
                        route_capacity_kg=float(capacity),
                    )
                )
    return rows


def _relocate_rows(bundle, positions: list[CustomerPosition]) -> list[dict[str, Any]]:
    distance = bundle.instance.distance
    trips = {
        (row.duty_id, row.trip_index): row
        for row in positions
    }
    result: list[dict[str, Any]] = []
    for source in positions:
        removal = _remove_saving(
            source.home_depot_id,
            source.customer_ids,
            source.position,
            distance,
        )
        best_any: tuple[float, CustomerPosition, int, float] | None = None
        best_capacity: tuple[float, CustomerPosition, int, float] | None = None
        for target in trips.values():
            if target.home_depot_id == source.home_depot_id:
                continue
            for position in range(len(target.customer_ids) + 1):
                insertion = _insertion_delta(
                    target.home_depot_id,
                    target.customer_ids,
                    position,
                    source.customer_id,
                    distance,
                )
                candidate = (insertion - removal, target, position, insertion)
                if best_any is None or candidate[0] < best_any[0]:
                    best_any = candidate
                if (
                    target.route_load_kg + source.demand_kg
                    <= target.route_capacity_kg + 1.0e-9
                    and (best_capacity is None or candidate[0] < best_capacity[0])
                ):
                    best_capacity = candidate
        if best_any is None:
            raise RuntimeError(
                f"{bundle.instance_id} has no alternate-depot target trip"
            )
        capacity_delta = None if best_capacity is None else best_capacity[0]
        result.append(
            {
                "instance_id": bundle.instance_id,
                "region": bundle.region,
                "customer_id": source.customer_id,
                "source_depot_id": source.home_depot_id,
                "source_duty_id": source.duty_id,
                "source_trip_index": source.trip_index,
                "demand_kg": source.demand_kg,
                "removal_saving_km": removal / 1000.0,
                "best_any_target_depot_id": best_any[1].home_depot_id,
                "best_any_target_duty_id": best_any[1].duty_id,
                "best_any_target_trip_index": best_any[1].trip_index,
                "best_any_target_position": best_any[2],
                "best_any_insertion_delta_km": best_any[3] / 1000.0,
                "best_any_relocate_net_delta_km": best_any[0] / 1000.0,
                "best_capacity_target_depot_id": (
                    "" if best_capacity is None else best_capacity[1].home_depot_id
                ),
                "best_capacity_target_duty_id": (
                    "" if best_capacity is None else best_capacity[1].duty_id
                ),
                "best_capacity_target_trip_index": (
                    "" if best_capacity is None else best_capacity[1].trip_index
                ),
                "best_capacity_target_position": (
                    "" if best_capacity is None else best_capacity[2]
                ),
                "best_capacity_relocate_net_delta_km": (
                    "" if capacity_delta is None else capacity_delta / 1000.0
                ),
                "best_any_distance_reducing": best_any[0] < 0.0,
                "best_capacity_distance_reducing": (
                    False if capacity_delta is None else capacity_delta < 0.0
                ),
            }
        )
    return result


def _swap_summary(
    bundle,
    positions: list[CustomerPosition],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    distance = bundle.instance.distance
    best_any: dict[str, tuple[float, CustomerPosition] | None] = {
        row.customer_id: None for row in positions
    }
    best_capacity: dict[str, tuple[float, CustomerPosition] | None] = {
        row.customer_id: None for row in positions
    }
    cross_pairs = 0
    negative_any = 0
    capacity_pairs = 0
    negative_capacity = 0
    for left_index, left in enumerate(positions):
        for right in positions[left_index + 1 :]:
            if left.home_depot_id == right.home_depot_id:
                continue
            cross_pairs += 1
            delta = _replacement_delta(
                left.home_depot_id,
                left.customer_ids,
                left.position,
                right.customer_id,
                distance,
            ) + _replacement_delta(
                right.home_depot_id,
                right.customer_ids,
                right.position,
                left.customer_id,
                distance,
            )
            if delta < 0.0:
                negative_any += 1
            for source, partner in ((left, right), (right, left)):
                current = best_any[source.customer_id]
                if current is None or delta < current[0]:
                    best_any[source.customer_id] = (delta, partner)
            capacity_ok = (
                left.route_load_kg - left.demand_kg + right.demand_kg
                <= left.route_capacity_kg + 1.0e-9
                and right.route_load_kg - right.demand_kg + left.demand_kg
                <= right.route_capacity_kg + 1.0e-9
            )
            if not capacity_ok:
                continue
            capacity_pairs += 1
            if delta < 0.0:
                negative_capacity += 1
            for source, partner in ((left, right), (right, left)):
                current = best_capacity[source.customer_id]
                if current is None or delta < current[0]:
                    best_capacity[source.customer_id] = (delta, partner)
    by_customer = {
        customer_id: {
            "best_any_swap_partner_customer_id": (
                "" if item is None else item[1].customer_id
            ),
            "best_any_swap_partner_depot_id": (
                "" if item is None else item[1].home_depot_id
            ),
            "best_any_swap_total_delta_km": (
                "" if item is None else item[0] / 1000.0
            ),
            "best_capacity_swap_partner_customer_id": (
                "" if best_capacity[customer_id] is None
                else best_capacity[customer_id][1].customer_id
            ),
            "best_capacity_swap_partner_depot_id": (
                "" if best_capacity[customer_id] is None
                else best_capacity[customer_id][1].home_depot_id
            ),
            "best_capacity_swap_total_delta_km": (
                "" if best_capacity[customer_id] is None
                else best_capacity[customer_id][0] / 1000.0
            ),
        }
        for customer_id, item in best_any.items()
    }
    return by_customer, {
        "cross_depot_swap_pair_count": cross_pairs,
        "distance_reducing_swap_pair_count": negative_any,
        "capacity_feasible_swap_pair_count": capacity_pairs,
        "capacity_feasible_distance_reducing_swap_pair_count": negative_capacity,
    }


def _instance_rows(
    repo: Path,
    instance_id: str,
    direct: dict[tuple[str, str], float],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    bundle, individual, _pi0, _context = _build_context(repo, instance_id)
    positions = _positions(bundle, individual)
    relocate = _relocate_rows(bundle, positions)
    swaps, swap_counts = _swap_summary(bundle, positions)
    customers: list[dict[str, Any]] = []
    for row in relocate:
        direct_delta = direct[(instance_id, row["customer_id"])]
        merged = {
            **row,
            **swaps[row["customer_id"]],
            "saved_direct_roundtrip_delta_km": direct_delta,
            "saved_direct_roundtrip_distance_reducing": direct_delta < 0.0,
        }
        customers.append(merged)
    capacity_relocate = [
        float(row["best_capacity_relocate_net_delta_km"])
        for row in customers
        if row["best_capacity_relocate_net_delta_km"] != ""
    ]
    direct_negative = sum(
        bool(row["saved_direct_roundtrip_distance_reducing"])
        for row in customers
    )
    marginal_negative = sum(
        bool(row["best_capacity_distance_reducing"])
        for row in customers
    )
    return (
        {
            "instance_id": bundle.instance_id,
            "region": bundle.region,
            "customer_count": len(customers),
            "customer_demand_kg": sum(float(row["demand_kg"]) for row in customers),
            "saved_direct_roundtrip_distance_reducing_customer_count": direct_negative,
            "capacity_feasible_distance_reducing_relocate_customer_count": marginal_negative,
            "new_distance_reducing_relocate_customer_count_vs_direct_screen": sum(
                bool(row["best_capacity_distance_reducing"])
                and not bool(row["saved_direct_roundtrip_distance_reducing"])
                for row in customers
            ),
            "capacity_feasible_relocate_delta_km_min": min(capacity_relocate),
            "capacity_feasible_relocate_delta_km_median": statistics.median(
                capacity_relocate
            ),
            "capacity_feasible_relocate_delta_km_max": max(capacity_relocate),
            **swap_counts,
            "status": "MARGINAL_SCREEN_PASS",
            "failure_reason": "",
        },
        customers,
    )


def _report(rows: list[dict[str, Any]]) -> str:
    passed = [row for row in rows if row["status"] == "MARGINAL_SCREEN_PASS"]
    direct = sum(
        int(row["saved_direct_roundtrip_distance_reducing_customer_count"])
        for row in passed
    )
    marginal = sum(
        int(row["capacity_feasible_distance_reducing_relocate_customer_count"])
        for row in passed
    )
    swaps = sum(
        int(row["capacity_feasible_distance_reducing_swap_pair_count"])
        for row in passed
    )
    return f"""# China81 跨车场路线边际机会复核

本轮不运行优化算法，只在 27 个登记起点的客户顺序上重新计算跨车场动作的距离变化。旧口径比较车场到客户的直接往返距离；本轮口径计算从当前路线删除客户的边际节省，以及插入另一车场现有路线的边际增加。两者不是同一件事。

{len(passed)}/27 个算例完成。旧直接往返口径共识别 {direct} 名距离更短的客户；当前路线且接收趟载重可容纳的 relocate 口径共识别 {marginal} 名；载重可容纳且总距离下降的跨场 swap 共有 {swaps} 对。逐客户结果全部保存在 `customer_marginals.csv`，没有只保留负值，也没有据此排名或选择算例。

这些数字依赖登记起点的具体路线，只说明现有单步邻域附近有没有距离机会。它们不包含时间窗、充电、利润底线和完整成本，不能替代完整评价，也不能证明某个算例最终有效或无效。

## 交付前九条自检

1. 每个事实是否有出处？——逐客户边际在 `customer_marginals.csv`，逐算例汇总在 `raw_runs.csv`，源码和输入版本在 `metadata.json`。
2. 有没有把建议或担忧写成已决或状态？——没有；没有选择正式算例或算法动作。
3. 是否超出任务范围？——没有；只纠正统一算例探索中的跨场机会测量口径。
4. 是否碰受保护文件？——未碰；前后哈希写入 `metadata.json`。
5. 待决事项是否给了选项和代价？——本包不产生用户待决事项。
6. 是否使用自造词或内部任务号？——没有。
7. 失败、跳过、超时和异常是否保留？——失败算例及原因保存在 `raw_runs.csv`。
8. 四件套是否齐全？——`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`、`report.md` 齐全，另附逐客户明细。
9. 交接记录是否同步？——本包复核后与后续动作探针一起同步项目交接和记忆。
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
        raise RuntimeError("marginal screen requires a clean worktree")
    candidate_ids = _candidate_ids(repo)
    if len(candidate_ids) != 27:
        raise RuntimeError(f"expected 27 candidates, got {len(candidate_ids)}")

    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    direct = _direct_opportunities(repo)
    rows: list[dict[str, Any]] = []
    customer_rows: list[dict[str, Any]] = []
    for instance_id in candidate_ids:
        try:
            row, customers = _instance_rows(repo, instance_id, direct)
            rows.append(row)
            customer_rows.extend(customers)
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
            rows.append(
                {
                    "instance_id": instance_id,
                    "region": instance_id.split("-")[1],
                    "status": "MARGINAL_SCREEN_FAILED",
                    "failure_reason": f"{type(error).__name__}: {error}",
                }
            )
    protected_after = {path: _sha256(repo / path) for path in PROTECTED}

    output.mkdir(parents=True)
    _write_csv(output / "raw_runs.csv", rows)
    _write_csv(output / "customer_marginals.csv", customer_rows)
    passed = [row for row in rows if row["status"] == "MARGINAL_SCREEN_PASS"]
    source = Path(__file__).resolve()
    _json(
        output / "metadata.json",
        {
            "schema": "resetp.duty-hgs-cross-depot-marginal-screen.v1",
            "purpose": "zero-search route-marginal correction; no ranking",
            "git_head": _git(repo, "rev-parse", "HEAD"),
            "git_branch": _git(repo, "branch", "--show-current"),
            "python_executable": sys.executable,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "runner_path": str(source.relative_to(repo)),
            "runner_sha256": _sha256(source),
            "candidate_ids": list(candidate_ids),
            "route_basis": "registered completed customer sequences",
            "distance_definition": (
                "directed distance-matrix arc replacement on customer-only route skeletons"
            ),
            "capacity_definition": (
                "receiving trip load after relocate or both trip loads after swap"
            ),
            "time_window_checked": False,
            "charging_checked": False,
            "profit_checked": False,
            "protected_hashes_before": protected_before,
            "protected_hashes_after": protected_after,
        },
    )
    _json(
        output / "decision.json",
        {
            "verdict": (
                "MARGINAL_SCREEN_COMPLETE"
                if len(passed) == len(rows) and protected_before == protected_after
                else "MARGINAL_SCREEN_HAS_FAILURES"
            ),
            "candidate_count": len(rows),
            "passed_count": len(passed),
            "failed_count": len(rows) - len(passed),
            "formal_algorithm_result": False,
            "formal_mechanism_result": False,
            "formal_instance_selected": None,
            "instance_ranking_performed": False,
            "customer_rows_dropped_by_sign": False,
        },
    )
    (output / "report.md").write_text(_report(rows), encoding="utf-8")
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
    print(
        json.dumps(
            {
                "output": str(output),
                "verdict": json.loads(
                    (output / "decision.json").read_text(encoding="utf-8")
                )["verdict"],
                "passed": len(passed),
                "customer_rows": len(customer_rows),
            },
            ensure_ascii=False,
        )
    )
    return 0 if len(passed) == len(rows) and protected_before == protected_after else 2


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
