#!/usr/bin/env python3
"""Freeze the route-column MIP G0 before execution."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
REGISTRATION = PACKAGE / "g0_registration_v1.json"
RC_REGISTRATION = (
    REPO
    / "baselines/algorithm_prototypes/resource_constrained_ev_split_20260725"
    / "g0_registration_v2.json"
)
SOURCE_PATHS = (
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/__init__.py",
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/build_g0_registration.py",
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/china81_columns.py",
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/mip_core.py",
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/run_g0.py",
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/test_mip_core.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/contracts.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/decoder_cache.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/fleet_assignment_dp.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/reference_decoder.py",
    "docs/handoff/e2_route_column_mip_contract_20260725.md",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/china81.py",
    "solver/src/setp_solver/china81_completion.py",
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/prices.py",
    "solver/src/setp_solver/search/evaluation.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    if REGISTRATION.exists():
        raise RuntimeError(f"registration already exists: {REGISTRATION}")
    upstream = json.loads(RC_REGISTRATION.read_text(encoding="utf-8"))
    write_json(
        REGISTRATION,
        {
            "schema": "resetp.route-column-mip-g0-registration.v1",
            "status": "FROZEN_BEFORE_EXECUTION",
            "registered_at_utc": datetime.now(timezone.utc).isoformat(),
            "approval_id": "E2-ROUTE-COLUMN-MIP-016",
            "contract_id": "E2-RC-MIP-ASSEMBLY-001",
            "config": {
                "workers": 3,
                "mip_time_limit_seconds": 10.0,
                "max_route_columns": 50_000,
                "max_peak_rss_gib": 4.0,
                "order_perturbations": 0,
            },
            "inputs": upstream["inputs"],
            "authority_registration": upstream[
                "authority_registration"
            ],
            "upstream_engineering_registration": {
                "path": RC_REGISTRATION.relative_to(REPO).as_posix(),
                "sha256": sha256(RC_REGISTRATION),
            },
            "source_hashes": {
                relative: sha256(REPO / relative)
                for relative in SOURCE_PATHS
            },
            "claim_boundary": (
                "Route-column and capacity-aware MIP engineering gate "
                "only; no algorithm-performance, HGS integration, paper, "
                "E3, BKS, SOTA, or hybrid claim."
            ),
        },
    )
    print(json.dumps({"registration": str(REGISTRATION)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
