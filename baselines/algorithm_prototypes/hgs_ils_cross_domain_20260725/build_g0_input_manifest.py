#!/usr/bin/env python3
"""Build the result-independent G0 input and sealed-reference manifest."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from common import (
    CAMPAIGN,
    FLEET_WITNESSES,
    INPUT_MANIFEST,
    LABELS,
    REGISTRATION,
    REPO,
    SEEDS,
    file_sha256,
    read_json,
    route_signatures,
    write_json,
)


def _v7_rows() -> list[dict[str, str]]:
    with (CAMPAIGN / "raw_runs.csv").open(
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        return list(csv.DictReader(handle))


def _task_dir(instance_id: str, seed: int) -> Path:
    return (
        CAMPAIGN
        / "tasks"
        / f"D6-E2-STAGED__{instance_id}__seed{seed}"
    )


def main() -> int:
    registration = read_json(REGISTRATION)
    rows = _v7_rows()
    instances: dict[str, object] = {}
    for instance_id in registration["instances"]:
        selected = [
            row
            for row in rows
            if row["instance_id"] == instance_id
            and int(row["seed"]) in SEEDS
        ]
        if len(selected) != len(SEEDS):
            raise RuntimeError(
                f"expected five sealed rows for {instance_id}, "
                f"found {len(selected)}"
            )
        if any(row["status"] != "PASS" for row in selected):
            raise RuntimeError(f"sealed v7 row is not PASS: {instance_id}")

        best = min(
            selected,
            key=lambda row: (
                float(row["HGS-M_cost"]),
                int(row["seed"]),
            ),
        )
        route_pool: set[tuple[str, ...]] = set()
        witness_files: list[dict[str, object]] = []
        for seed in SEEDS:
            witness_path = _task_dir(
                instance_id,
                seed,
            ) / "solution_witnesses.json"
            witness = read_json(witness_path)
            if set(witness) != set(LABELS):
                raise RuntimeError(
                    f"unexpected witness labels: {witness_path}"
                )
            for label in LABELS:
                route_pool.update(
                    route_signatures(
                        witness[label]["routes"],
                        minimum_customers=2,
                    )
                )
            witness_files.append(
                {
                    "seed": seed,
                    "path": str(witness_path.relative_to(REPO)),
                    "sha256": file_sha256(witness_path),
                }
            )

        best_seed = int(best["seed"])
        best_path = _task_dir(
            instance_id,
            best_seed,
        ) / "solution_witnesses.json"
        common_path = FLEET_WITNESSES / f"{instance_id}.json"
        if not common_path.is_file():
            raise FileNotFoundError(common_path)
        instances[instance_id] = {
            "common_initial_path": str(common_path.relative_to(REPO)),
            "common_initial_sha256": file_sha256(common_path),
            "warm_start_seed": best_seed,
            "warm_start_label": "HGS-M",
            "warm_start_cost": float(best["HGS-M_cost"]),
            "warm_start_witness_path": str(
                best_path.relative_to(REPO)
            ),
            "warm_start_witness_sha256": file_sha256(best_path),
            "v7_witness_files": witness_files,
            "v7_reference_route_signatures": [
                list(signature) for signature in sorted(route_pool)
            ],
            "v7_reference_route_signature_count": len(route_pool),
        }

    manifest = {
        "schema": "resetp.hgs-ils-xd.g0-input-manifest.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "registration_path": str(REGISTRATION.relative_to(REPO)),
        "registration_sha256": file_sha256(REGISTRATION),
        "sealed_v7_raw_runs_path": str(
            (CAMPAIGN / "raw_runs.csv").relative_to(REPO)
        ),
        "sealed_v7_raw_runs_sha256": file_sha256(
            CAMPAIGN / "raw_runs.csv"
        ),
        "instances": instances,
    }
    write_json(INPUT_MANIFEST, manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
