"""M2: what electrification costs when the route set is held fixed.

For every sealed v7 witness (seed 1) this holds the customer grouping and visit
order exactly as sealed, rebuilds the all-CV reference the completer starts
from, and then measures two things the completer never measures:

1.  the per-route cost delta of converting that one route to EV, for every
    route, whether or not the delta is an improvement;
2.  a *forced* max-EV assignment that fills each depot's registered EV slots
    regardless of whether cost falls.

The completer only ever accepts a conversion when the complete cost strictly
falls, and only ever forces one when routes outnumber the CV cap.  Measuring
the forced variant is what separates "EV is uneconomical" from "EV is never
offered the chance".

Read-only with respect to every protected file: this imports the frozen
evaluator, checker and charging repair and writes nothing outside its own
directory.
"""

from __future__ import annotations

import csv
import json
import statistics
from dataclasses import dataclass
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
TOL = 1.0e-9

# Same three variants the frozen completer generates, in the same order.
STRATEGIES = (
    ("ev_integrated", "integrated", 1.0),
    ("ev_low_carbon", "legacy", 1.0),
    ("ev_immediate", "integrated", 0.0),
)


@dataclass(frozen=True)
class EvVariant:
    route_index: int
    label: str
    route: Route
    actions: tuple[ChargingAction, ...]
    delta_vs_all_cv: float


def all_cv_reference(witness: dict, bundle) -> Solution:
    """Rebuild the completer's all-CV starting point from a witness."""

    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    routes: list[Route] = []
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


def swap_route(
    solution: Solution,
    route_index: int,
    route: Route,
    actions: tuple[ChargingAction, ...],
) -> Solution:
    old_vehicle_id = solution.routes[route_index].vehicle_id
    routes = list(solution.routes)
    routes[route_index] = route
    kept = [
        action
        for action in solution.charging_actions
        if action.vehicle_id != old_vehicle_id
    ]
    return Solution(routes=routes, charging_actions=[*kept, *actions])


def nonfleet(violations) -> list:
    return [item for item in violations if item.type != FLEET_SIZE]


