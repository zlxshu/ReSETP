#!/usr/bin/env python3
"""Build the frozen-customer JJJ depot-swap instance approved in P56.

Only the two depot rows and depot-derived order fields are changed.  The
customer identities, coordinates, demands, service times, time windows,
shifts, and shift ids are copied byte-for-byte at field level from the active
PRDFIX instance.  Missing directed arcs are queried from the frozen China81
OSRM graphs; no straight-line or symmetric completion is permitted.  This
script runs deterministic construction/evaluation only, never a search solver.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import platform
import re
import shlex
import sqlite3
import statistics
import sys
import tempfile
import urllib.request
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "solver" / "src"))

DEPOTPAIR_SCRIPT = REPO / "solver/scripts/build_suite_depotpair_rebuild_20260812.py"
PRDFIX_SCRIPT = REPO / "solver/scripts/build_suite_prd_fix_20260812.py"
OLD_ROOT = REPO / "data/ChinaInstances/china81_suite_prd_fix_v1_20260812"
OLD_ID = "cn-jjj-50c-01-V3-TWO-SHIFT-PRDFIX"
OLD_INSTANCE = OLD_ROOT / "instances" / OLD_ID
OLD_HEALTH = REPO / "solver/reports/station_restore_20260812/generation_prdfix/suite_health_v3.csv"
OLD_MATRIX_ROOT = REPO / "data/ChinaInstances/china81_depotpair_rebuild_v1_20260812/directed_matrices"
OSM_POOL = REPO / "data/ChinaInstances/china9_metro_pool_20260812/pools/beijing__logistics_candidate.csv"

NEW_ID = "cn-jjj-50c-01-V3-TWO-SHIFT-DEPOTSWAP"
NEW_POOL_ID = "cn-jjj-50c-01-DEPOTSWAP-POOL"
DEFAULT_OUTPUT = REPO / "data/ChinaInstances/china81_instance_depot_swap_jjj_v1_20260813"
DEFAULT_REPORT = REPO / "solver/reports/instance_depot_swap_jjj_20260813"

PROTECTED_EXPECTED = {
    "solver/src/setp_solver/cost.py": "525e91f7bd2cf7a4b6610ee1c8f662e8a4233c5daec800dcae5e5f21ac727989",
    "solver/src/setp_solver/check.py": "1cdb6236a662eec7363dfdf99c0c0df287b32aeffbc7bd48572320696c0b1072",
    "solver/src/setp_solver/search/evaluation.py": "c7215263c39d1d5a1429b41ca8ac40d950dbdf2bdc288337e56fbe9733406fc3",
}

DEPOTS = (
    {
        "depot_id": "D_beijing_xinan_south",
        "name": "北京西南物流中心南区",
        "osm_type": "way",
        "osm_id": "1008934072",
        "center_latitude": 39.8316727,
        "center_longitude": 116.2512885,
        "expected_source_response_sha256": "c914af936cee23252fb0a2987dc60c0ae08ae3b7456991e03d8e7b6a97fac855",
    },
    {
        "depot_id": "D_beijing_sanjianfang",
        "name": "北京外运三间房仓库",
        "osm_type": "way",
        "osm_id": "1423815157",
        "center_latitude": 39.8482117,
        "center_longitude": 116.5789113,
        "expected_source_response_sha256": "a4c59a4fe328d1630fcfdaceaecbfca93bb678ebd1477b480c889321ce805040",
    },
)

INVARIANT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "客户身份",
        (
            "region", "customer_size", "replicate", "customer_id", "city",
            "osm_type", "osm_id", "name", "order_seed",
            "empirical_source_index_zero_based", "source_order_uid",
            "source_instance_id_task", "source_customer_id_task",
            "source_instance_id_location", "source_customer_id_location",
            "location_mapping_class",
        ),
    ),
    ("客户坐标", ("latitude", "longitude")),
    (
        "需求量",
        ("source_volume_m3", "demand_kg", "demand_classification"),
    ),
    (
        "服务时长",
        ("service_minutes", "service_classification"),
    ),
    (
        "时间窗",
        (
            "time_window_early_minute", "time_window_late_minute",
            "time_window_width_minute", "source_time_window_early_minute",
            "source_time_window_late_minute", "source_time_window_width_minute",
            "window_classification",
        ),
    ),
    (
        "班次与 shift_id",
        (
            "shift_id", "preferred_shift_id", "shift_start_minute",
            "shift_end_minute", "depot_return_required", "shift_mapping_class",
        ),
    ),
)

DERIVED_ORDER_FIELDS = (
    "home_depot_id",
    "home_to_customer_travel_minute",
    "shift_reachability_status",
    "preferred_shift_reachable",
    "alternative_shift_reachable",
    "reachability_window_delay_minute",
)


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


dp = load_module("depot_swap_depotpair_20260813", DEPOTPAIR_SCRIPT)
base = dp.base


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    fields: Sequence[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    selected = list(fields or (list(rows[0]) if rows else ()))
    if not selected:
        raise ValueError(f"no CSV fields for {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=selected, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_hashes(root: Path, *, exclude_manifest: bool = True) -> dict[str, str]:
    output: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("._"):
            continue
        if exclude_manifest and path.name == "artifact_hashes.json":
            continue
        output[str(path.relative_to(root))] = sha256(path)
    return output


def remove_appledouble(root: Path) -> list[str]:
    removed = []
    for path in sorted(root.rglob("._*")):
        if path.is_file():
            removed.append(str(path.relative_to(root)))
            path.unlink()
    return removed


def canonical_sha(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> str:
    payload = [
        [str(row.get(field, "")) for field in fields]
        for row in sorted(rows, key=lambda item: str(item["customer_id"]))
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def protected_hashes() -> dict[str, str]:
    return {path: sha256(REPO / path) for path in PROTECTED_EXPECTED}


def snapshot_tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.name.startswith("._")
    }


def haversine_km(left: tuple[float, float], right: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, left)
    lat2, lon2 = map(math.radians, right)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    value = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    )
    return 2.0 * 6371.0088 * math.asin(math.sqrt(value))


def source_depot_rows() -> list[dict[str, Any]]:
    pool_rows = {
        (row["osm_type"], row["osm_id"]): row
        for row in read_csv(OSM_POOL)
    }
    output = []
    for spec in DEPOTS:
        row = pool_rows[(str(spec["osm_type"]), str(spec["osm_id"]))]
        if row["name"] != spec["name"]:
            raise RuntimeError(f"OSM name drift for {spec['osm_type']}/{spec['osm_id']}")
        if abs(float(row["latitude"]) - float(spec["center_latitude"])) > 1e-9:
            raise RuntimeError("frozen OSM latitude drift")
        if abs(float(row["longitude"]) - float(spec["center_longitude"])) > 1e-9:
            raise RuntimeError("frozen OSM longitude drift")
        raw = REPO / row["source_response_path"]
        actual_raw_sha = sha256(raw)
        if actual_raw_sha != row["source_response_sha256"]:
            raise RuntimeError(f"raw OSM response hash mismatch: {raw}")
        if actual_raw_sha != spec["expected_source_response_sha256"]:
            raise RuntimeError(f"approved OSM source drift: {raw}")
        output.append(
            {
                **spec,
                "osm_identity": f"{spec['osm_type']}/{spec['osm_id']}",
                "coordinate_status": row["coordinate_status"],
                "source_pool_path": str(OSM_POOL.relative_to(REPO)),
                "source_pool_sha256": sha256(OSM_POOL),
                "source_response_path": row["source_response_path"],
                "source_response_sha256": actual_raw_sha,
            }
        )
    return output


def snap_depots(
    source_rows: Sequence[Mapping[str, Any]], matrix_root: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    access_rows: list[dict[str, Any]] = []
    raw_payloads: list[dict[str, Any]] = []
    with dp.RouterSession("jjj", "cv", matrix_root) as router:
        for source in source_rows:
            lon = float(source["center_longitude"])
            lat = float(source["center_latitude"])
            url = f"{router.endpoint}/nearest/v1/driving/{lon},{lat}?number=1"
            with urllib.request.urlopen(url, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("code") != "Ok" or len(payload.get("waypoints", [])) != 1:
                raise RuntimeError(f"OSRM nearest failed for {source['osm_identity']}: {payload}")
            waypoint = payload["waypoints"][0]
            access_lon, access_lat = map(float, waypoint["location"])
            access_rows.append(
                {
                    "depot_id": source["depot_id"],
                    "name": source["name"],
                    "osm_identity": source["osm_identity"],
                    "osm_center_latitude": lat,
                    "osm_center_longitude": lon,
                    "scenario_access_latitude": access_lat,
                    "scenario_access_longitude": access_lon,
                    "osrm_nearest_reported_offset_m": float(waypoint["distance"]),
                    "access_semantics": "SCENARIO_ROAD_ACCESS_POINT_NOT_OBSERVED_TRUCK_GATE",
                    "access_profile": "cv",
                    "access_road_name": str(waypoint.get("name", "")),
                    "access_nodes": "|".join(str(item) for item in waypoint.get("nodes", [])),
                    "source_pool_path": source["source_pool_path"],
                    "source_pool_sha256": source["source_pool_sha256"],
                    "source_response_path": source["source_response_path"],
                    "source_response_sha256": source["source_response_sha256"],
                }
            )
            raw_payloads.append(
                {
                    "depot_id": source["depot_id"],
                    "request_url_path": f"/nearest/v1/driving/{lon},{lat}?number=1",
                    "response": payload,
                }
            )
    return access_rows, raw_payloads


def load_old_built() -> tuple[Any, list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    prd = load_module("depot_swap_prdfix_20260813", PRDFIX_SCRIPT)
    health_matches = [
        row for row in read_csv(REPO / "solver/reports/suite_prd_fix_20260812/suite_health_v3.csv")
        if row["instance_id"] == OLD_ID
    ]
    if len(health_matches) != 1:
        raise RuntimeError("active PRDFIX health row is not unique")
    health = health_matches[0]
    source_id = health["source_instance_id"]
    prior_matches = [
        row for row in prd.read_csv(prd.SOURCE_HEALTH)
        if row["source_instance_id"] == source_id
    ]
    if len(prior_matches) != 1:
        raise RuntimeError("depot-pair source health row is not unique")
    geometry, _, _ = prd.source_geometry(prior_matches[0], prd.SOURCE_DP)
    template = prd.dp.load_china81_bundle(
        REPO, f"cn-jjj-200c-{health['replicate']}-V2-LOCATIONS"
    )
    source_bundle = prd.load_existing_dp_bundle(
        health, template, geometry.home_depot_by_source_customer
    )
    prd.base.SOURCE_STATIC = prd.SOURCE_DP / "source_pools"
    prd.base.SOURCE_MATRICES = prd.SOURCE_DP / "directed_matrices"
    built = prd.base.build_instance(
        prd.new_identity("jjj", int(health["customer_count"]), health["replicate"]),
        prd.base.source_orders_by_instance()[source_id],
        geometry,
        prd.OneBundleCache(source_bundle),
    )
    old_nodes = read_csv(OLD_INSTANCE / "nodes.csv")
    old_orders = read_csv(OLD_INSTANCE / "orders.csv")
    old_mapping = read_csv(OLD_INSTANCE / "source_mapping.csv")
    if [dict(row) for row in built.node_rows] != old_nodes:
        raise RuntimeError("runtime PRDFIX reconstruction differs from saved nodes.csv")
    rebuilt_orders = [
        {key: str(value) for key, value in row.items()} for row in built.order_rows
    ]
    if rebuilt_orders != old_orders:
        raise RuntimeError("runtime PRDFIX reconstruction differs from saved orders.csv")
    return built, old_nodes, old_orders, old_mapping


def replace_depot_nodes(
    old_built: Any,
    old_nodes: Sequence[Mapping[str, str]],
    old_mapping: Sequence[Mapping[str, str]],
    access_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[Any], list[dict[str, Any]], list[dict[str, Any]]]:
    access_iter = iter(access_rows)
    old_obj_by_id = {node.node_id: node for node in old_built.instance.nodes}
    old_map_by_id = {row["new_node_id"]: row for row in old_mapping}
    objects: list[Any] = []
    node_rows: list[dict[str, Any]] = []
    mapping_rows: list[dict[str, Any]] = []
    for old_row in old_nodes:
        old_id = old_row["node_id"]
        old_obj = old_obj_by_id[old_id]
        if old_row["node_type"] == "depot":
            access = next(access_iter)
            new_id = str(access["depot_id"])
            objects.append(
                replace(
                    old_obj,
                    node_id=new_id,
                    x=float(access["scenario_access_longitude"]),
                    y=float(access["scenario_access_latitude"]),
                    city="beijing",
                )
            )
            node_rows.append(
                {
                    "node_id": new_id,
                    "node_type": "depot",
                    "city": "beijing",
                    "latitude": f"{float(access['scenario_access_latitude']):.7f}",
                    "longitude": f"{float(access['scenario_access_longitude']):.7f}",
                    "source_identity": access["osm_identity"],
                }
            )
            mapping_rows.append(
                {
                    "new_node_id": new_id,
                    "source_instance_id": NEW_POOL_ID,
                    "source_node_id": new_id,
                    "source_city": "beijing",
                    "latitude": f"{float(access['scenario_access_latitude']):.7f}",
                    "longitude": f"{float(access['scenario_access_longitude']):.7f}",
                    "mapping_class": "FROZEN_OSM_CENTER_TO_CV_OSRM_SCENARIO_ACCESS",
                    "origin_source_instance_id": "china9_metro_pool_20260812",
                    "origin_source_node_id": access["osm_identity"],
                }
            )
        else:
            objects.append(old_obj)
            node_rows.append(dict(old_row))
            old_map = old_map_by_id[old_id]
            mapping_rows.append(
                {
                    "new_node_id": old_id,
                    "source_instance_id": NEW_POOL_ID,
                    "source_node_id": old_id,
                    "source_city": old_map["source_city"],
                    "latitude": old_map["latitude"],
                    "longitude": old_map["longitude"],
                    "mapping_class": "IDENTITY_IN_DEDICATED_DEPOT_SWAP_MATRIX",
                    "origin_source_instance_id": old_map["source_instance_id"],
                    "origin_source_node_id": old_map["source_node_id"],
                }
            )
    try:
        next(access_iter)
        raise RuntimeError("too many access rows")
    except StopIteration:
        pass
    return objects, node_rows, mapping_rows


def build_directed_matrices(
    matrix_root: Path,
    node_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    required = dp.route_pairs_for_nodes(node_rows)
    profiles: dict[str, Any] = {}
    stats: list[dict[str, Any]] = []
    checks: dict[str, dict[str, Any]] = {}
    for profile in ("cv", "ev"):
        cache = matrix_root / f"route_cache_jjj_{profile}.sqlite"
        source_cache = OLD_MATRIX_ROOT / f"route_cache_jjj_{profile}.sqlite"
        source_before = sha256(source_cache)
        db = dp.matrix_builder.init_db(cache)
        try:
            reused = dp.seed_cache(db, source_cache, required)
            with dp.RouterSession("jjj", profile, matrix_root) as router:
                present, queried = dp.ensure_routes(
                    db,
                    router.endpoint,
                    required,
                    matrix_root / f"checkpoint_jjj_{profile}_depot_swap.json",
                )
            route_rows = dp.load_route_rows(db, required)
            profiles[profile] = dp.write_profile_matrices(
                matrix_root / "instances" / NEW_POOL_ID / profile,
                node_rows,
                route_rows,
            )
            db.commit()
        finally:
            db.close()
        source_after = sha256(source_cache)
        if source_before != source_after:
            raise RuntimeError(f"frozen source route cache changed: {source_cache}")
        profile_checks: dict[str, Any] = {}
        matrices = profiles[profile]
        for field, matrix in (
            ("road_distance_m", matrices.distance_m),
            ("road_duration_s", matrices.duration_s),
            ("road_sum_v2d_m3_s2", matrices.sum_v2d_m3_s2),
        ):
            n = len(matrix)
            asymmetric = sum(
                abs(float(matrix[i][j]) - float(matrix[j][i])) > 1.0e-9
                for i in range(n) for j in range(i + 1, n)
            )
            zero_diagonal = sum(abs(float(matrix[i][i])) <= 1.0e-12 for i in range(n))
            profile_checks[field] = {
                "rows": n,
                "columns": n,
                "zero_diagonal_count": zero_diagonal,
                "asymmetric_unordered_pair_count": asymmetric,
            }
        checks[profile] = profile_checks
        graph = dp.graph_identity("jjj", profile)
        graph_manifest = json.loads(
            (REPO / graph["graph_manifest"]).read_text(encoding="utf-8")
        )
        versions = []
        for log in sorted((matrix_root / "router_logs").glob(f"*jjj-{profile}-*.log")):
            if log.name.startswith("._"):
                continue
            match = re.search(r"starting up engines, (v[^\s]+)", log.read_text(encoding="utf-8"))
            if match:
                versions.append(match.group(1))
        if len(set(versions)) != 1:
            raise RuntimeError(f"OSRM runtime version is not unique for {profile}: {versions}")
        graph["clip_sha256"] = graph_manifest["clip_sha256"]
        graph["osrm_version"] = versions[0]
        stats.append(
            {
                "evidence_class": "FACT",
                "region": "jjj",
                "profile": profile,
                "required_directed_pairs": len(required),
                "reused_from_frozen_depotpair_cache": reused,
                "present_before_router": present,
                "queried_from_frozen_osrm_graph": queried,
                "straight_line_completion_count": 0,
                "symmetric_completion_count": 0,
                "source_cache_path": str(source_cache.relative_to(REPO)),
                "source_cache_sha256_before": source_before,
                "source_cache_sha256_after": source_after,
                **graph,
            }
        )
    remove_appledouble(matrix_root)
    write_json(matrix_root / "artifact_hashes.json", tree_hashes(matrix_root))
    return profiles, stats, checks


def make_built(
    old_built: Any,
    node_objects: Sequence[Any],
    node_rows: Sequence[Mapping[str, Any]],
    mapping_rows: Sequence[Mapping[str, Any]],
    profiles: Mapping[str, Any],
    order_rows: Sequence[Mapping[str, Any]],
    homes: Mapping[str, str],
    shift_flags: Sequence[str] = (),
) -> Any:
    instance = replace(
        old_built.instance,
        nodes=list(node_objects),
        distance_matrix=[list(row) for row in profiles["cv"].distance_m],
        road_profiles=dict(profiles),
    )
    identity = base.ParsedIdentity(
        source_instance_id=OLD_ID,
        new_instance_id=NEW_ID,
        region="jjj",
        size=50,
        replicate="01",
    )
    geometry = base.GeometryChoice(
        mode="REAL_OSM_DEPOT_SWAP_P56_FIXED_CUSTOMERS",
        matrix_source_instance_id=NEW_POOL_ID,
        depot_ids=tuple(row["depot_id"] for row in DEPOTS),
        customer_source_ids=tuple(sorted(row["customer_id"] for row in order_rows)),
        home_depot_by_source_customer=MappingProxyType(dict(homes)),
        attempted_rebuild=True,
        rebuild_succeeded=True,
        reanchored_customer_count=0,
        note=(
            "P56 user-approved real OSM depot swap; customers and all intrinsic "
            "order/shift fields are frozen; CV-defined scenario access points; "
            "no new contestability percentage upper bound"
        ),
    )
    order_copies = tuple(dict(row) for row in order_rows)
    by_customer = MappingProxyType({row["customer_id"]: row for row in order_copies})
    return base.BuiltInstance(
        identity=identity,
        source_bundle=old_built.source_bundle,
        instance=instance,
        prices=old_built.prices,
        time_profile=tuple(dict(row) for row in old_built.time_profile),
        node_rows=tuple(dict(row) for row in node_rows),
        order_rows=order_copies,
        source_mapping_rows=tuple(dict(row) for row in mapping_rows),
        orders_by_customer=by_customer,
        customer_home_depot=MappingProxyType(dict(homes)),
        geometry=geometry,
        shift_assignment_flags=tuple(shift_flags),
    )


def load_saved_depot_swap_built(
    output_root: Path = DEFAULT_OUTPUT,
) -> Any:
    """Read the saved same-city two-depot package without routing or search.

    This is the dedicated adapter used by the preceding depot-pair/PRDFIX
    method.  The generic China81 loader intentionally assumes one depot per
    city and therefore cannot represent this approved Beijing/Beijing pair
    without illegally changing customer city fields.
    """
    from setp_solver.instance_loader import load_profiled_road_matrices

    root = Path(output_root).resolve()
    old_built, old_nodes, _, old_mapping = load_old_built()
    access_rows = read_csv(root / "facility_access_points.csv")
    node_objects, expected_nodes, _ = replace_depot_nodes(
        old_built, old_nodes, old_mapping, access_rows
    )
    saved_nodes = read_csv(root / "instances" / NEW_ID / "nodes.csv")
    if expected_nodes != saved_nodes:
        raise RuntimeError("saved depot-swap nodes differ from adapter reconstruction")
    profiles = load_profiled_road_matrices(
        root / "directed_matrices" / "instances" / NEW_POOL_ID,
        list(node_objects),
    )
    orders = read_csv(root / "instances" / NEW_ID / "orders.csv")
    mapping = read_csv(root / "instances" / NEW_ID / "source_mapping.csv")
    homes = {row["customer_id"]: row["home_depot_id"] for row in orders}
    flags = [
        f"{row['customer_id']}: fixed shift unreachable"
        for row in orders
        if row["shift_reachability_status"]
        == "FLAG_FIXED_SHIFT_UNREACHABLE_NO_MUTATION"
    ]
    built = make_built(
        old_built,
        node_objects,
        saved_nodes,
        mapping,
        profiles,
        orders,
        homes,
        flags,
    )
    fleet_rows = read_csv(root / "fleet_caps.csv")
    num_cv = sum(int(row["base_all_cv_routes_Rd"]) for row in fleet_rows)
    num_ev = sum(int(row["base_all_ev_routes_Re"]) for row in fleet_rows)
    return replace(
        built,
        instance=replace(built.instance, num_cv=num_cv, num_ev=num_ev),
    )


def recompute_depot_derived_orders(
    old_orders: Sequence[Mapping[str, str]],
    preliminary: Any,
    contest_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
    contest_by_customer = {row["customer_id"]: row for row in contest_rows}
    homes = {
        customer: str(row["nearest_depot"])
        for customer, row in contest_by_customer.items()
    }
    output: list[dict[str, Any]] = []
    flags: list[str] = []
    for old in old_orders:
        customer = old["customer_id"]
        row: dict[str, Any] = dict(old)
        row["instance_id"] = NEW_ID
        home = homes[customer]
        _, duration_s, _ = preliminary.instance.arc_metrics(
            home, customer, "cv", fallback_speed_mps=1.0
        )
        travel_min = float(duration_s) / 60.0
        shift_start = float(old["shift_start_minute"])
        late = float(old["time_window_late_minute"])
        reachable = shift_start + travel_min <= late + 1.0e-9
        row["home_depot_id"] = home
        row["home_to_customer_travel_minute"] = travel_min
        row["preferred_shift_reachable"] = 1 if reachable else 0
        row["alternative_shift_reachable"] = ""
        row["reachability_window_delay_minute"] = 0.0
        if reachable:
            row["shift_reachability_status"] = "PASS_PREFERRED_SHIFT"
        else:
            row["shift_reachability_status"] = "FLAG_FIXED_SHIFT_UNREACHABLE_NO_MUTATION"
            flags.append(
                f"{customer}: fixed {old['shift_id']} shift cannot be reached from {home}"
            )
        output.append(row)
    return output, homes, flags


def audit_invariance(
    old_orders: Sequence[Mapping[str, str]],
    new_orders: Sequence[Mapping[str, Any]],
    old_nodes: Sequence[Mapping[str, str]],
    new_nodes: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    old_by_customer = {row["customer_id"]: row for row in old_orders}
    new_by_customer = {row["customer_id"]: row for row in new_orders}
    if set(old_by_customer) != set(new_by_customer) or len(old_by_customer) != 50:
        raise RuntimeError("customer set changed")
    rows: list[dict[str, Any]] = []
    for group, fields in INVARIANT_GROUPS:
        mismatches = []
        for customer in sorted(old_by_customer):
            for field in fields:
                if str(old_by_customer[customer].get(field, "")) != str(new_by_customer[customer].get(field, "")):
                    mismatches.append(f"{customer}.{field}")
        row = {
            "evidence_class": "FACT",
            "group": group,
            "fields": "|".join(fields),
            "customer_rows_checked": 50,
            "field_cells_checked": 50 * len(fields),
            "mismatch_count": len(mismatches),
            "status": "PASS_EXACT" if not mismatches else "FAIL",
            "old_projection_sha256": canonical_sha(old_orders, fields),
            "new_projection_sha256": canonical_sha(new_orders, fields),
            "mismatches": "|".join(mismatches),
        }
        if mismatches:
            raise RuntimeError(f"customer invariance failed: {group}: {mismatches[:5]}")
        rows.append(row)
    allowed_changes = {"instance_id", *DERIVED_ORDER_FIELDS}
    all_fields = tuple(old_orders[0])
    unexpected = []
    for customer in sorted(old_by_customer):
        for field in all_fields:
            if field in allowed_changes:
                continue
            if str(old_by_customer[customer][field]) != str(new_by_customer[customer][field]):
                unexpected.append(f"{customer}.{field}")
    if unexpected:
        raise RuntimeError(f"unexpected order changes: {unexpected[:5]}")
    old_customer_nodes = [row for row in old_nodes if row["node_type"] == "customer"]
    new_customer_nodes = [row for row in new_nodes if row["node_type"] == "customer"]
    if old_customer_nodes != new_customer_nodes:
        raise RuntimeError("customer nodes.csv rows changed")
    rows.append(
        {
            "evidence_class": "FACT",
            "group": "nodes.csv 客户整行",
            "fields": "|".join(old_customer_nodes[0]),
            "customer_rows_checked": 50,
            "field_cells_checked": 50 * len(old_customer_nodes[0]),
            "mismatch_count": 0,
            "status": "PASS_EXACT",
            "old_projection_sha256": hashlib.sha256(
                json.dumps(old_customer_nodes, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "new_projection_sha256": hashlib.sha256(
                json.dumps(new_customer_nodes, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "mismatches": "",
        }
    )
    return rows


def contest_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    output: dict[str, Any] = {"total": total}
    for pct in (20, 25, 30):
        count = sum(int(row[f"contestable_at_{pct}pct"]) for row in rows)
        output[f"count_{pct}"] = count
        output[f"share_{pct}"] = count / total
    output["lower_bound_25pct_count"] = math.ceil(0.30 * total)
    output["lower_gate"] = (
        "PASS_RETAINED_30PCT_LOWER_BOUND"
        if output["share_25"] >= 0.30
        else "FAIL_RETAINED_30PCT_LOWER_BOUND"
    )
    output["upper_gate"] = "NOT_APPLIED_FOR_THIS_NON_OVERLAPPING_PAIR_NO_NEW_PERCENTAGE_CAP"
    return output


def witness_rows(built: Any, witness: Any) -> list[dict[str, Any]]:
    if witness.solution is None:
        return []
    scheduled_lookup = {
        (physical, index): item
        for physical, items in witness.scheduled_by_physical.items()
        for index, item in enumerate(items, start=1)
    }
    output = []
    for route in witness.solution.routes:
        physical, trip_text = route.vehicle_id.split("#T", 1)
        item = scheduled_lookup[(physical, int(trip_text))]
        output.append(
            {
                "instance_id": NEW_ID,
                "witness_status": witness.status,
                "physical_vehicle_id": physical,
                "route_vehicle_id": route.vehicle_id,
                "depot_id": item.plan.depot_id,
                "shift_id": item.plan.shift_id,
                "customers": "|".join(item.plan.customers),
                "customer_count": len(item.plan.customers),
                "volume_m3": item.plan.volume_m3,
                "demand_kg": item.plan.demand_kg,
                "departure_minute": item.departure_second / 60.0,
                "return_minute": item.return_second / 60.0,
                "distance_km": item.plan.distance_m / 1000.0,
            }
        )
    return output


def geometric_split(
    customer_rows: Sequence[Mapping[str, Any]],
    depots: Sequence[tuple[str, tuple[float, float]]],
    orders_by_customer: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    demand: defaultdict[str, float] = defaultdict(float)
    nearest_distances = []
    for customer in customer_rows:
        customer_id = str(customer["node_id"])
        point = (float(customer["latitude"]), float(customer["longitude"]))
        ranked = sorted(
            (haversine_km(point, coords), depot_id) for depot_id, coords in depots
        )
        distance, depot_id = ranked[0]
        counts[depot_id] += 1
        demand[depot_id] += float(orders_by_customer[customer_id]["demand_kg"])
        nearest_distances.append(distance)
    return {
        "customer_counts": {depot_id: counts[depot_id] for depot_id, _ in depots},
        "demand_kg": {depot_id: demand[depot_id] for depot_id, _ in depots},
        "nearest_depot_customer_median_km": statistics.median(nearest_distances),
    }


def geometry_metrics(
    old_nodes: Sequence[Mapping[str, str]],
    new_nodes: Sequence[Mapping[str, Any]],
    old_orders: Sequence[Mapping[str, str]],
    new_orders: Sequence[Mapping[str, Any]],
    access_rows: Sequence[Mapping[str, Any]],
    contest_rows: Sequence[Mapping[str, Any]],
    profiles: Mapping[str, Any],
) -> dict[str, Any]:
    customer_rows = [row for row in old_nodes if row["node_type"] == "customer"]
    customer_points = [
        (float(row["latitude"]), float(row["longitude"])) for row in customer_rows
    ]
    center = (
        statistics.fmean(point[0] for point in customer_points),
        statistics.fmean(point[1] for point in customer_points),
    )
    lat_min, lat_max = min(p[0] for p in customer_points), max(p[0] for p in customer_points)
    lon_min, lon_max = min(p[1] for p in customer_points), max(p[1] for p in customer_points)
    range_ns = haversine_km((lat_min, center[1]), (lat_max, center[1]))
    range_ew = haversine_km((center[0], lon_min), (center[0], lon_max))
    pair_median = statistics.median(
        haversine_km(left, right) for left, right in combinations(customer_points, 2)
    )
    old_depots = [row for row in old_nodes if row["node_type"] == "depot"]
    old_depot_points = [
        (row["node_id"], (float(row["latitude"]), float(row["longitude"])))
        for row in old_depots
    ]
    new_access_points = [
        (
            str(row["depot_id"]),
            (float(row["scenario_access_latitude"]), float(row["scenario_access_longitude"])),
        )
        for row in access_rows
    ]
    new_center_points = [
        (
            str(row["depot_id"]),
            (float(row["osm_center_latitude"]), float(row["osm_center_longitude"])),
        )
        for row in access_rows
    ]
    old_by_customer = {row["customer_id"]: row for row in old_orders}
    new_by_customer = {row["customer_id"]: row for row in new_orders}
    old_split = geometric_split(customer_rows, old_depot_points, old_by_customer)
    new_access_split = geometric_split(customer_rows, new_access_points, new_by_customer)
    new_center_split = geometric_split(customer_rows, new_center_points, new_by_customer)
    old_formal_counts = Counter(row["home_depot_id"] for row in old_orders)
    old_formal_demand: defaultdict[str, float] = defaultdict(float)
    for row in old_orders:
        old_formal_demand[row["home_depot_id"]] += float(row["demand_kg"])
    new_formal_counts = Counter(str(row["nearest_depot"]) for row in contest_rows)
    new_formal_demand: defaultdict[str, float] = defaultdict(float)
    for row in contest_rows:
        new_formal_demand[str(row["nearest_depot"])] += float(new_by_customer[row["customer_id"]]["demand_kg"])
    def depot_geometry(points: Sequence[tuple[str, tuple[float, float]]], split: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "depot_distance_km": haversine_km(points[0][1], points[1][1]),
            "depot_to_customer_center_km": {
                depot_id: haversine_km(coords, center) for depot_id, coords in points
            },
            **dict(split),
            "nearest_to_customer_pair_median_ratio": (
                float(split["nearest_depot_customer_median_km"]) / pair_median
            ),
        }
    node_ids = [row["node_id"] for row in new_nodes]
    i, j = node_ids.index(DEPOTS[0]["depot_id"]), node_ids.index(DEPOTS[1]["depot_id"])
    road = {}
    for profile, matrices in profiles.items():
        road[profile] = {
            "a_to_b_distance_km": matrices.distance_m[i][j] / 1000.0,
            "b_to_a_distance_km": matrices.distance_m[j][i] / 1000.0,
            "a_to_b_duration_min": matrices.duration_s[i][j] / 60.0,
            "b_to_a_duration_min": matrices.duration_s[j][i] / 60.0,
        }
    return {
        "customer_center": {"latitude": center[0], "longitude": center[1]},
        "customer_range_ew_km": range_ew,
        "customer_range_ns_km": range_ns,
        "customer_pair_median_km": pair_median,
        "old_scenario_access_geometry": depot_geometry(old_depot_points, old_split),
        "new_osm_center_proxy_geometry": depot_geometry(new_center_points, new_center_split),
        "new_scenario_access_geometry": depot_geometry(new_access_points, new_access_split),
        "old_formal_cv_cost_home_split": {
            "customer_counts": dict(old_formal_counts),
            "demand_kg": dict(old_formal_demand),
        },
        "new_formal_cv_cost_home_split": {
            "customer_counts": dict(new_formal_counts),
            "demand_kg": dict(new_formal_demand),
        },
        "directed_depot_road_metrics": road,
    }


def fmt(value: Any, digits: int = 6) -> str:
    if value in (None, ""):
        return "—"
    if isinstance(value, float):
        if math.isinf(value):
            return "∞"
        return f"{value:.{digits}f}"
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    report_root = args.report_root.resolve()
    if output_root.exists() or report_root.exists():
        raise FileExistsError("target output/report already exists; refusing overwrite")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    report_root.parent.mkdir(parents=True, exist_ok=True)
    output_stage = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.partial-", dir=output_root.parent))
    report_stage = Path(tempfile.mkdtemp(prefix=f".{report_root.name}.partial-", dir=report_root.parent))
    started = datetime.now(UTC)
    protected_before = protected_hashes()
    if protected_before != PROTECTED_EXPECTED:
        raise RuntimeError(f"protected baseline mismatch: {protected_before}")
    old_before = snapshot_tree(OLD_INSTANCE)
    source_cache_before = {
        profile: sha256(OLD_MATRIX_ROOT / f"route_cache_jjj_{profile}.sqlite")
        for profile in ("cv", "ev")
    }

    source_rows = source_depot_rows()
    matrix_root = output_stage / "directed_matrices"
    matrix_root.mkdir(parents=True, exist_ok=False)
    access_rows, snap_payloads = snap_depots(source_rows, matrix_root)
    write_csv(output_stage / "facility_access_points.csv", access_rows)
    write_json(output_stage / "facility_access_nearest_raw.json", snap_payloads)

    old_built, old_nodes, old_orders, old_mapping = load_old_built()
    node_objects, node_rows, mapping_rows = replace_depot_nodes(
        old_built, old_nodes, old_mapping, access_rows
    )
    profiles, matrix_stats, matrix_checks = build_directed_matrices(matrix_root, node_rows)

    preliminary_orders = [{**row, "instance_id": NEW_ID} for row in old_orders]
    preliminary_homes = {row["customer_id"]: row["home_depot_id"] for row in old_orders}
    preliminary = make_built(
        old_built, node_objects, node_rows, mapping_rows, profiles,
        preliminary_orders, preliminary_homes,
    )
    preliminary_contest = base.contestability_rows(preliminary)
    order_rows, homes, shift_flags = recompute_depot_derived_orders(
        old_orders, preliminary, preliminary_contest
    )
    built = make_built(
        old_built, node_objects, node_rows, mapping_rows, profiles,
        order_rows, homes, shift_flags,
    )
    contest_rows = [
        {
            **dict(row),
            "instance_id": NEW_ID,
            "home_depot_id": row["nearest_depot"],
        }
        for row in preliminary_contest
    ]
    for row in contest_rows:
        if row["home_depot_id"] != row["nearest_depot"]:
            raise RuntimeError("formal home depot assignment did not converge")
    contest = contest_summary(contest_rows)
    invariance_rows = audit_invariance(old_orders, order_rows, old_nodes, node_rows)

    witness = None
    fleet: dict[str, Any] = {}
    lunch: dict[str, Any] = {"rows": []}
    per_km: dict[str, Any] = {}
    distance_health: dict[str, Any] = {}
    if contest["lower_gate"].startswith("PASS"):
        witness = base.build_witness(built)
        fleet = base.fleet_health(witness)
        lunch = base.lunch_health(built, witness)
        if witness.status == "PASS" and not shift_flags:
            per_km = base.per_km_health(built, witness)
            critical = [
                float(per_km["scenarios"][name]["critical_daily_km"])
                for name in ("valley", "flat", "peak")
            ]
            distance_health = base.witness_distance_health(built, witness, critical)
    edf_gate = (
        "PASS" if witness is not None and witness.status == "PASS" and not shift_flags
        else "NOT_RUN_AFTER_CONTESTABILITY_FAIL" if witness is None
        else "FAIL"
    )
    mixed_gate = (
        str(distance_health.get("two_sides", "NOT_RUN_AFTER_EDF_FAIL"))
        if edf_gate == "PASS" else "NOT_RUN_AFTER_EDF_FAIL"
    )
    if not contest["lower_gate"].startswith("PASS"):
        verdict = "HALT_CONTESTABILITY_LOWER_GATE_FAILED"
    elif edf_gate != "PASS":
        verdict = "HALT_EDF_WITNESS_FAILED"
    elif mixed_gate != "PASS_TWO_SIDES":
        verdict = "HALT_MIXED_FLEET_TWO_SIDES_FAILED"
    else:
        verdict = "PASS_ALL_THREE_FORMAL_GATES"

    geometry = geometry_metrics(
        old_nodes, node_rows, old_orders, order_rows, access_rows, contest_rows, profiles
    )
    route_rows = witness_rows(built, witness) if witness is not None else []

    instance_root = output_stage / "instances" / NEW_ID
    write_csv(instance_root / "nodes.csv", node_rows)
    write_csv(instance_root / "orders.csv", order_rows, list(old_orders[0]))
    mapping_fields = [
        "new_node_id", "source_instance_id", "source_node_id", "source_city",
        "latitude", "longitude", "mapping_class", "origin_source_instance_id",
        "origin_source_node_id",
    ]
    write_csv(instance_root / "source_mapping.csv", mapping_rows, mapping_fields)
    write_csv(instance_root / "contestability.csv", contest_rows)
    shift_contract = json.loads(
        (OLD_INSTANCE / "shift_contract.json").read_text(encoding="utf-8")
    )
    shift_contract["instance_id"] = NEW_ID
    shift_contract["source_instance_id"] = OLD_ID
    shift_contract["customer_shift_policy"] = (
        "COPY_EXACT_NO_REASSIGNMENT_NO_WINDOW_MOVEMENT"
    )
    shift_contract["fixed_shift_reachability_audit"] = {
        "unreachable_count": len(shift_flags),
        "unreachable_flags": shift_flags,
        "home_to_customer_duration_profile": "frozen directed CV OSRM",
        "time_window_or_shift_mutation_count": 0,
    }
    write_json(instance_root / "shift_contract.json", shift_contract)
    output_relative = output_root.relative_to(REPO)
    matrix_authority_relative = output_relative / "directed_matrices"
    matrix_reference = {
        "schema": "resetp.china81-suite-matrix-reference.v1",
        "instance_id": NEW_ID,
        "node_mapping_file": "source_mapping.csv",
        "source_authority": str(matrix_authority_relative),
        "source_instance_id": NEW_POOL_ID,
        "matrix_source_instance_id": NEW_POOL_ID,
        "node_order": [row["node_id"] for row in node_rows],
        "selection_semantics": "matrix rows and columns already align exactly with nodes.csv",
        "profiles": {
            profile: {
                filename: {
                    "path": str(
                        matrix_authority_relative
                        / "instances" / NEW_POOL_ID / profile / filename
                    ),
                    "sha256": sha256(matrix_root / "instances" / NEW_POOL_ID / profile / filename),
                }
                for filename in (
                    "road_distance_m.csv", "road_duration_s.csv",
                    "road_sum_v2d_m3_s2.csv", "raw_runs.csv",
                )
            }
            for profile in ("cv", "ev")
        },
        "straight_line_completion_count": 0,
        "symmetric_completion_count": 0,
    }
    write_json(instance_root / "matrix_reference.json", matrix_reference)
    provenance = json.loads(
        (OLD_INSTANCE / "provenance.json").read_text(encoding="utf-8")
    )
    provenance.update(
        {
            "evidence_class": "FACT",
            "schema": "resetp.china81-suite-instance-provenance.v1",
            "user_decision": "丙改（放宽可争夺上限，取那对 25/25 的真实园区）。",
            "instance_id": NEW_ID,
            "new_instance_id": NEW_ID,
            "source_instance_id": OLD_ID,
            "source_task_instance_id": old_built.identity.source_instance_id,
            "matrix_source_instance_id": NEW_POOL_ID,
            "geometry_mode": "REAL_OSM_DEPOT_SWAP_P56_FIXED_CUSTOMERS",
            "geometry_note": (
                "P56 approved real OSM depot swap; 50 customer intrinsic rows frozen; "
                f"formal 25pct contestability {contest['count_25']}/50; retained 30pct "
                "lower bound; percentage upper bound not applied for this non-overlapping pair"
            ),
            "reanchored_customer_count": 0,
            "depot_swap_only": True,
            "customer_intrinsic_fields_frozen": True,
            "depot_derived_order_fields_recomputed": list(DERIVED_ORDER_FIELDS),
            "formal_search_evaluations": 0,
            "old_instance_overwritten": False,
            "source_matrix_authority": str(matrix_authority_relative),
            "packaged_static_authority": str(output_relative),
            "packaged_order_authority": str(output_relative / "orders.csv"),
            "customer_and_station_source_static_authority": provenance[
                "source_static_authority"
            ],
            "depot_identity_authority": str(OSM_POOL.relative_to(REPO)),
            "depot_identity_raw_responses": [
                row["source_response_path"] for row in access_rows
            ],
            "parameter_authority_hashes": {
                str(path): sha256(REPO / path) for path in base.PARAMETER_AUTHORITIES
            },
            "contestability_upper_rule": (
                "for this pair only, percentage upper bound not applied because "
                "its anti-overlap intent is directly guarded by the observed depot separation; "
                "no replacement percentage or distance threshold introduced"
            ),
            "facility_access_semantics": (
                "SCENARIO_ROAD_ACCESS_POINT_NOT_OBSERVED_TRUCK_GATE"
            ),
            "facility_access_points": access_rows,
            "matrix_build": matrix_stats,
        }
    )
    write_json(
        instance_root / "provenance.json",
        provenance,
    )
    witness_status = witness.status if witness is not None else "NOT_RUN"
    witness_reason = (
        witness.reason if witness is not None else "contestability lower gate failed"
    )
    violation_count = len(witness.violations) if witness is not None else 0
    violations = list(witness.violations) if witness is not None else []
    write_json(
        instance_root / "witness_status.json",
        {
            "status": witness_status,
            "reason": witness_reason,
            "search_evaluations": 0,
            "violation_count": violation_count,
            "violations": violations,
            "construction_rule": (
                "home-depot two-shift EDF deterministic first-feasible packing; "
                "one AM route per vehicle; exact minimum feasible PM chain cover; "
                "same-depot cross-shift vehicle reuse"
            ),
            "contestability": contest,
            "edf_witness_gate": edf_gate,
            "witness_status": witness_status,
            "witness_reason": witness_reason,
            "served_customers": witness.served_customers if witness is not None else "",
            "served_demand_kg": witness.served_demand_kg if witness is not None else "",
            "checker_violation_count": violation_count,
            "mixed_fleet_two_sides_gate": mixed_gate,
            "verdict": verdict,
        },
    )
    write_json(instance_root / "artifact_hashes.json", tree_hashes(instance_root))

    write_csv(output_stage / "customer_invariance.csv", invariance_rows)
    write_csv(output_stage / "matrix_build_rows.csv", matrix_stats)
    write_csv(
        output_stage / "health_witness_routes.csv",
        route_rows,
        (
            list(route_rows[0]) if route_rows else [
                "instance_id", "witness_status", "physical_vehicle_id", "route_vehicle_id",
                "depot_id", "shift_id", "customers", "customer_count", "volume_m3",
                "demand_kg", "departure_minute", "return_minute", "distance_km",
            ]
        ),
    )
    write_csv(
        output_stage / "lunch_charge_rows.csv",
        list(lunch.get("rows", [])),
        (
            list(lunch["rows"][0]) if lunch.get("rows") else [
                "instance_id", "physical_vehicle_id", "depot_id", "first_pm_volume_m3",
                "loading_hours", "available_charge_hours",
                "chargeable_kwh_60kw_from_zero", "curve_id",
            ]
        ),
    )
    write_json(output_stage / "geometry_metrics.json", geometry)
    write_json(output_stage / "matrix_checks.json", matrix_checks)

    depot_counts: Counter[str] = Counter()
    if witness is not None and witness.status == "PASS":
        for scheduled in witness.scheduled_by_physical.values():
            depot_counts[scheduled[0].plan.depot_id] += 1
    else:
        depot_counts.update(homes.values())
    fleet_caps = []
    for depot_id in (row["depot_id"] for row in DEPOTS):
        cap = max(1, depot_counts[depot_id])
        fleet_caps.append(
            {
                "instance_id": NEW_ID,
                "depot_id": depot_id,
                "city": str(depot_id).removeprefix("D_"),
                "base_all_cv_routes_Rd": cap,
                "base_all_ev_routes_Re": cap,
                "num_cv": cap,
                "num_ev": cap,
                "total_fleet_cap": 2 * cap,
                "default_fleet_electrification_percent_metadata_only": "ENDOGENOUS_NOT_FIXED",
                "configured_depot_gun_count_if_finite": 2,
                "depot_charge_power_kw": base.DEPOT_POWER_KW,
                "depot_charger_capacity_default": "UNBOUNDED",
                "fleet_parameter_class": base.FLEET_PARAMETER_CLASS_ID,
                "fleet_cap_source": (
                    "EDF_TWO_SHIFT_PHYSICAL_WITNESS"
                    if witness is not None and witness.status == "PASS"
                    else "CUSTOMER_COUNT_CONSERVATIVE_CEILING_WITNESS_FAILED"
                ),
                "charger_parameter_class": (
                    "P43_I_CHINA_LOGISTICS_DEPOT_DC_60KW_DEFAULT"
                ),
            }
        )
    write_csv(output_stage / "fleet_caps.csv", fleet_caps)

    old_facilities = read_csv(OLD_ROOT / "facilities.csv")
    beijing_facility_matches = [row for row in old_facilities if row["city"] == "beijing"]
    if len(beijing_facility_matches) != 1:
        raise RuntimeError("source Beijing facility row is not unique")
    beijing_facility = beijing_facility_matches[0]
    facility_rows = []
    for index, access in enumerate(access_rows):
        facility = dict(beijing_facility)
        facility["city"] = (
            "beijing" if index == 0 else str(access["depot_id"]).removeprefix("D_")
        )
        facility["depot_name"] = access["name"]
        facility["depot_lon"] = access["scenario_access_longitude"]
        facility["depot_lat"] = access["scenario_access_latitude"]
        facility["depot_point_semantics"] = access["access_semantics"]
        facility["depot_source"] = (
            f"https://www.openstreetmap.org/{access['osm_identity']}; "
            "scenario access from frozen CV OSRM nearest"
        )
        facility["depot_site_power_kw_shadow"] = f"{base.DEPOT_POWER_KW:.1f}"
        facility["depot_gun_count"] = "2"
        facility["depot_parameter_class"] = (
            "P43_I_CHINA_LOGISTICS_DEPOT_DC_60KW_DEFAULT"
        )
        facility_rows.append(facility)
    first_specific = dict(facility_rows[0])
    first_specific["city"] = str(access_rows[0]["depot_id"]).removeprefix("D_")
    facility_rows.append(first_specific)
    facility_rows.sort(key=lambda row: row["city"])
    write_csv(output_stage / "facilities.csv", facility_rows, list(beijing_facility))
    write_csv(output_stage / "orders.csv", order_rows, list(old_orders[0]))
    write_csv(
        output_stage / "node_city_membership.csv",
        [
            {
                "instance_id": NEW_ID,
                "node_id": row["new_node_id"],
                "declared_city": row["source_city"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "gis_status": "PASS_DECLARED_CITY_BOUNDARY",
                "source_instance_id": row["origin_source_instance_id"],
                "source_node_id": row["origin_source_node_id"],
            }
            for row in mapping_rows
        ],
    )
    write_csv(
        output_stage / "instance_catalog.csv",
        [
            {
                "instance_id": NEW_ID,
                "source_instance_id": OLD_ID,
                "region": "jjj",
                "customer_count": 50,
                "replicate": "01",
                "depot_count": 2,
                "cities": "beijing",
                "node_count": 53,
                "matrix_source_instance_id": NEW_POOL_ID,
                "formal_search_evaluations": 0,
                "instance_artifact_manifest_sha256": sha256(
                    instance_root / "artifact_hashes.json"
                ),
            }
        ],
    )
    write_json(
        output_stage / "vehicle_cost_contract.json",
        {
            "schema": "resetp.vehicle-cost-contract.v3-suite",
            "cv": {
                "non_energy_cny_per_km": base.CV_NON_ENERGY_CNY_PER_KM,
                "daily_fixed_cny": base.CV_FIXED_CNY_PER_DAY,
            },
            "ev": {
                "effective_non_energy_cny_per_km": base.EV_NON_ENERGY_CNY_PER_KM,
                "daily_fixed_cny": base.EV_FIXED_CNY_PER_DAY,
                "daily_fixed_premium_vs_cv_cny": base.EV_FIXED_PREMIUM_CNY_PER_DAY,
            },
        },
    )
    write_json(
        output_stage / "build_status.json",
        {
            "status": "SWAPDONE",
            "completed_instances": 1,
            "target_instances": 1,
            "last_instance_id": NEW_ID,
            "formal_search_evaluations": 0,
            "verdict": verdict,
        },
    )

    health_row: dict[str, Any] = {
        "evidence_class": "FACT",
        "instance_id": NEW_ID,
        "source_instance_id": OLD_ID,
        "customer_count": 50,
        "contestable_count_20pct": contest["count_20"],
        "contestable_share_20pct": contest["share_20"],
        "contestable_count_25pct": contest["count_25"],
        "contestable_share_25pct": contest["share_25"],
        "contestable_count_30pct": contest["count_30"],
        "contestable_share_30pct": contest["share_30"],
        "contestability_lower_gate": contest["lower_gate"],
        "contestability_upper_gate": contest["upper_gate"],
        "edf_witness_gate": edf_gate,
        "fixed_shift_unreachable_count": len(shift_flags),
        "served_customers": witness.served_customers if witness is not None else "",
        "total_customers": 50,
        "served_demand_kg": witness.served_demand_kg if witness is not None else "",
        "total_demand_kg": sum(float(row["demand_kg"]) for row in order_rows),
        "checker_violation_count": len(witness.violations) if witness is not None else "",
        **{f"fleet_{key}": value for key, value in fleet.items()},
        "lunch_reused_vehicle_count": lunch.get("vehicle_count", ""),
        "lunch_chargeable_kwh_60kw_total": lunch.get("total_kwh", ""),
        "mixed_fleet_two_sides_gate": mixed_gate,
        "formal_search_evaluations": 0,
        "verdict": verdict,
    }
    if per_km:
        health_row.update(
            {
                "per_km_basis": per_km["basis"],
                "cv_fuel_l_per_km": per_km["cv_fuel_l_per_km"],
                "cv_cost_cny_per_km": per_km["cv_cost_cny_per_km"],
                "cv_emission_kgco2e_per_km": per_km["cv_emission_kg_per_km"],
                "ev_drive_kwh_per_km": per_km["ev_kwh_per_km"],
                **{
                    f"critical_daily_km_{name}": per_km["scenarios"][name]["critical_daily_km"]
                    for name in ("valley", "flat", "peak")
                },
                "witness_daily_km_min": min(distance_health["daily_distances"]),
                "witness_daily_km_median": statistics.median(distance_health["daily_distances"]),
                "witness_daily_km_max": max(distance_health["daily_distances"]),
                "critical_band_below_vehicle_count": distance_health["below"],
                "critical_band_overlap_vehicle_count": distance_health["within"],
                "critical_band_above_vehicle_count": distance_health["above"],
            }
        )
        for name in ("valley", "flat", "peak"):
            scenario = per_km["scenarios"][name]
            health_row[f"ev_cost_cny_per_km_{name}"] = scenario["ev_cost_cny_per_km"]
            health_row[f"ev_emission_kgco2e_per_km_{name}"] = scenario["ev_emission_kg_per_km"]
    write_csv(output_stage / "selection_health.csv", [health_row])

    raw_runs = [
        {
            "stage": "facility_access_snap",
            "status": "PASS",
            "deterministic_evaluator_calls": 0,
            "full_checker_calls": 0,
            "formal_search_evaluations": 0,
            "detail": f"{len(access_rows)} CV OSRM nearest queries",
        },
        *[
            {
                "stage": f"directed_matrix_{row['profile']}",
                "status": "PASS",
                "deterministic_evaluator_calls": 0,
                "full_checker_calls": 0,
                "formal_search_evaluations": 0,
                "detail": (
                    f"required={row['required_directed_pairs']};"
                    f"reused={row['reused_from_frozen_depotpair_cache']};"
                    f"queried={row['queried_from_frozen_osrm_graph']}"
                ),
            }
            for row in matrix_stats
        ],
        {
            "stage": "formal_contestability",
            "status": contest["lower_gate"],
            "deterministic_evaluator_calls": 100,
            "full_checker_calls": 0,
            "formal_search_evaluations": 0,
            "detail": f"25pct={contest['count_25']}/50; upper percentage not applied",
        },
        {
            "stage": "edf_full_service_witness",
            "status": edf_gate,
            "deterministic_evaluator_calls": 0,
            "full_checker_calls": 1 if witness is not None else 0,
            "formal_search_evaluations": 0,
            "detail": witness.reason if witness is not None else "not run after gate failure",
        },
        {
            "stage": "mixed_fleet_critical_band",
            "status": mixed_gate,
            "deterministic_evaluator_calls": (
                2 + len(witness.solution.routes)
                if per_km and witness is not None and witness.solution is not None
                else 0
            ),
            "full_checker_calls": 0,
            "formal_search_evaluations": 0,
            "detail": json.dumps(distance_health, ensure_ascii=False, separators=(",", ":")) if distance_health else "not run after gate failure",
        },
    ]
    write_csv(output_stage / "raw_runs.csv", raw_runs)

    loaded = load_saved_depot_swap_built(output_stage)
    if (
        len(loaded.instance.nodes) != 53
        or len(loaded.orders_by_customer) != 50
        or loaded.instance.num_cv != 8
        or loaded.instance.num_ev != 8
        or set(loaded.customer_home_depot.values())
        != {str(row["depot_id"]) for row in DEPOTS}
    ):
        raise RuntimeError("dedicated saved-package load probe failed")
    write_json(
        output_stage / "load_probe.json",
        {
            "status": "PASS_DEDICATED_SAME_CITY_TWO_DEPOT_ADAPTER",
            "adapter": (
                "solver/scripts/build_instance_depot_swap_jjj_20260813.py#"
                "load_saved_depot_swap_built"
            ),
            "node_count": len(loaded.instance.nodes),
            "customer_count": len(loaded.orders_by_customer),
            "num_cv_from_fleet_authority": loaded.instance.num_cv,
            "num_ev_from_fleet_authority": loaded.instance.num_ev,
            "formal_search_evaluations": 0,
            "generic_loader_boundary": (
                "generic China81 loader assumes one depot per city; this approved "
                "Beijing/Beijing pair follows the existing depot-pair/PRDFIX dedicated adapter "
                "so customer city fields remain unchanged"
            ),
        },
    )

    protected_after = protected_hashes()
    old_after = snapshot_tree(OLD_INSTANCE)
    source_cache_after = {
        profile: sha256(OLD_MATRIX_ROOT / f"route_cache_jjj_{profile}.sqlite")
        for profile in ("cv", "ev")
    }
    if protected_after != protected_before:
        raise RuntimeError("protected files changed during task")
    if old_after != old_before:
        raise RuntimeError("old active instance changed during task")
    if source_cache_after != source_cache_before:
        raise RuntimeError("frozen route cache changed during task")

    finished = datetime.now(UTC)
    dependency_paths = (
        Path("solver/scripts/build_instance_depot_swap_jjj_20260813.py"),
        Path("solver/scripts/build_suite_depotpair_rebuild_20260812.py"),
        Path("solver/scripts/build_suite_prd_fix_20260812.py"),
        Path("solver/scripts/build_china81_suite_rebuild_20260812.py"),
        Path("baselines/china_instances/build_china81_directed_matrices_20260718.py"),
    )
    metadata = {
        "evidence_class": "FACT",
        "schema": "resetp.china81-instance-depot-swap.v1",
        "task": "JJJ 50-customer depot swap P56",
        "started_at_utc": started.isoformat(),
        "finished_at_utc": finished.isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "script_path": str(Path(__file__).relative_to(REPO)),
        "script_sha256": sha256(Path(__file__)),
        "builder_dependency_sha256": {
            str(path): sha256(REPO / path) for path in dependency_paths
        },
        "argv": list(sys.argv),
        "cwd": os.getcwd(),
        "execution_command": shlex.join([sys.executable, *sys.argv]),
        "source_instance": str(OLD_INSTANCE.relative_to(REPO)),
        "orders": str(output_relative / "orders.csv"),
        "static_input_authority": str(output_relative),
        "road_matrix_authority": str(matrix_authority_relative),
        "finite_fleet_authority": str(output_relative),
        "dedicated_loader": (
            "solver/scripts/build_instance_depot_swap_jjj_20260813.py#"
            "load_saved_depot_swap_built"
        ),
        "graph_identity": {
            row["profile"]: {
                "graph_manifest": row["graph_manifest"],
                "graph_manifest_sha256": row["graph_manifest_sha256"],
                "clip_sha256": row["clip_sha256"],
                "profile_sha256": row["profile_sha256"],
                "osrm_version": row["osrm_version"],
            }
            for row in matrix_stats
        },
        "source_instance_tree_sha256": hashlib.sha256(
            json.dumps(old_before, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "protected_sha256_before": protected_before,
        "protected_sha256_after": protected_after,
        "source_route_cache_sha256_before": source_cache_before,
        "source_route_cache_sha256_after": source_cache_after,
        "formal_search_evaluations": 0,
        "appledouble_sidecars_removed_from_new_output": remove_appledouble(output_stage),
    }
    decision = {
        "evidence_class": "FACT",
        "completion_marker": "SWAPDONE",
        "verdict": verdict,
        "formal_search_evaluations": 0,
        "contestability_lower_gate": contest["lower_gate"],
        "contestability_upper_gate": contest["upper_gate"],
        "edf_witness_gate": edf_gate,
        "mixed_fleet_two_sides_gate": mixed_gate,
        "no_data_or_criterion_tuning_after_results": True,
    }
    write_json(output_stage / "metadata.json", metadata)
    write_json(output_stage / "decision.json", decision)
    remove_appledouble(output_stage)
    write_json(output_stage / "artifact_hashes.json", tree_hashes(output_stage))
    remove_appledouble(output_stage)

    build_report(
        report_stage=report_stage,
        output_stage=output_stage,
        output_root=output_root,
        metadata=metadata,
        decision=decision,
        access_rows=access_rows,
        invariance_rows=invariance_rows,
        contest=contest,
        contest_rows=contest_rows,
        witness=witness,
        fleet=fleet,
        lunch=lunch,
        per_km=per_km,
        distance_health=distance_health,
        edf_gate=edf_gate,
        mixed_gate=mixed_gate,
        geometry=geometry,
        matrix_stats=matrix_stats,
        matrix_checks=matrix_checks,
        health_row=health_row,
        raw_runs=raw_runs,
        route_rows=route_rows,
        old_before=old_before,
        old_after=old_after,
    )
    remove_appledouble(report_stage)
    write_json(report_stage / "artifact_hashes.json", tree_hashes(report_stage))
    remove_appledouble(report_stage)

    output_stage.rename(output_root)
    report_stage.rename(report_root)
    print(json.dumps({"verdict": verdict, "output": str(output_root), "report": str(report_root)}, ensure_ascii=False))
    return 0


def build_report(**kwargs: Any) -> None:
    report_stage: Path = kwargs["report_stage"]
    output_stage: Path = kwargs["output_stage"]
    output_root: Path = kwargs["output_root"]
    metadata: Mapping[str, Any] = kwargs["metadata"]
    decision: Mapping[str, Any] = kwargs["decision"]
    access_rows: Sequence[Mapping[str, Any]] = kwargs["access_rows"]
    invariance_rows: Sequence[Mapping[str, Any]] = kwargs["invariance_rows"]
    contest: Mapping[str, Any] = kwargs["contest"]
    contest_rows: Sequence[Mapping[str, Any]] = kwargs["contest_rows"]
    witness = kwargs["witness"]
    fleet: Mapping[str, Any] = kwargs["fleet"]
    lunch: Mapping[str, Any] = kwargs["lunch"]
    per_km: Mapping[str, Any] = kwargs["per_km"]
    distance_health: Mapping[str, Any] = kwargs["distance_health"]
    edf_gate: str = kwargs["edf_gate"]
    mixed_gate: str = kwargs["mixed_gate"]
    geometry: Mapping[str, Any] = kwargs["geometry"]
    matrix_stats: Sequence[Mapping[str, Any]] = kwargs["matrix_stats"]
    matrix_checks: Mapping[str, Any] = kwargs["matrix_checks"]
    health_row: Mapping[str, Any] = kwargs["health_row"]
    raw_runs: Sequence[Mapping[str, Any]] = kwargs["raw_runs"]
    route_rows: Sequence[Mapping[str, Any]] = kwargs["route_rows"]
    old_before: Mapping[str, str] = kwargs["old_before"]
    old_after: Mapping[str, str] = kwargs["old_after"]

    old_health_matches = [row for row in read_csv(OLD_HEALTH) if row["instance_id"] == OLD_ID]
    if len(old_health_matches) != 1:
        raise RuntimeError("old health evidence row is not unique")
    old_health = old_health_matches[0]
    old_orders = read_csv(OLD_INSTANCE / "orders.csv")
    new_orders = read_csv(output_stage / "instances" / NEW_ID / "orders.csv")
    derived_change_rows = []
    old_by = {row["customer_id"]: row for row in old_orders}
    new_by = {row["customer_id"]: row for row in new_orders}
    for field in DERIVED_ORDER_FIELDS:
        changed = sum(old_by[key][field] != new_by[key][field] for key in sorted(old_by))
        derived_change_rows.append(
            {
                "evidence_class": "FACT",
                "field": field,
                "changed_customer_count": changed,
                "unchanged_customer_count": 50 - changed,
                "reason": "DEPOT_DERIVED_RECOMPUTATION",
            }
        )
    derived_change_rows.append(
        {
            "evidence_class": "FACT",
            "field": "instance_id",
            "changed_customer_count": 50,
            "unchanged_customer_count": 0,
            "reason": "NEW_INSTANCE_ID_EXPECTED",
        }
    )

    write_csv(report_stage / "facility_access_points.csv", access_rows)
    write_csv(report_stage / "customer_invariance.csv", invariance_rows)
    write_csv(report_stage / "depot_derived_field_changes.csv", derived_change_rows)
    write_csv(report_stage / "formal_contestability.csv", contest_rows)
    write_csv(report_stage / "matrix_build_rows.csv", matrix_stats)
    write_json(report_stage / "matrix_checks.json", matrix_checks)
    write_json(report_stage / "geometry_metrics.json", geometry)
    write_csv(report_stage / "selection_health.csv", [health_row])
    write_csv(report_stage / "raw_runs.csv", raw_runs)
    write_csv(
        report_stage / "health_witness_routes.csv",
        route_rows,
        list(route_rows[0]) if route_rows else [
            "instance_id", "witness_status", "physical_vehicle_id", "route_vehicle_id",
            "depot_id", "shift_id", "customers", "customer_count", "volume_m3",
            "demand_kg", "departure_minute", "return_minute", "distance_km",
        ],
    )
    lunch_rows = list(lunch.get("rows", []))
    write_csv(
        report_stage / "lunch_charge_rows.csv",
        lunch_rows,
        list(lunch_rows[0]) if lunch_rows else [
            "instance_id", "physical_vehicle_id", "depot_id", "first_pm_volume_m3",
            "loading_hours", "available_charge_hours", "chargeable_kwh_60kw_from_zero",
            "curve_id",
        ],
    )
    write_json(report_stage / "metadata.json", metadata)
    write_json(report_stage / "decision.json", decision)

    old_access = geometry["old_scenario_access_geometry"]
    new_center = geometry["new_osm_center_proxy_geometry"]
    new_access = geometry["new_scenario_access_geometry"]
    old_formal = geometry["old_formal_cv_cost_home_split"]
    new_formal = geometry["new_formal_cv_cost_home_split"]
    old_depot_ids = [row["node_id"] for row in read_csv(OLD_INSTANCE / "nodes.csv") if row["node_type"] == "depot"]
    new_depot_ids = [str(row["depot_id"]) for row in DEPOTS]

    def split_text(payload: Mapping[str, Any], depot_ids: Sequence[str]) -> str:
        values = payload["customer_counts"]
        return "/".join(str(values.get(depot, 0)) for depot in depot_ids)

    def demand_text(payload: Mapping[str, Any], depot_ids: Sequence[str]) -> str:
        values = payload["demand_kg"]
        return "/".join(fmt(float(values.get(depot, 0.0)), 3) for depot in depot_ids)

    data_manifest_sha = sha256(output_stage / "artifact_hashes.json")
    instance_manifest_sha = sha256(output_stage / "instances" / NEW_ID / "artifact_hashes.json")
    matrix_manifest_sha = sha256(output_stage / "directed_matrices" / "artifact_hashes.json")
    route_pdf = REPO / "docs/paper_gci_dmm_vrp_20260804/route_map_probe_20260813/route_map_three_panel.pdf"
    route_pdf_size = route_pdf.stat().st_size
    route_pdf_sha = sha256(route_pdf)

    if decision["verdict"] == "PASS_ALL_THREE_FORMAL_GATES":
        headline = "三道正式关全部通过；新算例已冻结，旧算例未覆盖。"
    else:
        headline = (
            f"按铁律在 {decision['verdict']} 处停止；未回头调整客户、时间窗、需求或判据。"
        )

    lines: list[str] = [
        "SWAPDONE",
        "",
        "# 京津冀 50 客户统一算例换车场重建报告（2026-08-13）",
        "",
        f"`FACT`：{headline}",
        "",
        "`USER DECISION`：用户原话为「丙改（放宽可争夺上限，取那对 25/25 的真实园区）。」本轮只换两个车场，50 个客户不动；正式搜索评价次数为 **0**。",
        "",
        "## 1. 执行口径与结论",
        "",
        "`FACT`：正式可争夺仍以冻结有向 OSRM 弧、现行评价器的 CV 直达往返成本和 25% 相对差口径计算。保留原 30% 占比下限。原 45% 上限只为防两场几乎重合；本例两 OSM 中心相距 "
        f"{fmt(new_center['depot_distance_km'], 3)} km，明显不重合，因此本例不再套百分比上限，也没有另设新的百分比或距离阈值。正式实测值完整照报。",
        "",
        "| 正式关 | 实测 | 判定 |",
        "|---|---:|---|",
        f"| 25% 口径可争夺 + 保留 30% 下限 | {contest['count_25']}/50 = {100*float(contest['share_25']):.1f}% | {contest['lower_gate']}；上限对本例不适用 |",
        f"| 两班次 EDF 完整服务 | {fmt(witness.served_customers if witness is not None else '')}/50 客户，{fmt(witness.served_demand_kg if witness is not None else '', 3)}/{fmt(health_row['total_demand_kg'], 3)} kg | {edf_gate} |",
        f"| 混合车队临界带两侧有车 | 下侧/带内/上侧 = {fmt(distance_health.get('below', ''))}/{fmt(distance_health.get('within', ''))}/{fmt(distance_health.get('above', ''))} | {mixed_gate} |",
        "",
        f"`FACT`：20%/25%/30% 三档正式可争夺实测分别为 {contest['count_20']}/50、{contest['count_25']}/50、{contest['count_30']}/50；逐客户的两场成本、绝对差和相对差保存在 `formal_contestability.csv`。",
        "",
        "## 2. 两个真实车场及路网接入点",
        "",
        "`FACT`：OSM 原中心点只证明实体身份与原始几何；场景计算使用冻结 CV OSRM 图返回的最近可路由点。该点统一标记为 `SCENARIO_ROAD_ACCESS_POINT_NOT_OBSERVED_TRUCK_GATE`，不是虚构坐标，也不冒充已观测货车门。CV 与 EV 使用同一场景接入坐标，各自向对应冻结图查询有向弧。",
        "",
        "| 车场 | 冻结 OSM 身份 | OSM 原中心（纬度，经度） | 场景路网接入点（纬度，经度） | OSRM 报告偏移 | 道路名 |",
        "|---|---|---|---|---:|---|",
    ]
    for row in access_rows:
        lines.append(
            f"| {row['name']} | `{row['osm_identity']}` | "
            f"{float(row['osm_center_latitude']):.7f}, {float(row['osm_center_longitude']):.7f} | "
            f"{float(row['scenario_access_latitude']):.7f}, {float(row['scenario_access_longitude']):.7f} | "
            f"{float(row['osrm_nearest_reported_offset_m']):.3f} m | {row['access_road_name'] or '未命名道路'} |"
        )
    lines += [
        "",
        f"`FACT`：冻结实体池 `{access_rows[0]['source_pool_path']}` 的 SHA-256 为 `{access_rows[0]['source_pool_sha256']}`；两条原始 OSM 响应哈希分别为 `{access_rows[0]['source_response_sha256']}`、`{access_rows[1]['source_response_sha256']}`。",
        "",
        "## 3. 客户不变性逐字段核对",
        "",
        "`FACT`：下表比较旧实例和新实例 50 行客户。每组均按列逐单元格比对；哈希是按 `customer_id` 排序后的字段投影哈希。",
        "",
        "| 组别 | 字段数 | 核对单元格 | 不一致 | 旧/新投影哈希 | 结果 |",
        "|---|---:|---:|---:|---|---|",
    ]
    for row in invariance_rows:
        field_count = len(str(row["fields"]).split("|"))
        lines.append(
            f"| {row['group']} | {field_count} | {row['field_cells_checked']} | {row['mismatch_count']} | "
            f"`{row['old_projection_sha256']}` / `{row['new_projection_sha256']}` | {row['status']} |"
        )
    lines += [
        "",
        "`FACT`：客户身份、坐标、需求量、服务时长、当前与来源时间窗、班次、`shift_id`、`preferred_shift_id`、班次起止和返回车场要求均完全不变。AM/PM 仍为 "
        f"{sum(row['shift_id']=='AM' for row in new_orders)}/{sum(row['shift_id']=='PM' for row in new_orders)}；需求合计 {sum(float(row['demand_kg']) for row in new_orders):.3f} kg，体积合计 {sum(float(row['source_volume_m3']) for row in new_orders):.3f} m³，服务时长合计 {sum(float(row['service_minutes']) for row in new_orders):.3f} 分钟。",
        "",
        "`FACT`：`orders.csv` 不能整文件沿用旧哈希，因为换场后必须重算车场派生列。具体只允许 `instance_id` 以及以下六列变化：`home_depot_id`、`home_to_customer_travel_minute`、`shift_reachability_status`、`preferred_shift_reachable`、`alternative_shift_reachable`、`reachability_window_delay_minute`。逐列变化数在 `depot_derived_field_changes.csv`；固定班次不可达客户数为 "
        f"{health_row['fixed_shift_unreachable_count']}。没有为可达性移动时间窗或切换 `shift_id`。",
        "",
        "## 4. 正式三关明细",
        "",
        "### 4.1 可争夺",
        "",
        f"`FACT`：25% 口径为 {contest['count_25']}/50（{100*float(contest['share_25']):.1f}%）；保留下限要求至少 {contest['lower_bound_25pct_count']}/50，故为 `{contest['lower_gate']}`。上限状态为 `{contest['upper_gate']}`。43/50 只是一轮 Haversine 预筛代理，本报告没有把它升级成正式结果。",
        "",
        "### 4.2 两班次 EDF 完整服务见证",
        "",
    ]
    if witness is not None:
        lines += [
            f"`FACT`：EDF 状态 `{witness.status}`；服务 {witness.served_customers}/50 客户、{witness.served_demand_kg:.3f}/{float(health_row['total_demand_kg']):.3f} kg；完整检查器违规 {len(witness.violations)} 条。路线 {fmt(fleet.get('trip_count'))} 趟（AM {fmt(fleet.get('am_trip_count'))}、PM {fmt(fleet.get('pm_trip_count'))}），复用后物理车 {fmt(fleet.get('physical_vehicle_count'))} 辆，最多每车 {fmt(fleet.get('max_trips'))} 趟。逐路线到发时刻、里程和客户序列在 `health_witness_routes.csv`。",
            "",
            f"`FACT`：午间跨班复用车辆 {fmt(lunch.get('vehicle_count'))} 辆，按现行 60 kW 曲线从零起可补电合计 {fmt(lunch.get('total_kwh'), 6)} kWh；逐车记录在 `lunch_charge_rows.csv`。",
        ]
    else:
        lines.append("`FACT`：因上一关失败，按铁律未运行 EDF 见证。")
    lines += [
        "",
        "### 4.3 混合车队临界带",
        "",
    ]
    if per_km:
        critical = per_km["scenarios"]
        lines += [
            f"`FACT`：谷/平/峰临界日里程为 {fmt(critical['valley']['critical_daily_km'], 6)} / {fmt(critical['flat']['critical_daily_km'], 6)} / {fmt(critical['peak']['critical_daily_km'], 6)} km。见证车辆日里程最小/中位/最大为 {fmt(min(distance_health['daily_distances']), 6)} / {fmt(statistics.median(distance_health['daily_distances']), 6)} / {fmt(max(distance_health['daily_distances']), 6)} km；下侧/带内/上侧 {distance_health['below']}/{distance_health['within']}/{distance_health['above']}，判定 `{mixed_gate}`。",
            "",
            f"`FACT`：正式复算基于 `{per_km['basis']}`；CV 成本 {fmt(per_km['cv_cost_cny_per_km'], 9)} 元/km、排放 {fmt(per_km['cv_emission_kg_per_km'], 9)} kgCO₂e/km，EV 驱动电耗 {fmt(per_km['ev_kwh_per_km'], 9)} kWh/km。",
        ]
    else:
        lines.append("`FACT`：因上一关失败，按铁律未运行混合车队临界带复算。")

    lines += [
        "",
        "## 5. 改造前后几何对照",
        "",
        "`FACT`：几何表明确拆开三种口径：旧/新场景接入点 Haversine、新 OSM 中心直线代理、正式 CV 成本归属。旧正式 18%/82% 与候选 25/25 从来不是同一口径，不能直接写成同口径改善。",
        "",
        "| 指标 | 改造前：旧场景接入点 | 改造后：新 OSM 中心代理 | 改造后：新场景接入点 |",
        "|---|---:|---:|---:|",
        f"| 客户群东西×南北范围 | {fmt(geometry['customer_range_ew_km'], 3)} × {fmt(geometry['customer_range_ns_km'], 3)} km | 同左 | 同左 |",
        f"| 客户群均值中心 | {fmt(geometry['customer_center']['latitude'], 7)}, {fmt(geometry['customer_center']['longitude'], 7)} | 同左 | 同左 |",
        f"| 场间距 | {fmt(old_access['depot_distance_km'], 3)} km | {fmt(new_center['depot_distance_km'], 3)} km | {fmt(new_access['depot_distance_km'], 3)} km |",
        f"| 场 A 到客户中心 | {fmt(old_access['depot_to_customer_center_km'][old_depot_ids[0]], 3)} km | {fmt(new_center['depot_to_customer_center_km'][new_depot_ids[0]], 3)} km | {fmt(new_access['depot_to_customer_center_km'][new_depot_ids[0]], 3)} km |",
        f"| 场 B 到客户中心 | {fmt(old_access['depot_to_customer_center_km'][old_depot_ids[1]], 3)} km | {fmt(new_center['depot_to_customer_center_km'][new_depot_ids[1]], 3)} km | {fmt(new_access['depot_to_customer_center_km'][new_depot_ids[1]], 3)} km |",
        f"| 最近场到客户中位距 | {fmt(old_access['nearest_depot_customer_median_km'], 6)} km | {fmt(new_center['nearest_depot_customer_median_km'], 6)} km | {fmt(new_access['nearest_depot_customer_median_km'], 6)} km |",
        f"| 客户间中位距 | {fmt(geometry['customer_pair_median_km'], 6)} km | 同左 | 同左 |",
        f"| 两者比值 | {fmt(old_access['nearest_to_customer_pair_median_ratio'], 3)} 倍 | {fmt(new_center['nearest_to_customer_pair_median_ratio'], 3)} 倍 | {fmt(new_access['nearest_to_customer_pair_median_ratio'], 3)} 倍 |",
        f"| Haversine 客户分成 A/B | {split_text(old_access, old_depot_ids)} | {split_text(new_center, new_depot_ids)} | {split_text(new_access, new_depot_ids)} |",
        f"| Haversine 需求分成 A/B | {demand_text(old_access, old_depot_ids)} kg | {demand_text(new_center, new_depot_ids)} kg | {demand_text(new_access, new_depot_ids)} kg |",
        "",
        "| 正式 CV 直达往返成本归属 | 改造前 | 改造后 |",
        "|---|---:|---:|",
        f"| 客户分成 A/B | {split_text(old_formal, old_depot_ids)}（{100*float(old_formal['customer_counts'][old_depot_ids[0]])/50:.1f}%/{100*float(old_formal['customer_counts'][old_depot_ids[1]])/50:.1f}%） | {split_text(new_formal, new_depot_ids)}（{100*float(new_formal['customer_counts'][new_depot_ids[0]])/50:.1f}%/{100*float(new_formal['customer_counts'][new_depot_ids[1]])/50:.1f}%） |",
        f"| 需求分成 A/B | {demand_text(old_formal, old_depot_ids)} kg | {demand_text(new_formal, new_depot_ids)} kg |",
        "",
        "`FACT`：本表 Haversine 数统一以地球平均半径 6371.0088 km 复算；因此旧几何的末六位与上一轮报告沿用值有米级以下尾差，但 5.342 倍及分成结论不变。",
        "",
        f"`FACT`：新场间有向道路距离（A→B/B→A）为 CV {fmt(geometry['directed_depot_road_metrics']['cv']['a_to_b_distance_km'], 6)}/{fmt(geometry['directed_depot_road_metrics']['cv']['b_to_a_distance_km'], 6)} km，EV {fmt(geometry['directed_depot_road_metrics']['ev']['a_to_b_distance_km'], 6)}/{fmt(geometry['directed_depot_road_metrics']['ev']['b_to_a_distance_km'], 6)} km。",
        "",
        "## 6. 有向矩阵、补弧与哈希核对",
        "",
        "`FACT`：节点顺序为 2 车场 + 1 个原公共充电站 + 50 个原客户，共 53 节点；每个 profile 需要 2,756 条非对角有向弧。未变 51 节点之间的 2,550 条弧从上次冻结缓存继承；新车场相关缺弧只从同一冻结 OSRM 图查询。没有直线补弧，没有把一个方向复制给反方向。",
        "",
        "| profile | 需有向弧 | 从旧缓存继承 | 路由前已有 | 冻结图新查 | 图 manifest SHA-256 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in matrix_stats:
        lines.append(
            f"| {row['profile']} | {row['required_directed_pairs']} | {row['reused_from_frozen_depotpair_cache']} | "
            f"{row['present_before_router']} | {row['queried_from_frozen_osrm_graph']} | `{row['graph_manifest_sha256']}` |"
        )
    lines += [
        "",
        "| profile / 矩阵 | 形状 | 对角零值 | 有向不对称无序对 | 文件 SHA-256 |",
        "|---|---:|---:|---:|---|",
    ]
    filename_by_field = {
        "road_distance_m": "road_distance_m.csv",
        "road_duration_s": "road_duration_s.csv",
        "road_sum_v2d_m3_s2": "road_sum_v2d_m3_s2.csv",
    }
    for profile in ("cv", "ev"):
        for field, check in matrix_checks[profile].items():
            filename = filename_by_field[field]
            path = output_stage / "directed_matrices" / "instances" / NEW_POOL_ID / profile / filename
            lines.append(
                f"| {profile}/{filename} | {check['rows']}×{check['columns']} | {check['zero_diagonal_count']} | "
                f"{check['asymmetric_unordered_pair_count']} | `{sha256(path)}` |"
            )
    lines += [
        "",
        f"`FACT`：新数据总 manifest SHA-256 为 `{data_manifest_sha}`；实例 manifest 为 `{instance_manifest_sha}`；矩阵 manifest 为 `{matrix_manifest_sha}`。`matrix_reference.json` 中的 8 个 profile 文件路径与哈希均在生成后复核。",
        "",
        "`FACT`：新车队 authority 按既有方法取 EDF 物理车见证：两场各 `Rd=Re=4`，不是构造期的宽松 50/50。顶层 `instance_catalog.csv`、`orders.csv`、`facilities.csv`、`node_city_membership.csv` 与标准 `fleet_caps.csv` 已齐；同城双车场继续沿用上一轮专用适配语义，`load_probe.json` 已实测 53 节点、50 客户、CV/EV 各 8 辆读取成功，搜索评价仍为 0。",
        "",
        "## 7. 因本次几何变更而失效的旧数值和产物",
        "",
        "以下项目没有删除，但只能作为旧几何历史，不得继续用于新算例：",
        "",
        f"1. 旧正式 CV 成本归属 9/41（18%/82%）及需求 {old_health.get('served_demand_kg','') and demand_text(old_formal, old_depot_ids)} kg；旧 Haversine 分成 6/44 及其需求分成。",
        f"2. 旧可争夺 20%/25%/30% 三档 {old_health['contestable_count_20pct']}/50、{old_health['contestable_count_25pct']}/50、{old_health['contestable_count_30pct']}/50，以及旧 `contestability.csv` 内 50 客户的两场成本、差值、相对差和最近场。",
        f"3. 旧 EDF 的 {old_health['trip_count_no_reuse']} 趟路线（AM {old_health['trip_count_am']}、PM {old_health['trip_count_pm']}）、{old_health['physical_vehicle_count_reuse']} 辆物理车、减少 {old_health['fleet_reduction_upper_count_vs_no_reuse']} 辆/{old_health['fleet_reduction_upper_pct_vs_no_reuse']}%、最多 {old_health['max_trips_per_vehicle']} 趟、16 条逐路线到发与里程记录。",
        f"4. 旧午间复用 {old_health['lunch_reused_vehicle_count']} 辆及 {float(old_health['lunch_chargeable_kwh_60kw_total']):.6f} kWh，总表和逐车 `lunch_charge_rows` 均失效。",
        f"5. 旧谷/平/峰临界里程 {float(old_health['critical_daily_km_valley']):.6f}/{float(old_health['critical_daily_km_flat']):.6f}/{float(old_health['critical_daily_km_peak']):.6f} km，旧见证日里程最小/中位/最大 {float(old_health['witness_daily_km_min']):.6f}/{float(old_health['witness_daily_km_median']):.6f}/{float(old_health['witness_daily_km_max']):.6f} km，旧下/带内/上 {old_health['critical_band_below_vehicle_count']}/{old_health['critical_band_overlap_vehicle_count']}/{old_health['critical_band_above_vehicle_count']}，以及全部旧 CV/EV 每公里成本、能耗、排放和 `PASS_TWO_SIDES`。",
        "6. 旧 `orders.csv` 的 `home_depot_id`、到客时间、班次可达标记和状态；由它们产生的整文件哈希。客户固有字段本身不失效。",
        "7. 旧完整 53×53 CV/EV 矩阵、route-cache 作为新实例整体引用时失效，旧矩阵 manifest/hash 也失效；但 51 个未变节点之间的 2,550 条有向弧仍有效并已原值继承。",
        "8. 旧 `nodes.csv`、`source_mapping.csv`、`provenance.json`、`witness_status.json`、`shift_contract.json`、`matrix_reference.json` 和实例 `artifact_hashes.json` 的整件身份/哈希。",
        "9. 旧健康表整行、`selection_health.csv`、`fleet_caps.csv`、`health_witness_routes.csv`、`lunch_charge_rows.csv` 及相关 artifact manifest。",
        f"10. `docs/paper_gci_dmm_vrp_20260804/route_map_probe_20260813/` 全部路线图、画布、投影、示意路线、9/41 与 6/44 分配、C010/C014/C042 重分配、2/7 与 1/8 趟、392.52/398.74 km 等旧几何探针数值。更正旧交接中的‘PDF 为 0 字节’说法：当前 `route_map_three_panel.pdf` 实测 {route_pdf_size:,} 字节，SHA-256 `{route_pdf_sha}`；它失效是因为绑定旧车场和旧路线，不是因为文件为空。",
        "11. P53 选择 JJJ 50 客户作为正文主算例的决定仍保留；其中绑定旧车场几何的数值失效。P56 本次用户决定保留。P28 正式基线仍未运行，本轮没有借换场任务启动任何求解器。",
        "",
        "## 8. 旧实例、受保护文件与搜索次数",
        "",
        f"`FACT`：旧实例目录 `{OLD_INSTANCE.relative_to(REPO)}` 前后共有 {len(old_before)} 个文件，逐文件 SHA-256 映射完全一致：`{old_before == old_after}`。新实例写入独立目录 `{output_root.relative_to(REPO)}`，未覆盖旧算例。",
        "",
        "| 受保护文件 | 任务前 SHA-256 | 任务后 SHA-256 | 结果 |",
        "|---|---|---|---|",
    ]
    for path in PROTECTED_EXPECTED:
        before = metadata["protected_sha256_before"][path]
        after = metadata["protected_sha256_after"][path]
        lines.append(f"| `{path}` | `{before}` | `{after}` | {'未变' if before == after else '变化'} |")
    lines += [
        "",
        "`FACT`：本轮调用的是构造、OSRM 路由、现行评价器的确定性直达复算、EDF 见证与完整检查器；没有调用正式搜索 runner。`raw_runs.csv` 每阶段的 `formal_search_evaluations` 均为 0，总数为 **0**。",
        "",
        "## 9. 交付物",
        "",
        f"- 新数据：`{output_root.relative_to(REPO)}/`。包含独立实例、两套有向矩阵与 route cache、完整 authority 入口、专用加载探针、接入点、三关原始表、几何、不变性、`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`。",
        f"- 新实例：`{(output_root / 'instances' / NEW_ID).relative_to(REPO)}/`。",
        f"- 本报告：`{DEFAULT_REPORT.relative_to(REPO)}/report.md`；同目录保留逐客户可争夺、逐路线见证、午间补电、矩阵核对和客户不变性表。",
        "",
        f"`FACT`：最终判定 `{decision['verdict']}`；正式搜索评价 0；没有为达标调整客户、时间窗、需求、班次、`shift_id` 或判据。",
    ]
    (report_stage / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
