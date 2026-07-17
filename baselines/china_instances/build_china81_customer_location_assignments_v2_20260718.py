#!/usr/bin/env python3
"""Build the 81 deterministic, within-cell-disjoint customer location assignments."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np


REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / "data/ChinaInstances/china_customer_location_contract_v2_20260718.json"
BASE_POOL = REPO / "data/ChinaInstances/china9_city_full_pool_20260718_rerun_overpass_v2"
OVERLAY = REPO / "data/ChinaInstances/china81_customer_pool_replenishment_map_api_v2_20260718"
POOL_GATE = REPO / "data/ChinaInstances/china81_pool_sufficiency_gate_v2_20260718"
OUTPUT = REPO / "data/ChinaInstances/china81_customer_location_assignments_v2_20260718"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def seed_for(region: str, size: int, replicate: str, city: str) -> int:
    payload = f"resetp-china-v2-location|{region}|{size}|{replicate}|{city}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def load_pools() -> dict[str, dict[tuple[str, str], dict[str, str]]]:
    pools: dict[str, dict[tuple[str, str], dict[str, str]]] = {}
    for root in (BASE_POOL, OVERLAY):
        for path in sorted((root / "pools").glob("*__named_poi.csv")):
            city = path.name.split("__", 1)[0]
            city_pool = pools.setdefault(city, {})
            for row in read_rows(path):
                city_pool[(row["osm_type"], row["osm_id"])] = row
    return pools


def build(output: Path = OUTPUT) -> dict[str, Any]:
    if output.exists():
        raise RuntimeError(f"refusing to overwrite existing assignment package: {output}")
    contract = read_json(CONTRACT)
    if str(contract.get("status", "")).startswith("HALT_"):
        raise RuntimeError(
            "customer-location contract is deliberately halted pending PPS city-quota recalibration: "
            f"{contract.get('status')}"
        )
    if "city_quotas" not in contract:
        raise RuntimeError("active city_quotas are not frozen in the customer-location contract")
    gate = read_json(POOL_GATE / "decision.json")
    if gate.get("verdict") != "PASS_81_MUTUAL_EXCLUSIVITY_POOL_GATE":
        raise RuntimeError(f"pool gate is not PASS: {gate.get('verdict')}")
    pools = load_pools()
    assignments: list[dict[str, Any]] = []
    catalog: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    for region, size_table in contract["city_quotas"].items():
        for size_text, quotas in size_table.items():
            size = int(size_text)
            used: set[tuple[str, str]] = set()
            for replicate in contract["replicate_labels"]:
                instance_id = f"cn-{region}-{size}c-{replicate}-V2-LOCATIONS"
                instance_rows: list[dict[str, Any]] = []
                for city, quota in quotas.items():
                    available = [row for identity, row in sorted(pools[city].items()) if identity not in used]
                    if len(available) < int(quota):
                        raise RuntimeError(f"{instance_id}/{city}: {len(available)} available, {quota} required")
                    order = np.random.default_rng(seed_for(region, size, replicate, city)).permutation(len(available))
                    selected = [available[int(index)] for index in order[: int(quota)]]
                    for rank, row in enumerate(selected, start=1):
                        identity = (row["osm_type"], row["osm_id"])
                        used.add(identity)
                        item = {
                            "instance_id": instance_id,
                            "region": region,
                            "customer_size": size,
                            "replicate": replicate,
                            "city": city,
                            "city_quota": int(quota),
                            "city_selection_rank": rank,
                            "location_seed": seed_for(region, size, replicate, city),
                            **{field: row.get(field, "") for field in (
                                "osm_type", "osm_id", "latitude", "longitude", "name", "brand", "tags",
                                "source_response_path", "source_response_sha256", "source_query_bbox",
                            )},
                        }
                        assignments.append(item)
                        instance_rows.append(item)
                if len(instance_rows) != size:
                    raise RuntimeError(f"{instance_id}: selected {len(instance_rows)} != {size}")
                catalog.append(
                    {
                        "instance_id": instance_id,
                        "region": region,
                        "customer_size": size,
                        "replicate": replicate,
                        "customer_count": len(instance_rows),
                        "city_counts": json.dumps(Counter(row["city"] for row in instance_rows), ensure_ascii=False, sort_keys=True),
                        "unique_identity_count": len({(row["osm_type"], row["osm_id"]) for row in instance_rows}),
                        "search_evaluations": 0,
                        "status": "LOCATION_ASSIGNMENT_ONLY_NOT_FORMAL_INSTANCE",
                    }
                )
                runs.append(
                    {
                        "instance_id": instance_id,
                        "status": "OK_LOCATION_ASSIGNMENT",
                        "customer_count": len(instance_rows),
                        "search_evaluations": 0,
                    }
                )
    output.mkdir(parents=True)
    assignment_fields = list(assignments[0])
    write_csv(output / "assignments.csv", assignments, assignment_fields)
    write_csv(output / "instance_catalog.csv", catalog, list(catalog[0]))
    write_csv(output / "raw_runs.csv", runs, list(runs[0]))
    errors: list[str] = []
    for region, size_table in contract["city_quotas"].items():
        for size_text in size_table:
            cell = [row for row in assignments if row["region"] == region and row["customer_size"] == int(size_text)]
            identities = [(row["osm_type"], row["osm_id"]) for row in cell]
            if len(cell) != 3 * int(size_text) or len(set(identities)) != len(identities):
                errors.append(f"{region}/{size_text}: rows={len(cell)}, unique={len(set(identities))}")
    verdict = "PASS_81_DISJOINT_LOCATION_ASSIGNMENTS_BUILT" if len(catalog) == 81 and not errors else "HALT_LOCATION_ASSIGNMENT_BUILD"
    decision = {
        "schema": "resetp.china81.location-assignment.decision.v2",
        "verdict": verdict,
        "generated_utc": datetime.now(UTC).isoformat(),
        "instances": len(catalog),
        "assignment_rows": len(assignments),
        "region_size_cells": 27,
        "within_cell_overlap_violations": errors,
        "search_evaluations": 0,
        "formal_instance_build_allowed": False,
        "boundary": "This builds customer locations only; orders, depots, chargers, road matrices and vehicle feasibility are not built.",
    }
    write_json(output / "decision.json", decision)
    write_json(
        output / "metadata.json",
        {
            "schema": "resetp.china81.location-assignment.metadata.v2",
            "contract": str(CONTRACT.relative_to(REPO)),
            "contract_sha256": sha256(CONTRACT),
            "base_pool_decision_sha256": sha256(BASE_POOL / "decision.json"),
            "overlay_decision_sha256": sha256(OVERLAY / "decision.json"),
            "pool_gate_decision_sha256": sha256(POOL_GATE / "decision.json"),
            "seed_algorithm": contract["location_seed_rule"],
            "search_evaluations": 0,
        },
    )
    (output / "report.md").write_text(
        "# 中国81算例客户位置分配\n\n"
        f"结论：`{verdict}`。已生成{len(catalog)}份位置分配、{len(assignments)}行客户记录；27个城市群×规模单元内01/02/03的OSM身份零重叠。\n\n"
        "本包只冻结客户位置，不含订单、车场、充电站、路网矩阵或车辆可行性，因此不能启动正式搜索。\n",
        encoding="utf-8",
    )
    files = [output / name for name in ("assignments.csv", "instance_catalog.csv", "raw_runs.csv", "decision.json", "metadata.json", "report.md")]
    write_json(output / "artifact_hashes.json", {"schema": "resetp.artifact-hashes.v1", "files": {str(path.relative_to(REPO)): sha256(path) for path in files}})
    return decision


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, sort_keys=True))