def audit_instance(instance_id: str, witness: dict) -> tuple[dict, list[dict]]:
    bundle = load_china81_bundle(REPO, instance_id)

    base = all_cv_reference(witness, bundle)
    base_obj, base_bd, base_viol = exact_china81_score(base, bundle)
    base_feasible = not nonfleet(base_viol)

    per_route_rows: list[dict] = []
    variants: list[EvVariant] = []

    for route_index, route in enumerate(base.routes):
        best_for_route: EvVariant | None = None
        for label, strategy, carbon_weight in STRATEGIES:
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
            except (TypeError, ValueError) as exc:
                per_route_rows.append(
                    {
                        "instance_id": instance_id,
                        "route_index": route_index,
                        "depot_id": route.home_depot_id,
                        "label": label,
                        "status": "GENERATION_FAILED",
                        "reason": str(exc)[:120],
                        "delta_vs_all_cv": "",
                        "station_charging_kwh": "",
                    }
                )
                continue

            candidate = swap_route(
                base, route_index, repaired, tuple(actions)
            )
            cand_obj, cand_bd, cand_viol = exact_china81_score(
                candidate, bundle
            )
            if nonfleet(cand_viol):
                per_route_rows.append(
                    {
                        "instance_id": instance_id,
                        "route_index": route_index,
                        "depot_id": route.home_depot_id,
                        "label": label,
                        "status": "INFEASIBLE",
                        "reason": nonfleet(cand_viol)[0].type,
                        "delta_vs_all_cv": "",
                        "station_charging_kwh": "",
                    }
                )
                continue

            delta = cand_obj - base_obj
            per_route_rows.append(
                {
                    "instance_id": instance_id,
                    "route_index": route_index,
                    "depot_id": route.home_depot_id,
                    "label": label,
                    "status": "FEASIBLE",
                    "reason": "",
                    "delta_vs_all_cv": delta,
                    "station_charging_kwh": cand_bd["station_charging_kwh"],
                }
            )
            if best_for_route is None or delta < best_for_route.delta_vs_all_cv:
                best_for_route = EvVariant(
                    route_index=route_index,
                    label=label,
                    route=repaired,
                    actions=tuple(actions),
                    delta_vs_all_cv=delta,
                )
        if best_for_route is not None:
            variants.append(best_for_route)

    # Forced max-EV: fill each depot's registered EV slots by best single-route
    # delta, accepting even when the delta is positive.  Deterministic order,
    # never outcome-selected across instances.
    ranked = sorted(
        variants, key=lambda item: (item.delta_vs_all_cv, item.route_index)
    )
    forced = base
    forced_obj = base_obj
    ev_by_depot: dict[str, int] = {}
    forced_accepted: list[dict] = []
    forced_rejected_infeasible = 0
    for variant in ranked:
        depot_id = base.routes[variant.route_index].home_depot_id
        ev_cap = int(bundle.fleet_caps_by_depot[depot_id]["num_ev"])
        if ev_by_depot.get(depot_id, 0) >= ev_cap:
            continue
        candidate = swap_route(
            forced, variant.route_index, variant.route, variant.actions
        )
        cand_obj, _, cand_viol = exact_china81_score(candidate, bundle)
        if nonfleet(cand_viol):
            forced_rejected_infeasible += 1
            continue
        forced_accepted.append(
            {
                "route_index": variant.route_index,
                "label": variant.label,
                "delta": cand_obj - forced_obj,
            }
        )
        forced = candidate
        forced_obj = cand_obj
        ev_by_depot[depot_id] = ev_by_depot.get(depot_id, 0) + 1

    forced_obj, forced_bd, forced_viol = exact_china81_score(forced, bundle)

    sealed = Solution(
        routes=[Route(**r) for r in witness["routes"]],
        charging_actions=[
            ChargingAction(**a) for a in witness["charging_actions"]
        ],
    )
    sealed_obj, sealed_bd, sealed_viol = exact_china81_score(sealed, bundle)

    feasible_deltas = [
        float(row["delta_vs_all_cv"])
        for row in per_route_rows
        if row["status"] == "FEASIBLE"
    ]
    ev_feasible_routes = len(
        {
            row["route_index"]
            for row in per_route_rows
            if row["status"] == "FEASIBLE"
        }
    )

    summary = {
        "instance_id": instance_id,
        "routes": len(base.routes),
        "all_cv_feasible": base_feasible,
        "all_cv_cost": base_obj,
        "sealed_cost": sealed_obj,
        "sealed_violations": len(sealed_viol),
        "sealed_ev_routes": sum(
            r.vehicle_type.lower() == "ev" for r in sealed.routes
        ),
        "sealed_station_charging_kwh": sealed_bd["station_charging_kwh"],
        "forced_maxev_cost": forced_obj,
        "forced_maxev_violations": len(forced_viol),
        "forced_maxev_ev_routes": sum(ev_by_depot.values()),
        "forced_maxev_station_charging_kwh": forced_bd["station_charging_kwh"],
        "forced_vs_sealed_pct": (
            (forced_obj - sealed_obj) / sealed_obj * 100.0 if sealed_obj else None
        ),
        "ev_feasible_routes": ev_feasible_routes,
        "ev_route_feasible_rate": (
            ev_feasible_routes / len(base.routes) if base.routes else None
        ),
        "per_route_delta_min": min(feasible_deltas) if feasible_deltas else None,
        "per_route_delta_median": (
            statistics.median(feasible_deltas) if feasible_deltas else None
        ),
        "per_route_delta_max": max(feasible_deltas) if feasible_deltas else None,
        "per_route_negative_deltas": sum(
            1 for d in feasible_deltas if d < -TOL
        ),
        "per_route_feasible_variants": len(feasible_deltas),
        "forced_rejected_infeasible": forced_rejected_infeasible,
        "all_cv_cost_fix": base_bd["cost_fix"],
        "all_cv_cost_fuel": base_bd["cost_fuel"],
        "all_cv_cost_elec": base_bd["cost_elec"],
        "all_cv_cost_carbon": base_bd["cost_carbon"],
        "all_cv_E_total": base_bd["E_total"],
        "forced_cost_fix": forced_bd["cost_fix"],
        "forced_cost_fuel": forced_bd["cost_fuel"],
        "forced_cost_elec": forced_bd["cost_elec"],
        "forced_cost_carbon": forced_bd["cost_carbon"],
        "forced_E_total": forced_bd["E_total"],
    }
    return summary, per_route_rows


