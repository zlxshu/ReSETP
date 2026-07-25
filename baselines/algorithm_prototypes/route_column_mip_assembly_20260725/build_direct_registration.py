#!/usr/bin/env python3
"""Freeze the fresh five-parent route-column direct headroom gate."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
SELECTION = PACKAGE / "direct_input_selection_v1.json"
REGISTRATION = PACKAGE / "direct_gate_registration_v1.json"
G0_REGISTRATION = PACKAGE / "g0_registration_v1.json"
V7_ROOT = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / "corrected_china81_rerun_v7_small_archive_ledger_20260724"
    / "full_gate"
)
RAW = V7_ROOT / "raw_runs.csv"

SOURCE_PATHS = (
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/__init__.py",
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/build_direct_input_selection.py",
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/build_direct_registration.py",
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/china81_columns.py",
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/direct_gate_support.py",
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/mip_core.py",
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/run_direct_gate.py",
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/test_direct_gate_support.py",
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
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    if REGISTRATION.exists():
        raise RuntimeError(f"registration already exists: {REGISTRATION}")
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    if selection["status"] != "FROZEN_BEFORE_OBJECTIVE_ACCESS":
        raise RuntimeError("input selection is not frozen")
    instance_ids = {row["instance_id"] for row in selection["selected"]}
    with RAW.open(encoding="utf-8", newline="") as handle:
        rows = [
            row for row in csv.DictReader(handle) if row["instance_id"] in instance_ids
        ]
    grouped: dict[str, list[dict[str, Any]]] = {
        instance_id: [] for instance_id in instance_ids
    }
    for row in rows:
        witness_path = V7_ROOT / "tasks" / row["task_id"] / "solution_witnesses.json"
        grouped[row["instance_id"]].append(
            {
                "seed": int(row["seed"]),
                "task_id": row["task_id"],
                "expected_objective": float(row["MV-HGS-SP_cost"]),
                "witness_key": "MV-HGS-SP",
                "witness_path": witness_path.relative_to(REPO).as_posix(),
                "witness_sha256": sha256(witness_path),
            }
        )
    inputs = []
    for selected in selection["selected"]:
        instance_id = selected["instance_id"]
        parents = sorted(grouped[instance_id], key=lambda row: row["seed"])
        if [row["seed"] for row in parents] != [1, 2, 3, 4, 5]:
            raise RuntimeError(f"incomplete five-parent set: {instance_id}")
        inputs.append(
            {
                "instance_id": instance_id,
                "region": selected["region"],
                "customer_count": selected["customer_count"],
                "parents": parents,
            }
        )
    g0 = json.loads(G0_REGISTRATION.read_text(encoding="utf-8"))
    write_json(
        REGISTRATION,
        {
            "schema": "resetp.route-column-mip-direct-registration.v1",
            "status": "FROZEN_BEFORE_EXECUTION",
            "registered_at_utc": datetime.now(timezone.utc).isoformat(),
            "approval_id": "E2-ROUTE-COLUMN-MIP-G0-017",
            "contract_id": "E2-RC-MIP-ASSEMBLY-001",
            "selection": {
                "path": SELECTION.relative_to(REPO).as_posix(),
                "sha256": sha256(SELECTION),
            },
            "config": {
                "workers": 3,
                "mip_time_limit_seconds": 10.0,
                "max_route_columns": 50_000,
                "strict_improvement_absolute_tolerance": 1.0e-6,
                "required_improving_instances": 2,
            },
            "inputs": inputs,
            "authority_registration": g0["authority_registration"],
            "upstream_g0_registration": {
                "path": G0_REGISTRATION.relative_to(REPO).as_posix(),
                "sha256": sha256(G0_REGISTRATION),
            },
            "source_hashes": {
                relative: sha256(REPO / relative) for relative in SOURCE_PATHS
            },
            "claim_boundary": (
                "Fresh direct headroom gate only. A PASS authorizes design "
                "of an HGS integration gate; it does not authorize paper, "
                "E3, full China81, BKS, SOTA, or genuine-hybrid claims."
            ),
        },
    )
    print(json.dumps({"registration": str(REGISTRATION)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
