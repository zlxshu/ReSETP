#!/usr/bin/env python3
"""Build the 81 source-bound China DRAFT instances.

This is a construction and audit tool, not an optimisation runner.  It uses
the already captured OSM Map API snapshots for real mapped places and the
public Goeke--Schneider files for customer attributes.  It deliberately fails
closed when a region cannot supply enough mapped features; it never invents a
coordinate or a demand/time-window value.

The output is a DRAFT set.  It is not authorised for E1--E7 search until the
human review gates recorded in the design document are passed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "solver" / "src"))

from setp_solver.search.bundle import load_search_bundle  # noqa: E402


SIZES = (10, 15, 20, 25, 50, 75, 100, 150, 200)
VARIANTS = (1, 2, 3)
SHIFT_SECONDS = (0.0, 8 * 3600.0, 16 * 3600.0)
SHIFT_LABELS = ("00-08", "08-16", "16-24")
HORIZON_SECONDS = 24 * 3600.0
OSM_ROOT = REPO / "data" / "ChinaInstances" / "c31_3x3_osm_map_api_grid_probe_20260717"
OSM_CATALOG = OSM_ROOT / "probe_catalog.json"
GOEKE_ROOT = REPO / "models" / "data_bundle" / "raw_instances" / "goeke_uk"
TVCI = REPO / "baselines" / "e4_e5" / "china_tvci_source_gate_20260717_v2" / "tvci_2025_48slot_wide.csv"
OUTPUT_ROOT = REPO / "data" / "ChinaInstances" / "CHINA81_DRAFT_20260717_source_bound"


class Halt(RuntimeError):
    """A data-contract failure that must not be repaired synthetically."""


REGIONS: dict[str, dict[str, Any]] = {
    "jjj": {
        "name_zh": "京津冀",
        "role": "华北城市群：北京、天津、石家庄",
        "carbon_column": "Beijing",
        "small": ("beijing",),
        "medium": ("beijing", "tianjin"),
        "large": ("beijing", "tianjin", "shijiazhuang"),
        "source_role": "交通运输部绿色货运配送示范城市与国家物流枢纽相关城市的 OSM 地点快照",
    },
    "prd": {
        "name_zh": "珠三角",
        "role": "粤港澳大湾区内地城市群：深圳、东莞、广州、佛山",
        "carbon_column": "Guangdong",
        "small": ("shenzhen",),
        "medium": ("shenzhen", "dongguan"),
        "large": ("shenzhen", "guangzhou", "foshan"),
        "source_role": "交通运输部绿色货运配送示范城市与国家物流枢纽相关城市的 OSM 地点快照",
    },
    "cy": {
        "name_zh": "成渝",
        "role": "成渝城市群：成都、重庆",
        "carbon_column": "Chongqing",
        "small": ("chengdu",),
        "medium": ("chengdu", "chongqing"),
        "large": ("chengdu", "chongqing"),
        "source_role": "交通运输部绿色货运配送示范城市与国家物流枢纽相关城市的 OSM 地点快照",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def relative(path: Path) -> str:
    return str(path.relative_to(REPO))


def source_anchor(record: dict[str, Any]) -> str:
    logical = record.get("logical_anchor")
    if logical:
        return str(logical)
    return str(record["anchor"]).rsplit("_", 1)[-1]


def load_osm_catalog() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not OSM_CATALOG.exists():
        raise Halt(f"missing existing OSM catalog: {relative(OSM_CATALOG)}")
    catalog = json.loads(OSM_CATALOG.read_text(encoding="utf-8"))
    records = catalog.get("records")
    if not isinstance(records, list) or not records:
        raise Halt("OSM catalog has no records")
    successful = [row for row in records if row.get("status") == "success"]
    if not successful:
        raise Halt("OSM catalog has no successful snapshots")
    return catalog, records


def point(element: dict[str, Any]) -> tuple[float, float] | None:
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center")
    if isinstance(center, dict) and "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def load_osm_pools(records: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Load and de-duplicate the retained derived OSM responses."""

    pools: dict[str, list[dict[str, Any]]] = {"poi": [], "depot": [], "station": []}
    seen: set[tuple[str, str, int]] = set()
    for record in records:
        feature = str(record.get("feature", ""))
        if feature not in pools or record.get("status") != "success":
            continue
        response = REPO / str(record["response_path"])
        if not response.exists():
            raise Halt(f"catalog response is missing: {relative(response)}")
        payload = json.loads(response.read_text(encoding="utf-8"))
        elements = payload.get("elements", [])
        if not isinstance(elements, list):
            raise Halt(f"invalid OSM element list: {relative(response)}")
        anchor = source_anchor(record)
        for element in elements:
            coords = point(element)
            if coords is None:
                continue
            osm_type = str(element.get("type", ""))
            if not osm_type or "id" not in element:
                continue
            osm_id = int(element["id"])
            key = (feature, osm_type, osm_id)
            if key in seen:
                continue
            seen.add(key)
            pools[feature].append(
                {
                    "source_anchor": anchor,
                    "osm_type": osm_type,
                    "osm_id": osm_id,
                    "latitude": coords[0],
                    "longitude": coords[1],
                    "tags": element.get("tags", {}),
                    "source_response_path": str(record["response_path"]),
                    "source_response_sha256": str(record["response_sha256"]),
                    "source_download_path": str(record.get("source_download_path", "")),
                    "source_download_sha256": str(record.get("source_download_sha256", "")),
                }
            )
    return pools


