#!/usr/bin/env python3
"""Capture a deterministic JOINT regression witness around the lock fix."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
STRUCTURAL = (
    REPO / "baselines/china_e3_e7/e3_structural_20260731"
)
STRUCTURAL_RUNNER = STRUCTURAL / "run_e3_structural.py"
INSTANCE_ID = "cn-prd-50c-01-V2-LOCATIONS"
SEED = 1
CAP = 400
THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def payload_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_structural_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "e3_structural_regression_source", STRUCTURAL_RUNNER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load structural runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--arm", choices=("ZONE", "JOINT"), default="JOINT")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    for name, value in THREAD_ENV.items():
        os.environ[name] = value

    runner = load_structural_runner()
    e3 = runner.load_e3()
    bundle, initial, certificate = runner.load_input(
        e3, INSTANCE_ID, args.arm
    )
    hard_lock = args.arm == "ZONE"
    run = e3.run_hgs_route_pool_recombination(
        bundle,
        initial,
        seed=args.seed,
        hgs_seconds_per_view=None,
        exact_elites_per_view=runner.EXACT_ELITES_PER_VIEW,
        max_archive_candidates_per_view=runner.archive_limits(CAP),
        sp_time_limit_seconds=runner.MIP_TIME_LIMIT_SECONDS,
        hard_home_depot_lock=hard_lock,
        max_hgs_iterations_per_view=(
            runner.MAX_HGS_ITERATIONS_PER_VIEW
        ),
        wallclock_safety_seconds_per_view=900.0,
        exact_checkpoint_interval_iterations=None,
        preserve_base_pool_recombination=False,
    )
    audit = runner.e3e6_state_audit(e3, run.solution, bundle)
    full_objective = {
        "objective": audit["objective"],
        "independent": audit["independent"],
    }
    epochal = (
        REPO
        / "baselines/algorithm_prototypes/"
        "china81_mechanism_hybrid_20260720/epochal_hgs.py"
    )
    payload = {
        "schema": "resetp.e3-zone-joint.joint-regression.v1",
        "label": args.label,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "instance_id": INSTANCE_ID,
        "seed": args.seed,
        "arm": args.arm,
        "hard_home_depot_lock": hard_lock,
        "budget_cap": CAP,
        "complete_candidate_evaluations_consumed": int(
            run.stats["complete_candidate_evaluation_attempts"]
        ),
        "solution_sha256": audit["solution_sha256"],
        "objective": audit["objective"],
        "objective_float_hex": float(audit["objective"]).hex(),
        "full_objective": full_objective,
        "full_objective_sha256": payload_sha256(full_objective),
        "violation_count": (
            audit["independent"]["exact_violation_count"]
            + audit["independent"]["checker_violation_count"]
        ),
        "cross_site_service_count": audit["cross_site_service_count"],
        "hard_lock_filtered_candidates": sum(
            int(epoch.stats["hard_lock_filtered_candidates"])
            for epoch in run.view_epochs.values()
        ),
        "input_certificate": certificate,
        "epochal_hgs_sha256": file_sha256(epochal),
        "structural_runner_sha256": file_sha256(STRUCTURAL_RUNNER),
    }
    payload["witness_sha256"] = payload_sha256(payload)
    output_name = (
        f"joint_{args.label}.json"
        if args.arm == "JOINT" and args.seed == SEED
        else f"{args.arm.lower()}_{args.label}_seed{args.seed:02d}.json"
    )
    atomic_json(HERE / "regression" / output_name, payload)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
