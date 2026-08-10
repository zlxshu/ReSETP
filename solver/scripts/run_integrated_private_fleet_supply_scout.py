#!/usr/bin/env python3
"""Isolated fleet-supply scout for the current independent private HGS.

This is not a formal experiment and does not modify China81.  It compares
the current 25-percent typed fleet, the certified fixed-total 50-percent
fleet, and a model-consistent pool in which either type is sufficiently
available while the original total-use cap remains binding.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import traceback
from dataclasses import asdict, replace
from pathlib import Path
from types import MappingProxyType

from run_integrated_private_component_scout import (
    SEED,
    _private_accounting_payload,
    _run_arm,
    _served,
    _write_failure_package,
)
from run_problem_hgs_private_technical import (
    PROTECTED,
    _build_context,
    _json,
    _policy,
    _prepare_population,
    _sha256,
)
from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator
from setp_solver.algorithms.problem_hgs.model import (
    DutyIndividual,
    PhysicalVehicleDuty,
)
from setp_solver.china81_completion import complete_china81_route_skeleton
from setp_solver.search.metaheuristic_baselines import solution_to_dict
from setp_solver.solution import Route, Solution


ARM_LEVELS = {
    "CURRENT_25": "25",
    "FIXED_TOTAL_50": "50",
    "BOTH_TYPES_AVAILABLE": "50",
}


def _load_witness(repo: Path, bundle) -> dict:
    path = repo / bundle.fleet_authority / "witnesses" / f"{bundle.instance_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if str(payload.get("instance_id")) != bundle.instance_id:
        raise RuntimeError("finite-fleet witness belongs to another instance")
    return payload


def _witness_skeleton(bundle, witness: dict, level_name: str) -> Solution:
    level = witness.get("levels", {}).get(level_name)
    if not isinstance(level, dict):
        raise TypeError(f"finite-fleet witness has no level {level_name}")
    if level.get("status") != "CERTIFIED" or level.get("violations"):
        raise RuntimeError(f"finite-fleet level {level_name} is not certified")

    routes: list[Route] = []
    for depot_id, depot in sorted(level["depots"].items()):
        for vehicle_type in ("cv", "ev"):
            chain_by_route = {
                str(route_id): chain_index
                for chain_index, chain in enumerate(
                    depot[f"{vehicle_type}_cover"]["chains"],
                    start=1,
                )
                for route_id in chain
            }
            for timed in depot[f"{vehicle_type}_routes"]:
                route_id = str(timed["route_id"])
                if route_id not in chain_by_route:
                    raise RuntimeError(
                        f"certified route {route_id} is missing from its physical cover"
                    )
                routes.append(
                    Route(
                        vehicle_id=(
                            f"FLEET-SCOUT-{depot_id}-{vehicle_type.upper()}-"
                            f"{chain_by_route[route_id]:03d}"
                        ),
                        vehicle_type=vehicle_type,
                        home_depot_id=depot_id,
                        node_sequence=[
                            depot_id,
                            *[str(customer) for customer in timed["customers"]],
                            depot_id,
                        ],
                    )
                )
    return Solution(routes=routes)


def _bundle_for_arm(bundle, witness: dict, arm: str, level_name: str):
    level = witness["levels"][level_name]
    caps = {}
    for depot_id, current in sorted(bundle.fleet_caps_by_depot.items()):
        total = int(current["total_fleet_cap"])
        if arm == "CURRENT_25":
            changed = dict(current)
        elif arm == "FIXED_TOTAL_50":
            depot = level["depots"][depot_id]
            changed = {
                **dict(current),
                "num_cv": int(depot["cv_cap"]),
                "num_ev": int(depot["ev_cap"]),
                "total_fleet_cap": int(depot["total_cap"]),
            }
        elif arm == "BOTH_TYPES_AVAILABLE":
            # Each type can fill every original vehicle slot, but the number
            # actually used across both types cannot exceed the original cap.
            changed = {
                **dict(current),
                "num_cv": total,
                "num_ev": total,
                "total_fleet_cap": total,
            }
        else:
            raise ValueError(f"unknown arm: {arm}")
        caps[depot_id] = MappingProxyType(changed)
    return replace(
        bundle,
        instance=replace(
            bundle.instance,
            num_cv=sum(int(row["num_cv"]) for row in caps.values()),
            num_ev=sum(int(row["num_ev"]) for row in caps.values()),
        ),
        fleet_caps_by_depot=MappingProxyType(caps),
    )


def _with_available_assets(individual: DutyIndividual, bundle) -> DutyIndividual:
    """Register typed candidates; exact evaluation limits actual total use."""

    by_id = {duty.physical_vehicle_id: duty for duty in individual.duties}
    for depot_id, caps in sorted(bundle.fleet_caps_by_depot.items()):
        expected_ids = set()
        for vehicle_type, field in (("cv", "num_cv"), ("ev", "num_ev")):
            for index in range(1, int(caps[field]) + 1):
                vehicle_id = f"{vehicle_type.upper()}_{depot_id}_{index}"
                expected_ids.add(vehicle_id)
                by_id.setdefault(
                    vehicle_id,
                    PhysicalVehicleDuty(
                        physical_vehicle_id=vehicle_id,
                        vehicle_type=vehicle_type,
                        home_depot_id=depot_id,
                        trips=(),
                    ),
                )
        actual_ids = {
            duty.physical_vehicle_id
            for duty in individual.duties
            if duty.home_depot_id == depot_id
        }
        unexpected = actual_ids.difference(expected_ids)
        if unexpected:
            raise RuntimeError(
                "completed solution uses unregistered physical vehicles: "
                + ", ".join(sorted(unexpected))
            )
    return replace(
        individual,
        duties=tuple(by_id[duty_id] for duty_id in sorted(by_id)),
        source="fleet-supply-scout",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--arm", choices=tuple(ARM_LEVELS), required=True)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--max-runtime-seconds", type=float, default=180.0)
    parser.add_argument(
        "--route-only",
        action="store_true",
        help="disable problem-mechanism refinement for a route-layer ablation",
    )
    parser.add_argument(
        "--skip-charging-refinement",
        action="store_true",
        help=(
            "keep the problem mechanisms but skip the optional exhaustive "
            "charging-refinement layer"
        ),
    )
    args = parser.parse_args()
    if args.iterations < 1:
        raise ValueError("iterations must be positive")
    if not 0 < args.max_runtime_seconds <= 1200:
        raise ValueError("runtime must be in (0, 1200] seconds")
    search_mode = (
        "ROUTE_ONLY"
        if args.route_only
        else (
            "FULL_PROBLEM_COMPONENTS_NO_CHARGING_REFINEMENT"
            if args.skip_charging_refinement
            else "FULL_PROBLEM_COMPONENTS"
        )
    )

    repo = Path(__file__).resolve().parents[2]
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    protected_before = {path: _sha256(repo / path) for path in PROTECTED}
    _json(
        output / "metadata.json",
        {
            "status": "RUNNING",
            "purpose": "isolated fleet-supply scout; not formal",
            "instance_id": args.instance_id,
            "arm": args.arm,
            "search_mode": search_mode,
            "seed": SEED,
            "iterations": args.iterations,
            "max_runtime_seconds_per_arm": args.max_runtime_seconds,
            "fairness_enabled": False,
            "formal_model_or_instance_modified": False,
            "protected_hashes_before": protected_before,
        },
    )

    base_bundle, _base_initial, _pi0, base_context = _build_context(
        repo, args.instance_id
    )
    witness = _load_witness(repo, base_bundle)
    rows: list[dict[str, object]] = []
    solutions = {}

    arm = args.arm
    level_name = ARM_LEVELS[arm]
    bundle = _bundle_for_arm(base_bundle, witness, arm, level_name)
    skeleton = _witness_skeleton(bundle, witness, level_name)
    completed = complete_china81_route_skeleton(skeleton, bundle).solution
    initial = _with_available_assets(DutyIndividual.from_solution(completed), bundle)
    context = replace(base_context, bundle=bundle, fairness_enabled=False)
    evaluator = DutyFullEvaluator(context)
    candidates, *_rest = _prepare_population(
        initial,
        evaluator,
        _policy(evaluator),
        require_distinct_selection=False,
    )
    result, accounting, arm_initial = _run_arm(
        initial_candidates=candidates,
        context=context,
        iterations=args.iterations,
        max_runtime_seconds=args.max_runtime_seconds,
        include_mechanisms=not args.route_only,
        include_charging_candidates=(
            not args.route_only and not args.skip_charging_refinement
        ),
    )
    selected = result.best.evaluation
    if selected.full is None:
        raise RuntimeError(f"{arm} ended without a complete evaluation")
    served_count, served_demand, total_count, total_demand = _served(
        selected.individual, bundle
    )
    if not (
        selected.full.feasible
        and served_count == total_count
        and abs(served_demand - total_demand) <= 1e-9
    ):
        raise RuntimeError(f"{arm} did not preserve feasible complete service")
    row: dict[str, object] = {
        "instance_id": args.instance_id,
        "arm": arm,
        "search_mode": search_mode,
        "seed": SEED,
        "iterations": result.accounting.iterations,
        "runtime_seconds": result.accounting.elapsed_seconds,
        "initial_total_cost_cny": arm_initial.total_cost,
        "total_cost_cny": selected.full.total_cost,
        "total_emissions_kg": selected.full.breakdown["E_total"],
        "cv_direct_emissions_kg": selected.full.breakdown["E_cv_direct"],
        "ev_indirect_emissions_kg": selected.full.breakdown["E_ev_indirect"],
        "used_cv": selected.full.breakdown["n_veh_cv"],
        "used_ev": selected.full.breakdown["n_veh_ev"],
        "electricity_kwh": selected.full.breakdown["electricity_kwh"],
        "customers_served": served_count,
        "customers_total": total_count,
        "demand_served": served_demand,
        "demand_total": total_demand,
        "caps_by_depot_json": json.dumps(
            {key: dict(value) for key, value in bundle.fleet_caps_by_depot.items()},
            ensure_ascii=False,
            sort_keys=True,
        ),
        "individual_fingerprint": selected.individual.fingerprint,
    }
    rows.append(row)
    solutions[arm] = {
        "individual": asdict(selected.individual),
        "evaluation": {
            "total_cost": selected.full.total_cost,
            "breakdown": dict(selected.full.breakdown),
            "feasible": selected.full.feasible,
            "prepared_solution": solution_to_dict(selected.full.prepared_solution),
        },
        "run_accounting": asdict(result.accounting),
        "private_accounting": _private_accounting_payload(accounting),
    }

    protected_after = {path: _sha256(repo / path) for path in PROTECTED}
    if protected_before != protected_after:
        raise RuntimeError("protected evaluator files changed during the scout")
    with (output / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _json(output / "best_solutions.json", solutions)
    _json(
        output / "decision.json",
        {
            "verdict": "TECHNICAL_FLEET_SUPPLY_SCOUT_COMPLETE",
            "formal_experiment": False,
            "instance_id": args.instance_id,
            "search_mode": search_mode,
            "rows": rows,
            "service_and_demand_equal": True,
            "formal_model_or_instance_modified": False,
        },
    )
    (output / "report.md").write_text(
        "# 车队供给方式隔离短试\n\n"
        "本包比较当前25%供给、固定总量的50%供给与两类车均可充分候选。"
        "第三种情景仍保留原车场实际用车总上限。这是技术短试，没有修改正式算例。\n",
        encoding="utf-8",
    )
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    metadata["status"] = "COMPLETE"
    metadata["protected_hashes_after"] = protected_after
    _json(output / "metadata.json", metadata)
    _json(
        output / "artifact_hashes.json",
        {
            path.name: _sha256(path)
            for path in sorted(output.iterdir())
            if path.is_file() and path.name != "artifact_hashes.json"
        },
    )
    print(json.dumps({"output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    requested_output = (
        None
        if len(sys.argv) < 2 or sys.argv[1].startswith("-")
        else Path(sys.argv[1]).resolve()
    )
    try:
        raise SystemExit(main())
    except Exception as error:
        if requested_output is not None:
            _write_failure_package(requested_output, error)
        traceback.print_exc()
        raise
