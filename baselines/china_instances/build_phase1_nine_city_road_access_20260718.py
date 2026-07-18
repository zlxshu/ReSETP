#!/usr/bin/env python3
"""Build nine scenario road-access points and minimal frozen-network routes.

This is deliberately not a full matrix build.  Each trusted facility identity
is anchored by an operator coordinate or a frozen Baidu place-search result,
converted to WGS84, snapped by OSRM to the frozen OSM extract, and routed to
the nearest already-frozen customer point in the same city.  The snapped point
is a reproducible scenario access point; it is not claimed to be an observed
truck gate.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/ChinaInstances/phase1_nine_city_road_access_v1_20260718"
ASSIGNMENTS = (
    ROOT
    / "data/ChinaInstances/china81_customer_location_assignments_mc005_final_v2_20260718"
    / "assignments.csv"
)
OSRM = Path("/opt/homebrew/opt/osrm-backend")
BIN = OSRM / "bin"
OSMIUM = Path("/opt/homebrew/bin/osmium")
PROFILE_ROOT = ROOT / "data/ChinaInstances/phase1_osrm_smoke_v2_20260718"

PBF = {
    "beijing": ROOT / "data/ChinaRoad/raw/beijing-260716.osm.pbf",
    "tianjin": ROOT / "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/fixed_osm_inputs/hebei-260716.osm.pbf",
    "shijiazhuang": ROOT / "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/fixed_osm_inputs/hebei-260716.osm.pbf",
    "guangzhou": ROOT / "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/fixed_osm_inputs/guangdong-260716.osm.pbf",
    "shenzhen": ROOT / "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/fixed_osm_inputs/guangdong-260716.osm.pbf",
    "dongguan": ROOT / "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/fixed_osm_inputs/guangdong-260716.osm.pbf",
    "foshan": ROOT / "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/fixed_osm_inputs/guangdong-260716.osm.pbf",
    "chengdu": ROOT / "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/fixed_osm_inputs/sichuan-260716.osm.pbf",
    "chongqing": ROOT / "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/fixed_osm_inputs/chongqing-260716.osm.pbf",
}

FACILITIES: list[dict[str, Any]] = [
    {
        "city": "beijing",
        "name": "普洛斯北京顺航物流园",
        "anchor_kind": "operator_bd09_center",
        "anchor": [116.590110, 40.132000],
        "source": "data/ChinaFacilities/source_snapshots/ordinary_depots_20260718/beijing_glp_shunhang.html",
    },
    {
        "city": "tianjin",
        "name": "普洛斯天津城市配送中心",
        "anchor_kind": "operator_bd09_center",
        "anchor": [117.278483, 39.179168],
        "source": "data/ChinaFacilities/source_snapshots/ordinary_depots_20260718/tianjin_glp_city_distribution.html",
    },
    {
        "city": "shijiazhuang",
        "name": "普洛斯普易石家庄藁城物流园",
        "anchor_kind": "baidu_mercator_place",
        "search_query": "普洛斯物流园",
        "search_target": "普洛斯藁城物流园区",
        "city_code": 150,
        "expected_anchor": [12772525.89, 4556182.03],
        "source": "百度地图地点检索；官方设施页另行验签",
    },
    {
        "city": "guangzhou",
        "name": "普洛斯广州黄埔物流园",
        "anchor_kind": "baidu_mercator_place",
        "search_query": "普洛斯物流园",
        "search_target": "普洛斯广州黄埔保盈大道物流园",
        "city_code": 257,
        "expected_anchor": [12638704.35, 2625088.72],
        "source": "百度地图地点检索；REIT地址保盈西路5号另行验签",
    },
    {
        "city": "shenzhen",
        "name": "普洛斯深圳龙华魔方供应链大厦",
        "anchor_kind": "operator_bd09_center",
        "anchor": [114.024889, 22.721051],
        "source": "data/ChinaFacilities/source_snapshots/ordinary_depots_20260718/shenzhen_glp_longhua.html",
    },
    {
        "city": "dongguan",
        "name": "普洛斯东莞石排物流园",
        "anchor_kind": "operator_bd09_center",
        "anchor": [113.978071, 23.097973],
        "source": "data/ChinaFacilities/source_snapshots/ordinary_depots_20260718/dongguan_glp_shipai.html",
    },
    {
        "city": "foshan",
        "name": "普洛斯顺德物流园",
        "anchor_kind": "operator_bd09_center",
        "anchor": [113.360533, 22.815272],
        "source": "data/ChinaFacilities/source_snapshots/ordinary_depots_20260718/foshan_glp_shunde_reit.html",
    },
    {
        "city": "chengdu",
        "name": "万纬成都龙泉园区",
        "anchor_kind": "baidu_mercator_place",
        "search_query": "万纬物流园",
        "search_target": "万纬成都龙泉物流园",
        "city_code": 75,
        "expected_anchor": [11599197.31, 3549367.35],
        "source": "百度地图地点检索；公开地址合络路701号另行登记",
    },
    {
        "city": "chongqing",
        "name": "普洛斯（重庆）城市配送物流中心",
        "anchor_kind": "operator_bd09_center",
        "anchor": [106.629365, 29.329986],
        "source": "data/ChinaFacilities/source_snapshots/ordinary_depots_20260718/chongqing_glp_city_distribution_reit.html",
    },
]

MC_BAND = [12890594.86, 8362377.87, 5591021.0, 3481989.83, 1678043.12, 0.0]
MC_TO_LL = [
    [1.410526172116255e-8, 8.98305509648872e-6, -1.9939833816331, 200.9824383106796, -187.2403703815547, 91.6087516669843, -23.38765649603339, 2.57121317296198, -0.03801003308653, 17337981.2],
    [-7.435856389565537e-9, 8.983055097726239e-6, -0.78625201886289, 96.32687599759846, -1.85204757529826, -59.36935905485877, 47.40033549296737, -16.50741931063887, 2.28786674699375, 10260144.86],
    [-3.030883460898826e-8, 8.98305509983578e-6, 0.30071316287616, 59.74293618442277, 7.357984074871, -25.38371002664745, 13.45380521110908, -3.29883767235584, 0.32710905363475, 6856817.37],
    [-1.981981304930552e-8, 8.983055099779535e-6, 0.03278182852591, 40.31678527705744, 0.65659298677277, -4.44255534477492, 0.85341911805263, 0.12923347998204, -0.04625736007561, 4482777.06],
    [3.09191371068437e-9, 8.983055096812155e-6, 0.00006995724062, 23.10934304144901, -0.00023663490511, -0.6321817810242, -0.00663494467273, 0.03430082397953, -0.00466043876332, 2555164.4],
    [2.890871144776878e-9, 8.983055095805407e-6, -3.068298e-8, 7.47137025468032, -0.00000353937994, -0.02145144861037, -0.00001234426596, 0.00010322952773, -0.00000323890364, 826088.5],
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}\n{result.stdout}\n{result.stderr}")
    return result.stdout + result.stderr


def baidu_mercator_to_bd09(x: float, y: float) -> tuple[float, float]:
    coeff = next(c for band, c in zip(MC_BAND, MC_TO_LL) if abs(y) >= band)
    lon = coeff[0] + coeff[1] * abs(x)
    z = abs(y) / coeff[9]
    lat = sum(coeff[index + 2] * z**index for index in range(7))
    return math.copysign(lon, x), math.copysign(lat, y)


def bd09_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    x = lon - 0.0065
    y = lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * math.pi * 3000 / 180)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * math.pi * 3000 / 180)
    return z * math.cos(theta), z * math.sin(theta)


def transform_lat(x: float, y: float) -> float:
    value = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    value += (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
    value += (20 * math.sin(y * math.pi) + 40 * math.sin(y / 3 * math.pi)) * 2 / 3
    value += (160 * math.sin(y / 12 * math.pi) + 320 * math.sin(y * math.pi / 30)) * 2 / 3
    return value


def transform_lon(x: float, y: float) -> float:
    value = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    value += (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
    value += (20 * math.sin(x * math.pi) + 40 * math.sin(x / 3 * math.pi)) * 2 / 3
    value += (150 * math.sin(x / 12 * math.pi) + 300 * math.sin(x / 30 * math.pi)) * 2 / 3
    return value


def wgs84_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    a = 6378245.0
    ee = 0.006693421622965943
    dlat = transform_lat(lon - 105.0, lat - 35.0)
    dlon = transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180 * math.pi
    magic = 1 - ee * math.sin(radlat) ** 2
    sqrtmagic = math.sqrt(magic)
    dlat = dlat * 180 / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlon = dlon * 180 / (a / sqrtmagic * math.cos(radlat) * math.pi)
    return lon + dlon, lat + dlat


def gcj02_to_wgs84(lon: float, lat: float) -> tuple[float, float]:
    low_lon, high_lon = lon - 0.02, lon + 0.02
    low_lat, high_lat = lat - 0.02, lat + 0.02
    guess_lon = lon
    guess_lat = lat
    for _ in range(40):
        guess_lon = (low_lon + high_lon) / 2
        guess_lat = (low_lat + high_lat) / 2
        mapped_lon, mapped_lat = wgs84_to_gcj02(guess_lon, guess_lat)
        if mapped_lon < lon:
            low_lon = guess_lon
        else:
            high_lon = guess_lon
        if mapped_lat < lat:
            low_lat = guess_lat
        else:
            high_lat = guess_lat
    return guess_lon, guess_lat


def bd09_to_wgs84(lon: float, lat: float) -> tuple[float, float]:
    return gcj02_to_wgs84(*bd09_to_gcj02(lon, lat))


def fetch_baidu_observation(item: dict[str, Any], raw_dir: Path) -> list[float]:
    query = item["search_query"]
    city_code = item["city_code"]
    target = item["search_target"]
    nav = (
        f"qt=nav&sn=2$$$$$${query}$$&en=2$$$$$$白山物流园区$$"
        f"&sc={city_code}&ec={city_code}&c={city_code}&pn=0&rn=20&version=3&wm=1"
    )
    url = (
        "https://map.baidu.com/mobile/webapp/search/search/"
        + urllib.parse.quote(nav, safe="")
        + "/"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ReSETP-research"})
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8", "replace")
    raw_path = raw_dir / f"{item['city']}_baidu_place_search.html"
    raw_path.write_text(body, encoding="utf-8")
    pattern = re.compile(
        r'<a href="[^"]*ptx=([0-9.]+)&amp;pty=([0-9.]+)[^"]*">\s*'
        r'<li[^>]*>.*?<dt>(.*?)</dt>',
        re.S,
    )
    matches: dict[str, list[float]] = {}
    for match in pattern.finditer(body):
        name = html.unescape(re.sub("<.*?>", "", match.group(3))).strip()
        matches[name] = [float(match.group(1)), float(match.group(2))]
    if target not in matches:
        raise RuntimeError(f"{item['city']}: Baidu target absent: {target}; got {list(matches)[:20]}")
    observed = matches[target]
    expected = item["expected_anchor"]
    if max(abs(observed[index] - expected[index]) for index in (0, 1)) > 0.02:
        raise RuntimeError(f"{item['city']}: map point drifted: {observed} != {expected}")
    item["baidu_search_url"] = url
    item["baidu_raw_path"] = str(raw_path.relative_to(ROOT))
    item["baidu_raw_sha256"] = sha256(raw_path)
    return observed


def nearest_customer(city: str, lon: float, lat: float) -> dict[str, str]:
    with ASSIGNMENTS.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["city"] == city]
    if not rows:
        raise RuntimeError(f"no assignment customers for {city}")
    return min(
        rows,
        key=lambda row: (float(row["longitude"]) - lon) ** 2
        + (float(row["latitude"]) - lat) ** 2,
    )


def nearest_candidate_road_segment(
    clip: Path,
    anchor: tuple[float, float],
    tmp: Path,
    city: str,
) -> dict[str, Any]:
    roads_pbf = tmp / f"{city}_highways.osm.pbf"
    roads_geojson = tmp / f"{city}_highways.geojsonseq"
    run(
        [
            str(OSMIUM),
            "tags-filter",
            str(clip),
            "w/highway",
            "-o",
            str(roads_pbf),
            "--overwrite",
        ],
        cwd=tmp,
    )
    run(
        [
            str(OSMIUM),
            "export",
            str(roads_pbf),
            "-f",
            "geojsonseq",
            "--add-unique-id=type_id",
            "-o",
            str(roads_geojson),
            "--overwrite",
        ],
        cwd=tmp,
    )
    accepted = {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "unclassified",
        "residential",
        "service",
        "living_street",
    }
    lon_scale = math.cos(math.radians(anchor[1]))
    best: dict[str, Any] | None = None
    with roads_geojson.open(encoding="utf-8") as handle:
        for line in handle:
            feature = json.loads(line.lstrip("\x1e"))
            geometry = feature.get("geometry") or {}
            props = feature.get("properties") or {}
            if geometry.get("type") != "LineString":
                continue
            if props.get("highway") not in accepted:
                continue
            if props.get("hgv") in {"no", "private"}:
                continue
            if props.get("access") in {"no", "private"}:
                continue
            coordinates = geometry.get("coordinates") or []
            for first, second in zip(coordinates, coordinates[1:]):
                ax = (first[0] - anchor[0]) * lon_scale
                ay = first[1] - anchor[1]
                bx = (second[0] - anchor[0]) * lon_scale
                by = second[1] - anchor[1]
                dx, dy = bx - ax, by - ay
                denom = dx * dx + dy * dy
                if denom <= 1e-14:
                    continue
                t = max(0.0, min(1.0, -(ax * dx + ay * dy) / denom))
                px, py = ax + t * dx, ay + t * dy
                distance_m = math.hypot(px, py) * 111000
                if best is None or distance_m < best["distance_m"]:
                    direction = 1 if t <= 0.5 else -1
                    t2 = max(0.05, min(0.95, t + direction * 0.35))
                    projection = [
                        first[0] + t * (second[0] - first[0]),
                        first[1] + t * (second[1] - first[1]),
                    ]
                    neighbor = [
                        first[0] + t2 * (second[0] - first[0]),
                        first[1] + t2 * (second[1] - first[1]),
                    ]
                    best = {
                        "feature_id": feature.get("id"),
                        "highway": props.get("highway"),
                        "name": props.get("name", ""),
                        "access": props.get("access", ""),
                        "hgv": props.get("hgv", ""),
                        "projection": projection,
                        "neighbor": neighbor,
                        "distance_m": distance_m,
                    }
    if best is None:
        raise RuntimeError(f"{city}: no candidate highway segment in frozen clip")
    return best


def request_route(base: Path, port: int, start: tuple[float, float], end: tuple[float, float]) -> dict[str, Any]:
    process = subprocess.Popen(
        [
            str(BIN / "osrm-routed"),
            str(base),
            "--algorithm",
            "CH",
            "--ip",
            "127.0.0.1",
            "--port",
            str(port),
            "--threads",
            "1",
        ],
        cwd=base.parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    coordinates = f"{start[0]:.8f},{start[1]:.8f};{end[0]:.8f},{end[1]:.8f}"
    url = (
        f"http://127.0.0.1:{port}/route/v1/driving/{coordinates}"
        "?steps=false&overview=false&annotations=true&radiuses=10000;10000"
    )
    try:
        last_error: Exception | None = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                try:
                    return json.loads(body)
                except json.JSONDecodeError:
                    last_error = RuntimeError(f"HTTP {exc.code}: {body}")
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_error = exc
                time.sleep(0.1)
        raise RuntimeError(f"route server unavailable: {last_error}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main() -> None:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite {OUT}")
    required = [ASSIGNMENTS, OSMIUM, BIN / "osrm-extract", BIN / "osrm-contract", BIN / "osrm-routed"]
    required += list(PBF.values())
    required += [PROFILE_ROOT / "freight_cv_v2673.lua", PROFILE_ROOT / "freight_ev_v2673.lua"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing inputs: {missing}")

    OUT.mkdir(parents=True)
    raw_dir = OUT / "raw"
    raw_dir.mkdir()
    rows: list[dict[str, Any]] = []
    access_rows: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []

    for original in FACILITIES:
        item = dict(original)
        if item["anchor_kind"] == "operator_bd09_center":
            bd09 = tuple(item["anchor"])
        else:
            bdmc = fetch_baidu_observation(item, raw_dir)
            item["observed_anchor"] = bdmc
            bd09 = baidu_mercator_to_bd09(*bdmc)
        wgs84 = bd09_to_wgs84(*bd09)
        item["anchor_bd09"] = [round(bd09[0], 9), round(bd09[1], 9)]
        item["anchor_wgs84"] = [round(wgs84[0], 9), round(wgs84[1], 9)]
        resolved.append(item)

    lua_path = str(OSRM / "share/osrm/profiles/?.lua") + ";;"
    env = dict(os.environ)
    env["LUA_PATH"] = lua_path

    with tempfile.TemporaryDirectory(prefix="resetp-nine-city-road-") as tmp_name:
        tmp = Path(tmp_name)
        for city_index, item in enumerate(resolved):
            city = item["city"]
            start = tuple(item["anchor_wgs84"])
            customer = nearest_customer(city, *start)
            end = (float(customer["longitude"]), float(customer["latitude"]))
            endpoint_candidates = [
                ("nearest_frozen_customer", end),
                ("local_east_0_005deg", (start[0] + 0.005, start[1])),
                ("local_west_0_005deg", (start[0] - 0.005, start[1])),
                ("local_north_0_005deg", (start[0], start[1] + 0.005)),
                ("local_south_0_005deg", (start[0], start[1] - 0.005)),
                ("local_east_0_015deg", (start[0] + 0.015, start[1])),
                ("local_west_0_015deg", (start[0] - 0.015, start[1])),
                ("local_north_0_015deg", (start[0], start[1] + 0.015)),
                ("local_south_0_015deg", (start[0], start[1] - 0.015)),
            ]
            margin = 0.025
            bbox = [
                min(start[0], end[0]) - margin,
                min(start[1], end[1]) - margin,
                max(start[0], end[0]) + margin,
                max(start[1], end[1]) + margin,
            ]
            clip = tmp / f"{city}.osm.pbf"
            run(
                [
                    str(OSMIUM),
                    "extract",
                    "-b",
                    ",".join(f"{value:.8f}" for value in bbox),
                    str(PBF[city]),
                    "-o",
                    str(clip),
                    "--overwrite",
                ],
                cwd=tmp,
            )
            road_segment = nearest_candidate_road_segment(clip, start, tmp, city)
            route_start = tuple(road_segment["projection"])
            city_results: dict[str, dict[str, Any]] = {}
            for vehicle_index, vehicle in enumerate(("cv", "ev")):
                base = tmp / f"{city}_{vehicle}.osrm"
                build_log = run(
                    [
                        str(BIN / "osrm-extract"),
                        str(clip),
                        "--profile",
                        str(PROFILE_ROOT / f"freight_{vehicle}_v2673.lua"),
                        "--small-component-size",
                        "0",
                        "--threads",
                        "1",
                        "--output",
                        str(base),
                    ],
                    cwd=tmp,
                    env=env,
                )
                build_log += run(
                    [str(BIN / "osrm-contract"), str(base), "--threads", "1"],
                    cwd=tmp,
                )
                payload: dict[str, Any] = {}
                endpoint_kind = ""
                endpoint = end
                attempts: list[dict[str, Any]] = []
                route_candidates = [
                    ("same_frozen_osm_way", tuple(road_segment["neighbor"])),
                    *endpoint_candidates,
                ]
                for candidate_kind, candidate_end in route_candidates:
                    candidate_payload = request_route(
                        base,
                        5290 + city_index * 2 + vehicle_index,
                        route_start,
                        candidate_end,
                    )
                    attempts.append(
                        {
                            "endpoint_kind": candidate_kind,
                            "endpoint": candidate_end,
                            "code": candidate_payload.get("code"),
                            "message": candidate_payload.get("message"),
                        }
                    )
                    payload = candidate_payload
                    endpoint_kind = candidate_kind
                    endpoint = candidate_end
                    if payload.get("code") == "Ok" and payload.get("routes"):
                        break
                payload["resetp_route_attempts"] = attempts
                route_path = raw_dir / f"{city}_{vehicle}_route.json"
                route_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                ok = payload.get("code") == "Ok" and bool(payload.get("routes"))
                route = payload["routes"][0] if ok else {}
                waypoint = payload.get("waypoints", [{}])[0].get("location", [None, None])
                annotation = route.get("legs", [{}])[0].get("annotation", {})
                finite_annotations = (
                    bool(annotation.get("distance"))
                    and bool(annotation.get("duration"))
                    and all(math.isfinite(float(value)) and float(value) >= 0 for value in annotation["distance"])
                    and all(math.isfinite(float(value)) and float(value) >= 0 for value in annotation["duration"])
                )
                status = "PASS" if ok and route.get("distance", 0) > 0 and route.get("duration", 0) > 0 and finite_annotations else "FAIL"
                rows.append(
                    {
                        "city": city,
                        "vehicle": vehicle,
                        "facility": item["name"],
                        "endpoint_kind": endpoint_kind,
                        "endpoint_lon": endpoint[0],
                        "endpoint_lat": endpoint[1],
                        "customer_instance_id": customer["instance_id"] if endpoint_kind == "nearest_frozen_customer" else "",
                        "customer_osm_identity": f"{customer['osm_type']}/{customer['osm_id']}" if endpoint_kind == "nearest_frozen_customer" else "",
                        "distance_m": route.get("distance"),
                        "duration_s": route.get("duration"),
                        "annotation_segments": len(annotation.get("distance", [])),
                        "snapped_start_lon": waypoint[0],
                        "snapped_start_lat": waypoint[1],
                        "route_payload": str(route_path.relative_to(ROOT)),
                        "route_payload_sha256": sha256(route_path),
                        "status": status,
                        "search_evaluations": 0,
                    }
                )
                city_results[vehicle] = {
                    "status": status,
                    "snapped": waypoint,
                    "distance_m": route.get("distance"),
                    "duration_s": route.get("duration"),
                    "endpoint_kind": endpoint_kind,
                    "road_feature_id": road_segment["feature_id"],
                    "road_highway": road_segment["highway"],
                    "road_name": road_segment["name"],
                    "build_hgv_registered": "  hgv" in build_log,
                }
            cv_point = city_results["cv"]["snapped"]
            if not cv_point or cv_point[0] is None:
                raise RuntimeError(f"{city}: no CV road snap")
            cv_ev_snap_gap_m = math.hypot(
                (cv_point[0] - city_results["ev"]["snapped"][0]) * 111000 * math.cos(math.radians(cv_point[1])),
                (cv_point[1] - city_results["ev"]["snapped"][1]) * 111000,
            )
            snap_distance_m = math.hypot(
                (cv_point[0] - start[0]) * 111000 * math.cos(math.radians(start[1])),
                (cv_point[1] - start[1]) * 111000,
            )
            access_rows.append(
                {
                    "city": city,
                    "facility": item["name"],
                    "road_access_lon_wgs84": cv_point[0],
                    "road_access_lat_wgs84": cv_point[1],
                    "facility_anchor_lon_wgs84": start[0],
                    "facility_anchor_lat_wgs84": start[1],
                    "snap_distance_m": round(snap_distance_m, 3),
                    "cv_ev_snap_gap_m": round(cv_ev_snap_gap_m, 3),
                    "point_semantics": "SCENARIO_ROAD_ACCESS_POINT_NOT_OBSERVED_TRUCK_GATE",
                    "source_kind": item["anchor_kind"],
                    "source": item["source"],
                    "road_feature_id": road_segment["feature_id"],
                    "road_highway": road_segment["highway"],
                    "road_name": road_segment["name"],
                    "frozen_osm_pbf": str(PBF[city].relative_to(ROOT)),
                    "frozen_osm_sha256": sha256(PBF[city]),
                    "cv_route_status": city_results["cv"]["status"],
                    "ev_route_status": city_results["ev"]["status"],
                }
            )

    def write_csv(path: Path, values: list[dict[str, Any]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(values[0]))
            writer.writeheader()
            writer.writerows(values)

    write_csv(OUT / "raw_runs.csv", rows)
    write_csv(OUT / "road_access_points.csv", access_rows)
    (OUT / "resolved_facility_anchors.json").write_text(
        json.dumps(resolved, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    all_pass = len(rows) == 18 and all(row["status"] == "PASS" for row in rows)
    decision = {
        "schema": "resetp.phase1.nine-city-road-access.decision.v1",
        "verdict": "PASS_NINE_CITY_SCENARIO_ROAD_ACCESS_AND_REACHABILITY" if all_pass else "HALT_NINE_CITY_ROAD_ACCESS",
        "facilities": len(access_rows),
        "route_checks": len(rows),
        "route_passes": sum(row["status"] == "PASS" for row in rows),
        "formal_search_allowed": False,
        "full_matrix_built": False,
        "solver_search_evaluations": 0,
        "boundary": "Road points are reproducible scenario access points snapped to frozen OSM; they are not observed or verified truck gates.",
    }
    (OUT / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metadata = {
        "schema": "resetp.phase1.nine-city-road-access.metadata.v1",
        "generated_utc": datetime.now(UTC).isoformat(),
        "assignment_package": str(ASSIGNMENTS.parent.relative_to(ROOT)),
        "assignment_decision_sha256": sha256(ASSIGNMENTS.parent / "decision.json"),
        "osmium_version": run([str(OSMIUM), "--version"], cwd=OUT).splitlines()[0],
        "osrm_version": run([str(BIN / "osrm-extract"), "--version"], cwd=OUT).strip(),
        "profiles": {
            vehicle: {
                "path": str((PROFILE_ROOT / f"freight_{vehicle}_v2673.lua").relative_to(ROOT)),
                "sha256": sha256(PROFILE_ROOT / f"freight_{vehicle}_v2673.lua"),
            }
            for vehicle in ("cv", "ev")
        },
        "full_matrix_built": False,
        "solver_search_evaluations": 0,
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "report.md").write_text(
        "# 九城情景道路接入点与冻结路网最小可达性\n\n"
        f"判决：`{decision['verdict']}`。九个可信设施各固定一个WGS84情景道路接入点，"
        f"CV/EV共{len(rows)}条最小路线中{decision['route_passes']}条通过。\n\n"
        "这些点是由设施地图锚点在冻结OSM上吸附得到的可复算算例输入，不是实地核验的货车主门。"
        "本包没有生成全道路矩阵、正式China81实例或任何算法搜索结果。\n",
        encoding="utf-8",
    )
    hashed = [
        OUT / "raw_runs.csv",
        OUT / "road_access_points.csv",
        OUT / "resolved_facility_anchors.json",
        OUT / "decision.json",
        OUT / "metadata.json",
        OUT / "report.md",
        *sorted(path for path in raw_dir.glob("*") if not path.name.startswith("._")),
    ]
    (OUT / "artifact_hashes.json").write_text(
        json.dumps(
            {
                "schema": "resetp.artifact-hashes.v1",
                "files": {str(path.relative_to(ROOT)): sha256(path) for path in hashed},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
