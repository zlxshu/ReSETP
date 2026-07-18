#!/usr/bin/env python3
"""Attach the approved MC-001 order attributes to the 81 location assignments.

This is a deterministic data-layer build.  It samples complete empirical rows
with replacement and therefore never breaks the observed joint relationship
between volume, mapped demand, service duration, and delivery-window fields.
It does not create road matrices, feasibility witnesses, or solver inputs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
CONTRACT = (
    REPO / "data/ChinaInstances/china_order_attribute_contract_v2_20260718.json"
)
LOCATIONS = (
    REPO
    / "data/ChinaInstances/"
    "china81_customer_location_assignments_mc005_final_v2_20260718"
)
SOURCE_ROWS = (
    REPO
    / "data/ChinaInstances/china_order_attribute_calibration_v2_20260718/"
    "empirical_order_attribute_rows.csv"
)
DEFAULT_OUTPUT = (
    REPO
    / "data/ChinaInstances/china81_order_attributes_mc001_v1_20260718"
)
VERDICT = "PASS_CHINA81_MC001_ORDER_ATTRIBUTE_LAYER_BUILT"


class OrderBuildError(RuntimeError):
    """The approved order-attribute contract cannot be reproduced."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def order_seed(instance_id: str, contract_sha256: str) -> int:
    payload = f"{instance_id}{contract_sha256}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def build(output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    output = output.resolve()
    if output.exists():
        raise OrderBuildError(f"refusing to overwrite existing output: {output}")

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract.get("status") != (
        "APPROVED_ORDER_ATTRIBUTE_METHODS_BLOCKED_BY_STAGE2_INPUT_GATES"
    ):
        raise OrderBuildError(f"MC-001 contract status drift: {contract.get('status')}")
    if contract.get("calibration_evidence", {}).get(
        "model_transformation_approved_by_user"
    ) is not True:
        raise OrderBuildError("MC-001 approval flag is absent")
    expected_source_hash = contract["calibration_evidence"]["empirical_rows_sha256"]
    if sha256(SOURCE_ROWS) != expected_source_hash:
        raise OrderBuildError("empirical source-row hash drift")
    location_decision = json.loads(
        (LOCATIONS / "decision.json").read_text(encoding="utf-8")
    )
    if location_decision.get("verdict") != (
        "PASS_81_DISJOINT_LOCATION_ASSIGNMENTS_BUILT"
    ):
        raise OrderBuildError("authoritative MC-005 location package is not PASS")

    source_rows = read_csv(SOURCE_ROWS)
    if len(source_rows) != 1222:
        raise OrderBuildError(f"expected 1222 empirical rows, got {len(source_rows)}")
    location_rows = read_csv(LOCATIONS / "assignments.csv")
    by_instance: dict[str, list[dict[str, str]]] = {}
    for row in location_rows:
        by_instance.setdefault(row["instance_id"], []).append(row)
    if len(by_instance) != 81:
        raise OrderBuildError(f"expected 81 instances, got {len(by_instance)}")

    contract_hash = sha256(CONTRACT)
    output_rows: list[dict[str, Any]] = []
    catalog_rows: list[dict[str, Any]] = []
    raw_runs: list[dict[str, Any]] = []
    seen_seeds: set[int] = set()
    sibling_seeds: dict[tuple[str, int], set[int]] = {}

    for instance_id in sorted(by_instance):
        locations = sorted(
            by_instance[instance_id],
            key=lambda row: (row["city"], int(row["city_selection_rank"])),
        )
        seed = order_seed(instance_id, contract_hash)
        if seed in seen_seeds:
            raise OrderBuildError(f"duplicate order seed: {seed}")
        seen_seeds.add(seed)
        region = locations[0]["region"]
        customer_size = int(locations[0]["customer_size"])
        replicate = locations[0]["replicate"]
        sibling_key = (region, customer_size)
        sibling_seeds.setdefault(sibling_key, set()).add(seed)
        rng = random.Random(seed)
        instance_rows: list[dict[str, Any]] = []
        for customer_rank, location in enumerate(locations, start=1):
            source_index = rng.randrange(len(source_rows))
            source = source_rows[source_index]
            early = float(source["delivery_early_minute"])
            late = float(source["delivery_late_minute"])
            width = float(source["delivery_width_minute"])
            demand = int(source["demand_kg_capacity_share_proxy"])
            service = float(source["service_minutes_literature_rule"])
            if not 360 <= early < late <= 1320:
                raise OrderBuildError(
                    f"{instance_id}/C{customer_rank:03d} window outside 06:00-22:00"
                )
            if abs((late - early) - width) > 1e-5:
                raise OrderBuildError(
                    f"{instance_id}/C{customer_rank:03d} window width drift"
                )
            if demand not in {139, 208, 278, 347, 417}:
                raise OrderBuildError(f"unexpected demand proxy: {demand}")
            if service not in {6.0, 9.0, 12.0, 15.0, 18.0}:
                raise OrderBuildError(f"unexpected service duration: {service}")
            item = {
                "instance_id": instance_id,
                "region": region,
                "customer_size": customer_size,
                "replicate": replicate,
                "customer_id": f"C{customer_rank:03d}",
                "city": location["city"],
                "osm_type": location["osm_type"],
                "osm_id": location["osm_id"],
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "name": location["name"],
                "order_seed": seed,
                "empirical_source_index_zero_based": source_index,
                "source_order_uid": source["source_order_uid"],
                "source_volume_m3": source["Volume of goods (m3)"],
                "demand_kg": demand,
                "service_minutes": f"{service:.6f}",
                "time_window_early_minute": f"{early:.6f}",
                "time_window_late_minute": f"{late:.6f}",
                "time_window_width_minute": f"{width:.6f}",
                "demand_classification": (
                    "CONSTRUCTED_CAPACITY_SHARE_SCENARIO_PROXY"
                ),
                "service_classification": (
                    "PUBLISHED_CASE_PARAMETER_NOT_OBSERVED_STOP_DURATION"
                ),
                "window_classification": "OBSERVED_JOINT_EMPIRICAL_DELIVERY_WINDOW",
            }
            instance_rows.append(item)
            output_rows.append(item)

        demands = [int(row["demand_kg"]) for row in instance_rows]
        services = [float(row["service_minutes"]) for row in instance_rows]
        widths = [float(row["time_window_width_minute"]) for row in instance_rows]
        demand_counts = Counter(demands)
        catalog_rows.append(
            {
                "instance_id": instance_id,
                "region": region,
                "customer_size": customer_size,
                "replicate": replicate,
                "order_seed": seed,
                "customer_rows": len(instance_rows),
                "demand_total_kg": sum(demands),
                "demand_max_kg": max(demands),
                "service_total_minutes": f"{sum(services):.6f}",
                "window_width_min_minutes": f"{min(widths):.6f}",
                "window_width_max_minutes": f"{max(widths):.6f}",
                "demand_counts_json": json.dumps(
                    demand_counts, ensure_ascii=False, sort_keys=True
                ),
                "search_evaluations": 0,
                "status": "ORDER_ATTRIBUTE_LAYER_ONLY_NOT_FORMAL_INSTANCE",
            }
        )
        raw_runs.append(
            {
                "instance_id": instance_id,
                "status": "PASS",
                "customer_rows": len(instance_rows),
                "order_seed": seed,
                "search_evaluations": 0,
                "violations": 0,
            }
        )

    bad_sibling_cells = [
        f"{region}/{size}"
        for (region, size), seeds in sibling_seeds.items()
        if len(seeds) != 3
    ]
    if bad_sibling_cells:
        raise OrderBuildError(f"sibling order-seed overlap: {bad_sibling_cells}")
    if len(output_rows) != 5805:
        raise OrderBuildError(f"expected 5805 order rows, got {len(output_rows)}")

    output.mkdir(parents=True)
    order_fields = list(output_rows[0])
    write_csv(output / "orders.csv", order_fields, output_rows)
    write_csv(
        output / "instance_catalog.csv", list(catalog_rows[0]), catalog_rows
    )
    write_csv(output / "raw_runs.csv", list(raw_runs[0]), raw_runs)
    metadata = {
        "schema": "resetp.china81.mc001-order-layer.metadata.v1",
        "generated_utc": utc_now(),
        "authorization": "MC-001",
        "contract": str(CONTRACT.relative_to(REPO)),
        "contract_sha256": contract_hash,
        "location_package": str(LOCATIONS.relative_to(REPO)),
        "location_decision_sha256": sha256(LOCATIONS / "decision.json"),
        "empirical_rows": str(SOURCE_ROWS.relative_to(REPO)),
        "empirical_rows_sha256": expected_source_hash,
        "seed_payload": "instance_id + contract_sha256",
        "seed_digest": "SHA256 first 64 bits big-endian",
        "sampling": "complete empirical rows with replacement",
        "instances": 81,
        "order_rows": 5805,
        "solver_search_evaluations": 0,
        "formal_search_allowed": False,
    }
    atomic_json(output / "metadata.json", metadata)
    decision = {
        "schema": "resetp.china81.mc001-order-layer.decision.v1",
        "verdict": VERDICT,
        "instances": 81,
        "order_rows": 5805,
        "distinct_order_seeds": len(seen_seeds),
        "sibling_seed_overlap_violations": bad_sibling_cells,
        "joint_empirical_rows_preserved": True,
        "solver_search_evaluations": 0,
        "formal_search_allowed": False,
        "next_gate": "attach frozen depots, stations, local road matrices, and zero-search witnesses",
    }
    atomic_json(output / "decision.json", decision)
    (output / "report.md").write_text(
        "# China81 MC-001订单属性层\n\n"
        f"判定：`{VERDICT}`。81个位置实例共5805个客户，分别使用结果无关且"
        "互不重复的种子，从1222条获批中国交付经验行中有放回抽取完整行。"
        "需求、服务时间和交付时间窗没有拆开独立抽样。公斤需求继续明确为"
        "容量占比构造代理，服务时间继续明确为文献案例参数。本包不含道路矩阵、"
        "可行性见证或算法搜索，`formal_search_allowed=false`。\n",
        encoding="utf-8",
    )
    artifact_paths = [
        output / "orders.csv",
        output / "instance_catalog.csv",
        output / "raw_runs.csv",
        output / "metadata.json",
        output / "decision.json",
        output / "report.md",
    ]
    atomic_json(
        output / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "files": {
                str(path.relative_to(output)): sha256(path)
                for path in artifact_paths
            },
        },
    )
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    decision = build(args.output)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OrderBuildError as error:
        print(f"HALT: {error}", file=sys.stderr)
        raise SystemExit(2) from error
