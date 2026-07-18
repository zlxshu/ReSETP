#!/usr/bin/env python3
"""Audit and freeze the complete G1-independent China81 data package."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

from china81_artifact_integrity_20260719 import (
    require_decision,
    verify_artifact_package,
)


REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / "data/ChinaInstances/china81_stage2_static_inputs_v1_20260718"
MATRICES = REPO / "data/ChinaInstances/china81_local_directed_matrices_v9_20260718"
ORDER_PACKAGE = STATIC.parent / "china81_order_attributes_mc001_v1_20260718"
ORDERS = ORDER_PACKAGE / "orders.csv"
OUT = REPO / "data/ChinaInstances/china81_g1_independent_frozen_v2_20260718"
EXPECTED_INSTANCES = 81
EXPECTED_ORDERS = 5_805


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def matrix(path: Path) -> tuple[list[str], dict[tuple[str, str], float]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)[1:]
        result = {}
        row_ids = []
        for row in reader:
            row_ids.append(row[0])
            for target, value in zip(header, row[1:], strict=True):
                number = float(value)
                if not math.isfinite(number) or number < 0:
                    raise RuntimeError(f"invalid matrix value in {path}")
                result[(row[0], target)] = number
    if row_ids != header:
        raise RuntimeError(f"matrix row/column identity drift: {path}")
    return header, result


def write_csv(path: Path, data: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0]))
        w.writeheader()
        w.writerows(data)


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    authority_files = ("metadata.json", "raw_runs.csv", "decision.json", "report.md")
    verified_static_files = verify_artifact_package(STATIC, authority_files)
    verified_matrix_files = verify_artifact_package(MATRICES, authority_files)
    verified_order_files = verify_artifact_package(ORDER_PACKAGE, authority_files)
    require_decision(
        STATIC / "decision.json",
        "PASS_G1_INDEPENDENT_STATIC_INPUTS_FROZEN",
        {"formal_experiment_authorized": False, "search_evaluations": 0},
    )
    require_decision(
        MATRICES / "decision.json",
        "PASS_CHINA81_LOCAL_DIRECTED_THREE_MATRICES",
        {"ordered_pairs_complete": True, "unreachable_pairs": 0},
    )
    require_decision(
        ORDER_PACKAGE / "decision.json",
        "PASS_CHINA81_MC001_ORDER_ATTRIBUTE_LAYER_BUILT",
        {
            "instances": EXPECTED_INSTANCES,
            "order_rows": EXPECTED_ORDERS,
            "joint_empirical_rows_preserved": True,
            "formal_search_allowed": False,
        },
    )
    catalog = rows(STATIC / "instance_catalog.csv")
    all_orders = rows(ORDERS)
    catalog_ids = [row["instance_id"] for row in catalog]
    order_instance_ids = {row["instance_id"] for row in all_orders}
    package_violations = []
    if len(catalog) != EXPECTED_INSTANCES:
        package_violations.append(
            f"INSTANCE_COUNT:{len(catalog)}!={EXPECTED_INSTANCES}"
        )
    if len(set(catalog_ids)) != len(catalog_ids):
        package_violations.append("DUPLICATE_INSTANCE_ID")
    if len(all_orders) != EXPECTED_ORDERS:
        package_violations.append(f"ORDER_COUNT:{len(all_orders)}!={EXPECTED_ORDERS}")
    if order_instance_ids != set(catalog_ids):
        package_violations.append("ORDER_INSTANCE_COVERAGE")
    order_by_instance: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in all_orders:
        order_by_instance[row["instance_id"]].append(row)
    audits = []
    manifests = []
    for item in catalog:
        instance = item["instance_id"]
        node_file = STATIC / "instances" / instance / "nodes.csv"
        node_rows = rows(node_file)
        by_id = {r["node_id"]: r for r in node_rows}
        instance_orders = order_by_instance[instance]
        violations = []
        if len(by_id) != len(node_rows):
            violations.append("DUPLICATE_NODE_ID")
        if len(instance_orders) != int(item["customer_count"]):
            violations.append("ORDER_COUNT")
        customer_node_ids = {
            row["node_id"]
            for row in node_rows
            if row["node_type"].strip().lower() == "customer"
        }
        order_customer_ids = {row["customer_id"] for row in instance_orders}
        if customer_node_ids != order_customer_ids:
            violations.append("ORDER_CUSTOMER_IDENTITY")
        for order in instance_orders:
            demand = float(order["demand_kg"])
            early = float(order["time_window_early_minute"])
            late = float(order["time_window_late_minute"])
            service = float(order["service_minutes"])
            if not (0 < demand <= 1000):
                violations.append(f"DEMAND:{order['customer_id']}")
            if not (360 <= early < late <= 1320 and service > 0):
                violations.append(f"TIME_WINDOW:{order['customer_id']}")
        profile_hashes = {}
        max_ev_roundtrip_km = 0.0
        for profile in ("cv", "ev"):
            target = MATRICES / "instances" / instance / profile
            d_ids, distance = matrix(target / "road_distance_m.csv")
            t_ids, duration = matrix(target / "road_duration_s.csv")
            v_ids, v2d = matrix(target / "road_sum_v2d_m3_s2.csv")
            if d_ids != t_ids or d_ids != v_ids or set(d_ids) != set(by_id):
                violations.append(f"MATRIX_IDENTITY:{profile}")
            if any(distance[(x, x)] or duration[(x, x)] or v2d[(x, x)] for x in d_ids):
                violations.append(f"NONZERO_DIAGONAL:{profile}")
            for order in instance_orders:
                customer = order["customer_id"]
                city = order["city"]
                depot = f"D_{city}"
                station = f"S_{city}"
                if depot not in by_id or station not in by_id:
                    violations.append(f"FACILITY_ID:{customer}")
                    continue
                for facility in (depot, station):
                    if distance[(facility, customer)] <= 0 or distance[(customer, facility)] <= 0:
                        violations.append(f"UNREACHABLE:{profile}:{facility}:{customer}")
                travel_out = duration[(depot, customer)] / 60
                travel_back = duration[(customer, depot)] / 60
                arrival = max(360 + travel_out, float(order["time_window_early_minute"]))
                finish = arrival + float(order["service_minutes"]) + travel_back
                if arrival > float(order["time_window_late_minute"]) or finish > 1320:
                    violations.append(f"SINGLETON_TIME_WITNESS:{profile}:{customer}")
                if profile == "ev":
                    max_ev_roundtrip_km = max(
                        max_ev_roundtrip_km,
                        (distance[(depot, customer)] + distance[(customer, depot)]) / 1000,
                    )
            profile_hashes[profile] = {
                name: sha256(target / name)
                for name in (
                    "nodes.csv", "road_distance_m.csv", "road_duration_s.csv",
                    "road_sum_v2d_m3_s2.csv", "raw_runs.csv",
                )
            }
        if max_ev_roundtrip_km > 400:
            violations.append("EV_OFFICIAL_RANGE_SCALE")
        status = "PASS" if not violations else "FAIL"
        audits.append({
            "instance_id": instance,
            "status": status,
            "customer_count": len(instance_orders),
            "node_count": len(node_rows),
            "minimum_ev_vehicle_count_by_payload": math.ceil(
                sum(float(r["demand_kg"]) for r in instance_orders) / 1000
            ),
            "max_singleton_ev_roundtrip_km": f"{max_ev_roundtrip_km:.6f}",
            "violations": "|".join(violations),
            "search_evaluations": 0,
        })
        manifests.append({
            "instance_id": instance,
            "region": item["region"],
            "order_seed": instance_orders[0]["order_seed"] if instance_orders else "",
            "nodes_path": str(node_file.relative_to(REPO)),
            "nodes_sha256": sha256(node_file),
            "orders_source_sha256": sha256(ORDERS),
            "profile_hashes_json": json.dumps(profile_hashes, sort_keys=True),
            "audit_status": status,
            "formal_search_allowed": False,
        })
    failed = [r for r in audits if r["status"] != "PASS"]
    write_csv(OUT / "raw_runs.csv", audits)
    write_csv(OUT / "instance_manifest.csv", manifests)
    metadata = {
        "schema": "resetp.china81-g1-independent-frozen.v2",
        "instances": len(audits), "orders": sum(int(r["customer_count"]) for r in audits),
        "expected_instances": EXPECTED_INSTANCES,
        "expected_orders": EXPECTED_ORDERS,
        "verified_static_files": verified_static_files,
        "verified_matrix_files": verified_matrix_files,
        "verified_order_files": verified_order_files,
        "static_package_sha256": sha256(STATIC / "artifact_hashes.json"),
        "matrix_package_sha256": sha256(MATRICES / "artifact_hashes.json"),
        "audit_scope": [
            "capacity and time-window necessary conditions",
            "CV/EV matrix identity, finiteness and zero diagonals",
            "same-city depot/station bidirectional reachability",
            "deterministic singleton time-window witness",
            "official EV range-scale diagnostic",
        ],
        "excluded_g1_scope": [
            "nonlinear SOC and charging-time feasibility",
            "solver-search feasibility and algorithm acceptance",
        ],
        "formal_search_allowed": False, "draft_only": True, "search_evaluations": 0,
    }
    write_json(OUT / "metadata.json", metadata)
    verdict = (
        "PASS_CHINA81_G1_INDEPENDENT_DATA_FROZEN__G1_PHYSICAL_SEARCH_ACCEPTANCE_HELD"
        if not failed and not package_violations
        else "HALT_CHINA81_ZERO_SEARCH_AUDIT"
    )
    write_json(OUT / "decision.json", {
        "verdict": verdict, "passed_instances": len(audits) - len(failed),
        "failed_instances": len(failed), "package_violations": package_violations,
        "observed_instances": len(audits), "expected_instances": EXPECTED_INSTANCES,
        "observed_orders": len(all_orders), "expected_orders": EXPECTED_ORDERS,
        "formal_experiment_authorized": False,
        "formal_search_allowed": False, "search_evaluations": 0,
    })
    (OUT / "report.md").write_text(
        "# China81 G1 独立数据冻结\n\n"
        f"零搜索审计结果：{len(audits) - len(failed)}/{len(audits)} 通过；"
        f"包级违规 {len(package_violations)} 项。审计覆盖订单必要条件、"
        "CV/EV 三矩阵、设施双向可达和单客户时间窗见证。400 km 仅作官方续航尺度诊断；"
        "非线性 SOC、充电时间和算法可行性必须等待 G1 汇合后复算。正式搜索仍关闭。\n",
        encoding="utf-8",
    )
    hashes = {
        p.name: sha256(p) for p in OUT.iterdir()
        if p.is_file() and p.name != "artifact_hashes.json" and not p.name.startswith("._")
    }
    write_json(OUT / "artifact_hashes.json", {"sha256": hashes})
    print(json.dumps({"verdict": verdict, "failed": len(failed)}, ensure_ascii=False))
    return 0 if not failed and not package_violations else 2


if __name__ == "__main__":
    raise SystemExit(main())
