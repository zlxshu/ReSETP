#!/usr/bin/env python3
"""Validate the non-algorithm phase-one handoff without running the solver."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CUSTOMER_CONTRACT = ROOT / "data/ChinaInstances/china_customer_location_contract_v2_20260718.json"
ASSIGNMENTS = ROOT / "data/ChinaInstances/china81_customer_location_assignments_mc005_final_v2_20260718"
FACILITIES = ROOT / "data/ChinaInstances/china_ordinary_commercial_depot_manifest_v2_20260718.json"
ROAD_ACCESS = ROOT / "data/ChinaInstances/phase1_nine_city_road_access_v1_20260718"
FUNCTIONAL = ROOT / "data/ChinaInstances/phase1_osrm_functional_gate_v3_20260718"
ROAD_CONTRACT = ROOT / "data/ChinaInstances/china_road_matrix_contract_v2_20260718.json"
MC002 = ROOT / "baselines/statistics/mc002_compute_power_20260718"
PARAMETER_LOCK = ROOT / "data/ChinaInstances/china_parameter_lock_v2_20260718.json"
APPROVAL_REGISTER = ROOT / "docs/handoff/model_change_approval_register_20260718.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_hash_package(package: Path) -> list[str]:
    manifest_path = package / "artifact_hashes.json"
    if not manifest_path.is_file():
        return [f"missing artifact hashes: {manifest_path}"]
    manifest = load(manifest_path)
    entries = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(entries, dict):
        entries = manifest
    errors: list[str] = []
    if not entries:
        return [f"empty artifact hash manifest: {manifest_path}"]
    for relative, expected in entries.items():
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"missing hashed file: {relative}")
        elif sha256(path) != expected:
            errors.append(f"hash mismatch: {relative}")
        if "/._" in relative or Path(relative).name.startswith("._"):
            errors.append(f"AppleDouble included in authority hash: {relative}")
    return errors


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def audit(output: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}

    for package in (ASSIGNMENTS, ROAD_ACCESS, FUNCTIONAL, MC002):
        package_errors = verify_hash_package(package)
        errors.extend(package_errors)
        checks[f"hashes:{package.name}"] = not package_errors

    customer = load(CUSTOMER_CONTRACT)
    assignment_decision = load(ASSIGNMENTS / "decision.json")
    assignment_metadata = load(ASSIGNMENTS / "metadata.json")
    assignment_rows = read_csv(ASSIGNMENTS / "assignments.csv")
    quotas = customer.get("city_quotas", {})
    quota_errors: list[str] = []
    overlap_errors: list[str] = []
    for region, size_table in quotas.items():
        for size_text, expected_counts in size_table.items():
            cell = [
                row
                for row in assignment_rows
                if row["region"] == region and row["customer_size"] == size_text
            ]
            identities = [(row["osm_type"], row["osm_id"]) for row in cell]
            if len(identities) != len(set(identities)):
                overlap_errors.append(f"{region}/{size_text}")
            for replicate in customer.get("replicate_labels", []):
                observed = Counter(
                    row["city"] for row in cell if row["replicate"] == replicate
                )
                if dict(observed) != expected_counts:
                    quota_errors.append(
                        f"{region}/{size_text}/{replicate}: {dict(observed)} != {expected_counts}"
                    )
    customer_ok = (
        customer.get("status")
        == "MC005_CANDIDATE_A_APPLIED_ASSIGNMENTS_PASS_FORMAL_SEARCH_STILL_BLOCKED"
        and customer.get("formal_search_allowed") is False
        and assignment_decision.get("verdict") == "PASS_81_DISJOINT_LOCATION_ASSIGNMENTS_BUILT"
        and assignment_decision.get("instances") == 81
        and assignment_decision.get("assignment_rows") == 5805
        and assignment_decision.get("search_evaluations") == 0
        and assignment_metadata.get("contract_sha256") == sha256(CUSTOMER_CONTRACT)
        and not quota_errors
        and not overlap_errors
    )
    checks["mc005_candidate_a_assignments"] = customer_ok
    errors.extend(quota_errors)
    errors.extend(f"within-cell identity overlap: {value}" for value in overlap_errors)
    if not customer_ok and not quota_errors and not overlap_errors:
        errors.append("MC-005 customer contract or assignment metadata mismatch")

    facility_manifest = load(FACILITIES)
    facility_records = facility_manifest.get("records", [])
    source_errors: list[str] = []
    for record in facility_records:
        capture = ROOT / str(record.get("primary_source_capture", ""))
        if not capture.is_file():
            source_errors.append(f"facility source missing: {record.get('city')}")
        elif sha256(capture) != record.get("primary_source_capture_sha256"):
            source_errors.append(f"facility source hash mismatch: {record.get('city')}")
    road_decision = load(ROAD_ACCESS / "decision.json")
    access_rows = read_csv(ROAD_ACCESS / "road_access_points.csv")
    access_ok = (
        len(facility_records) == 9
        and len({record.get("city") for record in facility_records}) == 9
        and not source_errors
        and road_decision.get("verdict")
        == "PASS_NINE_CITY_SCENARIO_ROAD_ACCESS_AND_REACHABILITY"
        and road_decision.get("facilities") == 9
        and road_decision.get("route_checks") == 18
        and road_decision.get("route_passes") == 18
        and road_decision.get("solver_search_evaluations") == 0
        and len(access_rows) == 9
        and len({row["city"] for row in access_rows}) == 9
        and all(row["point_semantics"] == "SCENARIO_ROAD_ACCESS_POINT_NOT_OBSERVED_TRUCK_GATE" for row in access_rows)
        and all(row["road_feature_id"].startswith("w") for row in access_rows)
        and all(row["cv_route_status"] == row["ev_route_status"] == "PASS" for row in access_rows)
        and all(math.isfinite(float(row["road_access_lon_wgs84"])) and math.isfinite(float(row["road_access_lat_wgs84"])) for row in access_rows)
    )
    checks["facility_identity_and_nine_city_road_access"] = access_ok
    errors.extend(source_errors)
    if not access_ok and not source_errors:
        errors.append("nine-city facility road-access package mismatch")

    functional = load(FUNCTIONAL / "decision.json")
    functional_ok = (
        functional.get("verdict") == "PASS_OSRM_2673_MINIMUM_FREIGHT_FUNCTIONAL_GATE"
        and functional.get("route_checks") == 18
        and functional.get("route_passes") == 18
        and all(functional.get("checks", {}).values())
        and functional.get("solver_search_evaluations") == 0
        and functional.get("full_matrix_built") is False
    )
    checks["osrm_minimum_freight_functional_gate"] = functional_ok
    if not functional_ok:
        errors.append("OSRM minimum freight functional gate mismatch")

    pbf_rows = {
        row["frozen_osm_pbf"]: row["frozen_osm_sha256"] for row in access_rows
    }
    pbf_errors = [
        relative
        for relative, expected in pbf_rows.items()
        if not (ROOT / relative).is_file() or sha256(ROOT / relative) != expected
    ]
    checks["frozen_osm_inputs"] = len(pbf_rows) == 5 and not pbf_errors
    errors.extend(f"frozen OSM mismatch: {value}" for value in pbf_errors)
    if len(pbf_rows) != 5:
        errors.append(f"expected five frozen OSM inputs, observed {len(pbf_rows)}")

    mc002 = load(MC002 / "decision.json")
    mc002_ok = (
        mc002.get("status") == "PASS_MC002_METHOD_FROZEN_FULL_RUNS_NOT_AUTHORIZED"
        and mc002.get("whole_mc002_contract_frozen") is True
        and mc002.get("remaining_user_approvals") == []
        and mc002.get("user_approval", {}).get("approval_id") == "P1-APP-05"
        and mc002.get("formal_search_allowed") is False
    )
    checks["mc002_method_and_compute_contract"] = mc002_ok
    if not mc002_ok:
        errors.append("MC-002 method package mismatch")

    road_contract = load(ROAD_CONTRACT)
    register_text = APPROVAL_REGISTER.read_text(encoding="utf-8")
    mc004_approved = (
        road_contract.get("status") == "MC004_APPROVED_FULL_MATRIX_DEFERRED_TO_STAGE2"
        and "状态：`APPROVED_METHOD_FULL_MATRIX_DEFERRED_TO_STAGE2`" in register_text
    )
    mc004_ready = (
        road_contract.get("status")
        in {
            "MC004_REAPPROVAL_READY_EVIDENCE_PASS_FULL_MATRIX_NOT_RUN",
            "MC004_APPROVED_FULL_MATRIX_DEFERRED_TO_STAGE2",
        }
        and road_contract.get("router_contract", {})
        .get("phase1_functional_evidence", {})
        .get("verdict")
        == "PASS_OSRM_2673_MINIMUM_FREIGHT_FUNCTIONAL_GATE"
        and road_contract.get("router_contract", {})
        .get("phase1_nine_city_road_access_evidence", {})
        .get("verdict")
        == "PASS_NINE_CITY_SCENARIO_ROAD_ACCESS_AND_REACHABILITY"
    )
    checks["mc004_evidence_ready"] = mc004_ready
    checks["mc004_user_approval"] = mc004_approved
    if not mc004_ready:
        errors.append("MC-004 evidence is not ready for reapproval")

    lock = load(PARAMETER_LOCK)
    boundary_ok = lock.get("formal_search_allowed") is False and lock.get("status") == "NOT_FORMAL"
    checks["stage2_and_formal_search_remain_blocked"] = boundary_ok
    if not boundary_ok:
        errors.append("phase-two/formal-search safety boundary changed")

    protected = [
        "solver/src/setp_solver/cost.py",
        "solver/src/setp_solver/check.py",
        "solver/src/setp_solver/search/evaluation.py",
    ]
    diff = subprocess.run(
        ["git", "diff", "--name-only", "--", *protected],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    protected_clean = diff.returncode == 0 and not diff.stdout.strip()
    checks["protected_solver_files_unchanged"] = protected_clean
    if not protected_clean:
        errors.append(f"protected solver files changed: {diff.stdout.strip()}")

    approval_pending = [] if mc004_approved else ["MC-004"]
    evidence_pass = not errors
    handoff_ready = evidence_pass and not approval_pending
    verdict = (
        "PASS_PHASE1_NONALGORITHM_HANDOFF_READY"
        if handoff_ready
        else "EVIDENCE_PASS_AWAITING_MC004_USER_APPROVAL"
        if evidence_pass
        else "HALT_PHASE1_NONALGORITHM_HANDOFF"
    )
    result = {
        "schema": "resetp.phase1.nonalgorithm-handoff-audit.v1",
        "generated_utc": datetime.now(UTC).isoformat(),
        "verdict": verdict,
        "evidence_pass": evidence_pass,
        "handoff_ready": handoff_ready,
        "approval_pending": approval_pending,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "algorithm_optimization_in_scope": False,
        "full_matrix_built": False,
        "formal_search_allowed": False,
        "solver_search_evaluations": 0,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "decision.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "metadata.json").write_text(
        json.dumps(
            {
                "schema": "resetp.phase1.nonalgorithm-handoff-audit.metadata.v1",
                "inputs": {
                    str(path.relative_to(ROOT)): sha256(path)
                    for path in (
                        CUSTOMER_CONTRACT,
                        ASSIGNMENTS / "decision.json",
                        ASSIGNMENTS / "metadata.json",
                        FACILITIES,
                        ROAD_ACCESS / "decision.json",
                        ROAD_ACCESS / "road_access_points.csv",
                        FUNCTIONAL / "decision.json",
                        ROAD_CONTRACT,
                        MC002 / "decision.json",
                        PARAMETER_LOCK,
                        APPROVAL_REGISTER,
                    )
                },
                "solver_search_evaluations": 0,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "report.md").write_text(
        "# 阶段一非算法交接审计\n\n"
        f"判决：`{verdict}`。证据检查{'全部通过' if evidence_pass else '存在错误'}；"
        f"{'没有待批项' if not approval_pending else '只待用户批准MC-004方法'}。"
        "算法优化、全道路矩阵和正式搜索均不在本次范围内，搜索评价为0。\n",
        encoding="utf-8",
    )
    files = [output / "decision.json", output / "metadata.json", output / "report.md"]
    (output / "artifact_hashes.json").write_text(
        json.dumps(
            {
                "schema": "resetp.artifact-hashes.v1",
                "files": {str(path.relative_to(ROOT)): sha256(path) for path in files},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="data/ChinaInstances/phase1_nonalgorithm_handoff_audit_preapproval_v1_20260718",
    )
    args = parser.parse_args()
    output = ROOT / args.output
    if output.exists():
        raise RuntimeError(f"refusing to overwrite {output}")
    result = audit(output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["evidence_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
