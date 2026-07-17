#!/usr/bin/env python3
"""Audit whether the nine-city OSM pool can support 81 mutually exclusive instances."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
DEFAULT_POOL = REPO / "data/ChinaInstances/china9_city_full_pool_20260718_rerun_overpass_v2"
CONTRACT = REPO / "data/ChinaInstances/china_customer_location_contract_v2_20260718.json"
DEFAULT_OUTPUT = REPO / "data/ChinaInstances/china81_pool_sufficiency_gate_v2_20260718"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_pool(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8", newline="") as handle:
        return {(row["osm_type"], row["osm_id"]) for row in csv.DictReader(handle)}


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def audit(pool_root: Path, output: Path, overlay_roots: tuple[Path, ...] = ()) -> dict[str, Any]:
    contract = read_json(CONTRACT)
    output.mkdir(parents=True, exist_ok=True)
    pool_decision_path = pool_root / "decision.json"
    pool_verdict = read_json(pool_decision_path).get("verdict") if pool_decision_path.exists() else "MISSING"
    identities: dict[str, set[tuple[str, str]]] = {}
    for root in (pool_root, *overlay_roots):
        for path in sorted((root / "pools").glob("*__named_poi.csv")):
            city = path.name.split("__", 1)[0]
            identities.setdefault(city, set()).update(read_pool(path))
    counts = {city: len(values) for city, values in identities.items()}
    overlay_verdicts = {
        display_path(root): read_json(root / "decision.json").get("verdict")
        if (root / "decision.json").exists()
        else "MISSING"
        for root in overlay_roots
    }
    region_cities = {
        region: sorted({city for quotas in table.values() for city in quotas})
        for region, table in contract["city_quotas"].items()
    }
    cross_city_overlaps: dict[str, int] = {}
    for region, cities in region_cities.items():
        overlap_count = 0
        for index, city_a in enumerate(cities):
            for city_b in cities[index + 1 :]:
                overlap_count += len(identities.get(city_a, set()) & identities.get(city_b, set()))
        cross_city_overlaps[region] = overlap_count
    rows: list[dict[str, Any]] = []
    for region, size_table in contract["city_quotas"].items():
        for size_text, quotas in size_table.items():
            cell_pass = True
            details: list[str] = []
            for city, quota in quotas.items():
                required = int(quota) * int(contract["replicates_per_region_size"])
                available = counts.get(city, 0)
                passed = available >= required
                cell_pass &= passed
                details.append(f"{city}:{available}/{required}")
            rows.append(
                {
                    "region": region,
                    "customer_size": int(size_text),
                    "replicates": contract["replicates_per_region_size"],
                    "required_total": int(size_text) * int(contract["replicates_per_region_size"]),
                    "city_availability": ";".join(details),
                    "pass": cell_pass,
                }
            )
    all_cells_pass = (
        len(rows) == 27
        and all(row["pass"] for row in rows)
        and all(count == 0 for count in cross_city_overlaps.values())
    )
    full_source_pass = pool_verdict == "PASS_P1_FULL_POOL_EXTRACTED" and all(
        verdict == "PASS_CUSTOMER_POOL_REPLENISHMENT" for verdict in overlay_verdicts.values()
    )
    verdict = "PASS_81_MUTUAL_EXCLUSIVITY_POOL_GATE" if all_cells_pass and full_source_pass else "HALT_81_POOL_INSUFFICIENT_OR_INCOMPLETE"
    with (output / "cell_sufficiency.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    decision = {
        "schema": "resetp.china81.pool-sufficiency.decision.v2",
        "verdict": verdict,
        "generated_utc": datetime.now(UTC).isoformat(),
        "search_evaluations": 0,
        "pool_package": display_path(pool_root),
        "pool_package_verdict": pool_verdict,
        "overlay_packages": overlay_verdicts,
        "region_size_cells_passed": sum(bool(row["pass"]) for row in rows),
        "region_size_cells_required": 27,
        "formal_instance_build_allowed": verdict == "PASS_81_MUTUAL_EXCLUSIVITY_POOL_GATE",
        "failed_cells": [f"{row['region']}/{row['customer_size']}" for row in rows if not row["pass"]],
        "cross_city_identity_overlaps": cross_city_overlaps,
        "rule": "For each region-size cell, 01/02/03 need disjoint OSM identities under every frozen city quota; cross-size reuse is allowed.",
    }
    write_json(output / "decision.json", decision)
    write_json(
        output / "metadata.json",
        {
            "schema": "resetp.china81.pool-sufficiency.metadata.v2",
            "contract": str(CONTRACT.relative_to(REPO)),
            "contract_sha256": sha256(CONTRACT),
            "pool_decision_sha256": sha256(pool_decision_path) if pool_decision_path.exists() else None,
            "customer_pool_counts": counts,
            "cross_city_identity_overlaps": cross_city_overlaps,
            "overlay_packages": [display_path(root) for root in overlay_roots],
            "search_evaluations": 0,
        },
    )
    report = [
        "# 中国81算例客户池互斥充足性门",
        "",
        f"结论：`{verdict}`。通过 {decision['region_size_cells_passed']}/27 个城市群×客户规模单元。",
        "",
        "本门要求每个单元的01/02/03三个算例在OSM客户身份上零重叠；跨规模允许复用。任何不足都只能补抓源池，不能看过算法结果后改客户或放宽配额。",
        "",
        "| 城市群 | 客户数 | 三复本客户总数 | 分城市可用/所需 | 结果 |",
        "|---|---:|---:|---|---|",
    ]
    report.extend(
        f"| {row['region']} | {row['customer_size']} | {row['required_total']} | {row['city_availability']} | {'PASS' if row['pass'] else 'HALT'} |"
        for row in rows
    )
    (output / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    files = [output / "cell_sufficiency.csv", output / "decision.json", output / "metadata.json", output / "report.md"]
    write_json(
        output / "artifact_hashes.json",
        {"schema": "resetp.artifact-hashes.v1", "files": {display_path(path): sha256(path) for path in files}},
    )
    return decision


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool-root", type=Path, default=DEFAULT_POOL)
    parser.add_argument("--overlay-root", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    decision = audit(
        args.pool_root.resolve(),
        args.output.resolve(),
        tuple(path.resolve() for path in args.overlay_root),
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