def main() -> None:
    summaries: list[dict] = []
    all_rows: list[dict] = []

    task_dirs = sorted(
        path
        for path in TASKS.iterdir()
        if path.name.endswith(f"__{SEED}")
        and (path / "solution_witnesses.json").is_file()
    )
    for index, task_dir in enumerate(task_dirs, start=1):
        instance_id = task_dir.name.split("__")[1]
        witness = json.loads(
            (task_dir / "solution_witnesses.json").read_text(encoding="utf-8")
        )[ARM]
        summary, rows = audit_instance(instance_id, witness)
        summaries.append(summary)
        all_rows.extend(rows)
        print(
            f"[{index:>2}/{len(task_dirs)}] {instance_id:<32} "
            f"allCV={summary['all_cv_cost']:>12.4f} "
            f"sealed={summary['sealed_cost']:>12.4f} "
            f"forcedMaxEV={summary['forced_maxev_cost']:>12.4f} "
            f"({summary['forced_vs_sealed_pct']:+.3f}%) "
            f"evFeasRoutes={summary['ev_feasible_routes']}/{summary['routes']}",
            flush=True,
        )

    with (OUT / "m2_instance_summary.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0].keys()))
        writer.writeheader()
        writer.writerows(summaries)

    with (OUT / "m2_raw_runs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)

    forced_better = sum(
        1
        for s in summaries
        if s["forced_maxev_cost"] < s["sealed_cost"] - TOL
    )
    forced_worse = sum(
        1
        for s in summaries
        if s["forced_maxev_cost"] > s["sealed_cost"] + TOL
    )
    any_station = sum(
        1 for s in summaries if s["forced_maxev_station_charging_kwh"] > 0
    )
    negative_variants = sum(s["per_route_negative_deltas"] for s in summaries)
    feasible_variants = sum(s["per_route_feasible_variants"] for s in summaries)

    overall = {
        "schema": "resetp.joint-decoder-headroom.m2.v1",
        "arm": ARM,
        "seed": SEED,
        "instances": len(summaries),
        "all_cv_feasible_instances": sum(
            1 for s in summaries if s["all_cv_feasible"]
        ),
        "forced_maxev_better_than_sealed": forced_better,
        "forced_maxev_worse_than_sealed": forced_worse,
        "forced_maxev_equal_to_sealed": len(summaries)
        - forced_better
        - forced_worse,
        "mean_forced_vs_sealed_pct": round(
            statistics.mean(s["forced_vs_sealed_pct"] for s in summaries), 6
        ),
        "median_forced_vs_sealed_pct": round(
            statistics.median(s["forced_vs_sealed_pct"] for s in summaries), 6
        ),
        "ev_route_feasible_rate_mean": round(
            statistics.mean(s["ev_route_feasible_rate"] for s in summaries), 6
        ),
        "single_route_ev_variants_feasible": feasible_variants,
        "single_route_ev_variants_cheaper_than_cv": negative_variants,
        "instances_with_station_charging_under_forced_maxev": any_station,
        "sealed_instances_with_station_charging": sum(
            1 for s in summaries if s["sealed_station_charging_kwh"] > 0
        ),
    }
    (OUT / "m2_summary.json").write_text(
        json.dumps(overall, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print()
    print(json.dumps(overall, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
