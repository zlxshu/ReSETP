#!/usr/bin/env python3
"""Freeze fresh direct-gate instance IDs without reading algorithm results."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
OUTPUT = PACKAGE / "direct_input_selection_v1.json"
MANIFEST_ROOT = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / "corrected_china81_rerun_v7_small_archive_ledger_20260724"
    / "full_witness_replay/input_manifests"
)

# Strata were fixed before any candidate objective was read.
STRATA = (
    ("jjj", 25),
    ("prd", 100),
    ("cy", 200),
)

# Every instance previously used to design, debug, or illustrate an E2
# prototype is excluded.  This list is part of the frozen selection rule.
EXCLUDED = {
    "cn-cy-25c-01-V2-LOCATIONS",
    "cn-prd-75c-01-V2-LOCATIONS",
    "cn-cy-200c-01-V2-LOCATIONS",
    "cn-jjj-50c-02-V2-LOCATIONS",
    "cn-cy-100c-01-V2-LOCATIONS",
    "cn-prd-200c-02-V2-LOCATIONS",
    "cn-jjj-15c-01-V2-LOCATIONS",
    "cn-prd-75c-03-V2-LOCATIONS",
    "cn-cy-150c-01-V2-LOCATIONS",
    "cn-cy-50c-03-V2-LOCATIONS",
    "cn-jjj-100c-03-V2-LOCATIONS",
    "cn-prd-150c-03-V2-LOCATIONS",
    "cn-prd-50c-01-V2-LOCATIONS",
}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"selection already exists: {OUTPUT}")
    available = {path.stem for path in MANIFEST_ROOT.glob("cn-*-V2-LOCATIONS.json")}
    selected: list[dict[str, object]] = []
    for region, customer_count in STRATA:
        prefix = f"cn-{region}-{customer_count}c-"
        candidates = sorted(
            (
                instance_id
                for instance_id in available
                if instance_id.startswith(prefix) and instance_id not in EXCLUDED
            ),
            key=lambda instance_id: (
                sha256_text(instance_id),
                instance_id,
            ),
        )
        if not candidates:
            raise RuntimeError(f"no fresh candidate for {region}/{customer_count}")
        selected.append(
            {
                "region": region,
                "customer_count": customer_count,
                "instance_id": candidates[0],
                "selection_digest": sha256_text(candidates[0]),
                "eligible_instance_ids": sorted(candidates),
            }
        )
    payload = {
        "schema": "resetp.route-column-mip-direct-input-selection.v1",
        "status": "FROZEN_BEFORE_OBJECTIVE_ACCESS",
        "registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection_rule": (
            "For each pre-fixed region/customer-count stratum, exclude every "
            "instance used by prior E2 prototypes, then choose the eligible "
            "instance with the lexicographically smallest SHA-256(instance_id); "
            "algorithm objectives are not read."
        ),
        "strata": [
            {"region": region, "customer_count": count} for region, count in STRATA
        ],
        "excluded_instance_ids": sorted(EXCLUDED),
        "selected": selected,
    }
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["selected"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
