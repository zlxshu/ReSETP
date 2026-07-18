#!/usr/bin/env python3
"""Close the MC-005 Chongqing identity-pool precondition without changing quotas."""

from __future__ import annotations

import csv
import hashlib
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


REPO = Path(__file__).resolve().parents[2]
BASE_POOL = REPO / "data/ChinaInstances/china9_city_full_pool_20260718_rerun_overpass_v2"
OLD_OVERLAY = REPO / "data/ChinaInstances/china81_customer_pool_replenishment_map_api_v2_20260718"
PPS_PACKAGE = REPO / "data/ChinaInstances/china_city_pps_calibration_v2_20260718"
DEFAULT_OUTPUT = REPO / "data/ChinaInstances/china81_chongqing_mc005_pool_closure_20260718"
ENDPOINT = "https://api.openstreetmap.org/api/0.6/map"
USER_AGENT = "ReSETP-MC005-Chongqing-Pool/1.0 (academic reproducibility)"
CITY = "chongqing"
REGION = "cy"
INNER_GRID = 4
OUTER_GRID = 6
REPLICATES = 3
REQUIRED_CHONGQING_PER_REPLICATE = 116
REQUIRED_CHONGQING_UNIQUE = REQUIRED_CHONGQING_PER_REPLICATE * REPLICATES

POOL_FIELDS = [
    "city",
    "region",
    "feature",
    "osm_type",
    "osm_id",
    "latitude",
    "longitude",
    "coordinate_status",
    "name",
    "brand",
    "tags",
    "source_response_path",
    "source_response_sha256",
    "source_query_bbox",
    "positive_power_tag",
    "positive_capacity_tag",
    "socket_tag_present",
    "power_tags_json",
    "capacity_tags_json",
    "socket_tags_json",
]
RUN_FIELDS = [
    "tile",
    "status",
    "http_status",
    "request_path",
    "request_sha256",
    "raw_path",
    "raw_sha256",
    "raw_bytes",
    "customer_elements",
    "elapsed_seconds",
    "retrieved_utc",
    "failure_reason",
]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def clean_appledouble(root: Path) -> None:
    for path in sorted(root.rglob("._*")):
        if path.is_file():
            path.unlink()


def identity(row: dict[str, Any]) -> tuple[str, str]:
    return str(row["osm_type"]), str(row["osm_id"])


def is_customer(tags: dict[str, str]) -> bool:
    return bool(tags.get("name") or tags.get("brand")) and (
        "shop" in tags
        or tags.get("amenity") in {"restaurant", "cafe", "marketplace"}
        or "office" in tags
    )


def parse_customers(raw_path: Path, query_box: dict[str, float]) -> list[dict[str, Any]]:
    root = ET.fromstring(raw_path.read_bytes())
    coordinates = {
        node.attrib["id"]: (float(node.attrib["lat"]), float(node.attrib["lon"]))
        for node in root.findall("node")
    }
    rows: list[dict[str, Any]] = []
    for element in root.findall("node"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in element.findall("tag")}
        if not is_customer(tags):
            continue
        rows.append(
            pool_row(
                osm_type="node",
                osm_id=element.attrib["id"],
                latitude=float(element.attrib["lat"]),
                longitude=float(element.attrib["lon"]),
                tags=tags,
                raw_path=raw_path,
                query_box=query_box,
            )
        )
    for element in root.findall("way"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in element.findall("tag")}
        if not is_customer(tags):
            continue
        points = [
            coordinates[node.attrib["ref"]]
            for node in element.findall("nd")
            if node.attrib["ref"] in coordinates
        ]
        if not points:
            continue
        rows.append(
            pool_row(
                osm_type="way",
                osm_id=element.attrib["id"],
                latitude=sum(point[0] for point in points) / len(points),
                longitude=sum(point[1] for point in points) / len(points),
                tags=tags,
                raw_path=raw_path,
                query_box=query_box,
            )
        )
    return rows


