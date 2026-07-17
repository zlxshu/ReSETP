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
FACILITY_MANIFEST = REPO / "docs/handoff/china_facility_manifest_v2_20260718.json"
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
    if contract.get("status") != "LOCKED_DESIGN_NOT_APPLIED":
        errors.append(_error("ORDER_ATTRIBUTE_STATUS_INVALID", str(contract.get("status"))))
    if contract.get("formal_search_allowed") is not False:
        errors.append(_error("ORDER_ATTRIBUTE_FORMAL_FLAG_INVALID", "must remain false before V2 build"))
    if contract.get("observed_chinese_orders_claim_allowed") is not False:
        errors.append(_error("ORDER_ATTRIBUTE_OBSERVED_CLAIM_INVALID", "synthetic design cannot claim observed orders"))
    variants = contract.get("variants", {})
    if set(variants) != {"01", "02", "03"}:
        errors.append(_error("ORDER_ATTRIBUTE_VARIANTS_INVALID", repr(sorted(variants))))
    mixture = contract.get("demand_mixture", [])
    probabilities = [row.get("probability") for row in mixture if isinstance(row, dict)]
    if len(probabilities) != 3 or not math.isclose(sum(float(value) for value in probabilities), 1.0):
        errors.append(_error("ORDER_ATTRIBUTE_DEMAND_MIXTURE_INVALID", repr(probabilities)))
    maximum_demand = max(
        (row.get("integer_uniform_kg", [0, 0])[1] for row in mixture if isinstance(row, dict)), default=0
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
            "detail": "road-time matrices and verified depot entrances are required before windows can be generated",
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _error(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def validate_facility_manifest(errors: list[dict[str, str]], warnings: list[dict[str, str]]) -> dict[str, Any]:
    """Validate the named-depot candidate layer without accepting it as formal."""

    if not FACILITY_MANIFEST.is_file():
        errors.append(_error("FACILITY_MANIFEST_MISSING", str(FACILITY_MANIFEST)))
        return {"exists": False, "record_count": 0, "pending_records": []}

    try:
        manifest = json.loads(FACILITY_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(_error("FACILITY_MANIFEST_UNREADABLE", repr(exc)))
        return {"exists": True, "record_count": 0, "pending_records": []}

    if manifest.get("formal_search_allowed") is not False:
        errors.append(_error("FACILITY_MANIFEST_FORMAL_FLAG_INVALID", "candidate manifest must not authorize formal search"))
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

    required = (
        "facility_id",
        "city",
        "name_zh",
        "facility_kind",
        "source_url",
        "source_capture",
        "coordinates",
        "osm_or_operator_id",
        "operator_or_owner",
        "operating_status",
        "selection_reason",
    )
    pending_records: list[str] = []
    preferred_site_count = 0
    seen_ids: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(_error("FACILITY_RECORD_INVALID", f"index={index}"))
            continue
        facility_id = str(record.get("facility_id") or f"index-{index}")
        if facility_id in seen_ids:
            errors.append(_error("FACILITY_ID_DUPLICATE", facility_id))
        seen_ids.add(facility_id)
        for field in required:
            if field not in record or record.get(field) in ("", {}):
                errors.append(_error("FACILITY_FIELD_MISSING", f"{facility_id}.{field}"))
        source_url = record.get("source_url")
        if not isinstance(source_url, str) or not source_url.startswith("https://"):
            errors.append(_error("FACILITY_SOURCE_URL_INVALID", facility_id))
        capture = record.get("source_capture")
        if capture in (None, ""):
            errors.append(_error("FACILITY_SOURCE_CAPTURE_PENDING", facility_id))
        else:
            capture_path = REPO / str(capture)
            if not capture_path.is_file():
                errors.append(_error("FACILITY_SOURCE_CAPTURE_MISSING", str(capture_path)))
            elif record.get("source_capture_sha256") in (None, ""):
                errors.append(_error("FACILITY_SOURCE_CAPTURE_HASH_MISSING", facility_id))
            elif sha256(capture_path) != str(record["source_capture_sha256"]):
                errors.append(_error("FACILITY_SOURCE_CAPTURE_HASH_MISMATCH", facility_id))
        coordinates = record.get("coordinates")
        latitude = coordinates.get("latitude") if isinstance(coordinates, dict) else None
        longitude = coordinates.get("longitude") if isinstance(coordinates, dict) else None
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (latitude, longitude)):
            errors.append(_error("FACILITY_COORDINATES_PENDING", facility_id))
        if record.get("osm_or_operator_id") in (None, ""):
            errors.append(_error("FACILITY_MAP_OR_OPERATOR_ID_PENDING", facility_id))
        preferred = record.get("preferred_operational_site")
        if not isinstance(preferred, dict):
            errors.append(_error("FACILITY_PREFERRED_SITE_PENDING", facility_id))
        else:
            preferred_site_count += 1
            city = str(record.get("city"))
            expected_uid = EXPECTED_PREFERRED_MAP_UIDS.get(city)
            if preferred.get("map_uid") != expected_uid:
                errors.append(
                    _error(
                        "FACILITY_PREFERRED_SITE_CITY_MISMATCH",
                        f"{city}: expected map_uid={expected_uid}, observed={preferred.get('map_uid')}",
                    )
                )
            raw_coordinate = preferred.get("map_coordinate_original")
            if not isinstance(raw_coordinate, dict) or raw_coordinate.get("crs") != "BD09MC":
                errors.append(_error("FACILITY_PREFERRED_SITE_CRS_INVALID", facility_id))
            else:
                x = raw_coordinate.get("x")
                y = raw_coordinate.get("y")
                if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (x, y)):
                    errors.append(_error("FACILITY_PREFERRED_SITE_COORDINATE_INVALID", facility_id))
                # BD-09MC is a projected metre coordinate.  Values in this
                # range must never be accepted as WGS84 latitude/longitude.
                if isinstance(x, (int, float)) and isinstance(y, (int, float)) and abs(x) <= 180 and abs(y) <= 90:
                    errors.append(_error("FACILITY_PREFERRED_SITE_CRS_RANGE_SUSPICIOUS", facility_id))
            sources = preferred.get("official_operation_sources")
            if not isinstance(sources, list) or not sources or not all(
                isinstance(url, str) and url.startswith("https://") for url in sources
            ):
                errors.append(_error("FACILITY_OPERATION_SOURCE_INVALID", facility_id))
            if preferred.get("evidence_scope") in (None, ""):
                errors.append(_error("FACILITY_PREFERRED_SITE_SCOPE_MISSING", facility_id))
        if record.get("operator_or_owner") in (None, ""):
            errors.append(_error("FACILITY_OPERATOR_PENDING", facility_id))
        if "PENDING" in str(record.get("operating_status", "")):
            pending_records.append(facility_id)

    if pending_records:
        warnings.append(
            {
                "code": "FACILITY_MANIFEST_NOT_FORMAL",
                "detail": f"{len(pending_records)} records still require coordinate/operation verification",
            }
        )
    if preferred_site_count == len(EXPECTED_CITIES):
        warnings.append(
            {
                "code": "FACILITY_ENTRANCE_CANDIDATES_ONLY",
                "detail": "9/9 cities have map-identified operational-site candidates, but raw BD09MC coordinates are not formal WGS84 depot coordinates",
            }
        )
    return {
        "exists": True,
        "record_count": len(records),
        "cities": sorted(set(cities)),
        "pending_records": pending_records,
        "preferred_site_count": preferred_site_count,
        "preferred_coordinate_crs": "BD09MC",
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
        for field in ("model", "gross_mass_kg", "curb_mass_kg", "payload_capacity_kg", "source_url", "source_capture"):
            if spec.get(field) in (None, ""):
                errors.append(_error("VEHICLE_FIELD_MISSING", f"{vehicle_type}.{field}"))
        if float(spec.get("payload_capacity_kg", 0) or 0) <= 0:
            errors.append(_error("VEHICLE_PAYLOAD_INVALID", vehicle_type))
        capture = REPO / str(spec.get("source_capture", ""))
        if not capture.is_file():
            errors.append(_error("VEHICLE_SOURCE_CAPTURE_MISSING", str(capture)))

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

    order_summary = validate_order_contract(data, errors, warnings)
    facility_summary = validate_facility_manifest(errors, warnings)

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
        "facility_manifest": facility_summary,
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
