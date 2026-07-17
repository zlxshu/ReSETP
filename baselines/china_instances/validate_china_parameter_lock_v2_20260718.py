"""Read-only preflight for the China V2 parameter-lock contract.

This command never runs the solver and never changes an instance.  It answers a
narrow question: are the source-bound contract, unit contract and core
localisation gates in a state that permits a later formal instance build?
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
LOCK = REPO / "data/ChinaInstances/china_parameter_lock_v2_20260718.json"
VEHICLE_SOURCE_ROOT = REPO / "docs/handoff/china_vehicle_parameter_sources_20260718"
PRICES = REPO / "solver/src/setp_solver/prices.py"
ORDINARY_DEPOT_MANIFEST = REPO / "data/ChinaInstances/china_ordinary_commercial_depot_manifest_v2_20260718.json"
LOCATION_ASSIGNMENTS = REPO / "data/ChinaInstances/china81_customer_location_assignments_v2_20260718"
EXPECTED_CITIES = {
    "beijing",
    "tianjin",
    "shijiazhuang",
    "guangzhou",
    "shenzhen",
    "dongguan",
    "foshan",
    "chengdu",
    "chongqing",
}
EXPECTED_PREFERRED_MAP_UIDS = {
    "beijing": "07dc236824a0e3ba49fc8d2b",
    "tianjin": "0aa45c3b9adf9a5e6e20b930",
    "shijiazhuang": "f13a67f3eea2123a82a12e5e",
    "guangzhou": "f5141d94db59caa1c356ac61",
    "shenzhen": "6421a1c69b1aeab68a36eef1",
    "dongguan": "ee7fc367b5165e7f22f017f0",
    "foshan": "b3de3ceec4a5b371b31e3674",
    "chengdu": "85880009b61de98646572689",
    "chongqing": "6e699d1ad3a23e9b260bd089",
}


def validate_order_contract(
    data: dict[str, Any], errors: list[dict[str, str]], warnings: list[dict[str, str]]
) -> dict[str, Any]:
    """Validate the pre-registered synthetic order-attribute design."""

    customer_contract = data.get("customer_contract", {})
    relative_path = customer_contract.get("order_attribute_contract")
    if not isinstance(relative_path, str) or not relative_path:
        errors.append(_error("ORDER_ATTRIBUTE_CONTRACT_PATH_MISSING", "customer_contract.order_attribute_contract"))
        return {"exists": False}
    path = REPO / relative_path
    if not path.is_file():
        errors.append(_error("ORDER_ATTRIBUTE_CONTRACT_MISSING", str(path)))
        return {"exists": False, "path": relative_path}
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(_error("ORDER_ATTRIBUTE_CONTRACT_UNREADABLE", repr(exc)))
        return {"exists": True, "path": relative_path}
    if contract.get("schema") != "resetp.china.order-attribute-contract.v2":
        errors.append(_error("ORDER_ATTRIBUTE_SCHEMA_MISMATCH", str(contract.get("schema"))))
    witness = contract.get("witness_contract", {})
    if (
        witness.get("vehicle_payload_reference_kg") != 1000
        or witness.get("route_load_limit_fraction") != 1.0
        or witness.get("route_load_limit_kg") != 1000
    ):
        errors.append(_error("F1_BOX_BODY_PAYLOAD_CHAIN_MISMATCH", repr(witness)))
    if (
        witness.get("optional_robustness_construction_target_kg") != 800
        or witness.get("optional_robustness_construction_target_role") != "SENSITIVITY_ONLY_NOT_HARD_CAPACITY"
    ):
        errors.append(_error("F1_ROBUSTNESS_TARGET_BOUNDARY_MISSING", repr(witness)))
    if str(contract.get("status", "")).startswith("HALT_"):
        errors.append(
            _error(
                "ORDER_ATTRIBUTE_RECALIBRATION_REQUIRED",
                str(contract.get("status")),
            )
        )
        return {
            "exists": True,
            "path": relative_path,
            "sha256": sha256(path),
            "status": contract.get("status"),
            "customer_sizes": contract.get("customer_sizes"),
            "variants": sorted(contract.get("variants", {})),
        }
    if contract.get("status") != "LOCKED_DESIGN_NOT_APPLIED":
        errors.append(_error("ORDER_ATTRIBUTE_STATUS_INVALID", str(contract.get("status"))))
    if contract.get("formal_search_allowed") is not False:
        errors.append(_error("ORDER_ATTRIBUTE_FORMAL_FLAG_INVALID", "must remain false before V2 build"))
    if contract.get("observed_chinese_orders_claim_allowed") is not False:
        errors.append(_error("ORDER_ATTRIBUTE_OBSERVED_CLAIM_INVALID", "synthetic design cannot claim observed orders"))
    variants = contract.get("variants", {})
    if set(variants) != {"01", "02", "03"}:
        errors.append(_error("ORDER_ATTRIBUTE_VARIANTS_INVALID", repr(sorted(variants))))
    if {row.get("window_profile") for row in variants.values() if isinstance(row, dict)} != {
        "base_empirical_delivery"
    }:
        errors.append(_error("ORDER_ATTRIBUTE_REPLICATE_PROFILE_CONFOUNDED", repr(variants)))
    if {row.get("replicate_index") for row in variants.values() if isinstance(row, dict)} != {1, 2, 3}:
        errors.append(_error("ORDER_ATTRIBUTE_REPLICATE_INDEX_INVALID", repr(variants)))
    exclusivity = contract.get("mutual_exclusivity_contract", {})
    for field in (
        "customer_map_identity_overlap_allowed",
        "customer_id_overlap_allowed",
        "order_seed_overlap_allowed",
        "same_instance_with_changed_label_allowed",
        "post_result_customer_replacement_allowed",
    ):
        if exclusivity.get(field) is not False:
            errors.append(_error("ORDER_ATTRIBUTE_MUTUAL_EXCLUSIVITY_INVALID", f"{field}={exclusivity.get(field)!r}"))
    profiles = contract.get("time_window_profiles", {})
    if set(profiles) != {
        "base_empirical_delivery",
        "sensitivity_wide_pickup_proxy",
        "sensitivity_tight_delivery_lower_half",
    }:
        errors.append(_error("ORDER_ATTRIBUTE_WINDOW_PROFILES_INVALID", repr(sorted(profiles))))
    primary_profile = profiles.get("base_empirical_delivery", {})
    empirical_rows = REPO / str(primary_profile.get("source_rows", ""))
    if primary_profile.get("role") != "FORMAL_PRIMARY" or primary_profile.get("source_row_count") != 1222:
        errors.append(_error("ORDER_ATTRIBUTE_PRIMARY_PROFILE_INVALID", repr(primary_profile)))
    if not empirical_rows.is_file():
        errors.append(_error("ORDER_ATTRIBUTE_EMPIRICAL_ROWS_MISSING", str(empirical_rows)))
    calibration = contract.get("calibration_evidence", {})
    package = REPO / str(calibration.get("package", ""))
    decision_path = package / "decision.json"
    calibration_path = package / "calibration.json"
    if not decision_path.is_file() or not calibration_path.is_file():
        errors.append(_error("ORDER_ATTRIBUTE_CALIBRATION_PACKAGE_MISSING", str(package)))
    else:
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        if decision.get("decision") != "PASS_EVIDENCE_AUDIT_AWAITING_MODEL_TRANSFORMATION_APPROVAL":
            errors.append(_error("ORDER_ATTRIBUTE_CALIBRATION_NOT_PASSED", repr(decision)))
        if sha256(calibration_path) != calibration.get("calibration_sha256"):
            errors.append(_error("ORDER_ATTRIBUTE_CALIBRATION_HASH_MISMATCH", str(calibration_path)))
    if empirical_rows.is_file() and sha256(empirical_rows) != calibration.get("empirical_rows_sha256"):
        errors.append(_error("ORDER_ATTRIBUTE_EMPIRICAL_ROWS_HASH_MISMATCH", str(empirical_rows)))
    if calibration.get("named_city_or_company_claim_allowed") is not False:
        errors.append(_error("ORDER_ATTRIBUTE_ANONYMITY_BOUNDARY_MISSING", repr(calibration)))
    mixture = contract.get("demand_mixture", [])
    probabilities = [row.get("probability") for row in mixture if isinstance(row, dict)]
    if len(probabilities) != 5 or not math.isclose(sum(float(value) for value in probabilities), 1.0):
        errors.append(_error("ORDER_ATTRIBUTE_DEMAND_MIXTURE_INVALID", repr(probabilities)))
    maximum_demand = max(
        (row.get("fixed_proxy_kg", 0) for row in mixture if isinstance(row, dict)), default=0
    )
    minimum_payload = min(
        float(spec.get("payload_capacity_kg", 0) or 0) for spec in data.get("vehicle_contract", {}).values()
    )
    if not 0 < float(maximum_demand) < minimum_payload:
        errors.append(
            _error("ORDER_ATTRIBUTE_DEMAND_EXCEEDS_PAYLOAD", f"max_demand={maximum_demand}, payload={minimum_payload}")
        )
    witness = contract.get("witness_contract", {})
    if witness.get("algorithm_search_evaluations") != 0 or witness.get("regeneration_after_failure_allowed") is not False:
        errors.append(_error("ORDER_ATTRIBUTE_WITNESS_GOVERNANCE_INVALID", repr(witness)))
    if customer_contract.get("regional_24h_extension_allowed") is not False:
        errors.append(_error("ORDER_ATTRIBUTE_24H_EXTENSION_NOT_DISABLED", "formal urban family is 06:00--22:00"))
    warnings.append(
        {
            "code": "ORDER_ATTRIBUTE_DESIGN_NOT_APPLIED",
            "detail": "source-backed design is locked; road-time matrices and verified depot entrances are required before formal instances can be generated",
        }
    )
    return {
        "exists": True,
        "path": relative_path,
        "sha256": sha256(path),
        "status": contract.get("status"),
        "customer_sizes": contract.get("customer_sizes"),
        "variants": sorted(variants),
    }


def validate_customer_location_contract(
    data: dict[str, Any], errors: list[dict[str, str]], warnings: list[dict[str, str]]
) -> dict[str, Any]:
    """Validate the 3 regions x 9 sizes x 3 disjoint-replicate location design."""

    relative_path = data.get("customer_contract", {}).get("customer_location_contract")
    if not isinstance(relative_path, str) or not relative_path:
        errors.append(_error("CUSTOMER_LOCATION_CONTRACT_PATH_MISSING", "customer_contract.customer_location_contract"))
        return {"exists": False}
    path = REPO / relative_path
    if not path.is_file():
        errors.append(_error("CUSTOMER_LOCATION_CONTRACT_MISSING", str(path)))
        return {"exists": False, "path": relative_path}
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("schema") != "resetp.china.customer-location-contract.v2":
        errors.append(_error("CUSTOMER_LOCATION_SCHEMA_MISMATCH", str(contract.get("schema"))))
    if str(contract.get("status", "")).startswith("HALT_"):
        errors.append(
            _error(
                "CUSTOMER_LOCATION_PPS_RECALIBRATION_REQUIRED",
                str(contract.get("status")),
            )
        )
        return {
            "exists": True,
            "path": relative_path,
            "sha256": sha256(path),
            "status": contract.get("status"),
            "customer_sizes": contract.get("customer_sizes"),
            "replicate_labels": contract.get("replicate_labels"),
        }
    if contract.get("status") != "LOCKED_DESIGN_POOL_SUFFICIENCY_PASSED_NOT_BUILT":
        errors.append(_error("CUSTOMER_LOCATION_STATUS_INVALID", str(contract.get("status"))))
    if contract.get("formal_search_allowed") is not False:
        errors.append(_error("CUSTOMER_LOCATION_FORMAL_FLAG_INVALID", "must remain false before pool and build gates pass"))
    if contract.get("replicates_per_region_size") != 3 or contract.get("replicate_labels") != ["01", "02", "03"]:
        errors.append(_error("CUSTOMER_LOCATION_REPLICATE_CONTRACT_INVALID", repr(contract)))
    if contract.get("within_cell_identity_overlap_allowed") is not False:
        errors.append(_error("CUSTOMER_LOCATION_OVERLAP_GUARD_MISSING", "within-cell OSM identity overlap must be false"))
    if contract.get("post_result_replacement_allowed") is not False:
        errors.append(_error("CUSTOMER_LOCATION_RESULT_TUNING_GUARD_MISSING", "post-result replacement must be false"))
    quotas = contract.get("city_quotas", {})
    sizes = contract.get("customer_sizes", [])
    if set(quotas) != {"jjj", "prd", "cy"} or sum(len(table) for table in quotas.values()) != 27:
        errors.append(_error("CUSTOMER_LOCATION_27_CELL_SCOPE_INVALID", repr(quotas.keys())))
    for region, table in quotas.items():
        if sorted(int(size) for size in table) != sizes:
            errors.append(_error("CUSTOMER_LOCATION_SIZE_GRID_INVALID", region))
        for size, city_quotas in table.items():
            if sum(int(value) for value in city_quotas.values()) != int(size):
                errors.append(_error("CUSTOMER_LOCATION_CITY_QUOTA_INVALID", f"{region}/{size}={city_quotas!r}"))
    gate = contract.get("sufficiency_gate", {})
    package = REPO / str(gate.get("evidence_package", ""))
    decision_path = package / "decision.json"
    metadata_path = package / "metadata.json"
    artifact_hashes_path = package / "artifact_hashes.json"
    if not all(artifact.is_file() for artifact in (decision_path, metadata_path, artifact_hashes_path)):
        errors.append(_error("CUSTOMER_LOCATION_GATE_EVIDENCE_MISSING", str(package)))
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("contract_sha256") != sha256(path):
            errors.append(_error("CUSTOMER_LOCATION_GATE_CONTRACT_HASH_STALE", str(metadata.get("contract_sha256"))))
    if decision_path.is_file():
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        if decision.get("verdict") != gate.get("required_verdict") or decision.get("region_size_cells_passed") != 27:
            errors.append(_error("CUSTOMER_LOCATION_GATE_VERDICT_INVALID", repr(decision)))
    assignment_decision_path = LOCATION_ASSIGNMENTS / "decision.json"
    assignment_metadata_path = LOCATION_ASSIGNMENTS / "metadata.json"
    assignment_status = "MISSING"
    if assignment_decision_path.is_file() and assignment_metadata_path.is_file():
        assignment_decision = json.loads(assignment_decision_path.read_text(encoding="utf-8"))
        assignment_metadata = json.loads(assignment_metadata_path.read_text(encoding="utf-8"))
        assignment_status = str(assignment_decision.get("verdict"))
        if (
            assignment_status != "PASS_81_DISJOINT_LOCATION_ASSIGNMENTS_BUILT"
            or assignment_decision.get("instances") != 81
            or assignment_decision.get("within_cell_overlap_violations") != []
            or assignment_metadata.get("contract_sha256") != sha256(path)
        ):
            errors.append(_error("CUSTOMER_LOCATION_ASSIGNMENT_EVIDENCE_INVALID", repr(assignment_decision)))
    else:
        errors.append(_error("CUSTOMER_LOCATION_ASSIGNMENT_EVIDENCE_MISSING", str(LOCATION_ASSIGNMENTS)))
    warnings.append(
        {
            "code": "CUSTOMER_LOCATION_ASSIGNMENTS_BUILT_NOT_FORMAL_INSTANCES",
            "detail": "81 disjoint customer location selections exist; orders, depots, chargers and road matrices are not attached",
        }
    )
    return {
        "exists": True,
        "path": relative_path,
        "sha256": sha256(path),
        "status": contract.get("status"),
        "region_size_cells": sum(len(table) for table in quotas.values()),
        "replicates_per_cell": contract.get("replicates_per_region_size"),
        "assignment_status": assignment_status,
    }


def validate_road_matrix_contract(
    data: dict[str, Any], errors: list[dict[str, str]], warnings: list[dict[str, str]]
) -> dict[str, Any]:
    distance = data.get("distance_contract", {})
    relative_path = distance.get("road_matrix_contract")
    if not isinstance(relative_path, str) or not relative_path:
        errors.append(_error("ROAD_MATRIX_CONTRACT_PATH_MISSING", "distance_contract.road_matrix_contract"))
        return {"exists": False}
    path = REPO / relative_path
    if not path.is_file():
        errors.append(_error("ROAD_MATRIX_CONTRACT_MISSING", str(path)))
        return {"exists": False, "path": relative_path}
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("schema") != "resetp.china.road-matrix-contract.v2":
        errors.append(_error("ROAD_MATRIX_SCHEMA_MISMATCH", str(contract.get("schema"))))
    if contract.get("formal_search_allowed") is not False:
        errors.append(_error("ROAD_MATRIX_FORMAL_FLAG_INVALID", "design contract cannot authorize search"))
    coordinate = contract.get("coordinate_contract", {})
    if coordinate.get("formal_crs") != "WGS84" or coordinate.get("raw_baidu_crs") != "BD09MC":
        errors.append(_error("ROAD_MATRIX_CRS_CONTRACT_INVALID", repr(coordinate)))
    if coordinate.get("raw_baidu_values_may_enter_formal_lat_lon") is not False:
        errors.append(_error("ROAD_MATRIX_BAIDU_RAW_COORDINATE_GUARD_MISSING", repr(coordinate)))
    router = contract.get("router_contract", {})
    if router.get("euclidean_multiplier_allowed") is not False or router.get("straight_line_fallback_allowed") is not False:
        errors.append(_error("ROAD_MATRIX_GEOMETRIC_FALLBACK_NOT_BLOCKED", repr(router)))
    invariants = contract.get("matrix_invariants", {})
    if invariants.get("unreachable_node_policy") != "HALT_INSTANCE_NO_REPLACEMENT_AFTER_RESULTS":
        errors.append(_error("ROAD_MATRIX_UNREACHABLE_POLICY_INVALID", repr(invariants)))
    warnings.append(
        {
            "code": "ROAD_MATRIX_DESIGN_WAITING_FOR_WGS84_ENTRANCES",
            "detail": "matrix design is locked, but no formal road matrices exist until depot and charger road nodes are verified",
        }
    )
    return {
        "exists": True,
        "path": relative_path,
        "sha256": sha256(path),
        "status": contract.get("status"),
        "formal_crs": coordinate.get("formal_crs"),
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _error(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def validate_facility_manifest(
    data: dict[str, Any], errors: list[dict[str, str]], warnings: list[dict[str, str]]
) -> dict[str, Any]:
    """Validate ordinary commercial depot candidates without accepting park centres as truck gates."""

    facility_contract = data.get("facility_contract", {})
    relative_path = facility_contract.get("candidate_manifest")
    if not isinstance(relative_path, str) or not relative_path:
        errors.append(_error("FACILITY_MANIFEST_PATH_MISSING", "facility_contract.candidate_manifest"))
        return {"exists": False, "record_count": 0, "pending_records": []}
    facility_manifest = REPO / relative_path
    if facility_manifest != ORDINARY_DEPOT_MANIFEST:
        errors.append(
            _error(
                "FACILITY_MANIFEST_NOT_ORDINARY_COMMERCIAL",
                f"expected={ORDINARY_DEPOT_MANIFEST.relative_to(REPO)}, observed={relative_path}",
            )
        )
    if not facility_manifest.is_file():
        errors.append(_error("FACILITY_MANIFEST_MISSING", str(facility_manifest)))
        return {"exists": False, "record_count": 0, "pending_records": []}

    try:
        manifest = json.loads(facility_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(_error("FACILITY_MANIFEST_UNREADABLE", repr(exc)))
        return {"exists": True, "record_count": 0, "pending_records": []}

    if manifest.get("schema") != "resetp.china.ordinary-commercial-depot-manifest.v2":
        errors.append(_error("FACILITY_MANIFEST_SCHEMA_INVALID", str(manifest.get("schema"))))
    if manifest.get("formal_search_allowed") is not False:
        errors.append(_error("FACILITY_MANIFEST_FORMAL_FLAG_INVALID", "candidate manifest must not authorize formal search"))
    if manifest.get("result_aware_selection_allowed") is not False:
        errors.append(_error("FACILITY_RESULT_AWARE_SELECTION_NOT_BLOCKED", "depot selection cannot use experiment results"))
    records = manifest.get("records", [])
    if not isinstance(records, list):
        errors.append(_error("FACILITY_RECORDS_NOT_LIST", type(records).__name__))
        return {"exists": True, "record_count": 0, "pending_records": []}

    cities = [record.get("city") for record in records if isinstance(record, dict)]
    if len(records) != len(EXPECTED_CITIES) or set(cities) != EXPECTED_CITIES:
        errors.append(
            _error(
                "FACILITY_CITY_COVERAGE_INVALID",
                f"expected={sorted(EXPECTED_CITIES)!r}, observed={sorted(set(cities))!r}",
            )
        )

    required = ("city", "primary", "backup", "primary_source", "backup_source", "formal_status")
    pending_records: list[str] = []
    source_capture_count = 0
    verified_gate_count = 0
    verified_charger_count = 0
    seen_cities: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(_error("FACILITY_RECORD_INVALID", f"index={index}"))
            continue
        city = str(record.get("city") or f"index-{index}")
        facility_id = f"{city}:{record.get('primary', 'unnamed')}"
        if city in seen_cities:
            errors.append(_error("FACILITY_CITY_DUPLICATE", city))
        seen_cities.add(city)
        for field in required:
            if field not in record or record.get(field) in ("", {}):
                errors.append(_error("FACILITY_FIELD_MISSING", f"{facility_id}.{field}"))
        source_url = record.get("primary_source")
        if not isinstance(source_url, str) or not source_url.startswith("https://"):
            errors.append(_error("FACILITY_SOURCE_URL_INVALID", facility_id))
        capture = record.get("primary_source_capture")
        capture_hash = record.get("primary_source_capture_sha256")
        if capture in (None, ""):
            errors.append(_error("FACILITY_SOURCE_CAPTURE_PENDING", facility_id))
        else:
            capture_path = REPO / str(capture)
            if not capture_path.is_file():
                errors.append(_error("FACILITY_SOURCE_CAPTURE_MISSING", str(capture_path)))
            elif capture_hash in (None, ""):
                errors.append(_error("FACILITY_SOURCE_CAPTURE_HASH_MISSING", facility_id))
            elif sha256(capture_path) != str(capture_hash):
                errors.append(_error("FACILITY_SOURCE_CAPTURE_HASH_MISMATCH", facility_id))
            else:
                source_capture_count += 1
        brochure = record.get("official_brochure_capture")
        if brochure not in (None, ""):
            brochure_path = REPO / str(brochure)
            brochure_hash = record.get("official_brochure_capture_sha256")
            if not brochure_path.is_file():
                errors.append(_error("FACILITY_BROCHURE_CAPTURE_MISSING", str(brochure_path)))
            elif brochure_hash in (None, ""):
                errors.append(_error("FACILITY_BROCHURE_HASH_MISSING", facility_id))
            elif sha256(brochure_path) != str(brochure_hash):
                errors.append(_error("FACILITY_BROCHURE_HASH_MISMATCH", facility_id))
        park_center = record.get("park_center_candidate")
        if park_center is not None:
            if not isinstance(park_center, dict) or park_center.get("crs") != "BD-09":
                errors.append(_error("FACILITY_PARK_CENTER_CRS_INVALID", facility_id))
            elif "not_truck_gate" not in str(park_center.get("source_scope", "")):
                errors.append(_error("FACILITY_PARK_CENTER_SCOPE_UNSAFE", facility_id))
        gate = record.get("verified_truck_gate")
        if not isinstance(gate, dict) or gate.get("status") != "VERIFIED":
            errors.append(_error("FACILITY_TRUCK_GATE_PENDING", facility_id))
        else:
            coordinate = gate.get("wgs84")
            latitude = coordinate.get("latitude") if isinstance(coordinate, dict) else None
            longitude = coordinate.get("longitude") if isinstance(coordinate, dict) else None
            if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (latitude, longitude)):
                errors.append(_error("FACILITY_TRUCK_GATE_COORDINATE_INVALID", facility_id))
            if gate.get("road_node_id") in (None, ""):
                errors.append(_error("FACILITY_TRUCK_GATE_ROAD_NODE_PENDING", facility_id))
            if gate.get("evidence") in (None, [], ""):
                errors.append(_error("FACILITY_TRUCK_GATE_EVIDENCE_PENDING", facility_id))
            if not any(error["detail"] == facility_id and error["code"].startswith("FACILITY_TRUCK_GATE") for error in errors):
                verified_gate_count += 1
        operations = record.get("verified_operations")
        if not isinstance(operations, dict) or operations.get("status") != "VERIFIED":
            errors.append(_error("FACILITY_OPERATIONS_PENDING", facility_id))
        else:
            for field in ("external_delivery_trucks_allowed", "access_rule", "gate_open_hours", "parking_or_dock_capacity"):
                if operations.get(field) in (None, ""):
                    errors.append(_error("FACILITY_OPERATION_FIELD_PENDING", f"{facility_id}.{field}"))
        charging = record.get("verified_vehicle_charging")
        if not isinstance(charging, dict) or charging.get("status") not in {"VERIFIED_OPERATIONAL", "VERIFIED_ABSENT"}:
            errors.append(_error("FACILITY_VEHICLE_CHARGING_PENDING", facility_id))
        elif charging.get("status") == "VERIFIED_OPERATIONAL":
            for field in ("location", "charger_count", "connector_count", "rated_power_kw", "delivery_trucks_allowed"):
                if charging.get(field) in (None, ""):
                    errors.append(_error("FACILITY_CHARGING_FIELD_PENDING", f"{facility_id}.{field}"))
            verified_charger_count += 1
        if "PENDING" in str(record.get("formal_status", "")):
            pending_records.append(facility_id)

    if pending_records:
        warnings.append(
            {
                "code": "FACILITY_MANIFEST_NOT_FORMAL",
                "detail": f"{len(pending_records)} records still require coordinate/operation verification",
            }
        )
    return {
        "exists": True,
        "path": relative_path,
        "schema": manifest.get("schema"),
        "record_count": len(records),
        "cities": sorted(set(cities)),
        "pending_records": pending_records,
        "source_capture_count": source_capture_count,
        "verified_truck_gate_count": verified_gate_count,
        "verified_vehicle_charging_count": verified_charger_count,
        "historical_special_facilities_used": False,
    }


def validate_default_date_decision(
    data: dict[str, Any], errors: list[dict[str, str]], warnings: list[dict[str, str]]
) -> dict[str, Any]:
    """Ensure a favorable default date is preselected without deleting the full-month panel."""

    carbon_contract = data.get("carbon_contract", {})
    relative_path = carbon_contract.get("default_date_decision")
    if not isinstance(relative_path, str) or not relative_path:
        errors.append(_error("DEFAULT_DATE_DECISION_PATH_MISSING", "carbon_contract.default_date_decision"))
        return {"exists": False}
    path = REPO / relative_path
    if not path.is_file():
        errors.append(_error("DEFAULT_DATE_DECISION_MISSING", str(path)))
        return {"exists": False, "path": relative_path}
    try:
        decision = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(_error("DEFAULT_DATE_DECISION_UNREADABLE", repr(exc)))
        return {"exists": True, "path": relative_path}
    if decision.get("schema") != "resetp.china.default-date-decision.v2":
        errors.append(_error("DEFAULT_DATE_DECISION_SCHEMA_INVALID", str(decision.get("schema"))))
    if decision.get("formal_month") != "2025-02":
        errors.append(_error("DEFAULT_DATE_FORMAL_MONTH_INVALID", str(decision.get("formal_month"))))
    if decision.get("full_month_panel_required") is not True:
        errors.append(_error("DEFAULT_DATE_FULL_MONTH_PANEL_NOT_REQUIRED", "all 28 February days must remain"))
    if decision.get("selection_must_precede_formal_experiment_results") is not True:
        errors.append(_error("DEFAULT_DATE_RESULT_BLIND_RULE_MISSING", "selection must precede formal results"))
    if decision.get("optimization_results_read") is not False:
        errors.append(_error("DEFAULT_DATE_RESULT_CONTAMINATION", str(decision.get("optimization_results_read"))))
    options = decision.get("options", {})
    if set(options) != {"A", "B", "C", "D"}:
        errors.append(_error("DEFAULT_DATE_OPTIONS_INVALID", repr(sorted(options))))
    selected = decision.get("selected_option")
    if selected is None:
        warnings.append(
            {
                "code": "DEFAULT_DATE_USER_SELECTION_PENDING",
                "detail": "choose A, B, C or D before formal China experiments; full February remains mandatory",
            }
        )
    elif selected not in options:
        errors.append(_error("DEFAULT_DATE_SELECTION_INVALID", repr(selected)))
    elif selected == "C":
        if decision.get("selected_common_default_date") != "2025-02-12":
            errors.append(
                _error(
                    "DEFAULT_DATE_C_DATE_MISMATCH",
                    repr(decision.get("selected_common_default_date")),
                )
            )
        holiday = decision.get("holiday_sensitivity", {})
        if holiday.get("remaining_days") != 24 or holiday.get("formal_full_month_retained") is not True:
            errors.append(_error("DEFAULT_DATE_HOLIDAY_SENSITIVITY_INVALID", repr(holiday)))
    return {
        "exists": True,
        "path": relative_path,
        "status": decision.get("status"),
        "selected_option": selected,
        "formal_month": decision.get("formal_month"),
        "full_month_panel_required": decision.get("full_month_panel_required"),
        "optimization_results_read": decision.get("optimization_results_read"),
    }


def validate_lock(lock: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a machine-readable gate result without mutating repository state."""

    data = lock if lock is not None else json.loads(LOCK.read_text(encoding="utf-8"))
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if data.get("schema") != "resetp.china.parameter-lock.v2":
        errors.append(_error("SCHEMA_MISMATCH", str(data.get("schema"))))
    if data.get("formal_search_allowed") is not False:
        errors.append(_error("FORMAL_SEARCH_FLAG_MUST_BE_FALSE", "V2 contract is not yet frozen"))
    scope = data.get("scope", {})
    if scope.get("target_instances") != 81 or scope.get("customer_sizes") != [10, 15, 20, 25, 50, 75, 100, 150, 200]:
        errors.append(_error("CHINA81_SCOPE_INVALID", repr(scope)))
    if scope.get("instances_per_region_size") != 3 or scope.get("mutual_exclusivity_required") is not True:
        errors.append(_error("CHINA81_MUTUAL_EXCLUSIVITY_CONTRACT_INVALID", repr(scope)))
    units = data.get("units", {})
    expected_units = {
        "currency": "CNY",
        "money": "CNY",
        "mass": "kg",
        "energy": "kWh",
        "power": "kW",
        "emission": "kgCO2e",
        "time": "second",
    }
    for field, expected in expected_units.items():
        if units.get(field) != expected:
            errors.append(_error("UNIT_CONTRACT_MISMATCH", f"{field}={units.get(field)!r}, expected {expected!r}"))

    vehicles = data.get("vehicle_contract", {})
    for vehicle_type in ("cv", "ev"):
        spec = vehicles.get(vehicle_type, {})
        required_fields = ["model", "gross_mass_kg", "source_url", "source_capture"]
        if vehicle_type == "ev":
            required_fields.extend(["curb_mass_kg", "payload_capacity_kg"])
        for field in required_fields:
            if spec.get(field) in (None, ""):
                errors.append(_error("VEHICLE_FIELD_MISSING", f"{vehicle_type}.{field}"))
        if float(spec.get("payload_capacity_kg", 0) or 0) <= 0:
            errors.append(_error("VEHICLE_PAYLOAD_INVALID", vehicle_type))
        capture = REPO / str(spec.get("source_capture", ""))
        if not capture.is_file():
            errors.append(_error("VEHICLE_SOURCE_CAPTURE_MISSING", str(capture)))
    ev = vehicles.get("ev", {})
    cv = vehicles.get("cv", {})
    if (
        cv.get("configuration") != "官方第一配置列G12J8/G12K8，厢式货箱"
        or cv.get("curb_mass_kg") != 2565
        or cv.get("payload_capacity_kg") != 1735
        or cv.get("gross_mass_kg") != 4495
        or cv.get("box_internal_width_mm") != 2100
        or cv.get("box_internal_height_mm") != 2200
        or cv.get("selection_status") != "SELECTED_OFFICIAL_FIRST_COLUMN_BOX_BODY_CHAIN"
    ):
        errors.append(_error("CV_BOX_BODY_CHAIN_MISMATCH", repr(cv)))
    if (
        ev.get("configuration") != "厢式上装，宁德时代140.41kWh电池"
        or ev.get("curb_mass_kg") != 3300
        or ev.get("payload_capacity_kg") != 1000
        or ev.get("battery_kwh") != 140.41
    ):
        errors.append(_error("F1_EV_BOX_BODY_CHAIN_MISMATCH", repr(ev)))
    expected_variants = {
        (140.41, 75, 167, 400, ">"),
        (165.15, 92, 200, 500, ">"),
    }
    observed_variants = {
        (
            row.get("battery_kwh"),
            row.get("motor_rated_power_kw"),
            row.get("motor_peak_power_kw"),
            row.get("official_range_claim_km"),
            row.get("official_range_claim_operator"),
        )
        for row in ev.get("official_configuration_variants", [])
        if isinstance(row, dict)
    }
    if observed_variants != expected_variants:
        errors.append(_error("F2_EV_MOTOR_RANGE_VARIANTS_MISMATCH", repr(sorted(observed_variants))))
    if set(ev.get("zero_search_validation_gates", {})) != {"cruise_power", "range_energy_scale"}:
        errors.append(_error("F2_ZERO_SEARCH_GATES_MISSING", repr(ev.get("zero_search_validation_gates"))))

    charging = data.get("charging_profiles", {})
    depot_profile = charging.get("depot", {})
    if depot_profile.get("status") != "BLOCKS_FORMAL_SEARCH":
        errors.append(_error("DEPOT_CHARGER_GATE_NOT_EXPLICIT", "depot charging profile must remain blocked until evidenced"))
    public_base = charging.get("public_base", {})
    if public_base.get("source_class") != "SCENARIO_PROXY":
        errors.append(_error("PUBLIC_CHARGER_PROVENANCE_MISSING", "public base profile must identify its scenario boundary"))
    if charging.get("public_dual_gun_sensitivity", {}).get("power_sharing") != "UNSUPPORTED_UNTIL_CORE_SEMANTICS_AUDITED":
        errors.append(_error("DUAL_GUN_SEMANTICS_NOT_BLOCKED", "dual-gun sensitivity would be misinterpreted without sharing semantics"))

    carbon = data.get("carbon_contract", {})
    if carbon.get("slots_per_day") != 48 or carbon.get("realtime_measured_claim_allowed") is not False:
        errors.append(_error("CARBON_PROFILE_CONTRACT_INVALID", "China TVCI must be 48-slot projected data without realtime claim"))

    price = data.get("price_contract", {})
    if price.get("currency") != "CNY" or price.get("tou_slots_per_day") != 48:
        errors.append(_error("PRICE_CONTRACT_INVALID", "CNY and 48-slot TOU are required"))
    if price.get("time_varying_price_in_objective_required") is not True:
        errors.append(_error("TIME_VARYING_PRICE_NOT_REQUIRED", "D3 objective contract is missing"))
    f3 = price.get("f3_pre_registered_row_selection", {})
    legal = f3.get("legal_basis", {})
    if (
        f3.get("status") != "LEGAL_CLASS_RULE_LOCKED_LOCAL_NUMERIC_ROW_GAPS_REMAIN"
        or legal.get("document_number") != "发改价格〔2023〕526号"
    ):
        errors.append(_error("F3_LEGAL_ROW_RULE_MISSING", repr(f3)))
    manifest_relative = legal.get("snapshot_manifest")
    manifest_path = REPO / str(manifest_relative or "")
    if not manifest_relative or not manifest_path.is_file():
        errors.append(_error("F3_LEGAL_SOURCE_SNAPSHOT_MISSING", str(manifest_path)))
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(_error("F3_LEGAL_SOURCE_SNAPSHOT_UNREADABLE", repr(exc)))
        else:
            for item in manifest.get("files", []):
                source_path = REPO / str(item.get("path", ""))
                if not source_path.is_file() or sha256(source_path) != item.get("sha256"):
                    errors.append(_error("F3_LEGAL_SOURCE_HASH_MISMATCH", str(source_path)))

    order_summary = validate_order_contract(data, errors, warnings)
    customer_location_summary = validate_customer_location_contract(data, errors, warnings)
    road_matrix_summary = validate_road_matrix_contract(data, errors, warnings)
    facility_summary = validate_facility_manifest(data, errors, warnings)
    default_date_summary = validate_default_date_decision(data, errors, warnings)

    # This is intentionally a blocker until the protected core is changed in a
    # single audited semantic transition.  The historical British constants
    # are not deleted because old experiments need to remain reproducible.
    prices_text = PRICES.read_text(encoding="utf-8")
    british_markers = ("£/", "UK 2025", "diesel_price = 1.4331", "station_electricity_price = electricity_price")
    found = [marker for marker in british_markers if marker in prices_text]
    if found:
        errors.append(_error("LEGACY_BRITISH_CORE_STILL_ACTIVE", ", ".join(found)))

    if data.get("status") != "FROZEN":
        warnings.append({"code": "CONTRACT_NOT_FROZEN", "detail": str(data.get("status"))})
    return {
        "schema": "resetp.china.parameter-lock.validation.v1",
        "lock": str(LOCK.relative_to(REPO)),
        "formal_search_allowed": False,
        "pass": not errors,
        "errors": errors,
        "warnings": warnings,
        "order_attribute_contract": order_summary,
        "customer_location_contract": customer_location_summary,
        "road_matrix_contract": road_matrix_summary,
        "facility_manifest": facility_summary,
        "default_date_decision": default_date_summary,
        "search_evaluations": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print JSON only")
    args = parser.parse_args()
    result = validate_lock()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
