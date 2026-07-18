#!/usr/bin/env python3
"""Build routable, sparse-connected China81 OSRM graphs from frozen PBFs.

The first full-province build completed extract/contract but its spatial index
could not snap even coordinates printed in the extract log.  This runner keeps
that failed-at-use package intact and derives three reproducible sparse inputs:
all roads around each China81 city plus the regional motorway/trunk/primary/
secondary backbone. Acceptance requires a successful Nearest API probe for
every distinct China81 coordinate under both frozen freight profiles.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from build_china_stage2_local_osrm_graphs_20260718 import (
    GraphBuildError,
    atomic_csv,
    atomic_json,
    graph_files,
    profile_inputs,
    run_stage,
    sha256,
    utc_now,
    verify_runtime,
    write_artifact_hashes,
)


REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / "data/ChinaInstances/china81_stage2_static_inputs_v1_20260718"
OUT = REPO / "data/ChinaInstances/china_stage2_sparse_connected_osrm_graphs_v5_20260718"
HEBEI = REPO / "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/fixed_osm_inputs/hebei-260716.osm.pbf"
GUANGDONG = REPO / "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/fixed_osm_inputs/guangdong-260716.osm.pbf"
CHENGYU = REPO / "data/ChinaInstances/china_stage2_chengyu_merged_osm_v1_20260718/chengyu-260716.osm.pbf"
SOURCES = {"jjj": HEBEI, "prd": GUANGDONG, "cy": CHENGYU}
REGION_MARGIN_DEGREES = 0.35
LOCAL_MARGIN_DEGREES = 0.12
BACKBONE_FILTER = (
    "w/highway=motorway,motorway_link,trunk,trunk_link,primary,primary_link,"
    "secondary,secondary_link"
)
COMPLETION = "SPARSE_CONNECTED_OSRM_GRAPHS_COMPLETE.json"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def region_points(region: str, catalog: list[dict[str, str]]) -> list[tuple[float, float]]:
    points: set[tuple[float, float]] = set()
    for item in catalog:
        if item["region"] != region:
            continue
        nodes = read_csv(STATIC / "instances" / item["instance_id"] / "nodes.csv")
        points.update((float(row["longitude"]), float(row["latitude"])) for row in nodes)
    if len(points) < 2:
        raise GraphBuildError(f"insufficient frozen China81 points for {region}")
    return sorted(points)


def region_points_by_city(
    region: str, catalog: list[dict[str, str]]
) -> dict[str, list[tuple[float, float]]]:
    points: dict[str, set[tuple[float, float]]] = {}
    for item in catalog:
        if item["region"] != region:
            continue
        nodes = read_csv(STATIC / "instances" / item["instance_id"] / "nodes.csv")
        for row in nodes:
            points.setdefault(row["city"], set()).add(
                (float(row["longitude"]), float(row["latitude"]))
            )
    return {city: sorted(values) for city, values in sorted(points.items())}


def bbox(
    points: list[tuple[float, float]], margin: float
) -> tuple[float, float, float, float]:
    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]
    return (
        min(longitudes) - margin,
        min(latitudes) - margin,
        max(longitudes) + margin,
        max(latitudes) + margin,
    )


def run_command(command: list[str], log_path: Path) -> int:
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.run(
            command,
            cwd=REPO,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    return process.returncode


def build_sparse_input(
    source: Path,
    target: Path,
    all_points: list[tuple[float, float]],
    city_points: dict[str, list[tuple[float, float]]],
    rows: list[dict[str, Any]],
    raw_runs: Path,
    region: str,
) -> dict[str, Any]:
    started = utc_now()
    monotonic = time.monotonic()
    work = target.parent
    outer = work / f"{region}-outer.pbf"
    backbone = work / f"{region}-backbone.pbf"
    outer_bounds = bbox(all_points, REGION_MARGIN_DEGREES)
    logs: list[str] = []
    log_path = work / "01_outer_extract.log"
    logs.append(str(log_path.relative_to(REPO)))
    returncode = run_command(
        [
            "/opt/homebrew/bin/osmium",
            "extract",
            "-b",
            ",".join(f"{value:.8f}" for value in outer_bounds),
            str(source),
            "-o",
            str(outer),
            "--overwrite",
        ],
        log_path,
    )
    if returncode == 0:
        log_path = work / "02_backbone_filter.log"
        logs.append(str(log_path.relative_to(REPO)))
        returncode = run_command(
            [
                "/opt/homebrew/bin/osmium",
                "tags-filter",
                str(outer),
                BACKBONE_FILTER,
                "-o",
                str(backbone),
                "--overwrite",
            ],
            log_path,
        )
    local_paths: list[Path] = []
    local_bounds: dict[str, tuple[float, float, float, float]] = {}
    if returncode == 0:
        for index, (city, points) in enumerate(city_points.items(), start=3):
            bounds = bbox(points, LOCAL_MARGIN_DEGREES)
            local_bounds[city] = bounds
            local = work / f"{region}-local-{city}.pbf"
            local_paths.append(local)
            log_path = work / f"{index:02d}_local_{city}.log"
            logs.append(str(log_path.relative_to(REPO)))
            returncode = run_command(
                [
                    "/opt/homebrew/bin/osmium",
                    "extract",
                    "-b",
                    ",".join(f"{value:.8f}" for value in bounds),
                    str(outer),
                    "-o",
                    str(local),
                    "--overwrite",
                ],
                log_path,
            )
            if returncode != 0:
                break
    if returncode == 0:
        log_path = work / "99_merge.log"
        logs.append(str(log_path.relative_to(REPO)))
        returncode = run_command(
            [
                "/opt/homebrew/bin/osmium",
                "merge",
                str(backbone),
                *map(str, local_paths),
                "-o",
                str(target),
                "--overwrite",
            ],
            log_path,
        )
    rows.append(
        {
            "region": region,
            "profile": "shared",
            "stage": "osmium_sparse_connected_input",
            "status": "PASS" if returncode == 0 else "FAIL",
            "started_utc": started,
            "finished_utc": utc_now(),
            "elapsed_seconds": f"{time.monotonic() - monotonic:.6f}",
            "returncode": returncode,
            "log_path": ";".join(logs),
            "detail": (
                "all city-local roads plus motorway/trunk/primary/secondary backbone"
            ),
        }
    )
    atomic_csv(raw_runs, rows)
    if returncode != 0:
        raise GraphBuildError(f"{region} sparse input build failed; see {log_path}")
    return {
        "outer_bbox_wgs84": outer_bounds,
        "region_margin_degrees": REGION_MARGIN_DEGREES,
        "local_bboxes_wgs84": local_bounds,
        "local_margin_degrees": LOCAL_MARGIN_DEGREES,
        "backbone_filter": BACKBONE_FILTER,
    }


def probe_all_points(graph_base: Path, points: list[tuple[float, float]], port: int) -> dict[str, Any]:
    log_path = graph_base.parent / "routed_probe.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                "/opt/homebrew/bin/osrm-routed",
                str(graph_base),
                "--algorithm",
                "CH",
                "--ip",
                "127.0.0.1",
                "--port",
                str(port),
                "--threads",
                "1",
            ],
            cwd=REPO,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            failures: list[dict[str, Any]] = []
            matched = 0
            for index, (longitude, latitude) in enumerate(points):
                url = (
                    f"http://127.0.0.1:{port}/nearest/v1/driving/"
                    f"{longitude:.7f},{latitude:.7f}?number=1"
                )
                payload: dict[str, Any] | None = None
                for attempt in range(80 if index == 0 else 3):
                    if process.poll() is not None:
                        raise GraphBuildError(f"probe router exited; see {log_path}")
                    try:
                        with urllib.request.urlopen(url, timeout=5) as response:
                            payload = json.load(response)
                        break
                    except urllib.error.HTTPError as exc:
                        try:
                            payload = json.loads(exc.read().decode("utf-8"))
                        except json.JSONDecodeError:
                            payload = {"code": f"HTTP_{exc.code}"}
                        break
                    except (urllib.error.URLError, TimeoutError, ConnectionError):
                        time.sleep(0.1 if index == 0 else 0.2)
                if payload and payload.get("code") == "Ok" and payload.get("waypoints"):
                    matched += 1
                else:
                    failures.append(
                        {
                            "longitude": longitude,
                            "latitude": latitude,
                            "code": None if payload is None else payload.get("code"),
                        }
                    )
            return {
                "distinct_points": len(points),
                "matched_points": matched,
                "failures": failures,
            }
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def main() -> int:
    if (OUT / COMPLETION).exists():
        raise GraphBuildError("completion marker exists; refusing overwrite")
    OUT.mkdir(parents=True, exist_ok=True)
    runtime = verify_runtime()
    environment = dict(os.environ)
    environment["LUA_PATH"] = runtime["lua_runtime"]["profile_root"] + "/?.lua;;"
    profiles = profile_inputs()
    catalog = read_csv(STATIC / "instance_catalog.csv")
    rows: list[dict[str, Any]] = []
    raw_runs = OUT / "raw_runs.csv"
    metadata_regions: list[dict[str, Any]] = []
    probe_records: list[dict[str, Any]] = []

    for region_index, region in enumerate(("jjj", "prd", "cy")):
        source = SOURCES[region]
        if not source.is_file():
            raise GraphBuildError(f"missing frozen source: {source}")
        points = region_points(region, catalog)
        points_by_city = region_points_by_city(region, catalog)
        clip_dir = OUT / "clips" / region
        clip_dir.mkdir(parents=True, exist_ok=True)
        clip = clip_dir / f"{region}-china81-sparse-connected-260716.osm.pbf"
        construction = build_sparse_input(
            source, clip, points, points_by_city, rows, raw_runs, region
        )
        clip_hash = sha256(clip)
        metadata_regions.append(
            {
                "region": region,
                "source_path": str(source.relative_to(REPO)),
                "source_sha256": sha256(source),
                "construction": construction,
                "distinct_china81_points": len(points),
                "clip_path": str(clip.relative_to(REPO)),
                "clip_sha256": clip_hash,
            }
        )
        for profile_index, profile in enumerate(profiles):
            graph_dir = OUT / "graphs" / region / profile.name
            graph_dir.mkdir(parents=True, exist_ok=False)
            graph_base = graph_dir / f"{region}-{profile.name}.osrm"
            with tempfile.TemporaryDirectory(
                prefix=f"resetp-osrm-{region}-{profile.name}-",
                dir="/tmp",
            ) as temporary_name:
                temporary_base = (
                    Path(temporary_name) / f"{region}-{profile.name}.osrm"
                )
                run_stage(
                    [
                        runtime["osrm-extract"]["path"],
                        str(clip),
                        "--profile",
                        str(profile.path),
                        "--threads",
                        "6",
                        "--output",
                        str(temporary_base),
                    ],
                    environment,
                    graph_dir / "extract.log",
                    region,
                    profile.name,
                    "extract_apfs_runtime",
                    rows,
                    raw_runs,
                )
                run_stage(
                    [
                        runtime["osrm-contract"]["path"],
                        str(temporary_base),
                        "--threads",
                        "6",
                    ],
                    environment,
                    graph_dir / "contract.log",
                    region,
                    profile.name,
                    "contract_apfs_runtime",
                    rows,
                    raw_runs,
                )
                probe = probe_all_points(
                    temporary_base,
                    points,
                    5220 + region_index * 2 + profile_index,
                )
                copied_hashes: dict[str, str] = {}
                for source_file in sorted(
                    temporary_base.parent.glob(temporary_base.name + "*")
                ):
                    target_file = graph_dir / source_file.name
                    shutil.copy2(source_file, target_file)
                    source_hash = sha256(source_file)
                    target_hash = sha256(target_file)
                    if source_hash != target_hash:
                        raise GraphBuildError(
                            f"APFS-to-archive hash drift: {target_file}"
                        )
                    copied_hashes[target_file.name] = target_hash
            probe.update({"region": region, "profile": profile.name})
            probe_records.append(probe)
            atomic_json(OUT / "route_probe_checkpoint.json", {"records": probe_records})
            if probe["failures"]:
                raise GraphBuildError(
                    f"{region}/{profile.name}: {len(probe['failures'])} China81 points failed Nearest"
                )
            files = graph_files(graph_dir)
            atomic_json(
                graph_dir / "graph_manifest.json",
                {
                    "identity": f"{region}/{profile.name}",
                    "clip_sha256": clip_hash,
                    "profile_sha256": profile.sha256,
                    "build_filesystem": "APFS /tmp",
                    "archive_filesystem": "exFAT repository volume",
                    "apfs_to_archive_copy_hashes": copied_hashes,
                    "route_probe": probe,
                    "files": {
                        str(path.relative_to(graph_dir)): sha256(path)
                        for path in files
                    },
                },
            )

    metadata = {
        "schema": "resetp.china-stage2.sparse-connected-osrm-graphs.v5",
        "generated_utc": utc_now(),
        "reason": (
            "full-province v1 extract/contract succeeded but its spatial index "
            "returned NoSegment for all tested coordinates, the broader v2 "
            "clip repeated it, v3 proved large indexes must be built on APFS, "
            "and v4 proved small-component-size=0 can snap to disconnected "
            "local roads; all failures are retained"
        ),
        "runtime": runtime,
        "profiles": [
            {"name": profile.name, "path": str(profile.path.relative_to(REPO)), "sha256": profile.sha256}
            for profile in profiles
        ],
        "regions": metadata_regions,
        "route_probes": probe_records,
        "runtime_filesystem_contract": (
            "build and route on APFS; archive to exFAT only after byte hashes "
            "match; restore to APFS and reverify hashes before matrix routing"
        ),
        "endpoint_component_contract": (
            "OSRM default small-component filtering retained; the phase1 "
            "micro-probe override small-component-size=0 is forbidden here"
        ),
        "search_evaluations": 0,
        "formal_search_allowed": False,
    }
    atomic_json(OUT / "metadata.json", metadata)
    atomic_json(
        OUT / "decision.json",
        {
            "verdict": "PASS_CHINA81_SPARSE_CONNECTED_OSRM_GRAPHS_AND_ALL_POINT_SNAPS",
            "graph_count": 6,
            "all_distinct_points_matched_under_both_profiles": True,
            "v1_v2_broad_graphs_accepted_for_matrix_use": False,
            "search_evaluations": 0,
            "formal_search_allowed": False,
        },
    )
    (OUT / "report.md").write_text(
        "# China81 稀疏连通 OSRM 图 v5\n\n"
        "从原冻结 PBF 保留各城市 China81 坐标周边全部道路，并保留区域内"
        "motorway/trunk/primary/secondary 城际主干，生成三个可复现稀疏连通输入，"
        "再在 APFS 临时盘使用冻结 CV/EV profile 构建六套 CH 图。每套图均通过该区域全部去重"
        "China81 坐标的 Nearest API 吸附检查。旧全省图与宽区域裁剪图保留为"
        "“构建通过但使用失败”的异常证据，不进入矩阵。图文件逐字节哈希一致后"
        "才归档到 exFAT 仓库；矩阵运行前必须回读 APFS 并复核哈希。\n\n"
        "正式图保留 OSRM 默认小分量过滤，禁止沿用微探针的"
        "`--small-component-size 0`，避免端点吸附到孤立局部道路。\n\n"
        "本任务不调用求解器，搜索评价为 0；G1 冻结前仍不构成正式算法验收。\n",
        encoding="utf-8",
    )
    atomic_json(
        OUT / COMPLETION,
        {
            "completed_utc": utc_now(),
            "verdict": "PASS_CHINA81_SPARSE_CONNECTED_OSRM_GRAPHS_AND_ALL_POINT_SNAPS",
        },
    )
    write_artifact_hashes(OUT)
    print(json.dumps({"graphs": 6, "probes": probe_records}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
