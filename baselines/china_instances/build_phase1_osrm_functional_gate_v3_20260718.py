#!/usr/bin/env python3
"""Run the minimal complete OSRM freight-profile functional gate.

The synthetic fixture tests the rules required before China matrix generation:
height, width, length, weight, hgv access, oneway direction, unreachable pairs,
directed distance/duration, annotations, and the ability to compute sum(v^2 d).
It performs no solver search and builds no province graph or full matrix.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/ChinaInstances/phase1_osrm_functional_gate_v3_20260718"
OSRM = Path("/opt/homebrew/opt/osrm-backend")
BIN = OSRM / "bin"
PROFILE_ROOT = ROOT / "data/ChinaInstances/phase1_osrm_smoke_v2_20260718"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}\n{result.stdout}\n{result.stderr}")
    return result.stdout + result.stderr


def build_fixture() -> tuple[str, dict[str, tuple[tuple[float, float], tuple[float, float]]]]:
    nodes: list[str] = []
    ways: list[str] = []
    queries: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {}
    node_id = 1
    way_id = 100

    def node(lon: float, lat: float) -> int:
        nonlocal node_id
        value = node_id
        node_id += 1
        nodes.append(f'  <node id="{value}" lon="{lon:.6f}" lat="{lat:.6f}" version="1"/>')
        return value

    def way(refs: list[int], name: str, tags: dict[str, str]) -> None:
        nonlocal way_id
        tag_text = "".join(f'<tag k="{key}" v="{value}"/>' for key, value in tags.items())
        ref_text = "".join(f'<nd ref="{ref}"/>' for ref in refs)
        ways.append(f'  <way id="{way_id}" version="1">{ref_text}<tag k="highway" v="primary"/><tag k="name" v="{name}"/><tag k="maxspeed" v="50"/>{tag_text}</way>')
        way_id += 1

    restrictions = [
        ("height", {"maxheight": "3.0"}),
        ("width", {"maxwidth": "2.1"}),
        ("length", {"maxlength": "5.5"}),
        ("weight", {"maxweight": "4.0"}),
        ("hgv_access", {"hgv": "no"}),
    ]
    for index, (label, tags) in enumerate(restrictions):
        y = index * 0.020
        start = (0.000, y)
        end = (0.004, y)
        a = node(*start)
        b = node(0.002, y)
        c = node(*end)
        d = node(0.000, y + 0.004)
        e = node(0.004, y + 0.004)
        way([a, b, c], f"{label}_restricted_direct", tags)
        way([a, d, e, c], f"{label}_unrestricted_detour", {})
        queries[label] = (start, end)

    y = 0.120
    a = node(0.000, y)
    b = node(0.002, y)
    c = node(0.004, y)
    d = node(0.000, y + 0.004)
    e = node(0.004, y + 0.004)
    way([a, b, c], "oneway_direct", {"oneway": "yes"})
    way([a, d, e, c], "oneway_reverse_detour", {})
    queries["oneway_forward"] = ((0.000, y), (0.004, y))
    queries["oneway_reverse"] = ((0.004, y), (0.000, y))

    y = 0.160
    a = node(0.000, y)
    b = node(0.004, y)
    c = node(0.020, y)
    d = node(0.024, y)
    way([a, b], "reachable_component_a", {})
    way([c, d], "disconnected_component_b", {})
    queries["reachable"] = ((0.000, y), (0.004, y))
    queries["unreachable"] = ((0.000, y), (0.020, y))

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<osm version="0.6" generator="ReSETP phase1 functional gate">\n'
        + "\n".join(nodes)
        + "\n"
        + "\n".join(ways)
        + "\n</osm>\n"
    )
    return xml, queries


def request(port: int, start: tuple[float, float], end: tuple[float, float]) -> dict[str, Any]:
    url = (
        f"http://127.0.0.1:{port}/route/v1/driving/"
        f"{start[0]:.6f},{start[1]:.6f};{end[0]:.6f},{end[1]:.6f}"
        "?steps=true&overview=false&annotations=true&radiuses=50;50"
    )
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode("utf-8", "replace"))


def route_names(payload: dict[str, Any]) -> list[str]:
    if payload.get("code") != "Ok" or not payload.get("routes"):
        return []
    return [
        step.get("name", "")
        for leg in payload["routes"][0].get("legs", [])
        for step in leg.get("steps", [])
        if step.get("name")
    ]


def annotation_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    route = payload["routes"][0]
    annotation = route["legs"][0]["annotation"]
    distances = [float(value) for value in annotation["distance"]]
    durations = [float(value) for value in annotation["duration"]]
    finite = all(math.isfinite(value) and value >= 0 for value in distances + durations)
    sum_v2d = sum(
        ((distance / duration) ** 2) * distance
        for distance, duration in zip(distances, durations)
        if duration > 0
    )
    return {
        "segments": len(distances),
        "finite": finite,
        "distance_sum_m": sum(distances),
        "duration_sum_s": sum(durations),
        "route_distance_m": float(route["distance"]),
        "route_duration_s": float(route["duration"]),
        "distance_sum_matches": abs(sum(distances) - float(route["distance"])) <= 1.0,
        "duration_sum_matches": abs(sum(durations) - float(route["duration"])) <= 1.0,
        "sum_v2d": sum_v2d,
        "sum_v2d_positive_finite": math.isfinite(sum_v2d) and sum_v2d > 0,
    }


def main() -> None:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite {OUT}")
    profiles = {
        "cv": PROFILE_ROOT / "freight_cv_v2673.lua",
        "ev": PROFILE_ROOT / "freight_ev_v2673.lua",
    }
    required = [BIN / "osrm-extract", BIN / "osrm-contract", BIN / "osrm-routed", *profiles.values()]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing inputs: {missing}")
    OUT.mkdir(parents=True)
    raw_dir = OUT / "raw"
    raw_dir.mkdir()
    fixture, queries = build_fixture()
    fixture_path = OUT / "restriction_fixture_v3.osm"
    fixture_path.write_text(fixture, encoding="utf-8")
    lua_path = str(OSRM / "share/osrm/profiles/?.lua") + ";;"
    env = dict(os.environ)
    env["LUA_PATH"] = lua_path
    rows: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}

    with tempfile.TemporaryDirectory(prefix="resetp-osrm-functional-") as tmp_name:
        tmp = Path(tmp_name)
        for vehicle_index, (vehicle, profile) in enumerate(profiles.items()):
            osm = tmp / f"{vehicle}.osm"
            shutil.copy2(fixture_path, osm)
            base = tmp / f"{vehicle}.osrm"
            build_log = run(
                [
                    str(BIN / "osrm-extract"),
                    str(osm),
                    "--profile",
                    str(profile),
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
            build_log += run([str(BIN / "osrm-contract"), str(base), "--threads", "1"], cwd=tmp)
            (OUT / f"{vehicle}_build.log").write_text(build_log, encoding="utf-8")
            port = 5340 + vehicle_index
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
                cwd=tmp,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                for _ in range(60):
                    try:
                        urllib.request.urlopen(f"http://127.0.0.1:{port}/nearest/v1/driving/0,0", timeout=1).close()
                        break
                    except (urllib.error.URLError, TimeoutError):
                        time.sleep(0.1)
                for query_name, (start, end) in queries.items():
                    payload = request(port, start, end)
                    raw_path = raw_dir / f"{vehicle}_{query_name}.json"
                    raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    names = route_names(payload)
                    if query_name == "unreachable":
                        passed = payload.get("code") == "NoRoute"
                    elif payload.get("code") != "Ok" or not payload.get("routes"):
                        passed = False
                    elif query_name == "height":
                        expected = "height_restricted_direct" if vehicle == "cv" else "height_unrestricted_detour"
                        passed = expected in names
                    elif query_name in {"width", "length", "weight", "hgv_access"}:
                        passed = f"{query_name}_unrestricted_detour" in names
                    elif query_name == "oneway_forward":
                        passed = "oneway_direct" in names
                    elif query_name == "oneway_reverse":
                        passed = "oneway_reverse_detour" in names and "oneway_direct" not in names
                    else:
                        passed = payload["routes"][0]["distance"] > 0 and payload["routes"][0]["duration"] > 0
                    rows.append(
                        {
                            "vehicle": vehicle,
                            "query": query_name,
                            "code": payload.get("code"),
                            "route_names": "|".join(names),
                            "distance_m": payload.get("routes", [{}])[0].get("distance"),
                            "duration_s": payload.get("routes", [{}])[0].get("duration"),
                            "status": "PASS" if passed else "FAIL",
                            "search_evaluations": 0,
                        }
                    )
                    if query_name in {"reachable", "oneway_forward", "oneway_reverse"} and payload.get("code") == "Ok":
                        metrics[f"{vehicle}_{query_name}"] = annotation_metrics(payload)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    with (OUT / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "annotation_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    directed_ok = all(
        metrics[f"{vehicle}_oneway_forward"]["route_distance_m"]
        < metrics[f"{vehicle}_oneway_reverse"]["route_distance_m"]
        for vehicle in profiles
    )
    annotation_ok = all(
        value["finite"]
        and value["distance_sum_matches"]
        and value["duration_sum_matches"]
        and value["sum_v2d_positive_finite"]
        for value in metrics.values()
    )
    all_pass = len(rows) == 18 and all(row["status"] == "PASS" for row in rows) and directed_ok and annotation_ok
    decision = {
        "schema": "resetp.phase1.osrm-functional-gate.decision.v3",
        "verdict": "PASS_OSRM_2673_MINIMUM_FREIGHT_FUNCTIONAL_GATE" if all_pass else "HALT_OSRM_FREIGHT_FUNCTIONAL_GATE",
        "checks": {
            "height": all(row["status"] == "PASS" for row in rows if row["query"] == "height"),
            "width": all(row["status"] == "PASS" for row in rows if row["query"] == "width"),
            "length": all(row["status"] == "PASS" for row in rows if row["query"] == "length"),
            "weight": all(row["status"] == "PASS" for row in rows if row["query"] == "weight"),
            "hgv_access": all(row["status"] == "PASS" for row in rows if row["query"] == "hgv_access"),
            "oneway_direction": directed_ok,
            "unreachable_pair": all(row["status"] == "PASS" for row in rows if row["query"] == "unreachable"),
            "finite_directed_distance_duration": annotation_ok,
            "sum_v2d_interface": annotation_ok,
        },
        "route_checks": len(rows),
        "route_passes": sum(row["status"] == "PASS" for row in rows),
        "formal_search_allowed": False,
        "full_matrix_built": False,
        "solver_search_evaluations": 0,
    }
    (OUT / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metadata = {
        "schema": "resetp.phase1.osrm-functional-gate.metadata.v3",
        "generated_utc": datetime.now(UTC).isoformat(),
        "osrm_version": run([str(BIN / "osrm-extract"), "--version"], cwd=OUT).strip(),
        "profiles": {
            vehicle: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
            for vehicle, path in profiles.items()
        },
        "full_matrix_built": False,
        "solver_search_evaluations": 0,
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "report.md").write_text(
        "# OSRM 26.7.3 货运 profile 最小完整功能门\n\n"
        f"判决：`{decision['verdict']}`，{decision['route_passes']}/{decision['route_checks']}条查询通过。"
        "覆盖高、宽、长、重、hgv禁行、单行方向、不可达、方向性距离/时间、分段注释与sum(v²d)接口。"
        "本包没有建省图、全矩阵或运行求解器搜索。\n",
        encoding="utf-8",
    )
    hashed = [
        OUT / "restriction_fixture_v3.osm",
        OUT / "cv_build.log",
        OUT / "ev_build.log",
        OUT / "raw_runs.csv",
        OUT / "annotation_metrics.json",
        OUT / "decision.json",
        OUT / "metadata.json",
        OUT / "report.md",
        *sorted(path for path in raw_dir.glob("*.json") if not path.name.startswith("._")),
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
