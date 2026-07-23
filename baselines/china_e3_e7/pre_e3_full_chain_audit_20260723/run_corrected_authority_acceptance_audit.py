"""Independently accept corrected China81 authorities without running search."""

from __future__ import annotations

import csv
import gc
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[3]
sys.path.insert(0, str(REPO / "solver" / "src"))

from setp_solver.china81 import (  # noqa: E402
    _CITY_RUNTIME_MAPPING,
    load_china81_bundle,
)


OUT = SCRIPT.parent
STATIC = (
    REPO
    / "data/ChinaInstances/"
    "china81_stage2_static_inputs_corrected_v3_20260723"
)
MATRICES = (
    REPO
    / "data/ChinaInstances/"
    "china81_local_directed_matrices_corrected_v10_20260723"
)
PARAMETERS = (
    REPO
    / "data/ChinaInstances/"
    "china81_runtime_parameter_authority_v3_20260723"
)
LOCATIONS = (
    REPO
    / "data/ChinaInstances/"
    "china81_customer_location_assignments_gis_v3_20260723"
)
ORDERS = (
    REPO
    / "data/ChinaInstances/"
    "china81_order_attributes_gis_v2_20260723"
)

AUTHORITIES = (PARAMETERS, LOCATIONS, ORDERS, STATIC, MATRICES)
STATIC_RELATIVE = str(STATIC.relative_to(REPO))
MATRICES_RELATIVE = str(MATRICES.relative_to(REPO))
PARAMETERS_RELATIVE = str(PARAMETERS.relative_to(REPO))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def manifest_entries(payload: dict[str, Any]) -> dict[str, str]:
    for key in ("sha256", "files", "artifacts"):
        value = payload.get(key)
        if isinstance(value, dict):
            return {str(path): str(digest) for path, digest in value.items()}
    raise ValueError("artifact manifest has no supported hash mapping")


def included_files(root: Path) -> set[str]:
    return {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
        and path.suffix != ".tmp"
    }


