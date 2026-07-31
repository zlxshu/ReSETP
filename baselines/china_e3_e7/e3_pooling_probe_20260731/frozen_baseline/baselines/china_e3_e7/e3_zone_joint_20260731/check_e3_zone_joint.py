#!/usr/bin/env python3
"""Independent re-reader and complete-model verifier for ZONE versus JOINT."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
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
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
    temporary.replace(path)


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    out = Path(args.output_root).resolve()
    repo = out.parents[2]
    runner_path = out / "run_e3_zone_joint.py"
    runner = load_module("_e3_zone_joint_checker_runner", runner_path)
    source_lock = json.loads(
        (out / "source_lock.json").read_text(encoding="utf-8")
    )
    if source_lock["source_sha256"] != runner.current_source_hashes():
        raise RuntimeError("HALT_CHECKER_SOURCE_DRIFT")
    runner.verify_protected()
    rows = list(
        csv.DictReader(
            (out / "raw_runs.csv").open(encoding="utf-8", newline="")
        )
    )
    if len(rows) != 40:
        raise RuntimeError(f"HALT_CHECKER_DENOMINATOR:{len(rows)}/40")
    keys = {
        (row["instance_id"], int(row["seed"]), row["arm"])
        for row in rows
    }
    if len(keys) != 40:
        raise RuntimeError("HALT_CHECKER_DUPLICATE_KEYS")
    e3 = runner.load_e3()
    checked = []
    for row in rows:
        instance_id = row["instance_id"]
        arm = row["arm"]
        seed = int(row["seed"])
        stem = (
            f"{instance_id}__seed{seed:02d}__{arm}"
        )
        plan_path = out / "formal/plans" / f"{stem}.json"
        status_path = out / "formal/task_status" / f"{stem}.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if plan["plan_sha256"] != payload_sha256(
            {key: value for key, value in plan.items() if key != "plan_sha256"}
        ):
            raise RuntimeError(f"HALT_CHECKER_PLAN_HASH:{stem}")
        if sha256(plan_path) != status["plan_sha256"]:
            raise RuntimeError(f"HALT_CHECKER_PLAN_FILE_HASH:{stem}")
        responsibility = json.loads(
            (
                out
                / "inputs"
                / instance_id
                / arm
                / "responsibility_map.json"
            ).read_text(encoding="utf-8")
        )
        base = e3.load_bundle(instance_id)
        bundle = e3.with_responsibility(
            base, responsibility["mapping"]
        )
        solution = e3.solution_from_payload(plan["solution"])
        audit = runner.e3e6_state_audit(e3, solution, bundle)
        if audit["solution_sha256"] != plan["solution_sha256"]:
            raise RuntimeError(f"HALT_CHECKER_SOLUTION_HASH:{stem}")
        if not math.isclose(
            audit["objective"],
            float(row["total_cost_cny"]),
            rel_tol=1.0e-12,
            abs_tol=1.0e-9,
        ):
            raise RuntimeError(f"HALT_CHECKER_OBJECTIVE:{stem}")
        if int(row["violation_count"]) != 0:
            raise RuntimeError(f"HALT_CHECKER_RECORDED_VIOLATION:{stem}")
        if arm == "ZONE" and audit["cross_site_service_count"] != 0:
            raise RuntimeError(f"HALT_CHECKER_LOCK_CROSS_SITE:{stem}")
        consumed = int(row["complete_candidate_evaluations_consumed"])
        cap = int(row["complete_candidate_budget_cap"])
        if consumed > cap:
            raise RuntimeError(f"HALT_CHECKER_BUDGET:{stem}")
        if int(row["error_candidates"]) != 0:
            raise RuntimeError(f"HALT_CHECKER_TECHNICAL_ERROR:{stem}")
        for field, audited in (
            ("distance_total_m", audit["distance_total_m"]),
            ("carbon_emissions_kg", audit["carbon_emissions_kg"]),
            (
                "time_window_satisfied_customer_count",
                audit["time_window_satisfied_customer_count"],
            ),
        ):
            if float(row[field]) != float(audited):
                raise RuntimeError(
                    f"HALT_CHECKER_DERIVED_FIELD:{stem}:{field}"
                )
        if int(row["constraint_filtered_candidates"]) < 0:
            raise RuntimeError(f"HALT_CHECKER_FILTER_COUNT:{stem}")
        checked.append(
            {
                "instance_id": instance_id,
                "seed": seed,
                "arm": arm,
                "objective": audit["objective"],
                "solution_sha256": audit["solution_sha256"],
                "violation_count": 0,
                "budget_cap": cap,
                "evaluations_consumed": consumed,
                "constraint_filtered_candidates": int(
                    row["constraint_filtered_candidates"]
                ),
            }
        )
    assignments = list(
        csv.DictReader(
            (out / "input_assignments.csv").open(
                encoding="utf-8", newline=""
            )
        )
    )
    for instance_id, _role in runner.INSTANCES:
        administrative = {
            row["customer_id"]: row["administrative_registered_depot"]
            for row in assignments
            if row["instance_id"] == instance_id and row["arm"] == "ZONE"
        }
        zone = {
            row["customer_id"]: row["nearest_depot"]
            for row in assignments
            if row["instance_id"] == instance_id and row["arm"] == "ZONE"
        }
        if administrative != zone:
            raise RuntimeError(
                f"HALT_CHECKER_EXPECTED_INPUT_IDENTITY:{instance_id}"
            )
    before = json.loads(
        (out / "regression/joint_before.json").read_text(encoding="utf-8")
    )
    after = json.loads(
        (out / "regression/joint_after.json").read_text(encoding="utf-8")
    )
    for field in (
        "solution_sha256",
        "objective_float_hex",
        "full_objective",
        "full_objective_sha256",
        "complete_candidate_evaluations_consumed",
    ):
        if before[field] != after[field]:
            raise RuntimeError(f"HALT_CHECKER_JOINT_DRIFT:{field}")
    proof = json.loads(
        (out / "joint_semantics_proof.json").read_text(encoding="utf-8")
    )
    if proof.get("status") != "PASS_JOINT_SEMANTICS_UNCHANGED":
        raise RuntimeError("HALT_CHECKER_JOINT_PROOF")
    bug_fix = json.loads(
        (out / "cross_site_bug_fix_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    if (
        bug_fix.get("status") != "PASS_CROSS_SITE_BUG_FIXED"
        or int(bug_fix.get("old_halt_trace_count", -1)) != 14
    ):
        raise RuntimeError("HALT_CHECKER_BUG_FIX_EVIDENCE")
    result = {
        "schema": "resetp.e3-zone-joint.independent-verification.v1",
        "status": "PASS_INDEPENDENT_VERIFICATION",
        "formal_units_checked": len(checked),
        "objective_mismatches": 0,
        "solution_hash_mismatches": 0,
        "violations": 0,
        "budget_exceedances": 0,
        "technical_error_candidates": 0,
        "locked_cross_site_violations": 0,
        "administrative_zone_mapping_identity_rechecked": True,
        "joint_semantics_unchanged_proof_rechecked": True,
        "cross_site_bug_fix_evidence_rechecked": True,
        "protected_hashes": runner.verify_protected(),
        "source_lock_id": source_lock["source_lock_id"],
        "checked_rows_sha256": payload_sha256(checked),
    }
    result["verification_id"] = payload_sha256(result)
    atomic_json(out / "independent_verification.json", result)
    print(
        "PASS_INDEPENDENT_VERIFICATION formal_units_checked=40",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
