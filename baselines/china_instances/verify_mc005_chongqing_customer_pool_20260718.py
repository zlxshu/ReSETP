#!/usr/bin/env python3
"""Independent readback verifier for the MC-005 Chongqing pool evidence."""

from __future__ import annotations

import csv
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
OUTPUT = REPO / "data/ChinaInstances/china81_chongqing_mc005_pool_closure_20260718"
OLD_POOL = (
    REPO
    / "data/ChinaInstances/china81_customer_pool_replenishment_map_api_v2_20260718"
    / "pools/chongqing__named_poi.csv"
)
PPS_DECISION = REPO / "data/ChinaInstances/china_city_pps_calibration_v2_20260718/decision.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def identity(row: dict[str, str]) -> tuple[str, str]:
    return row["osm_type"], row["osm_id"]


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def clean_appledouble(root: Path) -> None:
    for path in sorted(root.rglob("._*")):
        if path.is_file():
            path.unlink()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def main() -> int:
    decision = json.loads((OUTPUT / "decision.json").read_text(encoding="utf-8"))
    metadata = json.loads((OUTPUT / "metadata.json").read_text(encoding="utf-8"))
    task_contract = json.loads((OUTPUT / "task_contract.json").read_text(encoding="utf-8"))
    runs = read_rows(OUTPUT / "raw_runs.csv")
    old_rows = read_rows(OLD_POOL)
    new_rows = read_rows(OUTPUT / "pools/chongqing__new_named_poi.csv")
    merged_rows = read_rows(OUTPUT / "pools/chongqing__merged_named_poi.csv")
    cells = read_rows(OUTPUT / "cell_sufficiency_candidate_a.csv")

    raw_identity_by_path: dict[str, set[tuple[str, str]]] = {}
    raw_hashes_match = True
    xml_well_formed = True
    for run in runs:
        raw_path = REPO / run["raw_path"]
        request_path = REPO / run["request_path"]
        raw_hashes_match &= (
            sha256(raw_path) == run["raw_sha256"]
            and sha256(request_path) == run["request_sha256"]
        )
        try:
            root = ET.fromstring(raw_path.read_bytes())
        except ET.ParseError:
            xml_well_formed = False
            continue
        raw_identity_by_path[run["raw_path"]] = {
            (element.tag, element.attrib["id"])
            for element in root
            if element.tag in {"node", "way"} and "id" in element.attrib
        }

    old_ids = {identity(row) for row in old_rows}
    new_ids = {identity(row) for row in new_rows}
    merged_ids = {identity(row) for row in merged_rows}
    new_rows_traceable = all(
        identity(row) in raw_identity_by_path.get(row["source_response_path"], set())
        and sha256(REPO / row["source_response_path"]) == row["source_response_sha256"]
        and bool(row["name"] or row["brand"])
        for row in new_rows
    )
    candidate_a = json.loads(PPS_DECISION.read_text(encoding="utf-8"))[
        "proposed_patch_not_applied"
    ]["proposed_city_quotas"]
    expected_cy200 = candidate_a["cy"]["200"]
    cy200 = next(
        row
        for row in cells
        if row["region"] == "cy" and row["customer_size"] == "200"
    )
    checks = {
        "decision_pass": decision["verdict"]
        == "PASS_MC005_CHONGQING_POOL_AND_27_CELL_GATE",
        "runner_hash_matches_metadata": metadata["runner_sha256"]
        == sha256(
            REPO
            / "baselines/china_instances/close_mc005_chongqing_customer_pool_20260718.py"
        ),
        "osm_odbl_license_recorded": metadata["source_license"]
        == "Open Data Commons Open Database License (ODbL) 1.0"
        and task_contract["source_license"]
        == "Open Data Commons Open Database License (ODbL) 1.0"
        and metadata["required_attribution"] == "OpenStreetMap and its contributors",
        "all_fixed_tiles_success": len(runs) == 20
        and all(row["status"] == "success" and row["http_status"] == "200" for row in runs),
        "raw_hashes_match": raw_hashes_match,
        "raw_xml_well_formed": xml_well_formed,
        "new_identity_rows_unique": len(new_rows) == len(new_ids) == 227,
        "new_identity_rows_exclude_prior_pool": not bool(new_ids & old_ids),
        "merged_identity_rows_unique": len(merged_rows) == len(merged_ids) == 532,
        "merged_pool_is_exact_union": merged_ids == old_ids | new_ids,
        "new_rows_traceable_to_raw_xml": new_rows_traceable,
        "candidate_a_cy200_quota_unchanged": expected_cy200
        == {"chongqing": 116, "chengdu": 84},
        "candidate_a_cy200_gate_uses_348_chongqing": {
            item.split(":")[0]: item.split(":")[1]
            for item in cy200["city_availability"].split(";")
        }.get("chongqing")
        == "532/348",
        "all_27_cells_pass": len(cells) == 27
        and all(row["pass"] == "True" for row in cells),
        "cross_city_identity_overlap_zero": decision[
            "cross_city_identity_overlaps"
        ]
        == {"cy": 0, "jjj": 0, "prd": 0},
        "no_search": decision["search_evaluations"] == 0,
        "formal_search_still_forbidden": decision["formal_search_allowed"] is False,
    }
    verdict = "PASS_INDEPENDENT_READBACK" if all(checks.values()) else "HALT_READBACK_FAILURE"
    verification = {
        "schema": "resetp.china81.mc005-chongqing-pool-independent-verification.v1",
        "verdict": verdict,
        "checks": checks,
        "raw_tiles_verified": len(runs),
        "new_unique_verified": len(new_ids),
        "merged_unique_verified": len(merged_ids),
        "candidate_a_cells_verified": len(cells),
        "search_evaluations": 0,
    }
    write_json(OUTPUT / "independent_verification.json", verification)

    clean_appledouble(OUTPUT)
    files = [
        path
        for path in sorted(OUTPUT.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    ]
    files.extend(
        [
            REPO / "baselines/china_instances/close_mc005_chongqing_customer_pool_20260718.py",
            Path(__file__).resolve(),
        ]
    )
    write_json(
        OUTPUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "files": {display_path(path): sha256(path) for path in files},
        },
    )
    clean_appledouble(OUTPUT)
    print(json.dumps(verification, ensure_ascii=False, sort_keys=True))
    return 0 if verdict == "PASS_INDEPENDENT_READBACK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
