"""M5: achieved gain from capacity-aware exchange plus electrification.

M2 proved the completer is already optimal once route composition is fixed, and
that every rejection is a payload rejection.  So the only remaining lever is
*which customers sit on which route*, because that is what sets the load.

This probe does exactly that, deterministically and without any metaheuristic:
for each route whose load sits just above the EV payload, it moves out the few
customers needed to bring it under 1000 kg, reinserts them into another route at
the same depot at the cheapest feasible position, electrifies the lightened
route, and scores the whole solution under the frozen complete model.  A move is
kept only when the complete cost strictly falls.

This replaces the M3 arithmetic relaxation with an achieved, complete-model
number.  It is a probe, not a proposed algorithm: it explores one move class
from the sealed incumbent and does not search.
"""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

from setp_solver.algorithms.resetp_alns.support.charging import (
    repair_route_charging,
)
from setp_solver.check import FLEET_SIZE
from setp_solver.china81 import load_china81_bundle
from setp_solver.china81_completion import exact_china81_score
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
EV_PAYLOAD = 1000.0
CV_PAYLOAD = 1735.0
TOL = 1.0e-9

STRATEGIES = (
    ("ev_integrated", "integrated", 1.0),
    ("ev_low_carbon", "legacy", 1.0),
    ("ev_immediate", "integrated", 0.0),
)
MAX_MOVED_CUSTOMERS = 2
MAX_INSERT_ROUTES = 6


def nonfleet(violations):
    return [v for v in violations if v.type != FLEET_SIZE]


def sealed_all_cv(witness, bundle) -> Solution:
    node_lookup = {n.node_id: n for n in bundle.instance.nodes}
    routes = []
    for route in witness["routes"]:
        customers = [
            node_id
            for node_id in route["node_sequence"]
            if node_id in node_lookup
            and node_lookup[node_id].node_type.lower() == "c"
        ]
        if not customers:
            continue
        routes.append(
            Route(
                vehicle_id=f"CH81-{len(routes) + 1:04d}",
                vehicle_type="cv",
                home_depot_id=route["home_depot_id"],
                node_sequence=[
                    route["home_depot_id"],
                    *customers,
                    route["home_depot_id"],
                ],
            )
        )
    return Solution(routes=routes)


def body(route: Route) -> list[str]:
    return list(route.node_sequence[1:-1])


def rebuild(route: Route, customers: list[str]) -> Route:
    return Route(
        vehicle_id=route.vehicle_id,
        vehicle_type=route.vehicle_type,
        home_depot_id=route.home_depot_id,
        node_sequence=[
            route.home_depot_id,
            *customers,
            route.home_depot_id,
        ],
    )


def electrify(route: Route, bundle):
    """Return the cheapest feasible EV form of a route, or None."""

    best = None
    for _label, strategy, carbon_weight in STRATEGIES:
        ev_route = Route(
            vehicle_id=route.vehicle_id,
            vehicle_type="ev",
            home_depot_id=route.home_depot_id,
            node_sequence=list(route.node_sequence),
        )
        try:
            repaired, actions = repair_route_charging(
                ev_route,
                bundle.instance,
                bundle.time_profile,
                bundle.prices,
                strategy=strategy,
                carbon_weight=carbon_weight,
                depot_charge_window_mode="same_day_predeparture",
            )
        except (TypeError, ValueError):
            continue
        if best is None:
            best = (repaired, tuple(actions))
    return best


