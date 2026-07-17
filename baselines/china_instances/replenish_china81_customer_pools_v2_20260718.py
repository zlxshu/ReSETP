#!/usr/bin/env python3
"""Expand and tile the Shijiazhuang/Chongqing customer pools without changing quotas."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import extract_china9_full_pool_20260718 as base


REPO = Path(__file__).resolve().parents[2]
BASE_POOL = REPO / "data/ChinaInstances/china9_city_full_pool_20260718_rerun_overpass_v2"
DEFAULT_OUTPUT = REPO / "data/ChinaInstances/china81_customer_pool_replenishment_v2_20260718"
CITIES = ("shijiazhuang", "chongqing")
BOX_SCALE = 2.0
ENDPOINTS = (
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expanded_tiles(box: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Double total width/height, then split into four original-area tiles."""

    center_lat = (float(box["south"]) + float(box["north"])) / 2
    center_lon = (float(box["west"]) + float(box["east"])) / 2
    half_lat = (float(box["north"]) - float(box["south"])) * BOX_SCALE / 2
    half_lon = (float(box["east"]) - float(box["west"])) * BOX_SCALE / 2
    south, north = center_lat - half_lat, center_lat + half_lat
    west, east = center_lon - half_lon, center_lon + half_lon
    return {
        "sw": {**box, "south": south, "west": west, "north": center_lat, "east": center_lon},
        "se": {**box, "south": south, "west": center_lon, "north": center_lat, "east": east},
        "nw": {**box, "south": center_lat, "west": west, "north": north, "east": center_lon},
        "ne": {**box, "south": center_lat, "west": center_lon, "north": north, "east": east},
    }


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def run(output: Path, workers: int, retries: int, timeout: float) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    boxes = json.loads((BASE_POOL / "query_boxes.json").read_text(encoding="utf-8"))
    tile_boxes = {city: expanded_tiles(boxes[city]) for city in CITIES}
    write_json(output / "query_tiles.json", tile_boxes)
    run_path = output / "raw_runs.csv"
    prior = read_rows(run_path)
    done = {(row["city"], row["tile"]) for row in prior if row.get("status") == "success"}
    tasks = [(city, tile, tile_box) for city in CITIES for tile, tile_box in tile_boxes[city].items() if (city, tile) not in done]
    new_rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 2))) as executor:
        futures = {
            executor.submit(
                base.fetch_one,
                city,
                "named_poi",
                tile_box,
                output / "tiles" / f"{city}__{tile}",
                ENDPOINTS,
                retries,
                timeout,
            ): (city, tile)
            for city, tile, tile_box in tasks
        }
        for future in as_completed(futures):
            city, tile = futures[future]
            row = future.result()
            row["tile"] = tile
            row["run_id"] = f"{city}:{tile}:{row['run_id']}"
            new_rows.append(row)
    runs = prior + new_rows
    fields = ["tile", *base.RUN_FIELDS]
    base.write_csv(run_path, sorted(runs, key=lambda row: row["run_id"]), fields)

    merged_counts: dict[str, dict[str, int]] = {}
    all_success = True
    for city in CITIES:
        merged: dict[tuple[str, str], dict[str, Any]] = {
            (row["osm_type"], row["osm_id"]): row
            for row in read_rows(BASE_POOL / "pools" / f"{city}__named_poi.csv")
        }
        base_count = len(merged)
        city_success = 0
        for tile, tile_box in tile_boxes[city].items():
            successes = [row for row in runs if row["city"] == city and row["tile"] == tile and row["status"] == "success"]
            if not successes:
                all_success = False
                continue
            city_success += 1
            tile_output = output / "tiles" / f"{city}__{tile}"
            rows = base.materialize_pool(city, "named_poi", tile_box, successes[0], tile_output)
            for row in rows:
                merged[(str(row["osm_type"]), str(row["osm_id"]))] = row
        pool_path = output / "pools" / f"{city}__named_poi.csv"
        base.write_csv(pool_path, merged.values(), base.POOL_FIELDS)
        merged_counts[city] = {
            "base_unique": base_count,
            "successful_tiles": city_success,
            "required_tiles": 4,
            "merged_unique": len(merged),
            "new_unique": len(merged) - base_count,
        }
    verdict = "PASS_CUSTOMER_POOL_REPLENISHMENT" if all_success else "HALT_CUSTOMER_POOL_REPLENISHMENT_INCOMPLETE"
    decision = {
        "schema": "resetp.china81.customer-pool-replenishment.decision.v2",
        "verdict": verdict,
        "generated_utc": datetime.now(UTC).isoformat(),
        "search_evaluations": 0,
        "box_scale": BOX_SCALE,
        "cities": list(CITIES),
        "counts": merged_counts,
        "quota_change_allowed": False,
        "formal_instance_build_allowed": False,
        "next_gate": "rerun China81 pool sufficiency audit with this directory as an overlay",
    }
    write_json(output / "decision.json", decision)
    write_json(
        output / "metadata.json",
        {
            "schema": "resetp.china81.customer-pool-replenishment.metadata.v2",
            "base_pool": str(BASE_POOL.relative_to(REPO)),
            "base_pool_decision_sha256": sha256(BASE_POOL / "decision.json"),
            "script": str(Path(__file__).resolve().relative_to(REPO)),
            "script_sha256": sha256(Path(__file__).resolve()),
            "search_evaluations": 0,
        },
    )
    lines = [
        "# 石家庄/重庆客户池扩抓",
        "",
        f"结论：`{verdict}`。固定城市配额不变；查询框总宽高各扩大到原来的{BOX_SCALE:.1f}倍并拆成四块，避免大框超时。",
        "",
        "| 城市 | 原池 | 新增唯一POI | 合并池 | 成功块 |",
        "|---|---:|---:|---:|---:|",
    ]
    lines.extend(
        f"| {city} | {row['base_unique']} | {row['new_unique']} | {row['merged_unique']} | {row['successful_tiles']}/4 |"
        for city, row in merged_counts.items()
    )
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    files = sorted(path for path in output.rglob("*") if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._"))
    write_json(
        output / "artifact_hashes.json",
        {"schema": "resetp.artifact-hashes.v1", "files": {str(path.relative_to(REPO)): sha256(path) for path in files}},
    )
    base.clean_appledouble(output)
    return decision


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()
    print(json.dumps(run(args.output.resolve(), args.workers, args.retries, args.timeout), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