def pool_row(
    *,
    osm_type: str,
    osm_id: str,
    latitude: float,
    longitude: float,
    tags: dict[str, str],
    raw_path: Path,
    query_box: dict[str, float],
) -> dict[str, Any]:
    return {
        "city": CITY,
        "region": REGION,
        "feature": "named_poi",
        "osm_type": osm_type,
        "osm_id": osm_id,
        "latitude": f"{latitude:.7f}",
        "longitude": f"{longitude:.7f}",
        "coordinate_status": "center_or_node",
        "name": tags.get("name", ""),
        "brand": tags.get("brand", ""),
        "tags": json.dumps(tags, ensure_ascii=False, sort_keys=True),
        "source_response_path": display_path(raw_path),
        "source_response_sha256": sha256(raw_path),
        "source_query_bbox": json.dumps(
            [query_box["south"], query_box["west"], query_box["north"], query_box["east"]]
        ),
        "positive_power_tag": "",
        "positive_capacity_tag": "",
        "socket_tag_present": "",
        "power_tags_json": "{}",
        "capacity_tags_json": "{}",
        "socket_tags_json": "{}",
    }


def fixed_outer_ring() -> dict[str, dict[str, float]]:
    """Return a one-tile ring around the frozen 4x4 Chongqing Map API grid."""
    old_tiles = read_json(OLD_OVERLAY / "query_tiles.json")[CITY]
    south = min(float(box["south"]) for box in old_tiles.values())
    west = min(float(box["west"]) for box in old_tiles.values())
    north = max(float(box["north"]) for box in old_tiles.values())
    east = max(float(box["east"]) for box in old_tiles.values())
    lat_step = (north - south) / INNER_GRID
    lon_step = (east - west) / INNER_GRID
    outer_south = south - lat_step
    outer_west = west - lon_step
    tiles: dict[str, dict[str, float]] = {}
    for row in range(OUTER_GRID):
        for col in range(OUTER_GRID):
            if 1 <= row <= INNER_GRID and 1 <= col <= INNER_GRID:
                continue
            tiles[f"ring_r{row}c{col}"] = {
                "south": outer_south + row * lat_step,
                "west": outer_west + col * lon_step,
                "north": outer_south + (row + 1) * lat_step,
                "east": outer_west + (col + 1) * lon_step,
            }
    if len(tiles) != OUTER_GRID * OUTER_GRID - INNER_GRID * INNER_GRID:
        raise AssertionError("fixed outer ring must contain exactly 20 tiles")
    return tiles


def fetch(tile: str, box: dict[str, float], output: Path, timeout: float) -> dict[str, Any]:
    bbox = f"{box['west']:.7f},{box['south']:.7f},{box['east']:.7f},{box['north']:.7f}"
    url = ENDPOINT + "?" + urllib.parse.urlencode({"bbox": bbox})
    request_path = output / "requests" / f"{CITY}__{tile}.request.txt"
    raw_path = output / "raw" / f"{CITY}__{tile}.osm"
    request_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(f"GET {url}\nUser-Agent: {USER_AGENT}\n", encoding="utf-8")
    started = time.monotonic()
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/xml"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body, status = response.read(), int(response.status)
        raw_path.write_bytes(body)
        return {
            "tile": tile,
            "status": "success",
            "http_status": status,
            "request_path": display_path(request_path),
            "request_sha256": sha256(request_path),
            "raw_path": display_path(raw_path),
            "raw_sha256": sha256(raw_path),
            "raw_bytes": len(body),
            "customer_elements": len(parse_customers(raw_path, box)),
            "elapsed_seconds": round(time.monotonic() - started, 6),
            "retrieved_utc": datetime.now(UTC).isoformat(),
            "failure_reason": "",
        }
    except Exception as exc:  # noqa: BLE001 - preserve exact external failure.
        error_path = output / "raw" / f"{CITY}__{tile}.error.txt"
        error_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        return {
            "tile": tile,
            "status": "failed",
            "http_status": getattr(exc, "code", ""),
            "request_path": display_path(request_path),
            "request_sha256": sha256(request_path),
            "raw_path": "",
            "raw_sha256": "",
            "raw_bytes": 0,
            "customer_elements": 0,
            "elapsed_seconds": round(time.monotonic() - started, 6),
            "retrieved_utc": datetime.now(UTC).isoformat(),
            "failure_reason": f"{type(exc).__name__}: {exc}",
        }


