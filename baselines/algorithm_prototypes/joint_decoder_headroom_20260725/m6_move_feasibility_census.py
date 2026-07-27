"""M6: is any load-shifting move available at all?

M5 accepted nothing and generated zero candidates.  That is only a result if no
move exists; if it were an artefact of the probe's limits it would be a bug.
This census settles it by pure arithmetic over the sealed solutions, ignoring
time windows and geography entirely -- so it is a *permissive* test.  If even
this permissive test finds no move, the restrictive probe finding no move is
confirmed rather than suspected.

For every heavy route (load > EV payload) at every depot it asks:

  (a) is there any other route at the same depot with residual capacity at least
      as large as the donor's smallest customer?  -- can one customer move at all
  (b) is the depot's total residual capacity across other routes at least the
      donor's excess over the EV payload?  -- could the excess fit if load were
      infinitely divisible

(a) is the real question; (b) is the relaxation M3's bound implicitly assumed.
The gap between them measures how much of M3's bound is destroyed by customer
demands being indivisible lumps.
"""

from __future__ import annotations

import csv
import json
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
EV_PAYLOAD = 1000.0
CV_PAYLOAD = 1735.0


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
            n.node_id: float(n.demand)
            for n in bundle.instance.nodes
            if n.node_type.lower() == "c"
        }

        by_depot: dict[str, list[dict]] = defaultdict(list)
        for route in witness["routes"]:
            customers = [
                c for c in route["node_sequence"] if c in demand
            ]
            by_depot[route["home_depot_id"]].append(
                {
                    "load": sum(demand[c] for c in customers),
                    "customers": customers,
                    "vehicle_type": route["vehicle_type"].lower(),
                }
            )

        for depot_id, routes in sorted(by_depot.items()):
            for index, route in enumerate(routes):
                if route["vehicle_type"] == "ev":
                    continue
                if route["load"] <= EV_PAYLOAD:
                    continue
                excess = route["load"] - EV_PAYLOAD
                smallest_customer = min(
                    demand[c] for c in route["customers"]
                )
                others = [
                    other
                    for j, other in enumerate(routes)
                    if j != index and other["vehicle_type"] == "cv"
                ]
                residuals = [
                    CV_PAYLOAD - other["load"] for other in others
                ]
                max_residual = max(residuals) if residuals else 0.0
                total_residual = sum(residuals)

                rows.append(
                    {
                        "instance_id": instance_id,
                        "depot_id": depot_id,
                        "route_index": index,
                        "load_kg": round(route["load"], 2),
                        "excess_over_ev_payload_kg": round(excess, 2),
                        "smallest_customer_kg": round(smallest_customer, 2),
                        "max_single_receiver_residual_kg": round(
                            max_residual, 2
                        ),
                        "total_receiver_residual_kg": round(
                            total_residual, 2
                        ),
                        "single_customer_move_possible": max_residual
                        >= smallest_customer,
                        "excess_fits_if_divisible": total_residual >= excess,
                    }
                )

    with (OUT / "m6_raw_runs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    movable = sum(1 for r in rows if r["single_customer_move_possible"])
    divisible = sum(1 for r in rows if r["excess_fits_if_divisible"])

    summary = {
        "schema": "resetp.joint-decoder-headroom.m6.v1",
        "seed": SEED,
        "heavy_cv_routes_examined": len(rows),
        "routes_where_one_customer_could_move": movable,
        "routes_where_one_customer_could_move_pct": round(
            movable / len(rows) * 100.0, 4
        ),
        "routes_where_excess_fits_if_load_were_divisible": divisible,
        "routes_where_excess_fits_if_divisible_pct": round(
            divisible / len(rows) * 100.0, 4
        ),
        "median_smallest_customer_kg": round(
            statistics.median(r["smallest_customer_kg"] for r in rows), 2
        ),
        "median_max_receiver_residual_kg": round(
            statistics.median(
                r["max_single_receiver_residual_kg"] for r in rows
            ),
            2,
        ),
        "median_excess_over_ev_payload_kg": round(
            statistics.median(r["excess_over_ev_payload_kg"] for r in rows), 2
        ),
        "interpretation": (
            "the divisible column is what the M3 arithmetic bound assumed; "
            "the single-customer column is what is physically available"
        ),
    }
    (OUT / "m6_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
