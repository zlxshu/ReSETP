"""M7: does spending an idle EV slot to split a heavy route pay?

M1 found 26.9% of registered vehicle slots idle, 69.1% of EV slots among them.
M5/M6 showed load cannot be shifted between existing routes -- the solution is
bin-packing tight.  That leaves one untested lever: stop holding the route count
fixed.  Split a heavy diesel route into two lighter routes, put both on electric
vehicles drawn from the idle slots, and pay one extra fixed vehicle cost.

For every CV route that two EV payloads could cover, this tries every contiguous
split of its visit sequence, electrifies both halves, and scores the complete
solution under the frozen evaluator.  A split is kept only when the complete
cost strictly falls, so the extra 170 CNY fixed cost has to be earned back.

This closes the audit: with load-shifting dead and splitting measured, every
route to more electrification on the current instances has been priced.
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
TOL = 1.0e-9

STRATEGIES = (
    ("ev_integrated", "integrated", 1.0),
    ("ev_low_carbon", "legacy", 1.0),
    ("ev_immediate", "integrated", 0.0),
)


def nonfleet(violations):
    return [v for v in violations if v.type != FLEET_SIZE]


def make_route(vehicle_id, depot_id, customers, vehicle_type="cv") -> Route:
    return Route(
        vehicle_id=vehicle_id,
        vehicle_type=vehicle_type,
        home_depot_id=depot_id,
        node_sequence=[depot_id, *customers, depot_id],
    )


def electrify(route: Route, bundle):
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
        return repaired, tuple(actions)
    return None


def probe_instance(instance_id: str, witness: dict) -> tuple[dict, list[dict]]:
    bundle = load_china81_bundle(REPO, instance_id)
    demand = {
        n.node_id: float(n.demand)
        for n in bundle.instance.nodes
        if n.node_type.lower() == "c"
    }

    current = Solution(
        routes=[Route(**r) for r in witness["routes"]],
        charging_actions=[
            ChargingAction(**a) for a in witness["charging_actions"]
        ],
    )
    sealed_obj, _, _ = exact_china81_score(current, bundle)
    current_obj = sealed_obj

    evaluations = 0
    attempts = 0
    accepted: list[dict] = []
    best_rejected_gap = None
    detail_rows: list[dict] = []

    improved = True
    while improved:
        improved = False
        ev_used: dict[str, int] = {}
        total_used: dict[str, int] = {}
        for route in current.routes:
            depot = route.home_depot_id
            total_used[depot] = total_used.get(depot, 0) + 1
            if route.vehicle_type.lower() == "ev":
                ev_used[depot] = ev_used.get(depot, 0) + 1

        for index, route in enumerate(current.routes):
            if route.vehicle_type.lower() != "cv":
                continue
            depot_id = route.home_depot_id
            caps = bundle.fleet_caps_by_depot[depot_id]
            ev_cap, total_cap = int(caps["num_ev"]), int(
                caps["total_fleet_cap"]
            )
            # splitting consumes one extra vehicle and two EV slots,
            # releasing one CV slot
            if ev_used.get(depot_id, 0) + 2 > ev_cap:
                continue
            if total_used.get(depot_id, 0) + 1 > total_cap:
                continue

            customers = list(route.node_sequence[1:-1])
            if len(customers) < 2:
                continue
            load = sum(demand.get(c, 0.0) for c in customers)
            if load <= EV_PAYLOAD or load > 2 * EV_PAYLOAD:
                continue

            for position in range(1, len(customers)):
                left, right = customers[:position], customers[position:]
                if sum(demand.get(c, 0.0) for c in left) > EV_PAYLOAD:
                    continue
                if sum(demand.get(c, 0.0) for c in right) > EV_PAYLOAD:
                    continue
                attempts += 1

                left_route = make_route(
                    route.vehicle_id, depot_id, left
                )
                right_route = make_route(
                    f"{route.vehicle_id}-SPLIT", depot_id, right
                )
                left_ev = electrify(left_route, bundle)
                right_ev = electrify(right_route, bundle)
                if left_ev is None or right_ev is None:
                    continue

                routes = list(current.routes)
                routes[index] = left_ev[0]
                routes.append(right_ev[0])
                kept = [
                    action
                    for action in current.charging_actions
                    if action.vehicle_id != route.vehicle_id
                ]
                candidate = Solution(
                    routes=routes,
                    charging_actions=[
                        *kept,
                        *left_ev[1],
                        *right_ev[1],
                    ],
                )
                cand_obj, _, cand_viol = exact_china81_score(
                    candidate, bundle
                )
                evaluations += 1
                if nonfleet(cand_viol):
                    continue
                gap = cand_obj - current_obj
                detail_rows.append(
                    {
                        "instance_id": instance_id,
                        "route_index": index,
                        "split_position": position,
                        "delta_vs_current": round(gap, 6),
                    }
                )
                if best_rejected_gap is None or gap < best_rejected_gap:
                    best_rejected_gap = gap
                if gap < -TOL:
                    accepted.append(
                        {"route_index": index, "gain": -gap}
                    )
                    current, current_obj = candidate, cand_obj
                    improved = True
                    break
            if improved:
                break

    final_obj, final_bd, final_viol = exact_china81_score(current, bundle)
    return (
        {
            "instance_id": instance_id,
            "sealed_cost": sealed_obj,
            "probe_cost": final_obj,
            "gain_cny": sealed_obj - final_obj,
            "gain_pct": (sealed_obj - final_obj) / sealed_obj * 100.0,
            "split_attempts": attempts,
            "complete_evaluations": evaluations,
            "accepted_splits": len(accepted),
            "best_split_delta_cny": (
                round(best_rejected_gap, 4)
                if best_rejected_gap is not None
                else ""
            ),
            "final_violations": len(final_viol),
            "probe_n_veh_cv": final_bd["n_veh_cv"],
            "probe_n_veh_ev": final_bd["n_veh_ev"],
        },
        detail_rows,
    )


def main() -> None:
    task_dirs = sorted(
        path
        for path in TASKS.iterdir()
        if path.name.endswith(f"__{SEED}")
        and (path / "solution_witnesses.json").is_file()
    )
    rows, details = [], []
    for index, task_dir in enumerate(task_dirs, start=1):
        instance_id = task_dir.name.split("__")[1]
        witness = json.loads(
            (task_dir / "solution_witnesses.json").read_text(encoding="utf-8")
        )[ARM]
        row, detail = probe_instance(instance_id, witness)
        rows.append(row)
        details.extend(detail)
        print(
            f"[{index:>2}/{len(task_dirs)}] {instance_id:<32} "
            f"gain={row['gain_pct']:+.4f}% splits={row['accepted_splits']} "
            f"tried={row['split_attempts']} evals={row['complete_evaluations']} "
            f"bestDelta={row['best_split_delta_cny']}",
            flush=True,
        )

    with (OUT / "m7_raw_runs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    if details:
        with (OUT / "m7_split_deltas.csv").open(
            "w", newline="", encoding="utf-8"
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=list(details[0].keys()))
            writer.writeheader()
            writer.writerows(details)

    total_sealed = sum(r["sealed_cost"] for r in rows)
    total_probe = sum(r["probe_cost"] for r in rows)
    deltas = [
        float(r["best_split_delta_cny"])
        for r in rows
        if r["best_split_delta_cny"] != ""
    ]
    summary = {
        "schema": "resetp.joint-decoder-headroom.m7.v1",
        "seed": SEED,
        "instances": len(rows),
        "total_split_attempts": sum(r["split_attempts"] for r in rows),
        "total_complete_evaluations": sum(
            r["complete_evaluations"] for r in rows
        ),
        "instances_with_any_feasible_split": sum(
            1 for r in rows if r["complete_evaluations"] > 0
        ),
        "accepted_splits_total": sum(r["accepted_splits"] for r in rows),
        "instances_improved": sum(1 for r in rows if r["gain_cny"] > TOL),
        "total_gain_cny": round(total_sealed - total_probe, 4),
        "aggregate_gain_pct": round(
            (total_sealed - total_probe) / total_sealed * 100.0, 6
        ),
        "best_split_delta_median_cny": (
            round(statistics.median(deltas), 4) if deltas else None
        ),
        "best_split_delta_min_cny": round(min(deltas), 4) if deltas else None,
        "vehicle_fixed_cost_cny": 170.0,
        "final_violations_total": sum(r["final_violations"] for r in rows),
    }
    (OUT / "m7_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print()
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
