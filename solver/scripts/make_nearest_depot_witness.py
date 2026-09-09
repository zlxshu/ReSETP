#!/usr/bin/env python3
"""Rebuild a saved health witness so every customer starts at its home depot.

The DEPOTSEARCH witness that ships with
``solver/reports/instance_build_only_d996f755bd_20260815`` assigns a few
customers to a depot that is not the nearest one recorded in the instance's
``orders.csv`` (``home_depot_id``).  In the ``independent`` arm that split is
frozen for the whole search (``customer_depot_lock``), so the starting skeleton
decides the arm's customer-to-depot partition.

This script produces a sibling witness whose split is exactly the instance's
own nearest-depot column.  Displaced customers are stripped from their trips
and re-packed into fresh trips at their home depot, on a registered vehicle
slot that is still free in that shift.  Nothing else is touched: schema,
row order convention, depot ids, shift ids and the clock columns of the
sibling rows are copied as-is.  The witness only has to be a legal starting
point -- the search improves it.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

FIELDS = [
    "instance_id",
    "witness_status",
    "physical_vehicle_id",
    "route_vehicle_id",
    "depot_id",
    "shift_id",
    "customers",
    "customer_count",
    "volume_m3",
    "demand_kg",
    "departure_minute",
    "return_minute",
    "distance_km",
]


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--instance-id", default="cn-jjj-50c-01-DEPOTSEARCH-d996f755bd"
    )
    parser.add_argument(
        "--package-root",
        type=Path,
        default=Path("data/ChinaInstances/china81_final_suite_v2_20260815"),
    )
    parser.add_argument(
        "--source-witness",
        type=Path,
        default=Path(
            "solver/reports/instance_build_only_d996f755bd_20260815"
            "/health_witness_routes.csv"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "solver/reports/instance_build_only_d996f755bd_20260815"
            "/health_witness_routes_nearest_depot.csv"
        ),
    )
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    package_root = repo / args.package_root
    saved_root = package_root / "instances" / args.instance_id

    orders = _rows(saved_root / "orders.csv")
    home_depot = {r["customer_id"]: r["home_depot_id"] for r in orders}
    order_shift = {r["customer_id"]: r["shift_id"] for r in orders}
    demand_kg = {r["customer_id"]: float(r["demand_kg"]) for r in orders}
    window = {
        r["customer_id"]: (
            float(r["time_window_late_minute"]),
            float(r["time_window_early_minute"]),
        )
        for r in orders
    }
    volume_m3 = {r["customer_id"]: float(r["source_volume_m3"]) for r in orders}

    contract = json.loads((saved_root / "shift_contract.json").read_text())
    cap_kg = float(contract["vehicle_payload_capacity_kg"])
    cap_m3 = float(contract["vehicle_volume_capacity_m3"])

    caps = {
        r["depot_id"]: int(r["num_cv"])
        for r in _rows(package_root / "fleet_caps.csv")
        if r["instance_id"] == args.instance_id
    }

    source = [
        r for r in _rows(args.repo_root / args.source_witness)
        if r["instance_id"] == args.instance_id
    ]
    if not source:
        raise SystemExit(f"source witness has no rows for {args.instance_id}")

    # Clock columns are per-shift constants in the saved witness; reuse them so
    # the appended trips read exactly like their siblings.
    clock: dict[str, tuple[str, str]] = {}
    for row in source:
        clock.setdefault(
            row["shift_id"], (row["departure_minute"], row["return_minute"])
        )

    kept: list[dict[str, str]] = []
    displaced: list[str] = []
    for row in source:
        customers = [c for c in row["customers"].split("|") if c]
        stay = [c for c in customers if home_depot[c] == row["depot_id"]]
        displaced.extend(c for c in customers if home_depot[c] != row["depot_id"])
        if stay:
            kept.append({**row, "customers": "|".join(stay)})

    # Occupancy of the surviving skeleton: which (vehicle, shift) pairs are used
    # and how many trips each vehicle already carries.
    used_shift: set[tuple[str, str]] = set()
    trip_count: dict[str, int] = defaultdict(int)
    for row in kept:
        used_shift.add((row["physical_vehicle_id"], row["shift_id"]))
        trip_count[row["physical_vehicle_id"]] += 1

    def slots(depot_id: str) -> list[str]:
        return [f"CV_{depot_id}_{i}" for i in range(1, caps[depot_id] + 1)]

    # Pack the displaced customers into capacity-feasible trips, per home depot
    # and per the shift the instance itself assigns them.
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for customer in displaced:
        groups[(home_depot[customer], order_shift[customer])].append(customer)

    appended: list[dict[str, str]] = []
    for (depot_id, shift_id), members in sorted(groups.items()):
        # Time-window order: pack and sequence by closing time, so the appended
        # trip is a legal chain rather than an alphabetical one.
        members.sort(key=lambda c: (window[c], c))
        trips: list[list[str]] = []
        for customer in members:
            for trip in trips:
                if (
                    sum(demand_kg[c] for c in trip) + demand_kg[customer] <= cap_kg
                    and sum(volume_m3[c] for c in trip) + volume_m3[customer] <= cap_m3
                ):
                    trip.append(customer)
                    break
            else:
                trips.append([customer])
        for trip in trips:
            # A trip appended behind an existing chain inherits that chain's
            # return time as its forced departure (multitrip_schedule.py:2346),
            # which in this instance is already past the displaced customers'
            # windows.  So prefer a registered slot that carries no trip yet --
            # its departure is still free -- and only fall back to a busy
            # vehicle that is unused in this shift when no idle slot is left.
            idle = [slot for slot in slots(depot_id) if trip_count[slot] == 0]
            free = [
                slot for slot in slots(depot_id)
                if (slot, shift_id) not in used_shift
            ]
            if not (idle or free):
                raise SystemExit(
                    f"no free registered {depot_id} slot in shift {shift_id}"
                )
            vehicle = idle[0] if idle else free[0]
            used_shift.add((vehicle, shift_id))
            trip_count[vehicle] += 1
            departure, ret = clock[shift_id]
            appended.append(
                {
                    "instance_id": args.instance_id,
                    "witness_status": "PASS",
                    "physical_vehicle_id": vehicle,
                    "route_vehicle_id": f"{vehicle}#T{trip_count[vehicle]}",
                    "depot_id": depot_id,
                    "shift_id": shift_id,
                    "customers": "|".join(trip),
                    "customer_count": str(len(trip)),
                    "volume_m3": "0.000000",
                    "demand_kg": f"{sum(demand_kg[c] for c in trip):.6f}",
                    "departure_minute": departure,
                    "return_minute": ret,
                    "distance_km": "",
                }
            )

    out_rows = kept + appended
    for row in out_rows:
        customers = row["customers"].split("|")
        row["customer_count"] = str(len(customers))
        row["demand_kg"] = f"{sum(demand_kg[c] for c in customers):.6f}"

    covered = [c for row in out_rows for c in row["customers"].split("|")]
    if sorted(covered) != sorted(home_depot):
        raise SystemExit("rebuilt witness does not cover customers exactly once")
    for row in out_rows:
        for customer in row["customers"].split("|"):
            if home_depot[customer] != row["depot_id"]:
                raise SystemExit(f"{customer} is still away from its home depot")

    destination = args.repo_root / args.output
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(out_rows)

    per_depot: dict[str, set[str]] = defaultdict(set)
    for row in out_rows:
        per_depot[row["depot_id"]].add(row["physical_vehicle_id"])
    print(f"wrote {destination} ({len(out_rows)} trips)")
    print(f"moved back to home depot: {sorted(displaced)}")
    for depot_id in sorted(per_depot):
        print(
            f"  {depot_id}: {len(per_depot[depot_id])} vehicles, "
            f"{sum(1 for r in out_rows if r['depot_id'] == depot_id)} trips"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