def named_poi(item: dict[str, Any]) -> bool:
    tags = item.get("tags", {})
    return bool(tags.get("name") or tags.get("brand"))


def source_anchors_for(region: str, size: int) -> tuple[str, ...]:
    spec = REGIONS[region]
    if size <= 25:
        return tuple(spec["small"])
    if size <= 100:
        return tuple(spec["medium"])
    return tuple(spec["large"])


def depot_count(size: int) -> int:
    if size <= 25:
        return 1
    if size <= 100:
        return 2
    return 3


def seed_for(region: str, size: int, variant: int) -> int:
    region_code = {"jjj": 11, "prd": 22, "cy": 33}[region]
    return 202607170000 + region_code * 100000 + size * 10 + variant


def customer_quotas(region: str, size: int, anchors: tuple[str, ...]) -> dict[str, int]:
    """Fixed city allocation; values are not tuned after seeing a solution."""

    if size <= 25:
        return {anchors[0]: size}
    if size <= 100:
        second = int(round(size * 0.20))
        return {anchors[0]: size - second, anchors[1]: second}
    if region == "jjj":
        shijiazhuang = 15 if size == 150 else 20
        tianjin = int(round(size * 0.25))
        return {"beijing": size - tianjin - shijiazhuang, "tianjin": tianjin, "shijiazhuang": shijiazhuang}
    if region == "prd":
        shenzhen = int(round(size * 0.40))
        guangzhou = int(round(size * 0.35))
        return {"shenzhen": shenzhen, "guangzhou": guangzhou, "foshan": size - shenzhen - guangzhou}
    chengdu = int(round(size * 0.70))
    return {"chengdu": chengdu, "chongqing": size - chengdu}


def sample_real(items: list[dict[str, Any]], count: int, seed: int, label: str) -> list[dict[str, Any]]:
    if len(items) < count:
        raise Halt(f"{label}: {len(items)} real mapped features available; {count} required")
    order = np.random.default_rng(seed).permutation(len(items))[:count]
    return [items[int(index)] for index in order]


