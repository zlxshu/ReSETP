"""09f large-scale all-CV diagnostic for E2 threeshift checkpoints.

This is a diagnostic runner only. It reads the 09d checkpoint artifacts,
re-evaluates every referenced solution with the shared evaluator, and performs
in-memory non-carbon parameter replays with ``dataclasses.replace``. It does
not modify model parameters, generated bundles, cost/check/evaluation
semantics, or promoted algorithms.
"""

from __future__ import annotations

import argparse
import csv
from contextlib import contextmanager
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
from typing import Any

import numpy as np

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES, PriceParameters
from setp_solver.solution import Route, Solution
from setp_solver.search.alns_wouda import SearchPolicy, run_alns_wouda
from setp_solver.search.bundle import SearchBundle, load_search_bundle
from setp_solver.search.charging import repair_route_charging
from setp_solver.search.fleet import route_ev_energy_summary
from setp_solver.search.metaheuristic_baselines import solution_from_dict
from setp_solver.search.winner_operators import e2_alns_throughput_flags


DEFAULT_INSTANCES = (
    "e2-threeshift-100c-01",
    "e2-threeshift-150c-01",
    "e2-threeshift-200c-01",
)
SEEDS = (1, 2, 3, 4, 5)
CARBON_PRICE = 0.05034
COST_TOLERANCE = 1e-6
ROLE_TO_ALGORITHM = {
    "allcv": "LNS",
    "mixed": "alns_e2_throughput",
}
ROLE_LABEL = {
    "allcv": "LNS/all-CV",
    "mixed": "ALNS/mixed",
}
RUNTIME_CAP_SECONDS = {
    "e2-threeshift-100c-01": 300.0,
    "e2-threeshift-150c-01": 900.0,
    "e2-threeshift-200c-01": 900.0,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="Repository root.")
    parser.add_argument("--output-dir", default="baselines/e2_alns/largescale_allcv_diagnostic_data")
    parser.add_argument("--report-path", default="baselines/e2_alns/largescale_allcv_diagnostic.md")
    parser.add_argument("--checkpoint-dir", default="baselines/e2_alns/checkpoints")
    parser.add_argument("--throughput-csv", default="baselines/e2_alns/throughput_raw_runs.csv")
    parser.add_argument("--phase0-only", action="store_true")
    parser.add_argument("--phase2-mode", choices=("fixed_replay",), default="fixed_replay")
    parser.add_argument("--enable-reopt-refine", action="store_true")
    parser.add_argument("--reopt-eval-budget", type=int, default=16000)
    parser.add_argument("--reopt-collection-note", default="")
    parser.add_argument("--instances", nargs="*", default=list(DEFAULT_INSTANCES))
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    metadata = _metadata(repo_root, args)
    stdout_summary: dict[str, Any] = {
        "schema_version": "setp-09f-stdout-summary.v1",
        "report": args.report_path,
        "output_dir": args.output_dir,
        "phase0_only": bool(args.phase0_only),
    }

    records = load_reference_records(repo_root, args)
    _write_csv(output_dir / "reference_solution_audit.csv", _csv_safe_records(records))
    phase0_rows = phase0_dominance(records)
    _write_csv(output_dir / "phase0_dominance.csv", phase0_rows)

    phase1_rows: list[dict[str, Any]] = []
    phase2_rows: list[dict[str, Any]] = []
    reopt_triggers: list[dict[str, Any]] = []
    reopt_rows: list[dict[str, Any]] = []
    if not args.phase0_only and not _has_audit_halt(records):
        phase1_rows = phase1_cost_breakdown(records)
        _write_csv(output_dir / "phase1_cost_breakdown.csv", phase1_rows)
        phase2_rows = phase2_fixed_replay(records)
        _write_csv(output_dir / "phase2_fixed_replay.csv", phase2_rows)
        reopt_triggers = _reopt_triggers(phase2_rows, _true_allcv_instances(phase0_rows))
        _write_csv(output_dir / "phase2_reopt_triggers.csv", reopt_triggers)
        if bool(args.enable_reopt_refine):
            reopt_rows = phase2_reopt_refine(repo_root, args, records, phase0_rows, phase2_rows)
            _write_csv(output_dir / "phase2_reopt_refine.csv", reopt_rows)
    else:
        _write_csv(output_dir / "phase1_cost_breakdown.csv", [])
        _write_csv(output_dir / "phase2_fixed_replay.csv", [])
        _write_csv(output_dir / "phase2_reopt_triggers.csv", [])
        _write_csv(output_dir / "phase2_reopt_refine.csv", [])

    conclusion = summarize_conclusion(records, phase0_rows, phase1_rows, phase2_rows, reopt_rows)
    metadata["elapsed_seconds"] = time.perf_counter() - started
    metadata["diagnostic_artifact_commit"] = "PENDING_COMMIT"
    stdout_summary.update(
        {
            "conclusion": conclusion["verdict"],
            "classifiers": {row["instance"]: row["classifier"] for row in phase0_rows},
            "reference_rows": len(records),
            "phase2_rows": len(phase2_rows),
            "reopt_trigger_rows": len(reopt_triggers),
            "reopt_rows": len(reopt_rows),
        }
    )
    metadata["stdout_summary"] = stdout_summary
    _write_json(output_dir / "metadata.json", metadata)
    _write_json(output_dir / "conclusion.json", conclusion)

    report = render_report(metadata, stdout_summary, records, phase0_rows, phase1_rows, phase2_rows, reopt_triggers, reopt_rows, conclusion)
    (repo_root / args.report_path).write_text(report, encoding="utf-8")
    print(json.dumps(stdout_summary, ensure_ascii=False, sort_keys=True))
    return 2 if conclusion["verdict"].startswith("HALT_") else 0