def probe_instance(instance_id: str, witness: dict) -> dict:
    bundle = load_china81_bundle(REPO, instance_id)
    demand = {
        n.node_id: float(n.demand)
        for n in bundle.instance.nodes
        if n.node_type.lower() == "c"
    }

    current = sealed_all_cv(witness, bundle)
    # start from the sealed cost, which M2 showed the completer already attains
    sealed = Solution(
        routes=[Route(**r) for r in witness["routes"]],
        charging_actions=[
            ChargingAction(**a) for a in witness["charging_actions"]
        ],
    )
    sealed_obj, _, _ = exact_china81_score(sealed, bundle)

    current = sealed
    current_obj = sealed_obj
    evaluations = 0
    accepted_moves = []

    def loads(solution):
        return [
            sum(demand.get(c, 0.0) for c in body(r)) for r in solution.routes
        ]

    improved = True
    while improved:
        improved = False
        route_loads = loads(current)
        ev_used = {}
        for route in current.routes:
            if route.vehicle_type.lower() == "ev":
                ev_used[route.home_depot_id] = (
                    ev_used.get(route.home_depot_id, 0) + 1
                )

        order = sorted(
            (
                index
                for index, route in enumerate(current.routes)
                if route.vehicle_type.lower() == "cv"
                and route_loads[index] > EV_PAYLOAD
            ),
            key=lambda index: route_loads[index],
        )
        for donor_index in order:
            donor = current.routes[donor_index]
            depot_id = donor.home_depot_id
            ev_cap = int(bundle.fleet_caps_by_depot[depot_id]["num_ev"])
            if ev_used.get(depot_id, 0) >= ev_cap:
                continue
            excess = route_loads[donor_index] - EV_PAYLOAD
            donor_body = body(donor)
            # smallest customer set covering the excess, largest demand first
            ranked = sorted(
                donor_body, key=lambda c: -demand.get(c, 0.0)
            )
            moving: list[str] = []
            covered = 0.0
            for customer in ranked:
                if covered >= excess:
                    break
                moving.append(customer)
                covered += demand.get(customer, 0.0)
            if covered < excess or len(moving) > MAX_MOVED_CUSTOMERS:
                continue

            receivers = [
                index
                for index, route in enumerate(current.routes)
                if index != donor_index
                and route.home_depot_id == depot_id
                and route.vehicle_type.lower() == "cv"
                and route_loads[index] + covered <= CV_PAYLOAD
            ][:MAX_INSERT_ROUTES]
            if not receivers:
                continue

            new_donor_body = [c for c in donor_body if c not in set(moving)]
            if not new_donor_body:
                continue
            lightened = rebuild(donor, new_donor_body)
            ev_form = electrify(lightened, bundle)
            if ev_form is None:
                continue
            ev_route, ev_actions = ev_form

            best_candidate = None
            for receiver_index in receivers:
                receiver = current.routes[receiver_index]
                receiver_body = body(receiver)
                for position in range(len(receiver_body) + 1):
                    new_receiver_body = (
                        receiver_body[:position]
                        + moving
                        + receiver_body[position:]
                    )
                    routes = list(current.routes)
                    routes[donor_index] = ev_route
                    routes[receiver_index] = rebuild(
                        receiver, new_receiver_body
                    )
                    kept = [
                        action
                        for action in current.charging_actions
                        if action.vehicle_id
                        not in {donor.vehicle_id, receiver.vehicle_id}
                    ]
                    candidate = Solution(
                        routes=routes,
                        charging_actions=[*kept, *ev_actions],
                    )
                    cand_obj, _, cand_viol = exact_china81_score(
                        candidate, bundle
                    )
                    evaluations += 1
                    if nonfleet(cand_viol):
                        continue
                    if best_candidate is None or cand_obj < best_candidate[0]:
                        best_candidate = (cand_obj, candidate)

            if best_candidate and best_candidate[0] < current_obj - TOL:
                accepted_moves.append(
                    {
                        "donor_route": donor_index,
                        "moved_customers": len(moving),
                        "gain": current_obj - best_candidate[0],
                    }
                )
                current_obj, current = best_candidate[0], best_candidate[1]
                improved = True
                break

    final_obj, final_bd, final_viol = exact_china81_score(current, bundle)
    return {
        "instance_id": instance_id,
        "sealed_cost": sealed_obj,
        "probe_cost": final_obj,
        "gain_cny": sealed_obj - final_obj,
        "gain_pct": (sealed_obj - final_obj) / sealed_obj * 100.0,
        "accepted_moves": len(accepted_moves),
        "complete_evaluations": evaluations,
        "final_violations": len(final_viol),
        "sealed_ev_routes": sum(
            r.vehicle_type.lower() == "ev" for r in sealed.routes
        ),
        "probe_ev_routes": sum(
            r.vehicle_type.lower() == "ev" for r in current.routes
        ),
        "probe_station_charging_kwh": final_bd["station_charging_kwh"],
        "probe_n_veh_cv": final_bd["n_veh_cv"],
        "probe_n_veh_ev": final_bd["n_veh_ev"],
    }


def main() -> None:
    task_dirs = sorted(
        path
        for path in TASKS.iterdir()
        if path.name.endswith(f"__{SEED}")
        and (path / "solution_witnesses.json").is_file()
    )
    rows = []
    for index, task_dir in enumerate(task_dirs, start=1):
        instance_id = task_dir.name.split("__")[1]
        witness = json.loads(
            (task_dir / "solution_witnesses.json").read_text(encoding="utf-8")
        )[ARM]
        row = probe_instance(instance_id, witness)
        rows.append(row)
        print(
            f"[{index:>2}/{len(task_dirs)}] {instance_id:<32} "
            f"sealed={row['sealed_cost']:>11.4f} probe={row['probe_cost']:>11.4f} "
            f"gain={row['gain_pct']:+.4f}% moves={row['accepted_moves']} "
            f"ev {row['sealed_ev_routes']}->{row['probe_ev_routes']} "
            f"evals={row['complete_evaluations']}",
            flush=True,
        )

    with (OUT / "m5_raw_runs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    total_sealed = sum(r["sealed_cost"] for r in rows)
    total_probe = sum(r["probe_cost"] for r in rows)
    wins = sum(1 for r in rows if r["gain_cny"] > TOL)
    summary = {
        "schema": "resetp.joint-decoder-headroom.m5.v1",
        "seed": SEED,
        "instances": len(rows),
        "instances_improved": wins,
        "instances_unchanged": len(rows) - wins,
        "instances_worsened": sum(1 for r in rows if r["gain_cny"] < -TOL),
        "total_sealed_cost": round(total_sealed, 4),
        "total_probe_cost": round(total_probe, 4),
        "total_gain_cny": round(total_sealed - total_probe, 4),
        "aggregate_gain_pct": round(
            (total_sealed - total_probe) / total_sealed * 100.0, 6
        ),
        "mean_instance_gain_pct": round(
            statistics.mean(r["gain_pct"] for r in rows), 6
        ),
        "max_instance_gain_pct": round(
            max(r["gain_pct"] for r in rows), 6
        ),
        "total_accepted_moves": sum(r["accepted_moves"] for r in rows),
        "ev_routes_before": sum(r["sealed_ev_routes"] for r in rows),
        "ev_routes_after": sum(r["probe_ev_routes"] for r in rows),
        "total_complete_evaluations": sum(
            r["complete_evaluations"] for r in rows
        ),
        "final_violations_total": sum(r["final_violations"] for r in rows),
        "m3_upper_bound_pct": 0.783,
    }
    (OUT / "m5_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print()
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
