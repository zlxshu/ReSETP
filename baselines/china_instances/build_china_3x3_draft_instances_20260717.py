#!/usr/bin/env python3
"""Build the C31 China 3x3 *DRAFT* instance set without running any search.

The script is deliberately a data-provenance and structural-construction tool.
It downloads only OSM/Overpass feature snapshots, records failed requests, and
creates no solver result or optimisation output.  Customer demand and time
windows are derived (not observed orders) from the existing instance-lab
generator distributions with a recorded NumPy seed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "solver" / "src"))

from setp_solver.search.bundle import load_search_bundle  # noqa: E402


OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
USER_AGENT = "ReSETP-C31-data-probe/1.0 (academic reproducibility contact: zhouleixishu@openai.com)"
SOURCE_ROOT = REPO / "data" / "ChinaInstances" / "c31_3x3_osm_map_api_grid_probe_20260717"
DRAFT_ROOT = REPO / "data" / "ChinaInstances" / "C31_DRAFT_20260717_osm_map_api_grid"
REPORT_PATH = REPO / "docs" / "handoff" / "china_3x3_instance_probe_20260717.md"
TVCI = REPO / "baselines" / "e4_e5" / "china_tvci_source_gate_20260717_v2" / "tvci_2025_48slot_wide.csv"

# Small city tiles intentionally avoid treating a failed wide Overpass request
# as an absence of mapped objects.  A 200-customer instance pools its named
# corridor anchors; it never manufactures geographic customer coordinates.
REGIONS: dict[str, dict[str, Any]] = {
    "jjj": {
        "carbon_column": "Beijing",
        "anchors": {
            "beijing": (39.85, 116.30, 39.95, 116.40),
            "tianjin": (39.05, 117.12, 39.15, 117.22),
            "shijiazhuang": (38.00, 114.45, 38.10, 114.55),
        },
        "scales": {50: ("beijing",), 100: ("beijing", "tianjin"), 200: ("beijing", "tianjin", "shijiazhuang")},
        "role": "京津冀：北京—天津—石家庄",
    },
    "prd": {
        "carbon_column": "Guangdong",
        "anchors": {
            "shenzhen": (22.50, 114.00, 22.60, 114.10),
            "dongguan": (23.00, 113.70, 23.10, 113.80),
            "guangzhou": (23.08, 113.22, 23.18, 113.32),
            "foshan": (23.00, 113.08, 23.10, 113.18),
        },
        "scales": {50: ("shenzhen",), 100: ("shenzhen", "dongguan"), 200: ("shenzhen", "guangzhou", "foshan")},
        "role": "珠三角：深圳—广州—佛山",
    },
    "cy": {
        "carbon_column": "Chongqing",
        "anchors": {
            "chengdu": (30.60, 104.00, 30.70, 104.10),
            "chongqing": (29.50, 106.45, 29.60, 106.55),
        },
        "scales": {50: ("chengdu",), 100: ("chengdu",), 200: ("chengdu", "chongqing")},
        "role": "成渝：成都—重庆",
    },
}


class ProbeError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def overpass_query(feature: str, bbox: tuple[float, float, float, float]) -> str:
    south, west, north, east = bbox
    box = f"({south:.5f},{west:.5f},{north:.5f},{east:.5f})"
    if feature == "poi":
        return (
            "[out:json][timeout:60];("
            f'node["shop"]{box};'
            f'node["amenity"~"^(restaurant|cafe|marketplace)$"]{box};'
            f'node["office"]{box};'
            ");out body;"
        )
    if feature == "station":
        return f'[out:json][timeout:45];(nwr["amenity"="charging_station"]{box};);out center tags;'
    if feature == "depot":
        return f'[out:json][timeout:45];(way["landuse"="industrial"]{box};relation["landuse"="industrial"]{box};);out center tags;'
    raise ValueError(feature)


def fetch(anchor: str, feature: str, bbox: tuple[float, float, float, float], root: Path) -> dict[str, Any]:
    """Fetch a single snapshot and retain response/error bytes plus query text."""
    queries = root / "queries"
    raw = root / "raw"
    queries.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    stem = f"{anchor}__{feature}"
    query = overpass_query(feature, bbox)
    query_path = queries / f"{stem}.overpassql"
    query_path.write_text(query + "\n", encoding="utf-8")
    url = OVERPASS_ENDPOINT + "?" + urllib.parse.urlencode({"data": query})
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    response_path = raw / f"{stem}.json"
    error_path = raw / f"{stem}.error.txt"
    base = {
        "anchor": anchor,
        "feature": feature,
        "bbox": list(bbox),
        "endpoint": OVERPASS_ENDPOINT,
        "request_url": url,
        "query_path": str(query_path.relative_to(REPO)),
        "query_sha256": sha256(query_path),
        "retrieved_utc": datetime.now(UTC).isoformat(),
    }
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
            status = int(response.status)
        response_path.write_bytes(body)
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload.get("elements"), list):
            raise ProbeError("Overpass JSON has no elements list")
        base.update(
            {
                "status": "success",
                "http_status": status,
                "response_path": str(response_path.relative_to(REPO)),
                "response_sha256": sha256(response_path),
                "response_bytes": len(body),
                "element_count": len(payload["elements"]),
                "osm_base_timestamp": payload.get("osm3s", {}).get("timestamp_osm_base", ""),
            }
        )
    except Exception as exc:  # Network peers also raise RemoteDisconnected/OSError directly.
        body = exc.read() if isinstance(exc, urllib.error.HTTPError) else b""
        message = f"{type(exc).__name__}: {exc}\n" + body.decode("utf-8", errors="replace")[:4000]
        error_path.write_text(message, encoding="utf-8")
        base.update(
            {
                "status": "failed",
                "http_status": int(exc.code) if isinstance(exc, urllib.error.HTTPError) else None,
                "error_path": str(error_path.relative_to(REPO)),
                "error_sha256": sha256(error_path),
                "failure_reason": message.splitlines()[0],
            }
        )
    return base


def point(element: dict[str, Any]) -> tuple[float, float] | None:
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center")
    if isinstance(center, dict) and "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def load_features(root: Path, records: Iterable[dict[str, Any]], feature: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for record in records:
        if record["feature"] != feature or record["status"] != "success":
            continue
        payload = json.loads((REPO / record["response_path"]).read_text(encoding="utf-8"))
        for element in payload["elements"]:
            coords = point(element)
            key = (str(element.get("type")), int(element.get("id", -1)))
            if coords is None or key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "source_anchor": record.get("logical_anchor", record["anchor"].split("_", 1)[1]),
                    "osm_type": key[0],
                    "osm_id": key[1],
                    "latitude": coords[0],
                    "longitude": coords[1],
                    "tags": element.get("tags", {}),
                    "source_response_sha256": record["response_sha256"],
                }
            )
    return result


def local_xy(items: list[dict[str, Any]]) -> dict[tuple[str, int], tuple[float, float]]:
    lat0 = sum(item["latitude"] for item in items) / len(items)
    lon0 = sum(item["longitude"] for item in items) / len(items)
    meters_lon = 111_320.0 * math.cos(math.radians(lat0))
    return {
        (item["osm_type"], item["osm_id"]): ((item["longitude"] - lon0) * meters_lon, (item["latitude"] - lat0) * 110_574.0)
        for item in items
    }


def deterministic_sample(items: list[dict[str, Any]], count: int, seed: int, *, label: str) -> list[dict[str, Any]]:
    if len(items) < count:
        raise ProbeError(f"{label} has {len(items)} real OSM features; need {count}. No random coordinates are allowed.")
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(items))[:count]
    return [items[int(index)] for index in order]


def farthest_sample(items: list[dict[str, Any]], count: int, seed: int, xy: dict[tuple[str, int], tuple[float, float]]) -> list[dict[str, Any]]:
    if len(items) < count:
        raise ProbeError(f"industrial depot pool has {len(items)} real OSM features; need {count}.")
    rng = np.random.default_rng(seed)
    first = items[int(rng.integers(len(items)))]
    selected = [first]
    while len(selected) < count:
        candidate = max(
            (item for item in items if item not in selected),
            key=lambda item: min(math.dist(xy[(item["osm_type"], item["osm_id"])], xy[(chosen["osm_type"], chosen["osm_id"])]) for chosen in selected),
        )
        selected.append(candidate)
    return selected


def derived_orders(count: int, seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Existing ScenarioConfig default distributions: truncnorm demand + mixed windows."""
    rng = np.random.default_rng(seed)
    demand = np.clip(rng.normal(520.0, 240.0, size=count), 50.0, 2372.5).round(1)
    modes = rng.choice(("uniform", "tight", "clustered"), size=count, p=(0.45, 0.25, 0.30))
    ready = np.zeros(count)
    due = np.zeros(count)
    service = np.zeros(count)
    for index, mode in enumerate(modes):
        if mode == "tight":
            width = rng.uniform(3600.0, 7200.0)
            start = rng.uniform(0.0, 86400.0 - width)
            duration = rng.uniform(180.0, 360.0)
        elif mode == "clustered":
            width = rng.uniform(3600.0, 14040.0)
            center = float(rng.choice((21600.0, 43200.0, 64800.0)))
            start = min(max(center - width / 2.0 + rng.normal(0.0, 1260.0), 0.0), 86400.0 - width)
            duration = rng.uniform(180.0, 1800.0)
        else:
            width = rng.uniform(3600.0, 21600.0)
            start = rng.uniform(0.0, 86400.0 - width)
            duration = rng.uniform(180.0, 1800.0)
        ready[index] = round(start, 1)
        due[index] = round(start + width, 1)
        service[index] = round(min(duration, width), 1)
    return demand, ready, due, service