def load_reference_records(repo_root: Path, args: argparse.Namespace) -> list[dict[str, Any]]:
    csv_rows = _read_throughput_rows(repo_root / args.throughput_csv)
    records: list[dict[str, Any]] = []
    base_prices = replace(DEFAULT_PRICES, carbon_price=CARBON_PRICE)
    bundles: dict[str, SearchBundle] = {}
    for instance in args.instances:
        bundles[instance] = _load_bundle(repo_root, instance)
        for role, algorithm in ROLE_TO_ALGORITHM.items():
            for seed in SEEDS:
                records.append(
                    load_reference_record(
                        repo_root,
                        repo_root / args.checkpoint_dir,
                        csv_rows,
                        bundles[instance],
                        instance,
                        role,
                        algorithm,
                        seed,
                        base_prices,
                    )
                )
    return records


def load_reference_record(
    repo_root: Path,
    checkpoint_dir: Path,
    csv_rows: dict[tuple[str, str, int], dict[str, str]],
    bundle: SearchBundle,
    instance: str,
    role: str,
    algorithm: str,
    seed: int,
    prices: PriceParameters,
) -> dict[str, Any]:
    checkpoint_path = checkpoint_dir / f"{instance}__{algorithm}__seed{seed}.json"
    row: dict[str, Any] = {
        "phase": "reference_audit",
        "instance": instance,
        "role": role,
        "algorithm": algorithm,
        "seed": int(seed),
        "checkpoint_path": str(checkpoint_path.relative_to(repo_root) if checkpoint_path.is_absolute() else checkpoint_path),
        "carbon_price": float(prices.carbon_price),
    }
    try:
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        solution = solution_from_dict(payload["solution"])
        metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices)
        violations = check_solution(solution, bundle.instance, prices)
        evaluated_cost = float(metrics["total_cost"])
        checkpoint_cost = float(payload["best_cost"])
        csv_row = csv_rows.get((instance, algorithm, int(seed)))
        csv_cost = float(csv_row["best_cost"]) if csv_row is not None else math.nan
        checkpoint_diff = evaluated_cost - checkpoint_cost
        csv_diff = evaluated_cost - csv_cost if math.isfinite(csv_cost) else math.nan
        route_count = len(solution.routes)
        cv_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv")
        ev_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev")
        status = "OK"
        errors: list[str] = []
        if violations:
            status = "HALT_REFERENCE_INFEASIBLE"
            errors.append(f"violations={len(violations)}")
        if abs(checkpoint_diff) > COST_TOLERANCE:
            status = "HALT_CHECKPOINT_COST_MISMATCH"
            errors.append(f"checkpoint_diff={checkpoint_diff}")
        if csv_row is None:
            status = "HALT_MISSING_THROUGHPUT_CSV_ROW"
            errors.append("missing throughput csv row")
        elif abs(csv_diff) > COST_TOLERANCE:
            status = "HALT_CSV_COST_MISMATCH"
            errors.append(f"csv_diff={csv_diff}")
        if role == "allcv" and ev_count != 0:
            status = "HALT_ALLCV_REFERENCE_HAS_EV"
            errors.append(f"ev_count={ev_count}")
        row.update(_metric_row(metrics))
        row.update(charging_behavior(solution, bundle, prices))
        row.update(
            {
                "status": status,
                "error": "; ".join(errors),
                "violation_count": len(violations),
                "checkpoint_best_cost": checkpoint_cost,
                "csv_best_cost": csv_cost,
                "checkpoint_cost_diff": checkpoint_diff,
                "csv_cost_diff": csv_diff,
                "route_count": route_count,
                "cv_route_count": cv_count,
                "ev_route_count": ev_count,
                "checkpoint_eval": int(payload.get("eval", 0)),
                "checkpoint_time_seconds": float(payload.get("time_seconds", math.nan)),
                "checkpoint_operator": str(payload.get("operator", "")),
                "_solution_obj": solution,
                "_bundle_obj": bundle,
            }
        )
    except Exception as exc:
        row.update(
            {
                "status": "HALT_REFERENCE_LOAD_ERROR",
                "error": repr(exc),
                "total_cost": math.inf,
                "violation_count": math.nan,
                "route_count": math.nan,
                "cv_route_count": math.nan,
                "ev_route_count": math.nan,
            }
        )
    return row


