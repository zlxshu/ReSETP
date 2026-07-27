"""M1: idle fleet capacity in the sealed v7 China81 solutions.

Read-only.  For every sealed MV-HGS-SP witness this counts how many routes
each depot actually used, splits them by vehicle type, and compares the counts
with the registered finite-fleet caps.  No solver, no evaluation, no search.

The question it answers: how much of the registered fleet -- and in particular
how many of the EV-only slots -- does the current pipeline never touch.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TASKS = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / "corrected_china81_rerun_v7_small_archive_ledger_20260724"
    / "full_gate/tasks"
)
FLEET_CAPS = (
    REPO
    / "data/ChinaInstances/china81_finite_fleet_authority_v1_20260723/fleet_caps.csv"
)
OUT = Path(__file__).resolve().parent
ARM = "MV-HGS-SP"


def load_caps() -> dict[tuple[str, str], dict[str, int]]:
    caps: dict[tuple[str, str], dict[str, int]] = {}
    with FLEET_CAPS.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            caps[(row["instance_id"], row["depot_id"])] = {
                "base_all_cv_routes_Rd": int(row["base_all_cv_routes_Rd"]),
                "num_cv": int(row["num_cv"]),
                "num_ev": int(row["num_ev"]),
                "total_fleet_cap": int(row["total_fleet_cap"]),
            }
    return caps


def main() -> None:
    caps = load_caps()
    rows: list[dict[str, object]] = []

    for task_dir in sorted(TASKS.iterdir()):
        witness_path = task_dir / "solution_witnesses.json"
        if not witness_path.is_file():
            continue
        # task_id form: D6-E2-STAGED__<instance>__seed<N>
        parts = task_dir.name.split("__")
        if len(parts) != 3:
            continue
        instance_id, seed_token = parts[1], parts[2]

        witness = json.loads(witness_path.read_text(encoding="utf-8"))[ARM]
        used: dict[tuple[str, str], int] = defaultdict(int)
        for route in witness["routes"]:
            used[(route["home_depot_id"], route["vehicle_type"].lower())] += 1

        depots = sorted(
            depot for (inst, depot) in caps if inst == instance_id
        )
        for depot_id in depots:
            cap = caps[(instance_id, depot_id)]
            cv_used = used[(depot_id, "cv")]
            ev_used = used[(depot_id, "ev")]
            rows.append(
                {
                    "instance_id": instance_id,
                    "seed": seed_token.replace("seed", ""),
                    "depot_id": depot_id,
                    "base_all_cv_routes_Rd": cap["base_all_cv_routes_Rd"],
                    "num_cv": cap["num_cv"],
                    "num_ev": cap["num_ev"],
                    "total_fleet_cap": cap["total_fleet_cap"],
                    "routes_used": cv_used + ev_used,
                    "cv_used": cv_used,
                    "ev_used": ev_used,
                    "cv_idle": cap["num_cv"] - cv_used,
                    "ev_idle": cap["num_ev"] - ev_used,
                    "total_idle": cap["total_fleet_cap"] - cv_used - ev_used,
                    # required_ev is the completer's only forcing rule
                    "required_ev_by_completer": max(
                        0, (cv_used + ev_used) - cap["num_cv"]
                    ),
                }
            )

    raw = OUT / "m1_raw_runs.csv"
    with raw.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    units = len(rows)
    instances = len({row["instance_id"] for row in rows})
    ev_slots = sum(int(row["num_ev"]) for row in rows)
    ev_used = sum(int(row["ev_used"]) for row in rows)
    ev_idle = sum(int(row["ev_idle"]) for row in rows)
    total_slots = sum(int(row["total_fleet_cap"]) for row in rows)
    routes_used = sum(int(row["routes_used"]) for row in rows)
    forced = sum(int(row["required_ev_by_completer"]) for row in rows)
    depot_units_zero_ev = sum(1 for row in rows if row["ev_used"] == 0)
    over_rd = sum(
        1
        for row in rows
        if int(row["routes_used"]) > int(row["base_all_cv_routes_Rd"])
    )

    summary = {
        "schema": "resetp.joint-decoder-headroom.m1.v1",
        "arm": ARM,
        "depot_seed_units": units,
        "instances_covered": instances,
        "total_fleet_slots": total_slots,
        "routes_actually_used": routes_used,
        "total_slots_idle": total_slots - routes_used,
        "ev_slots_registered": ev_slots,
        "ev_slots_used": ev_used,
        "ev_slots_idle": ev_idle,
        "ev_slot_idle_rate": round(ev_idle / ev_slots, 6) if ev_slots else None,
        "depot_units_with_zero_ev": depot_units_zero_ev,
        "depot_units_total": units,
        "ev_forced_by_completer_total": forced,
        "depot_units_using_more_routes_than_all_cv_requirement": over_rd,
    }
    (OUT / "m1_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
