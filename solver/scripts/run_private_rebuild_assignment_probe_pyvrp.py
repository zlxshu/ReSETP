#!/usr/bin/env python3
"""Frozen PyVRP 0.12.2 health probe for one-customer depot reassignment.

This is a technical diagnostic, not a formal experiment.  It solves the four
independent depot/shift routing slices with identical iteration budgets for a
baseline assignment and a one-customer flipped assignment.  The parent
rebuild script replays every returned route with the exact private evaluator.
"""

from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from pyvrp import Model
from pyvrp.stop import MaxIterations


INSTANCE_ID = "cn-prd-50c-01-V3-TWO-SHIFT-GZ-FS"
SEEDS = (1, 2, 3, 5, 7, 11, 13, 17, 19, 23)
SHIFT_MINUTES = {"AM": (480, 660), "PM": (780, 1140)}
VOLUME_SCALE = 10
MONEY_SCALE = 1000
CV_COST_PROXY_CNY_PER_KM = 1.7542
CV_FIXED_COST_CNY = 170.0


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def solve_slice(
    orders: Sequence[Mapping[str, str]],
    nodes: Mapping[str, Mapping[str, str]],
    distance: Mapping[str, Mapping[str, str]],
    duration: Mapping[str, Mapping[str, str]],
    *,
    depot_id: str,
    shift_id: str,
    seed: int,
    max_iterations: int,
) -> dict[str, Any]:
    if not orders:
        return {"depot_id": depot_id, "shift_id": shift_id, "routes": []}
    model = Model()
    depot_row = nodes[depot_id]
    shift_start, shift_end = SHIFT_MINUTES[shift_id]
    depot = model.add_depot(
        float(depot_row["longitude"]),
        float(depot_row["latitude"]),
        tw_early=shift_start * 60,
        tw_late=shift_end * 60,
        name=depot_id,
    )
    clients = {}
    for row in orders:
        node = nodes[row["customer_id"]]
        clients[row["customer_id"]] = model.add_client(
            float(node["longitude"]),
            float(node["latitude"]),
            delivery=[
                round(float(row["source_volume_m3"]) * VOLUME_SCALE),
                round(float(row["demand_kg"])),
            ],
            service_duration=round(float(row["service_minutes"]) * 60.0),
            tw_early=round(float(row["time_window_early_minute"]) * 60.0),
            tw_late=round(float(row["time_window_late_minute"]) * 60.0),
            name=row["customer_id"],
        )
    model.add_vehicle_type(
        num_available=len(orders),
        capacity=[round(7.2 * VOLUME_SCALE), 1735],
        start_depot=depot,
        end_depot=depot,
        fixed_cost=round(CV_FIXED_COST_CNY * MONEY_SCALE),
        tw_early=shift_start * 60,
        tw_late=shift_end * 60,
        unit_distance_cost=1,
        name=f"CV_{depot_id}_{shift_id}",
    )
    locations = {depot_id: depot, **clients}
    active_ids = [depot_id, *sorted(clients)]
    for left in active_ids:
        for right in active_ids:
            if left == right:
                continue
            cost = (
                float(distance[left][right])
                / 1000.0
                * CV_COST_PROXY_CNY_PER_KM
            )
            model.add_edge(
                locations[left],
                locations[right],
                distance=max(0, round(cost * MONEY_SCALE)),
                duration=max(0, round(float(duration[left][right]))),
            )
    result = model.solve(
        MaxIterations(max_iterations),
        seed=seed,
        collect_stats=False,
        display=False,
    )
    if not result.best.is_feasible():
        raise RuntimeError(
            f"PyVRP probe returned infeasible {depot_id}/{shift_id}/seed{seed}"
        )
    location_name = {
        index: location.name
        for index, location in enumerate(model.locations)
    }
    routes = [
        [location_name[int(index)] for index in route.visits()]
        for route in result.best.routes()
        if route.visits()
    ]
    served = sorted(customer for route in routes for customer in route)
    expected = sorted(row["customer_id"] for row in orders)
    if served != expected:
        raise RuntimeError("PyVRP probe customer coverage is incomplete")
    return {
        "depot_id": depot_id,
        "shift_id": shift_id,
        "routes": routes,
        "objective_integer": int(result.cost()),
        "iterations": int(result.num_iterations),
        "runtime_seconds": float(result.runtime),
    }


def solve_arm(
    orders: Sequence[Mapping[str, str]],
    nodes: Mapping[str, Mapping[str, str]],
    distance: Mapping[str, Mapping[str, str]],
    duration: Mapping[str, Mapping[str, str]],
    *,
    target_customer: str,
    flipped: bool,
    seed: int,
    max_iterations: int,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[Mapping[str, str]]] = {}
    for row in orders:
        home = f"D_{row['city']}"
        if flipped and row["customer_id"] == target_customer:
            home = "D_foshan" if home == "D_guangzhou" else "D_guangzhou"
        groups.setdefault((home, row["shift_id"]), []).append(row)
    return [
        solve_slice(
            groups.get((depot, shift), []),
            nodes,
            distance,
            duration,
            depot_id=depot,
            shift_id=shift,
            seed=seed,
            max_iterations=max_iterations,
        )
        for depot in ("D_foshan", "D_guangzhou")
        for shift in ("AM", "PM")
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-iterations", type=int, default=2000)
    args = parser.parse_args()
    if importlib.metadata.version("pyvrp") != "0.12.2":
        raise RuntimeError("assignment probe requires frozen PyVRP 0.12.2")
    root = args.bundle_root.resolve()
    orders = [
        row for row in read_csv(root / "orders.csv")
        if row["instance_id"] == INSTANCE_ID
    ]
    nodes = {
        row["node_id"]: row
        for row in read_csv(root / "instances" / INSTANCE_ID / "nodes.csv")
    }
    matrix_root = root / "instances" / INSTANCE_ID / "cv"
    distance = {
        row["node_id"]: row
        for row in read_csv(matrix_root / "road_distance_m.csv")
    }
    duration = {
        row["node_id"]: row
        for row in read_csv(matrix_root / "road_duration_s.csv")
    }
    contestability = read_csv(root / "contestability.csv")
    candidates = [
        row for row in contestability
        if float(row["relative_gap"]) < 0.25
    ]
    target = max(candidates, key=lambda row: float(row["absolute_gap_cny"]))[
        "customer_id"
    ]
    runs = []
    for seed in SEEDS:
        runs.append(
            {
                "seed": seed,
                "baseline": solve_arm(
                    orders,
                    nodes,
                    distance,
                    duration,
                    target_customer=target,
                    flipped=False,
                    seed=seed,
                    max_iterations=args.max_iterations,
                ),
                "flipped": solve_arm(
                    orders,
                    nodes,
                    distance,
                    duration,
                    target_customer=target,
                    flipped=True,
                    seed=seed,
                    max_iterations=args.max_iterations,
                ),
            }
        )
    payload = {
        "schema": "resetp.private-rebuild-pyvrp-flip-probe.v1",
        "run_kind": "technical_health_probe_no_formal_experiment",
        "pyvrp_version": importlib.metadata.version("pyvrp"),
        "instance_id": INSTANCE_ID,
        "target_customer": target,
        "max_iterations_per_slice": args.max_iterations,
        "seeds": SEEDS,
        "runs": runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"PYVRP_ASSIGNMENT_PROBE_DONE target={target} runs={len(runs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
