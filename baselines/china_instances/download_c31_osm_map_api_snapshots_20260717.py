#!/usr/bin/env python3
"""Fetch resumable OSM Map API snapshots and normalize allowed C31 features."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_china_3x3_draft_instances_20260717 as c31  # noqa: E402


ENDPOINT = "https://api.openstreetmap.org/api/0.6/map"
USER_AGENT = "ReSETP-C31-data-probe/1.0 (academic reproducibility contact: zhouleixishu@openai.com)"
ROOT = c31.SOURCE_ROOT


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def tiles_for(anchor_bbox: tuple[float, float, float, float]) -> tuple[tuple[float, float, float, float], ...]:
    south, west, _, _ = anchor_bbox
    return tuple((south + 0.03 * row, west + 0.03 * col, south + 0.03 * (row + 1), west + 0.03 * (col + 1)) for row in range(2) for col in range(2))


def extract_features(xml_path: Path) -> dict[str, list[dict[str, Any]]]:
    root = ET.fromstring(xml_path.read_bytes())
    coordinates: dict[str, tuple[float, float]] = {}
    poi: list[dict[str, Any]] = []
    stations: list[dict[str, Any]] = []
    depots: list[dict[str, Any]] = []
    for element in root.findall("node"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in element.findall("tag")}
        lat, lon = float(element.attrib["lat"]), float(element.attrib["lon"])
        coordinates[element.attrib["id"]] = (lat, lon)
        row = {"type": "node", "id": int(element.attrib["id"]), "lat": lat, "lon": lon, "tags": tags}
        if "shop" in tags or tags.get("amenity") in {"restaurant", "cafe", "marketplace"} or "office" in tags:
            poi.append(row)
        if tags.get("amenity") == "charging_station":
            stations.append(row)
    for element in root.findall("way"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in element.findall("tag")}
        if tags.get("landuse") != "industrial" and tags.get("amenity") != "charging_station":
            continue
        points = [coordinates[ref.attrib["ref"]] for ref in element.findall("nd") if ref.attrib["ref"] in coordinates]
        if not points:
            continue
        row = {"type": "way", "id": int(element.attrib["id"]), "center": {"lat": sum(lat for lat, _ in points) / len(points), "lon": sum(lon for _, lon in points) / len(points)}, "tags": tags}
        if tags.get("landuse") == "industrial":
            depots.append(row)
        if tags.get("amenity") == "charging_station":
            stations.append(row)
    return {"poi": poi, "depot": depots, "station": stations}


def fetch_tile(region: str, anchor: str, tile_index: int, bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    queries, raw, derived = ROOT / "queries", ROOT / "raw", ROOT / "derived"
    for path in (queries, raw, derived):
        path.mkdir(parents=True, exist_ok=True)
    qualified = f"{region}_{anchor}_t{tile_index}"
    south, west, north, east = bbox
    bbox_value = f"{west:.5f},{south:.5f},{east:.5f},{north:.5f}"
    query_path = queries / f"{qualified}.request.txt"
    query_path.write_text(f"GET {ENDPOINT}?bbox={bbox_value}\n", encoding="utf-8")
    url = ENDPOINT + "?" + urllib.parse.urlencode({"bbox": bbox_value})
    raw_path = raw / f"{qualified}.osm"
    base = {"anchor": qualified, "logical_anchor": anchor, "endpoint": ENDPOINT, "request_url": url, "query_path": str(query_path.relative_to(REPO)), "query_sha256": sha256(query_path), "bbox": [south, west, north, east], "retrieved_utc": datetime.now(UTC).isoformat()}
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/xml"})
        with urllib.request.urlopen(request, timeout=90) as response:
            body, status = response.read(), int(response.status)
        raw_path.write_bytes(body)
        feature_rows = extract_features(raw_path)
        records: list[dict[str, Any]] = []
        for feature, rows in feature_rows.items():
            feature_path = derived / f"{qualified}__{feature}.json"
            write_json(feature_path, {"elements": rows, "source_download_path": str(raw_path.relative_to(REPO)), "source_download_sha256": sha256(raw_path)})
            records.append(base | {"feature": feature, "status": "success", "http_status": status, "response_path": str(feature_path.relative_to(REPO)), "response_sha256": sha256(feature_path), "source_download_path": str(raw_path.relative_to(REPO)), "source_download_sha256": sha256(raw_path), "response_bytes": len(body), "element_count": len(rows), "osm_base_timestamp": "Map API snapshot; raw XML retained"})
        return records
    except Exception as exc:
        error_path = raw / f"{qualified}.error.txt"
        error_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        return [base | {"feature": feature, "status": "failed", "http_status": getattr(exc, "code", None), "error_path": str(error_path.relative_to(REPO)), "error_sha256": sha256(error_path), "failure_reason": f"{type(exc).__name__}: {exc}"} for feature in ("poi", "depot", "station")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-anchors", type=int, default=1)
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    progress = ROOT / "progress_catalog.json"
    records = json.loads(progress.read_text(encoding="utf-8"))["records"] if progress.exists() else []
    done = {record["anchor"] for record in records}
    run = 0
    for region, spec in c31.REGIONS.items():
        for anchor, bbox in spec["anchors"].items():
            for tile_index, tile in enumerate(tiles_for(bbox)):
                qualified = f"{region}_{anchor}_t{tile_index}"
                if qualified in done:
                    continue
                records.extend(fetch_tile(region, anchor, tile_index, tile))
                write_json(progress, {"schema": "resetp.c31.osm-map-api-progress.v1", "records": records})
                run += 1
                if run >= args.max_anchors:
                    print(json.dumps({"complete": False, "anchors_run": run, "anchors_total": len(done) + run}, ensure_ascii=False))
                    return 0
    print(json.dumps({"complete": True, "anchors_run": run, "anchors_total": len({record['anchor'] for record in records})}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
