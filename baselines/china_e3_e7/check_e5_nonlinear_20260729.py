#!/usr/bin/env python3
"""Independent common-NL checker for E5-NONLINEAR-CHARGING-01.

This executable deliberately does not import the E5 search runner.  It reads
the frozen search plans, replays every plan under the registered NL90 curve,
and cross-checks the shared checker/evaluator against exact_china81_score.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for path in (REPO / "solver/src",):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from setp_solver.charging_curve import (
    L100_CONTROL,
    NL90_MILD,
    curve_from_id,
)
from setp_solver.check import check_solution
from setp_solver.china81 import China81Bundle, load_china81_bundle
from setp_solver.china81_completion import (
    annotate_cross_site_services,
    exact_china81_score,
)
from setp_solver.cost import evaluate
from setp_solver.solution import (
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
    charging_action_from_dict,
)

TOL = 1.0e-7


def canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def payload_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_bytes(payload))
    temporary.replace(path)


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def solution_from_payload(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                vehicle_id=str(row["vehicle_id"]),
                vehicle_type=str(row["vehicle_type"]),
                home_depot_id=str(row["home_depot_id"]),
                node_sequence=[str(value) for value in row["node_sequence"]],
            )
            for row in payload["routes"]
        ],
        charging_actions=[
            charging_action_from_dict(row) for row in payload["charging_actions"]
        ],
        cross_site_services=[
            CrossSiteService(
                customer_id=str(row["customer_id"]),
                served_by_depot_id=str(row["served_by_depot_id"]),
            )
            for row in payload["cross_site_services"]
        ],
    )


def curve_bundle(bundle: China81Bundle, curve_id: str) -> China81Bundle:
    if curve_id == L100_CONTROL.curve_id:
        spec = L100_CONTROL
    elif curve_id == NL90_MILD.curve_id:
        spec = NL90_MILD
    else:
        raise ValueError(f"unregistered E5 curve: {curve_id}")
    prices = replace(
        bundle.prices,
        charging_curve_id=spec.curve_id,
        charging_soc_breakpoints=spec.soc_breakpoints,
        charging_relative_powers=spec.relative_powers,
    )
    return replace(bundle, prices=prices)


def station_power_kw(bundle: China81Bundle, station_id: str) -> float:
    node = bundle.instance.nodes[bundle.instance.node_index[station_id]]
    if node.node_type.lower() == "d":
        return float(bundle.prices.depot_charge_power_kw)
    if node.node_type.lower() != "f" or node.charge_power_kw is None:
        raise ValueError(f"missing charging power for {station_id}")
    return float(node.charge_power_kw)


def battery_capacity_kwh(bundle: China81Bundle) -> float:
    return bundle.instance.battery_capacity_kwh(
        fallback=float(bundle.prices.B_battery_kwh)
    )


def project_to_nl90(
    solution: Solution,
    nl_bundle: China81Bundle,
) -> tuple[Solution, list[dict[str, Any]], str, str]:
    """Replay unchanged decisions with the true NL90 duration.

    Route, vehicle, station, start time and charged energy are immutable.  Only
    occupancy and the explicit physics identifier are changed.  This is a
    physical replay, never a feasibility repair.
    """

    capacity = battery_capacity_kwh(nl_bundle)
    actions: list[ChargingAction] = []
    sessions: list[dict[str, Any]] = []
    before = structural_payload(solution)
    for index, action in enumerate(solution.charging_actions, start=1):
        if action.start_energy_kwh is None or action.end_energy_kwh is None:
            raise ValueError(
                "E5 formal action lacks start/end energy metadata: "
                f"{action.vehicle_id}:{action.station_id}"
            )
        start_energy = float(action.start_energy_kwh)
        end_energy = float(action.end_energy_kwh)
        power = station_power_kw(nl_bundle, action.station_id)
        linear_curve = curve_from_id(
            L100_CONTROL.curve_id,
            capacity_kwh=capacity,
            reference_power_kw=power,
        )
        nonlinear_curve = curve_from_id(
            NL90_MILD.curve_id,
            capacity_kwh=capacity,
            reference_power_kw=power,
        )
        linear_seconds = linear_curve.duration_seconds(start_energy, end_energy)
        nonlinear_seconds = nonlinear_curve.duration_seconds(start_energy, end_energy)
        actions.append(
            replace(
                action,
                occupancy_minutes=nonlinear_seconds / 60.0,
                charging_curve_id=NL90_MILD.curve_id,
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
                "planned_duration_seconds": (float(action.occupancy_minutes) * 60.0),
                "linear_duration_seconds": linear_seconds,
                "nonlinear_duration_seconds": nonlinear_seconds,
                "nonlinear_minus_linear_seconds": (nonlinear_seconds - linear_seconds),
            }
        )
    replay = Solution(
        routes=list(solution.routes),
        charging_actions=actions,
        cross_site_services=list(solution.cross_site_services),
    )
    after = structural_payload(replay)
    return replay, sessions, payload_sha256(before), payload_sha256(after)


def structural_payload(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_decisions": [
            {
                "vehicle_id": action.vehicle_id,
                "station_id": action.station_id,
                "energy_kwh": float(action.energy_kwh),
                "charge_start_second": float(action.charge_start_second),
                "charge_day_offset": int(action.charge_day_offset),
                "start_energy_kwh": action.start_energy_kwh,
                "end_energy_kwh": action.end_energy_kwh,
            }
            for action in solution.charging_actions
        ],
        "cross_site_services": [asdict(item) for item in solution.cross_site_services],
    }


def violation_payload(violations: list[Any]) -> list[dict[str, Any]]:
    return [asdict(item) for item in violations]


def normalized_ledger(violations: list[Any]) -> list[dict[str, Any]]:
    return sorted(
        violation_payload(violations),
        key=lambda row: (
            row["type"],
            row["vehicle_id"],
            row["location"],
            row["detail"],
            row["severity"],
        ),
    )


def independent_score(
    solution: Solution,
    bundle: China81Bundle,
) -> dict[str, Any]:
    annotated = annotate_cross_site_services(solution, bundle.customer_home_depot)
    direct_violations = check_solution(annotated, bundle.instance, bundle.prices)
    direct_breakdown = evaluate(
        annotated,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    exact_total, exact_breakdown, exact_violations = exact_china81_score(
        solution, bundle
    )
    direct_total = float(direct_breakdown["total_cost"])
    ledgers_match = normalized_ledger(direct_violations) == normalized_ledger(
        exact_violations
    )
    costs_match = abs(direct_total - exact_total) <= TOL * max(
        1.0, abs(direct_total), abs(exact_total)
    ) and payload_sha256(direct_breakdown) == payload_sha256(exact_breakdown)
    if not ledgers_match or not costs_match:
        raise RuntimeError(
            "HALT_E5_INDEPENDENT_CHECKER_DISAGREEMENT:"
            f"ledgers={ledgers_match}:costs={costs_match}"
        )
    return {
        "feasible": not direct_violations,
        "total_cost_cny_internal": direct_total,
        "cost_breakdown": direct_breakdown,
        "violations": normalized_ledger(direct_violations),
        "direct_vs_exact_ledgers_match": ledgers_match,
        "direct_vs_exact_costs_match": costs_match,
    }


def cause_category(row: dict[str, Any]) -> str:
    kind = str(row["type"])
    detail = str(row["detail"]).lower()
    if kind == "BATTERY":
        return "ELECTRIC_ENERGY_SHORTFALL_OR_SOC"
    if kind == "TIME_WINDOW":
        return "TIME_WINDOW_OVERRUN"
    if kind == "ROUTE_STRUCTURE":
        return "INTER_TRIP_CONNECTION_OR_ROUTE_CONTINUITY"
    if kind == "STATION_CAPACITY" and (
        "physical vehicle" in detail or "overlap" in detail
    ):
        return "INTER_TRIP_CONNECTION_OR_ROUTE_CONTINUITY"
    if kind == "CHARGING_START":
        return "CHARGING_TIMING_INCONSISTENCY"
    if kind == "CHARGING_POWER":
        return "CHARGING_DURATION_OR_POWER"
    if kind == "STATION_CAPACITY":
        return "CHARGER_CAPACITY_OR_CONCURRENCY"
    if kind == "FLEET_SIZE":
        return "FLEET_CAPACITY"
    return f"OTHER_{kind}"


def certify_plan(plan_path: Path, output_root: Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    instance_id = str(plan["instance_id"])
    arm = str(plan["arm"])
    seed = int(plan["seed"])
    if arm not in {L100_CONTROL.curve_id, NL90_MILD.curve_id}:
        raise ValueError(f"unexpected E5 arm: {arm}")
    plan_without_hash = dict(plan)
    declared_plan_hash = str(plan_without_hash.pop("plan_sha256"))
    if payload_sha256(plan_without_hash) != declared_plan_hash:
        raise RuntimeError(f"HALT_E5_PLAN_HASH_MISMATCH:{plan_path}")
    base = load_china81_bundle(REPO, instance_id)
    linear_bundle = curve_bundle(base, L100_CONTROL.curve_id)
    nl_bundle = curve_bundle(base, NL90_MILD.curve_id)
    planned = solution_from_payload(plan["solution"])
    if payload_sha256(plan["solution"]) != str(plan["solution_sha256"]):
        raise RuntimeError(f"HALT_E5_SOLUTION_HASH_MISMATCH:{plan_path}")

    replay, sessions, before_hash, after_hash = project_to_nl90(planned, nl_bundle)
    if before_hash != after_hash:
        raise RuntimeError(
            f"HALT_E5_NL_REPLAY_CHANGED_DECISIONS:{instance_id}:{arm}:{seed}"
        )

    if arm == L100_CONTROL.curve_id:
        planning_check = independent_score(planned, linear_bundle)
    else:
        planning_check = independent_score(planned, nl_bundle)
    nonlinear_check = independent_score(replay, nl_bundle)
    false_feasible = bool(
        arm == L100_CONTROL.curve_id
        and planning_check["feasible"]
        and not nonlinear_check["feasible"]
    )
    categories: dict[str, int] = {}
    for violation in nonlinear_check["violations"]:
        category = cause_category(violation)
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
        "schema_version": "E5-INDEPENDENT-CERT-v1",
        "task_id": "E5-NONLINEAR-CHARGING-01",
        "instance_id": instance_id,
        "sample_role": plan["sample_role"],
        "seed": seed,
        "arm": arm,
        "plan_path": str(plan_path.relative_to(REPO)),
        "plan_sha256": file_sha256(plan_path),
        "solution_sha256": plan["solution_sha256"],
        "common_nonlinear_curve": asdict(NL90_MILD),
        "planning_physics_feasible": bool(planning_check["feasible"]),
        "planning_physics_violations": planning_check["violations"],
        "nonlinear_feasible": bool(nonlinear_check["feasible"]),
        "nonlinear_violations": nonlinear_check["violations"],
        "nonlinear_infeasibility_categories": categories,
        "linear_plan_false_feasible": false_feasible,
        "full_model_total_cost_cny": (
            float(nonlinear_check["total_cost_cny_internal"])
            if nonlinear_check["feasible"]
            else None
        ),
        "full_model_cost_breakdown_if_feasible": (
            nonlinear_check["cost_breakdown"] if nonlinear_check["feasible"] else None
        ),
        "decision_structure_sha256_before_replay": before_hash,
        "decision_structure_sha256_after_replay": after_hash,
        "decision_structure_unchanged": before_hash == after_hash,
        "replay_solution_sha256": payload_sha256(
            {
                "routes": [asdict(row) for row in replay.routes],
                "charging_actions": [asdict(row) for row in replay.charging_actions],
                "cross_site_services": [
                    asdict(row) for row in replay.cross_site_services
                ],
            }
        ),
        "sessions": sessions,
        "checker_sources": {
            str(path.relative_to(REPO)): file_sha256(path)
            for path in (
                Path(__file__).resolve(),
                REPO / "solver/src/setp_solver/check.py",
                REPO / "solver/src/setp_solver/cost.py",
                REPO / "solver/src/setp_solver/search/evaluation.py",
                REPO / "solver/src/setp_solver/china81_completion.py",
                REPO / "solver/src/setp_solver/charging_curve.py",
            )
        },
        "direct_vs_exact": {
            "planning_ledgers_match": planning_check["direct_vs_exact_ledgers_match"],
            "planning_costs_match": planning_check["direct_vs_exact_costs_match"],
            "nonlinear_ledgers_match": nonlinear_check["direct_vs_exact_ledgers_match"],
            "nonlinear_costs_match": nonlinear_check["direct_vs_exact_costs_match"],
        },
        "certificate_status": "PASS",
    }
    certificate["certificate_id"] = payload_sha256(certificate)
    out = output_root / "certificates" / f"{instance_id}__seed-{seed:02d}__{arm}.json"
    atomic_json(out, certificate)
    return {
        "instance_id": instance_id,
        "sample_role": plan["sample_role"],
        "seed": seed,
        "arm": arm,
        "certificate_path": str(out.relative_to(REPO)),
        "certificate_sha256": file_sha256(out),
        "certificate_id": certificate["certificate_id"],
        "nonlinear_feasible": int(nonlinear_check["feasible"]),
        "linear_plan_false_feasible": int(false_feasible),
        "full_model_total_cost_cny": (
            nonlinear_check["total_cost_cny_internal"]
            if nonlinear_check["feasible"]
            else "NA_INFEASIBLE"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    plans = sorted((output_root / "formal" / "plans").glob("*.json"))
    if len(plans) != 30:
        raise RuntimeError(f"HALT_E5_EXPECTED_30_FORMAL_PLANS:found={len(plans)}")
    rows = [certify_plan(path, output_root) for path in plans]
    atomic_csv(output_root / "independent_certificates.csv", rows)
    verification = {
        "schema_version": "E5-INDEPENDENT-VERIFICATION-v1",
        "task_id": "E5-NONLINEAR-CHARGING-01",
        "status": "PASS",
        "expected_certificate_count": 30,
        "certificate_count": len(rows),
        "unique_certificate_ids": len({row["certificate_id"] for row in rows}),
        "checker_executable": str(Path(__file__).resolve().relative_to(REPO)),
        "checker_executable_sha256": file_sha256(Path(__file__).resolve()),
    }
    atomic_json(output_root / "independent_verification.json", verification)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
