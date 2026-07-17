#!/usr/bin/env python3
"""Build one provenance-complete C31 Chengdu-metropolitan DRAFT-v2 candidate.

This is a data-construction script, not a solver runner.  It fetches only
small OpenStreetMap Map API snapshots, preserves every request and raw XML
response, and fails closed when the real feature pool cannot meet the stated
geographic or structural contract.  It never generates geographic points and
records ``search_evaluations=0`` in every decision surface.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "solver" / "src"))

from setp_solver.search.bundle import load_search_bundle  # noqa: E402


ENDPOINT = "https://api.openstreetmap.org/api/0.6/map"
USER_AGENT = "ReSETP-C31-data-probe/1.1 (academic reproducibility contact: zhouleixishu@openai.com)"
ROOT = REPO / "data" / "ChinaInstances" / "C31_DRAFT_20260717_osm_map_api_grid_v2"
SNAPSHOTS = ROOT / "osm_map_api_snapshots"
BUNDLE_NAME = "c31-cy-100c-01-DRAFT-v2"
TVCI = REPO / "baselines" / "e4_e5" / "china_tvci_source_gate_20260717_v2" / "tvci_2025_48slot_wide.csv"
REPORT_DOC = REPO / "docs" / "handoff" / "china_3x3_instance_probe_20260717.md"

# These are real, named cities/districts in the Chengdu metropolitan area.
# Fixed 0.03° cells per anchor stay inside the successfully used Map API
# request geometry.  The geographic footprint is an observed consequence of
# the selected OSM POIs, not a coordinate transformation or target fitting.
ANCHORS: dict[str, tuple[float, float, float, float]] = {
    "chengdu_qingyang": (30.60, 104.00, 30.66, 104.06),
    "deyang_jingyang": (31.10, 104.35, 31.19, 104.44),
    "meishan_dongpo": (30.02, 103.80, 30.08, 103.86),
    "ziyang_yanjiang": (30.10, 104.62, 30.16, 104.68),
    "leshan_shizhong": (29.53, 103.70, 29.62, 103.82),
}
# The allocation is non-uniform but fixed before the Jingyang snapshot is
# fetched.  It reduces Qingyang's dominance while retaining genuine southern
# and eastern metropolitan boundary POIs; it is not a coordinate transform.
CUSTOMER_QUOTAS = {
    "chengdu_qingyang": 55,
    "deyang_jingyang": 10,
    "meishan_dongpo": 17,
    "ziyang_yanjiang": 3,
    "leshan_shizhong": 15,
}
SEED = 3171002


class Halt(RuntimeError):
    """A data-contract failure that must not be repaired synthetically."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def tiles_for(bbox: tuple[float, float, float, float]) -> tuple[tuple[float, float, float, float], ...]:
    south, west, north, east = bbox
    rows, cols = round((north - south) / 0.03), round((east - west) / 0.03)
    if rows < 1 or cols < 1 or not math.isclose(south + rows * 0.03, north) or not math.isclose(west + cols * 0.03, east):
        raise ValueError(f"anchor must be an exact 0.03-degree static-cell grid, got {bbox}")
    return tuple((south + 0.03 * row, west + 0.03 * col, south + 0.03 * (row + 1), west + 0.03 * (col + 1)) for row in range(rows) for col in range(cols))


def extract_features(xml_path: Path) -> dict[str, list[dict[str, Any]]]:
    root = ET.fromstring(xml_path.read_bytes())
    coordinates: dict[str, tuple[float, float]] = {}
    poi: list[dict[str, Any]] = []
    station: list[dict[str, Any]] = []
    depot: list[dict[str, Any]] = []
    for element in root.findall("node"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in element.findall("tag")}
        lat, lon = float(element.attrib["lat"]), float(element.attrib["lon"])
        coordinates[element.attrib["id"]] = (lat, lon)
        row = {"type": "node", "id": int(element.attrib["id"]), "lat": lat, "lon": lon, "tags": tags}
        if "shop" in tags or tags.get("amenity") in {"restaurant", "cafe", "marketplace"} or "office" in tags:
            poi.append(row)
        if tags.get("amenity") == "charging_station":
            station.append(row)
    for element in root.findall("way"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in element.findall("tag")}
        if tags.get("landuse") != "industrial" and tags.get("amenity") != "charging_station":
            continue
        points = [coordinates[ref.attrib["ref"]] for ref in element.findall("nd") if ref.attrib["ref"] in coordinates]
        if not points:
            continue
        row = {
            "type": "way",
            "id": int(element.attrib["id"]),
            "center": {"lat": sum(lat for lat, _ in points) / len(points), "lon": sum(lon for _, lon in points) / len(points)},
            "tags": tags,
        }
        if tags.get("landuse") == "industrial":
            depot.append(row)
        if tags.get("amenity") == "charging_station":
            station.append(row)
    return {"poi": poi, "depot": depot, "station": station}


