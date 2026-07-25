#!/usr/bin/env python3
"""Freeze the import-only v2 repair without changing the v1 experiment."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from common import PACKAGE, REPO, read_json, sha256, write_json


V1 = PACKAGE / "g0_registration_v1.json"
V2 = PACKAGE / "g0_registration_v2.json"
V2_CONTRACT = (
    REPO
    / "docs/handoff/e2_resource_slot_pricing_import_repair_v2_20260725.md"
)
V2_SOURCES = (
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/build_registration_v2.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/run_engineering_gate_v2.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/run_g0_v2.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/independent_replay_v2.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/run_release_chain_v2.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/monitor_engineering_v2.json",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/monitor_g0_v2.json",
    "docs/handoff/e2_resource_slot_pricing_import_repair_v2_20260725.md",
)


def main() -> int:
    if V2.exists():
        raise RuntimeError(f"v2 registration already exists: {V2}")
    v1 = read_json(V1)
    payload = deepcopy(v1)
    payload.update(
        {
            "schema": "resetp.resource-slot-pricing-g0-registration.v2",
            "registered_at_utc": datetime.now(timezone.utc).isoformat(),
            "approval_id": "E2-RESOURCE-SLOT-PRICING-IMPORT-REPAIR-V2-029",
            "user_authority": (
                "V2_IMPORT_ONLY_REPAIR_THEN_UNCHANGED_ENGINEERING_AND_G0"
            ),
            "v1_registration": {
                "path": V1.relative_to(REPO).as_posix(),
                "sha256": sha256(V1),
            },
            "v2_contract": {
                "path": V2_CONTRACT.relative_to(REPO).as_posix(),
                "sha256": sha256(V2_CONTRACT),
            },
        }
    )
    payload["source_hashes"].update(
        {relative: sha256(REPO / relative) for relative in V2_SOURCES}
    )
    payload["protected_hashes"].extend(
        [
            {
                "path": V1.relative_to(REPO).as_posix(),
                "sha256": sha256(V1),
            },
            {
                "path": V2_CONTRACT.relative_to(REPO).as_posix(),
                "sha256": sha256(V2_CONTRACT),
            },
        ]
    )
    payload["claim_boundary"] = (
        v1["claim_boundary"]
        + " V2 changes only pre-main module resolution and versioned paths; "
        "all algorithmic and experimental terms are byte-for-byte inherited."
    )
    write_json(V2, payload)
    print(V2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
