#!/usr/bin/env python3
"""Extract and audit the full OSM pools for the nine China city anchors.

This tool is intentionally data-only.  It never reads or writes solver
results, never changes an existing China instance, and never performs an
optimisation search.  ``--offline-audit`` creates the reproducibility shell
from the existing DRAFT coordinates and legacy snapshot.  The normal mode
uses Overpass, keeps every request/response, and can be resumed from the same
output directory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO / "data" / "ChinaInstances" / "china9_city_full_pool_20260718"
EXISTING_INSTANCES = REPO / "data" / "ChinaInstances" / "CHINA81_DRAFT_20260717_source_bound"
LEGACY_ROOT = REPO / "data" / "ChinaInstances" / "c31_3x3_osm_map_api_grid_probe_20260717"
LEGACY_CATALOG = LEGACY_ROOT / "probe_catalog.json"
LEGACY_SPECIAL_BEIJING_POI = LEGACY_ROOT / "raw" / "jjj_beijing__poi.json"
USER_AGENT = "ReSETP-China9-P1/1.0 (academic reproducibility)"
DEFAULT_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
FEATURES = ("charging_station", "named_poi", "logistics_candidate")
EXPANSION_FRACTION = 0.20
LOGISTICS_TERMS = re.compile(r"物流|仓储|园区|配送|快递|货运|logistics|warehouse|distribution|freight", re.I)
OBVIOUS_NON_LOGISTICS = re.compile(
    r"scrap[_ ]?yard|废品|垃圾|墓|陵|殡葬|采石|矿|污水|排水|水务|屠宰|养殖|"
    r"印钞|印制|邮票|棉纺|纺织|制管|管道|制药|药业|药厂|卷烟|烟厂|发电厂|"
    r"电力工程|特种电源|化纤|制衣|床垫|焊接|仪器|研究所|实验室|肉食|服装|轴承|"
    r"电子|生物医药|孵化|飞机设计|飞机工程|柴油机|能源|节能|文创|科技公司|科技有限公司|"
    r"汽车维修|维修|工厂|科技(?=\s)|汽车(?=\s)|factory|pharma|research|water|sewage|power|textile|"
    r"manufactur|scrap|cemetery|quarry|landfill|wastewater|slaughter",
    re.I,
)

CITIES: dict[str, dict[str, str]] = {
    "beijing": {"region": "jjj", "name_zh": "北京"},
    "tianjin": {"region": "jjj", "name_zh": "天津"},
    "shijiazhuang": {"region": "jjj", "name_zh": "石家庄"},
    "shenzhen": {"region": "prd", "name_zh": "深圳"},
    "dongguan": {"region": "prd", "name_zh": "东莞"},
    "guangzhou": {"region": "prd", "name_zh": "广州"},
    "foshan": {"region": "prd", "name_zh": "佛山"},
    "chengdu": {"region": "cy", "name_zh": "成都"},
    "chongqing": {"region": "cy", "name_zh": "重庆"},
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def clean_appledouble(root: Path) -> list[str]:
    """Remove macOS AppleDouble sidecars from this task's output only."""
    removed: list[str] = []
    if not root.exists():
        return removed
    for path in sorted(root.rglob("._*")):
        if path.is_file():
            removed.append(str(path.relative_to(REPO)))
            path.unlink()
    return removed


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def git_fingerprint() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, command in (
        ("branch", ["git", "branch", "--show-current"]),
        ("commit", ["git", "rev-parse", "HEAD"]),
    ):
        try:
            result[key] = subprocess.run(command, cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            result[key] = "unavailable"
    return result


def city_boxes() -> dict[str, dict[str, Any]]:
    points: dict[str, list[tuple[float, float]]] = defaultdict(list)
    source_files: dict[str, set[str]] = defaultdict(set)
    for node_path in sorted(EXISTING_INSTANCES.glob("cn-*/nodes.csv")):
        for row in read_csv(node_path):
            city = row.get("source_anchor", "").strip()
            if city not in CITIES:
                continue
            points[city].append((float(row["latitude"]), float(row["longitude"])))
            source_files[city].add(str(node_path.relative_to(REPO)))
    missing = sorted(set(CITIES) - set(points))
    if missing:
        raise RuntimeError(f"no existing DRAFT coordinates for city anchors: {missing}")
    boxes: dict[str, dict[str, Any]] = {}
    for city in sorted(CITIES):
        coords = points[city]
        latitudes = [point[0] for point in coords]
        longitudes = [point[1] for point in coords]
        south, north = min(latitudes), max(latitudes)
        west, east = min(longitudes), max(longitudes)
        lat_span, lon_span = north - south, east - west
        if lat_span <= 0 or lon_span <= 0:
            raise RuntimeError(f"city {city} has a zero-width coordinate span")
        boxes[city] = {
            "city": city,
            "region": CITIES[city]["region"],
            "name_zh": CITIES[city]["name_zh"],
            "source_node_count": len(coords),
            "source_file_count": len(source_files[city]),
            "source_lat_min": south,
            "source_lat_max": north,
            "source_lon_min": west,
            "source_lon_max": east,
            "expansion_fraction": EXPANSION_FRACTION,
            "south": south - EXPANSION_FRACTION * lat_span,
            "west": west - EXPANSION_FRACTION * lon_span,
            "north": north + EXPANSION_FRACTION * lat_span,
            "east": east + EXPANSION_FRACTION * lon_span,
            "source_files": sorted(source_files[city]),
        }
    return boxes


def point_from_element(element: dict[str, Any]) -> tuple[float, float] | None:
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center")
    if isinstance(center, dict) and "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def named_poi(tags: dict[str, Any]) -> bool:
    return bool(tags.get("name") or tags.get("brand"))


def logistics_candidate(tags: dict[str, Any]) -> bool:
    return tags.get("landuse") == "industrial" or bool(LOGISTICS_TERMS.search(str(tags.get("name", ""))))


def city_from_record(record: dict[str, Any]) -> str:
    """Resolve both current logical_anchor records and the legacy full-box record."""
    raw = str(record.get("logical_anchor") or record.get("anchor") or "")
    raw = re.sub(r"_t[0-3]$", "", raw)
    if "_" in raw and raw.split("_", 1)[0] in {"jjj", "prd", "cy"}:
        raw = raw.split("_", 1)[1]
    return raw


def legacy_source_evidence() -> list[dict[str, str]]:
    """Hash the retained old query/response files used to recompute old counts."""
    if not LEGACY_CATALOG.exists():
        return []
    catalog = json.loads(LEGACY_CATALOG.read_text(encoding="utf-8"))
    paths = {LEGACY_CATALOG}
    for record in catalog.get("records", []):
        for key in ("query_path", "response_path"):
            value = record.get(key)
            if value:
                path = REPO / str(value)
                if path.exists():
                    paths.add(path)
    return [
        {"path": str(path.relative_to(REPO)), "sha256": sha256_path(path)}
        for path in sorted(paths)
    ]


def legacy_counts() -> tuple[list[dict[str, Any]], dict[str, dict[str, dict[tuple[str, int], dict[str, Any]]]]]:
    if not LEGACY_CATALOG.exists():
        raise RuntimeError(f"missing legacy OSM catalog: {LEGACY_CATALOG}")
    catalog = json.loads(LEGACY_CATALOG.read_text(encoding="utf-8"))
    items: dict[str, dict[str, dict[tuple[str, int], dict[str, Any]]]] = {
        city: {feature: {} for feature in FEATURES} for city in CITIES
    }
    for record in catalog.get("records", []):
        if record.get("status") != "success":
            continue
        city = city_from_record(record)
        if city not in CITIES:
            continue
        response_path = REPO / str(record["response_path"])
        if not response_path.exists():
            continue
        payload = json.loads(response_path.read_text(encoding="utf-8"))
        for element in payload.get("elements", []):
            tags = element.get("tags") or {}
            key = (str(element.get("type", "")), int(element.get("id", -1)))
            feature = str(record.get("feature", ""))
            if feature == "station" and tags.get("amenity") == "charging_station":
                items[city]["charging_station"][key] = element
            elif feature == "poi" and named_poi(tags):
                items[city]["named_poi"][key] = element
            elif feature == "depot" and tags.get("landuse") == "industrial":
                items[city]["logistics_candidate"][key] = element
    rows: list[dict[str, Any]] = []
    for city in sorted(CITIES):
        for feature in FEATURES:
            rows.append(
                {
                    "city": city,
                    "region": CITIES[city]["region"],
                    "feature": feature,
                    "old_count": len(items[city][feature]),
                    "old_source": "c31_3x3_osm_map_api_grid_probe_20260717 probe_catalog + retained raw/derived responses",
                    "old_definition": {
                        "charging_station": "amenity=charging_station",
                        "named_poi": "name or brand tag present",
                        "logistics_candidate": "landuse=industrial",
                    }[feature],
                }
            )
    return rows, items


def query_for(feature: str, box: dict[str, Any]) -> str:
    bbox = f"({box['south']:.8f},{box['west']:.8f},{box['north']:.8f},{box['east']:.8f})"
    if feature == "charging_station":
        selector = f'nwr["amenity"="charging_station"]{bbox};'
    elif feature == "named_poi":
        selector = (
            f'nwr["shop"]{bbox};'
            f'nwr["amenity"~"^(restaurant|cafe|marketplace)$"]{bbox};'
            f'nwr["office"]{bbox};'
        )
    elif feature == "logistics_candidate":
        selector = (
            f'nwr["landuse"="industrial"]{bbox};'
            f'nwr["name"~"物流|仓储|园区|配送|快递|货运",i]{bbox};'
        )
    else:
        raise ValueError(feature)
    return f"[out:json][timeout:180];({selector});out center tags;"


def request_text(endpoint: str, query: str) -> tuple[bytes, str]:
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    text = "\n".join(
        (
            "POST " + endpoint,
            "Content-Type: application/x-www-form-urlencoded",
            "User-Agent: " + USER_AGENT,
            "",
            body.decode("ascii"),
            "",
        )
    )
    return body, text


def failure_record(
    city: str,
    feature: str,
    attempt: int,
    endpoint: str,
    request_path: Path,
    error_path: Path,
    started: float,
    exc: BaseException,
    box: dict[str, Any],
) -> dict[str, Any]:
    return {
        "run_id": f"{city}:{feature}:{attempt}",
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
        "response_bytes": 0,
        "elapsed_seconds": round(time.monotonic() - started, 6),
        "failure_reason": f"{type(exc).__name__}: {exc}",
        "retrieved_utc": utc_now(),
        "bbox": json.dumps([box["south"], box["west"], box["north"], box["east"]]),
    }


def fetch_one(
    city: str,
    feature: str,
    box: dict[str, Any],
    output: Path,
    endpoints: tuple[str, ...],
    retries: int,
    timeout: float,
) -> dict[str, Any]:
    query = query_for(feature, box)
    attempt = 0
    failures: list[dict[str, Any]] = []
    for endpoint_index, endpoint in enumerate(endpoints):
        for retry_index in range(1, retries + 1):
            attempt += 1
            stem = f"{city}__{feature}__e{endpoint_index + 1}__a{retry_index}"
            query_path = output / "requests" / f"{stem}.overpassql"
            request_path = output / "requests" / f"{stem}.request.txt"
            query_path.parent.mkdir(parents=True, exist_ok=True)
            query_path.write_text(query + "\n", encoding="utf-8")
            body, request_repr = request_text(endpoint, query)
            request_path.write_text(request_repr, encoding="utf-8")
            started = time.monotonic()
            try:
                request = urllib.request.Request(
                    endpoint,
                    data=body,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    response_body = response.read()
                    http_status = int(response.status)
                payload = json.loads(response_body.decode("utf-8"))
                if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
                    raise ValueError("Overpass response has no JSON elements list")
                response_path = output / "raw" / f"{stem}.json"
                response_path.parent.mkdir(parents=True, exist_ok=True)
                response_path.write_bytes(response_body)
                return {
                    "run_id": f"{city}:{feature}:{attempt}",
                    "city": city,
                    "region": CITIES[city]["region"],
                    "feature": feature,
                    "attempt": attempt,
                    "endpoint": endpoint,
                    "status": "success",
                    "http_status": http_status,
                    "request_path": str(request_path.relative_to(REPO)),
                    "request_sha256": sha256_path(request_path),
                    "response_path": str(response_path.relative_to(REPO)),
                    "response_sha256": sha256_path(response_path),
                    "error_path": "",
                    "error_sha256": "",
                    "response_bytes": len(response_body),
                    "elapsed_seconds": round(time.monotonic() - started, 6),
                    "failure_reason": "",
                    "retrieved_utc": utc_now(),
                    "bbox": json.dumps([box["south"], box["west"], box["north"], box["east"]]),
                }
            except Exception as exc:  # noqa: BLE001 - network failures are recorded, never hidden.
                error_path = output / "raw" / f"{stem}.error.txt"
                error_path.parent.mkdir(parents=True, exist_ok=True)
                error_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
                failures.append(failure_record(city, feature, attempt, endpoint, request_path, error_path, started, exc, box))
    if not failures:
        raise RuntimeError(f"no attempts made for {city}/{feature}")
    failures[-1]["failure_reason"] = "; ".join(item["failure_reason"] for item in failures)
    return failures[-1]


def element_matches(feature: str, tags: dict[str, Any]) -> bool:
    if feature == "charging_station":
        return tags.get("amenity") == "charging_station"
    if feature == "named_poi":
        return named_poi(tags) and (
            "shop" in tags or tags.get("amenity") in {"restaurant", "cafe", "marketplace"} or "office" in tags
        )
    if feature == "logistics_candidate":
        return logistics_candidate(tags)
    raise ValueError(feature)


def numeric_positive(value: Any) -> bool:
    numbers = re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", str(value))
    return any(float(number) > 0 for number in numbers)


def parameter_tags(tags: dict[str, Any]) -> dict[str, Any]:
    power = {key: value for key, value in tags.items() if "output" in key or key in {"power", "charging_power"}}
    capacity = {key: value for key, value in tags.items() if key == "capacity" or key.endswith(":capacity")}
    sockets = {key: value for key, value in tags.items() if key.startswith("socket:")}
    return {
        "power_tags_json": json.dumps(power, ensure_ascii=False, sort_keys=True),
        "capacity_tags_json": json.dumps(capacity, ensure_ascii=False, sort_keys=True),
        "socket_tags_json": json.dumps(sockets, ensure_ascii=False, sort_keys=True),
        "positive_power_tag": bool(power) and any(numeric_positive(value) for value in power.values()),
        "positive_capacity_tag": bool(capacity) and any(numeric_positive(value) for value in capacity.values()),
        "socket_tag_present": bool(sockets),
    }


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


def materialize_pool(
    city: str,
    feature: str,
    box: dict[str, Any],
    run: dict[str, Any],
    output: Path,
) -> list[dict[str, Any]]:
    payload = json.loads((REPO / run["response_path"]).read_text(encoding="utf-8"))
    elements: dict[tuple[str, int], dict[str, Any]] = {}
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        key = (str(element.get("type", "")), int(element.get("id", -1)))
        if key[0] and key[1] >= 0 and element_matches(feature, tags):
            elements[key] = element
    rows: list[dict[str, Any]] = []
    for (osm_type, osm_id), element in sorted(elements.items()):
        coords = point_from_element(element)
        tags = element.get("tags") or {}
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
            "source_query_bbox": json.dumps([box["south"], box["west"], box["north"], box["east"]]),
            "positive_power_tag": "",
            "positive_capacity_tag": "",
            "socket_tag_present": "",
            "power_tags_json": "{}",
            "capacity_tags_json": "{}",
            "socket_tags_json": "{}",
        }
        if feature == "charging_station":
            row.update(parameter_tags(tags))
        rows.append(row)
    pool_path = output / "pools" / f"{city}__{feature}.csv"
    write_csv(pool_path, rows, POOL_FIELDS)
    return rows


def tags_from_row(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("tags", {})
    return value if isinstance(value, dict) else json.loads(str(value))


def obvious_non_logistics(tags: dict[str, Any]) -> bool:
    text = " ".join(str(tags.get(key, "")) for key in ("name", "name:zh", "name:en", "industrial", "landuse", "amenity"))
    return bool(OBVIOUS_NON_LOGISTICS.search(text))


def candidate_score(tags: dict[str, Any]) -> int:
    text = json.dumps(tags, ensure_ascii=False)
    score = 0
    if LOGISTICS_TERMS.search(text):
        score += 5
    if tags.get("industrial") in {"logistics", "warehouse", "distribution", "transport", "depot"}:
        score += 4
    if tags.get("depot"):
        score += 2
    if tags.get("name") or tags.get("brand"):
        score += 1
    return score


def legacy_shortlist(
    old_items: dict[str, dict[str, dict[tuple[str, int], dict[str, Any]]]],
    output: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for region in ("jjj", "prd", "cy"):
        candidates: list[dict[str, Any]] = []
        for city, spec in CITIES.items():
            if spec["region"] != region:
                continue
            for (osm_type, osm_id), element in old_items[city]["logistics_candidate"].items():
                tags = element.get("tags") or {}
                if obvious_non_logistics(tags):
                    continue
                name = tags.get("name") or tags.get("brand") or "（无名工业用地）"
                candidates.append(
                    {
                        "region": region,
                        "city": city,
                        "city_name_zh": spec["name_zh"],
                        "name": name,
                        "osm_type": osm_type,
                        "osm_id": osm_id,
                        "tags_summary": "; ".join(f"{key}={tags[key]}" for key in sorted(tags) if key in {"landuse", "industrial", "depot", "name", "brand", "service", "operator"}),
                        "tags": json.dumps(tags, ensure_ascii=False, sort_keys=True),
                        "candidate_score": candidate_score(tags),
                        "source_basis": "legacy_small_snapshot",
                        "review_status": "REFERENCE_ONLY_NOT_P1_NEW_POOL",
                    }
                )
        candidates.sort(key=lambda row: (-int(row["candidate_score"]), row["city"], row["osm_type"], int(row["osm_id"])))
        rows.extend(candidates[:12])
    write_csv(
        output / "shortlist_candidates.csv",
        rows,
        [
            "region",
            "city",
            "city_name_zh",
            "name",
            "osm_type",
            "osm_id",
            "tags_summary",
            "tags",
            "candidate_score",
            "source_basis",
            "review_status",
        ],
    )
    return rows


def new_shortlist(output: Path, pool_rows: dict[tuple[str, str], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for region in ("jjj", "prd", "cy"):
        candidates: list[dict[str, Any]] = []
        for city, spec in CITIES.items():
            if spec["region"] != region:
                continue
            for row in pool_rows.get((city, "logistics_candidate"), []):
                tags = tags_from_row(row)
                if obvious_non_logistics(tags):
                    continue
                candidates.append(
                    {
                        "region": region,
                        "city": city,
                        "city_name_zh": spec["name_zh"],
                        "name": row.get("name") or row.get("brand") or "（无名工业用地）",
                        "osm_type": row["osm_type"],
                        "osm_id": row["osm_id"],
                        "tags_summary": "; ".join(f"{key}={tags[key]}" for key in sorted(tags) if key in {"landuse", "industrial", "depot", "name", "brand", "service", "operator"}),
                        "tags": row["tags"],
                        "candidate_score": candidate_score(tags),
                        "source_basis": "new_full_overpass_pool",
                        "review_status": "HUMAN_REVIEW_REQUIRED",
                    }
                )
        candidates.sort(key=lambda row: (-int(row["candidate_score"]), row["city"], row["osm_type"], int(row["osm_id"])))
        rows.extend(candidates[:12])
    write_csv(
        output / "shortlist_candidates.csv",
        rows,
        [
            "region",
            "city",
            "city_name_zh",
            "name",
            "osm_type",
            "osm_id",
            "tags_summary",
            "tags",
            "candidate_score",
            "source_basis",
            "review_status",
        ],
    )
    return rows


def environment_probe_files(output: Path) -> list[dict[str, Any]]:
    probes = [
        (
            "shell_overpass_dns",
            "https://overpass-api.de/api/interpreter",
            "POST [out:json][timeout:30];nwr[amenity=charging_station](39.82927240,116.27914138,39.96995338,116.42002434);out center tags;",
            "curl: (6) Could not resolve host: overpass-api.de",
        ),
        (
            "shell_geofabrik_dns",
            "https://download.geofabrik.de/asia/china.html",
            "HEAD https://download.geofabrik.de/asia/china.html",
            "curl: (6) Could not resolve host: download.geofabrik.de",
        ),
        (
            "dns_over_https_direct_ip",
            "https://1.1.1.1/dns-query?name=overpass-api.de&type=A",
            "GET https://1.1.1.1/dns-query?name=overpass-api.de&type=A",
            "curl: (7) Failed to connect to 1.1.1.1 port 443 after 1 ms: Could not connect to server",
        ),
        (
            "browser_mcp_attempt",
            "https://overpass-api.de/api/interpreter",
            "browser_navigate requested; no raw response accepted",
            "MCP tool call rejected by current session",
        ),
    ]
    rows: list[dict[str, Any]] = []
    for name, endpoint, request, error in probes:
        request_path = output / "network_probe" / f"{name}.request.txt"
        error_path = output / "network_probe" / f"{name}.error.txt"
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text(request + "\n", encoding="utf-8")
        error_path.write_text(error + "\n", encoding="utf-8")
        rows.append(
            {
                "run_id": f"environment:{name}",
                "city": "ALL",
                "region": "ALL",
                "feature": "environment_probe",
                "attempt": 1,
                "endpoint": endpoint,
                "status": "failed_environment",
                "http_status": "",
                "request_path": str(request_path.relative_to(REPO)),
                "request_sha256": sha256_path(request_path),
                "response_path": "",
                "response_sha256": "",
                "error_path": str(error_path.relative_to(REPO)),
                "error_sha256": sha256_path(error_path),
                "response_bytes": 0,
                "elapsed_seconds": "",
                "failure_reason": error,
                "retrieved_utc": utc_now(),
                "bbox": "",
            }
        )
    return rows


RUN_FIELDS = [
    "run_id",
    "city",
    "region",
    "feature",
    "attempt",
    "endpoint",
    "status",
    "http_status",
    "request_path",
    "request_sha256",
    "response_path",
    "response_sha256",
    "error_path",
    "error_sha256",
    "response_bytes",
    "elapsed_seconds",
    "failure_reason",
    "retrieved_utc",
    "bbox",
]


def write_counts(
    output: Path,
    boxes: dict[str, dict[str, Any]],
    old_rows: list[dict[str, Any]],
    pool_rows: dict[tuple[str, str], list[dict[str, Any]]],
    runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    old_index = {(row["city"], row["feature"]): int(row["old_count"]) for row in old_rows}
    successful = {(row["city"], row["feature"]): row for row in runs if row.get("status") == "success"}
    rows: list[dict[str, Any]] = []
    for city in sorted(CITIES):
        for feature in FEATURES:
            key = (city, feature)
            if key in successful:
                count: Any = len(pool_rows.get(key, []))
                status = "EXTRACTED"
                diff: Any = count - old_index[key]
            else:
                count = ""
                status = "NOT_EXTRACTED"
                diff = ""
            box = boxes[city]
            rows.append(
                {
                    "city": city,
                    "region": CITIES[city]["region"],
                    "feature": feature,
                    "new_status": status,
                    "new_count": count,
                    "old_count": old_index[key],
                    "new_minus_old": diff,
                    "query_bbox": json.dumps([box["south"], box["west"], box["north"], box["east"]]),
                    "old_source": "legacy C31 small-district snapshot",
                }
            )
    write_csv(
        output / "city_counts.csv",
        rows,
        ["city", "region", "feature", "new_status", "new_count", "old_count", "new_minus_old", "query_bbox", "old_source"],
    )
    return rows


def write_station_summary(
    output: Path,
    pool_rows: dict[tuple[str, str], list[dict[str, Any]]],
    runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    extracted_cities = {
        row["city"]
        for row in runs
        if row.get("feature") == "charging_station" and row.get("status") == "success"
    }
    rows: list[dict[str, Any]] = []
    for city in sorted(CITIES):
        stations = pool_rows.get((city, "charging_station"), [])
        if city not in extracted_cities:
            rows.append(
                {
                    "city": city,
                    "region": CITIES[city]["region"],
                    "station_count": "",
                    "positive_power_count": "",
                    "positive_capacity_count": "",
                    "positive_power_or_capacity_count": "",
                    "socket_tag_count": "",
                    "positive_power_rate": "",
                    "positive_capacity_rate": "",
                    "positive_power_or_capacity_rate": "",
                    "socket_tag_rate": "",
                    "status": "NOT_EXTRACTED",
                }
            )
            continue
        if not stations:
            rows.append(
                {
                    "city": city,
                    "region": CITIES[city]["region"],
                    "station_count": 0,
                    "positive_power_count": 0,
                    "positive_capacity_count": 0,
                    "positive_power_or_capacity_count": 0,
                    "socket_tag_count": 0,
                    "positive_power_rate": "0.000000",
                    "positive_capacity_rate": "0.000000",
                    "positive_power_or_capacity_rate": "0.000000",
                    "socket_tag_rate": "0.000000",
                    "status": "EXTRACTED",
                }
            )
            continue
        positive_power = sum(row["positive_power_tag"] is True or row["positive_power_tag"] == "True" for row in stations)
        positive_capacity = sum(row["positive_capacity_tag"] is True or row["positive_capacity_tag"] == "True" for row in stations)
        socket_count = sum(row["socket_tag_present"] is True or row["socket_tag_present"] == "True" for row in stations)
        total = len(stations)
        rows.append(
            {
                "city": city,
                "region": CITIES[city]["region"],
                "station_count": total,
                "positive_power_count": positive_power,
                "positive_capacity_count": positive_capacity,
                "positive_power_or_capacity_count": sum(
                    (row["positive_power_tag"] is True or row["positive_power_tag"] == "True")
                    or (row["positive_capacity_tag"] is True or row["positive_capacity_tag"] == "True")
                    for row in stations
                ),
                "socket_tag_count": socket_count,
                "positive_power_rate": f"{positive_power / total:.6f}",
                "positive_capacity_rate": f"{positive_capacity / total:.6f}",
                "positive_power_or_capacity_rate": f"{sum((row['positive_power_tag'] is True or row['positive_power_tag'] == 'True') or (row['positive_capacity_tag'] is True or row['positive_capacity_tag'] == 'True') for row in stations) / total:.6f}",
                "socket_tag_rate": f"{socket_count / total:.6f}",
                "status": "EXTRACTED",
            }
        )
    write_csv(
        output / "station_parameter_summary.csv",
        rows,
        [
            "city",
            "region",
            "station_count",
            "positive_power_count",
            "positive_capacity_count",
            "positive_power_or_capacity_count",
            "socket_tag_count",
            "positive_power_rate",
            "positive_capacity_rate",
            "positive_power_or_capacity_rate",
            "socket_tag_rate",
            "status",
        ],
    )
    return rows


def markdown_table(headers: list[str], rows: Iterable[Iterable[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines.extend("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |" for row in rows)
    return "\n".join(lines)


def write_report(
    output: Path,
    boxes: dict[str, dict[str, Any]],
    counts: list[dict[str, Any]],
    station_rows: list[dict[str, Any]],
    shortlist_rows: list[dict[str, Any]],
    decision: dict[str, Any],
) -> None:
    count_table = markdown_table(
        ["城市", "区域", "要素", "新池状态", "新计数", "旧小地块快照", "新−旧"],
        (
            [
                row["city"],
                row["region"],
                row["feature"],
                row["new_status"],
                row["new_count"] or "—",
                row["old_count"],
                row["new_minus_old"] or "—",
            ]
            for row in counts
        ),
    )
    bbox_table = markdown_table(
        ["城市", "区域", "源节点数", "south", "west", "north", "east"],
        (
            [
                city,
                box["region"],
                box["source_node_count"],
                f"{box['south']:.8f}",
                f"{box['west']:.8f}",
                f"{box['north']:.8f}",
                f"{box['east']:.8f}",
            ]
            for city, box in sorted(boxes.items())
        ),
    )
    station_table = markdown_table(
        ["城市", "站数", "正功率标签", "正桩数标签", "功率或桩数", "socket 标签", "状态"],
        (
            [
                row["city"],
                row["station_count"] if row["status"] == "EXTRACTED" else "—",
                f"{row['positive_power_count']} ({row['positive_power_rate']})" if row["status"] == "EXTRACTED" else "—",
                f"{row['positive_capacity_count']} ({row['positive_capacity_rate']})" if row["status"] == "EXTRACTED" else "—",
                f"{row['positive_power_or_capacity_count']} ({row['positive_power_or_capacity_rate']})" if row["status"] == "EXTRACTED" else "—",
                f"{row['socket_tag_count']} ({row['socket_tag_rate']})" if row["status"] == "EXTRACTED" else "—",
                row["status"],
            ]
            for row in station_rows
        ),
    )
    shortlist_sections: list[str] = []
    for region, region_name in (("jjj", "京津冀"), ("prd", "珠三角"), ("cy", "成渝")):
        region_rows = [row for row in shortlist_rows if row["region"] == region]
        shortlist_sections.append(f"### {region_name}（{region}）\n\n" + markdown_table(
            ["名称", "OSM id", "类型", "城市", "标签摘要", "来源/状态"],
            (
                [row["name"], f"{row['osm_type']}/{row['osm_id']}", row["osm_type"], row["city_name_zh"], row["tags_summary"], row["review_status"]]
                for row in region_rows
            ),
        ))
    full_extract = all(row["new_status"] == "EXTRACTED" for row in counts)
    report = f"""# P1 九城市簇 OSM 全量池抽取与审计

输出目录：`{output.relative_to(REPO)}`  
生成时间：`{utc_now()}`  
任务边界：仅数据下载、转换和审计；搜索评价数固定为 0；不重建算例，不改 `CHINA81_DRAFT_20260717_source_bound`，不改 solver。

## 当前判决

`{decision['verdict']}`。全量新池是否完成：`{'是' if full_extract else '否'}`。

{decision['summary']}

用户规定的“Overpass 与 Geofabrik 双路均不可用超过 2 小时”停止条件：`{decision['user_two_hour_stop_condition']}`。本包另外记录了当前执行环境在 DNS/直 IP 层无法建立网络的阻断；这不能被解释成 OSM 服务端“无数据”。

## 查询框

查询框由现有 81 个 DRAFT `nodes.csv` 中每个城市锚点的实际坐标最小/最大范围推导，再向外扩 20%。边界本身是派生输入，不是新的城市行政边界。

{bbox_table}

## 九城 × 三要素计数：新池 vs 旧小地块快照

旧计数来自 `c31_3x3_osm_map_api_grid_probe_20260717` 保留的请求/响应与派生物，按旧合同复算：命名 POI 要求 `name` 或 `brand`，工业候选要求 `landuse=industrial`，充电站要求 `amenity=charging_station`。北京命名 POI 使用同一目录中 catalog 未写 `logical_anchor` 的全框原始响应，城市由 `anchor=jjj_beijing` 推导。新池只有成功保存 Overpass 原始响应后才填入计数；阻断时使用“—”，不把旧数复制成新数。

{count_table}

## 充电站参数标签覆盖率

“正功率标签”识别 `charging_station:output`、`socket:*:output`、`power` 等键中的正数；“正桩数标签”识别 `capacity`/`*:capacity` 中的正数；`socket:*` 存在率单列，不能把 socket 类型存在误写成桩数。以下比例均以新池站数为分母；未抽取城市显示“—”。

{station_table}

## 三区域车场候选短名单

名单生成时排除了废品/垃圾、墓葬、采石/矿、排水/污水、屠宰/养殖，以及印制、纺织、制药、维修等明显非物流设施。若本报告当前为环境阻断状态，名单的 `REFERENCE_ONLY_NOT_P1_NEW_POOL` 只来自旧小地块快照，供人工预审，不能替代新池验收；网络恢复并成功抽取后会由同一脚本重写为 `new_full_overpass_pool`。

{"\n\n".join(shortlist_sections)}

## 记录与复核

- 所有 Overpass 请求文本、原始响应或错误、派生池 CSV、计数表、参数覆盖率表和候选表均由 `artifact_hashes.json` 逐文件绑定 SHA-256；`._*`、`__pycache__`、`.pytest_cache` 和临时文件排除在哈希清单之外。
- 旧计数所用 catalog、查询文本和响应也作为 `legacy_source_files` 单独绑定 SHA-256；AppleDouble 清理记录见 `appledouble_cleanup.json`，只作用于本次新输出目录。
- `raw_runs.csv` 每个网络尝试保留状态、端点、请求哈希、响应/错误哈希、HTTP 状态和耗时；失败行不删除。
- 回读测试至少覆盖：计数表行数/旧数一致、查询框包含现有源坐标、SHA-256 可复算、短名单排除明显非物流设施。
- 抽取脚本不读取 solver 结果，`search_evaluations=0`。

## HALT / 未完成项

{decision['halt_markdown']}
"""
    (output / "report.md").write_text(report, encoding="utf-8")


def hash_artifacts(output: Path, external_paths: list[Path]) -> dict[str, Any]:
    files: dict[str, str] = {}
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.name == "artifact_hashes.json" or path.name.startswith("._"):
            continue
        if any(part in {"__pycache__", ".pytest_cache"} for part in path.parts):
            continue
        files[str(path.relative_to(REPO))] = sha256_path(path)
    external: dict[str, str] = {}
    for path in external_paths:
        if path.exists():
            external[str(path.relative_to(REPO))] = sha256_path(path)
    legacy = {entry["path"]: entry["sha256"] for entry in legacy_source_evidence()}
    payload = {
        "schema": "resetp.china9.full-pool.artifact-hashes.v1",
        "hash_algorithm": "SHA-256",
        "excluded_self": "artifact_hashes.json is excluded from its own hash list",
        "excluded_patterns": ["._*", "__pycache__", ".pytest_cache", "temporary checkpoints"],
        "appledouble_policy": "AppleDouble sidecars are removed from this output before the final manifest is written",
        "files": files,
        "external_code_files": external,
        "legacy_source_files": legacy,
    }
    write_json(output / "artifact_hashes.json", payload)
    return payload


def write_metadata(output: Path, args: argparse.Namespace, boxes: dict[str, dict[str, Any]], status: str) -> None:
    write_json(
        output / "metadata.json",
        {
            "schema": "resetp.china9.full-pool.metadata.v1",
            "task": "P1 China nine-city full OSM pool extraction",
            "output_date_label": "20260718",
            "generated_utc": utc_now(),
            "git": git_fingerprint(),
            "cities": CITIES,
            "features": FEATURES,
            "bbox_rule": "min/max coordinates actually used by current CHINA81 DRAFT nodes per city, expanded by 20 percent",
            "query_boxes": boxes,
            "source_policy": {
                "primary": "Overpass API nwr queries",
                "fallback": "necessary Geofabrik provincial PBF plus local filtering only if Overpass repeatedly fails",
                "prohibited": ["Gaode", "Baidu", "synthetic coordinates", "optimisation search", "instance rebuild"],
            },
            "concurrency": {"max_workers": min(int(args.workers), 2), "process_or_thread_bound": "at most two network workers"},
            "disk_budget_gb": 5,
            "network_mode": args.mode,
            "status": status,
            "search_evaluations": 0,
            "legacy_source_evidence": legacy_source_evidence(),
            "appledouble_policy": "clean sidecars under this new output before final hashing; never touch old snapshot directories",
            "protected_surfaces": [
                "data/ChinaInstances/CHINA81_DRAFT_20260717_source_bound",
                "solver/src/setp_solver/cost.py",
                "solver/src/setp_solver/check.py",
                "solver/src/setp_solver/search/evaluation.py",
            ],
        },
    )


def run(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    removed_at_start = clean_appledouble(output)
    boxes = city_boxes()
    write_json(output / "query_boxes.json", boxes)
    write_csv(
        output / "city_query_boxes.csv",
        boxes.values(),
        [
            "city",
            "region",
            "name_zh",
            "source_node_count",
            "source_file_count",
            "source_lat_min",
            "source_lat_max",
            "source_lon_min",
            "source_lon_max",
            "expansion_fraction",
            "south",
            "west",
            "north",
            "east",
            "source_files",
        ],
    )
    old_rows, old_items = legacy_counts()
    write_csv(
        output / "old_snapshot_counts.csv",
        old_rows,
        ["city", "region", "feature", "old_count", "old_source", "old_definition"],
    )
    runs: list[dict[str, Any]] = []
    pool_rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
    if args.mode == "offline-audit":
        runs.extend(environment_probe_files(output))
        shortlist_rows = legacy_shortlist(old_items, output)
        status = "HALT_ENV_NETWORK_EGRESS_UNAVAILABLE"
        summary = "本次未能向 Overpass 或 Geofabrik 建立可保存原始字节的网络连接；只完成边界、旧池复算和可恢复抽取器现场。"
        halt_markdown = (
            "**环境阻断：** shell DNS 无法解析 Overpass/Geofabrik，直连 1.1.1.1 也失败，浏览器 MCP 调用被当前会话拒绝；本次没有新池计数。"
            "\n\n**未触发的用户服务停止条件：** 当前证据是本机网络出口阻断，不是已观察满 2 小时的 Overpass/Geofabrik 服务不可用。"
        )
    else:
        existing_runs_path = output / "raw_runs.csv"
        if existing_runs_path.exists():
            runs.extend(read_csv(existing_runs_path))
        done = {(row["city"], row["feature"]) for row in runs if row.get("status") == "success"}
        tasks = [(city, feature) for city in sorted(CITIES) for feature in FEATURES if (city, feature) not in done]
        with ThreadPoolExecutor(max_workers=min(max(args.workers, 1), 2)) as executor:
            futures = {
                executor.submit(fetch_one, city, feature, boxes[city], output, tuple(args.endpoint), args.retries, args.timeout): (city, feature)
                for city, feature in tasks
            }
            for future in as_completed(futures):
                runs.append(future.result())
        for city in sorted(CITIES):
            for feature in FEATURES:
                successful = [row for row in runs if row["city"] == city and row["feature"] == feature and row.get("status") == "success"]
                if successful:
                    pool_rows[(city, feature)] = materialize_pool(city, feature, boxes[city], successful[0], output)
        if pool_rows and len(pool_rows) == len(CITIES) * len(FEATURES):
            shortlist_rows = new_shortlist(output, pool_rows)
            status = "PASS_P1_FULL_POOL_EXTRACTED"
            summary = "九城三要素均已成功保存 Overpass 原始响应并生成去重派生池；请按短名单完成人工车场终审。"
            halt_markdown = "无网络 HALT。若某城市站数为 0，计数表和参数表会保留 0 并要求用户裁决。"
        else:
            shortlist_rows = legacy_shortlist(old_items, output)
            status = "HALT_P1_INCOMPLETE_NETWORK_EXTRACTION"
            summary = "只有成功保存原始响应的城市/要素才生成新池；其余项保留失败行，不用旧计数填充。"
            halt_markdown = "**P1 未闭合：** 至少一个城市/要素未获得可复核的新原始响应；请恢复网络后用同一输出目录续跑。"
    write_csv(output / "raw_runs.csv", sorted(runs, key=lambda row: str(row["run_id"])), RUN_FIELDS)
    counts = write_counts(output, boxes, old_rows, pool_rows, runs)
    station_rows = write_station_summary(output, pool_rows, runs)
    zero_station_cities = [row["city"] for row in station_rows if row["status"] == "EXTRACTED" and int(row["station_count"]) == 0]
    decision = {
        "schema": "resetp.china9.full-pool.decision.v1",
        "verdict": status,
        "summary": summary,
        "generated_utc": utc_now(),
        "search_evaluations": 0,
        "user_two_hour_stop_condition": "NOT_TRIGGERED: current failure is local network egress/DNS, not a two-hour service observation",
        "zero_station_cities": zero_station_cities,
        "blocking_conditions": [] if status == "PASS_P1_FULL_POOL_EXTRACTED" else ["network ingress unavailable or one or more Overpass requests failed"],
        "next_action": "human review of candidate shortlist, then separate P4 decision" if status == "PASS_P1_FULL_POOL_EXTRACTED" else "restore network access and rerun the same script; do not rebuild instances",
        "halt_markdown": halt_markdown,
    }
    write_json(output / "decision.json", decision)
    write_metadata(output, args, boxes, status)
    write_report(output, boxes, counts, station_rows, shortlist_rows, decision)
    removed_before_hash = clean_appledouble(output)
    write_json(
        output / "appledouble_cleanup.json",
        {
            "schema": "resetp.china9.full-pool.appledouble-cleanup.v1",
            "policy": "remove macOS AppleDouble sidecars under this new output before final hashing",
            "removed_at_run_start": removed_at_start,
            "removed_before_final_hash": removed_before_hash,
            "final_sweep_after_manifest": True,
            "old_snapshot_directories_touched": False,
        },
    )
    clean_appledouble(output)
    hash_artifacts(output, [Path(__file__), REPO / "baselines/china_instances/test_extract_china9_full_pool_20260718.py"])
    clean_appledouble(output)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("offline-audit", "overpass"), default="overpass")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--endpoint", action="append", default=list(DEFAULT_ENDPOINTS))
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
