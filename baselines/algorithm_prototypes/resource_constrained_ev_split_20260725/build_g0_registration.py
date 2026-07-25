#!/usr/bin/env python3
"""Freeze result-blind RC-EV-Split G0 inputs and implementation hashes."""

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
STRATA = (("jjj", 15), ("prd", 75), ("cy", 150))
EXCLUDED_IDS = {
    "cn-cy-25c-01-V2-LOCATIONS",
    "cn-prd-75c-01-V2-LOCATIONS",
    "cn-cy-200c-01-V2-LOCATIONS",
    "cn-jjj-50c-02-V2-LOCATIONS",
    "cn-cy-100c-01-V2-LOCATIONS",
    "cn-prd-200c-02-V2-LOCATIONS",
    "cn-cy-50c-03-V2-LOCATIONS",
    "cn-jjj-100c-03-V2-LOCATIONS",
    "cn-prd-150c-03-V2-LOCATIONS",
}
SOURCE_PATHS = (
    "baselines/algorithm_prototypes/resource_constrained_ev_split_20260725/__init__.py",
    "baselines/algorithm_prototypes/resource_constrained_ev_split_20260725/build_g0_registration.py",
    "baselines/algorithm_prototypes/resource_constrained_ev_split_20260725/china81_adapter.py",
    "baselines/algorithm_prototypes/resource_constrained_ev_split_20260725/run_g0.py",
    "baselines/algorithm_prototypes/resource_constrained_ev_split_20260725/split_core.py",
    "baselines/algorithm_prototypes/resource_constrained_ev_split_20260725/test_split_core.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/contracts.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/decoder_cache.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/fleet_assignment_dp.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/reference_decoder.py",
    "docs/handoff/e2_resource_constrained_split_contract_20260725.md",
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
    raw_path = V7 / "raw_runs.csv"
    with raw_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    all_ids = {row["instance_id"] for row in rows}
    chosen: list[str] = []
    for family, size in STRATA:
        pool = sorted(
            instance_id
            for instance_id in all_ids
            if f"cn-{family}-{size}c-" in instance_id
            and instance_id not in EXCLUDED_IDS
        )
        if not pool:
            raise RuntimeError(f"empty result-blind stratum: {family}/{size}")
        chosen.append(
            min(
                pool,
                key=lambda value: (
                    hashlib.sha256(value.encode()).hexdigest(),
                    value,
                ),
            )
        )

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
                    instance_id.encode()
                ).hexdigest(),
                "seed": int(winner["seed"]),
                "task_id": winner["task_id"],
                "witness_key": "MV-HGS-SP",
                "expected_objective": float(winner["MV-HGS-SP_cost"]),
                "witness_path": witness_path.relative_to(REPO).as_posix(),
                "witness_sha256": sha256(witness_path),
            }
        )

    authority = (
        REPO
        / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724"
        / "g0_real_bundle_preregistration_v1.json"
    )
    write_json(
        REGISTRATION,
        {
            "schema": "resetp.rc-ev-split-g0-registration.v1",
            "status": "FROZEN_BEFORE_EXECUTION",
            "registered_at_utc": datetime.now(timezone.utc).isoformat(),
            "approval_id": "E2-RC-EV-SPLIT-013",
            "contract_id": "E2-RC-EV-SPLIT-001",
            "selection_rule": (
                "fixed unseen family-size strata, minimum "
                "SHA-256(instance_id); then strongest sealed v7 "
                "MV-HGS-SP witness with seed tie-break"
            ),
            "config": {
                "max_labels_per_position": 50_000,
                "max_generated_labels": 500_000,
                "max_peak_rss_gib": 4.0,
                "workers": 3,
                "candidate_complete_objective_evaluations": 0,
                "order_perturbations": 0,
            },
            "excluded_instance_ids": sorted(EXCLUDED_IDS),
            "inputs": inputs,
            "sealed_v7_raw_runs": {
                "path": raw_path.relative_to(REPO).as_posix(),
                "sha256": sha256(raw_path),
            },
            "authority_registration": {
                "path": authority.relative_to(REPO).as_posix(),
                "sha256": sha256(authority),
            },
            "source_hashes": {
                relative: sha256(REPO / relative)
                for relative in SOURCE_PATHS
            },
            "claim_boundary": (
                "Zero-candidate-objective engineering and scale gate only; "
                "no algorithm-performance, HGS integration, paper, E3, "
                "BKS, SOTA, or hybrid claim."
            ),
        },
    )
    print(
        json.dumps(
            {"registration": str(REGISTRATION), "instances": chosen},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
