#!/usr/bin/env python3
"""Run the approved 50-customer E5-B short pilot matrix."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


REPO = Path(__file__).resolve().parents[3]
PROTOTYPE = (
    REPO / "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720"
)
for entry in (REPO, REPO / "solver/src", PROTOTYPE):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from route_pool_sp import run_hgs_route_pool_recombination
from setp_solver.algorithms.resetp_alns.support.charging import (
    replay_fixed_route_charging,
)
from setp_solver.check import check_solution
from setp_solver.charging_curve import L100_CONTROL
from setp_solver.china81 import China81Bundle, load_china81_bundle
from setp_solver.cost import evaluate
from setp_solver.solution import Route, Solution

from baselines.china_e3_e7.e5_enroute_nonlinear_20260801.runtime_overlay import (
    CAPACITY_SCENARIOS_KWH,
    CURVES,
    M17_22KW_NORMAL_PWL,
    PUBLIC_POWER_SCENARIOS_KW,
    apply_runtime_overlay,
)


DEFAULT_INSTANCE_ID = "cn-prd-50c-01-V2-LOCATIONS"
SEED = 1
ARCHIVE_PER_VIEW = 2
HGS_ITERATIONS_PER_VIEW = 40
WALLCLOCK_SECONDS_PER_VIEW = 120.0
SP_SECONDS = 2.0
FLEET = REPO / "data/ChinaInstances/china81_finite_fleet_authority_v1_20260723"


def _load_initial(instance_id: str) -> Solution:
    data = json.loads(
        (FLEET / "witnesses" / f"{instance_id}.json").read_text(
            encoding="utf-8"
        )
    )
    return Solution(
        routes=[
            Route(
                str(row["vehicle_id"]),
                str(row["vehicle_type"]),
                str(row["home_depot_id"]),
                [str(value) for value in row["node_sequence"]],
            )
            for row in data["routes"]
        ]
    )


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _route_hash(solution: Solution) -> str:
    payload = json.dumps(
        [asdict(route) for route in solution.routes],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _run_unit(
    base_bundle: China81Bundle,
    initial_solution: Solution,
    capacity_kwh: float,
    curve_id: str,
    public_power_kw: float,
) -> tuple[dict[str, Any], dict[str, Any], Solution]:
    bundle = apply_runtime_overlay(
        base_bundle,
        capacity_kwh=capacity_kwh,
        curve_id=curve_id,
        public_charge_power_kw=public_power_kw,
    )
    run = run_hgs_route_pool_recombination(
        bundle,
        initial_solution,
        seed=SEED,
        hgs_seconds_per_view=None,
        exact_elites_per_view=ARCHIVE_PER_VIEW,
        max_archive_candidates_per_view=ARCHIVE_PER_VIEW,
        sp_time_limit_seconds=SP_SECONDS,
        hard_home_depot_lock=False,
        max_hgs_iterations_per_view=HGS_ITERATIONS_PER_VIEW,
        wallclock_safety_seconds_per_view=WALLCLOCK_SECONDS_PER_VIEW,
        exact_checkpoint_interval_iterations=None,
        preserve_base_pool_recombination=False,
    )
    violations = check_solution(run.solution, bundle.instance, bundle.prices)
    metrics = evaluate(
        run.solution, bundle.instance, bundle.time_profile, bundle.prices
    )
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    public_actions = [
        action for action in run.solution.charging_actions
        if nodes[action.station_id].node_type.lower() == "f"
    ]
    depot_actions = [
        action for action in run.solution.charging_actions
        if nodes[action.station_id].node_type.lower() == "d"
    ]
    if depot_actions:
        raise RuntimeError("full-battery departure produced depot precharging")
    taper_count = sum(
        action.end_energy_kwh is not None
        and float(action.end_energy_kwh) > 0.85 * capacity_kwh + 1e-9
        for action in public_actions
    )
    row = {
        "instance_id": base_bundle.instance_id,
        "seed": SEED,
        "capacity_kwh": capacity_kwh,
        "public_charge_power_kw": public_power_kw,
        "curve_id": curve_id,
        "feasible": not violations,
        "total_cost_cny": float(metrics["total_cost"]),
        "route_hash": _route_hash(run.solution),
        "route_count": len(run.solution.routes),
        "ev_route_count": sum(route.vehicle_type.lower() == "ev" for route in run.solution.routes),
        "public_charging_session_count": len(public_actions),
        "depot_charging_session_count": len(depot_actions),
        "taper_entered_session_count": taper_count,
        "station_charging_kwh": float(metrics["station_charging_kwh"]),
        "depot_charging_kwh": float(metrics["depot_charging_kwh"]),
        "complete_candidate_evaluations": int(run.stats["complete_candidate_evaluation_attempts"]),
        "elapsed_seconds": float(run.elapsed_seconds),
        "violation_count": len(violations),
    }
    detail = {
        "row": row,
        "violations": [asdict(item) for item in violations],
        "cost_breakdown": metrics,
        "completion_activity": run.completion.activity,
        "solution": asdict(run.solution),
    }
    return row, detail, run.solution


def _recheck_linear_routes_under_m17(
    base_bundle: China81Bundle,
    solution: Solution,
    *,
    capacity_kwh: float,
    public_power_kw: float,
) -> dict[str, Any]:
    bundle = apply_runtime_overlay(
        base_bundle,
        capacity_kwh=capacity_kwh,
        curve_id=M17_22KW_NORMAL_PWL.curve_id,
        public_charge_power_kw=public_power_kw,
    )
    replayed = replay_fixed_route_charging(
        replace(solution, charging_actions=[]),
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
        strategy="aware",
    )
    violations = check_solution(replayed, bundle.instance, bundle.prices)
    metrics = evaluate(replayed, bundle.instance, bundle.time_profile, bundle.prices)
    return {
        "linear_routes_m17_recheck_feasible": not violations,
        "linear_routes_m17_recheck_total_cost_cny": float(metrics["total_cost"]),
        "linear_routes_m17_recheck_violation_count": len(violations),
        "linear_routes_m17_recheck_violation_types": "|".join(item.type for item in violations),
    }


def run_pilot(
    instance_id: str,
    capacities: tuple[float, ...],
    public_powers: tuple[float, ...],
    output_dir: Path,
) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    units = output_dir / "units"
    units.mkdir(parents=True, exist_ok=True)
    base_bundle = load_china81_bundle(REPO, instance_id)
    initial_solution = _load_initial(instance_id)
    rows: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []

    for power in public_powers:
        for capacity in capacities:
            pair = {
                curve_id: _run_unit(
                    base_bundle,
                    initial_solution,
                    capacity,
                    curve_id,
                    power,
                )
                for curve_id in CURVES
            }
            recheck = _recheck_linear_routes_under_m17(
                base_bundle,
                pair[L100_CONTROL.curve_id][2],
                capacity_kwh=capacity,
                public_power_kw=power,
            )
            for curve_id, (row, detail, _) in pair.items():
                row.update(recheck)
                detail["linear_routes_m17_recheck"] = recheck
                rows.append(row)
                _write_json(
                    units / f"P{power:g}__B{capacity:g}__{curve_id}.json",
                    detail,
                )
            linear = pair[L100_CONTROL.curve_id][0]
            nonlinear = pair[M17_22KW_NORMAL_PWL.curve_id][0]
            comparisons.append(
                {
                    "public_charge_power_kw": power,
                    "capacity_kwh": capacity,
                    "feasibility_differs": bool(linear["feasible"]) != bool(nonlinear["feasible"]),
                    "route_hash_differs": linear["route_hash"] != nonlinear["route_hash"],
                    "nonlinear_minus_linear_cost_cny": float(nonlinear["total_cost_cny"])
                    - float(linear["total_cost_cny"]),
                    **recheck,
                }
            )

    with (output_dir / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    metadata = {
        "task_id": "E5-ENROUTE-NONLINEAR-PILOT-20260801",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "evidence_role": "NONFORMAL_FEASIBILITY_EXPOSURE_PILOT",
        "instance_id": instance_id,
        "seed": SEED,
        "capacities_kwh": list(capacities),
        "public_power_kw": list(public_powers),
        "power_roles": {
            "22.0": "Montoya/Froger absolute-power main scenario",
            "60.0": "unchanged China81 public-power sensitivity",
        },
        "curves": {name: asdict(spec) for name, spec in CURVES.items()},
        "full_battery_departure": True,
        "search": {
            "archive_per_view": ARCHIVE_PER_VIEW,
            "hgs_iterations_per_view": HGS_ITERATIONS_PER_VIEW,
            "wallclock_seconds_per_view": WALLCLOCK_SECONDS_PER_VIEW,
            "set_partitioning_seconds": SP_SECONDS,
        },
        "original_public_station_power_kw": {
            node.node_id: float(node.charge_power_kw)
            for node in base_bundle.instance.nodes
            if node.node_type.lower() == "f"
        },
        "sources": [
            "Montoya et al. (2017), PDF pp.3-4 and 13",
            "Froger et al. (2019), author manuscript p.4 Fig.1",
            "Xiao (2021), p.18",
        ],
    }
    decision = {
        "status": "NONFORMAL_SHORT_PILOT_COMPLETE",
        "unit_count": len(rows),
        "feasible_unit_count": sum(bool(row["feasible"]) for row in rows),
        "pairs_with_route_difference": sum(
            bool(item["route_hash_differs"]) for item in comparisons
        ),
        "pairs_with_feasibility_difference": sum(
            bool(item["feasibility_differs"]) for item in comparisons
        ),
        "m17_rows_entering_taper": sum(
            row["curve_id"] == M17_22KW_NORMAL_PWL.curve_id
            and int(row["taper_entered_session_count"]) > 0
            for row in rows
        ),
        "max_unit_elapsed_seconds": max(float(row["elapsed_seconds"]) for row in rows),
        "pair_comparisons": comparisons,
    }
    _write_json(output_dir / "metadata.json", metadata)
    _write_json(output_dir / "decision.json", decision)
    (output_dir / "report.md").write_text(
        "# E5-B 非正式短矩阵\n\n"
        f"共 {len(rows)} 个单元，{decision['feasible_unit_count']} 个可行；"
        f"{decision['pairs_with_route_difference']} 对路线不同，"
        f"{decision['pairs_with_feasibility_difference']} 对可行性不同；"
        f"{decision['m17_rows_entering_taper']} 个 M17 单元进入 85% 以上折减段。\n",
        encoding="utf-8",
    )
    hashes = {
        str(path.relative_to(output_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output_dir.rglob("*"))
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    _write_json(output_dir / "artifact_hashes.json", hashes)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-id", default=DEFAULT_INSTANCE_ID)
    parser.add_argument("--output-name", default="pilot02")
    parser.add_argument("--capacities", nargs="+", type=float, default=list(CAPACITY_SCENARIOS_KWH))
    parser.add_argument(
        "--public-powers",
        nargs="+",
        type=float,
        default=list(PUBLIC_POWER_SCENARIOS_KW),
    )
    args = parser.parse_args()
    capacities = tuple(float(value) for value in args.capacities)
    powers = tuple(float(value) for value in args.public_powers)
    for values, allowed, label in (
        (capacities, CAPACITY_SCENARIOS_KWH, "capacities"),
        (powers, PUBLIC_POWER_SCENARIOS_KW, "public powers"),
    ):
        if any(value not in allowed for value in values):
            parser.error(f"{label} must come from {allowed}")
    output_dir = Path(__file__).resolve().parent / args.output_name
    rows = run_pilot(args.instance_id, capacities, powers, output_dir)
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "unit_count": len(rows),
                "feasible_unit_count": sum(bool(row["feasible"]) for row in rows),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
