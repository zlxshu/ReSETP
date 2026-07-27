"""M3: how much electrification the capacity slack could support.

M2 showed every EV-feasible route is cheaper as an EV (291/291) and that every
rejection is a CAPACITY rejection: the EV carries 1000 kg against the diesel
truck's 1735 kg.  Routes come out of a search that packs toward the diesel
capacity, so most of them are too heavy for the vehicle that would be cheaper.

This computes, per instance, how many routes *could* be brought under the EV
payload by redistributing load across the existing routes -- same route count,
no extra vehicle, no new fixed cost.  With N routes carrying total load L, the
number k of routes that can sit at or below the EV payload satisfies

    k * ev_payload + (N - k) * cv_payload >= L
    =>  k <= (N * cv_payload - L) / (cv_payload - ev_payload)

and k is additionally capped by the depot's registered EV slots.

This is a relaxation: it ignores geography, time windows and depot ownership,
so it is an upper bound on what a joint decoder could reach, not a forecast.
It is reported as a bound and must never be quoted as an achieved result.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

from setp_solver.china81 import load_china81_bundle
from setp_solver.solution import ChargingAction, Route, Solution

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
# Mean complete-model saving of one CV->EV conversion measured in M2.
MEAN_SAVING_PER_CONVERSION = 60.9723


def main() -> None:
    rows: list[dict] = []

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
        demand = {
            node.node_id: float(node.demand)
            for node in bundle.instance.nodes
            if node.node_type.lower() == "c"
        }

        by_depot: dict[str, list[float]] = defaultdict(list)
        ev_now: dict[str, int] = defaultdict(int)
        for route in witness["routes"]:
            load = sum(
                demand.get(node_id, 0.0)
                for node_id in route["node_sequence"]
            )
            by_depot[route["home_depot_id"]].append(load)
            if route["vehicle_type"].lower() == "ev":
                ev_now[route["home_depot_id"]] += 1

        for depot_id in sorted(by_depot):
            loads = by_depot[depot_id]
            n_routes = len(loads)
            total_load = sum(loads)
            ev_cap = int(bundle.fleet_caps_by_depot[depot_id]["num_ev"])

            slack_bound = (n_routes * CV_PAYLOAD - total_load) / (
                CV_PAYLOAD - EV_PAYLOAD
            )
            k_by_slack = max(0, math.floor(slack_bound + 1e-9))
            k_bound = min(k_by_slack, ev_cap, n_routes)
            already_light = sum(1 for load in loads if load <= EV_PAYLOAD)

            rows.append(
                {
                    "instance_id": instance_id,
                    "depot_id": depot_id,
                    "routes": n_routes,
                    "total_load_kg": round(total_load, 3),
                    "mean_route_load_kg": round(total_load / n_routes, 3),
                    "capacity_utilisation_vs_cv": round(
                        total_load / (n_routes * CV_PAYLOAD), 6
                    ),
                    "routes_already_under_ev_payload": already_light,
                    "ev_routes_in_sealed_solution": ev_now[depot_id],
                    "num_ev_slots": ev_cap,
                    "k_bound_by_capacity_slack": k_by_slack,
                    "k_bound_final": k_bound,
                    "additional_ev_routes_available": max(
                        0, k_bound - ev_now[depot_id]
                    ),
                }
            )

    with (OUT / "m3_raw_runs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    ev_now_total = sum(int(r["ev_routes_in_sealed_solution"]) for r in rows)
    bound_total = sum(int(r["k_bound_final"]) for r in rows)
    extra = sum(int(r["additional_ev_routes_available"]) for r in rows)
    routes_total = sum(int(r["routes"]) for r in rows)
    slots_total = sum(int(r["num_ev_slots"]) for r in rows)

    summary = {
        "schema": "resetp.joint-decoder-headroom.m3.v1",
        "note": (
            "capacity-relaxation upper bound; ignores geography, time windows "
            "and depot ownership; not an achieved result"
        ),
        "arm": ARM,
        "seed": SEED,
        "depot_units": len(rows),
        "routes_total": routes_total,
        "cv_payload_kg": CV_PAYLOAD,
        "ev_payload_kg": EV_PAYLOAD,
        "mean_capacity_utilisation_vs_cv": round(
            sum(float(r["capacity_utilisation_vs_cv"]) for r in rows)
            / len(rows),
            6,
        ),
        "ev_routes_in_sealed_solutions": ev_now_total,
        "ev_slots_registered": slots_total,
        "ev_routes_bound": bound_total,
        "additional_ev_routes_available_bound": extra,
        "ev_share_of_routes_now": round(ev_now_total / routes_total, 6),
        "ev_share_of_routes_bound": round(bound_total / routes_total, 6),
        "indicative_saving_upper_bound_cny": round(
            extra * MEAN_SAVING_PER_CONVERSION, 2
        ),
        "mean_saving_per_conversion_cny": MEAN_SAVING_PER_CONVERSION,
        "depot_units_where_slack_allows_more_ev": sum(
            1 for r in rows if int(r["additional_ev_routes_available"]) > 0
        ),
    }
    (OUT / "m3_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
