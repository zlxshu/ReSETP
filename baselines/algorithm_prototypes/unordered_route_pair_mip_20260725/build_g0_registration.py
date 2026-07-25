#!/usr/bin/env python3
"""Freeze the unordered route-pair MIP engineering gate."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
REGISTRATION = PACKAGE / "g0_registration_v1.json"
AUTHORITY = (
    REPO
    / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724"
    / "g0_real_bundle_preregistration_v1.json"
)
WITNESS = (
    REPO
    / "baselines/algorithm_prototypes/route_column_mip_assembly_20260725"
    / "g0_gate_v1/witnesses/cn-jjj-15c-01-V2-LOCATIONS.json"
)
SOURCE_PATHS = (
    "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/__init__.py",
    "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/build_g0_registration.py",
    "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/pair_core.py",
    "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/pair_mip.py",
    "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/run_g0.py",
    "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/test_pair_mip.py",
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/china81_columns.py",
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/mip_core.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/decoder_cache.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/fleet_assignment_dp.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/reference_decoder.py",
    "docs/handoff/e2_unordered_route_pair_resplit_contract_20260725.md",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/china81.py",
    "solver/src/setp_solver/china81_completion.py",
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/prices.py",
    "solver/src/setp_solver/search/evaluation.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if REGISTRATION.exists():
        raise RuntimeError(f"registration already exists: {REGISTRATION}")
    upstream = json.loads(AUTHORITY.read_text(encoding="utf-8"))
    payload = {
        "schema": "resetp.unordered-route-pair-g0-registration.v1",
        "status": "FROZEN_BEFORE_EXECUTION",
        "registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "approval_id": "E2-UNORDERED-ROUTE-PAIR-MIP-019",
        "contract_id": "E2-URP-MIP-001",
        "config": {
            "instance_id": "cn-jjj-15c-01-V2-LOCATIONS",
            "route_pair_indices": [0, 2],
            "mip_time_limit_seconds": 2.0,
            "max_pair_columns": 5000,
        },
        "expected_objective": 890.1851758129094,
        "witness": {
            "path": WITNESS.relative_to(REPO).as_posix(),
            "sha256": sha256(WITNESS),
        },
        "authority_registration": {
            "path": AUTHORITY.relative_to(REPO).as_posix(),
            "sha256": sha256(AUTHORITY),
        },
        "authority": upstream["authorities"],
        "scenario_date": upstream["scenario_date"],
        "source_hashes": {
            relative: sha256(REPO / relative) for relative in SOURCE_PATHS
        },
        "claim_boundary": (
            "Engineering and resource-residual closure only; no performance, "
            "independent algorithm B, hybrid, paper, E3, BKS, or SOTA claim."
        ),
    }
    REGISTRATION.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"registration": str(REGISTRATION)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
