#!/usr/bin/env python3
"""Independently summarize China81 matrix routing and snapping diagnostics."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sqlite3
from pathlib import Path

from china81_artifact_integrity_20260719 import (
    require_decision,
    verify_artifact_package,
)


REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / "data/ChinaInstances/china81_stage2_static_inputs_v1_20260718"
MATRICES = REPO / "data/ChinaInstances/china81_local_directed_matrices_v9_20260718"
OUT = REPO / "data/ChinaInstances/china81_matrix_diagnostics_v1_20260718"
EXPECTED_INSTANCES = 81
EXPECTED_MATERIALIZED_ORDERED_PAIRS = 1_578_948
EXPECTED_BATCHES = {
    (region, profile)
    for region in ("jjj", "prd", "cy")
    for profile in ("cv", "ev")
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def haversine_m(
    longitude_a: float, latitude_a: float, longitude_b: float, latitude_b: float
) -> float:
    radius = 6_371_000.0
    phi_a = math.radians(latitude_a)
    phi_b = math.radians(latitude_b)
    delta_phi = phi_b - phi_a
    delta_lambda = math.radians(longitude_b - longitude_a)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(value))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def coordinate_key(row: dict[str, str]) -> str:
    return f"{float(row['longitude']):.7f},{float(row['latitude']):.7f}"


def derive_expected_counts(
    static_root: Path,
) -> tuple[dict[str, int], dict[str, int]]:
    """Derive route-cache and materialized-pair counts from static inputs only."""

    catalog = read_csv(static_root / "instance_catalog.csv")
    instance_ids = [row["instance_id"] for row in catalog]
    if len(catalog) != EXPECTED_INSTANCES or len(set(instance_ids)) != EXPECTED_INSTANCES:
        raise RuntimeError(
            f"China81 catalog must contain {EXPECTED_INSTANCES} unique instances"
        )
    regional_pairs = {region: set() for region in ("jjj", "prd", "cy")}
    materialized = {region: 0 for region in ("jjj", "prd", "cy")}
    for item in catalog:
        region = item["region"]
        if region not in regional_pairs:
            raise RuntimeError(f"unexpected China81 region: {region}")
        nodes = read_csv(
            static_root / "instances" / item["instance_id"] / "nodes.csv"
        )
        keys = [coordinate_key(row) for row in nodes]
        if len(keys) != len(set(keys)):
            raise RuntimeError(f"duplicate node coordinate in {item['instance_id']}")
        regional_pairs[region].update(
            (origin, destination)
            for origin in keys
            for destination in keys
            if origin != destination
        )
        materialized[region] += len(nodes) * (len(nodes) - 1)
    unique = {region: len(pairs) for region, pairs in regional_pairs.items()}
    return unique, materialized


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    authority_files = ("metadata.json", "raw_runs.csv", "decision.json", "report.md")
    verified_static_files = verify_artifact_package(STATIC, authority_files)
    require_decision(
        STATIC / "decision.json",
        "PASS_G1_INDEPENDENT_STATIC_INPUTS_FROZEN",
        {"formal_experiment_authorized": False, "search_evaluations": 0},
    )
    verified_matrix_files = verify_artifact_package(
        MATRICES,
        authority_files,
    )
    require_decision(
        MATRICES / "decision.json",
        "PASS_CHINA81_LOCAL_DIRECTED_THREE_MATRICES",
        {"ordered_pairs_complete": True, "unreachable_pairs": 0},
    )
    summaries: list[dict] = []
    edge_cases: list[dict] = []
    expected_unique, expected_materialized = derive_expected_counts(STATIC)
    recorded: dict[tuple[str, str], tuple[int, int, str]] = {}
    with (MATRICES / "raw_runs.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            batch = (row["region"], row["profile"])
            if batch in recorded:
                raise RuntimeError(f"duplicate matrix batch record: {batch}")
            recorded[batch] = (
                int(row["unique_route_requests"]),
                int(row["materialized_ordered_pairs"]),
                row["status"],
            )
    if set(recorded) != EXPECTED_BATCHES:
        raise RuntimeError(
            f"matrix batch set mismatch: {sorted(recorded)}"
        )

    for region in ("jjj", "prd", "cy"):
        for profile in ("cv", "ev"):
            database = MATRICES / f"route_cache_{region}_{profile}.sqlite"
            connection = sqlite3.connect(database)
            connection.row_factory = sqlite3.Row
            totals = connection.execute(
                """
                SELECT COUNT(*) AS route_count,
                       SUM(zero_duration_positive_distance_segments) AS zero_segments,
                       SUM(colocated_snapped_pair) AS colocated,
                       SUM(subresolution_zero_duration_pair) AS subresolution,
                       SUM(via_repair) AS via_repairs,
                       MIN(distance_m) AS min_distance_m,
                       MAX(distance_m) AS max_distance_m,
                       MAX(duration_s) AS max_duration_s,
                       COUNT(DISTINCT response_sha256) AS response_hashes,
                       COUNT(DISTINCT request_sha256) AS request_hashes
                FROM routes
                """
            ).fetchone()
            maximum_snap = 0.0
            for row in connection.execute(
                """
                SELECT origin_key,destination_key,origin_matched_lon,
                       origin_matched_lat,destination_matched_lon,
                       destination_matched_lat
                FROM routes
                """
            ):
                origin_lon, origin_lat = map(float, row["origin_key"].split(","))
                destination_lon, destination_lat = map(
                    float, row["destination_key"].split(",")
                )
                maximum_snap = max(
                    maximum_snap,
                    haversine_m(
                        origin_lon,
                        origin_lat,
                        row["origin_matched_lon"],
                        row["origin_matched_lat"],
                    ),
                    haversine_m(
                        destination_lon,
                        destination_lat,
                        row["destination_matched_lon"],
                        row["destination_matched_lat"],
                    ),
                )
            for row in connection.execute(
                """
                SELECT origin_key,destination_key,distance_m,duration_s,
                       zero_duration_positive_distance_segments,
                       colocated_snapped_pair,subresolution_zero_duration_pair,
                       via_repair,via_matched_lon,via_matched_lat,
                       response_sha256,request_sha256
                FROM routes
                WHERE colocated_snapped_pair=1
                   OR subresolution_zero_duration_pair=1
                   OR via_repair=1
                ORDER BY origin_key,destination_key
                """
            ):
                edge_cases.append({"region": region, "profile": profile, **dict(row)})
            connection.close()
            route_count = int(totals["route_count"])
            summaries.append(
                {
                    "region": region,
                    "profile": profile,
                    "route_count": route_count,
                    "expected_route_count": expected_unique[region],
                    "recorded_route_count": recorded[(region, profile)][0],
                    "route_count_match": (
                        route_count
                        == expected_unique[region]
                        == recorded[(region, profile)][0]
                    ),
                    "expected_materialized_ordered_pairs": expected_materialized[
                        region
                    ],
                    "recorded_materialized_ordered_pairs": recorded[
                        (region, profile)
                    ][1],
                    "materialized_count_match": (
                        expected_materialized[region]
                        == recorded[(region, profile)][1]
                    ),
                    "recorded_status": recorded[(region, profile)][2],
                    "zero_duration_positive_distance_segments": int(
                        totals["zero_segments"] or 0
                    ),
                    "colocated_snapped_pairs": int(totals["colocated"] or 0),
                    "subresolution_zero_duration_pairs": int(
                        totals["subresolution"] or 0
                    ),
                    "via_repairs": int(totals["via_repairs"] or 0),
                    "max_endpoint_snap_m": f"{maximum_snap:.6f}",
                    "min_route_distance_m": f"{float(totals['min_distance_m']):.6f}",
                    "max_route_distance_m": f"{float(totals['max_distance_m']):.6f}",
                    "max_route_duration_s": f"{float(totals['max_duration_s']):.6f}",
                    "distinct_response_hashes": int(totals["response_hashes"]),
                    "distinct_request_hashes": int(totals["request_hashes"]),
                    "search_evaluations": 0,
                }
            )

    fields = list(summaries[0])
    write_csv(OUT / "raw_runs.csv", summaries, fields)
    edge_fields = [
        "region", "profile", "origin_key", "destination_key", "distance_m",
        "duration_s", "zero_duration_positive_distance_segments",
        "colocated_snapped_pair", "subresolution_zero_duration_pair",
        "via_repair", "via_matched_lon", "via_matched_lat",
        "response_sha256", "request_sha256",
    ]
    write_csv(OUT / "edge_cases.csv", edge_cases, edge_fields)
    all_counts_match = all(
        row["route_count_match"]
        and row["materialized_count_match"]
        and row["recorded_status"] == "PASS"
        for row in summaries
    )
    materialized_total = sum(
        row["expected_materialized_ordered_pairs"] for row in summaries
    )
    maximum_snap = max(float(row["max_endpoint_snap_m"]) for row in summaries)
    verdict = (
        "PASS_CHINA81_MATRIX_DIAGNOSTICS_COMPLETE"
        if (
            all_counts_match
            and materialized_total == EXPECTED_MATERIALIZED_ORDERED_PAIRS
            and maximum_snap <= 10_000
        )
        else "HALT_CHINA81_MATRIX_DIAGNOSTICS"
    )
    metadata = {
        "schema": "resetp.china81-matrix-diagnostics.v1",
        "matrix_package": str(MATRICES.relative_to(REPO)),
        "matrix_artifact_hashes_sha256": sha256(MATRICES / "artifact_hashes.json"),
        "verified_static_files": verified_static_files,
        "verified_matrix_files": verified_matrix_files,
        "unique_route_requests": sum(row["route_count"] for row in summaries),
        "materialized_ordered_pairs": materialized_total,
        "expected_materialized_ordered_pairs": EXPECTED_MATERIALIZED_ORDERED_PAIRS,
        "maximum_allowed_endpoint_snap_m": 10_000,
        "selection_contract": (
            "direct route first; on NoRoute evaluate at most 32 nearest road "
            "candidates from each endpoint as one via and select shortest route"
        ),
        "search_evaluations": 0,
        "formal_search_allowed": False,
    }
    (OUT / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    decision = {
        "verdict": verdict,
        "all_six_route_counts_match": all_counts_match,
        "materialized_ordered_pairs": materialized_total,
        "materialized_ordered_pairs_complete": (
            materialized_total == EXPECTED_MATERIALIZED_ORDERED_PAIRS
        ),
        "max_endpoint_snap_m": maximum_snap,
        "zero_duration_positive_distance_segments": sum(
            row["zero_duration_positive_distance_segments"] for row in summaries
        ),
        "colocated_snapped_pairs": sum(
            row["colocated_snapped_pairs"] for row in summaries
        ),
        "subresolution_zero_duration_pairs": sum(
            row["subresolution_zero_duration_pairs"] for row in summaries
        ),
        "via_repairs": sum(row["via_repairs"] for row in summaries),
        "formal_experiment_authorized": False,
        "search_evaluations": 0,
    }
    (OUT / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "report.md").write_text(
        "# China81 道路矩阵诊断\n\n"
        f"判定：`{verdict}`。六个区域/profile 缓存共含 "
        f"{metadata['unique_route_requests']} 个唯一有向请求，物化 1,578,948 个"
        "实例内有向对。所有特殊路线均在 `edge_cases.csv` 中保留端点、via 与"
        "响应/请求哈希。本审计不调用算法求解器，正式搜索仍关闭。\n",
        encoding="utf-8",
    )
    hashes = {
        path.name: sha256(path)
        for path in OUT.iterdir()
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    (OUT / "artifact_hashes.json").write_text(
        json.dumps({"sha256": hashes}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(decision, ensure_ascii=False))
    return 0 if verdict.startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
