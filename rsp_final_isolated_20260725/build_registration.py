"""Freeze the isolated final engineering correction without changing G0 terms."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from . import runtime


V3 = (
    runtime.REPO
    / "baselines/algorithm_prototypes/resource_slot_pricing_20260725"
    / "g0_registration_v3.json"
)
V4 = runtime.REGISTRATION
CONTRACT = (
    runtime.REPO
    / "docs/handoff/e2_resource_slot_pricing_isolated_final_v4_20260725.md"
)
SOURCES = (
    "rsp_final_isolated_20260725/__init__.py",
    "rsp_final_isolated_20260725/runtime.py",
    "rsp_final_isolated_20260725/frozen_loader.py",
    "rsp_final_isolated_20260725/workers.py",
    "rsp_final_isolated_20260725/engineering.py",
    "rsp_final_isolated_20260725/g0.py",
    "rsp_final_isolated_20260725/replay.py",
    "rsp_final_isolated_20260725/release.py",
    "rsp_final_isolated_20260725/build_registration.py",
    "rsp_final_isolated_20260725/monitor_engineering_v4.json",
    "rsp_final_isolated_20260725/monitor_g0_v4.json",
    "docs/handoff/e2_resource_slot_pricing_isolated_final_v4_20260725.md",
)
PRESERVED = (
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/engineering_gate_v1/artifact_hashes.json",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/engineering_gate_v2/artifact_hashes.json",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/engineering_gate_v3/artifact_hashes.json",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/g0_gate_v3/artifact_hashes.json",
)


def main() -> int:
    if V4.exists():
        raise RuntimeError(f"v4 registration already exists: {V4}")
    v3 = runtime.read_json(V3)
    payload = deepcopy(v3)
    payload.update(
        {
            "schema": "resetp.resource-slot-pricing-g0-registration.v4",
            "registered_at_utc": datetime.now(timezone.utc).isoformat(),
            "approval_id": "E2-RESOURCE-SLOT-PRICING-ISOLATED-FINAL-V4-032",
            "user_authority": "FINAL_ROOT_CAUSE_PACKAGE_ISOLATION_THEN_UNCHANGED_G0",
            "v3_registration": {
                "path": V3.relative_to(runtime.REPO).as_posix(),
                "sha256": runtime.sha256(V3),
            },
            "v4_contract": {
                "path": CONTRACT.relative_to(runtime.REPO).as_posix(),
                "sha256": runtime.sha256(CONTRACT),
            },
        }
    )
    payload["source_hashes"].update(
        {relative: runtime.sha256(runtime.REPO / relative) for relative in SOURCES}
    )
    payload["protected_hashes"].extend(
        [
            {
                "path": V3.relative_to(runtime.REPO).as_posix(),
                "sha256": runtime.sha256(V3),
            },
            *[
                {"path": relative, "sha256": runtime.sha256(runtime.REPO / relative)}
                for relative in PRESERVED
            ],
            {
                "path": CONTRACT.relative_to(runtime.REPO).as_posix(),
                "sha256": runtime.sha256(CONTRACT),
            },
        ]
    )
    payload["claim_boundary"] = (
        v3["claim_boundary"]
        + " V4 changes only import isolation: all spawned work enters through a "
        "unique importable package, exact dependency files are fail-closed, and "
        "six workers report runner identity before any real input. Algorithmic "
        "and experimental terms are unchanged."
    )
    runtime.write_json(V4, payload)
    print(V4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

