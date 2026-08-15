#!/usr/bin/env python3
"""Independent fixed-decision replay and certification for E5 fast charge.

This checker does not import the search runner. It reconstructs each plan from
disk, applies the frozen shared fast-charge configuration, and independently
compares the common check/evaluation path with exact China81 scoring.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
for path in (SCRIPT_DIR, REPO / "solver/src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import check_e5_nonlinear_20260729 as verified
import e5_fastcharge_config_20260731 as cfg
from setp_solver.charging_curve import L100_CONTROL
from setp_solver.solution import ChargingAction, Solution, physical_vehicle_id

EXPECTED_PLANS = 40
TOL = 1.0e-9


def project_to_fast_nonlinear(
    solution: Solution,
    nonlinear_bundle: Any,
) -> tuple[Solution, list[dict[str, Any]], str, str]:
    """Change only duration and explicit curve id under frozen fast physics."""

    capacity = verified.battery_capacity_kwh(nonlinear_bundle)
    before = verified.structural_payload(solution)
    actions: list[ChargingAction] = []
    sessions: list[dict[str, Any]] = []
    for index, action in enumerate(solution.charging_actions, start=1):
        if action.start_energy_kwh is None or action.end_energy_kwh is None:
            raise ValueError(
                "fast-charge action lacks start/end energy metadata: "
                f"{action.vehicle_id}:{action.station_id}"
            )
        start_energy = float(action.start_energy_kwh)
        end_energy = float(action.end_energy_kwh)
        power = verified.station_power_kw(
            nonlinear_bundle, action.station_id
        )
        linear = L100_CONTROL.scale(
            capacity_kwh=capacity,
            reference_power_kw=power,
        )
        nonlinear = cfg.FAST_CURVE.scale(
            capacity_kwh=capacity,
            reference_power_kw=power,
        )
        linear_seconds = linear.duration_seconds(start_energy, end_energy)
        nonlinear_seconds = nonlinear.duration_seconds(
            start_energy, end_energy
        )
        actions.append(
            replace(
                action,
                occupancy_minutes=nonlinear_seconds / 60.0,
                charging_curve_id=cfg.FAST_CURVE.curve_id,
            )
        )
        sessions.append(
            {
                "session_index": index,
                "vehicle_id": action.vehicle_id,
                "station_id": action.station_id,
                "start_soc_pct": 100.0 * start_energy / capacity,
                "end_soc_pct": 100.0 * end_energy / capacity,
                "energy_kwh": float(action.energy_kwh),
                "reference_power_kw": power,
                "charge_start_second": float(action.charge_start_second),
                "charge_day_offset": int(action.charge_day_offset),
                "planned_curve_id": action.charging_curve_id,
                "planned_duration_seconds": (
                    float(action.occupancy_minutes) * 60.0
                ),
                "linear_duration_seconds": linear_seconds,
                "nonlinear_duration_seconds": nonlinear_seconds,
                "nonlinear_minus_linear_seconds": (
                    nonlinear_seconds - linear_seconds
                ),
                "entered_taper_zone": int(
                    end_energy / capacity > cfg.TAPER_SOC + 1.0e-12
                    and end_energy > start_energy + 1.0e-12
                ),
            }
        )
    replay = Solution(
        routes=list(solution.routes),
        charging_actions=actions,
        cross_site_services=list(solution.cross_site_services),
    )
    after = verified.structural_payload(replay)
    return (
        replay,
        sessions,
        verified.payload_sha256(before),
        verified.payload_sha256(after),
    )


def certify_plan(plan_path: Path, output_root: Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    instance_id = str(plan["instance_id"])
    arm = str(plan["arm"])
    seed = int(plan["seed"])
    if arm not in set(cfg.ARMS):
        raise ValueError(f"unexpected fast-charge arm: {arm}")
    unhashed = dict(plan)
    declared_hash = str(unhashed.pop("plan_sha256"))
    if verified.payload_sha256(unhashed) != declared_hash:
        raise RuntimeError(f"HALT_E5_FAST_PLAN_HASH_MISMATCH:{plan_path}")
    if verified.payload_sha256(plan["solution"]) != str(
        plan["solution_sha256"]
    ):
        raise RuntimeError(
            f"HALT_E5_FAST_SOLUTION_HASH_MISMATCH:{plan_path}"
        )

    linear_bundle = cfg.load_fastcharge_bundle(
        instance_id, L100_CONTROL.curve_id
    )
    nonlinear_bundle = cfg.load_fastcharge_bundle(
        instance_id, cfg.FAST_CURVE.curve_id
    )
    planned = verified.solution_from_payload(plan["solution"])
    replay, sessions, before_hash, after_hash = project_to_fast_nonlinear(
        planned, nonlinear_bundle
    )
    if before_hash != after_hash:
        raise RuntimeError(
            "HALT_E5_FAST_REPLAY_CHANGED_DECISIONS:"
            f"{instance_id}:{arm}:{seed}"
        )

    planning_bundle = (
        linear_bundle
        if arm == L100_CONTROL.curve_id
        else nonlinear_bundle
    )
    planning_check = verified.independent_score(planned, planning_bundle)
    nonlinear_check = verified.independent_score(replay, nonlinear_bundle)
    search_objective = float(plan["search_total_cost_cny"])
    recomputed = float(planning_check["total_cost_cny_internal"])
    if abs(search_objective - recomputed) > TOL * max(
        1.0, abs(search_objective), abs(recomputed)
    ):
        raise RuntimeError(
            "HALT_E5_FAST_SEARCH_OBJECTIVE_RECOMPUTE_MISMATCH:"
            f"{instance_id}:{arm}:{seed}:{search_objective}:{recomputed}"
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

    certificate = {
        "schema_version": "E5-FASTCHARGE-INDEPENDENT-CERT-v1",
        "task_id": cfg.TASK_ID,
        "instance_id": instance_id,
        "sample_role": plan["sample_role"],
        "seed": seed,
        "arm": arm,
        "plan_path": str(plan_path.relative_to(REPO)),
        "plan_sha256": verified.file_sha256(plan_path),
        "solution_sha256": plan["solution_sha256"],
        "common_nonlinear_curve": asdict(cfg.FAST_CURVE),
        "depot_site_power_kw_shadow": cfg.DEPOT_POWER_KW,
        "planning_physics_feasible": bool(planning_check["feasible"]),
        "planning_physics_violations": planning_check["violations"],
        "planning_full_model_total_cost_cny": (
            float(planning_check["total_cost_cny_internal"])
            if planning_check["feasible"]
            else None
        ),
        "planning_full_model_cost_breakdown_if_feasible": (
            planning_check["cost_breakdown"]
            if planning_check["feasible"]
            else None
        ),
        "nonlinear_feasible": bool(nonlinear_check["feasible"]),
        "nonlinear_violations": nonlinear_check["violations"],
        "nonlinear_infeasibility_categories": categories,
        "linear_plan_false_feasible": false_feasible,
        "common_nonlinear_full_model_total_cost_cny": (
            float(nonlinear_check["total_cost_cny_internal"])
            if nonlinear_check["feasible"]
            else None
        ),
        "common_nonlinear_full_model_cost_breakdown_if_feasible": (
            nonlinear_check["cost_breakdown"]
            if nonlinear_check["feasible"]
            else None
        ),
        "physical_vehicle_count": len(
            {
                physical_vehicle_id(route.vehicle_id)
                for route in planned.routes
            }
        ),
        "decision_structure_sha256_before_replay": before_hash,
        "decision_structure_sha256_after_replay": after_hash,
        "decision_structure_unchanged": True,
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
        "direct_vs_exact": {
            "planning_ledgers_match": planning_check[
                "direct_vs_exact_ledgers_match"
            ],
            "planning_costs_match": planning_check[
                "direct_vs_exact_costs_match"
            ],
            "nonlinear_ledgers_match": nonlinear_check[
                "direct_vs_exact_ledgers_match"
            ],
            "nonlinear_costs_match": nonlinear_check[
                "direct_vs_exact_costs_match"
            ],
        },
        "checker_sources": {
            str(path.relative_to(REPO)): verified.file_sha256(path)
            for path in (
                Path(__file__).resolve(),
                REPO
                / "baselines/china_e3_e7/e5_fastcharge_config_20260731.py",
                REPO / "solver/src/setp_solver/check.py",
                REPO / "solver/src/setp_solver/cost.py",
                REPO / "solver/src/setp_solver/search/evaluation.py",
                REPO / "solver/src/setp_solver/china81_completion.py",
                REPO / "solver/src/setp_solver/charging_curve.py",
            )
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
        for path in (output_root / "formal/plans").glob("*.json")
        if not path.name.startswith("._")
    )
    if len(plans) != EXPECTED_PLANS:
        raise RuntimeError(
            f"HALT_E5_FAST_EXPECTED_{EXPECTED_PLANS}_PLANS:"
            f"found={len(plans)}"
        )
    rows = [certify_plan(path, output_root) for path in plans]
    verified.atomic_csv(output_root / "independent_certificates.csv", rows)
    verification = {
        "schema_version": "E5-FASTCHARGE-INDEPENDENT-VERIFICATION-v1",
        "task_id": cfg.TASK_ID,
        "status": "PASS",
        "expected_certificate_count": EXPECTED_PLANS,
        "certificate_count": len(rows),
        "unique_certificate_ids": len(
            {row["certificate_id"] for row in rows}
        ),
        "checker_executable": str(
            Path(__file__).resolve().relative_to(REPO)
        ),
        "checker_executable_sha256": verified.file_sha256(
            Path(__file__).resolve()
        ),
    }
    verified.atomic_json(
        output_root / "independent_verification.json", verification
    )
    print(
        f"INDEPENDENT_CHECK_PASS certificates={len(rows)}/{EXPECTED_PLANS}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
