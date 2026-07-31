#!/usr/bin/env python3
"""Independent physical replay and full-model certificate for E5 v2.

This executable intentionally does not import the E5 v2 search runner.  It
reuses the already verified low-level reconstruction/replay routines from the
sealed 2026-07-29 checker, then issues a new v2 certificate for every formal
plan.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
for path in (SCRIPT_DIR, REPO / "solver/src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import check_e5_nonlinear_20260729 as verified
from setp_solver.charging_curve import L100_CONTROL, NL90_MILD
from setp_solver.solution import physical_vehicle_id

TASK_ID = "E5-NONLINEAR-CHARGING-V2-20260730"
EXPECTED_PLANS = 40
EXCLUDED_ENUMERATION_DIRS = frozenset({"__pycache__", ".pytest_cache"})


def is_real_artifact_file(path: Path) -> bool:
    """Return true only for a real file, never AppleDouble/cache byproducts."""

    return (
        path.is_file()
        and not path.name.startswith("._")
        and not any(part in EXCLUDED_ENUMERATION_DIRS for part in path.parts)
    )


def physical_vehicle_count(solution: Any) -> int:
    return len({physical_vehicle_id(route.vehicle_id) for route in solution.routes})


def certify_plan(plan_path: Path, output_root: Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    instance_id = str(plan["instance_id"])
    arm = str(plan["arm"])
    seed = int(plan["seed"])
    if arm not in {L100_CONTROL.curve_id, NL90_MILD.curve_id}:
        raise ValueError(f"unexpected E5 arm: {arm}")
    plan_without_hash = dict(plan)
    declared_plan_hash = str(plan_without_hash.pop("plan_sha256"))
    if verified.payload_sha256(plan_without_hash) != declared_plan_hash:
        raise RuntimeError(f"HALT_E5_V2_PLAN_HASH_MISMATCH:{plan_path}")

    base = verified.load_china81_bundle(REPO, instance_id)
    linear_bundle = verified.curve_bundle(base, L100_CONTROL.curve_id)
    nonlinear_bundle = verified.curve_bundle(base, NL90_MILD.curve_id)
    planned = verified.solution_from_payload(plan["solution"])
    if verified.payload_sha256(plan["solution"]) != str(plan["solution_sha256"]):
        raise RuntimeError(f"HALT_E5_V2_SOLUTION_HASH_MISMATCH:{plan_path}")

    replay, sessions, before_hash, after_hash = verified.project_to_nl90(
        planned, nonlinear_bundle
    )
    if before_hash != after_hash:
        raise RuntimeError(
            f"HALT_E5_V2_REPLAY_CHANGED_DECISIONS:{instance_id}:{arm}:{seed}"
        )
    planning_bundle = (
        linear_bundle if arm == L100_CONTROL.curve_id else nonlinear_bundle
    )
    planning_check = verified.independent_score(planned, planning_bundle)
    nonlinear_check = verified.independent_score(replay, nonlinear_bundle)
    search_objective = float(plan["search_total_cost_cny"])
    recomputed_objective = float(planning_check["total_cost_cny_internal"])
    if abs(search_objective - recomputed_objective) > verified.TOL * max(
        1.0, abs(search_objective), abs(recomputed_objective)
    ):
        raise RuntimeError(
            "HALT_E5_V2_SEARCH_OBJECTIVE_RECOMPUTE_MISMATCH:"
            f"{instance_id}:{arm}:{seed}:{search_objective}:{recomputed_objective}"
        )
    false_feasible = bool(
        arm == L100_CONTROL.curve_id
        and planning_check["feasible"]
        and not nonlinear_check["feasible"]
    )
    categories: dict[str, int] = {}
    for violation in nonlinear_check["violations"]:
        category = verified.cause_category(violation)
        categories[category] = categories.get(category, 0) + 1
    for session in sessions:
        session.update(
            {
                "instance_id": instance_id,
                "sample_role": plan["sample_role"],
                "seed": seed,
                "arm": arm,
            }
        )

    planning_cost = (
        float(planning_check["total_cost_cny_internal"])
        if planning_check["feasible"]
        else None
    )
    nonlinear_cost = (
        float(nonlinear_check["total_cost_cny_internal"])
        if nonlinear_check["feasible"]
        else None
    )
    certificate = {
        "schema_version": "E5-INDEPENDENT-CERT-v2",
        "task_id": TASK_ID,
        "instance_id": instance_id,
        "sample_role": plan["sample_role"],
        "seed": seed,
        "arm": arm,
        "plan_path": str(plan_path.relative_to(REPO)),
        "plan_sha256": verified.file_sha256(plan_path),
        "solution_sha256": plan["solution_sha256"],
        "common_nonlinear_curve": asdict(NL90_MILD),
        "planning_physics_feasible": bool(planning_check["feasible"]),
        "planning_physics_violations": planning_check["violations"],
        "search_objective_matches_independent_recompute": True,
        "planning_full_model_total_cost_cny": planning_cost,
        "planning_full_model_cost_breakdown_if_feasible": (
            planning_check["cost_breakdown"] if planning_check["feasible"] else None
        ),
        "nonlinear_feasible": bool(nonlinear_check["feasible"]),
        "nonlinear_violations": nonlinear_check["violations"],
        "nonlinear_infeasibility_categories": categories,
        "linear_plan_false_feasible": false_feasible,
        "common_nonlinear_full_model_total_cost_cny": nonlinear_cost,
        "common_nonlinear_full_model_cost_breakdown_if_feasible": (
            nonlinear_check["cost_breakdown"]
            if nonlinear_check["feasible"]
            else None
        ),
        "physical_vehicle_count": physical_vehicle_count(planned),
        "decision_structure_sha256_before_replay": before_hash,
        "decision_structure_sha256_after_replay": after_hash,
        "decision_structure_unchanged": before_hash == after_hash,
        "replay_solution_sha256": verified.payload_sha256(
            {
                "routes": [asdict(row) for row in replay.routes],
                "charging_actions": [
                    asdict(row) for row in replay.charging_actions
                ],
                "cross_site_services": [
                    asdict(row) for row in replay.cross_site_services
                ],
            }
        ),
        "sessions": sessions,
        "checker_sources": {
            str(path.relative_to(REPO)): verified.file_sha256(path)
            for path in (
                Path(__file__).resolve(),
                REPO / "baselines/china_e3_e7/check_e5_nonlinear_20260729.py",
                REPO / "solver/src/setp_solver/check.py",
                REPO / "solver/src/setp_solver/cost.py",
                REPO / "solver/src/setp_solver/search/evaluation.py",
                REPO / "solver/src/setp_solver/china81_completion.py",
                REPO / "solver/src/setp_solver/charging_curve.py",
            )
        },
        "direct_vs_exact": {
            "planning_ledgers_match": planning_check[
                "direct_vs_exact_ledgers_match"
            ],
            "planning_costs_match": planning_check["direct_vs_exact_costs_match"],
            "nonlinear_ledgers_match": nonlinear_check[
                "direct_vs_exact_ledgers_match"
            ],
            "nonlinear_costs_match": nonlinear_check[
                "direct_vs_exact_costs_match"
            ],
        },
        "certificate_status": "PASS",
    }
    certificate["certificate_id"] = verified.payload_sha256(certificate)
    out = (
        output_root
        / "certificates"
        / f"{instance_id}__seed-{seed:02d}__{arm}.json"
    )
    verified.atomic_json(out, certificate)
    return {
        "instance_id": instance_id,
        "sample_role": plan["sample_role"],
        "seed": seed,
        "arm": arm,
        "certificate_path": str(out.relative_to(REPO)),
        "certificate_sha256": verified.file_sha256(out),
        "certificate_id": certificate["certificate_id"],
        "planning_physics_feasible": int(planning_check["feasible"]),
        "nonlinear_feasible": int(nonlinear_check["feasible"]),
        "linear_plan_false_feasible": int(false_feasible),
        "certificate_status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    plans = sorted(
        path
        for path in (output_root / "formal" / "plans").glob("*.json")
        if is_real_artifact_file(path)
    )
    if len(plans) != EXPECTED_PLANS:
        raise RuntimeError(
            f"HALT_E5_V2_EXPECTED_{EXPECTED_PLANS}_FORMAL_PLANS:"
            f"found={len(plans)}"
        )
    rows = [certify_plan(path, output_root) for path in plans]
    verified.atomic_csv(output_root / "independent_certificates.csv", rows)
    verification = {
        "schema_version": "E5-INDEPENDENT-VERIFICATION-v2",
        "task_id": TASK_ID,
        "status": "PASS",
        "expected_certificate_count": EXPECTED_PLANS,
        "certificate_count": len(rows),
        "unique_certificate_ids": len({row["certificate_id"] for row in rows}),
        "checker_executable": str(Path(__file__).resolve().relative_to(REPO)),
        "checker_executable_sha256": verified.file_sha256(
            Path(__file__).resolve()
        ),
    }
    verified.atomic_json(output_root / "independent_verification.json", verification)
    print(
        f"INDEPENDENT_CHECK_PASS certificates={len(rows)}/{EXPECTED_PLANS}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