def osm_capacity(tags: dict[str, Any]) -> tuple[int, str]:
    raw = str(tags.get("capacity", "")).strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw), "OSM capacity tag"
    return 1, "derived default=1 because this OSM station snapshot has no positive numeric capacity tag"


def carbon_rows(column: str) -> list[dict[str, str]]:
    with TVCI.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["date"] == "2025-01-01"]
    if len(rows) != 48:
        raise ProbeError(f"expected 48 S1-2025 rows for 2025-01-01; found {len(rows)}")
    return rows


def build_instance(region: str, scale: int, pools: dict[str, list[dict[str, Any]]], source_records: list[dict[str, Any]]) -> dict[str, Any]:
    spec = REGIONS[region]
    name = f"c31-{region}-{scale}c-01-DRAFT"
    out = DRAFT_ROOT / name
    out.mkdir(parents=True, exist_ok=False)
    anchors = set(spec["scales"][scale])
    selected = {kind: [item for item in values if item["source_anchor"] in anchors] for kind, values in pools.items()}
    seed = int(f"317{len(region)}{scale}")
    customers = deterministic_sample(selected["poi"], scale, seed, label=f"{name} POI pool")
    all_geo = customers + selected["depot"] + selected["station"]
    xy = local_xy(all_geo)
    depots = farthest_sample(selected["depot"], 2, seed + 1, xy)
    stations = deterministic_sample(selected["station"], min(3, len(selected["station"])), seed + 2, label=f"{name} station pool")
    demand, ready, due, service = derived_orders(scale, seed)
    nodes: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    for index, depot in enumerate(depots):
        x, y = xy[(depot["osm_type"], depot["osm_id"])]
        nodes.append({"node_id": f"D{index}", "node_type": "d", "x": x, "y": y, "demand": 0.0, "ready_time": 0.0, "due_time": 86400.0, "service_time": 0.0, "station_chargers": scale, "source_kind": "real_osm_industrial_candidate", **depot})
    for index, customer in enumerate(customers, start=1):
        x, y = xy[(customer["osm_type"], customer["osm_id"])]
        nodes.append({"node_id": f"C{index:03d}", "node_type": "c", "x": x, "y": y, "demand": float(demand[index - 1]), "ready_time": float(ready[index - 1]), "due_time": float(due[index - 1]), "service_time": float(service[index - 1]), "source_kind": "real_osm_poi_with_derived_order_attributes", **customer})
    for index, station in enumerate(stations, start=1):
        x, y = xy[(station["osm_type"], station["osm_id"])]
        chargers, charger_provenance = osm_capacity(station["tags"])
        nodes.append({"node_id": f"F{index}", "node_type": "f", "x": x, "y": y, "demand": 0.0, "ready_time": 0.0, "due_time": 86400.0, "service_time": 0.0, "charge_power_kw": 60.0, "station_chargers": chargers, "charger_count_provenance": charger_provenance, "source_kind": "real_osm_charging_station", **station})
    for node in nodes:
        source_rows.append({key: node.get(key, "") for key in ("node_id", "node_type", "source_kind", "source_anchor", "osm_type", "osm_id", "latitude", "longitude", "source_response_sha256", "charger_count_provenance")})
    coords = np.asarray([(node["x"], node["y"]) for node in nodes], dtype=float)
    matrix = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=2) * 1.4
    np.save(out / "distance_matrix.npy", matrix)
    with (out / "nodes.csv").open("w", encoding="utf-8", newline="") as handle:
        fieldnames = ["node_id", "node_type", "x", "y", "demand", "ready_time", "due_time", "service_time", "station_chargers", "charge_power_kw", "source_kind", "osm_type", "osm_id", "latitude", "longitude"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(nodes)
    curve = carbon_rows(spec["carbon_column"])
    with (out / "carbon_profile.csv").open("w", encoding="utf-8", newline="") as handle:
        fieldnames = ["time_index", "datetime_utc", "actual_gco2_per_kwh", "forecast_gco2_per_kwh", "index_label", "index_code", "horizon_second_start"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index, row in enumerate(curve, start=1):
            gco2 = float(row[spec["carbon_column"]]) * 1000.0
            writer.writerow({"time_index": index, "datetime_utc": f"2025-01-01T{int(row['hour_of_day']):02d}:{int(row['minute']):02d}:00+00:00", "actual_gco2_per_kwh": f"{gco2:.6f}", "forecast_gco2_per_kwh": f"{gco2:.6f}", "index_label": f"S1-2025 projected {spec['carbon_column']}", "index_code": index, "horizon_second_start": (index - 1) * 1800})
    payload = {
        "schema": "resetp.c31.draft.v1",
        "draft_only": True,
        "formal_experiment_authorized": False,
        "instance_id": name,
        "demand_unit": "kg",
        "distance_unit": "meter",
        "nodes": [{key: value for key, value in node.items() if key not in {"tags", "source_response_sha256", "source_anchor", "osm_type", "osm_id", "latitude", "longitude", "source_kind", "charger_count_provenance"}} for node in nodes],
        "metadata": {"region": region, "region_role": spec["role"], "customer_count_target": scale, "customer_count_actual": scale, "n_depots": 2, "n_stations": len(stations), "num_cv": 4, "num_ev": 3, "distance_rule": "local equirectangular meters × 1.4; DRAFT only", "coordinate_rule": "real OSM WGS84 point or way/relation center projected locally; never random", "order_attributes": {"status": "derived_data_not_real_orders", "seed": seed, "distribution_reference": "models/src/setp_instance_lab/generator.py ScenarioConfig defaults: truncnorm demand + mixed time windows", "demand_parameters": {"mean": 520.0, "std": 240.0, "min": 50.0, "max": 2372.5}, "time_horizon_seconds": 86400.0}, "carbon_curve": {"column": spec["carbon_column"], "source": str(TVCI.relative_to(REPO)), "source_sha256": sha256(TVCI), "data_nature": "Li et al. Scientific Data 2026 S1-2025 projected provincial hourly data, repeated to 48 half-hour slots; not measured realtime data"}, "station_capacity_note": "capacity tag is used when present; otherwise one connector is a derived operational placeholder, never claimed as observed pile count"},
    }
    write_json(out / "instance.json", payload)
    write_json(out / "source_manifest.json", {"schema": "resetp.c31.osm-source.v1", "draft_only": True, "instance_id": name, "selection_seed": seed, "feature_records": source_rows, "source_requests": [record for record in source_records if record.get("logical_anchor", record["anchor"].split("_", 1)[1]) in anchors], "file_hashes": {path.name: sha256(path) for path in sorted(out.iterdir()) if path.is_file()}})
    return validate_bundle(out)


def validate_bundle(bundle: Path) -> dict[str, Any]:
    payload = json.loads((bundle / "instance.json").read_text(encoding="utf-8"))
    nodes = payload["nodes"]
    node_ids = [str(node["node_id"]) for node in nodes]
    customers = [node for node in nodes if node["node_type"] == "c"]
    depots = [node for node in nodes if node["node_type"] == "d"]
    stations = [node for node in nodes if node["node_type"] == "f"]
    matrix = np.load(bundle / "distance_matrix.npy")
    loaded = load_search_bundle(bundle)
    errors: list[str] = []
    if len(node_ids) != len(set(node_ids)):
        errors.append("node ids are not unique")
    if len(customers) != int(payload["metadata"]["customer_count_actual"]):
        errors.append("customer count mismatch")
    if len(depots) < 2:
        errors.append("fewer than two depots")
    if not stations or any(node.get("station_chargers") in (None, 0) for node in stations):
        errors.append("charging station field missing")
    if any(not (0 <= float(node["ready_time"]) < float(node["due_time"]) <= 86400 and 0 < float(node["service_time"]) <= float(node["due_time"]) - float(node["ready_time"])) for node in customers):
        errors.append("invalid customer time window")
    if matrix.shape != (len(nodes), len(nodes)) or not np.allclose(matrix, matrix.T) or not np.allclose(np.diag(matrix), 0.0):
        errors.append("distance matrix invalid")
    if len(loaded.instance.nodes) != len(nodes) or len(loaded.carbon_profile) != 48:
        errors.append("existing loader round-trip failed")
    with (bundle / "nodes.csv").open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    if len(csv_rows) != len(nodes):
        errors.append("nodes.csv unreadable or row mismatch")
    result = {"bundle": str(bundle.relative_to(REPO)), "pass": not errors, "errors": errors, "customers": len(customers), "depots": len(depots), "stations": len(stations), "nodes": len(nodes), "loader_nodes": len(loaded.instance.nodes), "carbon_rows": len(loaded.carbon_profile)}
    write_json(bundle / "structure_gate.json", result)
    if errors:
        raise ProbeError(f"{bundle.name}: {'; '.join(errors)}")
    return result


def render_report(records: list[dict[str, Any]], results: list[dict[str, Any]], failures: list[str]) -> None:
    lines = ["# C31 中国 3×3 数据可得性探针与 DRAFT 算例构造（2026-07-17）", "", "状态：**DRAFT only；未运行任何算法或性能搜索；不得进入正式实验。**", "", "## 可得性与来源", "", "来源为 OpenStreetMap 官方 Map API 静态小地块快照（ODbL）。每次请求文本、编码 URL、原始 XML、派生要素 JSON 和 SHA-256 位于 `data/ChinaInstances/c31_3x3_osm_map_api_grid_probe_20260717/`。此前 Overpass POST 宽框请求返回 HTTP 406、GET 宽框请求返回 HTTP 504、随后被 HTTP 429 限流；这些失败不作为零数据。没有用随机坐标填补。", "", "| 区域 | POI | 工业/车场候选 | 充电站 | 失败请求 |", "|---|---:|---:|---:|---:|"]
    for region in REGIONS:
        subset = [record for record in records if record["anchor"].startswith(region + "_")]
        def count(feature: str) -> int:
            return sum(record.get("element_count", 0) for record in subset if record["feature"] == feature and record["status"] == "success")

        failed = sum(record["status"] == "failed" for record in subset)
        lines.append(f"| {region} | {count('poi')} | {count('depot')} | {count('station')} | {failed} |")
    lines += ["", "工业用地仅表示 OSM `landuse=industrial` 车场/物流园区候选，不声称每块都已核验为运营物流园。客户 POI 与充电站均保留 OSM 要素 ID；若 OSM 未给 `capacity`，`station_chargers=1` 是明确标注的派生运行参数，不是观察到的桩数。", "", "## 九个 DRAFT 算例与结构门", "", "| 实例 | 客户 | 车场 | 站点 | 覆盖半径（km） | 结构门 |", "|---|---:|---:|---:|---:|---:|"]
    for result in results:
        bundle = REPO / result["bundle"]
        node_rows = list(csv.DictReader((bundle / "nodes.csv").open(encoding="utf-8", newline="")))
        coords = [(float(row["x"]), float(row["y"])) for row in node_rows if row["node_type"] == "c"]
        cx = sum(x for x, _ in coords) / len(coords)
        cy = sum(y for _, y in coords) / len(coords)
        radius = max(math.dist((x, y), (cx, cy)) for x, y in coords) / 1000.0
        lines.append(f"| `{bundle.name}` | {result['customers']} | {result['depots']} | {result['stations']} | {radius:.1f} | {'PASS' if result['pass'] else 'FAIL'} |")
    lines += ["", "每个草稿含 `instance.json`、`nodes.csv`、`distance_matrix.npy`、`carbon_profile.csv`、`source_manifest.json` 和 `structure_gate.json`。坐标来自 OSM；需求、服务时长和时间窗是按已有 `setp_instance_lab` 生成器分布与各实例 seed 派生的模拟订单，绝不冒充真实订单。区域碳列分别为 `Beijing`、`Guangdong`、`Chongqing`，引自仓库已验签的 Li 等（Scientific Data, 2026）S1-2025 投影宽表，不能称为实测或实时数据。", "", "## 失败与决策", ""]
    if failures:
        lines += [f"- Map API 分块失败：{item}" for item in failures]
    else:
        lines.append("- Map API 分块：36/36 快照成功；完整请求台账在 `probe_catalog.json`。")
    lines += ["- Overpass POST（北京充电站宽框）：HTTP 406。", "- Overpass GET（北京 0.6° 充电站宽框）：HTTP 504，服务端忙。", "- Overpass GET（北京 POI 小框，重试后）：HTTP 429，速率限制。", "", "决策：本轮仅证明公开 OSM 的三区域要素在所取锚点上可构成可读取的**草稿**。工业地块标签不等同于已核验物流园，部分充电站缺少容量字段；且 `c31-cy-100c-01-DRAFT` 当前覆盖半径仅 3.7 km，不满足预注册的成都都市圈足迹，不能作为 v2 冻结候选。v2 前须补充多个成都都市圈真实 OSM 子区，或明确降级为抽象坐标；不得用随机点掩盖这个缺口。"]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(max_requests: int) -> dict[str, Any]:
    if DRAFT_ROOT.exists() and (DRAFT_ROOT / "build_manifest.json").exists():
        raise ProbeError("refusing to overwrite completed C31 DRAFT output")
    SOURCE_ROOT.mkdir(parents=True, exist_ok=True)
    progress_path = SOURCE_ROOT / "progress_catalog.json"
    records: list[dict[str, Any]] = json.loads(progress_path.read_text(encoding="utf-8"))["records"] if progress_path.exists() else []
    completed = {(record["anchor"], record["feature"]) for record in records}
    imported_static_snapshots = any("logical_anchor" in record for record in records)
    requests_run = 0
    if not imported_static_snapshots:
        for region, spec in REGIONS.items():
            for anchor, bbox in spec["anchors"].items():
                qualified = f"{region}_{anchor}"
                for feature in ("poi", "depot", "station"):
                    if (qualified, feature) in completed:
                        continue
                    records.append(fetch(qualified, feature, bbox, SOURCE_ROOT))
                    write_json(progress_path, {"schema": "resetp.c31.overpass-probe-progress.v1", "records": records})
                    requests_run += 1
                    if requests_run >= max_requests:
                        return {"complete": False, "requests_run": requests_run, "requests_total": len(records)}
                    time.sleep(1.2)
    write_json(SOURCE_ROOT / "probe_catalog.json", {"schema": "resetp.c31.overpass-probe.v1", "source_license": "Open Database License (ODbL)", "search_evaluations": 0, "records": records})
    pools: dict[str, list[dict[str, Any]]] = {}
    for feature in ("poi", "depot", "station"):
        pools[feature] = load_features(SOURCE_ROOT, records, feature)
    DRAFT_ROOT.mkdir(parents=True, exist_ok=False)
    results: list[dict[str, Any]] = []
    failures: list[str] = [f"{record['anchor']} / {record['feature']}: {record['failure_reason']}" for record in records if record["status"] == "failed"]
    for region in REGIONS:
        for scale in (50, 100, 200):
            try:
                results.append(build_instance(region, scale, pools, records))
            except ProbeError as exc:
                failures.append(str(exc))
    render_report(records, results, failures)
    manifest = {"schema": "resetp.c31.draft-build.v1", "draft_only": True, "formal_experiment_authorized": False, "search_evaluations": 0, "results": results, "failures": failures, "report": str(REPORT_PATH.relative_to(REPO))}
    write_json(DRAFT_ROOT / "build_manifest.json", manifest)
    if len(results) != 9 or failures:
        raise ProbeError(f"C31 build incomplete: {len(results)}/9 DRAFT bundles; failures={len(failures)}")
    manifest["complete"] = True
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="download OSM snapshots and construct all nine DRAFT bundles")
    parser.add_argument("--max-requests", type=int, default=2, help="maximum new network calls in this invocation; enables safe resume")
    args = parser.parse_args()
    if not args.build:
        parser.error("pass --build; this tool refuses implicit network/download side effects")
    if args.max_requests < 1:
        parser.error("--max-requests must be positive")
    manifest = build(args.max_requests)
    print(json.dumps({"complete": manifest["complete"], "requests_run": manifest.get("requests_run", 0), "bundles": len(manifest.get("results", [])), "report": manifest.get("report", ""), "search_evaluations": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
