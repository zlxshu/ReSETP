"""Diagnose saved section 4.4 schedules using production charging functions.

This is not a search arm or a paper table. Depot charging alone is retimed;
public sessions, routes, quantities, SOC and all trip clocks remain fixed.
Existing loader, curve integration and timing breakpoints own all physics.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import replace
from pathlib import Path

from run_problem_hgs_private_technical import _load_v3_suite_bundle
from setp_solver.china81 import ENDOGENOUS_FLEET_PARAMETERS
from setp_solver.charge_timing import (
    ChargeTimingContexts, _timing_candidates, select_charge_timing_start,
)
from setp_solver.cost import (
    charging_action_electricity_cost, charging_action_emissions_kg,
)
from setp_solver.search.metaheuristic_baselines import solution_from_dict

ROOT = Path(__file__).resolve().parents[2]
POLICIES = ("asap", "cost_min", "carbon_min", "cost_plus_carbon")
DAY = 86400.0


def sources():
    reports = ROOT / "solver/reports"
    for calendar, price, extra in (
        ("beijing", "0.2", "charging_arrangements_20260906"),
        ("midday", "1.0", "charging_arrangements_midday_P1.0_20260909"),
    ):
        for arm in ("MT-HGS", "MTC-HGS"):
            yield from (reports / "grid2x2_v3_20260906" / calendar / f"P={price}" / arm).glob("run_*/best_solution.json")
        for arm in ("cost_min", "carbon_min"):
            yield from (reports / extra / arm).glob("run_*/best_solution.json")


def load_bundle(meta, cache):
    key = (meta["bundle_source_paths"]["tariff_carbon_calendar"], meta["carbon_price_cny_per_kg"])
    if key not in cache:
        bundle, _ = _load_v3_suite_bundle(
            ROOT, package_root=ROOT / meta["bundle_source_paths"]["suite"],
            instance_id=meta["instance_id"], fleet_parameters=ENDOGENOUS_FLEET_PARAMETERS,
            tariff_calendar_authority=(ROOT / key[0]).parent,
        )
        bundle = replace(bundle, prices=replace(bundle.prices, carbon_price=key[1]), carbon_price_cny_per_kg=key[1])
        cache[key] = bundle
    return cache[key]


def bounds(action, clocks):
    vehicle, trip = action.vehicle_id.rsplit("#T", 1)
    trips = clocks[vehicle]
    index = int(trip)
    earliest = max(t["return_second"] for t in trips.values()) - DAY if index == 1 else trips[index - 1]["return_second"]
    latest = trips[index]["departure_second"] - action.occupancy_minutes * 60
    window = "first" if index == 1 else "lunch" if earliest <= 39600 and trips[index]["departure_second"] >= 46800 else "between"
    return earliest, latest, window


def at_start(action, absolute):
    offset = int(absolute // DAY)
    return replace(action, charge_start_second=absolute - offset * DAY, charge_day_offset=offset)


def settle(action, bundle):
    args = (action, bundle.instance, bundle.time_profile, bundle.prices)
    return charging_action_electricity_cost(*args), charging_action_emissions_kg(*args)


def diagnose(path, cache):
    saved = json.loads(path.read_text())
    meta = json.loads(path.with_name("metadata.json").read_text())
    bundle = load_bundle(meta, cache)
    source_policy = meta["mechanism_closure"]["effective_charge_timing_policy"]
    solution = solution_from_dict(saved["evaluation"]["prepared_solution"])
    baseline = saved["evaluation"]["breakdown"]
    raw = list(csv.DictReader(path.with_name("raw_runs.csv").open()))[-1]
    assert saved["evaluation"]["feasible"] and int(raw["customers_served"]) == 50
    assert float(raw["demand_served"]) == 13264
    clocks = {}
    for trip in saved["trip_clock"]:
        clocks.setdefault(trip["physical_vehicle_id"], {})[trip["trip_index"]] = trip
    old = [settle(action, bundle) for action in solution.charging_actions]
    assert abs(sum(x[0] for x in old) - baseline["cost_elec"]) < 1e-6
    assert abs(sum(x[1] for x in old) - baseline["E_ev_indirect"]) < 1e-6
    records, outputs = [], []
    contexts = ChargeTimingContexts(bundle.instance, bundle.prices)
    for policy in POLICIES:
        costs, emissions, actions = [], [], []
        for i, action in enumerate(solution.charging_actions):
            node = bundle.instance.node_lookup[action.station_id]
            if node.node_type.lower() != "d":
                shifted, window, earliest, latest = action, "public_fixed", None, None
            else:
                earliest, latest, window = bounds(action, clocks)
                old_start = action.charge_start_second + DAY * action.charge_day_offset
                assert earliest - 1e-6 <= old_start <= latest + 1e-6, (path, action, earliest, latest)
                # The production profile is cyclic but rejects negative slots.
                # Translate the entire window one day; restore offsets afterwards.
                shift = DAY if earliest < 0 else 0.0
                absolute_action = replace(action, charge_start_second=old_start + shift, charge_day_offset=0)
                start = select_charge_timing_start(
                    absolute_action, earliest_start_second=earliest + shift, latest_start_second=max(earliest, latest) + shift,
                    instance=bundle.instance, carbon_profile=bundle.time_profile,
                    prices=bundle.prices, charge_timing_policy=policy, timing_contexts=contexts,
                )
                shifted = at_start(action, start - shift)
            cost, emission = settle(shifted, bundle)
            costs.append(cost); emissions.append(emission); actions.append(shifted)
            record = dict(source=str(path.relative_to(ROOT)), source_policy=source_policy, policy=policy,
                          vehicle=action.vehicle_id, window=window, energy_kwh=action.energy_kwh,
                          earliest=earliest, latest=latest,
                          original_start=action.charge_start_second + DAY * action.charge_day_offset,
                          start=shifted.charge_start_second + DAY * shifted.charge_day_offset,
                          old_cost=old[i][0], old_emission=old[i][1], cost=cost, emission=emission)
            if policy == "cost_min" and earliest is not None:
                candidates = _timing_candidates(absolute_action, earliest + shift, max(earliest, latest) + shift, bundle.instance, bundle.prices)
                ties = [settle(at_start(action, t - shift), bundle) for t in candidates]
                record["same_bill_min_emission"] = min(e for c, e in ties if abs(c - cost) < 1e-7)
            records.append(record)
        new_cost = baseline["total_cost"] + sum(costs) - baseline["cost_elec"] + bundle.prices.carbon_price * (sum(emissions) - baseline["E_ev_indirect"])
        outputs.append(dict(source=str(path.relative_to(ROOT)), source_policy=source_policy, policy=policy,
                            carbon_price=bundle.prices.carbon_price, cost_elec=sum(costs),
                            E_ev_indirect=sum(emissions), E_total=baseline["E_cv_direct"] + sum(emissions),
                            total_cost=new_cost, original_total_cost=baseline["total_cost"],
                            original_E_total=baseline["E_total"], n_cv=baseline["n_veh_cv"], n_ev=baseline["n_veh_ev"],
                            customers_served=50, demand_served=13264,
                            original_full_feasible=True, fixed_clock_windows_feasible=True))
    return outputs, records


def write_csv(path, rows):
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader(); writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    cache, rows, sessions, failures = {}, [], [], []
    paths = sorted(sources())
    if args.limit:
        paths = paths[:args.limit]
    for path in paths:
        try:
            new_rows, new_sessions = diagnose(path, cache)
            rows.extend(new_rows); sessions.extend(new_sessions)
            print(f"{len(rows)//4}/{len(paths)} {path.parent}", flush=True)
        except Exception as exc:
            failures.append(dict(source=str(path.relative_to(ROOT)), error=repr(exc)))
    write_csv(args.output / "runs.csv", rows)
    write_csv(args.output / "sessions.csv", sessions)
    (args.output / "failures.json").write_text(json.dumps(failures, indent=2))
    print(json.dumps(dict(sources=len(paths), evaluations=len(rows), failures=failures)), flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