def fetch_tile(anchor: str, index: int, bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    queries, raw, derived = SNAPSHOTS / "queries", SNAPSHOTS / "raw", SNAPSHOTS / "derived"
    for directory in (queries, raw, derived):
        directory.mkdir(parents=True, exist_ok=True)
    stem = f"{anchor}_t{index}"
    south, west, north, east = bbox
    bbox_value = f"{west:.5f},{south:.5f},{east:.5f},{north:.5f}"
    request_path = queries / f"{stem}.request.txt"
    request_path.write_text(f"GET {ENDPOINT}?bbox={bbox_value}\n", encoding="utf-8")
    url = ENDPOINT + "?" + urllib.parse.urlencode({"bbox": bbox_value})
    base = {
        "anchor": stem,
        "logical_anchor": anchor,
        "endpoint": ENDPOINT,
        "request_url": url,
        "query_path": str(request_path.relative_to(REPO)),
        "query_sha256": sha256(request_path),
        "bbox": [south, west, north, east],
        "retrieved_utc": datetime.now(UTC).isoformat(),
    }
    raw_path = raw / f"{stem}.osm"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/xml"})
        with urllib.request.urlopen(request, timeout=90) as response:
            body, status = response.read(), int(response.status)
        raw_path.write_bytes(body)
        features = extract_features(raw_path)
        records: list[dict[str, Any]] = []
        for feature, elements in features.items():
            derived_path = derived / f"{stem}__{feature}.json"
            write_json(derived_path, {"elements": elements, "source_download_path": str(raw_path.relative_to(REPO)), "source_download_sha256": sha256(raw_path)})
            records.append(base | {"feature": feature, "status": "success", "http_status": status, "response_path": str(derived_path.relative_to(REPO)), "response_sha256": sha256(derived_path), "source_download_path": str(raw_path.relative_to(REPO)), "source_download_sha256": sha256(raw_path), "response_bytes": len(body), "element_count": len(elements), "osm_base_timestamp": "Map API snapshot; raw XML retained"})
        return records
    except Exception as exc:
        error_path = raw / f"{stem}.error.txt"
        error_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        return [base | {"feature": feature, "status": "failed", "http_status": getattr(exc, "code", None), "error_path": str(error_path.relative_to(REPO)), "error_sha256": sha256(error_path), "failure_reason": f"{type(exc).__name__}: {exc}"} for feature in ("poi", "depot", "station")]


def fetch_pending(max_requests: int, pause_seconds: float) -> dict[str, Any]:
    ROOT.mkdir(parents=True, exist_ok=True)
    catalog_path = SNAPSHOTS / "probe_catalog.json"
    records = json.loads(catalog_path.read_text(encoding="utf-8"))["records"] if catalog_path.exists() else []
    done = {row["anchor"] for row in records}
    count = 0
    for anchor, bbox in ANCHORS.items():
        for index, tile in enumerate(tiles_for(bbox)):
            stem = f"{anchor}_t{index}"
            if stem in done:
                continue
            records.extend(fetch_tile(anchor, index, tile))
            write_json(catalog_path, {"schema": "resetp.c31.osm-map-api.v2", "source_license": "Open Database License (ODbL)", "search_evaluations": 0, "records": records})
            count += 1
            if count >= max_requests:
                return {"complete": False, "requests_run": count, "tiles_recorded": len({row['anchor'] for row in records})}
            time.sleep(pause_seconds)
    return {"complete": True, "requests_run": count, "tiles_recorded": len({row['anchor'] for row in records})}


def point(element: dict[str, Any]) -> tuple[float, float] | None:
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center")
    if isinstance(center, dict) and "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def load_pool(records: list[dict[str, Any]], feature: str) -> list[dict[str, Any]]:
    seen: set[tuple[str, int]] = set()
    items: list[dict[str, Any]] = []
    for row in records:
        if row["feature"] != feature or row["status"] != "success":
            continue
        payload = json.loads((REPO / row["response_path"]).read_text(encoding="utf-8"))
        for element in payload["elements"]:
            coordinates = point(element)
            key = (str(element["type"]), int(element["id"]))
            if coordinates is None or key in seen:
                continue
            seen.add(key)
            items.append({"source_anchor": row["logical_anchor"], "osm_type": key[0], "osm_id": key[1], "latitude": coordinates[0], "longitude": coordinates[1], "tags": element.get("tags", {}), "source_response_sha256": row["response_sha256"]})
    return items


def local_xy(items: list[dict[str, Any]]) -> dict[tuple[str, int], tuple[float, float]]:
    lat0 = sum(item["latitude"] for item in items) / len(items)
    lon0 = sum(item["longitude"] for item in items) / len(items)
    meters_lon = 111_320.0 * math.cos(math.radians(lat0))
    return {(item["osm_type"], item["osm_id"]): ((item["longitude"] - lon0) * meters_lon, (item["latitude"] - lat0) * 110_574.0) for item in items}


def sample(items: list[dict[str, Any]], count: int, seed: int, label: str) -> list[dict[str, Any]]:
    if len(items) < count:
        raise Halt(f"{label}: {len(items)} genuine OSM features, need {count}; no synthetic substitute is permitted")
    return [items[int(index)] for index in np.random.default_rng(seed).permutation(len(items))[:count]]


def farthest(items: list[dict[str, Any]], count: int, xy: dict[tuple[str, int], tuple[float, float]], seed: int) -> list[dict[str, Any]]:
    if len(items) < count:
        raise Halt(f"industrial candidate pool: {len(items)} genuine OSM features, need {count}")
    selected = [items[int(np.random.default_rng(seed).integers(len(items)))]]
    while len(selected) < count:
        selected.append(max((item for item in items if item not in selected), key=lambda item: min(math.dist(xy[(item["osm_type"], item["osm_id"])], xy[(chosen["osm_type"], chosen["osm_id"])]) for chosen in selected)))
    return selected


def orders(count: int, seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    demand = np.clip(rng.normal(520.0, 240.0, size=count), 50.0, 2372.5).round(1)
    modes = rng.choice(("uniform", "tight", "clustered"), size=count, p=(0.45, 0.25, 0.30))
    ready, due, service = np.zeros(count), np.zeros(count), np.zeros(count)
    for index, mode in enumerate(modes):
        if mode == "tight":
            width, start, duration = rng.uniform(3600.0, 7200.0), 0.0, rng.uniform(180.0, 360.0)
            start = rng.uniform(0.0, 86400.0 - width)
        elif mode == "clustered":
            width, duration = rng.uniform(3600.0, 14040.0), rng.uniform(180.0, 1800.0)
            start = min(max(float(rng.choice((21600.0, 43200.0, 64800.0))) - width / 2.0 + rng.normal(0.0, 1260.0), 0.0), 86400.0 - width)
        else:
            width, duration = rng.uniform(3600.0, 21600.0), rng.uniform(180.0, 1800.0)
            start = rng.uniform(0.0, 86400.0 - width)
        ready[index], due[index], service[index] = round(start, 1), round(start + width, 1), round(min(duration, width), 1)
    return demand, ready, due, service


def carbon_rows() -> list[dict[str, str]]:
    with TVCI.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["date"] == "2025-01-01"]
    if len(rows) != 48:
        raise Halt(f"Chongqing TVCI must contain 48 2025-01-01 rows, found {len(rows)}")
    return rows


def coverage_km(customers: list[dict[str, Any]], xy: dict[tuple[str, int], tuple[float, float]]) -> float:
    coords = [xy[(item["osm_type"], item["osm_id"])] for item in customers]
    center = (sum(x for x, _ in coords) / len(coords), sum(y for _, y in coords) / len(coords))
    return max(math.dist(point, center) for point in coords) / 1000.0


def write_hashes() -> dict[str, str]:
    excluded = {"artifact_hashes.json"}
    return {str(path.relative_to(ROOT)): sha256(path) for path in sorted(ROOT.rglob("*")) if path.is_file() and path.name not in excluded and not path.name.startswith("._") and "__pycache__" not in path.parts and ".pytest_cache" not in path.parts}


def remove_appledouble() -> int:
    """Remove external-volume sidecars before the final content-hash audit."""
    sidecars = [path for path in ROOT.rglob("._*") if path.is_file()]
    for path in sidecars:
        path.unlink()
    return len(sidecars)


def build() -> dict[str, Any]:
    catalog_path = SNAPSHOTS / "probe_catalog.json"
    if not catalog_path.exists():
        raise Halt("no static Map API catalog exists; fetch snapshots first")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = catalog["records"]
    expected_tiles = {f"{anchor}_t{index}" for anchor, bbox in ANCHORS.items() for index, _ in enumerate(tiles_for(bbox))}
    active_records = [row for row in records if row["logical_anchor"] in ANCHORS]
    active_failed = [row for row in active_records if row["status"] == "failed"]
    active_tiles = {row["anchor"] for row in active_records}
    if active_failed or not expected_tiles.issubset(active_tiles):
        raise Halt(f"Map API catalog incomplete for current selected pool: tiles={len(active_tiles)}/{len(expected_tiles)}, failed_records={len(active_failed)}")
    bundle = ROOT / BUNDLE_NAME
    if bundle.exists():
        raise Halt(f"refusing to overwrite existing candidate {bundle}")
    pools = {feature: load_pool(active_records, feature) for feature in ("poi", "depot", "station")}
    if set(CUSTOMER_QUOTAS) != set(ANCHORS) or sum(CUSTOMER_QUOTAS.values()) != 100:
        raise Halt("configured customer quotas must cover exactly the selected blocks and sum to 100")
    customers: list[dict[str, Any]] = []
    for index, anchor in enumerate(ANCHORS):
        customers.extend(sample([item for item in pools["poi"] if item["source_anchor"] == anchor], CUSTOMER_QUOTAS[anchor], SEED + index, f"{anchor} POI pool"))
    all_geo = customers + pools["depot"] + pools["station"]
    xy = local_xy(all_geo)
    radius = coverage_km(customers, xy)
    if not 80.0 <= radius <= 150.0:
        raise Halt(f"real-POI coverage radius {radius:.3f} km is outside the pre-registered 80--150 km interval")
    depots = farthest(pools["depot"], 2, xy, SEED + 10)
    stations = sample(pools["station"], 3, SEED + 11, "charging-station pool")
    demand, ready, due, service = orders(100, SEED)
    bundle.mkdir(parents=True, exist_ok=False)
    nodes: list[dict[str, Any]] = []
    for index, item in enumerate(depots):
        x, y = xy[(item["osm_type"], item["osm_id"])]
        nodes.append({"node_id": f"D{index}", "node_type": "d", "x": x, "y": y, "demand": 0.0, "ready_time": 0.0, "due_time": 86400.0, "service_time": 0.0, "station_chargers": 100, "source_kind": "real_osm_industrial_candidate", **item})
    for index, item in enumerate(customers, 1):
        x, y = xy[(item["osm_type"], item["osm_id"])]
        nodes.append({"node_id": f"C{index:03d}", "node_type": "c", "x": x, "y": y, "demand": float(demand[index - 1]), "ready_time": float(ready[index - 1]), "due_time": float(due[index - 1]), "service_time": float(service[index - 1]), "source_kind": "real_osm_poi_with_derived_order_attributes", **item})
    for index, item in enumerate(stations, 1):
        x, y = xy[(item["osm_type"], item["osm_id"])]
        raw_capacity = str(item["tags"].get("capacity", "")).strip()
        chargers = int(raw_capacity) if raw_capacity.isdigit() and int(raw_capacity) > 0 else 1
        nodes.append({"node_id": f"F{index}", "node_type": "f", "x": x, "y": y, "demand": 0.0, "ready_time": 0.0, "due_time": 86400.0, "service_time": 0.0, "charge_power_kw": 60.0, "station_chargers": chargers, "charger_count_provenance": "OSM capacity tag" if raw_capacity.isdigit() and int(raw_capacity) > 0 else "derived default=1 because OSM has no positive numeric capacity", "source_kind": "real_osm_charging_station", **item})
    matrix = np.linalg.norm(np.asarray([(node["x"], node["y"]) for node in nodes])[:, None, :] - np.asarray([(node["x"], node["y"]) for node in nodes])[None, :, :], axis=2) * 1.4
    np.save(bundle / "distance_matrix.npy", matrix)
    with (bundle / "nodes.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = ["node_id", "node_type", "x", "y", "demand", "ready_time", "due_time", "service_time", "station_chargers", "charge_power_kw", "source_kind", "source_anchor", "osm_type", "osm_id", "latitude", "longitude"]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(nodes)
    with (bundle / "carbon_profile.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = ["time_index", "datetime_utc", "actual_gco2_per_kwh", "forecast_gco2_per_kwh", "index_label", "index_code", "horizon_second_start"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, row in enumerate(carbon_rows(), 1):
            gco2 = float(row["Chongqing"]) * 1000.0
            writer.writerow({"time_index": index, "datetime_utc": f"2025-01-01T{int(row['hour_of_day']):02d}:{int(row['minute']):02d}:00+00:00", "actual_gco2_per_kwh": f"{gco2:.6f}", "forecast_gco2_per_kwh": f"{gco2:.6f}", "index_label": "S1-2025 projected Chongqing", "index_code": index, "horizon_second_start": (index - 1) * 1800})
    instance = {"schema": "resetp.c31.draft.v2", "draft_only": True, "formal_experiment_authorized": False, "instance_id": BUNDLE_NAME, "demand_unit": "kg", "distance_unit": "meter", "nodes": [{key: value for key, value in node.items() if key not in {"tags", "source_response_sha256", "source_anchor", "osm_type", "osm_id", "latitude", "longitude", "source_kind", "charger_count_provenance"}} for node in nodes], "metadata": {"region": "cy", "region_role": "成渝：成都都市圈中规模候选", "named_real_osm_blocks": list(ANCHORS), "customer_count_target": 100, "customer_count_actual": 100, "customer_sampling_quotas": CUSTOMER_QUOTAS, "n_depots": 2, "n_stations": 3, "num_cv": 4, "num_ev": 3, "coverage_radius_km": radius, "coverage_contract_km": [80.0, 150.0], "distance_rule": "local equirectangular meters × 1.4; DRAFT only", "coordinate_rule": "real OSM WGS84 point or way center projected locally; never random or city-center fabricated", "order_attributes": {"status": "derived_data_not_real_orders", "seed": SEED, "distribution_reference": "models/src/setp_instance_lab/generator.py ScenarioConfig defaults: truncnorm demand + mixed time windows", "demand_parameters": {"mean": 520.0, "std": 240.0, "min": 50.0, "max": 2372.5}, "time_horizon_seconds": 86400.0}, "carbon_curve": {"column": "Chongqing", "source": str(TVCI.relative_to(REPO)), "source_sha256": sha256(TVCI), "data_nature": "Li et al. Scientific Data 2026 S1-2025 projected provincial hourly data, repeated to 48 half-hour slots; not measured realtime data"}}}
    write_json(bundle / "instance.json", instance)
    sources = []
    for node in nodes:
        sources.append({key: node.get(key, "") for key in ("node_id", "node_type", "source_kind", "source_anchor", "osm_type", "osm_id", "latitude", "longitude", "source_response_sha256", "charger_count_provenance")})
    write_json(bundle / "source_manifest.json", {"schema": "resetp.c31.osm-source.v2", "draft_only": True, "instance_id": BUNDLE_NAME, "selection_seed": SEED, "selection_rule": "non-uniform pre-snapshot real-POI quotas by named metropolitan block; no coordinate generation", "customer_sampling_quotas": CUSTOMER_QUOTAS, "feature_records": sources, "source_requests": active_records, "file_hashes": {path.name: sha256(path) for path in sorted(bundle.iterdir()) if path.is_file()}})
    return validate(bundle, radius)


def validate(bundle: Path, radius: float) -> dict[str, Any]:
    payload = json.loads((bundle / "instance.json").read_text(encoding="utf-8"))
    nodes = payload["nodes"]
    customers = [node for node in nodes if node["node_type"] == "c"]
    depots = [node for node in nodes if node["node_type"] == "d"]
    stations = [node for node in nodes if node["node_type"] == "f"]
    matrix = np.load(bundle / "distance_matrix.npy")
    loaded = load_search_bundle(bundle)
    errors = []
    if len(customers) != 100 or len(depots) != 2 or len(stations) < 3:
        errors.append("node-count contract failed")
    if any(not (0 <= float(node["ready_time"]) < float(node["due_time"]) <= 86400 and 0 < float(node["service_time"]) <= float(node["due_time"]) - float(node["ready_time"])) for node in customers):
        errors.append("customer time-window contract failed")
    if matrix.shape != (len(nodes), len(nodes)) or not np.allclose(matrix, matrix.T) or not np.allclose(np.diag(matrix), 0.0):
        errors.append("distance-matrix contract failed")
    if len(loaded.instance.nodes) != len(nodes) or len(loaded.carbon_profile) != 48:
        errors.append("existing-loader or 48-slot Chongqing-TVCI contract failed")
    if not 80.0 <= radius <= 150.0:
        errors.append("coverage contract failed")
    result = {"bundle": str(bundle.relative_to(REPO)), "pass": not errors, "errors": errors, "customers": len(customers), "depots": len(depots), "stations": len(stations), "nodes": len(nodes), "loader_nodes": len(loaded.instance.nodes), "carbon_rows": len(loaded.carbon_profile), "coverage_radius_km": radius, "search_evaluations": 0}
    write_json(bundle / "structure_gate.json", result)
    if errors:
        raise Halt("; ".join(errors))
    return result


def record_outcome(result: dict[str, Any] | None, error: str | None) -> None:
    history_path = ROOT / "attempt_history.json"
    history = json.loads(history_path.read_text(encoding="utf-8"))["attempts"] if history_path.exists() else []
    prior_decision_path = ROOT / "decision.json"
    if prior_decision_path.exists():
        prior = json.loads(prior_decision_path.read_text(encoding="utf-8"))
        key = (prior.get("verdict"), prior.get("halt_reason"))
        if not any((entry.get("verdict"), entry.get("halt_reason")) == key for entry in history):
            history.append({"recorded_utc": datetime.now(UTC).isoformat(), "verdict": prior.get("verdict"), "halt_reason": prior.get("halt_reason"), "result": prior.get("result"), "preserved_reason": "prior v2 outcome retained before controlled selected-subdistrict expansion"})
    write_json(history_path, {"schema": "resetp.c31.draft-v2-attempt-history.v1", "attempts": history})
    catalog_path = SNAPSHOTS / "probe_catalog.json"
    catalog_records = json.loads(catalog_path.read_text(encoding="utf-8"))["records"] if catalog_path.exists() else []
    selected_records = [row for row in catalog_records if row.get("logical_anchor") in ANCHORS]
    selected_counts = {
        anchor: {
            feature: sum(row.get("element_count", 0) for row in selected_records if row["logical_anchor"] == anchor and row["feature"] == feature and row["status"] == "success")
            for feature in ("poi", "depot", "station")
        }
        for anchor in ANCHORS
    }
    selected_tile_count = sum(len(tiles_for(bbox)) for bbox in ANCHORS.values())
    metadata = {"schema": "resetp.c31.draft-v2-task.v1", "task": "C31 Chengdu metropolitan 100-customer geographic-footprint repair", "script": str(Path(__file__).relative_to(REPO)), "script_sha256": sha256(Path(__file__)), "created_utc": datetime.now(UTC).isoformat(), "search_evaluations": 0, "draft_only": True, "formal_experiment_authorized": False, "network_endpoint": ENDPOINT, "old_drafts_overwritten": False}
    write_json(ROOT / "metadata.json", metadata)
    with (ROOT / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["instance_id", "status", "customers", "depots", "stations", "carbon_rows", "coverage_radius_km", "search_evaluations", "note"])
        writer.writeheader()
        if result:
            writer.writerow({"instance_id": BUNDLE_NAME, "status": "PASS_DRAFT_STRUCTURE_GATE", "customers": result["customers"], "depots": result["depots"], "stations": result["stations"], "carbon_rows": result["carbon_rows"], "coverage_radius_km": f"{result['coverage_radius_km']:.6f}", "search_evaluations": 0, "note": "DRAFT-v2 candidate only; not frozen"})
        else:
            writer.writerow({"instance_id": BUNDLE_NAME, "status": "HALT", "customers": "", "depots": "", "stations": "", "carbon_rows": "", "coverage_radius_km": "", "search_evaluations": 0, "note": error})
    decision = {"schema": "resetp.c31.draft-v2-decision.v1", "verdict": "PASS_DRAFT_STRUCTURE_GATE / NOT_READY_FOR_V2_FREEZE" if result else "HALT_C31_CY_100C_SELECTED_REAL_MAP_API_POOL_INSUFFICIENT", "draft_only": True, "formal_experiment_authorized": False, "search_evaluations": 0, "result": result, "halt_reason": error, "freeze_note": "This candidate is not a v2 frozen instance; user review and later formal gates remain required."}
    write_json(ROOT / "decision.json", decision)
    top_gate = result or {"bundle": None, "pass": False, "errors": [error], "customers": 0, "depots": 0, "stations": 0, "nodes": 0, "loader_nodes": 0, "carbon_rows": 0, "coverage_radius_km": None, "search_evaluations": 0, "note": "No candidate instance was written: the real OSM pool failed before any synthetic fallback could be considered."}
    write_json(ROOT / "structure_gate.json", top_gate)
    write_json(ROOT / "build_manifest.json", {"schema": "resetp.c31.draft-v2-build.v1", "complete": result is not None, "draft_only": True, "formal_experiment_authorized": False, "search_evaluations": 0, "candidate": BUNDLE_NAME, "selected_blocks": list(ANCHORS), "selected_static_tile_count": selected_tile_count, "selected_feature_counts": selected_counts, "result": result, "halt_reason": error, "report": str((ROOT / "report.md").relative_to(REPO))})
    report = ["# C31 成渝 100 客户 DRAFT-v2 地理足迹候选", "", "状态：**DRAFT-v2 only；0 次优化搜索；不得进入正式实验或直接冻结。**", ""]
    if result:
        report += [f"- 候选：`{BUNDLE_NAME}`；结构门=PASS；覆盖半径={result['coverage_radius_km']:.3f} km。", f"- 结构：客户={result['customers']}，车场={result['depots']}，充电站={result['stations']}，重庆TVCI=48槽。", f"- 坐标来源：{', '.join(ANCHORS)} 的 OSM Map API 静态小块；预先固定真实POI配额={CUSTOMER_QUOTAS}，车场为真实工业候选、充电站为真实OSM充电站。", "- 判决：`PASS_DRAFT_STRUCTURE_GATE / NOT_READY_FOR_V2_FREEZE`。通过构造门不等于冻结；仍待用户审阅与后续正式门。"]
    else:
        count_text = "；".join(f"{anchor}=POI/工业候选/充电站 {counts['poi']}/{counts['depot']}/{counts['station']}" for anchor, counts in selected_counts.items())
        report += [f"- 当前选定池：{selected_tile_count} 个 Map API 静态小块，{count_text}。", f"- 判决：`HALT_C31_CY_100C_SELECTED_REAL_MAP_API_POOL_INSUFFICIENT`。原因：{error}", "- 这是本轮预先声明的成都都市圈静态 Map API 小块池不足，不把它夸大为整个都市圈无数据。", "- 未用随机坐标、城市中心点伪造客户或坐标拉伸。"]
    (ROOT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    removed = remove_appledouble()
    write_json(ROOT / "artifact_hashes.json", {"schema": "resetp.artifact-hashes.v1", "search_evaluations": 0, "appledouble_event": f"removed {removed} external-volume sidecars before final audit", "files": write_hashes()})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="fetch only pending static Map API cells and preserve their raw records")
    parser.add_argument("--build", action="store_true", help="construct and validate only after all static snapshots exist")
    parser.add_argument("--max-requests", type=int, default=1)
    parser.add_argument("--pause-seconds", type=float, default=1.5)
    args = parser.parse_args()
    if args.fetch == args.build:
        parser.error("pass exactly one of --fetch or --build")
    if args.max_requests < 1:
        parser.error("--max-requests must be positive")
    if args.fetch:
        print(json.dumps(fetch_pending(args.max_requests, args.pause_seconds), ensure_ascii=False))
        return 0
    try:
        result = build()
        record_outcome(result, None)
        print(json.dumps({"verdict": "PASS_DRAFT_STRUCTURE_GATE", **result}, ensure_ascii=False))
        return 0
    except Halt as exc:
        ROOT.mkdir(parents=True, exist_ok=True)
        record_outcome(None, str(exc))
        print(json.dumps({"verdict": "HALT_C31_CY_100C_SELECTED_REAL_MAP_API_POOL_INSUFFICIENT", "reason": str(exc), "search_evaluations": 0}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
