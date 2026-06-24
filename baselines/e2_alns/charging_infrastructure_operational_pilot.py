#!/usr/bin/env python3
"""09o charging-infrastructure operational pilot.

This is a bounded diagnostic after the 09n fleet-cap HALT.  It asks a smaller
question before any formal model change: do 280kWh EV-heavy solutions depend on
large depot/public charging concurrency that the current generated instances
make unusually easy?

The script does not change prices.py, cost.py, check.py, evaluation.py,
generated bundles, or solver semantics.  It runs a small auditable optimization
probe, saves returned solutions, and audits station/depot charging occupancy
against the existing checker's capacity model.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Iterable

import numpy as np

from setp_solver.check import STATION_CAPACITY, check_solution
from setp_solver.cost import charging_slot_breakdown, evaluate
from setp_solver.prices import DEFAULT_PRICES, PriceParameters
from setp_solver.search.alns_wouda import SearchPolicy, run_alns_wouda
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.metaheuristic_baselines import solution_to_dict
from setp_solver.search.winner_operators import e2_alns_throughput_flags
from setp_solver.solution import Solution


BENCHMARK_ROOT = Path("models/data_bundle/generated_instances/e2_benchmark")
DEFAULT_OUTPUT_DIR = Path("baselines/e2_alns/charging_infrastructure_operational_pilot_data")
DEFAULT_REPORT = Path("baselines/e2_alns/charging_infrastructure_operational_pilot.md")
CARBON_PRICE = 0.05034
BATTERY_KWH = 280.0
VARIANT_ORDER = ("free_mixed", "ev_shell")
PILOT_INSTANCES = (
    "vanilla/e2-vanilla-200c-01",
    "multidepot/e2-multidepot-200c-01",
    "threeshift/e2-threeshift-200c-01",
)
SMOKE_INSTANCES = (
    "multidepot/e2-multidepot-100c-01",
    "threeshift/e2-threeshift-200c-01",
)
TERMINAL_STATUSES = {"OK", "VIOLATION", "TIMEOUT", "ERROR", "JSON_PARSE_ERROR", "SUBPROCESS_NONZERO"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT))
    parser.add_argument("--phase0-only", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--instances", nargs="*", default=[])
    parser.add_argument("--variants", nargs="*", default=list(VARIANT_ORDER))
    parser.add_argument("--seeds", nargs="*", type=int, default=[1])
    parser.add_argument("--eval-budget", type=int, default=500)
    parser.add_argument("--runtime-cap-small", type=float, default=60.0)
    parser.add_argument("--runtime-cap-medium", type=float, default=90.0)
    parser.add_argument("--runtime-cap-large", type=float, default=120.0)
    parser.add_argument("--task-timeout-buffer", type=float, default=30.0)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--retry-timeouts", action="store_true")
    parser.add_argument("--single-run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--single-category", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-instance", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-variant", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-seed", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--single-eval-budget", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--single-runtime-cap", type=float, default=0.0, help=argparse.SUPPRESS)
    parser.add_argument("--single-output-dir", default="", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    if args.single_run:
        return single_run_cli(repo_root, args)

    output_dir = repo_root / args.output_dir
    report_path = repo_root / args.report_path
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "solutions").mkdir(parents=True, exist_ok=True)

    instances = selected_instances(args)
    prices = pilot_prices()
    metadata = build_metadata(repo_root, args, instances, prices)
    instance_rows = instance_structure_rows(repo_root, instances)
    all_structure_rows = instance_structure_rows(repo_root, all_focus_instances(repo_root))
    write_csv(output_dir / "pilot_instance_structure.csv", instance_rows)
    write_csv(output_dir / "all_focus_instance_structure.csv", all_structure_rows)

    raw_rows: list[dict[str, Any]] = []
    winner_rows: list[dict[str, Any]] = []
    if not args.phase0_only:
        raw_rows = run_pilot(repo_root, output_dir, args, instances)
        write_csv(output_dir / "raw_runs.csv", raw_rows)
        winner_rows = winner_rows_from_raw(raw_rows)
        write_csv(output_dir / "winners.csv", winner_rows)
    else:
        write_csv(output_dir / "raw_runs.csv", raw_rows)
        write_csv(output_dir / "winners.csv", winner_rows)

    conclusion = summarize_conclusion(metadata, instance_rows, raw_rows, winner_rows)
    write_json(output_dir / "metadata.json", metadata)
    write_json(output_dir / "conclusion.json", conclusion)
    report_path.write_text(render_report(metadata, instance_rows, raw_rows, winner_rows, conclusion), encoding="utf-8")

    print(
        json.dumps(
            {
                "schema_version": metadata["schema_version"],
                "verdict": conclusion["verdict"],
                "report": str(args.report_path),
                "output_dir": str(args.output_dir),
                "raw_rows": len(raw_rows),
                "winner_rows": len(winner_rows),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 2 if str(conclusion["verdict"]).startswith("HALT_") else 0


def pilot_prices() -> PriceParameters:
    return replace(DEFAULT_PRICES, B_battery_kwh=BATTERY_KWH, carbon_price=CARBON_PRICE)


def selected_instances(args: argparse.Namespace) -> list[str]:
    if args.instances:
        return [normalize_instance(value) for value in args.instances]
    return list(SMOKE_INSTANCES if args.smoke else PILOT_INSTANCES)


def normalize_instance(value: str) -> str:
    text = str(value).strip()
    if "/" in text:
        category, instance = text.split("/", 1)
        return f"{category}/{instance}"
    for category in ("vanilla", "multidepot", "threeshift"):
        if text.startswith(f"e2-{category}-"):
            return f"{category}/{text}"
    raise ValueError(f"Cannot infer category for instance {value!r}; use category/instance")


def all_focus_instances(repo_root: Path) -> list[str]:
    root = repo_root / BENCHMARK_ROOT
    refs: list[str] = []
    for category in ("vanilla", "multidepot", "threeshift"):
        for path in sorted((root / category).glob("e2-*-*c-*")):
            match = re.search(r"-(75|100|150|200)c-", path.name)
            if path.is_dir() and match and (path / "instance.json").exists():
                refs.append(f"{category}/{path.name}")
    return refs


def build_metadata(repo_root: Path, args: argparse.Namespace, instances: list[str], prices: PriceParameters) -> dict[str, Any]:
    return {
        "schema_version": "setp-09o-charging-infrastructure-operational-pilot.v1",
        "commit_hash": git_output(repo_root, "rev-parse", "HEAD"),
        "git_status_short": git_output(repo_root, "status", "--short", "--untracked-files=all"),
        "python": sys.executable,
        "python_version": sys.version.replace("\n", " "),
        "numpy": np.__version__,
        "command": " ".join([sys.executable, *sys.argv]),
        "output_dir": str(args.output_dir),
        "report_path": str(args.report_path),
        "instances": instances,
        "variants": list(args.variants),
        "seeds": list(args.seeds),
        "eval_budget": int(args.eval_budget),
        "runtime_caps": {
            "small": float(args.runtime_cap_small),
            "medium": float(args.runtime_cap_medium),
            "large": float(args.runtime_cap_large),
        },
        "B_battery_kwh": float(prices.B_battery_kwh),
        "v_speed_ms": float(prices.v_speed_ms),
        "carbon_price": float(prices.carbon_price),
        "phase0_only": bool(args.phase0_only),
        "smoke": bool(args.smoke),
        "resume": bool(args.resume),
        "retry_timeouts": bool(args.retry_timeouts),
        "diagnostic_artifact_commit": "PENDING_COMMIT",
        "protected_files_unchanged_by_design": [
            "solver/src/setp_solver/prices.py",
            "solver/src/setp_solver/cost.py",
            "solver/src/setp_solver/check.py",
            "solver/src/setp_solver/search/evaluation.py",
        ],
    }


def instance_structure_rows(repo_root: Path, instances: Iterable[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in instances:
        category, instance = item.split("/", 1)
        bundle_dir = repo_root / BENCHMARK_ROOT / category / instance
        if not (bundle_dir / "instance.json").exists():
            rows.append({"category": category, "instance": instance, "exists": False})
            continue
        raw = json.loads((bundle_dir / "instance.json").read_text(encoding="utf-8"))
        nodes = raw.get("nodes", [])
        meta = raw.get("metadata", {})
        customers = [node for node in nodes if str(node.get("node_type", "")).lower() == "c"]
        depots = [node for node in nodes if str(node.get("node_type", "")).lower() == "d"]
        stations = [node for node in nodes if str(node.get("node_type", "")).lower() == "f"]
        depot_chargers = [int(node.get("station_chargers") or node.get("station_capacity") or 0) for node in depots]
        public_chargers = [int(node.get("station_chargers") or node.get("station_capacity") or 1) for node in stations]
        rows.append(
            {
                "category": category,
                "instance": instance,
                "exists": True,
                "customer_count": len(customers),
                "size_from_name": customer_count(instance),
                "replicate": replicate_id(instance),
                "depot_count": len(depots),
                "public_station_count": len(stations),
                "manifest_num_cv": meta.get("num_cv", ""),
                "manifest_num_ev": meta.get("num_ev", ""),
                "metadata_depot_chargers": meta.get("depot_chargers", ""),
                "metadata_depot_chargers_policy": meta.get("depot_chargers_policy", ""),
                "metadata_public_station_chargers": meta.get("public_station_chargers", ""),
                "depot_chargers_min": min(depot_chargers) if depot_chargers else "",
                "depot_chargers_max": max(depot_chargers) if depot_chargers else "",
                "depot_chargers_mean": mean(depot_chargers) if depot_chargers else "",
                "public_chargers_min": min(public_chargers) if public_chargers else "",
                "public_chargers_max": max(public_chargers) if public_chargers else "",
                "public_chargers_mean": mean(public_chargers) if public_chargers else "",
            }
        )
    return rows


def run_pilot(repo_root: Path, output_dir: Path, args: argparse.Namespace, instances: list[str]) -> list[dict[str, Any]]:
    tasks = build_tasks(instances, args)
    completed = load_completed_rows(output_dir, retry_timeouts=bool(args.retry_timeouts)) if args.resume else {}
    rows: list[dict[str, Any]] = []
    for task in tasks:
        existing = completed.get(task_key(task))
        if existing is not None:
            rows.append(existing)
            continue
        row = run_one_subprocess(repo_root, output_dir, args, task)
        rows.append(row)
        write_csv(output_dir / "raw_runs.partial.csv", sorted_rows(rows))
    return sorted_rows(rows)


def build_tasks(instances: list[str], args: argparse.Namespace) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for item in instances:
        category, instance = item.split("/", 1)
        cap = runtime_cap(instance, args)
        for seed in args.seeds:
            for variant in args.variants:
                tasks.append(
                    {
                        "category": category,
                        "instance": instance,
                        "seed": int(seed),
                        "variant": str(variant),
                        "eval_budget": int(args.eval_budget),
                        "runtime_cap_seconds": float(cap),
                    }
                )
    return tasks


def run_one_subprocess(repo_root: Path, output_dir: Path, args: argparse.Namespace, task: dict[str, Any]) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--repo-root",
        str(repo_root),
        "--single-run",
        "--single-category",
        str(task["category"]),
        "--single-instance",
        str(task["instance"]),
        "--single-variant",
        str(task["variant"]),
        "--single-seed",
        str(task["seed"]),
        "--single-eval-budget",
        str(task["eval_budget"]),
        "--single-runtime-cap",
        str(task["runtime_cap_seconds"]),
        "--single-output-dir",
        str(output_dir),
    ]
    timeout = float(task["runtime_cap_seconds"]) + float(args.task_timeout_buffer)
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, cwd=repo_root, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        return timeout_row(repo_root, task, timeout, time.perf_counter() - started, exc)
    stdout = completed.stdout.strip()
    try:
        payload = json.loads(stdout.splitlines()[-1]) if stdout else {}
    except Exception as exc:  # noqa: BLE001
        return subprocess_error_row(repo_root, task, "JSON_PARSE_ERROR", completed.returncode, time.perf_counter() - started, stdout, completed.stderr, str(exc))
    if completed.returncode != 0 and payload.get("status") == "OK":
        payload["status"] = "SUBPROCESS_NONZERO"
    payload.setdefault("subprocess_returncode", completed.returncode)
    if completed.stderr:
        payload.setdefault("subprocess_stderr_tail", tail_text(completed.stderr))
    return payload


def single_run_cli(repo_root: Path, args: argparse.Namespace) -> int:
    output_dir = Path(args.single_output_dir) if args.single_output_dir else repo_root / DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "solutions").mkdir(parents=True, exist_ok=True)
    flags = e2_alns_throughput_flags(route_cost_cache=True, repair_structure_cache=True, timing_ledger=False)
    row = run_one(
        repo_root,
        repo_root / BENCHMARK_ROOT / args.single_category / args.single_instance,
        str(args.single_category),
        str(args.single_instance),
        str(args.single_variant),
        int(args.single_seed),
        int(args.single_eval_budget),
        float(args.single_runtime_cap),
        output_dir,
        flags,
    )
    print(json.dumps(row, ensure_ascii=False, sort_keys=True))
    return 1 if row.get("status") in {"ERROR", "JSON_PARSE_ERROR", "SUBPROCESS_NONZERO"} else 0


def run_one(
    repo_root: Path,
    bundle_dir: Path,
    category: str,
    instance: str,
    variant: str,
    seed: int,
    eval_budget: int,
    runtime_cap_seconds: float,
    output_dir: Path,
    flags: dict[str, str],
) -> dict[str, Any]:
    started = time.perf_counter()
    prices = pilot_prices()
    row: dict[str, Any] = {
        "commit_hash": git_output(repo_root, "rev-parse", "--short", "HEAD"),
        "category": category,
        "instance": instance,
        "variant": variant,
        "seed": int(seed),
        "eval_budget": int(eval_budget),
        "runtime_cap_seconds": float(runtime_cap_seconds),
        "B_battery_kwh": float(prices.B_battery_kwh),
        "v_speed_ms": float(prices.v_speed_ms),
        "carbon_price": float(prices.carbon_price),
        "active_flags": json.dumps(flags, sort_keys=True),
    }
    try:
        with temporary_env(flags):
            result = run_alns_wouda(
                bundle_dir,
                iterations=None,
                seed=seed,
                eval_budget=eval_budget,
                max_runtime_seconds=runtime_cap_seconds,
                policy=policy_for_variant(variant),
                prices=prices,
            )
        bundle = load_search_bundle(bundle_dir)
        solution = result.best_solution
        metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices)
        violations = check_solution(solution, bundle.instance, prices)
        audit = charging_audit(solution, bundle.instance)
        solution_path = output_dir / "solutions" / solution_filename(category, instance, variant, seed, eval_budget)
        solution_path.write_text(
            json.dumps(
                {
                    "schema_version": "setp-09o-charging-solution.v1",
                    "category": category,
                    "instance": instance,
                    "variant": variant,
                    "seed": seed,
                    "eval_budget": eval_budget,
                    "prices": {
                        "B_battery_kwh": prices.B_battery_kwh,
                        "v_speed_ms": prices.v_speed_ms,
                        "carbon_price": prices.carbon_price,
                    },
                    "solution": solution_to_dict(solution),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        route_count = len(solution.routes)
        cv_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv")
        ev_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev")
        row.update(
            {
                "status": "OK" if not violations else "VIOLATION",
                "elapsed_seconds": time.perf_counter() - started,
                "actual_evals": int(result.evaluations),
                "best_penalized_obj": float(result.best_obj),
                "solver_reported_feasible": bool(result.feasible),
                "violation_count": len(violations),
                "station_capacity_violation_count": sum(1 for violation in violations if violation.type == STATION_CAPACITY),
                "route_count": route_count,
                "cv_route_count": cv_count,
                "ev_route_count": ev_count,
                "ev_route_share": ev_count / route_count if route_count else 0.0,
                "composition": classify_composition(cv_count, ev_count),
                "total_cost": float(metrics["total_cost"]),
                "cost_elec": float(metrics["cost_elec"]),
                "cost_occ": float(metrics["cost_occ"]),
                "depot_charging_kwh": float(metrics["depot_charging_kwh"]),
                "station_charging_kwh": float(metrics["station_charging_kwh"]),
                "solution_path": str(solution_path.relative_to(repo_root)),
                **audit,
            }
        )
    except Exception as exc:  # noqa: BLE001
        row.update(
            {
                "status": "ERROR",
                "elapsed_seconds": time.perf_counter() - started,
                "actual_evals": 0,
                "violation_count": -1,
                "station_capacity_violation_count": -1,
                "route_count": 0,
                "cv_route_count": 0,
                "ev_route_count": 0,
                "ev_route_share": 0.0,
                "composition": "error",
                "total_cost": float("inf"),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
    return row


def charging_audit(solution: Solution, instance: Any) -> dict[str, Any]:
    node_lookup = {node.node_id: node for node in instance.nodes}
    customer_count = sum(1 for node in instance.nodes if node.node_type.lower() == "c")
    route_types = {route.vehicle_id: route.vehicle_type.lower() for route in solution.routes}
    action_counts = {"d": 0, "f": 0}
    energy = {"d": 0.0, "f": 0.0}
    occupied: dict[tuple[str, int], set[str]] = {}
    slot_type_totals: dict[tuple[str, int], set[str]] = {}
    station_action_vehicle: dict[str, set[str]] = {}
    public_route_ids: set[str] = set()
    depot_route_ids: set[str] = set()
    for action in solution.charging_actions:
        node = node_lookup.get(action.station_id)
        if node is None or node.node_type.lower() not in {"d", "f"}:
            continue
        station_type = node.node_type.lower()
        action_counts[station_type] += 1
        energy[station_type] += float(action.energy_kwh)
        station_action_vehicle.setdefault(action.station_id, set()).add(action.vehicle_id)
        if station_type == "f":
            public_route_ids.add(action.vehicle_id)
        if station_type == "d":
            depot_route_ids.add(action.vehicle_id)
        for slot in charging_slot_breakdown(
            float(action.charge_start_second),
            float(action.occupancy_minutes) * 60.0,
            float(action.energy_kwh),
            instance,
            n_slots=48,
            cyclic=True,
        ):
            occupied.setdefault((action.station_id, slot.slot_index), set()).add(action.vehicle_id)
            slot_type_totals.setdefault((station_type, slot.slot_index), set()).add(action.vehicle_id)

    station_peaks: list[dict[str, Any]] = []
    for (station_id, slot_index), vehicles in occupied.items():
        node = node_lookup[station_id]
        capacity = station_capacity(node, customer_count)
        station_peaks.append(
            {
                "station_id": station_id,
                "station_type": node.node_type.lower(),
                "slot_index": int(slot_index),
                "occupied": len(vehicles),
                "capacity": capacity,
                "utilization": len(vehicles) / capacity if capacity else float("inf"),
            }
        )
    depot_peaks = [row for row in station_peaks if row["station_type"] == "d"]
    public_peaks = [row for row in station_peaks if row["station_type"] == "f"]
    depot_peak = max(depot_peaks, key=lambda row: (row["occupied"], row["utilization"], row["station_id"]), default={})
    public_peak = max(public_peaks, key=lambda row: (row["occupied"], row["utilization"], row["station_id"]), default={})
    total_depot_peak = max((len(vehicles) for (kind, _slot), vehicles in slot_type_totals.items() if kind == "d"), default=0)
    total_public_peak = max((len(vehicles) for (kind, _slot), vehicles in slot_type_totals.items() if kind == "f"), default=0)
    total_charging = energy["d"] + energy["f"]
    ev_routes = {route.vehicle_id for route in solution.routes if route.vehicle_type.lower() == "ev"}
    return {
        "charging_action_count": sum(action_counts.values()),
        "depot_action_count": action_counts["d"],
        "public_action_count": action_counts["f"],
        "depot_charging_kwh_audit": energy["d"],
        "public_charging_kwh_audit": energy["f"],
        "depot_charging_energy_share": energy["d"] / total_charging if total_charging else 0.0,
        "public_charging_energy_share": energy["f"] / total_charging if total_charging else 0.0,
        "ev_routes_with_depot_charge": len(depot_route_ids & ev_routes),
        "ev_routes_with_public_charge": len(public_route_ids & ev_routes),
        "public_charge_ev_route_share": len(public_route_ids & ev_routes) / len(ev_routes) if ev_routes else 0.0,
        "depot_peak_concurrent_at_one_depot": depot_peak.get("occupied", 0),
        "depot_peak_station_id": depot_peak.get("station_id", ""),
        "depot_peak_slot": depot_peak.get("slot_index", ""),
        "depot_peak_capacity": depot_peak.get("capacity", ""),
        "depot_peak_utilization": depot_peak.get("utilization", ""),
        "depot_peak_headroom": (depot_peak.get("capacity", 0) - depot_peak.get("occupied", 0)) if depot_peak else "",
        "total_depot_peak_concurrent_all_depots": total_depot_peak,
        "public_peak_concurrent_at_one_station": public_peak.get("occupied", 0),
        "public_peak_station_id": public_peak.get("station_id", ""),
        "public_peak_slot": public_peak.get("slot_index", ""),
        "public_peak_capacity": public_peak.get("capacity", ""),
        "public_peak_utilization": public_peak.get("utilization", ""),
        "total_public_peak_concurrent_all_stations": total_public_peak,
        "depot_station_slots_at_capacity": sum(1 for row in depot_peaks if row["occupied"] >= row["capacity"]),
        "public_station_slots_at_capacity": sum(1 for row in public_peaks if row["occupied"] >= row["capacity"]),
        "station_slots_over_capacity": sum(1 for row in station_peaks if row["occupied"] > row["capacity"]),
        "unique_depot_charge_stations": len({row["station_id"] for row in depot_peaks}),
        "unique_public_charge_stations": len({row["station_id"] for row in public_peaks}),
        "station_charge_vehicle_count_max": max((len(vehicles) for vehicles in station_action_vehicle.values()), default=0),
    }


def station_capacity(node: Any, customer_count: int) -> int:
    if node.station_chargers is not None:
        return int(node.station_chargers)
    if node.node_type.lower() == "d":
        return max(1, int(customer_count))
    if node.node_type.lower() == "f":
        return 1
    return 0


def policy_for_variant(variant: str) -> SearchPolicy:
    if variant == "free_mixed":
        return SearchPolicy(require_charging_signal=False)
    if variant == "ev_shell":
        return SearchPolicy(require_charging_signal=False, max_cv=0)
    if variant == "cv_shell":
        return SearchPolicy(require_charging_signal=False, max_ev=0)
    raise ValueError(f"unknown variant: {variant}")


def winner_rows_from_raw(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["category"]), str(row["instance"]), int(row["seed"])), []).append(row)
    winners: list[dict[str, Any]] = []
    for (category, instance, seed), candidates in sorted(grouped.items()):
        feasible = [row for row in candidates if row.get("status") == "OK" and int(row.get("violation_count", 999)) == 0]
        if not feasible:
            winners.append({"category": category, "instance": instance, "seed": seed, "winner_status": "NO_FEASIBLE_ROW"})
            continue
        best = min(feasible, key=lambda row: float(row["total_cost"]))
        winners.append(
            {
                "category": category,
                "instance": instance,
                "seed": seed,
                "winner_status": "OK",
                "winner_variant": best["variant"],
                "winner_total_cost": float(best["total_cost"]),
                "winner_composition": best["composition"],
                "winner_cv_route_count": int(best["cv_route_count"]),
                "winner_ev_route_count": int(best["ev_route_count"]),
                "winner_ev_route_share": float(best["ev_route_share"]),
                "winner_depot_charging_energy_share": float(best.get("depot_charging_energy_share", 0.0)),
                "winner_public_charging_energy_share": float(best.get("public_charging_energy_share", 0.0)),
                "winner_ev_routes_with_public_charge": int(best.get("ev_routes_with_public_charge", 0)),
                "winner_depot_peak_concurrent_at_one_depot": int(best.get("depot_peak_concurrent_at_one_depot", 0)),
                "winner_depot_peak_capacity": best.get("depot_peak_capacity", ""),
                "winner_depot_peak_headroom": best.get("depot_peak_headroom", ""),
                "winner_public_peak_concurrent_at_one_station": int(best.get("public_peak_concurrent_at_one_station", 0)),
                "winner_public_station_slots_at_capacity": int(best.get("public_station_slots_at_capacity", 0)),
                "solution_path": best.get("solution_path", ""),
            }
        )
    return winners


def summarize_conclusion(
    metadata: dict[str, Any],
    instance_rows: list[dict[str, Any]],
    raw_rows: list[dict[str, Any]],
    winner_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = len(metadata["instances"]) * len(metadata["seeds"]) * len(metadata["variants"])
    failures = [row for row in raw_rows if row.get("status") not in {"OK", "VIOLATION"}]
    ok_rows = [row for row in raw_rows if row.get("status") == "OK"]
    ok_winners = [row for row in winner_rows if row.get("winner_status") == "OK"]
    if metadata.get("phase0_only"):
        verdict = "PHASE0_ONLY"
        interpretation = "Only instance charger structure was audited; no optimization rows were run."
    elif len(raw_rows) < expected or failures or not ok_winners:
        verdict = "HALT_COLLECTION_COST"
        interpretation = "The pilot did not collect a complete auditable set; do not infer charging-infrastructure causality."
        if ok_rows:
            mean_depot_share = mean(float(row.get("depot_charging_energy_share", 0.0)) for row in ok_rows)
            mean_public_share = mean(float(row.get("public_charging_energy_share", 0.0)) for row in ok_rows)
            max_peak = max(float(row.get("depot_peak_concurrent_at_one_depot", 0.0)) for row in ok_rows)
            public_routes = sum(int(float(row.get("ev_routes_with_public_charge", 0) or 0)) for row in ok_rows)
            interpretation += (
                f" Under the HALT, the {len(ok_rows)} completed OK row(s) are still useful as a clue: "
                f"mean depot charging energy share={mean_depot_share:.3f}, mean public charging energy share={mean_public_share:.3f}, "
                f"max one-depot concurrent charging={max_peak:.0f}, EV routes using public charging={public_routes}. "
                "That points to depot charging capacity as the next hypothesis to evidence-check, not to public fast-charger scarcity."
            )
    else:
        mean_depot_share = mean(float(row.get("depot_charging_energy_share", 0.0)) for row in ok_rows)
        mean_public_share = mean(float(row.get("public_charging_energy_share", 0.0)) for row in ok_rows)
        mean_depot_peak = mean(float(row.get("depot_peak_concurrent_at_one_depot", 0.0)) for row in ok_rows)
        max_headroom = max(float_or_nan(row.get("depot_peak_headroom", "")) for row in ok_rows)
        if mean_depot_share >= 0.75 and mean_public_share <= 0.25:
            verdict = "DEPOT_CHARGING_CAPACITY_CANDIDATE_PILOT"
            interpretation = (
                "This small pilot says the tested EV-heavy solutions mainly rely on depot charging, while current depot charger counts are generated as a route-count upper bound. "
                "It is a candidate for a formal evidence-backed depot-capacity gate, not yet a model conclusion."
            )
        elif mean_public_share >= 0.25:
            verdict = "PUBLIC_CHARGING_SCARCITY_CANDIDATE_PILOT"
            interpretation = (
                "This small pilot says public charging is materially involved; public-station availability/scarcity deserves the next formal gate."
            )
        else:
            verdict = "CHARGING_CAPACITY_NOT_PRIMARY_IN_PILOT"
            interpretation = (
                "This small pilot did not show charging infrastructure as the obvious primary driver; look harder at capital budgets or route eligibility before formalizing charger caps."
            )
        interpretation += f" Mean one-depot peak concurrency in OK rows is {mean_depot_peak:.2f}; max generated-capacity headroom at a depot peak is {max_headroom:.2f}."
    return {
        "verdict": verdict,
        "expected_raw_rows": expected,
        "raw_rows": len(raw_rows),
        "ok_raw_rows": len(ok_rows),
        "failure_rows": len(failures),
        "winner_rows": len(ok_winners),
        "pilot_instance_count": len(instance_rows),
        "interpretation": interpretation,
        "ok_row_mean_depot_charging_energy_share": mean(float(row.get("depot_charging_energy_share", 0.0)) for row in ok_rows) if ok_rows else "",
        "ok_row_mean_public_charging_energy_share": mean(float(row.get("public_charging_energy_share", 0.0)) for row in ok_rows) if ok_rows else "",
        "ok_row_max_depot_peak_concurrent_at_one_depot": max((float(row.get("depot_peak_concurrent_at_one_depot", 0.0)) for row in ok_rows), default=""),
        "ok_row_ev_routes_with_public_charge_total": sum(int(float(row.get("ev_routes_with_public_charge", 0) or 0)) for row in ok_rows) if ok_rows else "",
    }


def render_report(
    metadata: dict[str, Any],
    instance_rows: list[dict[str, Any]],
    raw_rows: list[dict[str, Any]],
    winner_rows: list[dict[str, Any]],
    conclusion: dict[str, Any],
) -> str:
    lines = [
        "# 09o Charging-Infrastructure Operational Pilot",
        "",
        f"Commit: `{metadata['commit_hash'][:8]}`.",
        f"Python: `{metadata['python']}`; NumPy: `{metadata['numpy']}`.",
        f"Prices used by in-memory override: `B_battery_kwh={metadata['B_battery_kwh']}`, `v_speed_ms={metadata['v_speed_ms']}`, `carbon_price={metadata['carbon_price']}`.",
        f"Command: `{metadata['command']}`.",
        "",
        "## Verdict",
        "",
        f"`{conclusion['verdict']}`.",
        "",
        conclusion["interpretation"],
        "",
        "This is a pilot after 09n, not a formal parameter/model change. It freezes generated bundles and solver semantics.",
        "",
        "## Plain-Language Reading",
        "",
        "The full mini-batch did not pass because every `ev_shell` row timed out. So the honest status is still HALT, not proof. But the successful `free_mixed` rows all say the same thing: at 280kWh, the solver can build many-EV solutions without using public charging at all; it charges EVs at depots, and the generated depot charger counts are very large compared with observed peak concurrency. This makes depot charging capacity or depot charging capital the next cleaner hypothesis. Public fast-charger scarcity is lower priority for this specific mechanism, because the completed rows used zero public charging.",
        "",
        "## Why This Was Tested",
        "",
        "09n showed that directly capping vehicle route counts through `SearchPolicy` is too blunt: original Goeke/ReSETP fleet counts make many runs infeasible or too CV-light, while unbounded 280kWh winners can use many EV routes. The next plausible operational mechanism is charging infrastructure. Existing code already checks station capacity: public stations normally have one charger, while depots are generated with `customer_count_route_upper_bound` chargers. This pilot asks whether EV-heavy solutions are mostly leaning on that generous depot-charging assumption.",
        "",
        "## Instance Charger Structure",
        "",
        "| instance | depots | public stations | depot chargers | public chargers | metadata policy |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in instance_rows:
        lines.append(
            f"| {row['category']}/{row['instance']} | {row.get('depot_count', '')} | {row.get('public_station_count', '')} | "
            f"{row.get('depot_chargers_min', '')}-{row.get('depot_chargers_max', '')} | "
            f"{row.get('public_chargers_min', '')}-{row.get('public_chargers_max', '')} | "
            f"{row.get('metadata_depot_chargers_policy', '')} |"
        )
    lines.extend(["", "## Raw Optimization Rows", ""])
    if raw_rows:
        lines.append("| instance | variant | status | CV | EV | EV share | cost | depot kWh share | public kWh share | peak depot concurrent | public routes |")
        lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for row in raw_rows:
            lines.append(
                f"| {row['category']}/{row['instance']} | {row['variant']} | {row['status']} | "
                f"{row.get('cv_route_count', '')} | {row.get('ev_route_count', '')} | {fmt(row.get('ev_route_share'))} | "
                f"{fmt(row.get('total_cost'))} | {fmt(row.get('depot_charging_energy_share'))} | "
                f"{fmt(row.get('public_charging_energy_share'))} | {row.get('depot_peak_concurrent_at_one_depot', '')} | "
                f"{row.get('ev_routes_with_public_charge', '')} |"
            )
    else:
        lines.append("No optimization rows were run.")
    lines.extend(["", "## Winners", ""])
    if winner_rows:
        lines.append("| instance | winner | composition | EV share | depot kWh share | public kWh share | peak depot concurrent | depot peak cap | public routes |")
        lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|")
        for row in winner_rows:
            if row.get("winner_status") != "OK":
                lines.append(f"| {row['category']}/{row['instance']} | HALT | {row['winner_status']} |  |  |  |  |  |  |")
                continue
            lines.append(
                f"| {row['category']}/{row['instance']} | {row['winner_variant']} | {row['winner_composition']} | "
                f"{fmt(row['winner_ev_route_share'])} | {fmt(row['winner_depot_charging_energy_share'])} | "
                f"{fmt(row['winner_public_charging_energy_share'])} | {row['winner_depot_peak_concurrent_at_one_depot']} | "
                f"{row['winner_depot_peak_capacity']} | {row['winner_ev_routes_with_public_charge']} |"
            )
    else:
        lines.append("No winners were selected.")
    lines.extend(
        [
            "",
            "## Output Files",
            "",
            f"- `{metadata['output_dir']}/metadata.json`",
            f"- `{metadata['output_dir']}/pilot_instance_structure.csv`",
            f"- `{metadata['output_dir']}/all_focus_instance_structure.csv`",
            f"- `{metadata['output_dir']}/raw_runs.csv`",
            f"- `{metadata['output_dir']}/winners.csv`",
            f"- `{metadata['output_dir']}/solutions/*.json`",
            f"- `{metadata['output_dir']}/conclusion.json`",
            "",
            "## Next Rule",
            "",
            "If this pilot points to depot charging capacity, the next step should not be another ad hoc cap. It should first collect source evidence for depot charger counts or charging-capital budgets, then run a formal 75-200 stability gate with an explicit, switchable operational constraint. If this pilot times out or stays ambiguous, keep the result as a clue only and do not update TeX or defaults.",
            "",
        ]
    )
    return "\n".join(lines)


def timeout_row(repo_root: Path, task: dict[str, Any], timeout: float, elapsed: float, exc: subprocess.TimeoutExpired) -> dict[str, Any]:
    return {
        "commit_hash": git_output(repo_root, "rev-parse", "--short", "HEAD"),
        **task,
        "status": "TIMEOUT",
        "elapsed_seconds": float(elapsed),
        "task_timeout_seconds": float(timeout),
        "B_battery_kwh": BATTERY_KWH,
        "v_speed_ms": DEFAULT_PRICES.v_speed_ms,
        "carbon_price": CARBON_PRICE,
        "route_count": 0,
        "cv_route_count": 0,
        "ev_route_count": 0,
        "ev_route_share": 0.0,
        "composition": "timeout",
        "total_cost": float("inf"),
        "subprocess_stdout_tail": tail_text(exc.stdout),
        "subprocess_stderr_tail": tail_text(exc.stderr),
    }


def subprocess_error_row(
    repo_root: Path,
    task: dict[str, Any],
    status: str,
    returncode: int,
    elapsed: float,
    stdout: str,
    stderr: str,
    error: str,
) -> dict[str, Any]:
    return {
        "commit_hash": git_output(repo_root, "rev-parse", "--short", "HEAD"),
        **task,
        "status": status,
        "elapsed_seconds": float(elapsed),
        "B_battery_kwh": BATTERY_KWH,
        "v_speed_ms": DEFAULT_PRICES.v_speed_ms,
        "carbon_price": CARBON_PRICE,
        "subprocess_returncode": int(returncode),
        "route_count": 0,
        "cv_route_count": 0,
        "ev_route_count": 0,
        "ev_route_share": 0.0,
        "composition": "error",
        "total_cost": float("inf"),
        "subprocess_stdout_tail": tail_text(stdout),
        "subprocess_stderr_tail": tail_text(stderr),
        "error": error,
    }


def load_completed_rows(output_dir: Path, *, retry_timeouts: bool) -> dict[tuple[str, str, int, str, int], dict[str, Any]]:
    completed: dict[tuple[str, str, int, str, int], dict[str, Any]] = {}
    for name in ("raw_runs.csv", "raw_runs.partial.csv"):
        path = output_dir / name
        if not path.exists() or path.stat().st_size == 0:
            continue
        for row in read_csv(path):
            if row.get("status") == "TIMEOUT" and retry_timeouts:
                continue
            if row.get("status") in TERMINAL_STATUSES:
                completed[task_key(row)] = row
    return completed


def task_key(row: dict[str, Any]) -> tuple[str, str, int, str, int]:
    return (str(row["category"]), str(row["instance"]), int(row["seed"]), str(row["variant"]), int(row["eval_budget"]))


def sorted_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (str(row.get("category", "")), str(row.get("instance", "")), int(row.get("seed", 0)), variant_index(str(row.get("variant", "")))))


def variant_index(variant: str) -> int:
    try:
        return VARIANT_ORDER.index(variant)
    except ValueError:
        return len(VARIANT_ORDER)


def classify_composition(cv_count: int, ev_count: int) -> str:
    total = int(cv_count) + int(ev_count)
    if total <= 0:
        return "empty"
    if ev_count == 0:
        return "all_cv"
    if cv_count == 0:
        return "all_ev"
    ev_share = ev_count / total
    cv_share = cv_count / total
    if ev_share >= 0.80:
        return "ev_heavy_mixed"
    if cv_share >= 0.80:
        return "cv_heavy_mixed"
    return "balanced_mixed"


def runtime_cap(instance: str, args: argparse.Namespace) -> float:
    n = customer_count(instance)
    if n >= 150:
        return float(args.runtime_cap_large)
    if n >= 100:
        return float(args.runtime_cap_medium)
    return float(args.runtime_cap_small)


def customer_count(instance: str) -> int:
    match = re.search(r"-(\d+)c-", instance)
    return int(match.group(1)) if match else 0


def replicate_id(instance: str) -> int:
    match = re.search(r"-(\d+)$", instance)
    return int(match.group(1)) if match else 0


def solution_filename(category: str, instance: str, variant: str, seed: int, eval_budget: int) -> str:
    return f"{category}__{instance}__{variant}__seed{seed}__eval{eval_budget}.json"


def mean(values: Iterable[float]) -> float:
    items = [float(value) for value in values]
    return sum(items) / len(items) if items else float("nan")


def float_or_nan(value: Any) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return float("nan")


def fmt(value: Any) -> str:
    try:
        val = float(value)
    except Exception:  # noqa: BLE001
        return "" if value is None else str(value)
    if val == float("inf"):
        return "inf"
    return f"{val:.3f}"


def tail_text(value: Any, limit: int = 2000) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    return text[-limit:]


def git_output(repo_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(["git", *args], cwd=repo_root, text=True, capture_output=True, check=False)
        return completed.stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return f"GIT_ERROR:{exc}"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def temporary_env(flags: dict[str, str]):
    class _Env:
        def __enter__(self) -> None:
            self.old = {key: os.environ.get(key) for key in flags}
            for key, value in flags.items():
                os.environ[key] = str(value)

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            for key, value in self.old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    return _Env()


if __name__ == "__main__":
    raise SystemExit(main())
