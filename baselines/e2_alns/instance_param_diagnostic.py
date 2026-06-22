"""09e instance parameter diagnostic for E2 all-CV degeneration.

This is a diagnostic runner only. It does not modify model parameters,
instances, cost/check/evaluation semantics, or promoted algorithms. All
parameter perturbations are in-memory ``dataclasses.replace`` copies of
``DEFAULT_PRICES`` and every reported solution is independently re-evaluated
with the same prices object used for the run.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import numpy as np

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES, PriceParameters
from setp_solver.solution import ChargingAction, Route, Solution
from setp_solver.search.alns_wouda import SearchPolicy, run_alns_wouda
from setp_solver.search.bundle import SearchBundle, load_search_bundle
from setp_solver.search.charging import repair_route_charging
from setp_solver.search.construction import build_initial_solution
from setp_solver.search.fleet import FleetLimits, UNBOUNDED_FLEET, route_ev_energy_summary


DEFAULT_INSTANCES = (
    "vanilla/e2-vanilla-25c-01",
    "vanilla/e2-vanilla-50c-01",
    "threeshift/e2-threeshift-50c-01",
)

VARIANTS = ("cv_only", "ev_only", "mixed")
PHASE1_SEEDS = (1, 2, 3)
PHASE2_SCAN_SEEDS = (1,)
PHASE2_REFINE_EXTRA_SEEDS = (2, 3)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="Repository root.")
    parser.add_argument("--output-dir", default="baselines/e2_alns/instance_param_diagnostic_data")
    parser.add_argument("--report-path", default="baselines/e2_alns/instance_param_diagnostic.md")
    parser.add_argument("--eval-budget", type=int, default=120)
    parser.add_argument("--max-runtime-seconds", type=float, default=20.0)
    parser.add_argument("--phase0-only", action="store_true")
    parser.add_argument("--phase2-mode", choices=("fixed_replay", "resolve"), default="fixed_replay")
    parser.add_argument("--instances", nargs="*", default=list(DEFAULT_INSTANCES))
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    metadata = _metadata(repo_root, args)
    phase0 = phase0_audit(repo_root)
    _write_json(output_dir / "phase0_audit.json", phase0)

    phase1_rows: list[dict[str, Any]] = []
    phase2_rows: list[dict[str, Any]] = []
    conclusion = {
        "verdict": "PHASE0_ONLY",
        "summary": "Phase 0 audit only; Phase 1 and Phase 2 were not run.",
    }

    if not args.phase0_only:
        phase1_rows = run_phase1(repo_root, args.instances, int(args.eval_budget), float(args.max_runtime_seconds))
        _write_csv(output_dir / "phase1_cost_breakdown.csv", phase1_rows)

        phase2_rows = run_phase2(
            repo_root,
            args.instances,
            int(args.eval_budget),
            float(args.max_runtime_seconds),
            phase1_rows,
            str(args.phase2_mode),
        )
        _write_csv(output_dir / "phase2_scan.csv", phase2_rows)

        conclusion = summarize_conclusion(phase1_rows, phase2_rows)

    metadata["elapsed_seconds"] = time.perf_counter() - started
    metadata["phase0_only"] = bool(args.phase0_only)
    _write_json(output_dir / "metadata.json", metadata)

    report = render_report(metadata, phase0, phase1_rows, phase2_rows, conclusion)
    (repo_root / args.report_path).write_text(report, encoding="utf-8")
    print(json.dumps({"report": args.report_path, "output_dir": args.output_dir, "conclusion": conclusion}, ensure_ascii=False))
    return 0


def phase0_audit(repo_root: Path) -> dict[str, Any]:
    bundle = _load_bundle(repo_root, "vanilla/e2-vanilla-25c-01")
    base = replace(DEFAULT_PRICES, carbon_price=0.05034)
    slow = replace(base, v_speed_ms=11.1)
    big_battery = replace(base, B_battery_kwh=480.0)
    tiny_battery = replace(base, B_battery_kwh=0.1)
    cheap_public = replace(base, electricity_price=0.1853, station_electricity_price=0.1853)

    cv_seed = _cv_warm(bundle, base)
    customer_id = _first_customer(bundle)
    depot_id = _nearest_depot(bundle, customer_id)
    probe_route = Route("EV_PROBE", "ev", depot_id, [depot_id, customer_id, depot_id])

    one_ev_big = _one_ev_warm(bundle, big_battery)
    big_violations = check_solution(one_ev_big, bundle.instance, big_battery)
    tiny_violations = check_solution(one_ev_big, bundle.instance, tiny_battery)

    ev_default = _route_ev_kwh(probe_route, bundle, base)
    ev_slow = _route_ev_kwh(probe_route, bundle, slow)
    public_probe = _public_charge_probe(bundle)
    eval_default = evaluate(public_probe, bundle.instance, bundle.carbon_profile, base)
    eval_cheap = evaluate(public_probe, bundle.instance, bundle.carbon_profile, cheap_public)

    solver_probe = _solver_objective_probe(bundle, base, cheap_public)

    return {
        "schema_version": "setp-09e-phase0.v1",
        "bundle": str(bundle.bundle_dir),
        "carbon_price_pinned": base.carbon_price,
        "evaluate_speed_override_changes_ev_drive_kwh": abs(ev_default - ev_slow) > 1e-9,
        "ev_drive_kwh_default_speed": ev_default,
        "ev_drive_kwh_slow_speed": ev_slow,
        "evaluate_public_price_override_changes_cost": abs(float(eval_default["cost_elec"]) - float(eval_cheap["cost_elec"])) > 1e-9,
        "cost_elec_default_public": float(eval_default["cost_elec"]),
        "cost_elec_cheap_public": float(eval_cheap["cost_elec"]),
        "repair_route_charging_big_battery_action_count": len(one_ev_big.charging_actions),
        "check_solution_big_battery_violation_count": len(big_violations),
        "check_solution_tiny_battery_violation_count": len(tiny_violations),
        "check_solution_battery_override_changes_feasibility": len(big_violations) != len(tiny_violations),
        "solver_objective_probe": solver_probe,
        "cv_seed_route_count": len(cv_seed.routes),
        "diagnostic_policy": (
            "Main runs use explicit override warm starts plus independent "
            "evaluate/check with the same override prices. Existing LNS/winner "
            "runners are not used for override scans because they hard-code "
            "DEFAULT_PRICES at multiple call sites."
        ),
    }


def _solver_objective_probe(bundle: SearchBundle, base: PriceParameters, cheap_public: PriceParameters) -> dict[str, Any]:
    slow = replace(base, v_speed_ms=11.1)
    try:
        warm = _cv_warm(bundle, base)
        base_run = run_alns_wouda(
            bundle.bundle_dir,
            iterations=None,
            seed=1,
            eval_budget=20,
            max_runtime_seconds=5.0,
            policy=SearchPolicy(require_charging_signal=False),
            initial_solution=warm,
            prices=base,
        )
        slow_run = run_alns_wouda(
            bundle.bundle_dir,
            iterations=None,
            seed=1,
            eval_budget=20,
            max_runtime_seconds=5.0,
            policy=SearchPolicy(require_charging_signal=False),
            initial_solution=warm,
            prices=slow,
        )
        base_metrics = evaluate(base_run.best_solution, bundle.instance, bundle.carbon_profile, base)
        slow_metrics = evaluate(slow_run.best_solution, bundle.instance, bundle.carbon_profile, slow)
        return {
            "status": "OK",
            "base_best_obj": float(base_run.best_obj),
            "slow_best_obj": float(slow_run.best_obj),
            "base_total_cost": float(base_metrics["total_cost"]),
            "slow_total_cost": float(slow_metrics["total_cost"]),
            "objective_changed": abs(float(base_run.best_obj) - float(slow_run.best_obj)) > 1e-9,
            "independent_total_changed": abs(float(base_metrics["total_cost"]) - float(slow_metrics["total_cost"])) > 1e-9,
            "note": "Uses v_speed_ms override; public charging price is audited separately at evaluate().",
        }
    except Exception as exc:
        return {"status": "HALT_SOLVER_PROBE_ERROR", "error": repr(exc)}


def run_phase1(repo_root: Path, instances: list[str], eval_budget: int, max_runtime_seconds: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prices = replace(DEFAULT_PRICES, carbon_price=0.05034)
    for instance_ref in instances:
        bundle = _load_bundle(repo_root, instance_ref)
        for variant in VARIANTS:
            for seed in PHASE1_SEEDS:
                rows.append(run_variant(bundle, instance_ref, "phase1", "baseline", "", "", seed, variant, prices, eval_budget, max_runtime_seconds))
    return rows


def run_phase2(
    repo_root: Path,
    instances: list[str],
    eval_budget: int,
    max_runtime_seconds: float,
    phase1_rows: list[dict[str, Any]],
    mode: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    base = replace(DEFAULT_PRICES, carbon_price=0.05034)
    scan_specs = [
        ("battery_kwh", "B_battery_kwh", value, replace(base, B_battery_kwh=value))
        for value in (80.0, 160.0, 320.0, 480.0)
    ]
    scan_specs.extend(
        ("speed_ms", "v_speed_ms", value, replace(base, v_speed_ms=value))
        for value in (25.0, 16.7, 11.1)
    )
    scan_specs.extend(
        (
            "public_station_price",
            "station_electricity_price",
            value,
            replace(base, electricity_price=value, station_electricity_price=value),
        )
        for value in (0.82, 0.40, 0.1853)
    )
    scan_specs.extend(
        ("occupancy_fee", "occupancy_fee", value, replace(base, occupancy_fee=value))
        for value in (0.50, 0.10, 0.0)
    )

    if mode == "fixed_replay":
        return run_phase2_fixed_replay(repo_root, phase1_rows, scan_specs)

    for instance_ref in instances:
        bundle = _load_bundle(repo_root, instance_ref)
        for scan_name, field_name, value, prices in scan_specs:
            for variant in VARIANTS:
                for seed in PHASE2_SCAN_SEEDS:
                    rows.append(
                        run_variant(
                            bundle,
                            instance_ref,
                            "phase2",
                            scan_name,
                            field_name,
                            value,
                            seed,
                            variant,
                            prices,
                            eval_budget,
                            max_runtime_seconds,
                        )
                    )

    near_flip_keys = _near_flip_keys(rows)
    for instance_ref, scan_name, field_name, value in near_flip_keys:
        bundle = _load_bundle(repo_root, instance_ref)
        prices = _prices_for_scan(base, scan_name, float(value))
        for variant in VARIANTS:
            for seed in PHASE2_REFINE_EXTRA_SEEDS:
                rows.append(
                    run_variant(
                        bundle,
                        instance_ref,
                        "phase2_refine",
                        scan_name,
                        field_name,
                        value,
                        seed,
                        variant,
                        prices,
                        eval_budget,
                        max_runtime_seconds,
                    )
                )
    _ = phase1_rows
    return rows


def run_phase2_fixed_replay(
    repo_root: Path,
    phase1_rows: list[dict[str, Any]],
    scan_specs: list[tuple[str, str, float, PriceParameters]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for instance_ref, instance_rows in _group_by(phase1_rows, "instance").items():
        bundle = _load_bundle(repo_root, str(instance_ref))
        best = _best_by_variant(instance_rows)
        for scan_name, field_name, value, prices in scan_specs:
            for variant in VARIANTS:
                reference = best.get(variant)
                rows.append(_fixed_replay_row(bundle, str(instance_ref), scan_name, field_name, value, variant, prices, reference))
    return rows


def _fixed_replay_row(
    bundle: SearchBundle,
    instance_ref: str,
    scan_name: str,
    field_name: str,
    value: Any,
    variant: str,
    prices: PriceParameters,
    reference: dict[str, Any] | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "phase": "phase2_fixed_replay",
        "instance": instance_ref,
        "scan_name": scan_name,
        "field": field_name,
        "value": value,
        "seed": 0,
        "variant": variant,
        "carbon_price": float(prices.carbon_price),
        "eval_budget": 0,
        "max_runtime_seconds": 0.0,
    }
    if reference is None or reference.get("_solution_obj") is None:
        row.update({"status": "HALT_NO_REFERENCE_SOLUTION", "total_cost": math.inf})
        return row
    started = time.perf_counter()
    try:
        solution = _replay_solution_for_prices(reference["_solution_obj"], bundle, prices)
        metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices)
        violations = check_solution(solution, bundle.instance, prices)
        row.update(_metric_row(metrics))
        row.update(charging_behavior(solution, bundle, prices))
        row.update(
            {
                "status": "OK" if not violations else "HALT_INFEASIBLE_FIXED_REPLAY",
                "violation_count": len(violations),
                "solver_reported_feasible": "",
                "actual_evals": 0,
                "best_penalized_obj": "",
                "elapsed_seconds": time.perf_counter() - started,
                "route_count": len(solution.routes),
                "cv_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv"),
                "ev_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
                "warm_cv_route_count": reference.get("warm_cv_route_count", ""),
                "warm_ev_route_count": reference.get("warm_ev_route_count", ""),
                "reference_seed": reference.get("seed", ""),
                "reference_total_cost": reference.get("total_cost", ""),
            }
        )
    except Exception as exc:
        row.update({"status": "HALT_FIXED_REPLAY_ERROR", "error": repr(exc), "total_cost": math.inf, "elapsed_seconds": time.perf_counter() - started})
    return row


def run_variant(
    bundle: SearchBundle,
    instance_ref: str,
    phase: str,
    scan_name: str,
    field_name: str,
    value: Any,
    seed: int,
    variant: str,
    prices: PriceParameters,
    eval_budget: int,
    max_runtime_seconds: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    row: dict[str, Any] = {
        "phase": phase,
        "instance": instance_ref,
        "scan_name": scan_name,
        "field": field_name,
        "value": value,
        "seed": int(seed),
        "variant": variant,
        "carbon_price": float(prices.carbon_price),
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
    }
    try:
        warm = _warm_for_variant(bundle, prices, variant)
        policy = _policy_for_variant(variant)
        result = run_alns_wouda(
            bundle.bundle_dir,
            iterations=None,
            seed=int(seed),
            eval_budget=int(eval_budget),
            max_runtime_seconds=float(max_runtime_seconds),
            policy=policy,
            initial_solution=warm,
            prices=prices,
        )
        solution = result.best_solution
        metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices)
        violations = check_solution(solution, bundle.instance, prices)
        behavior = charging_behavior(solution, bundle, prices)
        row.update(_metric_row(metrics))
        row.update(behavior)
        row.update(
            {
                "status": "OK" if not violations else "HALT_INFEASIBLE",
                "violation_count": len(violations),
                "solver_reported_feasible": bool(result.feasible),
                "actual_evals": int(result.evaluations),
                "best_penalized_obj": float(result.best_obj),
                "elapsed_seconds": time.perf_counter() - started,
                "route_count": len(solution.routes),
                "cv_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv"),
                "ev_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
                "warm_cv_route_count": sum(1 for route in warm.routes if route.vehicle_type.lower() == "cv"),
                "warm_ev_route_count": sum(1 for route in warm.routes if route.vehicle_type.lower() == "ev"),
                "_solution_obj": solution,
            }
        )
        if variant == "ev_only" and row["cv_route_count"] != 0:
            row["status"] = "HALT_EV_ONLY_RETURNED_CV"
    except Exception as exc:
        row.update(
            {
                "status": "HALT_RUN_ERROR",
                "error": repr(exc),
                "elapsed_seconds": time.perf_counter() - started,
                "total_cost": math.inf,
                "cv_route_count": math.nan,
                "ev_route_count": math.nan,
                "violation_count": math.nan,
            }
        )
    return row


def charging_behavior(solution: Solution, bundle: SearchBundle, prices: PriceParameters) -> dict[str, Any]:
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    depot_kwh = 0.0
    public_kwh = 0.0
    depot_cost = 0.0
    public_cost = 0.0
    occupancy_cost = 0.0
    public_action_count = 0
    depot_action_count = 0
    actions_by_vehicle: dict[str, list[Any]] = {}
    for action in solution.charging_actions:
        actions_by_vehicle.setdefault(action.vehicle_id, []).append(action)
        node = node_lookup.get(action.station_id)
        if node and node.node_type.lower() == "d":
            depot_action_count += 1
            depot_kwh += float(action.energy_kwh)
            depot_cost += float(action.energy_kwh) * float(prices.depot_electricity_price)
        else:
            public_action_count += 1
            public_kwh += float(action.energy_kwh)
            public_cost += float(action.energy_kwh) * float(prices.station_electricity_price)
            occupancy_cost += float(action.occupancy_minutes) * float(prices.occupancy_fee)

    ev_drive_gt_battery = 0
    ev_public_routes = 0
    ev_detour_m = 0.0
    max_ev_route_kwh = 0.0
    for route in solution.routes:
        if route.vehicle_type.lower() != "ev":
            continue
        summary = route_ev_energy_summary(route, bundle.instance, prices)
        max_ev_route_kwh = max(max_ev_route_kwh, float(summary.ev_kwh))
        if float(summary.ev_kwh) > float(prices.B_battery_kwh) + 1e-9:
            ev_drive_gt_battery += 1
        route_actions = actions_by_vehicle.get(route.vehicle_id, [])
        if any((node_lookup.get(action.station_id) and node_lookup[action.station_id].node_type.lower() == "f") for action in route_actions):
            ev_public_routes += 1
        clean = [node_id for node_id in route.node_sequence if not (node_lookup.get(node_id) and node_lookup[node_id].node_type.lower() == "f")]
        if len(clean) >= 2:
            clean_distance = sum(bundle.instance.distance(a, b) for a, b in zip(clean, clean[1:]))
            actual_distance = sum(bundle.instance.distance(a, b) for a, b in zip(route.node_sequence, route.node_sequence[1:]))
            ev_detour_m += max(0.0, actual_distance - clean_distance)

    return {
        "charge_action_count": len(solution.charging_actions),
        "depot_charge_action_count": depot_action_count,
        "public_charge_action_count": public_action_count,
        "depot_charge_kwh": depot_kwh,
        "public_charge_kwh": public_kwh,
        "depot_charge_cost": depot_cost,
        "public_charge_cost": public_cost,
        "public_occupancy_cost": occupancy_cost,
        "ev_routes_drive_kwh_gt_battery": ev_drive_gt_battery,
        "ev_routes_with_public_charge": ev_public_routes,
        "ev_public_charge_detour_m": ev_detour_m,
        "max_ev_route_drive_kwh": max_ev_route_kwh,
    }


def summarize_conclusion(phase1_rows: list[dict[str, Any]], phase2_rows: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_status = _baseline_status(phase1_rows)
    if baseline_status["mixed_beats_cv_instances"]:
        count = len(baseline_status["mixed_beats_cv_instances"])
        total = len(baseline_status["checked_instances"])
        summary = (
            f"Baseline selected small cases did not reproduce all-CV optimality: "
            f"mixed best-found beat cv_only on {count}/{total} checked instances."
        )
        return {
            "verdict": "BASELINE_MIXED_ALREADY_BEATS_CV_ON_SELECTED_CASES",
            "summary": summary,
            "flips": [],
            "near_flips": [],
            "baseline_status": baseline_status,
            "phase1_mechanism": _phase1_mechanism_summary(phase1_rows),
        }

    flips = []
    near = []
    for key, rows in _group_phase2(phase2_rows).items():
        best = _best_by_variant(rows)
        cv = best.get("cv_only")
        mixed = best.get("mixed")
        ev = best.get("ev_only")
        if cv is None:
            continue
        cv_cost = float(cv["total_cost"])
        contenders = [row for row in (mixed, ev) if row is not None and math.isfinite(float(row["total_cost"]))]
        if not contenders:
            continue
        challenger = min(contenders, key=lambda row: float(row["total_cost"]))
        gap_pct = 100.0 * (float(challenger["total_cost"]) - cv_cost) / cv_cost if cv_cost else math.inf
        record = {
            "instance": key[0],
            "scan_name": key[1],
            "field": key[2],
            "value": key[3],
            "best_non_cv_variant": challenger["variant"],
            "gap_pct_non_cv_minus_cv": gap_pct,
            "cv_cost": cv_cost,
            "non_cv_cost": float(challenger["total_cost"]),
        }
        if gap_pct <= 0.0:
            flips.append(record)
        elif gap_pct <= 1.0:
            near.append(record)

    phase1_mechanism = _phase1_mechanism_summary(phase1_rows)
    if flips:
        first = sorted(flips, key=lambda row: (row["gap_pct_non_cv_minus_cv"], row["scan_name"], float(row["value"])))[0]
        summary = (
            f"At fixed carbon_price=0.05034, {first['scan_name']}={first['value']} "
            f"first produced {first['best_non_cv_variant']} <= cv_only on {first['instance']} "
            f"(gap {first['gap_pct_non_cv_minus_cv']:.3f}%)."
        )
        verdict = "SINGLE_PARAMETER_FLIP_FOUND"
    elif near:
        first = sorted(near, key=lambda row: (row["gap_pct_non_cv_minus_cv"], row["scan_name"], float(row["value"])))[0]
        summary = (
            f"No single parameter flipped the best found solution, but {first['scan_name']}={first['value']} "
            f"came within {first['gap_pct_non_cv_minus_cv']:.3f}% on {first['instance']}."
        )
        verdict = "SINGLE_PARAMETER_NEAR_FLIP_ONLY"
    else:
        summary = "No scanned single non-carbon parameter made mixed/EV <= cv_only in the best found small-budget runs."
        verdict = "NO_SINGLE_PARAMETER_FLIP"
    return {"verdict": verdict, "summary": summary, "flips": flips, "near_flips": near, "baseline_status": baseline_status, "phase1_mechanism": phase1_mechanism}


def _baseline_status(rows: list[dict[str, Any]]) -> dict[str, Any]:
    checked = []
    mixed_beats = []
    details = []
    for instance, instance_rows in _group_by(rows, "instance").items():
        best = _best_by_variant(instance_rows)
        cv = best.get("cv_only")
        mixed = best.get("mixed")
        if cv is None or mixed is None:
            continue
        checked.append(str(instance))
        cv_cost = float(cv["total_cost"])
        mixed_cost = float(mixed["total_cost"])
        gap_pct = 100.0 * (mixed_cost - cv_cost) / cv_cost if cv_cost else math.inf
        details.append({"instance": str(instance), "cv_cost": cv_cost, "mixed_cost": mixed_cost, "mixed_minus_cv_gap_pct": gap_pct})
        if mixed_cost <= cv_cost + 1e-9:
            mixed_beats.append(str(instance))
    return {"checked_instances": checked, "mixed_beats_cv_instances": mixed_beats, "details": details}


def _phase1_mechanism_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for instance, instance_rows in _group_by(rows, "instance").items():
        best = _best_by_variant(instance_rows)
        if "cv_only" not in best:
            continue
        cv = best["cv_only"]
        detail = {}
        for variant in ("mixed", "ev_only"):
            row = best.get(variant)
            if row is None:
                continue
            detail[variant] = {
                "total_gap_vs_cv": _gap(row, cv, "total_cost"),
                "fixed_gap_vs_cv": _gap(row, cv, "cost_fix"),
                "fuel_gap_vs_cv": _gap(row, cv, "cost_fuel"),
                "electric_gap_vs_cv": _gap(row, cv, "cost_elec"),
                "occupancy_gap_vs_cv": _gap(row, cv, "cost_occ"),
                "carbon_gap_vs_cv": _gap(row, cv, "cost_carbon"),
                "public_charge_kwh": float(row.get("public_charge_kwh", 0.0)),
                "ev_routes_with_public_charge": row.get("ev_routes_with_public_charge", 0),
            }
        out[str(instance)] = detail
    return out


def render_report(
    metadata: dict[str, Any],
    phase0: dict[str, Any],
    phase1_rows: list[dict[str, Any]],
    phase2_rows: list[dict[str, Any]],
    conclusion: dict[str, Any],
) -> str:
    lines = [
        "# 09e Instance Parameter Diagnostic",
        "",
        f"Conclusion: `{conclusion['verdict']}`.",
        "",
        conclusion["summary"],
        "",
        "## Environment",
        "",
        f"- repo_head: `{metadata['repo_head']}`",
        f"- branch: `{metadata['branch']}`",
        f"- python: `{metadata['python']}`",
        f"- numpy: `{metadata['numpy']}`",
        f"- PYTHONHASHSEED: `{metadata.get('PYTHONHASHSEED', '')}`",
        f"- eval_budget: `{metadata['eval_budget']}`",
        f"- max_runtime_seconds: `{metadata['max_runtime_seconds']}`",
        f"- phase2_mode: `{metadata['phase2_mode']}`",
        f"- elapsed_seconds: `{metadata['elapsed_seconds']:.3f}`",
        "",
        "## Phase 0 Override Audit",
        "",
        _phase0_table(phase0),
        "",
        "Audit note: main scans avoid existing LNS/winner runner override paths and use explicit warm starts plus independent `evaluate/check(..., prices)` verification.",
    ]

    if phase1_rows:
        lines.extend(
            [
                "",
                "## Phase 1 Mechanism",
                "",
                _phase1_table(phase1_rows),
                "",
                "Best-row charging behavior:",
                "",
                _phase1_charging_table(phase1_rows),
            ]
        )
    if phase2_rows:
        lines.extend(
            [
                "",
                "## Phase 2 Single-Parameter Scan",
                "",
                _phase2_table(phase2_rows),
                "",
                _phase2_mode_note(metadata),
            ]
        )

    lines.extend(
        [
            "",
            "## One-Line Root Cause",
            "",
            _root_cause_sentence(conclusion),
            "",
            "## Artifacts",
            "",
            "- `baselines/e2_alns/instance_param_diagnostic.py`",
            "- `baselines/e2_alns/instance_param_diagnostic_data/phase0_audit.json`",
            "- `baselines/e2_alns/instance_param_diagnostic_data/phase1_cost_breakdown.csv`",
            "- `baselines/e2_alns/instance_param_diagnostic_data/phase2_scan.csv`",
            "",
            "## Command",
            "",
            "```bash",
            metadata["command"],
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _phase0_table(phase0: dict[str, Any]) -> str:
    rows = [
        ("carbon price pinned", phase0["carbon_price_pinned"]),
        ("evaluate speed override changes EV kWh", phase0["evaluate_speed_override_changes_ev_drive_kwh"]),
        ("evaluate public price override changes cost", phase0["evaluate_public_price_override_changes_cost"]),
        ("check battery override changes feasibility", phase0["check_solution_battery_override_changes_feasibility"]),
        ("big battery violation count", phase0["check_solution_big_battery_violation_count"]),
        ("tiny battery violation count", phase0["check_solution_tiny_battery_violation_count"]),
        ("solver objective probe", phase0["solver_objective_probe"].get("status")),
        ("solver objective changed", phase0["solver_objective_probe"].get("objective_changed")),
    ]
    return _markdown_table(["check", "value"], rows)


def _phase1_table(rows: list[dict[str, Any]]) -> str:
    table_rows = []
    for instance, instance_rows in _group_by(rows, "instance").items():
        for variant, best in sorted(_best_by_variant(instance_rows).items()):
            table_rows.append(
                (
                    instance,
                    variant,
                    _fmt(best.get("total_cost")),
                    best.get("cv_route_count"),
                    best.get("ev_route_count"),
                    _fmt(best.get("cost_fix")),
                    _fmt(best.get("cost_fuel")),
                    _fmt(best.get("cost_elec")),
                    _fmt(best.get("cost_occ")),
                    _fmt(best.get("cost_carbon")),
                    best.get("status"),
                )
            )
    return _markdown_table(
        ["instance", "variant", "total", "CV", "EV", "fix", "fuel", "elec", "occ", "carbon", "status"],
        table_rows,
    )


def _phase1_charging_table(rows: list[dict[str, Any]]) -> str:
    table_rows = []
    for instance, instance_rows in _group_by(rows, "instance").items():
        for variant, best in sorted(_best_by_variant(instance_rows).items()):
            table_rows.append(
                (
                    instance,
                    variant,
                    best.get("charge_action_count"),
                    _fmt(best.get("depot_charge_kwh")),
                    _fmt(best.get("public_charge_kwh")),
                    _fmt(best.get("depot_charge_cost")),
                    _fmt(best.get("public_charge_cost")),
                    _fmt(best.get("public_occupancy_cost")),
                    best.get("ev_routes_drive_kwh_gt_battery"),
                    best.get("ev_routes_with_public_charge"),
                    _fmt(best.get("ev_public_charge_detour_m")),
                )
            )
    return _markdown_table(
        ["instance", "variant", "actions", "depot kWh", "public kWh", "depot GBP", "public GBP", "occ GBP", "EV>B", "EV public", "detour m"],
        table_rows,
    )


def _phase2_table(rows: list[dict[str, Any]]) -> str:
    table_rows = []
    for key, group_rows in sorted(_group_phase2(rows).items()):
        best = _best_by_variant(group_rows)
        cv = best.get("cv_only")
        mixed = best.get("mixed")
        ev = best.get("ev_only")
        cv_cost = float(cv["total_cost"]) if cv else math.nan
        mixed_cost = float(mixed["total_cost"]) if mixed else math.nan
        ev_cost = float(ev["total_cost"]) if ev else math.nan
        best_non_cv = min([mixed_cost, ev_cost])
        gap = 100.0 * (best_non_cv - cv_cost) / cv_cost if math.isfinite(cv_cost) and cv_cost else math.nan
        table_rows.append((key[0], key[1], key[3], _fmt(cv_cost), _fmt(mixed_cost), _fmt(ev_cost), _fmt(gap), gap <= 0.0))
    return _markdown_table(["instance", "parameter", "value", "cv_only", "mixed", "ev_only", "best non-CV gap %", "flip"], table_rows)


def _root_cause_sentence(conclusion: dict[str, Any]) -> str:
    if conclusion["verdict"] == "BASELINE_MIXED_ALREADY_BEATS_CV_ON_SELECTED_CASES":
        return (
            "固定真实碳价下, 本次 09e 选定小算例没有复现'全油车最优': mixed 已经低于本脚本的 cv_only。"
            "因此不能把电池/电价/占用费判为全油退化真凶; 下一步应转到 09d 中 LNS 全油车占优的更大实例或引入 LNS 级全油参考解再诊断。"
        )
    if conclusion["verdict"] == "SINGLE_PARAMETER_FLIP_FOUND":
        first = sorted(conclusion["flips"], key=lambda row: (row["gap_pct_non_cv_minus_cv"], row["scan_name"], float(row["value"])))[0]
        return (
            f"固定真实碳价下, `{first['scan_name']}={first['value']}` 是当前扫描中能让 "
            f"`{first['best_non_cv_variant']}` 反超全油车的非碳触发点; 先按该参数方向改算例口径, 再回测 ALNS vs GLNS。"
        )
    if conclusion["verdict"] == "SINGLE_PARAMETER_NEAR_FLIP_ONLY":
        first = sorted(conclusion["near_flips"], key=lambda row: (row["gap_pct_non_cv_minus_cv"], row["scan_name"], float(row["value"])))[0]
        return (
            f"固定真实碳价下, 单参数未翻盘; 最近的是 `{first['scan_name']}={first['value']}` "
            f"仍差 {first['gap_pct_non_cv_minus_cv']:.3f}%, 说明很可能需要组合改电池/速度/公共充电经济性。"
        )
    if conclusion["verdict"] == "NO_SINGLE_PARAMETER_FLIP":
        return "固定真实碳价下, 本次单参数扫描没有让混合/全电 best-found 不高于全油车; 不能硬判单一真凶, 需要组合扫描或更强重优化。"
    return "Phase 0 only; no root-cause conclusion yet."


def _phase2_mode_note(metadata: dict[str, Any]) -> str:
    if metadata.get("phase2_mode") == "fixed_replay":
        return (
            "Phase 2 uses fixed customer-order and vehicle-type references from Phase 1, "
            "then replays EV charging under each in-memory price override. It isolates "
            "parameter economics without claiming full re-optimization."
        )
    return "Phase 2 uses low-budget re-solving; refinement rows are added only where seed-1 mixed/EV is no worse than 1% above cv_only."


def _metadata(repo_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": "setp-09e-diagnostic-metadata.v1",
        "repo_root": str(repo_root),
        "repo_head": _git(repo_root, "rev-parse", "HEAD"),
        "branch": _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD"),
        "python": sys.executable,
        "python_version": sys.version.split()[0],
        "numpy": np.__version__,
        "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED", ""),
        "eval_budget": int(args.eval_budget),
        "max_runtime_seconds": float(args.max_runtime_seconds),
        "phase2_mode": str(args.phase2_mode),
        "instances": list(args.instances),
        "command": " ".join([sys.executable, *sys.argv]),
    }


def _warm_for_variant(bundle: SearchBundle, prices: PriceParameters, variant: str) -> Solution:
    if variant == "cv_only":
        return _cv_warm(bundle, prices)
    if variant == "ev_only":
        return _all_ev_warm(bundle, prices)
    if variant == "mixed":
        return _mixed_warm(bundle, prices)
    raise ValueError(f"unknown variant: {variant}")


def _policy_for_variant(variant: str) -> SearchPolicy:
    if variant == "cv_only":
        return SearchPolicy(require_charging_signal=False, max_ev=0)
    if variant == "ev_only":
        return SearchPolicy(require_charging_signal=False, max_cv=0)
    if variant == "mixed":
        return SearchPolicy(require_charging_signal=False)
    raise ValueError(f"unknown variant: {variant}")


def _cv_warm(bundle: SearchBundle, prices: PriceParameters) -> Solution:
    return build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        prices,
        fleet_limits=FleetLimits(cv=UNBOUNDED_FLEET, ev=0, source="09e cv_only"),
        introduce_ev=False,
        require_charging_signal=False,
    )


def _mixed_warm(bundle: SearchBundle, prices: PriceParameters) -> Solution:
    cv = _cv_warm(bundle, prices)
    try:
        one_ev = _one_ev_warm(bundle, prices)
        if not check_solution(one_ev, bundle.instance, prices):
            cv_cost = float(evaluate(cv, bundle.instance, bundle.carbon_profile, prices)["total_cost"])
            ev_cost = float(evaluate(one_ev, bundle.instance, bundle.carbon_profile, prices)["total_cost"])
            return one_ev if ev_cost < cv_cost else cv
    except Exception:
        return cv
    return cv


def _one_ev_warm(bundle: SearchBundle, prices: PriceParameters) -> Solution:
    cv = _cv_warm(bundle, prices)
    candidates: list[tuple[float, Solution]] = []
    for idx, route in enumerate(cv.routes, start=1):
        ev_route = Route(f"EV_WARM_{idx}", "ev", route.home_depot_id, list(route.node_sequence))
        try:
            repaired, route_actions = repair_route_charging(ev_route, bundle.instance, bundle.carbon_profile, prices)
        except ValueError:
            continue
        routes = [repaired if pos == idx - 1 else old_route for pos, old_route in enumerate(cv.routes)]
        candidate = Solution(routes=routes, charging_actions=list(route_actions), cross_site_services=cv.cross_site_services)
        if check_solution(candidate, bundle.instance, prices):
            continue
        cost = float(evaluate(candidate, bundle.instance, bundle.carbon_profile, prices)["total_cost"])
        candidates.append((cost, candidate))
    if not candidates:
        raise ValueError("Unable to build one-EV warm start under supplied prices")
    return min(candidates, key=lambda item: item[0])[1]


def _all_ev_warm(bundle: SearchBundle, prices: PriceParameters) -> Solution:
    cv = _cv_warm(bundle, prices)
    converted = _convert_solution_to_ev(cv, bundle, prices)
    if converted is not None and not check_solution(converted, bundle.instance, prices):
        return converted
    single = _single_customer_ev_solution(bundle, prices)
    violations = check_solution(single, bundle.instance, prices)
    if violations:
        detail = "; ".join(f"{v.type}:{v.vehicle_id}:{v.location}:{v.detail}" for v in violations[:8])
        raise ValueError(f"Unable to build all-EV warm start: {detail}")
    return single


def _convert_solution_to_ev(solution: Solution, bundle: SearchBundle, prices: PriceParameters) -> Solution | None:
    routes: list[Route] = []
    actions = []
    for idx, route in enumerate(solution.routes, start=1):
        ev_route = Route(f"EV{idx}", "ev", route.home_depot_id, list(route.node_sequence))
        try:
            repaired, route_actions = repair_route_charging(ev_route, bundle.instance, bundle.carbon_profile, prices)
        except ValueError:
            return None
        routes.append(repaired)
        actions.extend(route_actions)
    return Solution(routes=routes, charging_actions=actions, cross_site_services=solution.cross_site_services)


def _single_customer_ev_solution(bundle: SearchBundle, prices: PriceParameters) -> Solution:
    routes: list[Route] = []
    actions = []
    for idx, customer_id in enumerate(_customers(bundle), start=1):
        depot_id = _nearest_depot(bundle, customer_id)
        route = Route(f"EV{idx}", "ev", depot_id, [depot_id, customer_id, depot_id])
        repaired, route_actions = repair_route_charging(route, bundle.instance, bundle.carbon_profile, prices)
        routes.append(repaired)
        actions.extend(route_actions)
    return Solution(routes=routes, charging_actions=actions)


def _replay_solution_for_prices(solution: Solution, bundle: SearchBundle, prices: PriceParameters) -> Solution:
    routes: list[Route] = []
    actions = []
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    for route in solution.routes:
        if route.vehicle_type.lower() != "ev":
            routes.append(route)
            continue
        clean_sequence = [
            node_id
            for node_id in route.node_sequence
            if not (node_lookup.get(node_id) and node_lookup[node_id].node_type.lower() == "f")
        ]
        clean_route = Route(route.vehicle_id, "ev", route.home_depot_id, clean_sequence)
        repaired, route_actions = repair_route_charging(clean_route, bundle.instance, bundle.carbon_profile, prices)
        routes.append(repaired)
        actions.extend(route_actions)
    return Solution(routes=routes, charging_actions=actions, cross_site_services=solution.cross_site_services)


def _load_bundle(repo_root: Path, instance_ref: str) -> SearchBundle:
    return load_search_bundle(repo_root / "models/data_bundle/generated_instances/e2_benchmark" / instance_ref)


def _public_charge_probe(bundle: SearchBundle) -> Solution:
    depot_id = next(node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "d")
    station_id = next(node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "f")
    return Solution(
        routes=[Route("EV_PUBLIC_PROBE", "ev", depot_id, [depot_id, station_id, depot_id])],
        charging_actions=[ChargingAction("EV_PUBLIC_PROBE", station_id, 10.0, 1.0, 0.0)],
    )


def _customers(bundle: SearchBundle) -> list[str]:
    return sorted([node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c"], key=_natural_key)


def _first_customer(bundle: SearchBundle) -> str:
    customers = _customers(bundle)
    if not customers:
        raise ValueError("bundle has no customers")
    return customers[0]


def _nearest_depot(bundle: SearchBundle, customer_id: str) -> str:
    depots = [node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "d"]
    return min(depots, key=lambda depot_id: (bundle.instance.distance(depot_id, customer_id), depot_id))


def _route_ev_kwh(route: Route, bundle: SearchBundle, prices: PriceParameters) -> float:
    return float(route_ev_energy_summary(route, bundle.instance, prices).ev_kwh)


def _metric_row(metrics: dict[str, Any]) -> dict[str, float]:
    keys = (
        "total_cost",
        "cost_fix",
        "cost_km",
        "cost_fuel",
        "cost_elec",
        "cost_occ",
        "cost_transship",
        "cost_carbon",
        "E_total",
        "E_cv_direct",
        "E_ev_indirect",
        "distance_total",
        "distance_cv",
        "distance_ev",
        "fuel_liters",
        "electricity_kwh",
        "depot_charging_kwh",
        "station_charging_kwh",
        "ev_drive_kwh",
    )
    return {key: float(metrics.get(key, math.nan)) for key in keys}


def _near_flip_keys(rows: list[dict[str, Any]]) -> list[tuple[str, str, str, float]]:
    keys: set[tuple[str, str, str, float]] = set()
    for key, group_rows in _group_phase2(rows).items():
        best = _best_by_variant(group_rows)
        cv = best.get("cv_only")
        mixed = best.get("mixed")
        ev = best.get("ev_only")
        if cv is None:
            continue
        cv_cost = float(cv.get("total_cost", math.inf))
        if not math.isfinite(cv_cost) or cv_cost <= 0:
            continue
        for row in (mixed, ev):
            if row is None:
                continue
            cost = float(row.get("total_cost", math.inf))
            if math.isfinite(cost) and 100.0 * (cost - cv_cost) / cv_cost <= 1.0:
                keys.add((str(key[0]), str(key[1]), str(key[2]), float(key[3])))
    return sorted(keys)


def _prices_for_scan(base: PriceParameters, scan_name: str, value: float) -> PriceParameters:
    if scan_name == "battery_kwh":
        return replace(base, B_battery_kwh=value)
    if scan_name == "speed_ms":
        return replace(base, v_speed_ms=value)
    if scan_name == "public_station_price":
        return replace(base, electricity_price=value, station_electricity_price=value)
    if scan_name == "occupancy_fee":
        return replace(base, occupancy_fee=value)
    raise ValueError(f"unknown scan: {scan_name}")


def _group_phase2(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str, float], list[dict[str, Any]]]:
    out: dict[tuple[str, str, str, float], list[dict[str, Any]]] = {}
    for row in rows:
        if not str(row.get("phase", "")).startswith("phase2"):
            continue
        key = (str(row["instance"]), str(row["scan_name"]), str(row["field"]), float(row["value"]))
        out.setdefault(key, []).append(row)
    return out


def _best_by_variant(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("status") != "OK":
            continue
        variant = str(row["variant"])
        cost = float(row.get("total_cost", math.inf))
        if variant not in out or cost < float(out[variant].get("total_cost", math.inf)):
            out[variant] = row
    return out


def _group_by(rows: list[dict[str, Any]], key: str) -> dict[Any, list[dict[str, Any]]]:
    out: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(row.get(key), []).append(row)
    return out


def _gap(row: dict[str, Any], base: dict[str, Any], key: str) -> float:
    return float(row.get(key, 0.0)) - float(base.get(key, 0.0))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key.startswith("_"):
                continue
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: value for key, value in row.items() if key in fields})


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _markdown_table(headers: list[str], rows: list[tuple[Any, ...]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(out)


def _fmt(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "nan"
    return f"{number:.6f}"


def _natural_key(value: str) -> tuple[str, int]:
    prefix = "".join(ch for ch in value if not ch.isdigit())
    digits = "".join(ch for ch in value if ch.isdigit())
    return prefix, int(digits or "0")


def _git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=repo_root, text=True, capture_output=True, check=False)
    return completed.stdout.strip() if completed.returncode == 0 else ""


if __name__ == "__main__":
    raise SystemExit(main())
