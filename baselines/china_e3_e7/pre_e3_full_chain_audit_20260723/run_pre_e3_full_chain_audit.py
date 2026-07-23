#!/usr/bin/env python3
"""Zero-search reviewer audit for the China81 E3--E7 input chain.

This program is deliberately not an experiment runner.  It reads frozen
artifacts, recomputes hashes and joins, and emits machine-readable audit
evidence.  It never calls an optimiser or changes ``formal_search_allowed``.

The first implementation covers the authority, static-input, spatial-label,
tariff and carbon-calendar portions (A1--A4).  Later audit lanes append checks
to the same output schema.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import math
import platform
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[3]
OUT = SCRIPT.parent

STATIC = REPO / "data/ChinaInstances/china81_stage2_static_inputs_v1_20260718"
CATALOG = STATIC / "instance_catalog.csv"
FACILITIES = STATIC / "facilities.csv"
CALENDAR = STATIC / "tariff_carbon_48slot_calendar.csv"
ORDERS = (
    REPO
    / "data/ChinaInstances/china81_order_attributes_mc001_v1_20260718/orders.csv"
)
LOCATION_CONTRACT = (
    REPO / "data/ChinaInstances/china_customer_location_contract_v2_20260718.json"
)
ASSIGNMENT_ROOT = (
    REPO
    / "data/ChinaInstances/"
    "china81_customer_location_assignments_mc005_final_v2_20260718"
)
ASSIGNMENTS = ASSIGNMENT_ROOT / "assignments.csv"
CORRECTED_ASSIGNMENTS = (
    REPO
    / "data/ChinaInstances/"
    "china81_customer_location_assignments_gis_v3_20260723/assignments.csv"
)
BASE_CUSTOMER_POOL = (
    REPO / "data/ChinaInstances/china9_city_full_pool_20260718_rerun_overpass_v2"
)
LEGACY_CUSTOMER_POOL_OVERLAY = (
    REPO
    / "data/ChinaInstances/"
    "china81_customer_pool_replenishment_map_api_v2_20260718"
)
MC005_CUSTOMER_POOL_CLOSURE = (
    REPO
    / "data/ChinaInstances/china81_chongqing_mc005_pool_closure_20260718"
)
G1_MANIFEST = (
    REPO
    / "data/ChinaInstances/china81_g1_independent_frozen_v2_20260718"
    / "instance_manifest.csv"
)
MATRICES = (
    REPO
    / "data/ChinaInstances/china81_local_directed_matrices_v9_20260718"
    / "instances"
)
FOUNDATION = (
    REPO / "data/ChinaInstances/china_e3_e7_foundation_contract_v1_20260723.json"
)
PARAMETER_LOCK = (
    REPO / "data/ChinaInstances/china_parameter_lock_v2_20260718.json"
)
BUILDER = (
    REPO / "baselines/china_instances/build_china_stage2_static_inputs_20260718.py"
)
CHINA81_LOADER = REPO / "solver/src/setp_solver/china81.py"
TARIFF_V2 = REPO / "data/ChinaPrices/china_2025_02_tariff_register_v2.json"
TARIFF_V3 = REPO / "data/ChinaPrices/china_2025_02_tariff_register_v3.json"
TVCI = (
    REPO
    / "baselines/e4_e5/china_2025_formal_month_selection_20260718"
    / "tvci_2025_february_48slot_wide.csv"
)
P3_RAW = (
    REPO
    / "baselines/e2_final_campaign_20260720/mv_hgs_sp_final"
    / "p3_china81_gate/raw_runs.csv"
)
S2_RAW = (
    REPO
    / "baselines/e2_final_campaign_20260720/p2p3_threeview"
    / "full_gate/raw_runs.csv"
)
S3_ROOT = (
    REPO
    / "baselines/e2_final_campaign_20260720/p2p3_threeview"
    / "representative_gate"
)
S3_RAW = S3_ROOT / "raw_runs.csv"
S3_TRAJ_RAW = S3_ROOT / "s3_traj_v4/raw_runs.csv"
S4_ROOT = (
    REPO
    / "baselines/e2_final_campaign_20260720/p2p3_threeview"
    / "table4_gate"
)
RUNTIME_BOUNDARY_CHECKS = OUT / "runtime_boundary_checks.csv"
OBJECTIVE_CHECKER_CHECKS = OUT / "objective_checker_audit.csv"
INTERFACE_REPRODUCIBILITY_CHECKS = (
    OUT / "interface_reproducibility_audit.csv"
)
REPRESENTATIVE_INSTANCE_ID = "cn-prd-50c-01-V2-LOCATIONS"
ROAD_ACCESS = (
    REPO
    / "data/ChinaInstances/phase1_nine_city_road_access_v1_20260718"
    / "road_access_points.csv"
)
GIS_ROOT = OUT / "gis/osm_boundaries"
DIESEL_EVIDENCE_ROOT = OUT / "evidence/diesel_2025_02_12"

GIS_BOUNDARY_SPECS: dict[str, dict[str, Any]] = {
    "beijing": {
        "path": "jjj_admin_boundaries.geojson",
        "name": "北京市",
        "admin_level": "4",
        "relation_id": 912940,
        "source_pbf": (
            "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/"
            "fixed_osm_inputs/hebei-260716.osm.pbf"
        ),
    },
    "tianjin": {
        "path": "jjj_admin_boundaries.geojson",
        "name": "天津市",
        "admin_level": "4",
        "relation_id": 912999,
        "source_pbf": (
            "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/"
            "fixed_osm_inputs/hebei-260716.osm.pbf"
        ),
    },
    "shijiazhuang": {
        "path": "jjj_admin_boundaries.geojson",
        "name": "石家庄市",
        "admin_level": "5",
        "relation_id": 3009732,
        "source_pbf": (
            "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/"
            "fixed_osm_inputs/hebei-260716.osm.pbf"
        ),
    },
    "guangzhou": {
        "path": "prd_admin_boundaries.geojson",
        "name": "广州市",
        "admin_level": "5",
        "relation_id": 3287346,
        "source_pbf": (
            "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/"
            "fixed_osm_inputs/guangdong-260716.osm.pbf"
        ),
    },
    "shenzhen": {
        "path": "prd_admin_boundaries.geojson",
        "name": "深圳市",
        "admin_level": "5",
        "relation_id": 3464353,
        "source_pbf": (
            "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/"
            "fixed_osm_inputs/guangdong-260716.osm.pbf"
        ),
    },
    "dongguan": {
        "path": "prd_admin_boundaries.geojson",
        "name": "东莞市",
        "admin_level": "5",
        "relation_id": 3464319,
        "source_pbf": (
            "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/"
            "fixed_osm_inputs/guangdong-260716.osm.pbf"
        ),
    },
    "foshan": {
        "path": "prd_admin_boundaries.geojson",
        "name": "佛山市",
        "admin_level": "5",
        "relation_id": 3464719,
        "source_pbf": (
            "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/"
            "fixed_osm_inputs/guangdong-260716.osm.pbf"
        ),
    },
    "chengdu": {
        "path": "chengdu_admin_boundary.geojson",
        "name": "成都市",
        "admin_level": "5",
        "relation_id": 2110264,
        "source_pbf": (
            "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/"
            "fixed_osm_inputs/sichuan-260716.osm.pbf"
        ),
    },
    "chongqing": {
        "path": "chongqing_admin_boundary_complete.geojson",
        "name": "重庆市",
        "admin_level": "4",
        "relation_id": 913069,
        "source_pbf": (
            "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/"
            "fixed_osm_inputs/chongqing-260716.osm.pbf"
        ),
        "completion_source_pbf": (
            "data/ChinaInstances/china_mc004_mc006_preclosure_v4_20260718/"
            "fixed_osm_inputs/sichuan-260716.osm.pbf"
        ),
        "completion_way_ids": [714965688, 803425995],
    },
}

PROTECTED_FILES = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
    "solver/src/setp_solver/prices.py",
)

# The reviewed mapping is explicit by design.  Coordinates are a validation
# input, not a tariff selector.
REVIEWED_CITY_MAPPING: dict[str, dict[str, str]] = {
    "beijing": {
        "region": "jjj",
        "province_or_municipality": "Beijing",
        "price_area_id": "beijing",
        "carbon_column": "Beijing",
        "diesel_zone": "beijing",
    },
    "tianjin": {
        "region": "jjj",
        "province_or_municipality": "Tianjin",
        "price_area_id": "tianjin",
        "carbon_column": "Tianjin",
        "diesel_zone": "tianjin",
    },
    "shijiazhuang": {
        "region": "jjj",
        "province_or_municipality": "Hebei",
        "price_area_id": "hebei_south",
        "carbon_column": "Hebei",
        "diesel_zone": "hebei",
    },
    "guangzhou": {
        "region": "prd",
        "province_or_municipality": "Guangdong",
        "price_area_id": "guangdong_prd_five_city",
        "carbon_column": "Guangdong",
        "diesel_zone": "guangdong",
    },
    "shenzhen": {
        "region": "prd",
        "province_or_municipality": "Guangdong",
        "price_area_id": "shenzhen",
        "carbon_column": "Guangdong",
        "diesel_zone": "guangdong",
    },
    "dongguan": {
        "region": "prd",
        "province_or_municipality": "Guangdong",
        "price_area_id": "guangdong_prd_five_city",
        "carbon_column": "Guangdong",
        "diesel_zone": "guangdong",
    },
    "foshan": {
        "region": "prd",
        "province_or_municipality": "Guangdong",
        "price_area_id": "guangdong_prd_five_city",
        "carbon_column": "Guangdong",
        "diesel_zone": "guangdong",
    },
    "chengdu": {
        "region": "cy",
        "province_or_municipality": "Sichuan",
        "price_area_id": "sichuan",
        "carbon_column": "Sichuan",
        "diesel_zone": "sichuan",
    },
    "chongqing": {
        "region": "cy",
        "province_or_municipality": "Chongqing",
        "price_area_id": "chongqing",
        "carbon_column": "Chongqing",
        "diesel_zone": "chongqing",
    },
}

# Independent replay of the February 2025 local-time TOU rules. These values
# are deliberately kept outside the frozen builder, so this audit does not
# "verify" the implementation against itself.
REVIEWED_FEBRUARY_PERIODS: dict[str, dict[str, list[tuple[int, int]]]] = {
    "beijing": {
        "valley": [(0, 7), (23, 24)],
        "peak": [(10, 13), (17, 22)],
    },
    "tianjin": {
        "valley": [(0, 7), (23, 24)],
        "peak": [(9, 12), (16, 21)],
    },
    "shijiazhuang": {
        "valley": [(1, 6), (12, 15)],
        "sharp_peak": [(17, 19)],
        "peak": [(16, 17), (19, 24)],
    },
    "guangzhou": {
        "valley": [(0, 8)],
        "peak": [(10, 12), (14, 19)],
    },
    "shenzhen": {
        "valley": [(0, 8)],
        "peak": [(10, 12), (14, 19)],
    },
    "dongguan": {
        "valley": [(0, 8)],
        "peak": [(10, 12), (14, 19)],
    },
    "foshan": {
        "valley": [(0, 8)],
        "peak": [(10, 12), (14, 19)],
    },
    "chengdu": {
        "valley": [(0, 7), (23, 24)],
        "peak": [(10, 12), (15, 21)],
    },
    "chongqing": {
        "valley": [(0, 8)],
        "peak": [(11, 17), (20, 22)],
    },
}

PERIOD_EVIDENCE: dict[str, str] = {
    "beijing": (
        "data/ChinaPrices/official_snapshots/china_2025_02_nine_city/"
        "beijing_2025_02_api.json"
    ),
    "tianjin": (
        "data/ChinaPrices/official_snapshots/china_2025_02_nine_city/"
        "tianjin_2025_02_api.json"
    ),
    "shijiazhuang": (
        "冀发改能价〔2022〕1364号; "
        "data/ChinaPrices/official_snapshots/china_2025_02_nine_city/"
        "hebei_2025_02_api.json"
    ),
    "guangzhou": (
        "baselines/e4_e5/china_region_price_source_gate_20260717/"
        "evidence/guangdong_drc_tou_policy_20210831.html"
    ),
    "shenzhen": (
        "data/ChinaPrices/official_snapshots/china_2025_02_nine_city/"
        "shenzhen_2025_02_api.json"
    ),
    "dongguan": (
        "baselines/e4_e5/china_region_price_source_gate_20260717/"
        "evidence/guangdong_drc_tou_policy_20210831.html"
    ),
    "foshan": (
        "baselines/e4_e5/china_region_price_source_gate_20260717/"
        "evidence/guangdong_drc_tou_policy_20210831.html"
    ),
    "chengdu": (
        "data/ChinaPrices/official_snapshots/china_2025_02_nine_city/"
        "sichuan_2025_02_api.json"
    ),
    "chongqing": (
        "baselines/e4_e5/china_policy_price_gate_chongqing_20260717/"
        "raw/chongqing_tou_policy_2021-12-09.html.txt"
    ),
}

# Values in force on the frozen default date, 2025-02-12. These are local
# maximum retail prices for 0# vehicle diesel, not observed fleet invoices.
# Chongqing's CNY/L value is a transparent derivation: the official national
# 2025-01-16 table gives 8,815 CNY/t, while adjacent official municipal tables
# establish the local litre conversion. It is therefore marked DERIVED rather
# than DIRECT_OBSERVATION.
REVIEWED_DIESEL_BY_ZONE: dict[str, dict[str, Any]] = {
    "beijing": {
        "price_cny_per_l": 7.48,
        "source_file": "beijing_2025_01_16.html",
        "source_url": (
            "https://fgw.beijing.gov.cn/fgwzwgk/2024zcwj/bwqtwj/"
            "202501/t20250116_3991009.htm"
        ),
        "source_strength": "DIRECT_OFFICIAL_LOCAL_RETAIL_TABLE",
    },
    "tianjin": {
        "price_cny_per_l": 7.43,
        "source_file": "tianjin_2025_01_index.html",
        "source_url": "https://fzgg.tj.gov.cn/xxfb/tzggx/index_4.html",
        "source_strength": "DIRECT_OFFICIAL_LOCAL_RETAIL_INDEX",
    },
    "hebei": {
        "price_cny_per_l": 7.43,
        "source_file": "hebei_2025_01_16.pdf",
        "source_url": (
            "https://drc.chengde.gov.cn/module/download/downfile.jsp?"
            "classid=0&filename=7648b6dd9ce14c50bfe51657f97e0290.pdf"
        ),
        "source_strength": "DIRECT_OFFICIAL_PROVINCIAL_RETAIL_TABLE",
    },
    "guangdong": {
        "price_cny_per_l": 7.44,
        "source_file": "guangdong_2025_01_16.html",
        "source_url": (
            "https://www.zhanjiang.gov.cn/zjfgj/gkmlpt/content/2/"
            "2002/post_2002007.html"
        ),
        "source_strength": (
            "DIRECT_GOVERNMENT_MIRROR_OF_PROVINCIAL_DRC_TABLE"
        ),
    },
    "sichuan": {
        "price_cny_per_l": 7.48,
        "source_file": "sichuan_2025_h1_price_gazette.pdf",
        "source_url": (
            "https://fgw.sc.gov.cn/sfgw/jggb/2025/8/4/"
            "119ccf6d200b4d5f86cd8d56125bd793/files/"
            "%E3%80%8A%E4%BB%B7%E6%A0%BC%E5%85%AC%E6%8A%A5%C2%B7"
            "%E5%9B%9B%E5%B7%9D%E3%80%8B2025%E5%B9%B4%E4%B8%8A"
            "%E5%8D%8A%E5%B9%B4%E5%90%88%E5%88%8A-"
            "20250804125716253.pdf"
        ),
        "source_strength": "DIRECT_OFFICIAL_PROVINCIAL_PRICE_GAZETTE",
    },
    "chongqing": {
        "price_cny_per_l": 7.50,
        "source_file": "ndrc_2025_01_16_table.png",
        "supporting_source_file": "chongqing_2025_02_19.html",
        "source_url": (
            "https://www.ndrc.gov.cn/xwdt/xwfb/202501/"
            "t20250116_1395727.html"
        ),
        "source_strength": (
            "DERIVED_FROM_OFFICIAL_NDRC_PER_TON_AND_OFFICIAL_LOCAL_"
            "ADJACENT_RETAIL_TABLES"
        ),
    },
}


@dataclass(frozen=True)
class Check:
    check_id: str
    lane: str
    severity: str
    status: str
    subject: str
    observed: str
    expected: str
    evidence: str
    impact: str
    repair_authority: str


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def coordinate_key(
    instance_id: str,
    city: str,
    latitude: str | float,
    longitude: str | float,
) -> tuple[str, str, str, str]:
    return (
        instance_id,
        city.strip().lower(),
        f"{float(latitude):.7f}",
        f"{float(longitude):.7f}",
    )


def parse_osm_tags(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("OSM tags field is not a JSON object")
    return value


def active_customer_pools() -> dict[str, dict[tuple[str, str], dict[str, str]]]:
    """Replay the exact pool precedence used by the frozen assignment builder."""

    pools: dict[str, dict[tuple[str, str], dict[str, str]]] = {}
    for root in (BASE_CUSTOMER_POOL, LEGACY_CUSTOMER_POOL_OVERLAY):
        for path in sorted((root / "pools").glob("*__named_poi.csv")):
            city = path.name.split("__", 1)[0]
            city_pool = pools.setdefault(city, {})
            for row in read_csv(path):
                city_pool[(row["osm_type"], row["osm_id"])] = row
    chongqing_path = (
        MC005_CUSTOMER_POOL_CLOSURE
        / "pools/chongqing__merged_named_poi.csv"
    )
    pools["chongqing"] = {
        (row["osm_type"], row["osm_id"]): row
        for row in read_csv(chongqing_path)
    }
    return pools


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def literal_assignment(path: Path, name: str) -> Any:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            return ast.literal_eval(node.value)
    raise KeyError(f"{name} is not a literal assignment in {path}")


def reviewed_period_for(city: str, minute_of_day: int) -> str:
    hour = minute_of_day / 60.0
    for label in ("sharp_peak", "peak", "valley"):
        windows = REVIEWED_FEBRUARY_PERIODS[city].get(label, [])
        if any(start <= hour < end for start, end in windows):
            return label
    return "flat"


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def add(
    checks: list[Check],
    *,
    check_id: str,
    lane: str,
    severity: str,
    status: str,
    subject: str,
    observed: Any,
    expected: Any,
    evidence: str,
    impact: str = "",
    repair_authority: str = "",
) -> None:
    checks.append(
        Check(
            check_id=check_id,
            lane=lane,
            severity=severity,
            status=status,
            subject=subject,
            observed=str(observed),
            expected=str(expected),
            evidence=evidence,
            impact=impact,
            repair_authority=repair_authority,
        )
    )


def audit_authority_and_hashes(checks: list[Check]) -> dict[str, Any]:
    foundation = read_json(FOUNDATION)
    parameter_lock = read_json(PARAMETER_LOCK)
    static_hashes = read_json(STATIC / "artifact_hashes.json")["sha256"]
    catalog = read_csv(CATALOG)
    g1 = {row["instance_id"]: row for row in read_csv(G1_MANIFEST)}

    held = (
        foundation.get("formal_search_allowed") is False
        and foundation.get("search_evaluations") == 0
        and parameter_lock.get("formal_search_allowed") is False
        and parameter_lock.get("status") == "NOT_FORMAL"
    )
    add(
        checks,
        check_id="A1-01",
        lane="A1",
        severity="P0",
        status="PASS" if held else "FAIL",
        subject="formal release authority",
        observed={
            "foundation": foundation.get("formal_search_allowed"),
            "foundation_search_evaluations": foundation.get("search_evaluations"),
            "parameter_lock": parameter_lock.get("formal_search_allowed"),
            "parameter_status": parameter_lock.get("status"),
        },
        expected="all formal-search gates false and zero evaluations",
        evidence=f"{FOUNDATION.relative_to(REPO)}; {PARAMETER_LOCK.relative_to(REPO)}",
        impact="Audit must not accidentally release formal search.",
    )

    mismatches: list[str] = []
    for relative, expected in static_hashes.items():
        path = STATIC / relative
        if not path.is_file() or sha256(path) != expected:
            mismatches.append(relative)
    add(
        checks,
        check_id="A1-02",
        lane="A1",
        severity="P0",
        status="PASS" if not mismatches else "FAIL",
        subject="frozen static-input hashes",
        observed=f"{len(static_hashes) - len(mismatches)}/{len(static_hashes)} match",
        expected=f"{len(static_hashes)}/{len(static_hashes)} match",
        evidence=str((STATIC / "artifact_hashes.json").relative_to(REPO)),
        impact=";".join(mismatches[:20]),
    )

    manifest_errors: list[str] = []
    for row in catalog:
        instance_id = row["instance_id"]
        nodes = STATIC / "instances" / instance_id / "nodes.csv"
        if instance_id not in g1:
            manifest_errors.append(f"{instance_id}:missing_g1_manifest")
            continue
        actual = sha256(nodes)
        if actual != row["nodes_sha256"] or actual != g1[instance_id]["nodes_sha256"]:
            manifest_errors.append(f"{instance_id}:nodes_hash_disagreement")
        for profile in ("cv", "ev"):
            profile_root = MATRICES / instance_id / profile
            for name in (
                "nodes.csv",
                "road_distance_m.csv",
                "road_duration_s.csv",
                "road_sum_v2d_m3_s2.csv",
            ):
                if not (profile_root / name).is_file():
                    manifest_errors.append(f"{instance_id}:{profile}:{name}:missing")
    add(
        checks,
        check_id="A1-02B",
        lane="A1",
        severity="P0",
        status="PASS" if not manifest_errors else "FAIL",
        subject="catalog/G1/matrix file join",
        observed=f"{len(catalog) - len({x.split(':')[0] for x in manifest_errors})}/"
        f"{len(catalog)} instances without join error",
        expected="81/81",
        evidence=f"{CATALOG.relative_to(REPO)}; {G1_MANIFEST.relative_to(REPO)}",
        impact=";".join(manifest_errors[:20]),
    )

    protected_diff = git("diff", "--", *PROTECTED_FILES)
    add(
        checks,
        check_id="A1-06",
        lane="A1",
        severity="P0",
        status="PASS" if not protected_diff else "FAIL",
        subject="protected evaluator files",
        observed="clean" if not protected_diff else "working-tree diff present",
        expected="no unreviewed diff",
        evidence="git diff -- " + " ".join(PROTECTED_FILES),
        impact=protected_diff[:1000],
    )

    return {
        "catalog": catalog,
        "foundation": foundation,
        "parameter_lock": parameter_lock,
        "static_hash_mismatches": mismatches,
        "manifest_errors": manifest_errors,
    }


def audit_instance_joins(
    checks: list[Check],
    catalog: list[dict[str, str]],
) -> dict[str, Any]:
    orders = read_csv(ORDERS)
    assignments = read_csv(ASSIGNMENTS)
    orders_by_instance: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in orders:
        orders_by_instance[row["instance_id"]].append(row)

    assignment_by_coordinate: dict[
        tuple[str, str, str, str], list[dict[str, str]]
    ] = defaultdict(list)
    assignment_parse_errors: list[str] = []
    source_hash_expectations: dict[str, set[str]] = defaultdict(set)
    for assignment in assignments:
        try:
            tags = parse_osm_tags(assignment["tags"])
        except (json.JSONDecodeError, ValueError) as exc:
            assignment_parse_errors.append(
                f"{assignment['instance_id']}:{assignment['osm_type']}:"
                f"{assignment['osm_id']}:tags:{exc}"
            )
            tags = {}
        assignment["_tag_country"] = str(
            tags.get("addr:country")
            or tags.get("country")
            or tags.get("ISO3166-1")
            or ""
        ).upper()
        assignment_by_coordinate[
            coordinate_key(
                assignment["instance_id"],
                assignment["city"],
                assignment["latitude"],
                assignment["longitude"],
            )
        ].append(assignment)
        source_hash_expectations[assignment["source_response_path"]].add(
            assignment["source_response_sha256"]
        )

    source_errors: list[str] = []
    for relative, expected_hashes in sorted(source_hash_expectations.items()):
        source = REPO / relative
        if len(expected_hashes) != 1:
            source_errors.append(
                f"{relative}:conflicting_expected_hashes={len(expected_hashes)}"
            )
        elif not source.is_file():
            source_errors.append(f"{relative}:missing")
        elif sha256(source) not in expected_hashes:
            source_errors.append(f"{relative}:sha256_mismatch")
    add(
        checks,
        check_id="A1-02C",
        lane="A1",
        severity="P0",
        status="PASS" if not source_errors else "FAIL",
        subject="customer-assignment raw-source hash replay",
        observed=(
            f"{len(source_hash_expectations) - len(source_errors)}/"
            f"{len(source_hash_expectations)} unique raw sources match"
        ),
        expected="every assignment source exists and matches its frozen SHA-256",
        evidence=str(ASSIGNMENTS.relative_to(REPO)),
        impact=";".join(source_errors[:20]),
    )

    location_contract = read_json(LOCATION_CONTRACT)
    cells: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    for assignment in assignments:
        cells[(assignment["region"], int(assignment["customer_size"]))].append(
            assignment
        )
    cell_errors: list[str] = []
    physical_duplicate_rows: list[dict[str, Any]] = []
    physical_duplicate_instances: set[str] = set()
    for (region, customer_size), rows in sorted(cells.items()):
        expected_rows = (
            len(location_contract["replicate_labels"]) * customer_size
        )
        identities = [
            (row["osm_type"], row["osm_id"])
            for row in rows
        ]
        if len(rows) != expected_rows:
            cell_errors.append(
                f"{region}/{customer_size}:rows={len(rows)}:"
                f"expected={expected_rows}"
            )
        duplicate_identities = [
            identity
            for identity, count in Counter(identities).items()
            if count > 1
        ]
        if duplicate_identities:
            cell_errors.append(
                f"{region}/{customer_size}:duplicate_osm_identities="
                f"{len(duplicate_identities)}"
            )
        by_physical_point: dict[
            tuple[str, str, str], list[dict[str, str]]
        ] = defaultdict(list)
        for row in rows:
            by_physical_point[
                (
                    row["city"],
                    f"{float(row['latitude']):.7f}",
                    f"{float(row['longitude']):.7f}",
                )
            ].append(row)
        for (city, latitude, longitude), point_rows in by_physical_point.items():
            if len(point_rows) <= 1:
                continue
            distinct_replicates = sorted(
                {row["replicate"] for row in point_rows}
            )
            if len(distinct_replicates) <= 1:
                continue
            physical_duplicate_instances.update(
                row["instance_id"] for row in point_rows
            )
            physical_duplicate_rows.append(
                {
                    "region": region,
                    "customer_size": customer_size,
                    "city": city,
                    "latitude": latitude,
                    "longitude": longitude,
                    "replicates": "|".join(distinct_replicates),
                    "instances": "|".join(
                        sorted({row["instance_id"] for row in point_rows})
                    ),
                    "osm_identities": "|".join(
                        sorted(
                            {
                                f"{row['osm_type']}:{row['osm_id']}"
                                for row in point_rows
                            }
                        )
                    ),
                    "names": "|".join(
                        sorted({row["name"] for row in point_rows})
                    ),
                    "classification": (
                        "EXACT_PHYSICAL_POINT_REUSED_ACROSS_CELL_REPLICATES"
                    ),
                }
            )

    write_csv(
        OUT / "customer_physical_duplicates.csv",
        physical_duplicate_rows,
        [
            "region",
            "customer_size",
            "city",
            "latitude",
            "longitude",
            "replicates",
            "instances",
            "osm_identities",
            "names",
            "classification",
        ],
    )
    add(
        checks,
        check_id="A2-03-IDENTITY",
        lane="A2",
        severity="P0",
        status=(
            "PASS"
            if len(assignments) == 5805
            and len(cells) == 27
            and not cell_errors
            and not assignment_parse_errors
            else "FAIL"
        ),
        subject="customer-assignment row count and within-cell OSM-identity disjointness",
        observed={
            "assignment_rows": len(assignments),
            "unique_osm_identities_across_sizes": len(
                {
                    (row["osm_type"], row["osm_id"])
                    for row in assignments
                }
            ),
            "region_size_cells": len(cells),
            "cell_errors": len(cell_errors),
            "tag_parse_errors": len(assignment_parse_errors),
        },
        expected=(
            "5805 rows; 27 cells; zero within-cell identity overlap; "
            "cross-size identity reuse allowed by contract"
        ),
        evidence=(
            f"{ASSIGNMENTS.relative_to(REPO)}; "
            f"{LOCATION_CONTRACT.relative_to(REPO)}"
        ),
        impact=";".join((cell_errors + assignment_parse_errors)[:20]),
    )
    add(
        checks,
        check_id="A2-03-PHYSICAL",
        lane="A2",
        severity="P0",
        status="PASS" if not physical_duplicate_rows else "FAIL",
        subject="within-cell physical-location disjointness beyond OSM identity",
        observed={
            "exact_coordinate_duplicate_groups": len(physical_duplicate_rows),
            "affected_instances": sorted(physical_duplicate_instances),
        },
        expected="no exact physical point reused across the three maps in a cell",
        evidence="customer_physical_duplicates.csv",
        impact=(
            "OSM way/relation aliases can bypass the identity-only disjointness "
            "gate and create pseudoreplicated customer locations."
        ),
        repair_authority=(
            "Deduplicate pools by physical feature before a deterministic "
            "versioned rebuild; preserve all old evidence."
        ),
    )

    city_node_counts: Counter[tuple[str, str]] = Counter()
    instance_city_sets: dict[str, set[str]] = {}
    errors: list[str] = []
    coordinate_rows: list[dict[str, Any]] = []
    for row in catalog:
        instance_id = row["instance_id"]
        nodes_path = STATIC / "instances" / instance_id / "nodes.csv"
        nodes = read_csv(nodes_path)
        customers = [node for node in nodes if node["node_type"] == "customer"]
        orders_here = orders_by_instance.get(instance_id, [])
        expected = int(row["customer_count"])
        if len(customers) != expected or len(orders_here) != expected:
            errors.append(
                f"{instance_id}:customers={len(customers)} orders={len(orders_here)} "
                f"expected={expected}"
            )
        order_map = {order["customer_id"]: order for order in orders_here}
        if len(order_map) != len(orders_here):
            errors.append(f"{instance_id}:duplicate_customer_order")
        for node in nodes:
            city = node["city"].strip().lower()
            city_node_counts[(city, node["node_type"])] += 1
            assignment_matches: list[dict[str, str]] = []
            if node["node_type"] == "customer":
                assignment_matches = assignment_by_coordinate.get(
                    coordinate_key(
                        instance_id,
                        city,
                        node["latitude"],
                        node["longitude"],
                    ),
                    [],
                )
                if len(assignment_matches) != 1:
                    errors.append(
                        f"{instance_id}:{node['node_id']}:"
                        f"assignment_coordinate_matches={len(assignment_matches)}"
                    )
            assignment = (
                assignment_matches[0] if len(assignment_matches) == 1 else {}
            )
            coordinate_rows.append(
                {
                    "instance_id": instance_id,
                    "node_id": node["node_id"],
                    "node_type": node["node_type"],
                    "declared_city": city,
                    "latitude": node["latitude"],
                    "longitude": node["longitude"],
                    "osm_type": assignment.get("osm_type", ""),
                    "osm_id": assignment.get("osm_id", ""),
                    "name": assignment.get("name", ""),
                    "tag_country": assignment.get("_tag_country", ""),
                    "source_response_path": assignment.get(
                        "source_response_path", ""
                    ),
                    "gis_status": "PENDING_BOUNDARY_EVIDENCE",
                }
            )
            if city not in REVIEWED_CITY_MAPPING:
                errors.append(f"{instance_id}:{node['node_id']}:unknown_city={city}")
            if node["node_type"] == "customer":
                order = order_map.get(node["node_id"])
                if order is None:
                    errors.append(f"{instance_id}:{node['node_id']}:missing_order")
                elif (
                    order["city"].strip().lower() != city
                    or not math.isclose(
                        float(order["latitude"]),
                        float(node["latitude"]),
                        abs_tol=1e-10,
                    )
                    or not math.isclose(
                        float(order["longitude"]),
                        float(node["longitude"]),
                        abs_tol=1e-10,
                    )
                ):
                    errors.append(f"{instance_id}:{node['node_id']}:order_node_mismatch")
        cities = {node["city"].strip().lower() for node in nodes}
        instance_city_sets[instance_id] = cities
        if "|".join(sorted(cities)) != row["cities"]:
            errors.append(f"{instance_id}:catalog_city_set_mismatch")

    add(
        checks,
        check_id="A2-03-LABEL",
        lane="A2",
        severity="P0",
        status="PASS" if not errors else "FAIL",
        subject="5805 customer/node/order city-label join",
        observed=f"{len(orders)} orders; {len(errors)} join errors",
        expected="5805 orders; 0 join errors",
        evidence=f"{ORDERS.relative_to(REPO)}; {STATIC.relative_to(REPO)}/instances/*/nodes.csv",
        impact=";".join(errors[:20]),
    )

    write_csv(
        OUT / "coordinate_inventory.csv",
        coordinate_rows,
        [
            "instance_id",
            "node_id",
            "node_type",
            "declared_city",
            "latitude",
            "longitude",
            "osm_type",
            "osm_id",
            "name",
            "tag_country",
            "source_response_path",
            "gis_status",
        ],
    )

    return {
        "orders": orders,
        "instance_city_sets": instance_city_sets,
        "city_node_counts": city_node_counts,
        "join_errors": errors,
        "coordinate_rows": coordinate_rows,
        "assignments": assignments,
        "physical_duplicate_instances": sorted(physical_duplicate_instances),
        "physical_duplicate_rows": physical_duplicate_rows,
    }


def audit_gis(
    checks: list[Check],
    coordinate_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        from shapely.geometry import Point, shape
        from shapely.validation import explain_validity
    except ImportError as exc:
        add(
            checks,
            check_id="A2-01/02/03-GIS",
            lane="A2",
            severity="P1",
            status="PENDING",
            subject="administrative-boundary geometry runtime",
            observed=f"Shapely unavailable: {exc}",
            expected="project-isolated Shapely geometry validator",
            evidence="build/python_envs/pre-e3-audit-20260723",
            impact="Point-in-boundary validation could not run.",
        )
        return {"status": "PENDING", "errors": ["shapely_unavailable"]}

    loaded_files: dict[Path, dict[str, Any]] = {}
    geometries: dict[str, Any] = {}
    source_rows: list[dict[str, Any]] = []
    geometry_errors: list[str] = []
    for city, spec in GIS_BOUNDARY_SPECS.items():
        path = GIS_ROOT / spec["path"]
        if path not in loaded_files:
            loaded_files[path] = read_json(path)
        matches = [
            feature
            for feature in loaded_files[path]["features"]
            if feature.get("properties", {}).get("name") == spec["name"]
            and feature.get("properties", {}).get("admin_level")
            == spec["admin_level"]
        ]
        expected_area_id = f"a{2 * int(spec['relation_id']) + 1}"
        matches = [
            feature
            for feature in matches
            if feature.get("id") == expected_area_id
        ]
        if len(matches) != 1:
            geometry_errors.append(
                f"{city}:expected_one_boundary_feature:found={len(matches)}"
            )
            continue
        geometry = shape(matches[0]["geometry"])
        if geometry.is_empty or not geometry.is_valid:
            geometry_errors.append(
                f"{city}:invalid_geometry:{explain_validity(geometry)}"
            )
        geometries[city] = geometry
        source_pbf = REPO / spec["source_pbf"]
        source_rows.append(
            {
                "city": city,
                "boundary_name": spec["name"],
                "admin_level": spec["admin_level"],
                "osm_relation_id": spec["relation_id"],
                "source_pbf": spec["source_pbf"],
                "source_pbf_sha256": sha256(source_pbf),
                "extracted_geojson": str(path.relative_to(REPO)),
                "extracted_geojson_sha256": sha256(path),
                "geometry_type": geometry.geom_type,
                "geometry_valid": geometry.is_valid,
                "geometry_area_square_degrees": geometry.area,
                "source_class": "COMPUTATIONAL_VALIDATION_BOUNDARY_NOT_OFFICIAL_CHINA_SURVEY",
                "source_timestamp": "2026-07-16",
                "license": "OpenStreetMap ODbL",
            }
        )

    write_csv(
        GIS_ROOT / "boundary_source_manifest.csv",
        source_rows,
        list(source_rows[0]) if source_rows else [
            "city",
            "boundary_name",
            "admin_level",
            "osm_relation_id",
            "source_pbf",
            "source_pbf_sha256",
            "extracted_geojson",
            "extracted_geojson_sha256",
            "geometry_type",
            "geometry_valid",
            "geometry_area_square_degrees",
            "source_class",
            "source_timestamp",
            "license",
        ],
    )

    row_errors: list[str] = []
    row_errors_by_type: dict[str, list[str]] = defaultdict(list)
    cross_city_errors: list[str] = []
    validated_rows: list[dict[str, Any]] = []
    for row in coordinate_rows:
        point = Point(float(row["longitude"]), float(row["latitude"]))
        memberships = sorted(
            city
            for city, geometry in geometries.items()
            if geometry.covers(point)
        )
        declared = row["declared_city"]
        status = (
            "PASS_DECLARED_CITY_BOUNDARY"
            if declared in memberships and memberships == [declared]
            else "FAIL_CITY_BOUNDARY"
        )
        if declared not in memberships:
            message = (
                f"{row['instance_id']}:{row['node_id']}:{declared}:"
                f"memberships={'|'.join(memberships) or 'NONE'}"
            )
            row_errors.append(message)
            row_errors_by_type[row["node_type"]].append(message)
        if len(memberships) != 1:
            cross_city_errors.append(
                f"{row['instance_id']}:{row['node_id']}:"
                f"memberships={'|'.join(memberships) or 'NONE'}"
            )
        validated_rows.append(
            {
                **row,
                "gis_status": status,
                "boundary_memberships": "|".join(memberships),
                "boundary_source_date": "2026-07-16",
                "boundary_source_class": (
                    "COMPUTATIONAL_VALIDATION_BOUNDARY_NOT_OFFICIAL_CHINA_SURVEY"
                ),
            }
        )

    write_csv(
        OUT / "coordinate_inventory.csv",
        validated_rows,
        [
            "instance_id",
            "node_id",
            "node_type",
            "declared_city",
            "latitude",
            "longitude",
            "osm_type",
            "osm_id",
            "name",
            "tag_country",
            "source_response_path",
            "gis_status",
            "boundary_memberships",
            "boundary_source_date",
            "boundary_source_class",
        ],
    )

    customer_exceptions = [
        row
        for row in validated_rows
        if row["node_type"] == "customer"
        and row["gis_status"] != "PASS_DECLARED_CITY_BOUNDARY"
    ]
    write_csv(
        OUT / "customer_geography_exceptions.csv",
        customer_exceptions,
        [
            "instance_id",
            "node_id",
            "node_type",
            "declared_city",
            "latitude",
            "longitude",
            "osm_type",
            "osm_id",
            "name",
            "tag_country",
            "source_response_path",
            "gis_status",
            "boundary_memberships",
            "boundary_source_date",
            "boundary_source_class",
        ],
    )

    unique_points: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in validated_rows:
        key = (
            row["node_type"],
            row["declared_city"],
            row["latitude"],
            row["longitude"],
        )
        unique_points.setdefault(key, row)
    unique_by_type = Counter(key[0] for key in unique_points)
    unique_errors_by_type = Counter()
    for key, row in unique_points.items():
        if row["gis_status"] != "PASS_DECLARED_CITY_BOUNDARY":
            unique_errors_by_type[key[0]] += 1
    row_counts_by_type = Counter(row["node_type"] for row in validated_rows)

    for check_id, node_type, label, expected_unique in (
        ("A2-01", "depot", "nine depot road-access points", 9),
        ("A2-02", "station", "nine public charging stations", 9),
    ):
        type_errors = unique_errors_by_type[node_type]
        unique_count = unique_by_type[node_type]
        add(
            checks,
            check_id=check_id,
            lane="A2",
            severity="P1",
            status=(
                "PASS"
                if not geometry_errors
                and type_errors == 0
                and unique_count == expected_unique
                else "FAIL"
            ),
            subject=f"WGS84 administrative-boundary check: {label}",
            observed=f"unique={unique_count}; outside_or_ambiguous={type_errors}",
            expected=f"unique={expected_unique}; outside_or_ambiguous=0",
            evidence=(
                "coordinate_inventory.csv; "
                "gis/osm_boundaries/boundary_source_manifest.csv"
            ),
            impact=";".join(row_errors_by_type[node_type][:20]),
        )

    customer_identity_count = len(
        {
            (row["osm_type"], row["osm_id"])
            for row in validated_rows
            if row["node_type"] == "customer"
        }
    )
    customer_failed_instances = sorted(
        {row["instance_id"] for row in customer_exceptions}
    )
    add(
        checks,
        check_id="A2-03",
        lane="A2",
        severity="P0",
        status=(
            "PASS"
            if not geometry_errors
            and row_counts_by_type["customer"] == 5805
            and not customer_exceptions
            else "FAIL"
        ),
        subject="5805 customer-assignment WGS84 administrative-boundary check",
        observed={
            "assignment_rows": row_counts_by_type["customer"],
            "unique_osm_identities": customer_identity_count,
            "unique_physical_points": unique_by_type["customer"],
            "outside_rows": len(customer_exceptions),
            "outside_unique_points": unique_errors_by_type["customer"],
            "affected_instances": customer_failed_instances,
        },
        expected=(
            "5805 assignment rows; every point is covered by exactly its declared "
            "city boundary; cross-size identity reuse is allowed"
        ),
        evidence=(
            "coordinate_inventory.csv; customer_geography_exceptions.csv; "
            "gis/osm_boundaries/boundary_source_manifest.csv"
        ),
        impact=";".join(row_errors_by_type["customer"][:20]),
        repair_authority=(
            "Filter the frozen source pool by declared administrative boundary, "
            "then create a deterministic versioned rebuild; do not overwrite E2."
        ),
    )

    foreign_tagged = [
        row
        for row in validated_rows
        if row["node_type"] == "customer"
        and row["tag_country"]
        and row["tag_country"] not in {"CN", "CHN"}
    ]
    foreign_tagged_outside = [
        row
        for row in foreign_tagged
        if row["gis_status"] != "PASS_DECLARED_CITY_BOUNDARY"
    ]
    add(
        checks,
        check_id="A2-03-TAGS",
        lane="A2",
        severity="P1",
        status="FAIL" if foreign_tagged_outside else "PASS",
        subject="OSM country tags cross-checked against geometric membership",
        observed={
            "non_CN_tag_rows": len(foreign_tagged),
            "non_CN_tag_rows_outside_declared_city": len(
                foreign_tagged_outside
            ),
            "note": (
                "inside-city foreign tags include diplomatic premises and are "
                "not interpreted as geographic country membership"
            ),
        },
        expected="no explicitly foreign-tagged point outside its declared city",
        evidence="coordinate_inventory.csv; customer_geography_exceptions.csv",
        impact=(
            "The Hong Kong-tagged Shenzhen-pool POI confirms that the source "
            "query bbox crossed an administrative boundary."
        ),
    )

    pool_audit_rows: list[dict[str, Any]] = []
    pool_outside_counts: Counter[str] = Counter()
    for city, pool in sorted(active_customer_pools().items()):
        geometry = geometries.get(city)
        if geometry is None:
            continue
        for (osm_type, osm_id), row in sorted(pool.items()):
            point = Point(float(row["longitude"]), float(row["latitude"]))
            memberships = sorted(
                candidate
                for candidate, candidate_geometry in geometries.items()
                if candidate_geometry.covers(point)
            )
            status = (
                "PASS_DECLARED_CITY_BOUNDARY"
                if memberships == [city]
                else "FAIL_CITY_BOUNDARY"
            )
            if status != "PASS_DECLARED_CITY_BOUNDARY":
                pool_outside_counts[city] += 1
            tags = parse_osm_tags(row.get("tags", ""))
            pool_audit_rows.append(
                {
                    "declared_city": city,
                    "osm_type": osm_type,
                    "osm_id": osm_id,
                    "latitude": row["latitude"],
                    "longitude": row["longitude"],
                    "name": row.get("name", ""),
                    "tag_country": str(
                        tags.get("addr:country")
                        or tags.get("country")
                        or tags.get("ISO3166-1")
                        or ""
                    ).upper(),
                    "boundary_memberships": "|".join(memberships),
                    "gis_status": status,
                    "source_response_path": row.get(
                        "source_response_path", ""
                    ),
                }
            )
    write_csv(
        OUT / "customer_pool_boundary_audit.csv",
        pool_audit_rows,
        [
            "declared_city",
            "osm_type",
            "osm_id",
            "latitude",
            "longitude",
            "name",
            "tag_country",
            "boundary_memberships",
            "gis_status",
            "source_response_path",
        ],
    )
    add(
        checks,
        check_id="A2-03-POOL",
        lane="A2",
        severity="P0",
        status="PASS" if not pool_outside_counts else "FAIL",
        subject="active customer-pool administrative-boundary filter",
        observed={
            "active_pool_identities": len(pool_audit_rows),
            "outside_by_declared_city": dict(pool_outside_counts),
        },
        expected="zero out-of-city identities before seeded selection",
        evidence="customer_pool_boundary_audit.csv",
        impact=(
            "The assignment builder currently samples a bbox-derived pool "
            "without a geographic membership filter."
        ),
        repair_authority=(
            "Add a pre-seed, fail-closed boundary filter and rerun the frozen "
            "deterministic assignment build under a new version."
        ),
    )

    road_rows = read_csv(ROAD_ACCESS)
    provenance_errors = [
        row["city"]
        for row in road_rows
        if row["source_kind"]
        not in {"operator_bd09_center", "baidu_mercator_place"}
        or not row["road_access_lon_wgs84"]
        or not row["road_access_lat_wgs84"]
        or row["point_semantics"]
        != "SCENARIO_ROAD_ACCESS_POINT_NOT_OBSERVED_TRUCK_GATE"
    ]
    add(
        checks,
        check_id="A2-04",
        lane="A2",
        severity="P1",
        status="PASS" if not provenance_errors else "FAIL",
        subject="BD09/BD09MC -> GCJ02 -> WGS84 facility-coordinate provenance",
        observed=(
            "9/9 source kinds and scenario semantics explicit"
            if not provenance_errors
            else ";".join(provenance_errors)
        ),
        expected="no raw BD09/BD09MC values presented as WGS84",
        evidence=(
            f"{ROAD_ACCESS.relative_to(REPO)}; "
            "baselines/china_instances/build_phase1_nine_city_road_access_20260718.py"
        ),
        impact=(
            "Conversion implementation remains a reproducible scenario-coordinate "
            "pipeline; road-access points are not claimed as observed truck gates."
        ),
    )
    add(
        checks,
        check_id="A2-09",
        lane="A2",
        severity="P1",
        status="FAIL",
        subject="wrong-city fault injection at runtime loader",
        observed=(
            "Current loader checks node.city against order.city only; a coordinated "
            "wrong label passes and selects that wrong city's price/carbon rows."
        ),
        expected="coordinates outside declared city fail closed before bundle creation",
        evidence="solver/src/setp_solver/china81.py::_node_from_rows",
        impact="A corrupted but internally consistent city label silently misprices a node.",
        repair_authority="Add a versioned city-boundary validation registry and negative test.",
    )

    return {
        "status": "PASS" if not geometry_errors and not row_errors else "FAIL",
        "geometry_errors": geometry_errors,
        "row_errors": row_errors,
        "cross_city_errors": cross_city_errors,
        "unique_by_type": dict(unique_by_type),
        "outside_customer_rows": len(customer_exceptions),
        "outside_customer_unique_points": unique_errors_by_type["customer"],
        "affected_customer_instances": customer_failed_instances,
        "pool_outside_counts": dict(pool_outside_counts),
    }


def audit_mapping_and_calendar(
    checks: list[Check],
    instance_city_sets: dict[str, set[str]],
) -> dict[str, Any]:
    builder_mapping = literal_assignment(BUILDER, "CITIES")
    tariff_v2 = read_json(TARIFF_V2)
    tariff_v3 = read_json(TARIFF_V3)
    calendar = read_csv(CALENDAR)
    tvci_rows = read_csv(TVCI)
    tvci = {
        (row["date"], int(row["half_hour_slot"])): row
        for row in tvci_rows
    }

    mapping_rows: list[dict[str, Any]] = []
    carbon_mapping_errors: list[str] = []
    price_mapping_errors: list[str] = []
    for city, reviewed in REVIEWED_CITY_MAPPING.items():
        actual_region, actual_carbon, actual_price_area = builder_mapping[city]
        registered_price_area = tariff_v2["city_to_price_area"].get(city)
        mapping_rows.append(
            {
                "city": city,
                **reviewed,
                "builder_region": actual_region,
                "builder_price_area_id": actual_price_area,
                "builder_carbon_column": actual_carbon,
                "calendar_carbon_columns": "|".join(
                    sorted(
                        {
                            row["carbon_source_column"]
                            for row in calendar
                            if row["city"] == city
                        }
                    )
                ),
                "price_mapping_status": (
                    "PASS"
                    if actual_price_area == reviewed["price_area_id"]
                    and registered_price_area == reviewed["price_area_id"]
                    else "FAIL"
                ),
                "carbon_mapping_status": (
                    "PASS"
                    if actual_carbon == reviewed["carbon_column"]
                    else "FAIL"
                ),
                "gis_status": "PENDING_BOUNDARY_EVIDENCE",
                "runtime_selector": "explicit node.city label",
            }
        )
        if actual_price_area != reviewed["price_area_id"]:
            price_mapping_errors.append(
                f"{city}:builder={actual_price_area}:expected={reviewed['price_area_id']}"
            )
        if registered_price_area != reviewed["price_area_id"]:
            price_mapping_errors.append(
                f"{city}:register={registered_price_area}:expected={reviewed['price_area_id']}"
            )
        if actual_carbon != reviewed["carbon_column"]:
            carbon_mapping_errors.append(
                f"{city}:builder={actual_carbon}:expected={reviewed['carbon_column']}"
            )

    write_csv(
        OUT / "city_parameter_mapping_registry.csv",
        mapping_rows,
        list(mapping_rows[0]),
    )
    add(
        checks,
        check_id="A2-05",
        lane="A2",
        severity="P0",
        status="PASS" if not price_mapping_errors else "FAIL",
        subject="city -> region -> price_area_id mapping",
        observed=";".join(price_mapping_errors) if price_mapping_errors else "9/9 match",
        expected="9/9 explicit reviewed mappings",
        evidence="city_parameter_mapping_registry.csv",
        impact="Wrong price-area mapping changes charging cost.",
    )
    add(
        checks,
        check_id="A4-01",
        lane="A4",
        severity="P0",
        status="PASS" if not carbon_mapping_errors else "FAIL",
        subject="city -> provincial carbon column mapping",
        observed=";".join(carbon_mapping_errors) if carbon_mapping_errors else "9/9 match",
        expected="9/9 city-province mappings",
        evidence="city_parameter_mapping_registry.csv",
        impact="Wrong carbon column changes emissions and carbon cost.",
        repair_authority="Deterministic mapping bug may be corrected without changing the model.",
    )

    key_counts = Counter(
        (row["city"], row["date"], int(row["half_hour_slot"]))
        for row in calendar
    )
    duplicate_keys = [key for key, count in key_counts.items() if count != 1]
    expected_dates = {f"2025-02-{day:02d}" for day in range(1, 29)}
    calendar_errors: list[str] = []
    for city in REVIEWED_CITY_MAPPING:
        city_rows = [row for row in calendar if row["city"] == city]
        if len(city_rows) != 28 * 48:
            calendar_errors.append(f"{city}:rows={len(city_rows)}")
        if {row["date"] for row in city_rows} != expected_dates:
            calendar_errors.append(f"{city}:date_set")
        for date in expected_dates:
            slots = sorted(
                int(row["half_hour_slot"])
                for row in city_rows
                if row["date"] == date
            )
            if slots != list(range(1, 49)):
                calendar_errors.append(f"{city}:{date}:slots")
                break
        noncanonical_starts = [
            row
            for row in city_rows
            if int(row["minute_of_day"])
            != (int(row["half_hour_slot"]) - 1) * 30
        ]
        if noncanonical_starts:
            calendar_errors.append(
                f"{city}:noncanonical_minute_of_day="
                f"{len(noncanonical_starts)}"
            )
    if duplicate_keys:
        calendar_errors.append(f"duplicate_keys={len(duplicate_keys)}")
    add(
        checks,
        check_id="A3-09",
        lane="A3",
        severity="P0",
        status="PASS" if not calendar_errors else "FAIL",
        subject="full-month 48-slot calendar completeness",
        observed=f"{len(calendar)} rows; errors={len(calendar_errors)}",
        expected="12096 rows; 9 cities x 28 days x 48 unique slots",
        evidence=str(CALENDAR.relative_to(REPO)),
        impact=";".join(calendar_errors[:20]),
    )

    arithmetic_errors: list[str] = []
    source_value_errors: list[str] = []
    chengdu_differences: list[float] = []
    for row in calendar:
        total = float(row["public_total_cny_per_kwh"])
        expected_total = (
            float(row["public_energy_cny_per_kwh"])
            + float(row["public_service_fee_cny_per_kwh"])
        )
        if not math.isclose(total, expected_total, rel_tol=0.0, abs_tol=1e-9):
            arithmetic_errors.append(
                f"{row['city']}:{row['date']}:{row['half_hour_slot']}"
            )
        source = tvci[(row["date"], int(row["half_hour_slot"]))]
        actual_source_value = float(source[row["carbon_source_column"]])
        if not math.isclose(
            float(row["carbon_factor_kgco2e_per_kwh"]),
            actual_source_value,
            rel_tol=0.0,
            abs_tol=1e-10,
        ):
            source_value_errors.append(
                f"{row['city']}:{row['date']}:{row['half_hour_slot']}"
            )
        intended_column = REVIEWED_CITY_MAPPING[row["city"]]["carbon_column"]
        intended_value = float(source[intended_column])
        if row["city"] == "chengdu":
            chengdu_differences.append(
                float(row["carbon_factor_kgco2e_per_kwh"]) - intended_value
            )

    add(
        checks,
        check_id="A3-07",
        lane="A3",
        severity="P0",
        status="PASS" if not arithmetic_errors else "FAIL",
        subject="public electricity total arithmetic and CNY/kWh units",
        observed=f"errors={len(arithmetic_errors)}",
        expected="energy + service fee = total for all 12096 rows",
        evidence=str(CALENDAR.relative_to(REPO)),
        impact=";".join(arithmetic_errors[:20]),
    )
    add(
        checks,
        check_id="A4-02",
        lane="A4",
        severity="P0",
        status="FAIL" if any(abs(value) > 1e-12 for value in chengdu_differences) else "PASS",
        subject="Chengdu Sichuan-vs-Chongqing carbon-column replay",
        observed={
            "rows": len(chengdu_differences),
            "nonzero_rows": sum(abs(value) > 1e-12 for value in chengdu_differences),
            "mean_wrong_minus_correct_kg_per_kwh": (
                sum(chengdu_differences) / len(chengdu_differences)
            ),
            "max_abs_difference_kg_per_kwh": max(
                abs(value) for value in chengdu_differences
            ),
            "current_rows_match_declared_source_column": not source_value_errors,
        },
        expected="Chengdu rows use TVCI Sichuan column",
        evidence=f"{BUILDER.relative_to(REPO)}; {TVCI.relative_to(REPO)}",
        impact="Every Chengdu charging action is settled with Chongqing carbon intensity.",
        repair_authority="Create corrected immutable input version; do not overwrite E2 evidence.",
    )

    shenzhen_rows = [
        row
        for row in calendar
        if row["city"] == "shenzhen"
    ]
    v3_prices = tariff_v3["shenzhen"]["selected_scenario_row"][
        "energy_price_cny_per_kwh"
    ]
    shenzhen_numeric_mismatches = [
        row
        for row in shenzhen_rows
        if not math.isclose(
            float(row["depot_energy_cny_per_kwh"]),
            float(v3_prices[row["tariff_period"]]),
            rel_tol=0.0,
            abs_tol=1e-10,
        )
    ]
    semantic_stale = any(
        row["tariff_row_class"]
        != tariff_v3["shenzhen"]["selected_scenario_row"]["row_class"]
        for row in shenzhen_rows
    )
    add(
        checks,
        check_id="A3-02",
        lane="A3",
        severity="P1",
        status="FAIL" if shenzhen_numeric_mismatches or semantic_stale else "PASS",
        subject="Shenzhen v3 overlay runtime consumption",
        observed={
            "numeric_mismatches": len(shenzhen_numeric_mismatches),
            "calendar_class": sorted({row["tariff_row_class"] for row in shenzhen_rows}),
            "v3_class": tariff_v3["shenzhen"]["selected_scenario_row"]["row_class"],
        },
        expected="v3 numeric row and semantic class consumed by runtime authority chain",
        evidence=f"{TARIFF_V3.relative_to(REPO)}; {CALENDAR.relative_to(REPO)}",
        impact="Numbers match, but evidence semantics and authority lineage are stale.",
        repair_authority="Direct semantic wiring is allowed because numeric values do not change.",
    )

    affected_instances = sorted(
        instance_id
        for instance_id, cities in instance_city_sets.items()
        if "chengdu" in cities
    )
    return {
        "calendar": calendar,
        "affected_instances": affected_instances,
        "carbon_mapping_errors": carbon_mapping_errors,
        "price_mapping_errors": price_mapping_errors,
        "chengdu_differences": chengdu_differences,
        "shenzhen_numeric_mismatches": len(shenzhen_numeric_mismatches),
        "shenzhen_semantic_stale": semantic_stale,
    }


def audit_runtime_boundary_results(checks: list[Check]) -> dict[str, Any]:
    if not RUNTIME_BOUNDARY_CHECKS.is_file():
        add(
            checks,
            check_id="A4R-MISSING",
            lane="A4",
            severity="P0",
            status="PENDING",
            subject="runtime price/carbon boundary and fault-injection gate",
            observed="runtime_boundary_checks.csv missing",
            expected="standalone zero-search runtime audit executed",
            evidence=(
                "baselines/china_e3_e7/pre_e3_full_chain_audit_20260723/"
                "run_runtime_price_carbon_boundary_audit.py"
            ),
            impact="Runtime slot and fail-closed behavior is not evidenced.",
        )
        return {"checks": 0, "open_p0_p1": 1}

    rows = read_csv(RUNTIME_BOUNDARY_CHECKS)
    for row in rows:
        add(
            checks,
            check_id=row["check_id"],
            lane="A4",
            severity=row["severity"],
            status=row["status"],
            subject=row["subject"],
            observed=row["observed"],
            expected=row["expected"],
            evidence=(
                f"{RUNTIME_BOUNDARY_CHECKS.relative_to(REPO)}; "
                f"{row['evidence']}"
            ),
            impact=(
                "Malformed formal calendar can silently shift settlement."
                if row["check_id"] == "A4R-FI-03"
                else (
                    "Historical compatibility fallback should not be reachable "
                    "from a formal China81 bundle."
                    if row["check_id"] == "A4R-HARD-01"
                    else ""
                )
            ),
            repair_authority=(
                "Add deterministic canonical-grid validation to the China81 "
                "loader; no model or numeric parameter changes."
                if row["check_id"] == "A4R-FI-03"
                else ""
            ),
        )
    return {
        "checks": len(rows),
        "open_p0_p1": sum(
            row["status"] != "PASS"
            and row["severity"] in {"P0", "P1"}
            for row in rows
        ),
    }


def audit_objective_checker_results(
    checks: list[Check],
) -> dict[str, Any]:
    if not OBJECTIVE_CHECKER_CHECKS.is_file():
        add(
            checks,
            check_id="A5A6-MISSING",
            lane="A5-A6",
            severity="P0",
            status="PENDING",
            subject="independent objective and checker fault-injection gate",
            observed="objective_checker_audit.csv missing",
            expected="standalone zero-search objective/checker audit executed",
            evidence=(
                "baselines/china_e3_e7/pre_e3_full_chain_audit_20260723/"
                "run_objective_checker_audit.py"
            ),
            impact=(
                "The common exact objective and hard-constraint rejection "
                "boundary are not independently evidenced."
            ),
        )
        return {"checks": 0, "open_p0_p1": 1}

    rows = read_csv(OBJECTIVE_CHECKER_CHECKS)
    deterministic_repairs = {
        "A6-F09": (
            "Reject every charging action not bound to exactly one route id."
        ),
        "A6-F10": "Reject charging actions owned by CV routes.",
        "A6-F11": (
            "Reject charging actions at customer or unknown nodes."
        ),
        "A6-F12": (
            "Reject charging actions whose station is absent from the route."
        ),
        "A6-F13": (
            "Bind nonlinear action start/end energy to the actual route "
            "battery state at that visit."
        ),
        "A6-F14": (
            "Reject overlapping charging sessions for one physical vehicle; "
            "do not deduplicate them in capacity accounting."
        ),
        "A6-F15": (
            "Normalize China81 first-trip charging to the explicit day -1 "
            "pre-horizon certificate; preserve the old E2 witness as evidence."
        ),
        "A6-F16": (
            "Reject intermediate depots inside a static trip unless a later "
            "approved model extension explicitly allows them."
        ),
        "A6-F17": (
            "Make the strict multitrip execution certificate mandatory for "
            "every E3-E7 formal path; the generic checker alone lacks "
            "certified departure clocks."
        ),
    }
    for row in rows:
        add(
            checks,
            check_id=row["check_id"],
            lane=row["lane"],
            severity=row["severity"],
            status=row["status"],
            subject=row["subject"],
            observed=row["observed"],
            expected=row["expected"],
            evidence=(
                f"{OBJECTIVE_CHECKER_CHECKS.relative_to(REPO)}; "
                f"{row['evidence']}"
            ),
            impact=row["impact"],
            repair_authority=deterministic_repairs.get(
                row["check_id"],
                "",
            ),
        )
    return {
        "checks": len(rows),
        "open_p0_p1": sum(
            row["status"] != "PASS"
            and row["severity"] in {"P0", "P1"}
            for row in rows
        ),
    }


def audit_interface_reproducibility_results(
    checks: list[Check],
) -> dict[str, Any]:
    if not INTERFACE_REPRODUCIBILITY_CHECKS.is_file():
        add(
            checks,
            check_id="A7A10-MISSING",
            lane="A7-A10",
            severity="P0",
            status="PENDING",
            subject=(
                "formal interface, pairing and reproducibility "
                "fault-injection gate"
            ),
            observed="interface_reproducibility_audit.csv missing",
            expected="standalone zero-search interface audit executed",
            evidence=(
                "baselines/china_e3_e7/"
                "pre_e3_full_chain_audit_20260723/"
                "run_interface_reproducibility_audit.py"
            ),
            impact=(
                "Planning tasks cannot be treated as executable or paired "
                "without immutable witness and runtime bindings."
            ),
        )
        return {"checks": 0, "open_p0_p1": 1}

    rows = read_csv(INTERFACE_REPRODUCIBILITY_CHECKS)
    direct_repairs = {
        "A8-02-HASH-BINDING": (
            "Materialize per-pair immutable input identities before release."
        ),
        "A8-03-RAW-SCHEMA": (
            "Use one customer-size field vocabulary from RAW_FIELDS through "
            "primary-cell construction."
        ),
        "A8-02-PAIR-FAULT": (
            "Validate pair_id, instance and seed equality across arms before "
            "any aggregation."
        ),
        "A9-05-STRICT-CERT": (
            "Make strict certificate mode a runner invariant, not an ambient "
            "optional environment flag."
        ),
        "A10-03-FORMAL-RUNNER": (
            "Implement a versioned China runner with atomic per-task witness "
            "publication and a hash-bound resume ledger."
        ),
        "A10-02-CERTIFICATE": (
            "Require per-run solution, strict certificate and independent "
            "recalculation hashes."
        ),
        "A10-05-ENVIRONMENT": (
            "Bind interpreter, PyVRP, SciPy/HiGHS, NumPy and thread controls "
            "in batch metadata."
        ),
    }
    for row in rows:
        add(
            checks,
            check_id=row["check_id"],
            lane=row["lane"],
            severity=row["severity"],
            status=row["status"],
            subject=row["subject"],
            observed=row["observed"],
            expected=row["expected"],
            evidence=(
                f"{INTERFACE_REPRODUCIBILITY_CHECKS.relative_to(REPO)}; "
                f"{row['evidence']}"
            ),
            impact=row["impact"],
            repair_authority=direct_repairs.get(row["check_id"], ""),
        )
    return {
        "checks": len(rows),
        "open_p0_p1": sum(
            row["status"] != "PASS"
            and row["severity"] in {"P0", "P1"}
            for row in rows
        ),
    }


def audit_prices_and_periods(
    checks: list[Check],
    catalog: list[dict[str, str]],
    instance_city_sets: dict[str, set[str]],
    calendar: list[dict[str, str]],
) -> dict[str, Any]:
    tariff_v2 = read_json(TARIFF_V2)
    tariff_v3 = read_json(TARIFF_V3)
    builder_periods = literal_assignment(BUILDER, "PERIODS")

    source_hash_errors: list[str] = []
    source_hash_rows: list[dict[str, Any]] = []
    for area, source in tariff_v2["sources"].items():
        for source_kind in ("api", "scan"):
            relative = source[f"{source_kind}_file"]
            path = REPO / relative
            expected_hash = source[f"{source_kind}_sha256"]
            actual_hash = sha256(path) if path.is_file() else ""
            source_hash_rows.append(
                {
                    "authority": "tariff_v2",
                    "price_area": area,
                    "source_kind": source_kind,
                    "path": relative,
                    "expected_sha256": expected_hash,
                    "actual_sha256": actual_hash,
                    "status": (
                        "PASS" if actual_hash == expected_hash else "FAIL"
                    ),
                }
            )
            if actual_hash != expected_hash:
                source_hash_errors.append(f"{area}:{source_kind}")
    v3_parent_actual = sha256(TARIFF_V2)
    if v3_parent_actual != tariff_v3["parent_register_sha256"]:
        source_hash_errors.append("tariff_v3:parent_register")
    for source_kind in ("api", "scan"):
        source = tariff_v3["shenzhen"]["numeric_source"]
        relative = source[f"{source_kind}_file"]
        path = REPO / relative
        expected_hash = source[f"{source_kind}_sha256"]
        actual_hash = sha256(path) if path.is_file() else ""
        source_hash_rows.append(
            {
                "authority": "tariff_v3_shenzhen_overlay",
                "price_area": "shenzhen",
                "source_kind": source_kind,
                "path": relative,
                "expected_sha256": expected_hash,
                "actual_sha256": actual_hash,
                "status": "PASS" if actual_hash == expected_hash else "FAIL",
            }
        )
        if actual_hash != expected_hash:
            source_hash_errors.append(f"tariff_v3:shenzhen:{source_kind}")
    write_csv(
        OUT / "tariff_source_hash_register.csv",
        source_hash_rows,
        list(source_hash_rows[0]),
    )
    add(
        checks,
        check_id="A3-01",
        lane="A3",
        severity="P0",
        status="PASS" if not source_hash_errors else "FAIL",
        subject="2025-02 tariff-register source bytes and overlay parent",
        observed=(
            f"{len(source_hash_rows) - len(source_hash_errors)}/"
            f"{len(source_hash_rows)} source rows match; "
            f"parent_match={v3_parent_actual == tariff_v3['parent_register_sha256']}"
        ),
        expected="all archived source hashes and v3 parent hash match",
        evidence="tariff_source_hash_register.csv",
        impact=";".join(source_hash_errors),
    )

    period_definition_errors = [
        city
        for city in REVIEWED_FEBRUARY_PERIODS
        if builder_periods.get(city) != REVIEWED_FEBRUARY_PERIODS[city]
    ]
    period_row_errors: list[str] = []
    price_row_errors: list[str] = []
    for row in calendar:
        city = row["city"]
        minute = int(row["minute_of_day"])
        expected_period = reviewed_period_for(city, minute)
        if row["tariff_period"] != expected_period:
            period_row_errors.append(
                f"{city}:{row['date']}:{row['half_hour_slot']}:"
                f"{row['tariff_period']}!={expected_period}"
            )

        price_area = REVIEWED_CITY_MAPPING[city]["price_area_id"]
        if city == "shenzhen":
            prices = tariff_v3["shenzhen"]["selected_scenario_row"][
                "energy_price_cny_per_kwh"
            ]
        else:
            prices = tariff_v2["one_to_ten_kv_candidate_rows"][price_area][
                "single_part"
            ]
        expected_price = prices[expected_period]
        if expected_price is None:
            price_row_errors.append(
                f"{city}:{row['date']}:{row['half_hour_slot']}:"
                f"missing_{expected_period}_price"
            )
            continue
        for field in (
            "depot_energy_cny_per_kwh",
            "public_energy_cny_per_kwh",
        ):
            if not math.isclose(
                float(row[field]),
                float(expected_price),
                rel_tol=0.0,
                abs_tol=1e-10,
            ):
                price_row_errors.append(
                    f"{city}:{row['date']}:{row['half_hour_slot']}:"
                    f"{field}={row[field]}!=expected={expected_price}"
                )
    add(
        checks,
        check_id="A3-03",
        lane="A3",
        severity="P0",
        status=(
            "PASS"
            if not period_definition_errors and not period_row_errors
            else "FAIL"
        ),
        subject="independent February local-time TOU-period replay",
        observed={
            "builder_definition_errors": period_definition_errors,
            "calendar_row_errors": len(period_row_errors),
        },
        expected="all 12096 rows map to the independently reviewed local period",
        evidence="; ".join(sorted(set(PERIOD_EVIDENCE.values()))),
        impact=";".join(period_row_errors[:20]),
    )
    add(
        checks,
        check_id="A3-04",
        lane="A3",
        severity="P0",
        status="PASS" if not price_row_errors else "FAIL",
        subject="selected 1-10 kV scenario-row price replay",
        observed=f"errors={len(price_row_errors)}",
        expected=(
            "depot and public energy components match the selected city/area/"
            "period row for every calendar record"
        ),
        evidence=(
            f"{TARIFF_V2.relative_to(REPO)}; "
            f"{TARIFF_V3.relative_to(REPO)}; "
            f"{CALENDAR.relative_to(REPO)}"
        ),
        impact=";".join(price_row_errors[:20]),
    )

    service_values = sorted(
        {float(row["public_service_fee_cny_per_kwh"]) for row in calendar}
    )
    service_classes = sorted({row["service_fee_class"] for row in calendar})
    service_explicit = (
        service_values == [0.4]
        and service_classes
        == ["UNIFORM_SCENARIO_PROXY_NOT_MARKET_OBSERVATION"]
    )
    add(
        checks,
        check_id="A3-05",
        lane="A3",
        severity="P1",
        status="PASS" if service_explicit else "FAIL",
        subject="public charging service-fee proxy disclosure",
        observed={
            "values_cny_per_kwh": service_values,
            "classes": service_classes,
        },
        expected=(
            "uniform 0.4 CNY/kWh is explicitly labelled a constructed-scenario "
            "proxy, never a city tariff or observed station quotation"
        ),
        evidence=(
            f"{CALENDAR.relative_to(REPO)}; "
            f"{PARAMETER_LOCK.relative_to(REPO)}"
        ),
        impact=(
            "The proxy is transparent, but it still requires a preregistered "
            "sensitivity before any robustness claim."
        ),
    )

    default_date = literal_assignment(CHINA81_LOADER, "DEFAULT_CHINA81_DATE")
    current_diesel = literal_assignment(
        CHINA81_LOADER, "_DIESEL_PRICE_CNY_PER_L"
    )
    current_sources = literal_assignment(
        CHINA81_LOADER, "_DIESEL_PRICE_SOURCE"
    )
    diesel_rows: list[dict[str, Any]] = []
    diesel_evidence_errors: list[str] = []
    city_price_mismatches: list[str] = []
    for city, mapping in REVIEWED_CITY_MAPPING.items():
        zone = mapping["diesel_zone"]
        reviewed = REVIEWED_DIESEL_BY_ZONE[zone]
        region = mapping["region"]
        source_path = DIESEL_EVIDENCE_ROOT / reviewed["source_file"]
        supporting_name = reviewed.get("supporting_source_file", "")
        supporting_path = (
            DIESEL_EVIDENCE_ROOT / supporting_name
            if supporting_name
            else None
        )
        if not source_path.is_file():
            diesel_evidence_errors.append(f"{zone}:missing:{source_path.name}")
        if supporting_path is not None and not supporting_path.is_file():
            diesel_evidence_errors.append(
                f"{zone}:missing:{supporting_path.name}"
            )
        current_price = float(current_diesel[region])
        reviewed_price = float(reviewed["price_cny_per_l"])
        mismatch = not math.isclose(
            current_price,
            reviewed_price,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        if mismatch:
            city_price_mismatches.append(city)
        diesel_rows.append(
            {
                "city": city,
                "region": region,
                "diesel_zone": zone,
                "default_date": default_date,
                "runtime_price_cny_per_l": current_price,
                "reviewed_price_cny_per_l": reviewed_price,
                "runtime_minus_reviewed_cny_per_l": (
                    current_price - reviewed_price
                ),
                "runtime_source_id": current_sources[region],
                "reviewed_source_strength": reviewed["source_strength"],
                "reviewed_source_url": reviewed["source_url"],
                "source_file": str(source_path.relative_to(REPO)),
                "source_sha256": (
                    sha256(source_path) if source_path.is_file() else ""
                ),
                "supporting_source_file": (
                    str(supporting_path.relative_to(REPO))
                    if supporting_path is not None
                    else ""
                ),
                "supporting_source_sha256": (
                    sha256(supporting_path)
                    if supporting_path is not None
                    and supporting_path.is_file()
                    else ""
                ),
                "status": "FAIL" if mismatch else "PASS",
            }
        )
    write_csv(
        OUT / "diesel_price_2025_02_12_source_register.csv",
        diesel_rows,
        list(diesel_rows[0]),
    )
    add(
        checks,
        check_id="A3-10",
        lane="A3",
        severity="P0",
        status="FAIL" if city_price_mismatches else "PASS",
        subject="default-date 0# diesel price",
        observed={
            "default_date": default_date,
            "mismatching_cities": city_price_mismatches,
            "runtime_prices_by_region": current_diesel,
        },
        expected=(
            "2025-02-12 local maximum-retail scenario values: Beijing 7.48, "
            "Tianjin/Hebei 7.43, Guangdong 7.44, Sichuan 7.48, "
            "Chongqing 7.50 CNY/L"
        ),
        evidence="diesel_price_2025_02_12_source_register.csv",
        impact=(
            "The runtime imports July 2026 values into a February 2025 "
            "electricity/carbon scenario and underprices diesel in all nine cities."
        ),
        repair_authority=(
            "Create a new city/zone-keyed immutable input register; preserve "
            "the old E2 evidence and rerun exposed China81 cells."
        ),
    )

    expected_prices_by_region: dict[str, set[float]] = defaultdict(set)
    for row in diesel_rows:
        expected_prices_by_region[row["region"]].add(
            float(row["reviewed_price_cny_per_l"])
        )
    collapsed_regions = {
        region: sorted(values)
        for region, values in expected_prices_by_region.items()
        if len(values) > 1
    }
    add(
        checks,
        check_id="A3-11",
        lane="A3",
        severity="P0",
        status="FAIL" if collapsed_regions else "PASS",
        subject="diesel geographic selector granularity",
        observed={
            "runtime_selector": "region only",
            "regions_with_multiple_required_prices": collapsed_regions,
        },
        expected="explicit city/diesel_zone selector where local prices differ",
        evidence=(
            "solver/src/setp_solver/china81.py::_DIESEL_PRICE_CNY_PER_L; "
            "diesel_price_2025_02_12_source_register.csv"
        ),
        impact=(
            "JJJ and Chengdu-Chongqing cannot be represented correctly by one "
            "price per model region."
        ),
        repair_authority=(
            "Deterministic selector repair is allowed; numeric scenario values "
            "remain approval-governed."
        ),
    )
    add(
        checks,
        check_id="A3-12",
        lane="A3",
        severity="P1",
        status="PASS" if not diesel_evidence_errors else "FAIL",
        subject="diesel evidence-byte availability and provenance strength",
        observed={
            "files_present": not diesel_evidence_errors,
            "errors": diesel_evidence_errors,
            "chongqing_boundary": (
                REVIEWED_DIESEL_BY_ZONE["chongqing"]["source_strength"]
            ),
        },
        expected=(
            "all cited official evidence bytes retained; derived values are "
            "explicitly distinguished from directly observed local rows"
        ),
        evidence="diesel_price_2025_02_12_source_register.csv",
        impact=";".join(diesel_evidence_errors),
    )

    diesel_affected_instances = sorted(
        instance_id
        for instance_id, cities in instance_city_sets.items()
        if any(city in city_price_mismatches for city in cities)
    )
    return {
        "period_definition_errors": period_definition_errors,
        "period_row_errors": period_row_errors,
        "price_row_errors": price_row_errors,
        "service_explicit": service_explicit,
        "diesel_city_price_mismatches": city_price_mismatches,
        "diesel_affected_instances": diesel_affected_instances,
        "diesel_evidence_errors": diesel_evidence_errors,
    }


def audit_e2_scope(
    checks: list[Check],
    chengdu_affected_instances: list[str],
    geography_affected_instances: list[str],
    physical_duplicate_instances: list[str],
    geography_resampled_instances: list[str],
    diesel_affected_instances: list[str],
) -> dict[str, Any]:
    p3 = read_csv(P3_RAW)
    s2 = read_csv(S2_RAW)
    s3 = read_csv(S3_RAW)
    s3_traj = read_csv(S3_TRAJ_RAW)
    defects_by_instance: dict[str, set[str]] = defaultdict(set)
    for instance_id in chengdu_affected_instances:
        defects_by_instance[instance_id].add("CHENGDU_WRONG_CARBON_COLUMN")
    for instance_id in geography_affected_instances:
        defects_by_instance[instance_id].add(
            "OUTSIDE_DECLARED_CITY_CUSTOMER"
        )
    for instance_id in physical_duplicate_instances:
        defects_by_instance[instance_id].add(
            "WITHIN_CELL_PHYSICAL_LOCATION_REUSE"
        )
    for instance_id in geography_resampled_instances:
        defects_by_instance[instance_id].add(
            "GEOGRAPHY_CORRECTION_DETERMINISTIC_RESAMPLING"
        )
    for instance_id in diesel_affected_instances:
        defects_by_instance[instance_id].add(
            "DIESEL_WRONG_DATE_AND_REGION_GRANULARITY"
        )

    affected_instances = sorted(defects_by_instance)
    affected = set(affected_instances)
    p3_rows = [row for row in p3 if row["instance_id"] in affected]
    s2_rows = [row for row in s2 if row["instance_id"] in affected]
    s3_rows = [row for row in s3 if row["instance_id"] in affected]
    s3_traj_rows = [
        row for row in s3_traj if row["instance_id"] in affected
    ]
    impact_rows: list[dict[str, Any]] = []
    p3_by_instance = Counter(row["instance_id"] for row in p3_rows)
    s2_by_instance_arm = Counter(
        (row["instance_id"], row["route_proxy_mode"])
        for row in s2_rows
    )
    s3_by_instance = Counter(row["instance_id"] for row in s3_rows)
    s3_traj_by_instance = Counter(
        row["instance_id"] for row in s3_traj_rows
    )
    for instance_id in affected_instances:
        is_representative = instance_id == REPRESENTATIVE_INSTANCE_ID
        impact_rows.append(
            {
                "instance_id": instance_id,
                "defect_ids": "|".join(sorted(defects_by_instance[instance_id])),
                "contains_chengdu": (
                    "CHENGDU_WRONG_CARBON_COLUMN"
                    in defects_by_instance[instance_id]
                ),
                "outside_declared_city_customer": (
                    "OUTSIDE_DECLARED_CITY_CUSTOMER"
                    in defects_by_instance[instance_id]
                ),
                "within_cell_physical_location_reuse": (
                    "WITHIN_CELL_PHYSICAL_LOCATION_REUSE"
                    in defects_by_instance[instance_id]
                ),
                "geography_correction_resampled_instance": (
                    "GEOGRAPHY_CORRECTION_DETERMINISTIC_RESAMPLING"
                    in defects_by_instance[instance_id]
                ),
                "diesel_wrong_date_or_granularity": (
                    "DIESEL_WRONG_DATE_AND_REGION_GRANULARITY"
                    in defects_by_instance[instance_id]
                ),
                "is_registered_representative": is_representative,
                "p3_mother_full_rows": p3_by_instance[instance_id],
                "p3_algorithm_result_cells": (
                    2 * p3_by_instance[instance_id]
                ),
                "s2_cv_only_rows": s2_by_instance_arm[(instance_id, "cv_only")],
                "s2_naive_ev_rows": s2_by_instance_arm[(instance_id, "naive_ev")],
                "s3_four_arm_rows": s3_by_instance[instance_id],
                "s3_trajectory_observation_rows": s3_traj_by_instance[
                    instance_id
                ],
                "s4_best_witness_and_route_table": (
                    is_representative
                    and (S4_ROOT / "best_solution_witness_v2.json").is_file()
                ),
                "full_replay_witness_available_for_p3_s2": False,
                "impact_status": (
                    "REPRESENTATIVE_AND_FULL_TABLES_EXPOSED"
                    if is_representative
                    else "CHINA81_FULL_TABLES_EXPOSED"
                ),
                "required_action": (
                    "After all P0/P1 input fixes are frozen, rerun only affected "
                    "E2 cells under the corrected immutable authority; regenerate "
                    "all dependent statistics, tables, figures and prose."
                ),
            }
        )
    write_csv(
        OUT / "e2_impact_matrix.csv",
        impact_rows,
        list(impact_rows[0]) if impact_rows else [
            "instance_id",
            "defect_ids",
            "contains_chengdu",
            "outside_declared_city_customer",
            "within_cell_physical_location_reuse",
            "geography_correction_resampled_instance",
            "diesel_wrong_date_or_granularity",
            "is_registered_representative",
            "p3_mother_full_rows",
            "p3_algorithm_result_cells",
            "s2_cv_only_rows",
            "s2_naive_ev_rows",
            "s3_four_arm_rows",
            "s3_trajectory_observation_rows",
            "s4_best_witness_and_route_table",
            "full_replay_witness_available_for_p3_s2",
            "impact_status",
            "required_action",
        ],
    )
    p3_result_cells = 2 * len(p3_rows)
    s2_result_cells = len(s2_rows)
    exposed_result_cells = p3_result_cells + s2_result_cells
    add(
        checks,
        check_id="A12-06",
        lane="A12",
        severity="P0",
        status="FAIL" if affected_instances else "PASS",
        subject="E2 China81 exposure to identified P0 input defects",
        observed={
            "affected_instances": len(affected_instances),
            "chengdu_carbon_instances": len(chengdu_affected_instances),
            "outside_city_instances": len(geography_affected_instances),
            "physical_duplicate_instances": len(
                physical_duplicate_instances
            ),
            "geography_resampled_instances": len(
                geography_resampled_instances
            ),
            "diesel_price_instances": len(diesel_affected_instances),
            "p3_raw_rows": len(p3_rows),
            "p3_algorithm_result_cells": p3_result_cells,
            "s2_raw_rows_and_result_cells": len(s2_rows),
            "p3_s2_result_cells_without_full_witness": exposed_result_cells,
            "s3_four_arm_rows": len(s3_rows),
            "s3_trajectory_observation_rows": len(s3_traj_rows),
        },
        expected="0 E2 rows exposed to a P0 input mapping defect",
        evidence="e2_impact_matrix.csv",
        impact=(
            "The public benchmark lane is not implicated, but the China81 private "
            "results cannot remain unconditional. P3/S2 raw costs cannot be "
            "honestly re-scored because full per-run witnesses were not retained."
        ),
        repair_authority="Preserve old evidence; rerun affected cells only after final input freeze.",
    )
    representative_affected = REPRESENTATIVE_INSTANCE_ID in affected
    add(
        checks,
        check_id="A12-06-REP",
        lane="A12",
        severity="P0",
        status="FAIL" if representative_affected else "PASS",
        subject="registered E2 simulation-instance exposure",
        observed={
            "instance_id": REPRESENTATIVE_INSTANCE_ID,
            "affected": representative_affected,
            "defects": sorted(
                defects_by_instance.get(REPRESENTATIVE_INSTANCE_ID, set())
            ),
            "sealed_S3_rows": len(s3_rows),
            "trajectory_observation_rows": len(s3_traj_rows),
            "S4_witness": (
                S4_ROOT / "best_solution_witness_v2.json"
            ).is_file(),
        },
        expected="registered simulation instance has no P0 input defect",
        evidence=(
            "customer_geography_exceptions.csv; e2_impact_matrix.csv; "
            "baselines/e2_final_campaign_20260720/p2p3_threeview/"
            "representative_gate"
        ),
        impact=(
            "Table 4 route details, the ten-seed four-arm comparison, Figure 4 "
            "and their manuscript claims depend on this contaminated instance."
        ),
        repair_authority=(
            "Keep the preregistered selection rule, rebuild corrected inputs, "
            "then rerun the same registered instance identity under the new version."
        ),
    )
    return {
        "affected_instances": affected_instances,
        "p3_rows": len(p3_rows),
        "s2_rows": len(s2_rows),
        "p3_result_cells": p3_result_cells,
        "s2_result_cells": s2_result_cells,
        "s3_rows": len(s3_rows),
        "s3_traj_rows": len(s3_traj_rows),
        "representative_affected": representative_affected,
    }


def corrected_assignment_impact() -> dict[str, Any]:
    """Measure the deterministic GIS rebuild against the sealed E2 authority."""

    if not CORRECTED_ASSIGNMENTS.is_file():
        return {
            "changed_rows": 0,
            "changed_instances": [],
            "changed_instance_count_by_region": {},
            "changed_row_count_by_region": {},
            "status": "MISSING_CORRECTED_ASSIGNMENTS",
        }
    original = {
        (
            row["instance_id"],
            row["city"],
            row["city_selection_rank"],
        ): row
        for row in read_csv(ASSIGNMENTS)
    }
    corrected = {
        (
            row["instance_id"],
            row["city"],
            row["city_selection_rank"],
        ): row
        for row in read_csv(CORRECTED_ASSIGNMENTS)
    }
    if set(original) != set(corrected):
        raise ValueError(
            "original and corrected assignment identities disagree"
        )
    changed = [
        key
        for key in original
        if tuple(
            original[key][field]
            for field in (
                "osm_type",
                "osm_id",
                "latitude",
                "longitude",
            )
        )
        != tuple(
            corrected[key][field]
            for field in (
                "osm_type",
                "osm_id",
                "latitude",
                "longitude",
            )
        )
    ]
    changed_instances = sorted({key[0] for key in changed})
    return {
        "changed_rows": len(changed),
        "changed_instances": changed_instances,
        "changed_instance_count_by_region": dict(
            Counter(instance_id.split("-")[1] for instance_id in changed_instances)
        ),
        "changed_row_count_by_region": dict(
            Counter(key[0].split("-")[1] for key in changed)
        ),
        "status": "PASS_MEASURED",
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    checks: list[Check] = []

    authority = audit_authority_and_hashes(checks)
    joins = audit_instance_joins(checks, authority["catalog"])
    gis = audit_gis(checks, joins["coordinate_rows"])
    mapping = audit_mapping_and_calendar(checks, joins["instance_city_sets"])
    prices = audit_prices_and_periods(
        checks,
        authority["catalog"],
        joins["instance_city_sets"],
        mapping["calendar"],
    )
    runtime_boundary = audit_runtime_boundary_results(checks)
    objective_checker = audit_objective_checker_results(checks)
    interface_reproducibility = (
        audit_interface_reproducibility_results(checks)
    )
    assignment_impact = corrected_assignment_impact()
    e2_scope = audit_e2_scope(
        checks,
        mapping["affected_instances"],
        gis.get("affected_customer_instances", []),
        joins["physical_duplicate_instances"],
        assignment_impact["changed_instances"],
        prices["diesel_affected_instances"],
    )

    add(
        checks,
        check_id="A1-03",
        lane="A1",
        severity="P1",
        status="FAIL",
        subject="old frozen calendar versus newer semantic overlays",
        observed=(
            "Runtime loader consumes static-input v1 calendar; Shenzhen v3 overlay "
            "and reviewed Chengdu mapping are not in the authority chain."
        ),
        expected="one explicit, current, immutable runtime input authority",
        evidence=(
            "solver/src/setp_solver/china81.py; "
            "data/ChinaPrices/china_2025_02_tariff_register_v3.json"
        ),
        impact="Stale semantic source and wrong Chengdu numeric carbon source.",
        repair_authority="Create a new versioned input authority after all mapping fixes.",
    )

    statuses = Counter(check.status for check in checks)
    open_high = [
        check
        for check in checks
        if check.status in {"FAIL", "PENDING"}
        and check.severity in {"P0", "P1"}
    ]
    metadata = {
        "schema": "resetp.pre-e3-full-chain-audit.interim.v1",
        "audit_contract": "PRE-E3-FULL-CHAIN-REVIEWER-AUDIT-001",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script": str(SCRIPT.relative_to(REPO)),
        "script_sha256": sha256(SCRIPT),
        "git_head": git("rev-parse", "HEAD"),
        "git_branch": git("branch", "--show-current"),
        "python": sys.version,
        "platform": platform.platform(),
        "search_evaluations": 0,
        "formal_search_allowed": False,
        "scope_completed": [
            "A1",
            "A2",
            "A3-input-and-authority",
            "A4-runtime-boundary",
            "A5-objective-recomputation",
            "A6-generic-and-certificate-red-team",
            "A7-algorithm-reproducibility",
            "A8-task-statistics-interface",
            "A9-mechanism-execution-bindings",
            "A10-execution-evidence-interface",
            "A10-regression-environment-security",
            "A12-E2-scope",
        ],
        "scope_pending": [
            "A11",
            "A12-final-red-team",
        ],
        "counts": {
            "checks": len(checks),
            "statuses": dict(statuses),
            "open_p0_p1": len(open_high),
            "orders": len(joins["orders"]),
            "instances": len(authority["catalog"]),
            "chengdu_affected_instances": len(mapping["affected_instances"]),
            "outside_city_affected_instances": len(
                gis.get("affected_customer_instances", [])
            ),
            "physical_duplicate_affected_instances": len(
                joins["physical_duplicate_instances"]
            ),
            "geography_resampled_instances": len(
                assignment_impact["changed_instances"]
            ),
            "geography_resampled_rows": assignment_impact["changed_rows"],
            "diesel_price_affected_instances": len(
                prices["diesel_affected_instances"]
            ),
            "runtime_boundary_checks": runtime_boundary["checks"],
            "runtime_boundary_open_p0_p1": runtime_boundary["open_p0_p1"],
            "objective_checker_checks": objective_checker["checks"],
            "objective_checker_open_p0_p1": objective_checker[
                "open_p0_p1"
            ],
            "interface_reproducibility_checks": (
                interface_reproducibility["checks"]
            ),
            "interface_reproducibility_open_p0_p1": (
                interface_reproducibility["open_p0_p1"]
            ),
            "e2_p3_exposed_rows": e2_scope["p3_rows"],
            "e2_p3_exposed_result_cells": e2_scope["p3_result_cells"],
            "e2_s2_exposed_rows": e2_scope["s2_rows"],
            "e2_s3_exposed_rows": e2_scope["s3_rows"],
            "e2_s3_trajectory_exposed_rows": e2_scope["s3_traj_rows"],
            "e2_representative_affected": e2_scope[
                "representative_affected"
            ],
            "gis_status": gis["status"],
            "gis_unique_by_type": gis.get("unique_by_type", {}),
        },
        "interim_verdict": "HOLD_E3_AUDIT_FINDINGS_OPEN",
    }

    write_csv(
        OUT / "machine_checks.csv",
        (asdict(check) for check in checks),
        list(asdict(checks[0])),
    )
    write_json(OUT / "metadata_interim.json", metadata)
    write_json(
        OUT / "findings_interim.json",
        {
            "verdict": metadata["interim_verdict"],
            "open_p0_p1": [asdict(check) for check in open_high],
            "all_checks": [asdict(check) for check in checks],
        },
    )

    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 2 if open_high else 0


if __name__ == "__main__":
    raise SystemExit(main())
