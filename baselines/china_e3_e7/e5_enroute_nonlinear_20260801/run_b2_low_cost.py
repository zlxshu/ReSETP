#!/usr/bin/env python3
"""Run the approved original-vehicle E5-B2 low-cost diagnostic."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
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

from setp_solver.check import check_solution
from setp_solver.charging_curve import L100_CONTROL
from setp_solver.china81 import load_china81_bundle
from setp_solver.cost import evaluate
from setp_solver.solution import Route, Solution

from baselines.china_e3_e7.e5_enroute_nonlinear_20260801.b2_low_cost_hook import (
    B2_CHARGE_AMOUNT_STRATEGIES,
    b2_completion_hook,
)
from baselines.china_e3_e7.e5_enroute_nonlinear_20260801.runtime_overlay import (
    M17_22KW_NORMAL_PWL,
    apply_b2_sensitivity_foundation,
)


INSTANCE_IDS = (
    "cn-prd-50c-01-V2-LOCATIONS",
    "cn-prd-100c-02-V2-LOCATIONS",
)
CURVE_IDS = (
    L100_CONTROL.curve_id,
    M17_22KW_NORMAL_PWL.curve_id,
)
SEED = 1
ARCHIVE_PER_VIEW = 2
HGS_ITERATIONS_PER_VIEW = 40
WALLCLOCK_SECONDS_PER_VIEW = 120.0
SP_SECONDS = 2.0
FLEET = (
    REPO / "data/ChinaInstances/china81_finite_fleet_authority_v1_20260723"
)


def _load_initial(instance_id: str) -> Solution:
    payload = json.loads(
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
            for row in payload["routes"]
        ]
    )


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _route_hash(solution: Solution) -> str:
    return hashlib.sha256(
        json.dumps(
            [asdict(route) for route in solution.routes],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _run_unit(instance_id: str, curve_id: str) -> dict[str, Any]:
    from route_pool_sp import run_hgs_route_pool_recombination

    base = load_china81_bundle(REPO, instance_id)
    bundle = apply_b2_sensitivity_foundation(base, curve_id=curve_id)
    if (
        bundle.instance.vehicle_parameters
        != base.instance.vehicle_parameters
        or bundle.prices.B_battery_kwh != base.prices.B_battery_kwh
        or bundle.prices.initial_ev_battery_kwh
        != base.prices.initial_ev_battery_kwh
    ):
        raise RuntimeError("E5-B2 changed the original vehicle or initial SOC")
    initial = _load_initial(instance_id)
    with b2_completion_hook():
        run = run_hgs_route_pool_recombination(
            bundle,
            initial,
            seed=SEED,
            hgs_seconds_per_view=None,
            exact_elites_per_view=ARCHIVE_PER_VIEW,
            max_archive_candidates_per_view=ARCHIVE_PER_VIEW,
            sp_time_limit_seconds=SP_SECONDS,
            hard_home_depot_lock=False,
            max_hgs_iterations_per_view=HGS_ITERATIONS_PER_VIEW,
            wallclock_safety_seconds_per_view=(
                WALLCLOCK_SECONDS_PER_VIEW
            ),
            exact_checkpoint_interval_iterations=None,
            preserve_base_pool_recombination=False,
        )
    violations = check_solution(
        run.solution,
        bundle.instance,
        bundle.prices,
    )
    metrics = evaluate(
        run.solution,
        bundle.instance,
        bundle.time_profile,
        bundle.prices,
    )
    nodes = {node.node_id: node for node in bundle.instance.nodes}
    public_actions = [
        action
        for action in run.solution.charging_actions
        if nodes[action.station_id].node_type.lower() == "f"
    ]
    capacity = bundle.instance.battery_capacity_kwh(
        fallback=bundle.prices.B_battery_kwh
    )
    return {
        "instance_id": instance_id,
        "seed": SEED,
        "curve_id": curve_id,
        "formal_result": False,
        "battery_capacity_kwh": capacity,
        "initial_ev_battery_kwh": bundle.prices.initial_ev_battery_kwh,
        "route_time_cost_per_hour": (
            bundle.prices.route_time_cost_per_hour
        ),
        "charge_amount_strategies": "|".join(
            B2_CHARGE_AMOUNT_STRATEGIES
        ),
        "status": "OK" if not violations else "VIOLATION",
        "violation_count": len(violations),
        "total_cost_cny": float(metrics["total_cost"]),
        "route_hash": _route_hash(run.solution),
        "route_count": len(run.solution.routes),
        "ev_route_count": sum(
            route.vehicle_type.lower() == "ev"
            for route in run.solution.routes
        ),
        "charging_action_count": len(run.solution.charging_actions),
        "public_charging_action_count": len(public_actions),
        "public_actions_over_85pct": sum(
            action.end_energy_kwh is not None
            and float(action.end_energy_kwh) > 0.85 * capacity + 1e-9
            for action in public_actions
        ),
        "complete_candidate_evaluations": int(
            run.stats["complete_candidate_evaluation_attempts"]
        ),
        "elapsed_seconds": float(run.elapsed_seconds),
        "selected_charge_amount_strategies": "|".join(
            sorted(
                {
                    str(item["charge_amount_strategy"])
                    for item in (
                        *run.completion.activity.get(
                            "mandatory_fleet_assignments", []
                        ),
                        *run.completion.activity.get(
                            "accepted_variants", []
                        ),
                    )
                }
            )
        ),
    }


def _report(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# E5-B2 原车型低成本诊断",
        "",
        "本诊断保持 China81 原车型、77.28 kWh 电池、默认初始电量和算例不变。",
        "两条曲线使用相同充电量策略和相同种子、评价预算；formal_result=false。",
        "",
        "| 算例 | 曲线 | 状态 | 成本 | EV路线 | 公共站充电 | 超85%公共站充电 |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['instance_id']} | {row['curve_id']} | "
            f"{row['status']} | {row['total_cost_cny']:.6f} | "
            f"{row['ev_route_count']} | "
            f"{row['public_charging_action_count']} | "
            f"{row['public_actions_over_85pct']} |"
        )
    return "\n".join(lines) + "\n"


def run_b2_low_cost(output_dir: Path) -> list[dict[str, Any]]:
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    rows = [
        _run_unit(instance_id, curve_id)
        for instance_id in INSTANCE_IDS
        for curve_id in CURVE_IDS
    ]
    with (output_dir / "raw_runs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    metadata = {
        "task_id": "E5-B2-LOW-COST-DIAGNOSTIC-20260801",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "formal_result": False,
        "instance_ids": list(INSTANCE_IDS),
        "seed": SEED,
        "curve_ids": list(CURVE_IDS),
        "charge_amount_strategies": list(
            B2_CHARGE_AMOUNT_STRATEGIES
        ),
        "battery_capacity_kwh": 77.28,
        "initial_ev_battery_kwh": 0.0,
        "search": {
            "archive_per_view": ARCHIVE_PER_VIEW,
            "hgs_iterations_per_view": HGS_ITERATIONS_PER_VIEW,
            "wallclock_seconds_per_view": (
                WALLCLOCK_SECONDS_PER_VIEW
            ),
            "set_partitioning_seconds": SP_SECONDS,
        },
    }
    decision = {
        "status": "DIAGNOSTIC_COMPLETE_NOT_FORMAL",
        "formal_result": False,
        "expected_row_count": len(INSTANCE_IDS) * len(CURVE_IDS),
        "row_count": len(rows),
        "all_rows_retained": len(rows)
        == len(INSTANCE_IDS) * len(CURVE_IDS),
        "ok_row_count": sum(row["status"] == "OK" for row in rows),
    }
    _write_json(output_dir / "metadata.json", metadata)
    _write_json(output_dir / "decision.json", decision)
    (output_dir / "report.md").write_text(
        _report(rows), encoding="utf-8"
    )
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output_dir.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    _write_json(output_dir / "artifact_hashes.json", hashes)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=(
            Path(__file__).resolve().parent
            / "b2_low_cost_diagnostic_20260801"
        ),
    )
    args = parser.parse_args()
    rows = run_b2_low_cost(args.output_dir)
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "row_count": len(rows),
                "formal_result": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
