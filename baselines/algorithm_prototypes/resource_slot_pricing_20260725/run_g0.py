#!/usr/bin/env python3
"""Run the single frozen six-task resource-slot pricing G0."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
from typing import Any

from china81_columns import materialize_columns
from common import (
    ENGINEERING,
    OUTPUT,
    artifact_hashes,
    load_bundle,
    load_registered_solutions,
    peak_rss_bytes,
    read_json,
    set_single_thread_environment,
    solution_payload,
    verify_registration,
    write_csv,
    write_json,
)
from fleet_assignment_dp import _station_charger_caps
from mip_core import solve_route_columns
from pair_core import build_parent_route_pool
from pricing_core import fleet_caps, generate_priced_routes
from setp_solver.check import check_solution
from setp_solver.china81_completion import exact_china81_score


def exact_replay(solution: Any, bundle: Any, label: str) -> float:
    objective, _, exact_violations = exact_china81_score(solution, bundle)
    direct_violations = check_solution(
        solution,
        bundle.instance,
        bundle.prices,
    )
    if exact_violations or direct_violations:
        raise RuntimeError(
            f"{label} infeasible: exact={len(exact_violations)}, "
            f"direct={len(direct_violations)}"
        )
    return float(objective)


def run_one(task: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    set_single_thread_environment()
    started = time.perf_counter()
    bundle = load_bundle(task["instance_id"])
    start, parents = load_registered_solutions(task)
    start_objective = exact_replay(start, bundle, "start")
    if not math.isclose(
        start_objective,
        float(task["start_expected_objective"]),
        rel_tol=0.0,
        abs_tol=1.0e-9,
    ):
        raise RuntimeError("registered HGS-M start objective drift")
    customers, parent_columns = build_parent_route_pool(parents, bundle)
    pricing = generate_priced_routes(
        start,
        parents,
        bundle,
        lane=task["lane"],
        max_extensions=int(config["max_label_extensions"]),
        max_routes=int(config["max_generated_routes"]),
        wall_seconds=float(config["task_wall_seconds"]),
    )
    columns = (*parent_columns, *pricing.columns)
    mip = solve_route_columns(
        customers,
        columns,
        fleet_caps=fleet_caps(bundle),
        charger_caps=_station_charger_caps(bundle),
        time_limit_seconds=float(config["mip_time_limit_seconds"]),
    )
    if not mip.selected:
        raise RuntimeError(
            f"route-column assembly rejected: {mip.status_class}: {mip.message}"
        )
    candidate = materialize_columns(mip.selected, bundle)
    output_objective = exact_replay(candidate, bundle, "output")
    if time.perf_counter() - started > float(config["task_wall_seconds"]):
        raise TimeoutError("registered 60-second safety limit reached")
    generated_selected = [
        column
        for column in mip.selected
        if column.source.startswith("resource_slot_pricing_")
    ]
    changed_selected = [
        column
        for column in generated_selected
        if column.payload["changed_adjacencies"]
    ]
    negative_selected = [
        column
        for column in generated_selected
        if float(column.payload["reduced_cost"]) < -1.0e-7
    ]
    attributed_selected = [
        column
        for column in generated_selected
        if bool(column.payload["resource_rank_changed"])
    ]
    wall = time.perf_counter() - started
    witness_path = OUTPUT / "witnesses" / f"{task['task_id']}.json"
    write_json(
        witness_path,
        {
            "schema": "resetp.resource-slot-pricing-witness.v1",
            "task_id": task["task_id"],
            "instance_id": task["instance_id"],
            "lane": task["lane"],
            "start": solution_payload(start),
            "output": solution_payload(candidate),
            "start_objective": start_objective,
            "output_objective": output_objective,
        },
    )
    return {
        "task_id": task["task_id"],
        "instance_id": task["instance_id"],
        "lane": task["lane"],
        "status": "OK",
        "start_seed": task["start_seed"],
        "start_objective": start_objective,
        "output_objective": output_objective,
        "improvement_pct": (
            100.0 * (start_objective - output_objective) / start_objective
        ),
        "strict_improvement": output_objective < start_objective - 1.0e-9,
        "generated_routes": len(pricing.columns),
        "selected_generated_routes": len(generated_selected),
        "selected_negative_routes": len(negative_selected),
        "selected_changed_adjacency_routes": len(changed_selected),
        "selected_resource_rank_changed_routes": len(attributed_selected),
        "label_extensions": pricing.extensions,
        "complete_labels": pricing.complete_labels,
        "complete_candidate_evaluations": 1,
        "wall_seconds": wall,
        "mip_status": mip.status_class,
        "mip_gap": mip.mip_gap,
        "mip_dual_bound": mip.dual_bound,
        "lp_primal_residual": pricing.lp_primal_residual,
        "lp_stationarity_residual": pricing.lp_stationarity_residual,
        "positive_resource_prices": pricing.positive_resource_prices,
        "violation_count": 0,
        "peak_rss_bytes": peak_rss_bytes(),
        "witness_path": witness_path.relative_to(
            Path(__file__).resolve().parents[3]
        ).as_posix(),
        "error": "",
    }


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"G0 output exists: {OUTPUT}")
    engineering = read_json(ENGINEERING / "decision.json")
    if not engineering.get("pass"):
        raise RuntimeError("engineering gate did not pass")
    registration = verify_registration()
    config = registration["config"]
    OUTPUT.mkdir(parents=True)
    write_json(
        OUTPUT / "metadata.json",
        {
            "schema": "resetp.resource-slot-pricing-g0.v1",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "workers": int(config["workers"]),
            "tasks": len(registration["tasks"]),
            "claim_boundary": registration["claim_boundary"],
        },
    )
    rows = []
    failures = []
    with ProcessPoolExecutor(max_workers=int(config["workers"])) as pool:
        futures = {
            pool.submit(run_one, task, config): task
            for task in registration["tasks"]
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:  # noqa: BLE001
                message = f"{task['task_id']}: {type(exc).__name__}: {exc}"
                failures.append(message)
                rows.append(
                    {
                        "task_id": task["task_id"],
                        "instance_id": task["instance_id"],
                        "lane": task["lane"],
                        "status": "ERROR",
                        "violation_count": 1,
                        "error": message,
                    }
                )
    rows.sort(key=lambda row: row["task_id"])
    write_csv(OUTPUT / "raw_runs.csv", rows)
    write_json(
        OUTPUT / "run_status.json",
        {
            "schema": "resetp.resource-slot-pricing-run-status.v1",
            "failures": failures,
            "completed_rows": sum(row["status"] == "OK" for row in rows),
            "expected_rows": 6,
        },
    )
    print(json.dumps({"rows": len(rows), "failures": failures}, ensure_ascii=False))
    return 0 if not failures and len(rows) == 6 else 2


if __name__ == "__main__":
    raise SystemExit(main())
