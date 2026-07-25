#!/usr/bin/env python3
"""Freeze the result-blind G0 inputs and source hashes before execution."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
REGISTRATION = PACKAGE / "g0_registration_v1.json"
V7 = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / "corrected_china81_rerun_v7_small_archive_ledger_20260724"
    / "full_gate"
)
SELECTED_STRATA = (
    ("jjj", 50),
    ("cy", 100),
    ("prd", 200),
)
EXPECTED_IDS = (
    "cn-jjj-50c-02-V2-LOCATIONS",
    "cn-cy-100c-01-V2-LOCATIONS",
    "cn-prd-200c-02-V2-LOCATIONS",
)
SOURCE_PATHS = (
    "baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/__init__.py",
    "baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/build_g0_registration.py",
    "baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/ejection_rebuild.py",
    "baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/feasible_moves.py",
    "baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/fge_vnd.py",
    "baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/run_g0.py",
    "baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/test_feasible_moves.py",
    "baselines/algorithm_prototypes/tailored_dp_vns_20260725/neighborhoods.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/contracts.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/decoder_cache.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/fleet_assignment_dp.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/reference_decoder.py",
    "docs/handoff/e2_feasibility_guided_vns_contract_20260725.md",
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


def selected_ids(all_ids: set[str]) -> tuple[str, ...]:
    output: list[str] = []
    for family, size in SELECTED_STRATA:
        pool = sorted(
            instance_id
            for instance_id in all_ids
            if f"cn-{family}-{size}c-" in instance_id
        )
        if len(pool) != 3:
            raise RuntimeError(
                f"unexpected stratum cardinality {family}/{size}: {pool}"
            )
        output.append(
            min(
                pool,
                key=lambda value: (
                    hashlib.sha256(value.encode("utf-8")).hexdigest(),
                    value,
                ),
            )
        )
    return tuple(output)


def main() -> int:
    if REGISTRATION.exists():
        raise RuntimeError(f"registration already exists: {REGISTRATION}")
    raw_path = V7 / "raw_runs.csv"
    with raw_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    chosen = selected_ids({row["instance_id"] for row in rows})
    if chosen != EXPECTED_IDS:
        raise RuntimeError(f"result-blind instance selection drift: {chosen}")

    inputs: list[dict[str, Any]] = []
    for instance_id in chosen:
        instance_rows = [
            row for row in rows if row["instance_id"] == instance_id
        ]
        winner = min(
            instance_rows,
            key=lambda row: (
                float(row["MV-HGS-SP_cost"]),
                int(row["seed"]),
            ),
        )
        witness_path = (
            V7
            / "tasks"
            / winner["task_id"]
            / "solution_witnesses.json"
        )
        inputs.append(
            {
                "instance_id": instance_id,
                "instance_id_sha256": hashlib.sha256(
                    instance_id.encode("utf-8")
                ).hexdigest(),
                "seed": int(winner["seed"]),
                "task_id": winner["task_id"],
                "witness_key": "MV-HGS-SP",
                "expected_objective": float(winner["MV-HGS-SP_cost"]),
                "witness_path": witness_path.relative_to(REPO).as_posix(),
                "witness_sha256": sha256(witness_path),
            }
        )

    source_hashes = {
        relative: sha256(REPO / relative)
        for relative in SOURCE_PATHS
    }
    payload = {
        "schema": "resetp.fge-vns-g0-registration.v1",
        "status": "FROZEN_BEFORE_EXECUTION",
        "registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "approval_id": "E2-FEASIBILITY-GUIDED-VNS-011",
        "contract_id": "E2-FEASIBILITY-GUIDED-VNS-001",
        "selection_rule": (
            "fixed family-size strata, minimum SHA-256(instance_id); "
            "then strongest sealed v7 MV-HGS-SP witness with seed tie-break"
        ),
        "candidate_complete_objective_evaluations": 0,
        "config": {
            "inspection_limit_per_local_neighborhood": 512,
            "feasible_structures_per_neighborhood": 12,
            "block_widths": [2, 3, 4],
            "block_seed_limit": 8,
            "rebuild_beam_width": 8,
            "nearest_anchor_count": 24,
            "workers": 3,
        },
        "inputs": inputs,
        "source_hashes": source_hashes,
        "sealed_v7_raw_runs": {
            "path": raw_path.relative_to(REPO).as_posix(),
            "sha256": sha256(raw_path),
        },
        "authority_registration": {
            "path": (
                "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/"
                "g0_real_bundle_preregistration_v1.json"
            ),
            "sha256": sha256(
                REPO
                / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724"
                / "g0_real_bundle_preregistration_v1.json"
            ),
        },
        "claim_boundary": (
            "Zero candidate-objective wiring and feasibility gate only; "
            "no performance, hybrid, E3, BKS, SOTA, or paper claim."
        ),
    }
    write_json(REGISTRATION, payload)
    print(f"FROZEN_BEFORE_EXECUTION {len(inputs)} {len(source_hashes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