def phase0_dominance(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for instance, group in _group_by(records, "instance").items():
        allcv = _ok_records([row for row in group if row["role"] == "allcv"])
        mixed = _ok_records([row for row in group if row["role"] == "mixed"])
        row: dict[str, Any] = {"phase": "phase0", "instance": instance}
        if len(allcv) != len(SEEDS) or len(mixed) != len(SEEDS):
            row.update(
                {
                    "status": "HALT_INCOMPLETE_REFERENCE_AUDIT",
                    "classifier": "HALT",
                    "allcv_ok_rows": len(allcv),
                    "mixed_ok_rows": len(mixed),
                }
            )
            rows.append(row)
            continue
        allcv_costs = [float(item["total_cost"]) for item in allcv]
        mixed_costs = [float(item["total_cost"]) for item in mixed]
        best_allcv = min(allcv, key=lambda item: float(item["total_cost"]))
        best_mixed = min(mixed, key=lambda item: float(item["total_cost"]))
        mean_allcv = sum(allcv_costs) / len(allcv_costs)
        mean_mixed = sum(mixed_costs) / len(mixed_costs)
        paired_allcv_wins = 0
        paired_mixed_wins = 0
        paired_ties = 0
        for seed in SEEDS:
            a = _record_for_seed(allcv, seed)
            m = _record_for_seed(mixed, seed)
            delta = float(m["total_cost"]) - float(a["total_cost"])
            if delta < -COST_TOLERANCE:
                paired_mixed_wins += 1
            elif delta > COST_TOLERANCE:
                paired_allcv_wins += 1
            else:
                paired_ties += 1
        if float(best_allcv["total_cost"]) <= float(best_mixed["total_cost"]) + COST_TOLERANCE and mean_allcv <= mean_mixed + COST_TOLERANCE:
            classifier = "ALLCV_BEST_AND_MEAN"
        elif float(best_mixed["total_cost"]) < float(best_allcv["total_cost"]) - COST_TOLERANCE and mean_allcv <= mean_mixed + COST_TOLERANCE:
            classifier = "MIXED_EXISTS_MEAN_ALLCV"
        elif float(best_mixed["total_cost"]) < float(best_allcv["total_cost"]) - COST_TOLERANCE and mean_mixed < mean_allcv - COST_TOLERANCE:
            classifier = "MIXED_DOMINANT"
        else:
            classifier = "MIXED_MEAN_ONLY"
        row.update(
            {
                "status": "OK",
                "classifier": classifier,
                "best_allcv_cost": float(best_allcv["total_cost"]),
                "best_allcv_seed": int(best_allcv["seed"]),
                "best_mixed_cost": float(best_mixed["total_cost"]),
                "best_mixed_seed": int(best_mixed["seed"]),
                "best_gap_pct_mixed_minus_allcv": _gap_pct(float(best_mixed["total_cost"]), float(best_allcv["total_cost"])),
                "mean_allcv_cost": mean_allcv,
                "mean_mixed_cost": mean_mixed,
                "mean_gap_pct_mixed_minus_allcv": _gap_pct(mean_mixed, mean_allcv),
                "paired_allcv_wins": paired_allcv_wins,
                "paired_mixed_wins": paired_mixed_wins,
                "paired_ties": paired_ties,
            }
        )
        rows.append(row)
    return rows


def phase1_cost_breakdown(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for instance, group in _group_by(_ok_records(records), "instance").items():
        best_allcv = min((row for row in group if row["role"] == "allcv"), key=lambda item: float(item["total_cost"]))
        best_mixed = min((row for row in group if row["role"] == "mixed"), key=lambda item: float(item["total_cost"]))
        allcv_cost = float(best_allcv["total_cost"])
        for source in (best_allcv, best_mixed):
            row = {key: value for key, value in source.items() if not key.startswith("_")}
            row["phase"] = "phase1"
            row["role_label"] = ROLE_LABEL[str(source["role"])]
            row["best_reference"] = True
            row["gap_pct_vs_best_allcv"] = _gap_pct(float(source["total_cost"]), allcv_cost)
            rows.append(row)
    return rows


def phase2_fixed_replay(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for instance, group in _group_by(_ok_records(records), "instance").items():
        bundle = group[0]["_bundle_obj"]
        best_allcv = min((row for row in group if row["role"] == "allcv"), key=lambda item: float(item["total_cost"]))
        best_mixed = min((row for row in group if row["role"] == "mixed"), key=lambda item: float(item["total_cost"]))
        for scan_name, field_name, value, prices in _scan_specs():
            for source in (best_allcv, best_mixed):
                rows.append(
                    replay_reference(
                        instance=instance,
                        role=str(source["role"]),
                        source_seed=int(source["seed"]),
                        scan_name=scan_name,
                        field_name=field_name,
                        value=value,
                        solution=source["_solution_obj"],
                        bundle=bundle,
                        prices=prices,
                    )
                )
    return rows


def replay_reference(
    *,
    instance: str,
    role: str,
    source_seed: int,
    scan_name: str,
    field_name: str,
    value: float,
    solution: Solution,
    bundle: SearchBundle,
    prices: PriceParameters,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "phase": "phase2_fixed_replay",
        "instance": instance,
        "role": role,
        "algorithm": ROLE_TO_ALGORITHM[role],
        "source_seed": int(source_seed),
        "scan_name": scan_name,
        "field": field_name,
        "value": float(value),
        "carbon_price": float(prices.carbon_price),
    }
    try:
        replayed = solution if role == "allcv" else _replay_solution_for_prices(solution, bundle, prices)
        metrics = evaluate(replayed, bundle.instance, bundle.carbon_profile, prices)
        violations = check_solution(replayed, bundle.instance, prices)
        row.update(_metric_row(metrics))
        row.update(charging_behavior(replayed, bundle, prices))
        row.update(
            {
                "status": "OK" if not violations else "HALT_REPLAY_INFEASIBLE",
                "violation_count": len(violations),
                "route_count": len(replayed.routes),
                "cv_route_count": sum(1 for route in replayed.routes if route.vehicle_type.lower() == "cv"),
                "ev_route_count": sum(1 for route in replayed.routes if route.vehicle_type.lower() == "ev"),
            }
        )
    except Exception as exc:
        row.update(
            {
                "status": "HALT_REPLAY_ERROR",
                "error": repr(exc),
                "total_cost": math.inf,
                "violation_count": math.nan,
            }
        )
    return row


def phase2_reopt_refine(
    repo_root: Path,
    args: argparse.Namespace,
    records: list[dict[str, Any]],
    phase0_rows: list[dict[str, Any]],
    phase2_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Optional expensive refinement for near-flips on true all-CV instances."""

    true_allcv_instances = _true_allcv_instances(phase0_rows)
    triggers = _reopt_triggers(phase2_rows, true_allcv_instances)
    out: list[dict[str, Any]] = []
    for trigger in triggers:
        instance = str(trigger["instance"])
        bundle = _load_bundle(repo_root, instance)
        base_group = [row for row in _ok_records(records) if row["instance"] == instance]
        warm = min((row for row in base_group if row["role"] == "mixed"), key=lambda item: float(item["total_cost"]))["_solution_obj"]
        _, _, _, prices = _scan_spec_by_key(str(trigger["scan_name"]), float(trigger["value"]))
        for seed in (1, 2, 3):
            out.append(
                reopt_mixed(
                    bundle=bundle,
                    instance=instance,
                    trigger=trigger,
                    seed=seed,
                    eval_budget=int(args.reopt_eval_budget),
                    max_runtime_seconds=float(RUNTIME_CAP_SECONDS.get(instance, 900.0)),
                    initial_solution=warm,
                    prices=prices,
                )
            )
    return out


def reopt_mixed(
    *,
    bundle: SearchBundle,
    instance: str,
    trigger: dict[str, Any],
    seed: int,
    eval_budget: int,
    max_runtime_seconds: float,
    initial_solution: Solution,
    prices: PriceParameters,
) -> dict[str, Any]:
    started = time.perf_counter()
    row: dict[str, Any] = {
        "phase": "phase2_reopt_refine",
        "instance": instance,
        "role": "mixed",
        "algorithm": "run_alns_wouda_direct",
        "scan_name": str(trigger["scan_name"]),
        "field": str(trigger["field"]),
        "value": float(trigger["value"]),
        "seed": int(seed),
        "eval_budget": int(eval_budget),
        "max_runtime_seconds": float(max_runtime_seconds),
        "carbon_price": float(prices.carbon_price),
    }
    try:
        repaired_warm = _replay_solution_for_prices(initial_solution, bundle, prices)
        flags = e2_alns_throughput_flags(route_cost_cache=True, repair_structure_cache=True, timing_ledger=False)
        with _temporary_env(flags):
            result = run_alns_wouda(
                bundle.bundle_dir,
                iterations=None,
                seed=int(seed),
                eval_budget=int(eval_budget),
                max_runtime_seconds=float(max_runtime_seconds),
                policy=SearchPolicy(require_charging_signal=False),
                initial_solution=repaired_warm,
                prices=prices,
            )
        solution = result.best_solution
        metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices)
        violations = check_solution(solution, bundle.instance, prices)
        row.update(_metric_row(metrics))
        row.update(charging_behavior(solution, bundle, prices))
        row.update(
            {
                "status": "OK" if not violations else "HALT_REOPT_INFEASIBLE",
                "violation_count": len(violations),
                "solver_reported_feasible": bool(result.feasible),
                "actual_evals": int(result.evaluations),
                "best_penalized_obj": float(result.best_obj),
                "elapsed_seconds": time.perf_counter() - started,
                "route_count": len(solution.routes),
                "cv_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv"),
                "ev_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
                "active_flags": flags,
            }
        )
    except Exception as exc:
        row.update(
            {
                "status": "HALT_REOPT_ERROR",
                "error": repr(exc),
                "elapsed_seconds": time.perf_counter() - started,
                "total_cost": math.inf,
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

    ev_count = 0
    ev_drive_gt_battery = 0
    ev_public_routes = 0
    ev_detour_m = 0.0
    total_ev_route_kwh = 0.0
    max_ev_route_kwh = 0.0
    total_ev_route_distance_m = 0.0
    max_ev_route_distance_m = 0.0
    for route in solution.routes:
        if route.vehicle_type.lower() != "ev":
            continue
        ev_count += 1
        summary = route_ev_energy_summary(route, bundle.instance, prices)
        route_kwh = float(summary.ev_kwh)
        total_ev_route_kwh += route_kwh
        max_ev_route_kwh = max(max_ev_route_kwh, route_kwh)
        if route_kwh > float(prices.B_battery_kwh) + 1e-9:
            ev_drive_gt_battery += 1
        route_actions = actions_by_vehicle.get(route.vehicle_id, [])
        if any((node_lookup.get(action.station_id) and node_lookup[action.station_id].node_type.lower() == "f") for action in route_actions):
            ev_public_routes += 1
        clean = [node_id for node_id in route.node_sequence if not (node_lookup.get(node_id) and node_lookup[node_id].node_type.lower() == "f")]
        if len(clean) >= 2:
            clean_distance = sum(bundle.instance.distance(a, b) for a, b in zip(clean, clean[1:]))
            actual_distance = sum(bundle.instance.distance(a, b) for a, b in zip(route.node_sequence, route.node_sequence[1:]))
            total_ev_route_distance_m += clean_distance
            max_ev_route_distance_m = max(max_ev_route_distance_m, clean_distance)
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
        "avg_ev_route_drive_kwh": total_ev_route_kwh / ev_count if ev_count else 0.0,
        "max_ev_route_drive_kwh": max_ev_route_kwh,
        "avg_ev_route_distance_m": total_ev_route_distance_m / ev_count if ev_count else 0.0,
        "max_ev_route_distance_m": max_ev_route_distance_m,
        "battery_kwh": float(prices.B_battery_kwh),
        "avg_ev_route_drive_kwh_over_battery": (total_ev_route_kwh / ev_count / float(prices.B_battery_kwh)) if ev_count and float(prices.B_battery_kwh) else 0.0,
        "max_ev_route_drive_kwh_over_battery": (max_ev_route_kwh / float(prices.B_battery_kwh)) if float(prices.B_battery_kwh) else 0.0,
    }


def summarize_conclusion(
    records: list[dict[str, Any]],
    phase0_rows: list[dict[str, Any]],
    phase1_rows: list[dict[str, Any]],
    phase2_rows: list[dict[str, Any]],
    reopt_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if _has_audit_halt(records):
        return {
            "verdict": "HALT_REFERENCE_AUDIT_FAILED",
            "summary": "At least one 09d checkpoint failed load, feasibility, vehicle-type, or cost-consistency audit.",
            "halt_rows": [row for row in _csv_safe_records(records) if str(row.get("status")) != "OK"],
        }
    classifiers = {str(row["instance"]): str(row["classifier"]) for row in phase0_rows}
    mechanism = _mechanism_by_instance(phase1_rows)
    scan = _scan_summary(phase0_rows, phase2_rows)
    allcv_true = [instance for instance, classifier in classifiers.items() if classifier == "ALLCV_BEST_AND_MEAN"]
    mixed_exists = [instance for instance, classifier in classifiers.items() if classifier == "MIXED_EXISTS_MEAN_ALLCV"]
    if allcv_true:
        verdict = "ALLCV_ECONOMIC_ON_TRUE_LARGESCALE_CASE"
        summary = (
            f"True best-and-mean all-CV dominance is present on {', '.join(allcv_true)}. "
            f"Cases with best mixed already present: {', '.join(mixed_exists) if mixed_exists else 'none'}."
        )
    elif mixed_exists:
        verdict = "MIXED_EXISTS_SEARCH_RELIABILITY_ISSUE"
        summary = (
            "No checked instance has all-CV dominance in both best and mean; "
            "the issue is primarily search reliability/variance, not proof that mixed is economically impossible."
        )
    else:
        verdict = "MIXED_DOMINANT_ON_CHECKED_LARGESCALE_CASES"
        summary = "Mixed dominates on checked large-scale references; the all-CV premise is not reproduced."
    return {
        "verdict": verdict,
        "summary": summary,
        "classifiers": classifiers,
        "phase1_mechanism": mechanism,
        "phase2_scan": scan,
        "reopt_rows": len(reopt_rows),
    }


def _mechanism_by_instance(phase1_rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for instance, rows in _group_by(phase1_rows, "instance").items():
        allcv = next((row for row in rows if row["role"] == "allcv"), None)
        mixed = next((row for row in rows if row["role"] == "mixed"), None)
        if not allcv or not mixed:
            continue
        out[instance] = {
            "mixed_total_gap_pct": _gap_pct(float(mixed["total_cost"]), float(allcv["total_cost"])),
            "mixed_cost_fix_minus_allcv": float(mixed["cost_fix"]) - float(allcv["cost_fix"]),
            "mixed_cost_fuel_minus_allcv": float(mixed["cost_fuel"]) - float(allcv["cost_fuel"]),
            "mixed_cost_elec_minus_allcv": float(mixed["cost_elec"]) - float(allcv["cost_elec"]),
            "mixed_cost_occ_minus_allcv": float(mixed["cost_occ"]) - float(allcv["cost_occ"]),
            "mixed_cost_carbon_minus_allcv": float(mixed["cost_carbon"]) - float(allcv["cost_carbon"]),
            "mixed_public_charge_kwh": float(mixed.get("public_charge_kwh", 0.0)),
            "mixed_public_occupancy_cost": float(mixed.get("public_occupancy_cost", 0.0)),
            "mixed_ev_routes_with_public_charge": int(mixed.get("ev_routes_with_public_charge", 0)),
            "mixed_ev_routes_drive_kwh_gt_battery": int(mixed.get("ev_routes_drive_kwh_gt_battery", 0)),
            "mixed_max_ev_route_drive_kwh_over_battery": float(mixed.get("max_ev_route_drive_kwh_over_battery", 0.0)),
        }
    return out


def _scan_summary(phase0_rows: list[dict[str, Any]], phase2_rows: list[dict[str, Any]]) -> dict[str, Any]:
    true_allcv = {str(row["instance"]) for row in phase0_rows if row.get("classifier") == "ALLCV_BEST_AND_MEAN"}
    out: dict[str, Any] = {"true_allcv_instances": sorted(true_allcv), "flips": [], "near_flips": []}
    for key, rows in _group_phase2_rows(phase2_rows).items():
        instance, scan_name, field, value = key
        if instance not in true_allcv:
            continue
        allcv = next((row for row in rows if row["role"] == "allcv" and row["status"] == "OK"), None)
        mixed = next((row for row in rows if row["role"] == "mixed" and row["status"] == "OK"), None)
        if not allcv or not mixed:
            continue
        gap = _gap_pct(float(mixed["total_cost"]), float(allcv["total_cost"]))
        rec = {
            "instance": instance,
            "scan_name": scan_name,
            "field": field,
            "value": value,
            "gap_pct_mixed_minus_allcv": gap,
            "allcv_cost": float(allcv["total_cost"]),
            "mixed_cost": float(mixed["total_cost"]),
        }
        if gap <= 0.0:
            out["flips"].append(rec)
        elif gap <= 1.0:
            out["near_flips"].append(rec)
    out["flips"].sort(key=lambda row: (row["gap_pct_mixed_minus_allcv"], row["instance"], row["scan_name"], float(row["value"])))
    out["near_flips"].sort(key=lambda row: (row["gap_pct_mixed_minus_allcv"], row["instance"], row["scan_name"], float(row["value"])))
    return out


def render_report(
    metadata: dict[str, Any],
    stdout_summary: dict[str, Any],
    records: list[dict[str, Any]],
    phase0_rows: list[dict[str, Any]],
    phase1_rows: list[dict[str, Any]],
    phase2_rows: list[dict[str, Any]],
    reopt_triggers: list[dict[str, Any]],
    reopt_rows: list[dict[str, Any]],
    conclusion: dict[str, Any],
) -> str:
    lines = [
        "# 09f Large-Scale All-CV Diagnostic",
        "",
        f"Conclusion: `{conclusion['verdict']}`.",
        "",
        conclusion["summary"],
        "",
        "## Environment",
        "",
        f"- repo_head: `{metadata['repo_head']}`",
        f"- diagnostic_artifact_commit: `{metadata['diagnostic_artifact_commit']}`",
        f"- branch: `{metadata['branch']}`",
        f"- python: `{metadata['python']}`",
        f"- python_version: `{metadata['python_version']}`",
        f"- numpy: `{metadata['numpy']}`",
        f"- PYTHONHASHSEED: `{metadata.get('PYTHONHASHSEED', '')}`",
        f"- carbon_price: `{CARBON_PRICE}`",
        f"- phase2_mode: `{metadata['phase2_mode']}`",
        f"- enable_reopt_refine: `{metadata['enable_reopt_refine']}`",
        f"- reopt_collection_note: `{metadata.get('reopt_collection_note', '')}`",
        f"- elapsed_seconds: `{metadata['elapsed_seconds']:.3f}`",
        "",
        "## Command",
        "",
        "```bash",
        metadata["command"],
        "```",
        "",
        "Stdout summary:",
        "",
        "```json",
        json.dumps(stdout_summary, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "## Phase 0 Reference Audit And Dominance",
        "",
        _phase0_table(phase0_rows),
        "",
        "Checkpoint audit status:",
        "",
        _reference_audit_table(records),
    ]
    if phase1_rows:
        lines.extend(
            [
                "",
                "## Phase 1 Cost And Charging Mechanism",
                "",
                _phase1_cost_table(phase1_rows),
                "",
                "Mixed EV charging behavior:",
                "",
                _phase1_charging_table(phase1_rows),
            ]
        )
    if phase2_rows:
        lines.extend(
            [
                "",
                "## Phase 2 Fixed-Replay Single-Parameter Scan",
                "",
                _phase2_table(phase0_rows, phase2_rows),
                "",
                "Fixed replay strips public station nodes from EV routes, replays charging under the override, and re-evaluates/checks independently. It isolates economics, but it is not a full re-optimization proof. Re-optimization refinement, when enabled, uses the strongest fixed-replay trigger per parameter lever on true all-CV instances to avoid rerunning duplicate grid points with identical fixed-route economics.",
            ]
        )
    if reopt_triggers or reopt_rows or metadata.get("reopt_collection_note"):
        lines.extend(["", "## Phase 2 Re-Optimization Refinement", "", "Reopt trigger candidates:", "", _trigger_table(reopt_triggers)])
        if reopt_rows:
            lines.extend(["", "Completed reopt rows:", "", _reopt_table(reopt_rows)])
        elif metadata.get("reopt_collection_note"):
            lines.extend(["", f"Status: `HALT_REOPT_COLLECTION_COST`. {metadata['reopt_collection_note']}"])
        else:
            lines.extend(["", "Status: `NOT_RUN_IN_THIS_COMMAND`; triggers are listed for an explicit expensive refine run."])
    lines.extend(
        [
            "",
            "## One-Line Root Cause",
            "",
            _root_cause_sentence(conclusion),
            "",
            "## Artifacts",
            "",
            "- `baselines/e2_alns/largescale_allcv_diagnostic.py`",
            "- `baselines/e2_alns/largescale_allcv_diagnostic_data/reference_solution_audit.csv`",
            "- `baselines/e2_alns/largescale_allcv_diagnostic_data/phase0_dominance.csv`",
            "- `baselines/e2_alns/largescale_allcv_diagnostic_data/phase1_cost_breakdown.csv`",
            "- `baselines/e2_alns/largescale_allcv_diagnostic_data/phase2_fixed_replay.csv`",
            "- `baselines/e2_alns/largescale_allcv_diagnostic_data/phase2_reopt_triggers.csv`",
            "- `baselines/e2_alns/largescale_allcv_diagnostic_data/metadata.json`",
            "",
        ]
    )
    return "\n".join(lines)


def _phase0_table(rows: list[dict[str, Any]]) -> str:
    table_rows = [
        (
            row["instance"],
            row.get("classifier", ""),
            _fmt(row.get("best_allcv_cost")),
            row.get("best_allcv_seed", ""),
            _fmt(row.get("best_mixed_cost")),
            row.get("best_mixed_seed", ""),
            _fmt(row.get("best_gap_pct_mixed_minus_allcv")),
            _fmt(row.get("mean_allcv_cost")),
            _fmt(row.get("mean_mixed_cost")),
            _fmt(row.get("mean_gap_pct_mixed_minus_allcv")),
            row.get("paired_allcv_wins", ""),
            row.get("paired_mixed_wins", ""),
        )
        for row in rows
    ]
    return _markdown_table(
        [
            "instance",
            "classifier",
            "best all-CV",
            "seed",
            "best mixed",
            "seed",
            "best gap %",
            "mean all-CV",
            "mean mixed",
            "mean gap %",
            "paired all-CV wins",
            "paired mixed wins",
        ],
        table_rows,
    )


def _reference_audit_table(records: list[dict[str, Any]]) -> str:
    table_rows = [
        (
            row["instance"],
            row["role"],
            row["seed"],
            row["status"],
            _fmt(row.get("total_cost")),
            row.get("cv_route_count", ""),
            row.get("ev_route_count", ""),
            row.get("violation_count", ""),
            _fmt(row.get("csv_cost_diff")),
            _fmt(row.get("checkpoint_cost_diff")),
        )
        for row in records
    ]
    return _markdown_table(["instance", "role", "seed", "status", "total", "CV", "EV", "viol", "csv diff", "ckpt diff"], table_rows)


def _phase1_cost_table(rows: list[dict[str, Any]]) -> str:
    table_rows = [
        (
            row["instance"],
            row["role_label"],
            row["seed"],
            _fmt(row["total_cost"]),
            _fmt(row["gap_pct_vs_best_allcv"]),
            row["cv_route_count"],
            row["ev_route_count"],
            _fmt(row["cost_fix"]),
            _fmt(row["cost_km"]),
            _fmt(row["cost_fuel"]),
            _fmt(row["cost_elec"]),
            _fmt(row["cost_occ"]),
            _fmt(row["cost_carbon"]),
            _fmt(row["E_cv_direct"]),
            _fmt(row["E_ev_indirect"]),
            _fmt(row["E_total"]),
        )
        for row in rows
    ]
    return _markdown_table(
        [
            "instance",
            "role",
            "seed",
            "total",
            "gap %",
            "CV",
            "EV",
            "fix",
            "km",
            "fuel",
            "elec",
            "occ",
            "carbon",
            "E_cv",
            "E_ev",
            "E_total",
        ],
        table_rows,
    )


def _phase1_charging_table(rows: list[dict[str, Any]]) -> str:
    table_rows = []
    for row in rows:
        if row["role"] != "mixed":
            continue
        table_rows.append(
            (
                row["instance"],
                row["seed"],
                row["ev_route_count"],
                row["charge_action_count"],
                _fmt(row["depot_charge_kwh"]),
                _fmt(row["public_charge_kwh"]),
                _fmt(row["depot_charge_cost"]),
                _fmt(row["public_charge_cost"]),
                _fmt(row["public_occupancy_cost"]),
                row["ev_routes_with_public_charge"],
                row["ev_routes_drive_kwh_gt_battery"],
                _fmt(row["avg_ev_route_drive_kwh"]),
                _fmt(row["max_ev_route_drive_kwh"]),
                _fmt(row["max_ev_route_drive_kwh_over_battery"]),
            )
        )
    return _markdown_table(
        [
            "instance",
            "seed",
            "EV routes",
            "charges",
            "depot kWh",
            "public kWh",
            "depot cost",
            "public cost",
            "occ cost",
            "EV routes public",
            "EV routes >80kWh",
            "avg EV kWh",
            "max EV kWh",
            "max/battery",
        ],
        table_rows,
    )


def _phase2_table(phase0_rows: list[dict[str, Any]], phase2_rows: list[dict[str, Any]]) -> str:
    classifier = {str(row["instance"]): str(row["classifier"]) for row in phase0_rows}
    table_rows = []
    for key, rows in _group_phase2_rows(phase2_rows).items():
        instance, scan_name, _field, value = key
        allcv = next((row for row in rows if row["role"] == "allcv" and row["status"] == "OK"), None)
        mixed = next((row for row in rows if row["role"] == "mixed" and row["status"] == "OK"), None)
        if not allcv or not mixed:
            table_rows.append((instance, classifier.get(instance, ""), scan_name, value, "HALT", "", "", "", "", ""))
            continue
        gap = _gap_pct(float(mixed["total_cost"]), float(allcv["total_cost"]))
        table_rows.append(
            (
                instance,
                classifier.get(instance, ""),
                scan_name,
                value,
                _fmt(allcv["total_cost"]),
                _fmt(mixed["total_cost"]),
                _fmt(gap),
                gap <= 0.0,
                _fmt(mixed.get("public_charge_kwh")),
                _fmt(mixed.get("public_occupancy_cost")),
            )
        )
    return _markdown_table(
        ["instance", "classifier", "parameter", "value", "all-CV", "mixed", "gap %", "mixed <= all-CV", "mixed public kWh", "mixed occ cost"],
        table_rows,
    )


def _reopt_table(rows: list[dict[str, Any]]) -> str:
    table_rows = [
        (
            row["instance"],
            row["scan_name"],
            row["value"],
            row["seed"],
            row["status"],
            _fmt(row.get("total_cost")),
            row.get("actual_evals", ""),
            _fmt(row.get("elapsed_seconds")),
            row.get("cv_route_count", ""),
            row.get("ev_route_count", ""),
        )
        for row in rows
    ]
    return _markdown_table(["instance", "parameter", "value", "seed", "status", "total", "evals", "elapsed", "CV", "EV"], table_rows)


def _trigger_table(rows: list[dict[str, Any]]) -> str:
    table_rows = [
        (
            row["instance"],
            row["scan_name"],
            row["field"],
            row["value"],
            _fmt(row["gap_pct_mixed_minus_allcv"]),
        )
        for row in rows
    ]
    return _markdown_table(["instance", "parameter", "field", "value", "fixed replay gap %"], table_rows)


def _root_cause_sentence(conclusion: dict[str, Any]) -> str:
    if conclusion["verdict"] == "HALT_REFERENCE_AUDIT_FAILED":
        return "09f did not reach a mechanism conclusion because the checkpoint source-of-truth audit failed."
    classifiers = conclusion.get("classifiers", {})
    scan = conclusion.get("phase2_scan", {})
    flips = scan.get("flips", [])
    near = scan.get("near_flips", [])
    mixed_exists = [instance for instance, label in classifiers.items() if label == "MIXED_EXISTS_MEAN_ALLCV"]
    allcv_true = [instance for instance, label in classifiers.items() if label == "ALLCV_BEST_AND_MEAN"]
    if flips:
        first = flips[0]
        return (
            f"固定真实碳价下，100/150c 的问题是 mixed 好解存在但搜索均值不稳；"
            f"{', '.join(allcv_true)} 的 all-CV 真实占优可由单参数 `{first['scan_name']}={first['value']}` 在 fixed replay 中翻成 mixed <= all-CV，"
            "需要后续重优化确认。"
        )
    if near:
        first = near[0]
        return (
            f"固定真实碳价下，{', '.join(mixed_exists) if mixed_exists else '部分大算例'} 已有 mixed best 解，"
            f"{', '.join(allcv_true)} 仍 all-CV 占优；最近的单参数是 `{first['scan_name']}={first['value']}`，"
            f"但 fixed replay 仍差 {first['gap_pct_mixed_minus_allcv']:.3f}%，不能硬判单一现实参数已经足够。"
        )
    if allcv_true:
        return (
            f"固定真实碳价下，{', '.join(mixed_exists) if mixed_exists else '100/150c'} 指向搜索可靠性/方差问题，"
            f"{', '.join(allcv_true)} 指向真实经济/参数压力；本次单参数 fixed replay 没有让 mixed 反超 true all-CV case，"
            "因此不能把电池/速度/公共电价/占用费中的任一项单独定为已证实充分真凶。"
        )
    return "固定真实碳价下，checked large-scale cases 没有复现 best-and-mean all-CV 支配，优先查搜索可靠性。"


def _scan_specs() -> list[tuple[str, str, float, PriceParameters]]:
    base = replace(DEFAULT_PRICES, carbon_price=CARBON_PRICE)
    specs: list[tuple[str, str, float, PriceParameters]] = []
    specs.extend(("battery_kwh", "B_battery_kwh", value, replace(base, B_battery_kwh=value)) for value in (80.0, 160.0, 320.0, 480.0))
    specs.extend(("speed_ms", "v_speed_ms", value, replace(base, v_speed_ms=value)) for value in (25.0, 16.7, 11.1))
    specs.extend(
        (
            "public_station_price",
            "station_electricity_price",
            value,
            replace(base, electricity_price=value, station_electricity_price=value),
        )
        for value in (0.82, 0.40, 0.1853)
    )
    specs.extend(("occupancy_fee", "occupancy_fee", value, replace(base, occupancy_fee=value)) for value in (0.50, 0.10, 0.0))
    return specs


def _true_allcv_instances(phase0_rows: list[dict[str, Any]]) -> set[str]:
    return {
        str(row["instance"])
        for row in phase0_rows
        if row.get("classifier") == "ALLCV_BEST_AND_MEAN" and row.get("status") == "OK"
    }


def _scan_spec_by_key(scan_name: str, value: float) -> tuple[str, str, float, PriceParameters]:
    for spec in _scan_specs():
        if spec[0] == scan_name and abs(float(spec[2]) - float(value)) <= 1e-9:
            return spec
    raise KeyError((scan_name, value))


def _reopt_triggers(phase2_rows: list[dict[str, Any]], instances: set[str]) -> list[dict[str, Any]]:
    best_by_lever: dict[tuple[str, str], dict[str, Any]] = {}
    for key, rows in _group_phase2_rows(phase2_rows).items():
        instance, scan_name, field, value = key
        if instance not in instances:
            continue
        allcv = next((row for row in rows if row["role"] == "allcv" and row["status"] == "OK"), None)
        mixed = next((row for row in rows if row["role"] == "mixed" and row["status"] == "OK"), None)
        if not allcv or not mixed:
            continue
        gap = _gap_pct(float(mixed["total_cost"]), float(allcv["total_cost"]))
        if gap <= 1.0:
            candidate = {"instance": instance, "scan_name": scan_name, "field": field, "value": value, "gap_pct_mixed_minus_allcv": gap}
            lever_key = (instance, scan_name)
            previous = best_by_lever.get(lever_key)
            if previous is None or gap < float(previous["gap_pct_mixed_minus_allcv"]):
                best_by_lever[lever_key] = candidate
    triggers = list(best_by_lever.values())
    triggers.sort(key=lambda row: (row["gap_pct_mixed_minus_allcv"], row["instance"], row["scan_name"], float(row["value"])))
    return triggers


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


def _metric_row(metrics: dict[str, Any]) -> dict[str, float]:
    keys = [
        "total_cost",
        "cost_fix",
        "cost_km",
        "cost_fuel",
        "cost_elec",
        "cost_occ",
        "cost_transship",
        "cost_carbon",
        "fuel_liters",
        "electric_kwh",
        "E_total",
        "E_cv_direct",
        "E_ev_indirect",
        "carbon_quota_kg",
    ]
    return {key: float(metrics.get(key, 0.0)) for key in keys}


def _read_throughput_rows(path: Path) -> dict[tuple[str, str, int], dict[str, str]]:
    rows: dict[tuple[str, str, int], dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows[(str(row["instance"]), str(row["algorithm"]), int(row["seed"]))] = row
    return rows


def _load_bundle(repo_root: Path, instance: str) -> SearchBundle:
    return load_search_bundle(repo_root / "models/data_bundle/generated_instances/e2_benchmark" / "threeshift" / instance)


def _metadata(repo_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": "setp-09f-diagnostic-metadata.v1",
        "repo_root": str(repo_root),
        "repo_head": _git(repo_root, "rev-parse", "HEAD"),
        "branch": _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD"),
        "python": sys.executable,
        "python_version": sys.version.split()[0],
        "numpy": np.__version__,
        "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED", ""),
        "phase2_mode": str(args.phase2_mode),
        "enable_reopt_refine": bool(args.enable_reopt_refine),
        "reopt_collection_note": str(args.reopt_collection_note),
        "reopt_eval_budget": int(args.reopt_eval_budget),
        "instances": list(args.instances),
        "checkpoint_dir": str(args.checkpoint_dir),
        "throughput_csv": str(args.throughput_csv),
        "command": "PYTHONPATH=solver/src:models/src PYTHONHASHSEED=0 " + " ".join(shlex.quote(part) for part in [sys.executable, *sys.argv]),
    }


def _has_audit_halt(records: list[dict[str, Any]]) -> bool:
    return any(str(row.get("status")) != "OK" for row in records)


def _ok_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in records if str(row.get("status")) == "OK" and math.isfinite(float(row.get("total_cost", math.inf)))]


def _record_for_seed(records: list[dict[str, Any]], seed: int) -> dict[str, Any]:
    for row in records:
        if int(row["seed"]) == int(seed):
            return row
    raise KeyError(seed)


def _group_by(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(str(row[key]), []).append(row)
    return out


def _group_phase2_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str, float], list[dict[str, Any]]]:
    out: dict[tuple[str, str, str, float], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["instance"]), str(row["scan_name"]), str(row["field"]), float(row["value"]))
        out.setdefault(key, []).append(row)
    return out


def _gap_pct(value: float, reference: float) -> float:
    if not reference:
        return math.inf
    return 100.0 * (float(value) - float(reference)) / float(reference)


def _csv_safe_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in row.items() if not key.startswith("_")} for row in rows]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row.keys() if not key.startswith("_")})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(value) for key, value in row.items() if not key.startswith("_")})


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _csv_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _markdown_table(headers: list[str], rows: list[tuple[Any, ...]]) -> str:
    if not rows:
        return "_No rows._"
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_md(value) for value in row) + " |")
    return "\n".join(lines)


def _md(value: Any) -> str:
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _fmt(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return str(value)
    if math.isnan(number):
        return "nan"
    if math.isinf(number):
        return "inf" if number > 0 else "-inf"
    return f"{number:.6f}"


def _git(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=repo_root, text=True).strip()
    except Exception:
        return "UNKNOWN"


@contextmanager
def _temporary_env(flags: dict[str, str]):
    old_env = {name: os.environ.get(name) for name in flags}
    try:
        for name, value in flags.items():
            os.environ[name] = str(value)
        yield
    finally:
        for name, value in old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


if __name__ == "__main__":
    raise SystemExit(main())
