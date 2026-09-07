#!/usr/bin/env python3
"""First-trip charging window projection: same-day 00:00 vs last night's return.

**No search is run here.**  Every solution is read from a finished batch and
re-settled twice with its routes, trips and fleet held fixed -- once under the
historical window (the first trip's depot charge may start from the simulation
day's own 00:00) and once under the new one (it may start when the vehicle came
back to the depot the preceding evening).  Only the charging instants can move.

For every solution and every charge-timing policy the probe records

* the first-trip depot charge of every electric duty (day offset + start),
* whether the whole solution can still be evaluated, and its breakdown,
* and, separately, whether flipping ONLY the depot-window mode
  (``same_day_predeparture`` -> ``full_gap``, which the preceding-day placement
  needs to survive the ledger replay) changes anything on its own.

That last check matters because the new window forces the mode switch: without
it a difference could not be attributed to the window rather than the mode.

Usage (repository root)::

    export PYTHONPATH='solver/src:third_party/setp_hgs_kernel:models/src:solver/scripts'
    .public-hgs-venv/bin/python3 \\
        solver/scripts/probe_first_trip_charge_window_20260906.py \\
        --out-dir solver/reports/first_trip_window_probe_20260906
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

POLICIES = ("asap", "cost_plus_carbon")
ARMS = ("MT-HGS", "MTC-HGS")
REPORTED_KEYS = (
    "total_cost",
    "cost_elec",
    "cost_carbon",
    "E_ev_indirect",
    "E_total",
    "electricity_kwh",
    "n_veh_ev",
    "n_veh_cv",
)

BEIJING_CAL = "data/ChinaInstances/china81_runtime_parameter_authority_v4_20260723"
MIDDAY_CAL = "data/ChinaInstances/china81_cf_calendar_midday_valley_v1_20260904"

# The four cells of the 2x2.  beijing x 1.0 is NOT in grid2x2_v2_20260905:
# that cell was deliberately not re-run on 09-05 and still lives in the older
# batch (see grid2x2_v2_20260905/build_comparisons.sh).
CELLS: tuple[dict[str, Any], ...] = (
    {
        "cell": "beijing_P0.2",
        "batch": "solver/reports/grid2x2_v2_20260905/beijing/P=0.2",
        "carbon_price": 0.2,
        "calendar": BEIJING_CAL,
    },
    {
        "cell": "beijing_P1.0",
        "batch": "solver/reports/grid2x2_20260905/beijing/P=1.0",
        "carbon_price": 1.0,
        "calendar": BEIJING_CAL,
    },
    {
        "cell": "midday_P0.2",
        "batch": "solver/reports/grid2x2_v2_20260905/midday/P=0.2",
        "carbon_price": 0.2,
        "calendar": MIDDAY_CAL,
    },
    {
        "cell": "midday_P1.0",
        "batch": "solver/reports/grid2x2_v2_20260905/midday/P=1.0",
        "carbon_price": 1.0,
        "calendar": MIDDAY_CAL,
    },
)


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _first_trip_depot_charges(individual) -> dict[str, list[float]]:
    """Per electric duty: ``[day_offset, local_start_second]`` of trip 1."""

    placements: dict[str, list[float]] = {}
    for duty in individual.duties:
        for session in duty.charging_sessions:
            if (
                int(session.trip_index) == 1
                and session.station_id == duty.home_depot_id
            ):
                placements[duty.physical_vehicle_id] = [
                    float(session.charge_day_offset),
                    float(session.charge_start_second),
                ]
    return dict(sorted(placements.items()))


def _duty_last_return_seconds(individual, context) -> dict[str, float]:
    """Each duty's own last-trip return in the settled plan.

    Read from the same multi-trip certificate the ledger replay uses, one duty
    at a time (a single duty always has one first-trip charge day offset, so
    this never trips the solution-wide uniformity rule).
    """

    from setp_solver.algorithms.problem_hgs.evaluation import (
        _shift_minimum_departure_second_by_route,
    )
    from setp_solver.algorithms.problem_hgs.model import DutyIndividual
    from setp_solver.search.multitrip_schedule import prepare_multitrip_solution

    returns: dict[str, float] = {}
    for duty in individual.duties:
        # Registered-but-idle vehicle slots carry no trip and no charge.
        if not duty.trips:
            continue
        solution = DutyIndividual(
            duties=(duty,), source="first-trip-window-return-check"
        ).to_solution()
        _prepared, certificate = prepare_multitrip_solution(
            solution,
            context.bundle.instance,
            context.bundle.prices,
            depot_charge_window_mode=context.depot_charge_window_mode,
            minimum_departure_second_by_route=(
                _shift_minimum_departure_second_by_route(solution, context)
            ),
        )
        returns[duty.physical_vehicle_id] = max(
            float(trip.return_second) for trip in certificate.trips
        )
    return returns


def _absolute_starts(placements: dict[str, list[float]]) -> dict[str, float]:
    return {
        vehicle: offset * 86_400.0 + start
        for vehicle, (offset, start) in placements.items()
    }


def _settle_once(
    *,
    individual,
    context,
    evaluator,
    policy,
    repair_changed_duties,
) -> dict[str, Any]:
    changed = {duty.physical_vehicle_id for duty in individual.duties}
    try:
        repaired = repair_changed_duties(
            individual,
            individual,
            changed_duty_ids=changed,
            context=context,
            policy=policy,
        )
    except Exception as error:  # repair refuses this route set
        return {"status": "repair_failed", "error": f"{type(error).__name__}: {error}"}
    placements = _first_trip_depot_charges(repaired)
    record: dict[str, Any] = {
        "status": "ok",
        "first_trip_depot_charge": placements,
        "day_offsets": sorted({int(value[0]) for value in placements.values()}),
        "_repaired": repaired,
    }
    try:
        evaluation = evaluator.evaluate(repaired)
    except Exception as error:
        # The certificate carries ONE first-trip charge day offset for the
        # whole solution, so a plan whose vehicles disagree cannot be evaluated
        # at all.  That is a fact about the window rule, recorded not swallowed.
        record["status"] = "evaluation_refused"
        record["error"] = f"{type(error).__name__}: {error}"
        return record
    record["feasible"] = bool(evaluation.feasible)
    record["violations"] = [str(item) for item in evaluation.violations]
    record["breakdown"] = {
        key: float(evaluation.breakdown[key])
        for key in REPORTED_KEYS
        if key in evaluation.breakdown
    }
    return record


def _return_consistency(repaired, context) -> dict[str, Any]:
    """Does a preceding-day charge really start at last night's return?

    The window's opening instant is measured by an extra anchoring pass, so it
    can in principle disagree with the return the settled plan ends up with.
    Anything other than an exact match, and a placement sitting exactly on the
    contract's last shift end (68400 s, the single-trip fallback), is reported.
    """

    returns = _duty_last_return_seconds(repaired, context)
    rows = []
    for duty in repaired.duties:
        for session in duty.charging_sessions:
            if (
                int(session.trip_index) != 1
                or session.station_id != duty.home_depot_id
                or int(session.charge_day_offset) != -1
            ):
                continue
            start = float(session.charge_start_second)
            last_return = returns[duty.physical_vehicle_id]
            rows.append(
                {
                    "vehicle": duty.physical_vehicle_id,
                    "charge_start_second": start,
                    "settled_last_return_second": last_return,
                    "difference_second": start - last_return,
                    "on_shift_end_fallback": abs(start - 68_400.0) < 1e-6,
                    "n_trips": len(duty.trips),
                }
            )
    return {
        "n_prev_day_charges": len(rows),
        "n_exact_match": sum(
            1 for row in rows if abs(row["difference_second"]) < 1e-6
        ),
        "n_on_shift_end_fallback": sum(
            1 for row in rows if row["on_shift_end_fallback"]
        ),
        "rows": rows,
    }


def probe_cell(
    repo: Path,
    comparison,
    runtime,
    cell: dict[str, Any],
    *,
    verbose: bool = True,
) -> dict[str, Any]:
    from setp_solver.algorithms.problem_hgs.charging import repair_changed_duties
    from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator

    batch_dir = (repo / cell["batch"]).resolve()
    runs, shared = comparison._collect_runs(batch_dir)
    fleet_class = runtime.FLEET_PARAMETER_CLASSES[shared["fleet_parameter_class"]]
    quotas = {
        float(run["carbon_quota_kg"])
        for arm_runs in runs.values()
        for run in arm_runs
    }
    if len(quotas) != 1:
        raise SystemExit(f"{cell['cell']}: batch mixes carbon quotas {sorted(quotas)}")
    quota = next(iter(quotas))
    carbon_price = float(cell["carbon_price"])
    if float(shared["carbon_price_cny_per_kg"]) != carbon_price:
        raise SystemExit(
            f"{cell['cell']}: batch carbon price "
            f"{shared['carbon_price_cny_per_kg']} != declared {carbon_price}"
        )

    bundle, _initial, _np, base_context = runtime._build_context(
        repo,
        shared["instance_id"],
        fleet_parameters=fleet_class,
        tariff_calendar_authority=cell["calendar"],
    )
    bundle = replace(
        bundle,
        prices=replace(bundle.prices, carbon_price=carbon_price),
        carbon_price_cny_per_kg=carbon_price,
    )
    base_context = replace(base_context, bundle=bundle, carbon_quota_kg=quota)

    old_context = replace(
        base_context, depot_charge_window_mode="same_day_predeparture"
    )
    new_context = replace(base_context, depot_charge_window_mode="full_gap")
    old_evaluator = DutyFullEvaluator(old_context)
    new_evaluator = DutyFullEvaluator(new_context)
    old_policies = {
        name: runtime._policy(
            old_evaluator, charge_timing_policy=name, first_trip_window="same_day"
        )
        for name in POLICIES
    }
    new_policies = {
        name: runtime._policy(
            new_evaluator,
            charge_timing_policy=name,
            first_trip_window="prev_return",
        )
        for name in POLICIES
    }

    rows: list[dict[str, Any]] = []
    mode_inertness: list[dict[str, Any]] = []
    for arm in ARMS:
        for run in runs[arm]:
            individual = comparison._rebuild_individual(runtime, run["solution"])
            for name in POLICIES:
                old = _settle_once(
                    individual=individual,
                    context=old_context,
                    evaluator=old_evaluator,
                    policy=old_policies[name],
                    repair_changed_duties=repair_changed_duties,
                )
                new = _settle_once(
                    individual=individual,
                    context=new_context,
                    evaluator=new_evaluator,
                    policy=new_policies[name],
                    repair_changed_duties=repair_changed_duties,
                )
                # Mode-only control: the SAME re-settled plan (produced under
                # the historical window) evaluated by the full_gap evaluator.
                # Any difference here belongs to the depot-window mode, not to
                # the window rule.
                repaired = old.pop("_repaired", None)
                new_repaired = new.pop("_repaired", None)
                if new_repaired is not None:
                    new["return_consistency"] = _return_consistency(
                        new_repaired, new_context
                    )
                if repaired is not None and old.get("status") == "ok":
                    try:
                        mode_only = new_evaluator.evaluate(repaired)
                        mode_only_breakdown = {
                            key: float(mode_only.breakdown[key])
                            for key in REPORTED_KEYS
                            if key in mode_only.breakdown
                        }
                        mode_inertness.append(
                            {
                                "solution": f"{arm}/{run['run']}",
                                "policy": name,
                                "identical": mode_only_breakdown
                                == old.get("breakdown"),
                                "same_day_mode": old.get("breakdown"),
                                "full_gap_mode": mode_only_breakdown,
                            }
                        )
                    except Exception as error:
                        mode_inertness.append(
                            {
                                "solution": f"{arm}/{run['run']}",
                                "policy": name,
                                "identical": False,
                                "error": f"{type(error).__name__}: {error}",
                            }
                        )
                row: dict[str, Any] = {
                    "arm": arm,
                    "run": run["run"],
                    "native_policy": run["policy"],
                    "policy": name,
                    "same_day": old,
                    "prev_return": new,
                }
                if old.get("status") == "ok" and new.get("status") == "ok":
                    row["charge_placement_identical"] = (
                        old["first_trip_depot_charge"]
                        == new["first_trip_depot_charge"]
                    )
                    if "breakdown" in old and "breakdown" in new:
                        row["delta"] = {
                            key: new["breakdown"][key] - old["breakdown"][key]
                            for key in old["breakdown"]
                            if key in new["breakdown"]
                        }
                        row["breakdown_identical"] = all(
                            value == 0.0 for value in row["delta"].values()
                        )
                    row["absolute_start_shift_second"] = {
                        vehicle: _absolute_starts(new["first_trip_depot_charge"])[
                            vehicle
                        ]
                        - value
                        for vehicle, value in _absolute_starts(
                            old["first_trip_depot_charge"]
                        ).items()
                        if vehicle in new["first_trip_depot_charge"]
                    }
                rows.append(row)
                if verbose:
                    print(
                        f"  {arm}/{run['run']:<7} {name:<17} "
                        f"same_day={old.get('status')} "
                        f"prev_return={new.get('status')}",
                        flush=True,
                    )
    return {
        "cell": cell["cell"],
        "batch_dir": str(batch_dir.relative_to(repo)),
        "calendar_authority": cell["calendar"],
        "carbon_price_cny_per_kg": carbon_price,
        "carbon_quota_kg": quota,
        "instance_id": shared["instance_id"],
        "n_runs": {arm: len(runs[arm]) for arm in ARMS},
        "rows": rows,
        "mode_only_control": mode_inertness,
    }


def _summarise(cell_result: dict[str, Any]) -> dict[str, Any]:
    """The two contrasts the projection was asked for, per cell."""

    def _pick(arm: str, policy: str) -> list[dict[str, Any]]:
        return [
            row
            for row in cell_result["rows"]
            if row["arm"] == arm and row["policy"] == policy
        ]

    def _block(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
        settled = [
            row
            for row in rows
            if row["same_day"].get("status") == "ok"
            and row["prev_return"].get("status") == "ok"
        ]
        comparable = [row for row in settled if "delta" in row]
        placement_same = [
            row for row in settled if row.get("charge_placement_identical")
        ]
        block: dict[str, Any] = {
            "n_solutions": len(rows),
            "n_both_settled": len(settled),
            "n_both_evaluated": len(comparable),
            "n_charge_placement_identical": len(placement_same),
            "n_breakdown_identical": sum(
                1 for row in comparable if row.get("breakdown_identical")
            ),
            "prev_return_status_counts": {},
            "same_day_status_counts": {},
        }
        for key, side in (
            ("prev_return_status_counts", "prev_return"),
            ("same_day_status_counts", "same_day"),
        ):
            counts: dict[str, int] = {}
            for row in rows:
                status = str(row[side].get("status"))
                counts[status] = counts.get(status, 0) + 1
            block[key] = counts
        if comparable:
            for metric in ("total_cost", "cost_elec", "E_total", "E_ev_indirect"):
                deltas = [
                    row["delta"][metric]
                    for row in comparable
                    if metric in row["delta"]
                ]
                if deltas:
                    block[f"delta_{metric}"] = {
                        "mean": sum(deltas) / len(deltas),
                        "min": min(deltas),
                        "max": max(deltas),
                    }
        starts_old: list[float] = []
        starts_new: list[float] = []
        for row in settled:
            starts_old.extend(
                _absolute_starts(row["same_day"]["first_trip_depot_charge"]).values()
            )
            starts_new.extend(
                _absolute_starts(
                    row["prev_return"]["first_trip_depot_charge"]
                ).values()
            )
        if starts_old:
            block["first_trip_start_second_same_day"] = {
                "min": min(starts_old),
                "max": max(starts_old),
                "mean": sum(starts_old) / len(starts_old),
                "n": len(starts_old),
            }
        if starts_new:
            block["first_trip_start_second_prev_return"] = {
                "min": min(starts_new),
                "max": max(starts_new),
                "mean": sum(starts_new) / len(starts_new),
                "n": len(starts_new),
            }
        return block

    checks = [
        row["prev_return"]["return_consistency"]
        for row in cell_result["rows"]
        if "return_consistency" in row["prev_return"]
    ]
    return {
        "a_mtc_cost_plus_carbon": _block(_pick("MTC-HGS", "cost_plus_carbon")),
        "b_mt_asap": _block(_pick("MT-HGS", "asap")),
        "mode_only_control_all_identical": all(
            item.get("identical") for item in cell_result["mode_only_control"]
        ),
        "mode_only_control_n": len(cell_result["mode_only_control"]),
        "return_consistency": {
            "n_prev_day_charges": sum(
                item["n_prev_day_charges"] for item in checks
            ),
            "n_exact_match": sum(item["n_exact_match"] for item in checks),
            "n_on_shift_end_fallback": sum(
                item["n_on_shift_end_fallback"] for item in checks
            ),
            "worst_difference_second": max(
                (
                    abs(row["difference_second"])
                    for item in checks
                    for row in item["rows"]
                ),
                default=0.0,
            ),
        },
    }


def probe_carbon_price_sweep(
    repo: Path,
    comparison,
    runtime,
    sweep_dir: Path,
    *,
    verbose: bool = True,
) -> dict[str, Any]:
    """At which carbon prices does the new window change the carbon-aware arm?

    The 2x2 only samples two carbon prices.  The sweep batch samples 22, all
    solved under ``cost_plus_carbon``, so it locates the price above which the
    preceding afternoon (the grid's cleanest hours) beats the night valley and
    the first-trip charge starts moving.  Same contract as everywhere here:
    fixed routes, no search.
    """

    from setp_solver.algorithms.problem_hgs.charging import repair_changed_duties
    from setp_solver.algorithms.problem_hgs.evaluation import DutyFullEvaluator

    rows: list[dict[str, Any]] = []
    for price_dir in sorted(
        (path for path in sweep_dir.iterdir() if path.name.startswith("P=")),
        key=lambda path: float(path.name.split("=", 1)[1]),
    ):
        carbon_price = float(price_dir.name.split("=", 1)[1])
        run_dirs = sorted(
            path
            for path in price_dir.iterdir()
            if path.is_dir() and (path / "best_solution.json").exists()
        )
        if not run_dirs:
            continue
        first_metadata = json.loads(
            (run_dirs[0] / "metadata.json").read_text(encoding="utf-8")
        )
        calendar = first_metadata.get("tariff_calendar_authority")
        quota = float(first_metadata.get("effective_carbon_quota_kg") or 0.0)
        fleet_class = runtime.FLEET_PARAMETER_CLASSES[
            first_metadata["fleet_parameter_class"]
        ]
        bundle, _initial, _np, base_context = runtime._build_context(
            repo,
            first_metadata["instance_id"],
            fleet_parameters=fleet_class,
            tariff_calendar_authority=calendar,
        )
        bundle = replace(
            bundle,
            prices=replace(bundle.prices, carbon_price=carbon_price),
            carbon_price_cny_per_kg=carbon_price,
        )
        base_context = replace(base_context, bundle=bundle, carbon_quota_kg=quota)
        old_context = replace(
            base_context, depot_charge_window_mode="same_day_predeparture"
        )
        new_context = replace(base_context, depot_charge_window_mode="full_gap")
        old_evaluator = DutyFullEvaluator(old_context)
        new_evaluator = DutyFullEvaluator(new_context)
        old_policy = runtime._policy(
            old_evaluator,
            charge_timing_policy="cost_plus_carbon",
            first_trip_window="same_day",
        )
        new_policy = runtime._policy(
            new_evaluator,
            charge_timing_policy="cost_plus_carbon",
            first_trip_window="prev_return",
        )
        for run_dir in run_dirs:
            solution = json.loads(
                (run_dir / "best_solution.json").read_text(encoding="utf-8")
            )
            individual = comparison._rebuild_individual(runtime, solution)
            old = _settle_once(
                individual=individual,
                context=old_context,
                evaluator=old_evaluator,
                policy=old_policy,
                repair_changed_duties=repair_changed_duties,
            )
            new = _settle_once(
                individual=individual,
                context=new_context,
                evaluator=new_evaluator,
                policy=new_policy,
                repair_changed_duties=repair_changed_duties,
            )
            old.pop("_repaired", None)
            new.pop("_repaired", None)
            placements = new.get("first_trip_depot_charge") or {}
            row = {
                "carbon_price_cny_per_kg": carbon_price,
                "run": run_dir.name,
                "same_day_status": old.get("status"),
                "prev_return_status": new.get("status"),
                "n_ev_with_first_trip_charge": len(placements),
                "n_moved_to_previous_day": sum(
                    1 for offset, _start in placements.values() if int(offset) == -1
                ),
                "charge_placement_identical": (
                    old.get("first_trip_depot_charge")
                    == new.get("first_trip_depot_charge")
                    if old.get("status") == "ok" and new.get("status") == "ok"
                    else None
                ),
            }
            if "breakdown" in old and "breakdown" in new:
                row["delta"] = {
                    key: new["breakdown"][key] - old["breakdown"][key]
                    for key in old["breakdown"]
                    if key in new["breakdown"]
                }
            rows.append(row)
            if verbose:
                print(
                    f"  P={carbon_price:<8} {run_dir.name}  "
                    f"moved={row['n_moved_to_previous_day']}/"
                    f"{row['n_ev_with_first_trip_charge']}  "
                    f"prev_return={new.get('status')}",
                    flush=True,
                )
    by_price: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = f"{row['carbon_price_cny_per_kg']}"
        block = by_price.setdefault(
            key,
            {
                "n_runs": 0,
                "n_runs_with_a_moved_charge": 0,
                "n_runs_unevaluable_under_prev_return": 0,
                "n_runs_bit_identical": 0,
            },
        )
        block["n_runs"] += 1
        if row["n_moved_to_previous_day"] > 0:
            block["n_runs_with_a_moved_charge"] += 1
        if row["prev_return_status"] != "ok":
            block["n_runs_unevaluable_under_prev_return"] += 1
        if row.get("charge_placement_identical"):
            block["n_runs_bit_identical"] += 1
    return {
        "sweep_dir": str(sweep_dir.relative_to(repo)),
        "policy": "cost_plus_carbon",
        "rows": rows,
        "by_carbon_price": by_price,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("solver/reports/first_trip_window_probe_20260906"),
    )
    parser.add_argument("--cells", default=None, help="comma-separated cell names")
    parser.add_argument(
        "--sweep-dir",
        type=Path,
        default=None,
        help=(
            "instead of the 2x2 cells, scan a carbon-price sweep batch "
            "(P=*/run_*) for the price above which the window starts moving"
        ),
    )
    args = parser.parse_args(argv)

    repo = args.repo_root.resolve()
    out_dir = args.out_dir if args.out_dir.is_absolute() else repo / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    comparison = _load_module(
        repo / "solver/scripts/build_charge_timing_comparison.py",
        "resetp_charge_timing_comparison",
    )
    runtime = comparison._load_runtime(repo)

    if args.sweep_dir is not None:
        sweep_dir = (
            args.sweep_dir
            if args.sweep_dir.is_absolute()
            else repo / args.sweep_dir
        ).resolve()
        result = probe_carbon_price_sweep(repo, comparison, runtime, sweep_dir)
        target = out_dir / "carbon_price_sweep_probe.json"
        target.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )
        print(f"\nwritten -> {target}", flush=True)
        return 0

    wanted = (
        None
        if args.cells is None
        else {name.strip() for name in args.cells.split(",") if name.strip()}
    )
    results = []
    for cell in CELLS:
        if wanted is not None and cell["cell"] not in wanted:
            continue
        print(f"== {cell['cell']} ==", flush=True)
        result = probe_cell(repo, comparison, runtime, cell)
        result["summary"] = _summarise(result)
        results.append(result)

    payload = {
        "what": (
            "first-trip depot charging window projection; fixed routes, "
            "no search"
        ),
        "windows": {
            "same_day": (
                "historical: the first trip's depot charge may start from the "
                "simulation day's own 00:00 (depot window mode "
                "same_day_predeparture)"
            ),
            "prev_return": (
                "new: it may start when the vehicle came back to the depot on "
                "the preceding evening -- the duty's own last-trip return "
                "mapped one day back, or the contract's last shift end (19:00) "
                "for a single-trip duty (depot window mode full_gap)"
            ),
        },
        "cells": results,
    }
    (out_dir / "probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nwritten -> {out_dir / 'probe.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
