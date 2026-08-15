#!/usr/bin/env python3
"""Repair PRD geometry and rebuild all 81 shift assignments and health rows.

The construction reuses the already frozen cy/jjj depot-pair geometry, keeps
the 23 healthy PRD geometries unchanged, and expands the frozen Guangzhou OSM
customer pool only for the four registered PRD geometry failures.  No search
solver is invoked and no existing authority is overwritten.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, Mapping, Sequence


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "solver" / "src"))

DEPOTPAIR_SCRIPT = REPO / "solver/scripts/build_suite_depotpair_rebuild_20260812.py"
SOURCE_HEALTH = REPO / "solver/reports/suite_depotpair_rebuild_20260812/suite_health_v2.csv"
SOURCE_DP = REPO / "data/ChinaInstances/china81_depotpair_rebuild_v1_20260812"
SOURCE_PRD = REPO / "data/ChinaInstances/china81_suite_v3_20260812"
DEFAULT_OUTPUT = REPO / "data/ChinaInstances/china81_suite_prd_fix_v1_20260812"
DEFAULT_REPORT = REPO / "solver/reports/suite_prd_fix_20260812"
PROTECTED = (
    Path("solver/src/setp_solver/cost.py"),
    Path("solver/src/setp_solver/check.py"),
    Path("solver/src/setp_solver/search/evaluation.py"),
)
REGIONS = ("cy", "jjj", "prd")
SIZES = (10, 15, 20, 25, 50, 75, 100, 150, 200)
REPLICATES = ("01", "02", "03")
PRD_GEOMETRY_FIX = {
    "cn-prd-75c-02-V2-LOCATIONS",
    "cn-prd-100c-01-V2-LOCATIONS",
    "cn-prd-100c-02-V2-LOCATIONS",
    "cn-prd-100c-03-V2-LOCATIONS",
}
PRD_REGISTERED_FAILURES = (
    "cn-prd-75c-01-V2-LOCATIONS",
    "cn-prd-75c-02-V2-LOCATIONS",
    "cn-prd-75c-03-V2-LOCATIONS",
    "cn-prd-100c-01-V2-LOCATIONS",
    "cn-prd-100c-02-V2-LOCATIONS",
    "cn-prd-100c-03-V2-LOCATIONS",
    "cn-prd-150c-02-V2-LOCATIONS",
    "cn-prd-200c-01-V2-LOCATIONS",
)
MAX_OUTPUT_BYTES = 2 * 1024**3


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


dp = load_module("suite_prd_fix_depotpair_20260812", DEPOTPAIR_SCRIPT)
base = dp.base


PRD_SPEC = {
    "actual_city": "guangzhou",
    "pool": "guangzhou__named_poi.csv",
    "depots": (
        {
            "depot_id": "D_guangzhou",
            "facility_key": "guangzhou",
            "name": "普洛斯广州黄埔物流园",
            "longitude": 113.522578,
            "latitude": 23.078890,
            "identity": "EXISTING_FACILITY_ROW/guangzhou",
            "source": (
                "data/ChinaInstances/"
                "china81_stage2_static_inputs_corrected_v3_20260723/"
                "facilities.csv#city=guangzhou"
            ),
        },
        {
            "depot_id": "D_foshan",
            "facility_key": "foshan",
            "name": "普洛斯顺德物流园",
            "longitude": 113.348373,
            "latitude": 22.812386,
            "identity": "EXISTING_FACILITY_ROW/foshan",
            "source": (
                "data/ChinaInstances/"
                "china81_stage2_static_inputs_corrected_v3_20260723/"
                "facilities.csv#city=foshan"
            ),
        },
    ),
}
dp.FACILITY_SPEC["prd"] = PRD_SPEC


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


def manifest_rows(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload.get("sha256", payload))


def read_matrix(path: Path, node_ids: Sequence[str]) -> tuple[tuple[float, ...], ...]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        if header[1:] != list(node_ids):
            raise RuntimeError(f"matrix header differs from nodes: {path}")
        rows = []
        observed = []
        for row in reader:
            observed.append(row[0])
            rows.append(tuple(float(value) for value in row[1:]))
    if observed != list(node_ids):
        raise RuntimeError(f"matrix row identities differ from nodes: {path}")
    return tuple(rows)


def load_profiles(
    matrix_root: Path,
    pool_id: str,
    node_ids: Sequence[str],
) -> dict[str, Any]:
    profiles = {}
    for profile in ("cv", "ev"):
        root = matrix_root / "instances" / pool_id / profile
        profiles[profile] = dp.RoadProfileMatrices(
            distance_m=read_matrix(root / "road_distance_m.csv", node_ids),
            duration_s=read_matrix(root / "road_duration_s.csv", node_ids),
            sum_v2d_m3_s2=read_matrix(root / "road_sum_v2d_m3_s2.csv", node_ids),
        )
    return profiles


def identity_key(region: str, size: int, replicate: str) -> str:
    return f"cn-{region}-{size}c-{replicate}-V2-LOCATIONS"


def new_identity(region: str, size: int, replicate: str) -> Any:
    source_id = identity_key(region, size, replicate)
    return base.ParsedIdentity(
        source_instance_id=source_id,
        new_instance_id=f"cn-{region}-{size}c-{replicate}-V3-TWO-SHIFT-PRDFIX",
        region=region,
        size=size,
        replicate=replicate,
    )


def source_geometry(
    row: Mapping[str, str],
    instance_root: Path,
) -> tuple[Any, dict[str, str], list[dict[str, str]]]:
    old_id = row["instance_id"]
    root = instance_root / "instances" / old_id
    orders = read_csv(root / "orders.csv")
    mapping = {
        item["new_node_id"]: item["source_node_id"]
        for item in read_csv(root / "source_mapping.csv")
    }
    selected = tuple(mapping[item["customer_id"]] for item in orders)
    home_by_source = {
        mapping[item["customer_id"]]: item["home_depot_id"]
        for item in orders
    }
    provenance = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
    geometry = base.GeometryChoice(
        mode=row["geometry_mode"],
        matrix_source_instance_id=row["matrix_source_instance_id"],
        depot_ids=tuple(row["depot_ids"].split("|")),
        customer_source_ids=selected,
        home_depot_by_source_customer=MappingProxyType(home_by_source),
        attempted_rebuild=bool(int(float(row["reanchored_customer_count"]))),
        rebuild_succeeded=row["contestability_gate"] == "PASS",
        reanchored_customer_count=int(float(row["reanchored_customer_count"])),
        note=str(provenance["geometry_note"]),
    )
    return geometry, mapping, orders


def load_existing_dp_bundle(
    row: Mapping[str, str],
    template: Any,
    homes: Mapping[str, str],
) -> Any:
    pool_id = row["matrix_source_instance_id"]
    node_rows = read_csv(SOURCE_DP / "source_pools" / "instances" / pool_id / "nodes.csv")
    node_ids = [item["node_id"] for item in node_rows]
    profiles = load_profiles(SOURCE_DP / "directed_matrices", pool_id, node_ids)
    return dp.make_bundle(
        row["region"],
        pool_id,
        node_rows,
        profiles,
        homes,
        template,
        dp.station_facilities_by_city(),
    )


def prd_source_node_rows(
    selected: Sequence[Any],
    customer_by_id: Mapping[str, Mapping[str, str]],
) -> list[dict[str, Any]]:
    rows = []
    station_by_city = dp.station_facilities_by_city()
    station_cities: set[str] = set()
    for depot in PRD_SPEC["depots"]:
        city = str(depot["facility_key"])
        rows.append(
            {
                "node_id": depot["depot_id"],
                "node_type": "depot",
                "city": city,
                "latitude": f"{float(depot['latitude']):.7f}",
                "longitude": f"{float(depot['longitude']):.7f}",
                "source_identity": depot["identity"],
            }
        )
        if city not in station_cities:
            facility = station_by_city[city]
            rows.append(
                {
                    "node_id": f"S_{city}",
                    "node_type": "station",
                    "city": city,
                    "latitude": facility["station_lat"],
                    "longitude": facility["station_lon"],
                    "source_identity": facility["station_identity"],
                }
            )
            station_cities.add(city)
    for fact in selected:
        customer = customer_by_id[fact.source_node_id]
        rows.append(
            {
                "node_id": fact.source_node_id,
                "node_type": "customer",
                "city": customer["city"],
                "latitude": customer["latitude"],
                "longitude": customer["longitude"],
                "source_identity": dp.source_identity(customer),
            }
        )
    return rows


def make_prd_bundle(
    pool_id: str,
    rows: Sequence[Mapping[str, Any]],
    profiles: Mapping[str, Any],
    homes: Mapping[str, str],
    template: Any,
) -> Any:
    nodes = []
    station_by_city = dp.station_facilities_by_city()
    for row in rows:
        is_depot = row["node_type"] == "depot"
        is_station = row["node_type"] == "station"
        facility = station_by_city[str(row["city"])] if is_station else None
        nodes.append(
            dp.Node(
                node_id=str(row["node_id"]),
                node_type="d" if is_depot else ("f" if is_station else "c"),
                x=float(row["longitude"]),
                y=float(row["latitude"]),
                demand=0.0 if (is_depot or is_station) else 1.0,
                ready_time=0.0,
                due_time=24.0 * 3600.0,
                charge_power_kw=(
                    base.DEPOT_POWER_KW
                    if is_depot
                    else (
                        float(facility["station_power_kw"])
                        if facility is not None
                        else None
                    )
                ),
                station_chargers=(
                    2
                    if is_depot
                    else (
                        int(float(facility["station_gun_count"]))
                        if facility is not None
                        else None
                    )
                ),
                city=str(row["city"]),
            )
        )
    instance = dp.Instance(
        nodes=nodes,
        distance_matrix=[list(row) for row in profiles["cv"].distance_m],
        num_cv=max(1, len(nodes)),
        num_ev=max(1, len(nodes)),
        road_profiles=dict(profiles),
        vehicle_parameters=template.instance.vehicle_parameters,
        demand_mass_per_unit_kg=1.0,
    )
    return SimpleNamespace(
        instance_id=pool_id,
        instance=instance,
        prices=template.prices,
        time_profile=template.time_profile,
        customer_home_depot=MappingProxyType(dict(homes)),
    )


def build_prd_repair_authority(
    output_root: Path,
    report_root: Path,
) -> tuple[
    dict[str, Any],
    dict[str, str],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    static_root = output_root / "source_pools"
    matrix_root = output_root / "directed_matrices"
    matrix_root.mkdir(parents=True, exist_ok=False)
    write_csv(
        static_root / "facilities.csv",
        read_csv(SOURCE_DP / "source_pools/facilities.csv"),
    )

    real_pool = dp.load_real_pool("prd")
    customer_by_id = {dp.location_id(row): row for row in real_pool.values()}
    candidates = {
        replicate: sorted(
            [
                row
                for osm_identity, row in real_pool.items()
                if dp.replicate_for(osm_identity) == replicate
            ],
            key=dp.source_identity,
        )
        for replicate in REPLICATES
    }
    templates = {
        replicate: dp.load_china81_bundle(
            REPO, f"cn-prd-200c-{replicate}-V2-LOCATIONS"
        )
        for replicate in REPLICATES
    }
    required_direct = dp.route_pairs_for_direct(
        "prd", [row for replicate in REPLICATES for row in candidates[replicate]]
    )
    dbs: dict[str, Any] = {}
    direct_rows: dict[str, Any] = {}
    matrix_stats: list[dict[str, Any]] = []
    try:
        for profile in ("cv", "ev"):
            db = dp.matrix_builder.init_db(matrix_root / f"route_cache_prd_{profile}.sqlite")
            dbs[profile] = db
            reused = dp.seed_cache(
                db,
                dp.SOURCE_MATRICES / f"route_cache_prd_{profile}.sqlite",
                required_direct,
            )
            with dp.RouterSession("prd", profile, matrix_root) as router:
                before, queried = dp.ensure_routes(
                    db,
                    router.endpoint,
                    required_direct,
                    matrix_root / f"checkpoint_prd_{profile}_direct.json",
                )
            direct_rows[profile] = dp.load_route_rows(db, required_direct)
            matrix_stats.append(
                {
                    "evidence_class": "FACT",
                    "stage": "direct_contestability",
                    "region": "prd",
                    "profile": profile,
                    "required_directed_pairs": len(required_direct),
                    "present_before_router": before,
                    "reused_from_frozen_cache_this_stage": reused,
                    "queried_from_frozen_osrm_graph": queried,
                    **dp.graph_identity("prd", profile),
                }
            )

        selections: dict[tuple[str, int], Sequence[Any]] = {}
        selection_rows: list[dict[str, Any]] = []
        for replicate in REPLICATES:
            facts = dp.direct_facts(
                "prd",
                candidates[replicate],
                direct_rows,
                templates[replicate],
            )
            for size in ((75,) if replicate == "02" else ()) + (100,):
                selected, success, note = base.select_locations_for_gate(facts, size)
                count = sum(
                    fact.relative_gap < base.MAIN_CONTEST_THRESHOLD
                    for fact in selected
                )
                selection_rows.append(
                    {
                        "evidence_class": "FACT",
                        "region": "prd",
                        "replicate": replicate,
                        "customer_count": size,
                        "candidate_pool_count": len(facts),
                        "contestable_count_25pct": count,
                        "contestable_share_25pct": count / size if selected else "",
                        "selection_status": "PASS" if success else "FAIL",
                        "selection_note": note,
                    }
                )
                if not success:
                    raise RuntimeError(f"PRD gate unattainable for {replicate}/{size}: {note}")
                selections[(replicate, size)] = selected
        write_csv(report_root / "selection_health.csv", selection_rows)

        nodes_by_pool: dict[str, list[dict[str, Any]]] = {}
        homes_by_pool: dict[str, dict[str, str]] = {}
        catalog = []
        point_sources: dict[str, dict[str, Any]] = {}
        for (replicate, size), selected in selections.items():
            pool_id = f"cn-prd-{size}c-{replicate}-PRDFIX-POOL"
            nodes = prd_source_node_rows(selected, customer_by_id)
            nodes_by_pool[pool_id] = nodes
            homes_by_pool[pool_id] = {
                fact.source_node_id: fact.nearest_depot for fact in selected
            }
            write_csv(static_root / "instances" / pool_id / "nodes.csv", nodes)
            catalog.append(
                {
                    "instance_id": pool_id,
                    "region": "prd",
                    "customer_count": size,
                    "replicate": replicate,
                    "cities": "foshan|guangzhou",
                    "depot_count": 2,
                    "node_count": len(nodes),
                    "source_pool": PRD_SPEC["pool"],
                }
            )
            for fact in selected:
                source = customer_by_id[fact.source_node_id]
                point_sources[dp.source_identity(source)] = {
                    "evidence_class": "FACT",
                    "location_id": fact.source_node_id,
                    "city": source["city"],
                    "name": source["name"],
                    "osm_identity": dp.source_identity(source),
                    "latitude": source["latitude"],
                    "longitude": source["longitude"],
                    "coordinate_status": source["coordinate_status"],
                    "source_response_path": source["source_response_path"],
                    "source_response_sha256": source["source_response_sha256"],
                }
        write_csv(static_root / "instance_catalog.csv", catalog)
        write_csv(
            output_root / "customer_point_sources.csv",
            sorted(point_sources.values(), key=lambda row: row["osm_identity"]),
        )

        profiles_by_pool: dict[str, dict[str, Any]] = defaultdict(dict)
        for profile in ("cv", "ev"):
            db = dbs[profile]
            required_full = set()
            for nodes in nodes_by_pool.values():
                required_full.update(dp.route_pairs_for_nodes(nodes))
            reused = dp.seed_cache(
                db,
                dp.SOURCE_MATRICES / f"route_cache_prd_{profile}.sqlite",
                required_full,
            )
            with dp.RouterSession("prd", profile, matrix_root) as router:
                before, queried = dp.ensure_routes(
                    db,
                    router.endpoint,
                    required_full,
                    matrix_root / f"checkpoint_prd_{profile}_full.json",
                )
            rows = dp.load_route_rows(db, required_full)
            matrix_stats.append(
                {
                    "evidence_class": "FACT",
                    "stage": "full_repaired_instances",
                    "region": "prd",
                    "profile": profile,
                    "required_directed_pairs": len(required_full),
                    "present_before_router": before,
                    "reused_from_frozen_cache_this_stage": reused,
                    "queried_from_frozen_osrm_graph": queried,
                    **dp.graph_identity("prd", profile),
                }
            )
            for pool_id, nodes in nodes_by_pool.items():
                pairs = dp.route_pairs_for_nodes(nodes)
                profiles_by_pool[pool_id][profile] = dp.write_profile_matrices(
                    matrix_root / "instances" / pool_id / profile,
                    nodes,
                    {key: rows[key] for key in pairs},
                )

        bundles = {}
        for pool_id, nodes in nodes_by_pool.items():
            parts = pool_id.split("-")
            size = int(parts[2].removesuffix("c"))
            replicate = parts[3]
            bundles[pool_id] = make_prd_bundle(
                pool_id,
                nodes,
                profiles_by_pool[pool_id],
                homes_by_pool[pool_id],
                templates[replicate],
            )
        for db in dbs.values():
            db.commit()
            db.execute("DROP TABLE IF EXISTS temp.required_pairs")
            db.commit()
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            db.close()
        dbs.clear()
        write_json(static_root / "artifact_hashes.json", dp.tree_hashes(static_root))
        write_json(matrix_root / "artifact_hashes.json", dp.tree_hashes(matrix_root))
        write_csv(report_root / "matrix_build_rows.csv", matrix_stats)
        return (
            bundles,
            manifest_rows(matrix_root / "artifact_hashes.json"),
            selection_rows,
            matrix_stats,
        )
    finally:
        for db in dbs.values():
            try:
                db.close()
            except Exception:
                pass


class OneBundleCache:
    def __init__(self, bundle: Any) -> None:
        self.bundle = bundle

    def get(self, instance_id: str) -> Any:
        if instance_id != self.bundle.instance_id:
            raise KeyError(instance_id)
        return self.bundle


def health_and_write(
    output_root: Path,
    built: Any,
    matrix_hashes: Mapping[str, str],
) -> tuple[dict[str, Any], Any, Any, Any]:
    contest = base.contestability_rows(built)
    witness = base.build_witness(built)
    fleet = base.fleet_health(witness)
    lunch = base.lunch_health(built, witness)
    per_km = base.per_km_health(built, witness)
    critical = [
        float(per_km["scenarios"][name]["critical_daily_km"])
        for name in ("valley", "flat", "peak")
    ]
    distance = base.witness_distance_health(built, witness, critical)
    manifest_sha = base.write_instance_outputs(
        output_root, built, contest, witness, matrix_hashes
    )
    health = base.health_row(
        built, contest, witness, fleet, lunch, per_km, distance, manifest_sha
    )
    return health, witness, fleet, lunch


def old_and_new_counts(
    rows: Sequence[Mapping[str, Any]], field: str, passing: str
) -> dict[str, int]:
    return {
        region: sum(row[field] == passing for row in rows if row["region"] == region)
        for region in REGIONS
    }


def render_report(
    old_rows: Sequence[Mapping[str, str]],
    new_rows: Sequence[Mapping[str, Any]],
    selection_rows: Sequence[Mapping[str, Any]],
    protected_before: Mapping[str, str],
    protected_after: Mapping[str, str],
    total_bytes: int,
) -> str:
    old_edf = old_and_new_counts(old_rows, "edf_witness_status", "PASS")
    new_edf = old_and_new_counts(new_rows, "edf_witness_status", "PASS")
    geometry = old_and_new_counts(new_rows, "contestability_gate", "PASS")
    mixed = old_and_new_counts(
        new_rows, "mixed_fleet_two_sides_status", "PASS_TWO_SIDES"
    )
    switches = {
        region: sum(
            int(row["shift_reachability_switch_count"])
            for row in new_rows
            if row["region"] == region
        )
        for region in REGIONS
    }
    new_by_source = {row["source_instance_id"]: row for row in new_rows}
    changed = sum(int(row["shift_reachability_switch_count"]) for row in new_rows)
    both_unreachable = sum(int(row["shift_both_unreachable_count"]) for row in new_rows)
    lines = [
        "PRDFIX_DONE",
        "",
        "# China81 prd 失败算例补救与全套班次可达性复检（2026-08-12）",
        "",
        "## 结论",
        "",
        "| 标签 | 区域 | 修正前 EDF 通过 | 修正后 EDF 通过 | 班次改分客户 | 可争夺通过 | 混合两侧通过 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for region in REGIONS:
        lines.append(
            f"| FACT | {region} | {old_edf[region]}/27 | {new_edf[region]}/27 | "
            f"{switches[region]} | {geometry[region]}/27 | {mixed[region]}/27 |"
        )
    lines.extend(
        [
            "",
            f"- `FACT`：81 例共有 {changed} 个客户因首选班次不可达而改分另一班次；两班次都不可达的客户为 {both_unreachable} 个。",
            f"- `FACT`：新的 `suite_health_v3.csv` 恰有 {len(new_rows)} 行，三项现行判据分别是 25% 相对差下可争夺占比 30%–45%、EDF 完整服务见证、临界带下方和上方都有车。",
            "",
            "## prd 原 8 个失败算例的修正后状态",
            "",
            "| 标签 | 原算例 | 可争夺 | EDF | 混合两侧 | 班次改分数 | 终态与原因 |",
            "|---|---|---|---|---|---:|---|",
        ]
    )
    for source_id in PRD_REGISTERED_FAILURES:
        row = new_by_source[source_id]
        all_pass = (
            row["contestability_gate"] == "PASS"
            and row["edf_witness_status"] == "PASS"
            and row["mixed_fleet_two_sides_status"] == "PASS_TWO_SIDES"
        )
        reason = "三项全过" if all_pass else str(row["FLAG"] or "未通过，无 FLAG 原因")
        lines.append(
            f"| FACT | `{source_id}` | {row['contestability_gate']} | "
            f"{row['edf_witness_status']} | {row['mixed_fleet_two_sides_status']} | "
            f"{row['shift_reachability_switch_count']} | {reason} |"
        )
    lines.extend(
        [
            "",
            "## prd 几何补救",
            "",
            "- `FACT`：保留普洛斯广州黄埔物流园＋普洛斯顺德物流园车场对；补救只把 4 个几何失败例的客户候选扩到冻结 `guangzhou__named_poi.csv`，其他 prd 几何保持原来的真实点映射。",
            "- `FACT`：候选池为 1110 个有 OSM 身份的冻结真实点；三个副本候选数和入选比例如下。",
            "",
            "| 标签 | 副本 | 规模 | 候选点 | 25% 可争夺数 | 占比 | 状态 |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in selection_rows:
        lines.append(
            f"| FACT | {row['replicate']} | {row['customer_count']} | "
            f"{row['candidate_pool_count']} | {row['contestable_count_25pct']} | "
            f"{float(row['contestable_share_25pct']):.6f} | {row['selection_status']} |"
        )
    lines.extend(
        [
            "",
            "## 混合车队判据更正",
            "",
            "- `FACT`：`critical_band_overlap_status` 及 `critical_band_overlap_vehicle_count` 作为旧口径对照列保留。新的第三关是 `mixed_fleet_two_sides_status=PASS_TWO_SIDES`，它严格要求 `critical_band_below_vehicle_count>0` 且 `critical_band_above_vehicle_count>0`。",
            "- `FACT`：新表 FLAG 不再使用错误的 `CRITICAL_BAND:NO_OVERLAP`；未达到正确两侧判据时写为 `MIXED_TWO_SIDES:*`。",
            "",
            "## 红线与产物",
            "",
            "| 标签 | 受保护文件 | 任务前 SHA-256 | 任务后 SHA-256 |",
            "|---|---|---|---|",
        ]
    )
    for path in PROTECTED:
        key = str(path)
        lines.append(
            f"| FACT | `{key}` | `{protected_before[key]}` | `{protected_after[key]}` |"
        )
    lines.extend(
        [
            "",
            f"- `FACT`：本轮新数据与报告合计 {total_bytes} 字节，旧目录覆盖或删除数为 0。",
            "- `FACT`：正式搜索评价次数为 0；本轮只做确定性构造、冻结路网复算、EDF 见证和健康检查。",
            "- `FACT`：`metadata.json`、`raw_runs.csv`、`decision.json`、`artifact_hashes.json`、`suite_health_v3.csv` 和本报告齐全。",
            "",
        ]
    )
    return "\n".join(lines)


def build(output_root: Path, report_root: Path) -> None:
    if output_root.exists() or report_root.exists():
        raise FileExistsError("refusing to overwrite an existing output/report root")
    protected_before = {str(path): dp.sha256(REPO / path) for path in PROTECTED}
    output_root.mkdir(parents=True, exist_ok=False)
    report_root.mkdir(parents=True, exist_ok=False)
    write_json(
        output_root / "build_status.json",
        {"status": "IN_PROGRESS", "completed_health_rows": 0, "target_health_rows": 81},
    )

    old_rows = read_csv(SOURCE_HEALTH)
    old_by_source = {row["source_instance_id"]: row for row in old_rows}
    if len(old_rows) != 81 or len(old_by_source) != 81:
        raise RuntimeError("source health is not a unique 81-row table")
    tasks_by_instance = base.source_orders_by_instance()
    dp_hashes = manifest_rows(SOURCE_DP / "directed_matrices/artifact_hashes.json")
    original_hashes = manifest_rows(base.SOURCE_MATRICES / "artifact_hashes.json")
    repair_bundles, repair_hashes, selection_rows, _ = build_prd_repair_authority(
        output_root, report_root
    )

    health_rows: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    all_orders: list[dict[str, Any]] = []
    all_fleet: list[dict[str, Any]] = []
    all_witness: list[dict[str, Any]] = []
    all_lunch: list[dict[str, Any]] = []
    assignment_changes: list[dict[str, Any]] = []
    catalog: list[dict[str, Any]] = []

    for region in REGIONS:
        for size in SIZES:
            for replicate in REPLICATES:
                source_id = identity_key(region, size, replicate)
                old = old_by_source[source_id]
                identity = new_identity(region, size, replicate)
                if region in {"cy", "jjj"}:
                    geometry, _, _ = source_geometry(old, SOURCE_DP)
                    template = dp.load_china81_bundle(
                        REPO, f"cn-{region}-200c-{replicate}-V2-LOCATIONS"
                    )
                    bundle = load_existing_dp_bundle(
                        old, template, geometry.home_depot_by_source_customer
                    )
                    geometry = base.GeometryChoice(
                        **{**geometry.__dict__, "rebuild_succeeded": True}
                    )
                    base.SOURCE_STATIC = SOURCE_DP / "source_pools"
                    base.SOURCE_MATRICES = SOURCE_DP / "directed_matrices"
                    matrix_hashes = dp_hashes
                elif source_id in PRD_GEOMETRY_FIX:
                    pool_id = f"cn-prd-{size}c-{replicate}-PRDFIX-POOL"
                    bundle = repair_bundles[pool_id]
                    selected = tuple(sorted(bundle.customer_home_depot))
                    geometry = base.GeometryChoice(
                        mode="REAL_OSM_EXISTING_DEPOTPAIR_EXPANDED_POOL_PRDFIX",
                        matrix_source_instance_id=pool_id,
                        depot_ids=("D_foshan", "D_guangzhou"),
                        customer_source_ids=selected,
                        home_depot_by_source_customer=bundle.customer_home_depot,
                        attempted_rebuild=True,
                        rebuild_succeeded=True,
                        reanchored_customer_count=size,
                        note=(
                            "existing real Guangzhou-Huangpu/Foshan-Shunde depot pair; "
                            "expanded frozen Guangzhou named OSM pool; fixed 0.30-0.45 gate"
                        ),
                    )
                    base.SOURCE_STATIC = output_root / "source_pools"
                    base.SOURCE_MATRICES = output_root / "directed_matrices"
                    matrix_hashes = repair_hashes
                else:
                    geometry, _, _ = source_geometry(old, SOURCE_PRD)
                    bundle = dp.load_china81_bundle(
                        REPO, geometry.matrix_source_instance_id
                    )
                    base.SOURCE_STATIC = dp.SOURCE_STATIC
                    base.SOURCE_MATRICES = dp.SOURCE_MATRICES
                    matrix_hashes = original_hashes

                geometry = base.GeometryChoice(
                    mode=geometry.mode,
                    matrix_source_instance_id=geometry.matrix_source_instance_id,
                    depot_ids=geometry.depot_ids,
                    customer_source_ids=geometry.customer_source_ids,
                    home_depot_by_source_customer=geometry.home_depot_by_source_customer,
                    attempted_rebuild=geometry.attempted_rebuild,
                    rebuild_succeeded=geometry.rebuild_succeeded,
                    reanchored_customer_count=geometry.reanchored_customer_count,
                    note=geometry.note,
                )
                built = base.build_instance(
                    identity,
                    tasks_by_instance[source_id],
                    geometry,
                    OneBundleCache(bundle),
                )
                health, witness, _, lunch = health_and_write(
                    output_root, built, matrix_hashes
                )
                health_rows.append(health)
                all_orders.extend(dict(row) for row in built.order_rows)
                all_fleet.extend(base.fleet_rows(built, witness))
                all_witness.extend(base.witness_rows(built, witness))
                all_lunch.extend(dict(row) for row in lunch["rows"])
                for order in built.order_rows:
                    if order["shift_reachability_status"] != "PASS_PREFERRED_SHIFT":
                        assignment_changes.append(
                            {
                                "evidence_class": "FACT",
                                "instance_id": identity.new_instance_id,
                                "source_instance_id": source_id,
                                "customer_id": order["customer_id"],
                                "home_depot_id": order["home_depot_id"],
                                "home_to_customer_travel_minute": order[
                                    "home_to_customer_travel_minute"
                                ],
                                "preferred_shift_id": order["preferred_shift_id"],
                                "assigned_shift_id": order["shift_id"],
                                "reachability_window_delay_minute": order[
                                    "reachability_window_delay_minute"
                                ],
                                "shift_reachability_status": order[
                                    "shift_reachability_status"
                                ],
                            }
                        )
                raw_rows.append(
                    {
                        "evidence_class": "FACT",
                        "instance_id": identity.new_instance_id,
                        "source_instance_id": source_id,
                        "region": region,
                        "customer_count": size,
                        "replicate": replicate,
                        "contestability_gate": health["contestability_gate"],
                        "edf_witness_status": health["edf_witness_status"],
                        "mixed_fleet_two_sides_status": health[
                            "mixed_fleet_two_sides_status"
                        ],
                        "critical_band_overlap_status_old": health[
                            "critical_band_overlap_status"
                        ],
                        "shift_reachability_switch_count": health[
                            "shift_reachability_switch_count"
                        ],
                        "shift_both_unreachable_count": health[
                            "shift_both_unreachable_count"
                        ],
                        "FLAG": health["FLAG"],
                        "formal_search_evaluations": 0,
                    }
                )
                catalog.append(
                    {
                        "instance_id": identity.new_instance_id,
                        "source_instance_id": source_id,
                        "region": region,
                        "customer_count": size,
                        "replicate": replicate,
                        "depot_count": len(geometry.depot_ids),
                        "matrix_source_instance_id": geometry.matrix_source_instance_id,
                        "formal_search_evaluations": 0,
                        "instance_artifact_manifest_sha256": health[
                            "instance_artifact_manifest_sha256"
                        ],
                    }
                )
                write_json(
                    output_root / "build_status.json",
                    {
                        "status": "IN_PROGRESS",
                        "completed_health_rows": len(health_rows),
                        "target_health_rows": 81,
                        "last_instance_id": identity.new_instance_id,
                    },
                )

    if len(health_rows) != 81 or len(all_orders) != 5805:
        raise RuntimeError(
            f"final suite size mismatch: health={len(health_rows)}, orders={len(all_orders)}"
        )
    health_rows.sort(
        key=lambda row: (
            REGIONS.index(str(row["region"])),
            int(row["customer_count"]),
            str(row["replicate"]),
        )
    )
    write_csv(report_root / "suite_health_v3.csv", health_rows)
    write_csv(report_root / "raw_runs.csv", raw_rows)
    write_csv(report_root / "assignment_changes.csv", assignment_changes)
    write_csv(report_root / "health_witness_routes.csv", all_witness)
    write_csv(report_root / "lunch_charge_rows.csv", all_lunch)
    write_csv(output_root / "orders.csv", all_orders)
    write_csv(output_root / "fleet_caps.csv", all_fleet)
    write_csv(output_root / "instance_catalog.csv", catalog)
    facilities = read_csv(dp.SOURCE_STATIC / "facilities.csv")
    facilities.extend(read_csv(SOURCE_DP / "source_pools/facilities.csv"))
    unique_facilities = {
        (row["region"], row["city"]): row for row in facilities
    }
    write_csv(
        output_root / "facilities.csv",
        [unique_facilities[key] for key in sorted(unique_facilities)],
    )
    write_json(
        output_root / "metadata.json",
        {
            "schema": "resetp.china81-suite-prd-fix.v1",
            "created_date": "2026-08-12",
            "instance_count": 81,
            "order_count": 5805,
            "formal_search_allowed": False,
            "formal_search_evaluations": 0,
            "shift_rule": "one-in-three preferred; frozen-road reachability preflight",
            "mixed_fleet_gate": "below>0 and above>0",
            "old_data_overwritten": False,
            "builder_path": str(Path(__file__).resolve().relative_to(REPO)),
            "builder_sha256": dp.sha256(Path(__file__).resolve()),
            "base_builder_sha256": dp.sha256(
                REPO / "solver/scripts/build_china81_suite_rebuild_20260812.py"
            ),
        },
    )
    write_json(
        output_root / "decision.json",
        {
            "completion": "PRDFIX_DONE",
            "health_rows": 81,
            "formal_experiment_started": False,
            "old_data_overwritten": False,
            "protected_files_modified": False,
        },
    )
    write_json(
        report_root / "metadata.json",
        {
            "run_kind": "deterministic_prd_repair_and_full_suite_health",
            "health_rows": 81,
            "formal_search_evaluations": 0,
            "source_health_sha256": dp.sha256(SOURCE_HEALTH),
            "protected_hashes_before": protected_before,
            "builder_path": str(Path(__file__).resolve().relative_to(REPO)),
            "builder_sha256": dp.sha256(Path(__file__).resolve()),
        },
    )
    write_json(
        report_root / "decision.json",
        {
            "completion": "PRDFIX_DONE",
            "health_rows": 81,
            "flags_preserved": True,
            "mixed_fleet_gate": "below>0 and above>0",
        },
    )
    write_json(
        output_root / "build_status.json",
        {"status": "PRDFIX_DONE", "completed_health_rows": 81, "target_health_rows": 81},
    )

    protected_after = {str(path): dp.sha256(REPO / path) for path in PROTECTED}
    if protected_before != protected_after:
        raise RuntimeError("protected evaluator hash changed")
    report_path = report_root / "report.md"
    report_path.write_text(
        render_report(
            old_rows,
            health_rows,
            selection_rows,
            protected_before,
            protected_after,
            0,
        ),
        encoding="utf-8",
    )
    (report_root / "PRDFIX_DONE").write_text("PRDFIX_DONE\n", encoding="utf-8")

    sidecars = [
        path
        for root in (output_root, report_root)
        for path in root.rglob("._*")
        if path.is_file()
    ]
    for path in sidecars:
        path.unlink()
    write_json(output_root / "artifact_hashes.json", dp.tree_hashes(output_root))
    write_json(report_root / "artifact_hashes.json", dp.tree_hashes(report_root))
    for _ in range(5):
        total_bytes = dp.tree_bytes(output_root, report_root)
        if total_bytes > MAX_OUTPUT_BYTES:
            raise RuntimeError(f"new output exceeds 2 GiB: {total_bytes}")
        report_path.write_text(
            render_report(
                old_rows,
                health_rows,
                selection_rows,
                protected_before,
                protected_after,
                total_bytes,
            ),
            encoding="utf-8",
        )
        write_json(report_root / "artifact_hashes.json", dp.tree_hashes(report_root))
        if dp.tree_bytes(output_root, report_root) == total_bytes:
            break
    else:
        raise RuntimeError("reported byte count did not stabilize")
    final_sidecars = [
        path
        for root in (output_root, report_root)
        for path in root.rglob("._*")
        if path.is_file()
    ]
    for path in final_sidecars:
        path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report-root", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    build(args.output_root.resolve(), args.report_root.resolve())
    print("PRDFIX_DONE 81")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
