#!/usr/bin/env python3
"""Freeze the spawn-only v3 repair without changing v1/v2 evidence."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from common import PACKAGE, REPO, read_json, sha256, write_json


V2 = PACKAGE / "g0_registration_v2.json"
V3 = PACKAGE / "g0_registration_v3.json"
V3_CONTRACT = (
    REPO
    / "docs/handoff/e2_resource_slot_pricing_spawn_repair_v3_20260725.md"
)
V3_SOURCES = (
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/build_registration_v3.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/worker_entry_v3.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/run_engineering_gate_v3.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/run_g0_v3.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/independent_replay_v3.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/run_release_chain_v3.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/monitor_engineering_v3.json",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/monitor_g0_v3.json",
    "docs/handoff/e2_resource_slot_pricing_spawn_repair_v3_20260725.md",
)


def main() -> int:
    if V3.exists():
        raise RuntimeError(f"v3 registration already exists: {V3}")
    v2 = read_json(V2)
    payload = deepcopy(v2)
    payload.update(
        {
            "schema": "resetp.resource-slot-pricing-g0-registration.v3",
            "registered_at_utc": datetime.now(timezone.utc).isoformat(),
            "approval_id": "E2-RESOURCE-SLOT-PRICING-SPAWN-REPAIR-V3-031",
            "user_authority": (
                "V3_SPAWN_ONLY_REPAIR_THEN_UNCHANGED_ENGINEERING_AND_G0"
            ),
            "v2_registration": {
                "path": V2.relative_to(REPO).as_posix(),
                "sha256": sha256(V2),
            },
            "v3_contract": {
                "path": V3_CONTRACT.relative_to(REPO).as_posix(),
                "sha256": sha256(V3_CONTRACT),
            },
        }
    )
    payload["source_hashes"].update(
        {relative: sha256(REPO / relative) for relative in V3_SOURCES}
    )
    payload["protected_hashes"].extend(
        [
            {
                "path": V2.relative_to(REPO).as_posix(),
                "sha256": sha256(V2),
            },
            {
                "path": V3_CONTRACT.relative_to(REPO).as_posix(),
                "sha256": sha256(V3_CONTRACT),
            },
        ]
    )
    payload["claim_boundary"] = (
        v2["claim_boundary"]
        + " V3 changes only spawned-worker importability and adds a "
        "zero-objective six-process deserialization smoke gate before any "
        "real input; all algorithmic and experimental terms are inherited."
    )
    write_json(V3, payload)
    print(V3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
