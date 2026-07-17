#!/usr/bin/env python3
"""Fallback customer-pool replenishment using official OSM Map API snapshots."""

from __future__ import annotations

import argparse
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
from typing import Any

import extract_china9_full_pool_20260718 as base


REPO = Path(__file__).resolve().parents[2]
BASE_POOL = REPO / "data/ChinaInstances/china9_city_full_pool_20260718_rerun_overpass_v2"
DEFAULT_OUTPUT = REPO / "data/ChinaInstances/china81_customer_pool_replenishment_map_api_v2_20260718"
ENDPOINT = "https://api.openstreetmap.org/api/0.6/map"
USER_AGENT = "ReSETP-China81-Pool/2.0 (academic reproducibility)"
CITIES = ("shijiazhuang", "chongqing")
REQUIRED_UNIQUE = {"shijiazhuang": 60, "chongqing": 180}
BOX_SCALE = 2.0
GRID = 4


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
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def tiles(box: dict[str, Any]) -> dict[str, dict[str, float]]:
    center_lat = (float(box["south"]) + float(box["north"])) / 2
    center_lon = (float(box["west"]) + float(box["east"])) / 2
    half_lat = (float(box["north"]) - float(box["south"])) * BOX_SCALE / 2
    half_lon = (float(box["east"]) - float(box["west"])) * BOX_SCALE / 2
    south, north = center_lat - half_lat, center_lat + half_lat
    west, east = center_lon - half_lon, center_lon + half_lon
    lat_step, lon_step = (north - south) / GRID, (east - west) / GRID
    return {
        f"r{row}c{col}": {
            "south": south + row * lat_step,
            "west": west + col * lon_step,
            "north": south + (row + 1) * lat_step,
            "east": west + (col + 1) * lon_step,
        }
        for row in range(GRID)
        for col in range(GRID)
    }


def is_customer(tags: dict[str, str]) -> bool:
    return bool(tags.get("name") or tags.get("brand")) and (
        "shop" in tags or tags.get("amenity") in {"restaurant", "cafe", "marketplace"} or "office" in tags
    )


def parse_customers(raw_path: Path, city: str) -> list[dict[str, Any]]:
    root = ET.fromstring(raw_path.read_bytes())
    coordinates = {
        node.attrib["id"]: (float(node.attrib["lat"]), float(node.attrib["lon"])) for node in root.findall("node")
    }
    rows: list[dict[str, Any]] = []
    for element in root.findall("node"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in element.findall("tag")}
        if is_customer(tags):
            rows.append(
                {
                    "osm_type": "node",
                    "osm_id": element.attrib["id"],
                    "latitude": element.attrib["lat"],
                    "longitude": element.attrib["lon"],
                    "tags": tags,
                }
            )
    for element in root.findall("way"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in element.findall("tag")}
        if not is_customer(tags):
            continue
        points = [coordinates[node.attrib["ref"]] for node in element.findall("nd") if node.attrib["ref"] in coordinates]
        if not points:
            continue
        rows.append(
            {
                "osm_type": "way",
                "osm_id": element.attrib["id"],
                "latitude": sum(point[0] for point in points) / len(points),
                "longitude": sum(point[1] for point in points) / len(points),
                "tags": tags,
            }
        )
    return rows


def fetch(city: str, tile: str, box: dict[str, float], output: Path, timeout: float) -> dict[str, Any]:
    bbox = f"{box['west']:.7f},{box['south']:.7f},{box['east']:.7f},{box['north']:.7f}"
    url = ENDPOINT + "?" + urllib.parse.urlencode({"bbox": bbox})
    request_path = output / "requests" / f"{city}__{tile}.request.txt"
    raw_path = output / "raw" / f"{city}__{tile}.osm"
    request_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(f"GET {url}\nUser-Agent: {USER_AGENT}\n", encoding="utf-8")
    started = time.monotonic()
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/xml"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body, status = response.read(), int(response.status)
        raw_path.write_bytes(body)
        count = len(parse_customers(raw_path, city))
        return {
            "city": city,
            "tile": tile,
            "status": "success",
            "http_status": status,
            "request_path": str(request_path.relative_to(REPO)),
            "request_sha256": sha256(request_path),
            "raw_path": str(raw_path.relative_to(REPO)),
            "raw_sha256": sha256(raw_path),
            "raw_bytes": len(body),
            "customer_elements": count,
            "elapsed_seconds": round(time.monotonic() - started, 6),
            "retrieved_utc": datetime.now(UTC).isoformat(),
            "failure_reason": "",
        }
    except Exception as exc:  # noqa: BLE001 - preserve the external failure.
        error_path = output / "raw" / f"{city}__{tile}.error.txt"
        error_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        return {
            "city": city,
            "tile": tile,
            "status": "failed",
            "http_status": getattr(exc, "code", ""),
            "request_path": str(request_path.relative_to(REPO)),
            "request_sha256": sha256(request_path),
            "raw_path": "",
            "raw_sha256": "",
            "raw_bytes": 0,
            "customer_elements": 0,
            "elapsed_seconds": round(time.monotonic() - started, 6),
            "retrieved_utc": datetime.now(UTC).isoformat(),
            "failure_reason": f"{type(exc).__name__}: {exc}",
        }


