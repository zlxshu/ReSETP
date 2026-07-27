"""M4: does the EV saving scale with route distance and load?

M3's bound multiplied the 37 newly-eligible routes by the mean saving of the
291 routes that are *already* EV-feasible.  Those 291 are the light routes, and
light routes are plausibly also short ones, so that mean may understate what a
heavier, longer route would save once it is brought under the EV payload.

This attaches route distance and route load to every feasible EV variant from
M2, measures the relationship, and recomputes the M3 bound using a saving
predicted from the newly-eligible routes' own distances instead of a flat mean.
Read-only; no search.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from setp_solver.china81 import load_china81_bundle

REPO = Path(__file__).resolve().parents[3]
TASKS = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / "corrected_china81_rerun_v7_small_archive_ledger_20260724"
    / "full_gate/tasks"
)
OUT = Path(__file__).resolve().parent
ARM = "MV-HGS-SP"
SEED = "seed1"
CV_PAYLOAD = 1735.0
EV_PAYLOAD = 1000.0


def route_metrics(bundle, node_sequence: list[str]) -> tuple[float, float]:
    """Return (distance_metres, load_kg) for a customer-only route body."""

    demand = {
        node.node_id: float(node.demand)
        for node in bundle.instance.nodes
        if node.node_type.lower() == "c"
    }
    load = sum(demand.get(node_id, 0.0) for node_id in node_sequence)
    distance = 0.0
    for left, right in zip(node_sequence, node_sequence[1:]):
        distance += float(bundle.instance.distance(left, right))
    return distance, load


def main() -> None:
    per_route = {
        (row["instance_id"], int(row["route_index"])): row
        for row in csv.DictReader((OUT / "m2_raw_runs.csv").open(encoding="utf-8"))
        if row["status"] == "FEASIBLE"
    }
    # keep the best (most negative) delta per route
    best: dict[tuple[str, int], float] = {}
    for row in csv.DictReader((OUT / "m2_raw_runs.csv").open(encoding="utf-8")):
        if row["status"] != "FEASIBLE":
            continue
        key = (row["instance_id"], int(row["route_index"]))
        delta = float(row["delta_vs_all_cv"])
        if key not in best or delta < best[key]:
            best[key] = delta

    observed: list[dict] = []
    eligible_after_rebalance: list[dict] = []

    task_dirs = sorted(
        path
        for path in TASKS.iterdir()
        if path.name.endswith(f"__{SEED}")
        and (path / "solution_witnesses.json").is_file()
    )

    for task_dir in task_dirs:
        instance_id = task_dir.name.split("__")[1]
        witness = json.loads(
            (task_dir / "solution_witnesses.json").read_text(encoding="utf-8")
        )[ARM]
        bundle = load_china81_bundle(REPO, instance_id)
        node_lookup = {n.node_id: n for n in bundle.instance.nodes}

        # rebuild the completer's all-CV route order (same filter it uses)
        bodies: list[tuple[str, list[str]]] = []
        for route in witness["routes"]:
            customers = [
                node_id
                for node_id in route["node_sequence"]
                if node_id in node_lookup
                and node_lookup[node_id].node_type.lower() == "c"
            ]
            if customers:
                bodies.append((route["home_depot_id"], customers))

        for route_index, (depot_id, customers) in enumerate(bodies):
            sequence = [depot_id, *customers, depot_id]
            distance, load = route_metrics(bundle, sequence)
            record = {
                "instance_id": instance_id,
                "route_index": route_index,
                "depot_id": depot_id,
                "customers": len(customers),
                "distance_m": round(distance, 3),
                "load_kg": round(load, 3),
                "ev_feasible": (instance_id, route_index) in best,
                "best_delta": best.get((instance_id, route_index), ""),
            }
            if record["ev_feasible"]:
                observed.append(record)
            elif EV_PAYLOAD < load <= CV_PAYLOAD:
                eligible_after_rebalance.append(record)

    with (OUT / "m4_raw_runs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list((observed + eligible_after_rebalance)[0].keys())
        )
        writer.writeheader()
        writer.writerows(observed + eligible_after_rebalance)

    # least-squares saving = a + b * distance_km, fitted on observed EV routes
    xs = [row["distance_m"] / 1000.0 for row in observed]
    ys = [-float(row["best_delta"]) for row in observed]  # positive saving
    n = len(xs)
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx else 0.0
    intercept = mean_y - slope * mean_x
    syy = sum((y - mean_y) ** 2 for y in ys)
    r = sxy / math.sqrt(sxx * syy) if sxx and syy else 0.0

    heavy_x = [row["distance_m"] / 1000.0 for row in eligible_after_rebalance]
    predicted = [max(0.0, intercept + slope * x) for x in heavy_x]

    summary = {
        "schema": "resetp.joint-decoder-headroom.m4.v1",
        "observed_ev_feasible_routes": n,
        "observed_mean_distance_km": round(mean_x, 4),
        "observed_mean_load_kg": round(
            statistics.mean(row["load_kg"] for row in observed), 2
        ),
        "observed_mean_saving_cny": round(mean_y, 4),
        "currently_infeasible_routes_within_cv_payload": len(
            eligible_after_rebalance
        ),
        "infeasible_mean_distance_km": round(statistics.mean(heavy_x), 4)
        if heavy_x
        else None,
        "infeasible_mean_load_kg": round(
            statistics.mean(row["load_kg"] for row in eligible_after_rebalance), 2
        )
        if eligible_after_rebalance
        else None,
        "saving_vs_distance_slope_cny_per_km": round(slope, 4),
        "saving_vs_distance_intercept_cny": round(intercept, 4),
        "saving_vs_distance_pearson_r": round(r, 4),
        "predicted_mean_saving_for_heavier_routes_cny": round(
            statistics.mean(predicted), 4
        )
        if predicted
        else None,
        "flat_mean_used_by_m3_cny": round(mean_y, 4),
        "ratio_predicted_to_flat": round(
            statistics.mean(predicted) / mean_y, 4
        )
        if predicted and mean_y
        else None,
    }
    (OUT / "m4_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
