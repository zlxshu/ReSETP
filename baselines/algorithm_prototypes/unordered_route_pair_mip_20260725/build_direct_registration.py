#!/usr/bin/env python3
"""Freeze the unordered route-pair fresh direct headroom gate."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
SELECTION = PACKAGE / "input_selection_v2.json"
INVALID_SELECTION = PACKAGE / "input_selection_v1.json"
G0_DECISION = PACKAGE / "g0_gate_v2/decision.json"
G0_HASHES = PACKAGE / "g0_gate_v2/artifact_hashes.json"
G0_REGISTRATION = PACKAGE / "g0_registration_v2.json"
REGISTRATION = PACKAGE / "direct_registration_v1.json"
V7_ROOT = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / "corrected_china81_rerun_v7_small_archive_ledger_20260724"
    / "full_gate"
)
RAW = V7_ROOT / "raw_runs.csv"
SOURCE_PATHS = (
    "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/__init__.py",
    "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/build_direct_registration.py",
    "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/build_input_selection.py",
    "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/build_input_selection_v2.py",
    "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/pair_core.py",
    "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/pair_mip.py",
    "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/run_direct_gate.py",
    "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/test_pair_mip.py",
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/china81_columns.py",
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/mip_core.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/contracts.py",
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
    g0 = json.loads(G0_DECISION.read_text(encoding="utf-8"))
    if g0["verdict"] != "PASS_URP_MIP_G0_ENGINEERING":
        raise RuntimeError("engineering gate has not passed")
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
        parents = sorted(
            grouped[selected["instance_id"]],
            key=lambda row: row["seed"],
        )
        if [row["seed"] for row in parents] != [1, 2, 3, 4, 5]:
            raise RuntimeError(f"incomplete parents: {selected['instance_id']}")
        inputs.append(
            {
                "instance_id": selected["instance_id"],
                "region": selected["region"],
                "customer_count": selected["customer_count"],
                "parents": parents,
            }
        )
    g0_registration = json.loads(G0_REGISTRATION.read_text(encoding="utf-8"))
    write_json(
        REGISTRATION,
        {
            "schema": "resetp.unordered-route-pair-direct-registration.v1",
            "status": "FROZEN_BEFORE_EXECUTION",
            "registered_at_utc": datetime.now(timezone.utc).isoformat(),
            "approval_id": "E2-UNORDERED-ROUTE-PAIR-MIP-019",
            "contract_id": "E2-URP-MIP-001",
            "selection": {
                "path": SELECTION.relative_to(REPO).as_posix(),
                "sha256": sha256(SELECTION),
            },
            "invalid_selection_preserved": {
                "path": INVALID_SELECTION.relative_to(REPO).as_posix(),
                "sha256": sha256(INVALID_SELECTION),
            },
            "g0": {
                "decision_path": G0_DECISION.relative_to(REPO).as_posix(),
                "decision_sha256": sha256(G0_DECISION),
                "artifact_hashes_path": G0_HASHES.relative_to(REPO).as_posix(),
                "artifact_hashes_sha256": sha256(G0_HASHES),
            },
            "config": {
                "workers": 3,
                "pair_mip_time_limit_seconds": 2.0,
                "instance_wallclock_safety_seconds": 1200.0,
                "max_pair_columns": 5000,
                "strict_improvement_absolute_tolerance": 1.0e-6,
                "required_improving_instances": 2,
                "pass_requires_nonadjacent_parent_pair": True,
                "search_passes_per_start": 1,
            },
            "inputs": inputs,
            "authority_registration": g0_registration["authority_registration"],
            "source_hashes": {
                relative: sha256(REPO / relative) for relative in SOURCE_PATHS
            },
            "claim_boundary": (
                "Fresh direct headroom of one exact unordered-route-pair "
                "best-improvement pass only. PASS authorizes development of "
                "standalone algorithm B; no paper, E3, formal China81, BKS, "
                "SOTA, hybrid, or 1+1>2 claim."
            ),
        },
    )
    print(json.dumps({"registration": str(REGISTRATION)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
