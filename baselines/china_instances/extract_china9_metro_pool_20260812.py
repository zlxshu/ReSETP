#!/usr/bin/env python3
"""Collect traceable OSM pools over nine metropolitan delivery boxes.

The collector is data-only and serial.  It preserves every Overpass query,
raw response or error, and never reads or writes solver results.  Existing
China81 suites are outside its write surface.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import subprocess
import time
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO = Path(__file__).resolve().parents[2]
LEGACY_SCRIPT = REPO / "baselines/china_instances/extract_china9_full_pool_20260718.py"
DEFAULT_OUTPUT = REPO / "data/ChinaInstances/china9_metro_pool_20260812"
ENDPOINTS = (
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
FEATURES = ("named_poi", "logistics_candidate", "charging_station")
TILE_PARTS = ("tile_sw", "tile_se", "tile_nw", "tile_ne")
USER_AGENT = "ReSETP-China9-Metro/1.0 (academic reproducibility)"

# Half-spans around the old query-box centre.  These boxes cover the main
# contiguous built delivery area while avoiding province-scale downloads.
HALF_SPANS = {
    "beijing": (0.28, 0.42),
    "tianjin": (0.25, 0.34),
    "shijiazhuang": (0.22, 0.28),
    "shenzhen": (0.22, 0.36),
    "dongguan": (0.25, 0.31),
    "guangzhou": (0.30, 0.38),
    "foshan": (0.28, 0.33),
    "chengdu": (0.30, 0.40),
    "chongqing": (0.31, 0.39),
}

LOGISTICS_NAME_TERMS = (
    "物流|仓储|配送中心|配送站|快递中心|快递分拨|货运|货场|物流园|物流中心|"
    "logistics|warehouse|distribution|freight|cargo"
)
LOGISTICS_EXACT_TAG_SET = {
    "building": [
        "warehouse",
        "depot only when a logistics/freight/warehouse name or depot subtype is present",
    ],
    "industrial": [
        "warehouse",
        "logistics",
        "distribution",
        "freight",
        "depot only when a logistics/freight/warehouse name or depot subtype is present",
    ],
    "landuse": [
        "industrial AND industrial in the exact logistics values",
        "industrial AND name matches explicit logistics/warehouse/distribution/freight terms",
    ],
    "amenity": ["post_depot", "freight_terminal"],
    "accepted_depot_subtypes": [
        "cargo",
        "distribution",
        "freight",
        "logistics",
        "postal",
        "truck",
        "warehouse",
    ],
    "excluded_transit_depot_subtypes": [
        "bus",
        "light_rail",
        "rail",
        "subway",
        "tram",
    ],
    "explicitly_removed_name_only_term": "园区",
}


def load_legacy() -> Any:
    spec = importlib.util.spec_from_file_location("china9_full_pool_legacy", LEGACY_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {LEGACY_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


legacy = load_legacy()
CITIES = legacy.CITIES
POOL_FIELDS = legacy.POOL_FIELDS
RUN_FIELDS = [*legacy.RUN_FIELDS, "query_part"]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    fields: Iterable[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def clean_appledouble(root: Path) -> list[str]:
    removed: list[str] = []
    for path in sorted(root.rglob("._*")) if root.exists() else []:
        if path.is_file():
            removed.append(str(path.relative_to(REPO)))
            path.unlink()
    return removed


def metro_boxes() -> dict[str, dict[str, Any]]:
    old = legacy.city_boxes()
    boxes: dict[str, dict[str, Any]] = {}
    for city, source in sorted(old.items()):
        centre_lat = (float(source["south"]) + float(source["north"])) / 2.0
        centre_lon = (float(source["west"]) + float(source["east"])) / 2.0
        half_lat, half_lon = HALF_SPANS[city]
        south, north = centre_lat - half_lat, centre_lat + half_lat
        west, east = centre_lon - half_lon, centre_lon + half_lon
        height_km = 111.195 * (north - south)
        width_km = 111.195 * math.cos(math.radians(centre_lat)) * (east - west)
        boxes[city] = {
            "city": city,
            "region": CITIES[city]["region"],
            "name_zh": CITIES[city]["name_zh"],
            "centre_latitude": centre_lat,
            "centre_longitude": centre_lon,
            "south": south,
            "west": west,
            "north": north,
            "east": east,
            "height_km": height_km,
            "width_km": width_km,
            "old_bbox": [source["south"], source["west"], source["north"], source["east"]],
            "rule": "old bbox centre plus city-specific metropolitan half-spans",
        }
    return boxes


def query_parts(feature: str) -> tuple[str, ...]:
    if feature == "logistics_candidate":
        return ("building", "industrial", "landuse_name", "amenity")
    return ("all",)


def tile_box(box: Mapping[str, Any], part: str) -> dict[str, Any]:
    if part.startswith("tile_"):
        quadrants = part.split("_")[1:]
    elif "__" in part:
        quadrants = part.split("__")[1:]
    else:
        return dict(box)
    current = dict(box)
    for quadrant in quadrants:
        if quadrant not in {"sw", "se", "nw", "ne"}:
            raise ValueError(f"invalid tile quadrant: {quadrant}")
        middle_lat = (float(current["south"]) + float(current["north"])) / 2.0
        middle_lon = (float(current["west"]) + float(current["east"])) / 2.0
        south = float(current["south"]) if quadrant in {"sw", "se"} else middle_lat
        north = middle_lat if quadrant in {"sw", "se"} else float(current["north"])
        west = float(current["west"]) if quadrant in {"sw", "nw"} else middle_lon
        east = middle_lon if quadrant in {"sw", "nw"} else float(current["east"])
        current.update({"south": south, "west": west, "north": north, "east": east})
    return current


def planned_parts(
    city: str,
    feature: str,
    runs: Iterable[Mapping[str, Any]],
) -> tuple[str, ...]:
    relevant = [
        row
        for row in runs
        if row.get("city") == city and row.get("feature") == feature
    ]
    if feature == "named_poi":
        if any(row.get("status") == "success" and row.get("query_part", "all") == "all" for row in relevant):
            return ("all",)
        parts = list(TILE_PARTS) if relevant else ["all"]
        child = lambda part, quadrant: f"{part}_{quadrant}"  # noqa: E731
    elif feature == "logistics_candidate":
        parts = list(query_parts(feature))
        child = lambda part, quadrant: f"{part}__{quadrant}"  # noqa: E731
    else:
        return query_parts(feature)
    if relevant:
        changed = True
        while changed:
            changed = False
            expanded: list[str] = []
            for part in parts:
                part_rows = [row for row in relevant if row.get("query_part") == part]
                if any(row.get("status") == "success" for row in part_rows):
                    expanded.append(part)
                elif part_rows:
                    expanded.extend(child(part, quadrant) for quadrant in ("sw", "se", "nw", "ne"))
                    changed = True
                else:
                    expanded.append(part)
            parts = expanded
    return tuple(parts)


def query_for(feature: str, box: Mapping[str, Any], part: str = "all") -> str:
    bbox = f"({box['south']:.8f},{box['west']:.8f},{box['north']:.8f},{box['east']:.8f})"
    if feature == "named_poi":
        selector = (
            f'nwr["shop"]{bbox};'
            f'nwr["amenity"~"^(restaurant|cafe|marketplace)$"]{bbox};'
            f'nwr["office"]{bbox};'
        )
    elif feature == "charging_station":
        selector = f'nwr["amenity"="charging_station"]{bbox};'
    elif feature == "logistics_candidate":
        base_part = part.split("__", 1)[0]
        if base_part == "building":
            selector = f'nwr["building"~"^(warehouse|depot)$"]{bbox};'
        elif base_part == "industrial":
            selector = f'nwr["industrial"~"^(warehouse|logistics|distribution|depot|freight)$"]{bbox};'
        elif base_part == "landuse_name":
            selector = (
                f'nwr["landuse"="industrial"]["name"~"{LOGISTICS_NAME_TERMS}",i]{bbox};'
            )
        elif base_part == "amenity":
            selector = f'nwr["amenity"~"^(post_depot|freight_terminal)$"]{bbox};'
        else:
            raise ValueError(part)
    else:
        raise ValueError(feature)
    return f"[out:json][timeout:240];({selector});out center tags;"


def logistics_match(tags: Mapping[str, Any]) -> bool:
    import re

    building = str(tags.get("building", ""))
    industrial = str(tags.get("industrial", ""))
    amenity = str(tags.get("amenity", ""))
    depot_subtype = str(tags.get("depot", "")).lower()
    explicit_name = bool(
        re.search(LOGISTICS_NAME_TERMS, str(tags.get("name", "")), re.I)
    )
    accepted_depot_subtype = depot_subtype in {
        "cargo",
        "distribution",
        "freight",
        "logistics",
        "postal",
        "truck",
        "warehouse",
    }
    if building == "warehouse":
        return True
    if building == "depot":
        return explicit_name or accepted_depot_subtype
    if industrial in {"warehouse", "logistics", "distribution", "freight"}:
        return True
    if industrial == "depot":
        return explicit_name or accepted_depot_subtype
    if amenity in {"post_depot", "freight_terminal"}:
        return True
    if tags.get("landuse") == "industrial":
        return explicit_name
    return False


def element_match(feature: str, tags: Mapping[str, Any]) -> bool:
    if feature == "named_poi":
        return bool(tags.get("name") or tags.get("brand")) and (
            "shop" in tags
            or tags.get("amenity") in {"restaurant", "cafe", "marketplace"}
            or "office" in tags
        )
    if feature == "charging_station":
        return tags.get("amenity") == "charging_station"
    if feature == "logistics_candidate":
        return logistics_match(tags)
    raise ValueError(feature)


def fetch_one(
    city: str,
    feature: str,
    box: Mapping[str, Any],
    output: Path,
    timeout: int,
    retries: int,
    part: str = "all",
) -> list[dict[str, Any]]:
    query = query_for(feature, box, part)
    records: list[dict[str, Any]] = []
    attempt = 0
    for endpoint_index, endpoint in enumerate(ENDPOINTS, start=1):
        for retry in range(1, retries + 1):
            attempt += 1
            part_token = "" if part == "all" else f"__{part}"
            host_token = urllib.parse.urlparse(endpoint).hostname.replace(".", "_")
            stem = (
                f"{city}__{feature}{part_token}__{host_token}"
                f"__e{endpoint_index}__a{retry}"
            )
            query_path = output / "requests" / f"{stem}.overpassql"
            request_path = output / "requests" / f"{stem}.request.txt"
            query_path.parent.mkdir(parents=True, exist_ok=True)
            query_path.write_text(query + "\n", encoding="utf-8")
            request_path.write_text(
                "\n".join(
                    [
                        f"POST {endpoint}",
                        "Content-Type: application/x-www-form-urlencoded",
                        f"User-Agent: {USER_AGENT}",
                        "TLS verification: enabled",
                        "",
                        query,
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            started = time.monotonic()
            command = [
                "curl",
                "--fail-with-body",
                "--silent",
                "--show-error",
                "--max-time",
                str(timeout),
                "--user-agent",
                USER_AGENT,
                "--data-urlencode",
                f"data={query}",
                endpoint,
            ]
            result = subprocess.run(command, capture_output=True, check=False)
            elapsed = round(time.monotonic() - started, 6)
            bbox = json.dumps(
                [box["south"], box["west"], box["north"], box["east"]]
            )
            if result.returncode == 0:
                try:
                    payload = json.loads(result.stdout.decode("utf-8"))
                    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
                        raise ValueError("Overpass response lacks an elements list")
                    if payload.get("remark"):
                        raise ValueError(
                            f"Overpass returned a partial/error remark: {payload['remark']}"
                        )
                except Exception as exc:  # noqa: BLE001
                    result = subprocess.CompletedProcess(
                        command,
                        90,
                        stdout=result.stdout,
                        stderr=f"{type(exc).__name__}: {exc}".encode(),
                    )
                else:
                    response_path = output / "raw" / f"{stem}.json"
                    response_path.parent.mkdir(parents=True, exist_ok=True)
                    response_path.write_bytes(result.stdout)
                    records.append(
                        {
                            "run_id": f"{city}:{feature}:{part}:{host_token}:{attempt}",
                            "city": city,
                            "region": CITIES[city]["region"],
                            "feature": feature,
                            "attempt": attempt,
                            "endpoint": endpoint,
                            "status": "success",
                            "http_status": 200,
                            "request_path": str(request_path.relative_to(REPO)),
                            "request_sha256": sha256_path(request_path),
                            "response_path": str(response_path.relative_to(REPO)),
                            "response_sha256": sha256_path(response_path),
                            "error_path": "",
                            "error_sha256": "",
                            "response_bytes": len(result.stdout),
                            "elapsed_seconds": elapsed,
                            "failure_reason": "",
                            "retrieved_utc": utc_now(),
                            "bbox": bbox,
                            "query_part": part,
                        }
                    )
                    return records
            error_path = output / "raw" / f"{stem}.error.txt"
            error_path.parent.mkdir(parents=True, exist_ok=True)
            error_text = result.stderr.decode("utf-8", errors="replace") or (
                f"curl exit {result.returncode}"
            )
            error_path.write_text(error_text.rstrip() + "\n", encoding="utf-8")
            records.append(
                {
                    "run_id": f"{city}:{feature}:{part}:{host_token}:{attempt}",
                    "city": city,
                    "region": CITIES[city]["region"],
                    "feature": feature,
                    "attempt": attempt,
                    "endpoint": endpoint,
                    "status": "failed",
                    "http_status": "",
                    "request_path": str(request_path.relative_to(REPO)),
                    "request_sha256": sha256_path(request_path),
                    "response_path": "",
                    "response_sha256": "",
                    "error_path": str(error_path.relative_to(REPO)),
                    "error_sha256": sha256_path(error_path),
                    "response_bytes": len(result.stdout),
                    "elapsed_seconds": elapsed,
                    "failure_reason": error_text.strip(),
                    "retrieved_utc": utc_now(),
                    "bbox": bbox,
                    "query_part": part,
                }
            )
    return records


def materialize(
    city: str,
    feature: str,
    box: Mapping[str, Any],
    runs: Iterable[Mapping[str, Any]],
    output: Path,
) -> list[dict[str, Any]]:
    elements: dict[tuple[str, int], tuple[dict[str, Any], Mapping[str, Any]]] = {}
    ordered_runs = sorted(runs, key=lambda row: str(row.get("query_part", "all")))
    for run in ordered_runs:
        response = REPO / str(run["response_path"])
        payload = json.loads(response.read_text(encoding="utf-8"))
        for element in payload.get("elements", []):
            tags = element.get("tags") or {}
            key = (str(element.get("type", "")), int(element.get("id", -1)))
            if key[0] and key[1] >= 0 and element_match(feature, tags):
                elements.setdefault(key, (element, run))
    rows: list[dict[str, Any]] = []
    for (osm_type, osm_id), (element, run) in sorted(elements.items()):
        tags = element.get("tags") or {}
        coords = legacy.point_from_element(element)
        row: dict[str, Any] = {
            "city": city,
            "region": CITIES[city]["region"],
            "feature": feature,
            "osm_type": osm_type,
            "osm_id": osm_id,
            "latitude": "" if coords is None else coords[0],
            "longitude": "" if coords is None else coords[1],
            "coordinate_status": "missing" if coords is None else "center_or_node",
            "name": tags.get("name", ""),
            "brand": tags.get("brand", ""),
            "tags": json.dumps(tags, ensure_ascii=False, sort_keys=True),
            "source_response_path": run["response_path"],
            "source_response_sha256": run["response_sha256"],
            "source_query_bbox": run["bbox"],
            "positive_power_tag": "",
            "positive_capacity_tag": "",
            "socket_tag_present": "",
            "power_tags_json": "{}",
            "capacity_tags_json": "{}",
            "socket_tags_json": "{}",
        }
        if feature == "charging_station":
            row.update(legacy.parameter_tags(tags))
        rows.append(row)
    write_csv(output / "pools" / f"{city}__{feature}.csv", rows, POOL_FIELDS)
    return rows


def hash_tree(output: Path) -> None:
    files: dict[str, str] = {}
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.name == "artifact_hashes.json" or path.name.startswith("._"):
            continue
        files[str(path.relative_to(REPO))] = sha256_path(path)
    write_json(
        output / "artifact_hashes.json",
        {
            "schema": "resetp.china9-metro-pool.artifact-hashes.v1",
            "hash_algorithm": "SHA-256",
            "excluded_self": "artifact_hashes.json",
            "files": files,
            "collector": {
                str(Path(__file__).relative_to(REPO)): sha256_path(Path(__file__)),
                str(LEGACY_SCRIPT.relative_to(REPO)): sha256_path(LEGACY_SCRIPT),
            },
        },
    )


def run(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    removed_start = clean_appledouble(output)
    boxes = metro_boxes()
    write_json(output / "query_boxes.json", boxes)
    write_csv(
        output / "city_query_boxes.csv",
        boxes.values(),
        [
            "city",
            "region",
            "name_zh",
            "centre_latitude",
            "centre_longitude",
            "south",
            "west",
            "north",
            "east",
            "height_km",
            "width_km",
            "old_bbox",
            "rule",
        ],
    )
    write_json(output / "logistics_tag_contract.json", LOGISTICS_EXACT_TAG_SET)
    existing = read_csv(output / "raw_runs.csv")
    runs: list[dict[str, Any]] = [
        row for row in existing if row.get("feature") in FEATURES
    ]
    for row in runs:
        row["query_part"] = row.get("query_part") or "all"
    successful_parts = {
        (row["city"], row["feature"], row["query_part"])
        for row in runs
        if row.get("status") == "success" and (REPO / row["response_path"]).is_file()
    }
    for city in sorted(CITIES):
        for feature in FEATURES:
            pending_parts = list(planned_parts(city, feature, runs))
            while pending_parts:
                part = pending_parts.pop(0)
                if (city, feature, part) in successful_parts:
                    continue
                request_box = tile_box(boxes[city], part)
                new_records = fetch_one(
                    city,
                    feature,
                    request_box,
                    output,
                    args.timeout,
                    args.retries,
                    part,
                )
                runs.extend(new_records)
                write_csv(output / "raw_runs.csv", runs, RUN_FIELDS)
                if new_records and new_records[-1]["status"] == "success":
                    successful_parts.add((city, feature, part))
                else:
                    if feature in {"named_poi", "logistics_candidate"}:
                        children = (
                            TILE_PARTS
                            if feature == "named_poi" and part == "all"
                            else tuple(
                                (
                                    f"{part}_{quadrant}"
                                    if feature == "named_poi"
                                    else f"{part}__{quadrant}"
                                )
                                for quadrant in ("sw", "se", "nw", "ne")
                            )
                        )
                        pending_parts[0:0] = list(children)
                        continue
                    completed_features = sum(
                        all((c, f, p) in successful_parts for p in planned_parts(c, f, runs))
                        for c in CITIES
                        for f in FEATURES
                    )
                    write_json(
                        output / "step2_status.json",
                        {
                            "step": 2,
                            "status": "HALT_INCOMPLETE_OVERPASS_EXTRACTION",
                            "failed_city": city,
                            "failed_feature": feature,
                            "failed_query_part": part,
                            "completed_city_features": completed_features,
                            "target_city_features": len(CITIES) * len(FEATURES),
                            "generated_utc": utc_now(),
                        },
                    )
                    clean_appledouble(output)
                    hash_tree(output)
                    return 2

    pool_rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
    count_rows: list[dict[str, Any]] = []
    for city in sorted(CITIES):
        for feature in FEATURES:
            expected_parts = planned_parts(city, feature, runs)
            feature_runs = [
                row
                for row in runs
                if row["city"] == city
                and row["feature"] == feature
                and row.get("status") == "success"
                and row.get("query_part", "all") in expected_parts
            ]
            rows = materialize(city, feature, boxes[city], feature_runs, output)
            pool_rows[(city, feature)] = rows
            response_paths = [str(row["response_path"]) for row in feature_runs]
            response_hashes = [str(row["response_sha256"]) for row in feature_runs]
            count_rows.append(
                {
                    "city": city,
                    "region": CITIES[city]["region"],
                    "feature": feature,
                    "record_count": len(rows),
                    "coordinate_missing_count": sum(
                        row["coordinate_status"] == "missing" for row in rows
                    ),
                    "response_path": json.dumps(response_paths, ensure_ascii=False),
                    "response_sha256": json.dumps(response_hashes),
                    "query_bbox": json.dumps(
                        [
                            boxes[city]["south"],
                            boxes[city]["west"],
                            boxes[city]["north"],
                            boxes[city]["east"],
                        ]
                    ),
                }
            )
    write_csv(
        output / "city_counts.csv",
        count_rows,
        [
            "city",
            "region",
            "feature",
            "record_count",
            "coordinate_missing_count",
            "response_path",
            "response_sha256",
            "query_bbox",
        ],
    )
    write_json(
        output / "metadata.json",
        {
            "schema": "resetp.china9-metro-pool.metadata.v1",
            "task": "nine-city metropolitan Overpass extraction",
            "generated_utc": utc_now(),
            "cities": CITIES,
            "features": FEATURES,
            "network_mode": "Overpass API via curl with TLS verification",
            "serial": True,
            "bbox_rule": "old box centre with city-specific metropolitan half-spans",
            "query_boxes": boxes,
            "logistics_tag_contract": LOGISTICS_EXACT_TAG_SET,
            "record_count_total": sum(len(rows) for rows in pool_rows.values()),
            "search_evaluations": 0,
            "old_suite_modified": False,
            "protected_files_modified": False,
        },
    )
    removed_final = clean_appledouble(output)
    write_json(
        output / "appledouble_cleanup.json",
        {
            "removed_at_start": removed_start,
            "removed_before_hash": removed_final,
            "scope": str(output.relative_to(REPO)),
        },
    )
    write_json(
        output / "step2_status.json",
        {
            "step": 2,
            "status": "PASS",
            "completed_city_features": len(CITIES) * len(FEATURES),
            "target_city_features": len(CITIES) * len(FEATURES),
            "successful_query_parts": len(successful_parts),
            "pool_record_count": sum(len(rows) for rows in pool_rows.values()),
            "generated_utc": utc_now(),
        },
    )
    hash_tree(output)
    clean_appledouble(output)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--retries", type=int, default=1)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
