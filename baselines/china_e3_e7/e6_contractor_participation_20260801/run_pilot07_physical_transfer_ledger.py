#!/usr/bin/env python3
"""Derive a physical depot-transfer ledger from the saved E6 grand solution."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for path in (HERE, REPO / "solver/src", REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_pilot05_grand_coalition_recovery as pilot05
from setp_solver.china81_completion import exact_china81_score
from setp_solver.search.metaheuristic_baselines import solution_from_dict


SOURCE = HERE / "pilot05_grand_coalition_recovery_20260801"
OUTPUT = HERE / "pilot07_physical_transfer_ledger_20260801"
VEHICLE_TYPES = ("cv", "ev")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def required_trips(quantity_kg: float, capacity_kg: float) -> int:
    if quantity_kg < 0.0 or capacity_kg <= 0.0:
        raise ValueError("invalid transfer quantity or vehicle capacity")
    return math.ceil(quantity_kg / capacity_kg) if quantity_kg else 0


def source_audit() -> dict[str, str]:
    expected = json.loads((SOURCE / "artifact_hashes.json").read_text(encoding="utf-8"))
    observed = {name: sha256(SOURCE / name) for name in expected}
    if observed != expected:
        raise RuntimeError("pilot05 artifact hashes changed")
    return observed


def transfer_quantities(bundle: Any, solution: Any) -> dict[tuple[str, str], dict[str, float]]:
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    values: dict[tuple[str, str], dict[str, float]] = {}
    for route in solution.routes:
        serving = route.home_depot_id
        for customer in route.node_sequence:
            owner = bundle.customer_home_depot.get(customer)
            if owner is None or owner == serving:
                continue
            row = values.setdefault((owner, serving), {"quantity_kg": 0.0, "customer_count": 0.0})
            row["quantity_kg"] += float(nodes[customer].demand)
            row["customer_count"] += 1.0
    return values


def build_rows(bundle: Any, solution: Any) -> list[dict[str, Any]]:
    quantities = transfer_quantities(bundle, solution)
    rows: list[dict[str, Any]] = []
    for (owner, serving), transfer in sorted(quantities.items()):
        quantity = transfer["quantity_kg"]
        for vehicle_type in VEHICLE_TYPES:
            capacity = bundle.instance.payload_capacity_kg(
                vehicle_type,
                fallback=float(bundle.prices.Q_capacity),
            )
            trips = required_trips(quantity, capacity)
            outbound_m, outbound_s, _ = bundle.instance.arc_metrics(
                owner,
                serving,
                vehicle_type,
                fallback_speed_mps=float(bundle.prices.v_speed_ms),
            )
            return_m, return_s, _ = bundle.instance.arc_metrics(
                serving,
                owner,
                vehicle_type,
                fallback_speed_mps=float(bundle.prices.v_speed_ms),
            )
            distance_cost = bundle.instance.non_energy_distance_cost_per_km(
                vehicle_type,
                fallback=float(bundle.prices.c_km),
            )
            one_way_vehicle_km = trips * outbound_m / 1000.0
            closed_vehicle_km = trips * (outbound_m + return_m) / 1000.0
            rows.append(
                {
                    "original_owner": owner,
                    "actual_service_depot": serving,
                    "vehicle_type": vehicle_type,
                    "customer_count": int(transfer["customer_count"]),
                    "quantity_kg": quantity,
                    "payload_capacity_kg": capacity,
                    "minimum_trip_count": trips,
                    "outbound_distance_km_per_trip": outbound_m / 1000.0,
                    "return_distance_km_per_trip": return_m / 1000.0,
                    "outbound_minutes_per_trip": outbound_s / 60.0,
                    "return_minutes_per_trip": return_s / 60.0,
                    "one_way_vehicle_km": one_way_vehicle_km,
                    "closed_vehicle_km": closed_vehicle_km,
                    "outbound_tonne_km": quantity * outbound_m / 1_000_000.0,
                    "non_energy_cost_cny_per_km": distance_cost,
                    "one_way_non_energy_cost_cny": one_way_vehicle_km * distance_cost,
                    "closed_non_energy_cost_cny": closed_vehicle_km * distance_cost,
                }
            )
    return rows


def report_text(decision: dict[str, Any]) -> str:
    lines = [
        "# E6 实体转运物理账本",
        "",
        "本账本读取已经保存并独立验过的大联盟方案，不重新搜索。货物流向按“原客户所属车场 → 实际配送车场”统计。",
        "",
        f"方案中跨承包商客户 {decision['cross_contractor_customers']} 个，转移货量 {decision['cross_contractor_quantity_kg']:.3f} kg。",
        f"未计实体转运前，大联盟相对四家单干节省 {decision['pre_transfer_saving_cny']:.3f} 元。",
        "",
        "| 假定转运车型 | 至少趟数 | 单向车公里 | 闭环车公里 | 单向非能源里程费/元 | 闭环非能源里程费/元 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for vehicle_type in VEHICLE_TYPES:
        row = decision["vehicle_boundaries"][vehicle_type]
        lines.append(
            f"| {vehicle_type.upper()} | {row['minimum_trip_count']} | "
            f"{row['one_way_vehicle_km']:.3f} | {row['closed_vehicle_km']:.3f} | "
            f"{row['one_way_non_energy_cost_cny']:.3f} | "
            f"{row['closed_non_energy_cost_cny']:.3f} |"
        )
    lines.extend(
        [
            "",
            "这里的费用只含 China81 车型参数中的维保、轮胎、路桥等非能源里程费；没有加入柴油、电费、碳成本、装卸或派遣费，因此不是实体转运总成本。",
            "",
            "计算方向和货量定义对应饶卫振等（2019）第1521页及第1522页式(7)；把车场间调运里程计入联盟运输成本对应饶卫振等（2022）第2726—2727页。",
        ]
    )
    return "\n".join(lines) + "\n"


def run(output: Path = OUTPUT) -> dict[str, Any]:
    if output.exists():
        raise RuntimeError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    source_hashes = source_audit()
    payload = json.loads((SOURCE / "solution.json").read_text(encoding="utf-8"))
    solution = solution_from_dict(payload["solution"])
    bundle, _, _, _ = pilot05.load_context()
    objective, _, violations = exact_china81_score(solution, bundle)
    if violations or not math.isclose(objective, float(payload["objective_cny"]), abs_tol=1.0e-6):
        raise RuntimeError("saved pilot05 solution failed independent scoring")

    rows = build_rows(bundle, solution)
    source_decision = json.loads((SOURCE / "decision.json").read_text(encoding="utf-8"))
    boundaries: dict[str, dict[str, float | int]] = {}
    for vehicle_type in VEHICLE_TYPES:
        selected = [row for row in rows if row["vehicle_type"] == vehicle_type]
        boundaries[vehicle_type] = {
            key: sum(row[key] for row in selected)
            for key in (
                "minimum_trip_count",
                "one_way_vehicle_km",
                "closed_vehicle_km",
                "outbound_tonne_km",
                "one_way_non_energy_cost_cny",
                "closed_non_energy_cost_cny",
            )
        }
    decision = {
        "status": "PASS_PHYSICAL_TRANSFER_LEDGER",
        "source_solution_sha256": payload["solution_sha256"],
        "source_objective_cny": objective,
        "cross_contractor_customers": source_decision["cross_contractor_customers"],
        "cross_contractor_quantity_kg": source_decision["cross_contractor_quantity_kg"],
        "pre_transfer_saving_cny": source_decision["saving_vs_pilot04_singletons_cny"],
        "vehicle_boundaries": boundaries,
        "complete_transfer_cost_calculated": False,
        "requires_business_semantics_for_formal_cost": True,
    }
    metadata = {
        "schema": "resetp.e6-physical-transfer-ledger.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source": str(SOURCE.relative_to(REPO)),
        "source_artifact_hashes": source_hashes,
        "literature": [
            "Rao et al. (2019), p.1518 and pp.1521-1522",
            "Rao et al. (2022), pp.2726-2727 and p.2730",
        ],
        "cost_scope": "non-energy distance cost only",
    }
    write_csv(output / "raw_runs.csv", rows)
    write_json(output / "metadata.json", metadata)
    write_json(output / "decision.json", decision)
    (output / "report.md").write_text(report_text(decision), encoding="utf-8")
    write_json(
        output / "artifact_hashes.json",
        {
            name: sha256(output / name)
            for name in ("metadata.json", "raw_runs.csv", "decision.json", "report.md")
        },
    )
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run(args.output), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