def candidate_a_quotas() -> dict[str, dict[str, dict[str, int]]]:
    decision = read_json(PPS_PACKAGE / "decision.json")
    return decision["proposed_patch_not_applied"]["proposed_city_quotas"]


def all_city_identities(
    new_chongqing: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, set[tuple[str, str]]]:
    identities: dict[str, set[tuple[str, str]]] = {}
    for path in sorted((BASE_POOL / "pools").glob("*__named_poi.csv")):
        city = path.name.split("__", 1)[0]
        identities.setdefault(city, set()).update(identity(row) for row in read_rows(path))
    for path in sorted((OLD_OVERLAY / "pools").glob("*__named_poi.csv")):
        city = path.name.split("__", 1)[0]
        identities.setdefault(city, set()).update(identity(row) for row in read_rows(path))
    identities[CITY] = set(new_chongqing)
    return identities


def audit_cells(
    identities: dict[str, set[tuple[str, str]]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    quotas = candidate_a_quotas()
    rows: list[dict[str, Any]] = []
    region_cities = {
        region: sorted({city for table in sizes.values() for city in table})
        for region, sizes in quotas.items()
    }
    overlaps: dict[str, int] = {}
    for region, cities in region_cities.items():
        overlaps[region] = sum(
            len(identities.get(city_a, set()) & identities.get(city_b, set()))
            for index, city_a in enumerate(cities)
            for city_b in cities[index + 1 :]
        )
    for region, sizes in quotas.items():
        for size_text, city_quotas in sizes.items():
            details: list[str] = []
            passed = True
            for city, quota in city_quotas.items():
                available = len(identities.get(city, set()))
                required = int(quota) * REPLICATES
                details.append(f"{city}:{available}/{required}")
                passed &= available >= required
            rows.append(
                {
                    "region": region,
                    "customer_size": int(size_text),
                    "replicates": REPLICATES,
                    "required_total": int(size_text) * REPLICATES,
                    "city_availability": ";".join(details),
                    "pass": passed,
                }
            )
    return sorted(rows, key=lambda row: (row["region"], row["customer_size"])), overlaps


def run(output: Path, workers: int, timeout: float) -> dict[str, Any]:
    if output.exists() and (output / "decision.json").exists():
        raise RuntimeError(f"refuse to overwrite completed evidence package: {output}")
    output.mkdir(parents=True, exist_ok=True)
    ring = fixed_outer_ring()
    task_contract = {
        "schema": "resetp.china81.mc005-chongqing-pool-task-contract.v1",
        "approval_id": "MC-005",
        "selection_rule": (
            "Fetch every tile in the deterministic one-tile ring around the prior frozen "
            "4x4 Chongqing Map API grid; no result-dependent tile selection or early stopping."
        ),
        "source_api": "OpenStreetMap Map API 0.6",
        "source_license": "Open Data Commons Open Database License (ODbL) 1.0",
        "required_attribution": "OpenStreetMap and its contributors",
        "license_url": "https://www.openstreetmap.org/copyright",
        "customer_rule": (
            "named or branded OSM node/way with shop, office, or amenity in "
            "{restaurant,cafe,marketplace}; identical to the frozen location contract"
        ),
        "identity_key": ["osm_type", "osm_id"],
        "required_new_unique_beyond_prior_pool": 43,
        "prior_unique": 305,
        "required_total_unique": REQUIRED_CHONGQING_UNIQUE,
        "required_tiles": len(ring),
        "all_tiles_must_succeed": True,
        "quota_change_allowed": False,
        "formal_search_allowed": False,
        "search_evaluations": 0,
    }
    write_json(output / "task_contract.json", task_contract)
    write_json(output / "query_tiles.json", {CITY: ring})

    runs = read_rows(output / "raw_runs.csv")
    successes = {row["tile"]: row for row in runs if row["status"] == "success"}
    tasks = [(tile, box) for tile, box in ring.items() if tile not in successes]
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 2))) as executor:
        futures = {
            executor.submit(fetch, tile, box, output, timeout): tile
            for tile, box in tasks
        }
        for future in as_completed(futures):
            row = future.result()
            runs.append(row)
            write_csv(
                output / "raw_runs.csv",
                sorted(runs, key=lambda item: item["tile"]),
                RUN_FIELDS,
            )
    successes = {row["tile"]: row for row in runs if row["status"] == "success"}

    prior_rows = read_rows(OLD_OVERLAY / "pools" / f"{CITY}__named_poi.csv")
    merged = {identity(row): row for row in prior_rows}
    prior_identities = set(merged)
    new_source_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for tile, box in ring.items():
        run_row = successes.get(tile)
        if not run_row:
            continue
        raw_path = REPO / run_row["raw_path"]
        for row in parse_customers(raw_path, box):
            row_identity = identity(row)
            if row_identity not in prior_identities:
                new_source_rows[row_identity] = row
            merged.setdefault(row_identity, row)
    write_csv(
        output / "pools" / f"{CITY}__new_named_poi.csv",
        (new_source_rows[key] for key in sorted(new_source_rows)),
        POOL_FIELDS,
    )
    write_csv(
        output / "pools" / f"{CITY}__merged_named_poi.csv",
        (merged[key] for key in sorted(merged)),
        POOL_FIELDS,
    )

    identities = all_city_identities(merged)
    cell_rows, overlaps = audit_cells(identities)
    write_csv(
        output / "cell_sufficiency_candidate_a.csv",
        cell_rows,
        [
            "region",
            "customer_size",
            "replicates",
            "required_total",
            "city_availability",
            "pass",
        ],
    )
    all_tiles_pass = len(successes) == len(ring)
    all_cells_pass = len(cell_rows) == 27 and all(bool(row["pass"]) for row in cell_rows)
    no_cross_city_overlap = all(value == 0 for value in overlaps.values())
    enough_new = len(new_source_rows) >= 43 and len(merged) >= REQUIRED_CHONGQING_UNIQUE
    source_identity_traceable = all(
        row["source_response_path"]
        and row["source_response_sha256"]
        and (REPO / row["source_response_path"]).exists()
        and sha256(REPO / row["source_response_path"]) == row["source_response_sha256"]
        for row in new_source_rows.values()
    )
    passed = (
        all_tiles_pass
        and all_cells_pass
        and no_cross_city_overlap
        and enough_new
        and source_identity_traceable
    )
    verdict = (
        "PASS_MC005_CHONGQING_POOL_AND_27_CELL_GATE"
        if passed
        else "HALT_MC005_CHONGQING_POOL_OR_27_CELL_GATE"
    )
    decision = {
        "schema": "resetp.china81.mc005-chongqing-pool-decision.v1",
        "verdict": verdict,
        "generated_utc": datetime.now(UTC).isoformat(),
        "approval_id": "MC-005",
        "search_evaluations": 0,
        "formal_search_allowed": False,
        "quota_change_allowed": False,
        "prior_chongqing_unique": len(prior_identities),
        "new_chongqing_unique": len(new_source_rows),
        "merged_chongqing_unique": len(merged),
        "required_chongqing_unique": REQUIRED_CHONGQING_UNIQUE,
        "successful_tiles": len(successes),
        "required_tiles": len(ring),
        "source_identity_traceable": source_identity_traceable,
        "region_size_cells_passed": sum(bool(row["pass"]) for row in cell_rows),
        "region_size_cells_required": 27,
        "failed_cells": [
            f"{row['region']}/{row['customer_size']}"
            for row in cell_rows
            if not row["pass"]
        ],
        "cross_city_identity_overlaps": overlaps,
        "boundary": (
            "PASS only closes the MC-005 source-pool and mutual-exclusivity precondition. "
            "OSM POIs are mapped eligible scenario identities, not observed historical customers."
        ),
    }
    write_json(output / "decision.json", decision)
    write_json(
        output / "metadata.json",
        {
            "schema": "resetp.china81.mc005-chongqing-pool-metadata.v1",
            "runner": display_path(Path(__file__).resolve()),
            "runner_sha256": sha256(Path(__file__).resolve()),
            "base_pool": display_path(BASE_POOL),
            "base_pool_decision_sha256": sha256(BASE_POOL / "decision.json"),
            "prior_overlay": display_path(OLD_OVERLAY),
            "prior_overlay_decision_sha256": sha256(OLD_OVERLAY / "decision.json"),
            "pps_package": display_path(PPS_PACKAGE),
            "pps_decision_sha256": sha256(PPS_PACKAGE / "decision.json"),
            "source_license": "Open Data Commons Open Database License (ODbL) 1.0",
            "required_attribution": "OpenStreetMap and its contributors",
            "license_url": "https://www.openstreetmap.org/copyright",
            "customer_pool_counts": {
                city: len(city_identities)
                for city, city_identities in sorted(identities.items())
            },
            "cross_city_identity_overlaps": overlaps,
            "search_evaluations": 0,
        },
    )
    report_lines = [
        "# MC-005 重庆客户身份池与候选A 27格复核",
        "",
        f"结论：`{verdict}`。",
        "",
        (
            f"既有重庆池 {len(prior_identities)} 个OSM身份；固定外围一圈20块新增 "
            f"{len(new_source_rows)} 个不重复身份；合并后 {len(merged)} 个，"
            f"候选A所需 {REQUIRED_CHONGQING_UNIQUE} 个。"
        ),
        "",
        (
            f"固定块成功 {len(successes)}/{len(ring)}；新身份原始响应逐项可追溯="
            f"{source_identity_traceable}；候选A充足性通过 "
            f"{sum(bool(row['pass']) for row in cell_rows)}/27；"
            f"区域内跨城市身份冲突={overlaps}。"
        ),
        "",
        (
            "选择规则在抓取前固定为既有4×4框的单块宽外围一圈，整圈抓完，"
            "不按抓取结果选择方向或提前停止；GDP-PPS配额未改变。"
        ),
        "",
        (
            "边界：OSM节点/道路要素是真实、可追溯的已测绘POI身份，但不是企业"
            "历史订单或观测客户。PASS仅关闭MC-005的源池与同格三复本互斥前置，"
            "不授权正式实例或搜索。"
        ),
        "",
        (
            "许可：数据来自OpenStreetMap及其贡献者，采用ODbL 1.0；后续分发或"
            "制图须保留OpenStreetMap署名并遵守相同许可。许可页："
            "https://www.openstreetmap.org/copyright"
        ),
        "",
        "| 城市群 | 客户数 | 三复本总数 | 分城市可用/所需 | 结果 |",
        "|---|---:|---:|---|---|",
    ]
    report_lines.extend(
        f"| {row['region']} | {row['customer_size']} | {row['required_total']} | "
        f"{row['city_availability']} | {'PASS' if row['pass'] else 'HALT'} |"
        for row in cell_rows
    )
    (output / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    clean_appledouble(output)
    files = [
        path
        for path in sorted(output.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    ]
    files.append(Path(__file__).resolve())
    write_json(
        output / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "files": {display_path(path): sha256(path) for path in files},
        },
    )
    clean_appledouble(output)
    return decision


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    decision = run(args.output.resolve(), args.workers, args.timeout)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