RUN_FIELDS = [
    "city", "tile", "status", "http_status", "request_path", "request_sha256", "raw_path", "raw_sha256",
    "raw_bytes", "customer_elements", "elapsed_seconds", "retrieved_utc", "failure_reason",
]


def run(output: Path, workers: int, timeout: float) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    boxes = json.loads((BASE_POOL / "query_boxes.json").read_text(encoding="utf-8"))
    query_tiles = {city: tiles(boxes[city]) for city in CITIES}
    write_json(output / "query_tiles.json", query_tiles)
    runs = read_rows(output / "raw_runs.csv")
    done = {(row["city"], row["tile"]) for row in runs if row["status"] == "success"}
    tasks = [(city, tile, box) for city in CITIES for tile, box in query_tiles[city].items() if (city, tile) not in done]
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 2))) as executor:
        futures = {executor.submit(fetch, city, tile, box, output, timeout): (city, tile) for city, tile, box in tasks}
        for future in as_completed(futures):
            runs.append(future.result())
            base.write_csv(output / "raw_runs.csv", sorted(runs, key=lambda row: (row["city"], row["tile"])), RUN_FIELDS)
    success = {(row["city"], row["tile"]): row for row in runs if row["status"] == "success"}
    counts: dict[str, dict[str, int]] = {}
    for city in CITIES:
        merged = {(row["osm_type"], row["osm_id"]): row for row in read_rows(BASE_POOL / "pools" / f"{city}__named_poi.csv")}
        base_count = len(merged)
        for tile in query_tiles[city]:
            row = success.get((city, tile))
            if not row:
                continue
            for item in parse_customers(REPO / row["raw_path"], city):
                tags = item.pop("tags")
                pool_row = {
                    "city": city,
                    "region": base.CITIES[city]["region"],
                    "feature": "named_poi",
                    **item,
                    "coordinate_status": "center_or_node",
                    "name": tags.get("name", ""),
                    "brand": tags.get("brand", ""),
                    "tags": json.dumps(tags, ensure_ascii=False, sort_keys=True),
                    "source_response_path": row["raw_path"],
                    "source_response_sha256": row["raw_sha256"],
                    "source_query_bbox": json.dumps(list(query_tiles[city][tile].values())),
                    "positive_power_tag": "",
                    "positive_capacity_tag": "",
                    "socket_tag_present": "",
                    "power_tags_json": "{}",
                    "capacity_tags_json": "{}",
                    "socket_tags_json": "{}",
                }
                merged[(str(pool_row["osm_type"]), str(pool_row["osm_id"]))] = pool_row
        base.write_csv(output / "pools" / f"{city}__named_poi.csv", merged.values(), base.POOL_FIELDS)
        counts[city] = {"base_unique": base_count, "merged_unique": len(merged), "new_unique": len(merged) - base_count, "required_unique": REQUIRED_UNIQUE[city]}
    complete = len(success) == len(CITIES) * GRID * GRID
    sufficient = all(row["merged_unique"] >= row["required_unique"] for row in counts.values())
    verdict = "PASS_CUSTOMER_POOL_REPLENISHMENT" if complete and sufficient else "HALT_CUSTOMER_POOL_REPLENISHMENT_INCOMPLETE"
    decision = {
        "schema": "resetp.china81.customer-pool-replenishment.decision.v2",
        "verdict": verdict,
        "generated_utc": datetime.now(UTC).isoformat(),
        "source_api": "OpenStreetMap Map API 0.6",
        "successful_tiles": len(success),
        "required_tiles": len(CITIES) * GRID * GRID,
        "counts": counts,
        "quota_change_allowed": False,
        "search_evaluations": 0,
        "formal_instance_build_allowed": False,
    }
    write_json(output / "decision.json", decision)
    write_json(output / "metadata.json", {"schema": "resetp.china81.map-api-replenishment.metadata.v2", "base_pool": str(BASE_POOL.relative_to(REPO)), "script": str(Path(__file__).resolve().relative_to(REPO)), "script_sha256": sha256(Path(__file__).resolve()), "search_evaluations": 0})
    (output / "report.md").write_text(
        "# OSM Map API客户池补抓\n\n"
        f"结论：`{verdict}`；成功块={len(success)}/{len(CITIES) * GRID * GRID}。固定配额未改变。\n\n"
        + "\n".join(f"- {city}: {row['base_unique']} + {row['new_unique']} = {row['merged_unique']}，门槛 {row['required_unique']}" for city, row in counts.items())
        + "\n",
        encoding="utf-8",
    )
    base.clean_appledouble(output)
    files = sorted(path for path in output.rglob("*") if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._"))
    write_json(output / "artifact_hashes.json", {"schema": "resetp.artifact-hashes.v1", "files": {str(path.relative_to(REPO)): sha256(path) for path in files}})
    return decision


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    print(json.dumps(run(args.output.resolve(), args.workers, args.timeout), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