def choose_customers(pools: dict[str, list[dict[str, Any]]], region: str, size: int, variant: int, used: set[tuple[str, int]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    anchors = source_anchors_for(region, size)
    quotas = customer_quotas(region, size, anchors)
    selected: list[dict[str, Any]] = []
    for index, (anchor, quota) in enumerate(quotas.items()):
        candidates = [
            item
            for item in pools["poi"]
            if item["source_anchor"] == anchor and named_poi(item) and (item["osm_type"], item["osm_id"]) not in used
        ]
        chosen = sample_real(candidates, quota, seed_for(region, size, variant) + index * 1009, f"{region}/{size}/{variant} customer pool {anchor}")
        selected.extend(chosen)
    if len(selected) != size:
        raise Halt(f"customer quota total mismatch for {region}/{size}/{variant}")
    return selected, quotas


def local_xy(items: list[dict[str, Any]]) -> dict[tuple[str, int], tuple[float, float]]:
    if not items:
        raise Halt("cannot project an empty geographic node set")
    lat0 = sum(float(item["latitude"]) for item in items) / len(items)
    lon0 = sum(float(item["longitude"]) for item in items) / len(items)
    meters_lon = 111_320.0 * math.cos(math.radians(lat0))
    return {
        (str(item["osm_type"]), int(item["osm_id"])): (
            (float(item["longitude"]) - lon0) * meters_lon,
            (float(item["latitude"]) - lat0) * 110_574.0,
        )
        for item in items
    }


def choose_depots(pools: dict[str, list[dict[str, Any]]], anchors: tuple[str, ...], count: int, seed: int) -> list[dict[str, Any]]:
    candidates = [item for item in pools["depot"] if item["source_anchor"] in anchors]
    if len(candidates) < count:
        raise Halt(f"depot pool {anchors}: {len(candidates)} real industrial candidates; {count} required")
    selected: list[dict[str, Any]] = []
    # Keep the multi-city footprint visible whenever the source has fewer city
    # anchors than the requested depot count, then spread remaining depots.
    for anchor in anchors:
        if len(selected) >= count:
            break
        options = [item for item in candidates if item["source_anchor"] == anchor]
        if not options:
            raise Halt(f"no industrial candidate for required city anchor {anchor}")
        selected.append(options[int(np.random.default_rng(seed + len(selected)).integers(len(options)))])
    xy = local_xy(candidates)
    while len(selected) < count:
        available = [item for item in candidates if item not in selected]
        selected.append(
            max(
                available,
                key=lambda item: min(
                    math.dist(xy[(item["osm_type"], item["osm_id"])], xy[(chosen["osm_type"], chosen["osm_id"])])
                    for chosen in selected
                ),
            )
        )
    return selected


def choose_stations(pools: dict[str, list[dict[str, Any]]], anchors: tuple[str, ...], count: int, seed: int, used: set[tuple[str, int]]) -> list[dict[str, Any]]:
    candidates = [
        item
        for item in pools["station"]
        if item["source_anchor"] in anchors and (item["osm_type"], item["osm_id"]) not in used
    ]
    if not candidates:
        raise Halt(f"public charging station pool {anchors}: no real mapped station available")
    take = min(3, len(candidates))
    return sample_real(candidates, take, seed, f"public station pool {anchors}")


def parse_goeke(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise Halt(f"missing Goeke source file: {relative(path)}")
    customers: list[dict[str, Any]] = []
    num_cv = num_ev = None
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        match_cv = re.search(r"m\s+numPetrolVeh\s*/\s*([0-9]+)\s*/", line)
        match_ev = re.search(r"m\s+numElectroVeh\s*/\s*([0-9]+)\s*/", line)
        if match_cv:
            num_cv = int(match_cv.group(1))
        if match_ev:
            num_ev = int(match_ev.group(1))
        parts = line.split()
        if len(parts) < 8 or parts[1] != "c":
            continue
        customers.append(
            {
                "source_row_number": line_number,
                "source_customer_id": parts[0],
                "x": float(parts[2]),
                "y": float(parts[3]),
                "demand": float(parts[4]),
                "ready_time": float(parts[5]),
                "due_time": float(parts[6]),
                "service_time": float(parts[7]),
            }
        )
    if num_cv is None or num_ev is None:
        raise Halt(f"Goeke fleet metadata missing in {relative(path)}")
    if not customers:
        raise Halt(f"Goeke source has no customers: {relative(path)}")
    return {"customers": customers, "num_cv": num_cv, "num_ev": num_ev}


def transform_orders(source: dict[str, Any], locations: list[dict[str, Any]], size: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(source["customers"]) != size:
        raise Halt(f"Goeke source customer count mismatch: {len(source['customers'])} != {size}")
    if len(locations) != size:
        raise Halt(f"location count mismatch: {len(locations)} != {size}")
    rows: list[dict[str, Any]] = []
    mapping: list[dict[str, Any]] = []
    # Round-robin assignment keeps each of the three 8-hour blocks populated
    # without sorting away the source variant's customer identity.
    for index, (source_row, location) in enumerate(zip(source["customers"], locations)):
        shift_index = index % 3
        scale = 8.0 / 9.0
        ready = SHIFT_SECONDS[shift_index] + source_row["ready_time"] * scale
        due = SHIFT_SECONDS[shift_index] + source_row["due_time"] * scale
        row = {
            "node_id": f"C{index + 1:03d}",
            "node_type": "c",
            "demand": source_row["demand"],
            "ready_time": round(ready, 6),
            "due_time": round(due, 6),
            "service_time": source_row["service_time"],
            "shift_index": shift_index,
            "shift_label": SHIFT_LABELS[shift_index],
            "source_customer_id": source_row["source_customer_id"],
            "source_row_number": source_row["source_row_number"],
            **location,
        }
        rows.append(row)
        mapping.append(
            {
                "new_node_id": row["node_id"],
                "source_customer_id": source_row["source_customer_id"],
                "source_row_number": source_row["source_row_number"],
                "source_demand": source_row["demand"],
                "source_ready_time_9h": source_row["ready_time"],
                "source_due_time_9h": source_row["due_time"],
                "source_service_time": source_row["service_time"],
                "shift_index": shift_index,
                "shift_label": SHIFT_LABELS[shift_index],
                "derived_ready_time_8h": row["ready_time"],
                "derived_due_time_8h": row["due_time"],
                "osm_type": location["osm_type"],
                "osm_id": location["osm_id"],
                "osm_source_anchor": location["source_anchor"],
                "osm_name": location.get("tags", {}).get("name", ""),
            }
        )
    return rows, mapping


def numeric_kw(tags: dict[str, Any]) -> tuple[float, str]:
    for key in ("max_power", "output", "capacity"):
        value = str(tags.get(key, "")).strip().lower()
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:kw)?", value)
        if match and float(match.group(1)) > 0 and ("kw" in value or key != "capacity"):
            return float(match.group(1)), f"OSM tag {key}"
    return 60.0, "derived DRAFT default=60 kW; no positive OSM power tag"


def station_capacity(tags: dict[str, Any]) -> tuple[int, str]:
    value = str(tags.get("capacity", "")).strip()
    if value.isdigit() and int(value) > 0:
        return int(value), "OSM capacity tag"
    return 1, "derived DRAFT default=1; no positive OSM capacity tag"


def carbon_rows(column: str) -> list[dict[str, Any]]:
    if not TVCI.exists():
        raise Halt(f"missing local TVCI source: {relative(TVCI)}")
    with TVCI.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("date") == "2025-01-01"]
    if len(rows) != 48 or any(column not in row for row in rows):
        raise Halt(f"TVCI source must contain 48 rows and column {column}: {relative(TVCI)}")
    return rows


def all_hashes(root: Path) -> dict[str, str]:
    excluded = {"artifact_hashes.json"}
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in excluded or path.name.startswith("._"):
            continue
        if "__pycache__" in path.parts or ".pytest_cache" in path.parts:
            continue
        result[str(path.relative_to(root))] = sha256(path)
    return result


def node_public(node: dict[str, Any]) -> dict[str, Any]:
    hidden = {
        "tags",
        "source_response_path",
        "source_response_sha256",
        "source_download_path",
        "source_download_sha256",
        "source_anchor",
        "osm_type",
        "osm_id",
        "latitude",
        "longitude",
        "source_customer_id",
        "source_row_number",
        "charger_count_provenance",
        "power_provenance",
    }
    return {key: value for key, value in node.items() if key not in hidden}


def write_bundle(
    *,
    region: str,
    size: int,
    variant: int,
    pools: dict[str, list[dict[str, Any]]],
    catalog: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    anchors = source_anchors_for(region, size)
    n_depots = depot_count(size)
    name = f"cn-{region}-{size}c-{n_depots}d-{variant:02d}-24h-DRAFT"
    out = OUTPUT_ROOT / name
    out.mkdir(parents=False, exist_ok=False)
    seed = seed_for(region, size, variant)
    used: set[tuple[str, int]] = set()
    customers, quotas = choose_customers(pools, region, size, variant, used)
    used.update((item["osm_type"], item["osm_id"]) for item in customers)
    depots = choose_depots(pools, anchors, n_depots, seed + 100003)
    used.update((item["osm_type"], item["osm_id"]) for item in depots)
    stations = choose_stations(pools, anchors, n_depots, seed + 200003, used)
    used.update((item["osm_type"], item["osm_id"]) for item in stations)
    geo_items = customers + depots + stations
    xy = local_xy(geo_items)
    goeke_path = GOEKE_ROOT / f"E-UK{size}_{variant:02d}.txt"
    source = parse_goeke(goeke_path)
    locations = sorted(customers, key=lambda item: (item["source_anchor"], item["osm_type"], item["osm_id"]))
    customer_rows, order_mapping = transform_orders(source, locations, size)
    source_cv, source_ev = int(source["num_cv"]), int(source["num_ev"])
    # The original source occasionally records zero EVs for a variant.  The
    # Chinese DRAFT contract requires a mixed-fleet slot; the one-vehicle
    # lower bound is therefore explicit and must be reviewed before freezing.
    num_cv, num_ev = max(1, source_cv), max(1, source_ev)
    depot_chargers = max(1, math.ceil(num_ev / n_depots))
    nodes: list[dict[str, Any]] = []
    for index, depot in enumerate(depots):
        x, y = xy[(depot["osm_type"], depot["osm_id"])]
        nodes.append(
            {
                "node_id": f"D{index}",
                "node_type": "d",
                "x": x,
                "y": y,
                "demand": 0.0,
                "ready_time": 0.0,
                "due_time": HORIZON_SECONDS,
                "service_time": 0.0,
                "station_chargers": depot_chargers,
                "charger_count_provenance": "derived ceil(num_ev/n_depots); DRAFT operational capacity, not observed depot charger count",
                "source_kind": "real_osm_landuse_industrial_candidate",
                **depot,
            }
        )
    for row in customer_rows:
        location_key = (row["osm_type"], row["osm_id"])
        x, y = xy[location_key]
        nodes.append({"node_id": row["node_id"], "node_type": "c", "x": x, "y": y, **{key: row[key] for key in ("demand", "ready_time", "due_time", "service_time")}, "source_kind": "real_osm_named_poi_with_goeke_attributes", **row})
    for index, station in enumerate(stations, start=1):
        x, y = xy[(station["osm_type"], station["osm_id"])]
        capacity, capacity_provenance = station_capacity(station.get("tags", {}))
        power, power_provenance = numeric_kw(station.get("tags", {}))
        nodes.append(
            {
                "node_id": f"F{index}",
                "node_type": "f",
                "x": x,
                "y": y,
                "demand": 0.0,
                "ready_time": 0.0,
                "due_time": HORIZON_SECONDS,
                "service_time": 0.0,
                "charge_power_kw": power,
                "station_chargers": capacity,
                "charger_count_provenance": capacity_provenance,
                "power_provenance": power_provenance,
                "source_kind": "real_osm_charging_station",
                **station,
            }
        )
    coords = np.asarray([(float(node["x"]), float(node["y"])) for node in nodes], dtype=float)
    # DRAFT only.  OSM locations are real, but this local metric is not a road
    # router.  The formal-freeze gate explicitly requires a road-distance
    # decision and an independent matrix audit.
    matrix = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=2) * 1.4
    np.fill_diagonal(matrix, 0.0)
    np.save(out / "distance_matrix.npy", matrix)
    node_fields = [
        "node_id", "node_type", "x", "y", "demand", "ready_time", "due_time", "service_time",
        "station_chargers", "charge_power_kw", "source_kind", "source_anchor", "osm_type", "osm_id",
        "latitude", "longitude", "tags", "source_customer_id", "source_row_number", "shift_index", "shift_label",
        "charger_count_provenance", "power_provenance",
    ]
    with (out / "nodes.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=node_fields, extrasaction="ignore")
        writer.writeheader()
        for node in nodes:
            row = dict(node)
            row["tags"] = json.dumps(row.get("tags", {}), ensure_ascii=False, sort_keys=True)
            writer.writerow(row)
    curve = carbon_rows(REGIONS[region]["carbon_column"])
    with (out / "carbon_profile.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = ["time_index", "datetime_utc", "actual_gco2_per_kwh", "forecast_gco2_per_kwh", "index_label", "index_code", "horizon_second_start"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, row in enumerate(curve, start=1):
            gco2 = float(row[REGIONS[region]["carbon_column"]]) * 1000.0
            hour, minute = int(row["hour_of_day"]), int(row["minute"])
            writer.writerow(
                {
                    "time_index": index,
                    "datetime_utc": f"2025-01-01T{hour:02d}:{minute:02d}:00+00:00",
                    "actual_gco2_per_kwh": f"{gco2:.6f}",
                    "forecast_gco2_per_kwh": f"{gco2:.6f}",
                    "index_label": f"S1-2025 projected {REGIONS[region]['carbon_column']}",
                    "index_code": index,
                    "horizon_second_start": (index - 1) * 1800,
                }
            )
    metadata = {
        "region": region,
        "region_name_zh": REGIONS[region]["name_zh"],
        "region_role": REGIONS[region]["role"],
        "source_city_anchors": anchors,
        "customer_sampling_quotas": quotas,
        "customer_count_target": size,
        "customer_count_actual": len(customer_rows),
        "n_depots": n_depots,
        "n_stations": len(stations),
        "num_cv": num_cv,
        "num_ev": num_ev,
        "source_fleet": {"num_cv": source_cv, "num_ev": source_ev, "policy": "source inherited; zero lower bound lifted to one only to keep the DRAFT mixed-fleet contract"},
        "depot_chargers": depot_chargers,
        "shift_contract": {"horizon_seconds": HORIZON_SECONDS, "blocks": list(SHIFT_LABELS), "assignment": "source customer order round-robin modulo three", "time_window_transform": "ready_final=shift_start+ready_source*8/9; due_final=shift_start+due_source*8/9; service unchanged"},
        "coordinate_provenance": {"status": "real_mapped_places", "source": "OpenStreetMap Map API snapshots retained locally", "license": "ODbL 1.0", "customer_rule": "named POI only (name or brand tag)", "depot_rule": "landuse=industrial mapped candidate; not automatically verified operating depot", "station_rule": "amenity=charging_station mapped candidate"},
        "distance_rule": "local WGS84 equirectangular projection then Euclidean distance times 1.4; DRAFT only, not road-routed",
        "order_attributes": {"status": "Goeke-Schneider public benchmark attributes mapped to real Chinese POIs; not observed Chinese orders", "source_file": relative(goeke_path), "source_file_sha256": sha256(goeke_path), "source_dataset_url": "https://data.mendeley.com/datasets/bd7rm5fw6k/1", "source_paper_doi": "10.1016/j.ejor.2015.01.049", "source_scale": size, "source_variant": f"{variant:02d}"},
        "carbon_curve": {"column": REGIONS[region]["carbon_column"], "source_file": relative(TVCI), "source_sha256": sha256(TVCI), "source_paper_doi": "10.1038/s41597-026-07272-6", "source_data_url": "https://doi.org/10.6084/m9.figshare.28953545", "data_nature": "peer-reviewed China provincial S1-2025 projected hourly factor repeated as 48 half-hour slots; not measured realtime data"},
        "charging": {"public_power_default_kw": 60.0, "public_power_default_status": "derived only when OSM has no positive power tag", "public_capacity_default": 1, "depot_capacity_policy": "ceil(num_ev/n_depots), derived DRAFT scenario parameter, not observed"},
        "search_evaluations": 0,
        "formal_experiment_authorized": False,
    }
    payload = {
        "schema": "resetp.china81.draft.v1",
        "draft_only": True,
        "formal_experiment_authorized": False,
        "instance_id": name,
        "demand_unit": "kg",
        "distance_unit": "meter",
        "nodes": [node_public(node) for node in nodes],
        "metadata": metadata,
    }
    write_json(out / "instance.json", payload)
    source_rows = []
    for node in nodes:
        source_rows.append({key: node.get(key, "") for key in ("node_id", "node_type", "source_kind", "source_anchor", "osm_type", "osm_id", "latitude", "longitude", "source_response_path", "source_response_sha256", "source_download_path", "source_download_sha256", "source_customer_id", "source_row_number", "shift_index", "shift_label", "charger_count_provenance", "power_provenance")})
    selected_records = [record for record in records if source_anchor(record) in anchors]
    source_manifest = {
        "schema": "resetp.china81.source-bound.v1",
        "draft_only": True,
        "instance_id": name,
        "selection_seed": seed,
        "selection_rule": "deterministic NumPy PCG64 permutation of real named OSM features within fixed city quotas",
        "source_catalog": relative(OSM_CATALOG),
        "source_catalog_sha256": sha256(OSM_CATALOG),
        "source_license": catalog.get("source_license", "Open Database License (ODbL)"),
        "source_requests": selected_records,
        "node_source_rows": source_rows,
        "goeke_order_mapping": order_mapping,
        "goeke_fleet": {"num_cv": source_cv, "num_ev": source_ev},
        "output_file_hashes": {},
    }
    write_json(out / "source_manifest.json", source_manifest)
    result = validate_bundle(out, size, n_depots, len(stations), source_cv, source_ev)
    source_manifest["output_file_hashes"] = {
        path.name: sha256(path)
        for path in sorted(out.iterdir())
        if path.is_file() and path.name not in {"source_manifest.json"} and not path.name.startswith("._")
    }
    write_json(out / "source_manifest.json", source_manifest)
    return result


def validate_bundle(bundle: Path, size: int, n_depots: int, n_stations: int, source_cv: int, source_ev: int) -> dict[str, Any]:
    data = json.loads((bundle / "instance.json").read_text(encoding="utf-8"))
    nodes = data["nodes"]
    customers = [row for row in nodes if row["node_type"] == "c"]
    depots = [row for row in nodes if row["node_type"] == "d"]
    stations = [row for row in nodes if row["node_type"] == "f"]
    errors: list[str] = []
    if len(customers) != size:
        errors.append(f"customer_count={len(customers)} != {size}")
    if len(depots) != n_depots:
        errors.append(f"depot_count={len(depots)} != {n_depots}")
    if len(stations) != n_stations or not stations:
        errors.append("public charging station count invalid")
    if any(float(row["ready_time"]) < 0 or float(row["ready_time"]) >= float(row["due_time"]) or float(row["due_time"]) > HORIZON_SECONDS for row in customers):
        errors.append("customer time window outside 24h horizon")
    if any(float(row["service_time"]) <= 0 or float(row["service_time"]) > float(row["due_time"]) - float(row["ready_time"]) for row in customers):
        errors.append("customer service time exceeds transformed window")
    shift_counts = Counter(str(row.get("shift_label", "")) for row in customers)
    if any(shift_counts[label] == 0 for label in SHIFT_LABELS):
        errors.append(f"empty shift block: {dict(shift_counts)}")
    node_ids = [row["node_id"] for row in nodes]
    if len(node_ids) != len(set(node_ids)):
        errors.append("duplicate node ids")
    matrix = np.load(bundle / "distance_matrix.npy")
    if matrix.shape != (len(nodes), len(nodes)) or not np.allclose(matrix, matrix.T) or not np.allclose(np.diag(matrix), 0.0) or np.any(matrix < 0):
        errors.append("distance matrix structure invalid")
    loaded = load_search_bundle(bundle)
    if len(loaded.instance.nodes) != len(nodes) or len(loaded.carbon_profile) != 48:
        errors.append("solver search bundle round-trip failed")
    with (bundle / "nodes.csv").open(encoding="utf-8", newline="") as handle:
        if len(list(csv.DictReader(handle))) != len(nodes):
            errors.append("nodes.csv row count mismatch")
    result = {"instance_id": bundle.name, "bundle": relative(bundle), "pass": not errors, "errors": errors, "customers": len(customers), "depots": len(depots), "stations": len(stations), "nodes": len(nodes), "carbon_rows": len(loaded.carbon_profile), "source_num_cv": source_cv, "source_num_ev": source_ev, "search_evaluations": 0, "status": "DRAFT_STRUCTURAL_ONLY"}
    write_json(bundle / "structure_gate.json", result)
    if errors:
        raise Halt(f"{bundle.name}: {'; '.join(errors)}")
    return result


def write_records(results: list[dict[str, Any]], catalog: dict[str, Any], records: list[dict[str, Any]], failures: list[str]) -> None:
    summary_path = OUTPUT_ROOT / "instance_catalog.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        fields = ["instance_id", "region", "customer_count", "depot_count", "station_count", "source_num_cv", "source_num_ev", "search_evaluations", "status", "pass"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in results:
            match = re.match(r"cn-([a-z]+)-(\d+)c-(\d+)d-(\d+)-24h-DRAFT", result["instance_id"])
            writer.writerow({"instance_id": result["instance_id"], "region": match.group(1) if match else "", "customer_count": result["customers"], "depot_count": result["depots"], "station_count": result["stations"], "source_num_cv": result["source_num_cv"], "source_num_ev": result["source_num_ev"], "search_evaluations": 0, "status": result["status"], "pass": result["pass"]})
    metadata = {
        "schema": "resetp.china81.build-metadata.v1",
        "created_utc": datetime.now(UTC).isoformat(),
        "target_instances": 81,
        "built_instances": len(results),
        "regions": list(REGIONS),
        "sizes": list(SIZES),
        "variants": list(VARIANTS),
        "osm_catalog": relative(OSM_CATALOG),
        "goeke_root": relative(GOEKE_ROOT),
        "tvci_source": relative(TVCI),
        "search_evaluations": 0,
        "formal_experiment_authorized": False,
        "failures": failures,
    }
    write_json(OUTPUT_ROOT / "metadata.json", metadata)
    with (OUTPUT_ROOT / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = ["instance_id", "stage", "search_evaluations", "run_status", "note"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in results:
            writer.writerow({"instance_id": result["instance_id"], "stage": "construction", "search_evaluations": 0, "run_status": "NOT_RUN", "note": "DRAFT structural construction only"})
    decision = {
        "schema": "resetp.china81.decision.v1",
        "decision": "DRAFT_SET_BUILT_NOT_AUTHORIZED_FOR_SEARCH" if len(results) == 81 and not failures else "HALT_INCOMPLETE_DRAFT_SET",
        "target_count": 81,
        "pass_count": sum(bool(result["pass"]) for result in results),
        "search_evaluations": 0,
        "formal_search_allowed": False,
        "blocking_items": [
            "customer demand/time windows are benchmark-derived, not observed Chinese orders",
            "industrial candidates are not manually verified operating depots",
            "some station capacity/power values are derived defaults",
            "distance matrix is not road-routed",
            "source variant with zero EV uses an explicit one-EV mixed-fleet lower bound",
            "human review and NL/core contract freeze remain outstanding",
        ],
    }
    write_json(OUTPUT_ROOT / "decision.json", decision)
    report = render_report(results, catalog, records, failures)
    (OUTPUT_ROOT / "report.md").write_text(report, encoding="utf-8")
    manifest = {
        "schema": "resetp.china81.build-manifest.v1",
        "draft_only": True,
        "formal_experiment_authorized": False,
        "target_instances": 81,
        "results": results,
        "failures": failures,
        "search_evaluations": 0,
        "report": relative(OUTPUT_ROOT / "report.md"),
    }
    write_json(OUTPUT_ROOT / "build_manifest.json", manifest)
    write_json(OUTPUT_ROOT / "artifact_hashes.json", {"schema": "resetp.artifact-hashes.v1", "excluded_self": True, "files": all_hashes(OUTPUT_ROOT)})


def render_report(results: list[dict[str, Any]], catalog: dict[str, Any], records: list[dict[str, Any]], failures: list[str]) -> str:
    success = [row for row in records if row.get("status") == "success"]
    lines = [
        "# 中国三区域 9 梯度 × 3 变体 DRAFT 算例构造报告（2026-07-17）",
        "",
        "状态：**DRAFT only；81 个目录构造与结构回读，不含任何优化搜索，不得直接作为论文正式结果。**",
        "",
        "## 结论",
        "",
        f"目标 81 个，已构造 {len(results)} 个，结构门通过 {sum(bool(row['pass']) for row in results)} 个；搜索评价次数为 0。每个区域覆盖 10、15、20、25、50、75、100、150、200 客户，每个梯度有 01/02/03 三个变体。25 客户及以下为 1 个车场，50--100 为 2 个车场，150--200 为 3 个车场；所有目录均包含三班 00--08/08--16/16--24、公共充电站和车场充电字段。",
        "",
        "## 数据真实性边界",
        "",
        "客户地点来自保留的 OpenStreetMap Map API 快照中的命名 POI（name 或 brand），车场来自 `landuse=industrial` 的实际地图要素候选，公共站来自 `amenity=charging_station` 的实际地图要素。它们是有坐标和 OSM 要素编号的真实地图标注，但不是政府经营主体名录，也不等于人工核验过的运营车场或订单客户。",
        "",
        "需求量、服务时长和时间窗逐客户继承 Goeke--Schneider 公开文件 `E-UK{N}_{01/02/03}.txt`；仅将原 9 小时基准窗按 8/9 缩放并放入三个 8 小时班次，客户数不删、不补、不按解截取。它们是公开基准属性的中国地理映射，不是中国真实订单。",
        "",
        "时变碳曲线使用仓库已验签的中国省级 S1-2025 48 槽文件；该文件对应 Li 等发表于 Scientific Data 的逐小时预测数据，不能写成中国实测实时碳强度。",
        "",
        "## 81 个算例",
        "",
        "| 实例 | 客户 | 车场 | 公共站 | Goeke车队 CV/EV | 结构门 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in results:
        lines.append(f"| `{row['instance_id']}` | {row['customers']} | {row['depots']} | {row['stations']} | {row['source_num_cv']}/{row['source_num_ev']} | {'PASS' if row['pass'] else 'FAIL'} |")
    lines += [
        "",
        "## 当前不能直接冻结的项目",
        "",
        "1. 距离矩阵目前是本地投影直线距离乘 1.4 的 DRAFT 口径，不是 OSM 路网最短路；正式冻结前必须完成路网距离决定和独立矩阵审计。",
        "2. OSM 工业用地只代表车场候选；正式论文若称物流园或运营车场，需要人工核验或政府/园区名录补证。",
        "3. OSM 中多数充电站没有正数容量或功率标签；没有来源的地方使用了明确标注的 1 桩、60 kW 派生默认，不能把它们写成观察值。",
        "4. 个别 Goeke 变体原始车队记录为 0 辆电动车。为保持中国 DRAFT 的混合车队结构，构造器只把该下界提升为 1，并在每个实例的 `metadata.json` 与总决策中标出，正式实验前仍需冻结这一口径。",
        "5. 这些限制不会被 `PASS` 结构门掩盖；`PASS` 只表示文件可读、客户数/车场数/站点/时间窗/碳曲线/矩阵结构一致。",
        "",
        "## 证据位置",
        "",
        f"- OSM 请求目录：`{relative(OSM_ROOT)}`；成功快照数 {len(success)}，原始 XML 和派生要素均保留。",
        f"- Goeke--Schneider 原始文件：`{relative(GOEKE_ROOT)}`。",
        f"- 中国 TVCI：`{relative(TVCI)}`。",
        f"- 本集总台账：`{relative(OUTPUT_ROOT / 'instance_catalog.csv')}`、`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`。",
    ]
    if failures:
        lines += ["", "## 构造失败", ""] + [f"- {failure}" for failure in failures]
    return "\n".join(lines) + "\n"


def build() -> dict[str, Any]:
    if OUTPUT_ROOT.exists():
        raise Halt(f"refusing to overwrite existing output: {relative(OUTPUT_ROOT)}")
    catalog, records = load_osm_catalog()
    pools = load_osm_pools(records)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=False)
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    try:
        for region in REGIONS:
            for size in SIZES:
                for variant in VARIANTS:
                    try:
                        results.append(write_bundle(region=region, size=size, variant=variant, pools=pools, catalog=catalog, records=records))
                    except Exception as exc:
                        failures.append(f"{region}/{size}/{variant:02d}: {type(exc).__name__}: {exc}")
        # The variant contract is a real source-sample contract, not merely a
        # filename contract.  Reject any exact duplicate location set within a
        # region/size triplet.
        for region in REGIONS:
            for size in SIZES:
                fingerprints = []
                for variant in VARIANTS:
                    bundle = OUTPUT_ROOT / f"cn-{region}-{size}c-{depot_count(size)}d-{variant:02d}-24h-DRAFT"
                    if not (bundle / "nodes.csv").exists():
                        continue
                    with (bundle / "nodes.csv").open(encoding="utf-8", newline="") as handle:
                        rows = csv.DictReader(handle)
                        fingerprints.append(tuple(sorted((row["node_type"], row["osm_type"], row["osm_id"]) for row in rows if row["node_type"] == "c")))
                if len(fingerprints) == 3 and len(set(fingerprints)) != 3:
                    failures.append(f"{region}/{size}: 01/02/03 customer location sets are not all different")
    finally:
        write_records(results, catalog, records, failures)
    if len(results) != 81 or failures:
        raise Halt(f"China 81 construction incomplete: {len(results)}/81 bundles; failures={len(failures)}")
    return {"complete": True, "bundles": len(results), "search_evaluations": 0, "output": relative(OUTPUT_ROOT)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="construct the 81 DRAFT bundles from existing local snapshots")
    args = parser.parse_args()
    if not args.build:
        parser.error("pass --build; no implicit construction side effect")
    result = build()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
