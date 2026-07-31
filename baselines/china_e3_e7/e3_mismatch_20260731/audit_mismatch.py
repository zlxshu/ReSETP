#!/usr/bin/env python3
"""Independently enumerate administrative-versus-road-nearest mismatch."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SOLVER_SRC = REPO / "solver/src"
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))

from setp_solver.china81 import load_china81_bundle  # noqa: E402


STATIC_ROOT = (
    REPO
    / "data/ChinaInstances/"
    "china81_stage2_static_inputs_corrected_v3_20260723"
)
CATALOG = STATIC_ROOT / "instance_catalog.csv"
OUTPUT_DIR = HERE / "input_audit"
TIE_TOLERANCE_M = 1.0e-9


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def read_catalog() -> list[dict[str, str]]:
    with CATALOG.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows = [row for row in rows if not row["instance_id"].startswith("._")]
    if len(rows) != 81 or len({row["instance_id"] for row in rows}) != 81:
        raise RuntimeError(f"HALT_CATALOG_DENOMINATOR:{len(rows)}/81")
    return rows


def audit() -> dict[str, Any]:
    instance_rows: list[dict[str, Any]] = []
    customer_rows: list[dict[str, Any]] = []
    mismatch_rows: list[dict[str, Any]] = []
    total_customers = 0
    multi_depot_instances = 0
    tie_count = 0

    for catalog_row in read_catalog():
        instance_id = catalog_row["instance_id"]
        bundle = load_china81_bundle(
            REPO,
            instance_id,
            static_input_authority=STATIC_ROOT,
        )
        nodes = {node.node_id: node for node in bundle.instance.nodes}
        depots = sorted(
            node.node_id
            for node in bundle.instance.nodes
            if node.node_type.lower() == "d"
        )
        depots_by_city: dict[str, str] = {}
        for depot_id in depots:
            city = str(nodes[depot_id].city).strip().lower()
            if city in depots_by_city:
                raise RuntimeError(
                    f"HALT_MULTIPLE_DEPOTS_PER_CITY:{instance_id}:{city}"
                )
            depots_by_city[city] = depot_id
        if len(depots) > 1:
            multi_depot_instances += 1

        mismatches = 0
        instance_ties = 0
        for customer_id in sorted(bundle.customer_home_depot):
            customer = nodes[customer_id]
            customer_city = str(customer.city).strip().lower()
            administrative_depot = bundle.customer_home_depot[customer_id]
            if depots_by_city.get(customer_city) != administrative_depot:
                raise RuntimeError(
                    "HALT_ADMINISTRATIVE_MAPPING_DRIFT:"
                    f"{instance_id}:{customer_id}"
                )
            distances = {
                depot_id: float(
                    bundle.instance.distance(depot_id, customer_id)
                )
                for depot_id in depots
            }
            minimum_distance = min(distances.values())
            nearest_candidates = sorted(
                depot_id
                for depot_id, distance in distances.items()
                if math.isclose(
                    distance,
                    minimum_distance,
                    rel_tol=0.0,
                    abs_tol=TIE_TOLERANCE_M,
                )
            )
            nearest_depot = nearest_candidates[0]
            tied = len(nearest_candidates) > 1
            mismatch = administrative_depot != nearest_depot
            administrative_distance = distances[administrative_depot]
            saving = administrative_distance - minimum_distance
            row = {
                "instance_id": instance_id,
                "region": catalog_row["region"],
                "customer_count": int(catalog_row["customer_count"]),
                "depot_count": len(depots),
                "customer_id": customer_id,
                "customer_city": customer_city,
                "administrative_depot": administrative_depot,
                "administrative_depot_city": str(
                    nodes[administrative_depot].city
                ).strip().lower(),
                "nearest_depot": nearest_depot,
                "nearest_depot_city": str(
                    nodes[nearest_depot].city
                ).strip().lower(),
                "administrative_distance_m": administrative_distance,
                "nearest_distance_m": minimum_distance,
                "road_distance_saving_m": saving,
                "road_distance_saving_pct_of_administrative": (
                    100.0 * saving / administrative_distance
                    if administrative_distance > 0
                    else 0.0
                ),
                "nearest_tie": tied,
                "nearest_tie_candidates": "|".join(nearest_candidates),
                "mismatch": mismatch,
                "cause": (
                    "same-city administrative depot is not the directed-road "
                    "nearest depot"
                    if mismatch
                    else "same-city administrative depot is road-nearest"
                ),
                "all_directed_depot_to_customer_distances_m": json.dumps(
                    distances,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
            customer_rows.append(row)
            if tied:
                instance_ties += 1
                tie_count += 1
            if mismatch:
                mismatches += 1
                mismatch_rows.append(row)

        expected = int(catalog_row["customer_count"])
        if len(bundle.customer_home_depot) != expected:
            raise RuntimeError(
                f"HALT_CUSTOMER_DENOMINATOR:{instance_id}:"
                f"{len(bundle.customer_home_depot)}/{expected}"
            )
        total_customers += expected
        instance_rows.append(
            {
                "instance_id": instance_id,
                "region": catalog_row["region"],
                "customer_count": expected,
                "depot_count": len(depots),
                "mismatch_customer_count": mismatches,
                "mismatch_rate_pct": 100.0 * mismatches / expected,
                "nearest_tie_count": instance_ties,
                "administrative_assignment_rule":
                    "customer city -> unique same-city depot",
                "nearest_assignment_rule":
                    "minimum directed depot-to-customer CV road distance",
            }
        )
        print(
            "AUDIT_INSTANCE "
            f"instance={instance_id} customers={expected} "
            f"mismatches={mismatches} ties={instance_ties}",
            flush=True,
        )

    nonzero = [
        row for row in instance_rows
        if int(row["mismatch_customer_count"]) > 0
    ]
    if total_customers != 5805:
        raise RuntimeError(
            f"HALT_GLOBAL_CUSTOMER_DENOMINATOR:{total_customers}/5805"
        )
    if multi_depot_instances != 45:
        raise RuntimeError(
            f"HALT_MULTI_DEPOT_DENOMINATOR:{multi_depot_instances}/45"
        )
    if tie_count:
        raise RuntimeError(f"HALT_NEAREST_DISTANCE_TIES:{tie_count}")

    atomic_csv(OUTPUT_DIR / "all_instances.csv", instance_rows)
    atomic_csv(OUTPUT_DIR / "all_customers.csv", customer_rows)
    atomic_csv(OUTPUT_DIR / "mismatched_customers.csv", mismatch_rows)
    summary = {
        "schema": "resetp.e3-mismatch.input-audit.v1",
        "status": "PASS_COMPLETE_81_INSTANCE_ENUMERATION",
        "created_at_utc": now_iso(),
        "instances_checked": len(instance_rows),
        "customers_checked": total_customers,
        "multi_depot_instances": multi_depot_instances,
        "single_depot_instances": len(instance_rows) - multi_depot_instances,
        "nearest_distance_ties": tie_count,
        "nonzero_mismatch_instances_found": len(nonzero),
        "mismatched_customers_total": len(mismatch_rows),
        "global_mismatch_rate_pct": 100.0 * len(mismatch_rows) / total_customers,
        "nonzero_instances": nonzero,
        "rules": {
            "administrative":
                "loader customer_home_depot; customer city to unique same-city depot",
            "nearest":
                "minimum directed CV road distance from depot to customer",
            "tie_break": "depot id, with ties separately detected at 1e-9 m",
        },
        "authorities": {
            "catalog": str(CATALOG.relative_to(REPO)),
            "static_input": str(STATIC_ROOT.relative_to(REPO)),
            "loader": "solver/src/setp_solver/china81.py",
        },
    }
    atomic_json(OUTPUT_DIR / "summary.json", summary)
    hashes = {
        str(path.relative_to(HERE)): sha256_path(path)
        for path in sorted(OUTPUT_DIR.glob("*"))
        if path.is_file()
        and not path.name.startswith("._")
        and path.name != "hashes.json"
    }
    atomic_json(
        OUTPUT_DIR / "hashes.json",
        {
            "schema": "resetp.e3-mismatch.input-audit-hashes.v1",
            "created_at_utc": now_iso(),
            "files": hashes,
        },
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("audit",),
    )
    args = parser.parse_args()
    if args.command == "audit":
        summary = audit()
        print(
            "AUDIT_COMPLETE "
            f"instances={summary['instances_checked']} "
            f"nonzero={summary['nonzero_mismatch_instances_found']} "
            f"mismatched_customers={summary['mismatched_customers_total']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