def audit_authority_hashes() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for root in AUTHORITIES:
        manifest_path = root / "artifact_hashes.json"
        manifest = read_json(manifest_path)
        expected = manifest_entries(manifest)
        observed_files = included_files(root)
        missing = sorted(set(expected) - observed_files)
        unexpected = sorted(observed_files - set(expected))
        mismatches = []
        for relative, expected_hash in sorted(expected.items()):
            path = root / relative
            if path.is_file() and sha256(path) != expected_hash:
                mismatches.append(relative)
        rows.append(
            {
                "check_id": f"HASH-{root.name}",
                "scope": "authority_hashes",
                "status": (
                    "PASS"
                    if not missing and not unexpected and not mismatches
                    else "FAIL"
                ),
                "observed": (
                    f"manifest_files={len(expected)};"
                    f"missing={len(missing)};"
                    f"unexpected={len(unexpected)};"
                    f"mismatch={len(mismatches)}"
                ),
                "expected": "missing=0;unexpected=0;mismatch=0",
                "evidence": str(manifest_path.relative_to(REPO)),
                "details": json.dumps(
                    {
                        "missing": missing,
                        "unexpected": unexpected,
                        "mismatches": mismatches,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    return rows


def audit_bundles() -> list[dict[str, Any]]:
    catalog = read_csv(STATIC / "instance_catalog.csv")
    rows: list[dict[str, Any]] = []
    for catalog_row in sorted(catalog, key=lambda item: item["instance_id"]):
        instance_id = catalog_row["instance_id"]
        bundle = None
        try:
            bundle = load_china81_bundle(
                REPO,
                instance_id,
                static_input_authority=STATIC_RELATIVE,
                road_matrix_authority=MATRICES_RELATIVE,
                runtime_parameter_authority=PARAMETERS_RELATIVE,
            )
            cities = {
                str(node.city)
                for node in bundle.instance.nodes
                if node.city is not None
            }
            profile_city_counts = {
                city: sum(
                    1
                    for profile_row in bundle.time_profile
                    if profile_row["city"] == city
                )
                for city in cities
            }
            expected_price_areas = {
                city: _CITY_RUNTIME_MAPPING[city]["price_area_id"]
                for city in sorted(cities)
            }
            expected_diesel_zones = {
                city: _CITY_RUNTIME_MAPPING[city]["diesel_zone"]
                for city in sorted(cities)
            }
            checks = {
                "static_authority": (
                    bundle.static_input_authority == STATIC_RELATIVE
                ),
                "matrix_authority": (
                    bundle.road_matrix_authority == MATRICES_RELATIVE
                ),
                "parameter_authority": (
                    bundle.runtime_parameter_authority == PARAMETERS_RELATIVE
                ),
                "formal_search_frozen": bundle.formal_search_allowed is False,
                "node_count": (
                    len(bundle.instance.nodes) == int(catalog_row["node_count"])
                ),
                "customer_count": (
                    sum(
                        node.node_type == "c"
                        for node in bundle.instance.nodes
                    )
                    == int(catalog_row["customer_count"])
                ),
                "city_calendar_48_slots": all(
                    count == 48
                    for count in profile_city_counts.values()
                ),
                "price_area_map": (
                    dict(bundle.price_area_by_city) == expected_price_areas
                ),
                "diesel_zone_map": (
                    dict(bundle.diesel_zone_by_city) == expected_diesel_zones
                ),
                "road_profiles": (
                    set(bundle.instance.road_profiles or {}) == {"cv", "ev"}
                ),
            }
            failed = sorted(
                name
                for name, passed in checks.items()
                if not passed
            )
            status = "PASS" if not failed else "FAIL"
            observed = (
                f"nodes={len(bundle.instance.nodes)};"
                f"customers="
                f"{sum(node.node_type == 'c' for node in bundle.instance.nodes)};"
                f"cities={','.join(sorted(cities))};"
                f"failed={','.join(failed)}"
            )
            details: dict[str, Any] = checks
        except Exception as exc:  # noqa: BLE001 - retain every audit failure.
            status = "FAIL"
            observed = f"{type(exc).__name__}: {exc}"
            details = {
                "exception_type": type(exc).__name__,
                "message": str(exc),
            }
        rows.append(
            {
                "check_id": f"BUNDLE-{instance_id}",
                "scope": "corrected_bundle",
                "status": status,
                "observed": observed,
                "expected": (
                    "all explicit-authority and runtime mapping checks pass"
                ),
                "evidence": (
                    f"{STATIC_RELATIVE}/instances/{instance_id}/nodes.csv"
                ),
                "details": json.dumps(
                    details,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
        del bundle
        gc.collect()
    return rows


def write_outputs(rows: list[dict[str, Any]]) -> None:
    csv_path = OUT / "corrected_authority_acceptance.csv"
    fieldnames = (
        "check_id",
        "scope",
        "status",
        "observed",
        "expected",
        "evidence",
        "details",
    )
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    failed = [row["check_id"] for row in rows if row["status"] == "FAIL"]
    payload = {
        "schema": "resetp.pre-e3.corrected-authority-acceptance.v1",
        "script": str(SCRIPT.relative_to(REPO)),
        "script_sha256": sha256(SCRIPT),
        "checks": len(rows),
        "pass": sum(row["status"] == "PASS" for row in rows),
        "fail": len(failed),
        "failed_checks": failed,
        "authorities": {
            "static": STATIC_RELATIVE,
            "matrices": MATRICES_RELATIVE,
            "runtime_parameters": PARAMETERS_RELATIVE,
        },
        "diesel_candidate_values_activated": False,
        "formal_search_allowed": False,
        "search_evaluations": 0,
        "verdict": (
            "PASS_CORRECTED_AUTHORITIES__FORMAL_E3_STILL_HELD"
            if not failed
            else "HALT_CORRECTED_AUTHORITY_ACCEPTANCE"
        ),
    }
    (OUT / "corrected_authority_acceptance_findings.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    rows = audit_authority_hashes()
    rows.extend(audit_bundles())
    write_outputs(rows)
    return 1 if any(row["status"] == "FAIL" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
