#!/usr/bin/env python3
"""Freeze fresh route-pair gate instances without reading objectives."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
OUTPUT = PACKAGE / "input_selection_v1.json"
MANIFEST_ROOT = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / "corrected_china81_rerun_v7_small_archive_ledger_20260724"
    / "full_witness_replay/input_manifests"
)
STRATA = (("jjj", 50), ("prd", 100), ("cy", 150))
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
    "cn-jjj-25c-01-V2-LOCATIONS",
    "cn-prd-100c-03-V2-LOCATIONS",
    "cn-cy-200c-03-V2-LOCATIONS",
}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"selection already exists: {OUTPUT}")
    available = {path.stem for path in MANIFEST_ROOT.glob("*.json")}
    selected = []
    for region, customer_count in STRATA:
        prefix = f"cn-{region}-{customer_count}c-"
        eligible = sorted(
            (
                instance_id
                for instance_id in available
                if instance_id.startswith(prefix) and instance_id not in EXCLUDED
            ),
            key=lambda instance_id: (digest(instance_id), instance_id),
        )
        if not eligible:
            raise RuntimeError(f"no fresh input for {region}/{customer_count}")
        selected.append(
            {
                "region": region,
                "customer_count": customer_count,
                "instance_id": eligible[0],
                "selection_digest": digest(eligible[0]),
                "eligible_instance_ids": sorted(eligible),
            }
        )
    payload = {
        "schema": "resetp.unordered-route-pair-input-selection.v1",
        "status": "FROZEN_BEFORE_OBJECTIVE_ACCESS",
        "registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection_rule": (
            "Use pre-fixed 50/100/150-customer strata; exclude every prior "
            "prototype instance; choose the eligible instance with smallest "
            "SHA-256(instance_id), without reading objectives."
        ),
        "excluded_instance_ids": sorted(EXCLUDED),
        "selected": selected,
    }
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(selected, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
