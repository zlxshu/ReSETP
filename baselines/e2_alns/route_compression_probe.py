#!/usr/bin/env python3
"""Hard-subset route-compression probe for the E2 ALNS closeout.

This is a diagnostic probe, not a formal T3 rerun. It reuses the existing
E2 final-closure task runner, reads A0/LNS from the closed Tier1 material, and
only runs the hard subset for explicit RELAXED_ROUTE_COMPRESSION profiles.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "solver/src", REPO_ROOT / "models/src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.metaheuristic_baselines import solution_from_dict, solution_to_dict
from setp_solver.search.winner_operators import WinnerKernelConfig, run_e2_alns_throughput, run_winner_kernel

from baselines.e2_alns import e2_final_closure as fc


OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/route_compression_probe_20260705"
SOURCE_DIR = REPO_ROOT / "baselines/e2_alns/e2_final_closure_20260703/phase_d_g5_t3_material"
SOURCE_DECISION = REPO_ROOT / "baselines/e2_alns/e2_final_closure_20260703/decision.json"
SOURCE_TABLE = SOURCE_DIR / "t3_table_material.csv"
SOURCE_RAW = SOURCE_DIR / "raw_runs.csv"
INSTANCE_ROOT = REPO_ROOT / "models/data_bundle/generated_instances/e2_benchmark"
GOEKE_BUNDLE = REPO_ROOT / "models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113"
THREESHIFT_BUNDLE = INSTANCE_ROOT / "threeshift/e2-threeshift-150c-01"

GOLD_PYTHON = "/opt/anaconda3/bin/python3.13"
GOLD_NUMPY = "2.3.5"
EXPECTED_GO_EKE_CURRENT_COST = 2677.7953638343815
EXPECTED_THREESHIFT_280_COST = 3561.080964207054
CARBON_PRICE = 0.05034
DIAGNOSTIC_BATTERY_KWH = 280.0

LNS_DISPLAY = "LNS"
A0_DISPLAY = "alns_e2_throughput+LOCAL_SEARCH"
A1_DISPLAY = "alns_e2_throughput+RELAXED_ROUTE_COMPRESSION"
A2_DISPLAY = "alns_e2_throughput+RELAXED_ROUTE_COMPRESSION+LOCAL_SEARCH"
PROFILE_BY_DISPLAY = {
    LNS_DISPLAY: "LNS_REFERENCE",
    A0_DISPLAY: "A0_CURRENT",
    A1_DISPLAY: "A1_RELAXED_ROUTE_COMPRESSION",
    A2_DISPLAY: "A2_RELAXED_ROUTE_COMPRESSION_LOCAL_SEARCH",
}
ALNS_PROFILES = (
    "A0_CURRENT",
    "A1_RELAXED_ROUTE_COMPRESSION",
    "A2_RELAXED_ROUTE_COMPRESSION_LOCAL_SEARCH",
)
USER_PROTECTED_PATHS = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
    "solver/src/setp_solver/prices.py",
    "docs/paper_submission_final/paper_main.tex",
)
HASH_EXCLUDE_NAMES = {"artifact_hashes.json", ".DS_Store"}
HASH_EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".tasks"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--eval-budget", type=int, default=16000)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-runs", action="store_true")
    parser.add_argument("--skip-anchors", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = fc.repo_path(Path(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    clean_artifact_dir(output_dir)

    metadata = build_metadata(args, output_dir)
    fc.write_json(output_dir / "metadata.json", metadata)

    source_decision = fc.read_json(SOURCE_DECISION)
    t3_rows = fc.read_csv(SOURCE_TABLE)
    source_raw = fc.read_csv(SOURCE_RAW)
    preflight = preflight_checks(source_decision, t3_rows, source_raw)
    fc.write_json(output_dir / "preflight.json", preflight)

    hard_subset, current_summary = hard_subset_from_table(t3_rows)
    fc.write_csv(output_dir / "hard_subset_instances.csv", hard_subset)

    seed_source_rows(output_dir, source_raw, hard_subset, force=args.force)
    initial_raw_rows = fc.read_csv(output_dir / "raw_runs.csv")
    initial_cost_rows = cost_decomposition(initial_raw_rows, hard_subset)
    initial_root_cause = root_cause_summary(initial_cost_rows)
    if not initial_root_cause.get("route_fixed_cost_supported"):
        fc.write_csv(output_dir / "cost_decomposition.csv", initial_cost_rows)
        hard_subset = enrich_hard_subset_with_root_cause(hard_subset, initial_cost_rows)
        fc.write_csv(output_dir / "hard_subset_instances.csv", hard_subset)
        profile_rows = profile_summary(initial_cost_rows, anchors={}, root_cause=initial_root_cause)
        fc.write_csv(output_dir / "profile_summary.csv", profile_rows)
        fc.write_json(output_dir / "root_cause_summary.json", initial_root_cause)
        decision = halt_root_cause_decision(metadata, preflight, current_summary, hard_subset, initial_cost_rows, profile_rows)
        fc.write_json(output_dir / "decision.json", decision)
        write_report(output_dir, metadata, decision, current_summary, hard_subset, profile_rows)
        write_hashes(output_dir)
        print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    if not preflight["can_continue"]:
        fc.write_csv(output_dir / "cost_decomposition.csv", initial_cost_rows)
        hard_subset = enrich_hard_subset_with_root_cause(hard_subset, initial_cost_rows)
        fc.write_csv(output_dir / "hard_subset_instances.csv", hard_subset)
        profile_rows = profile_summary(initial_cost_rows, anchors={}, root_cause=initial_root_cause)
        fc.write_csv(output_dir / "profile_summary.csv", profile_rows)
        fc.write_json(output_dir / "root_cause_summary.json", initial_root_cause)
        decision = halt_root_cause_decision(metadata, preflight, current_summary, hard_subset, initial_cost_rows, profile_rows)
        fc.write_json(output_dir / "decision.json", decision)
        write_report(output_dir, metadata, decision, current_summary, hard_subset, profile_rows)
        write_hashes(output_dir)
        print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    tasks = build_probe_tasks(output_dir, hard_subset, parse_seeds(args.seeds), int(args.eval_budget))
    if not args.skip_runs:
        fc.run_tasks(output_dir, tasks, workers=int(args.workers), force=bool(args.force))

    raw_rows = fc.read_csv(output_dir / "raw_runs.csv")
    cost_rows = cost_decomposition(raw_rows, hard_subset)
    fc.write_csv(output_dir / "cost_decomposition.csv", cost_rows)
    hard_subset = enrich_hard_subset_with_root_cause(hard_subset, cost_rows)
    fc.write_csv(output_dir / "hard_subset_instances.csv", hard_subset)
    root_cause = root_cause_summary(cost_rows)
    fc.write_json(output_dir / "root_cause_summary.json", root_cause)

    anchors = {} if args.skip_anchors else run_anchor_parity()
    fc.write_json(output_dir / "anchor_parity.json", anchors)

    profile_rows = profile_summary(cost_rows, anchors=anchors, root_cause=root_cause)
    fc.write_csv(output_dir / "profile_summary.csv", profile_rows)

    decision = decide(metadata, preflight, current_summary, hard_subset, cost_rows, profile_rows, root_cause, anchors)
    fc.write_json(output_dir / "decision.json", decision)
    write_report(output_dir, metadata, decision, current_summary, hard_subset, profile_rows)
    write_hashes(output_dir)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision["verdict"] in {"ROUTE_COMPRESSION_FIX_SUPPORTED", "ROUTE_COMPRESSION_FIX_NOT_SUPPORTED"} else 2


def build_metadata(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    return {
        "schema": "setp-e2-route-compression-probe.v1",
        "task": "E2 ALNS hard-subset route-compression fix/probe",
        "boundary": "diagnostic hard subset only; not formal T3; no TeX write",
        "head": fc.git_head(),
        "python": sys.executable,
        "numpy": fc.numpy_version(),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", ""),
        "output_dir": fc.rel(output_dir),
        "source_decision": fc.rel(SOURCE_DECISION),
        "source_table": fc.rel(SOURCE_TABLE),
        "source_raw": fc.rel(SOURCE_RAW),
        "eval_budget": int(args.eval_budget),
        "seeds": parse_seeds(args.seeds),
        "workers": int(args.workers),
        "protected_paths": list(USER_PROTECTED_PATHS),
        "started_at_epoch": time.time(),
    }


def preflight_checks(source_decision: dict[str, Any], t3_rows: list[dict[str, str]], source_raw: list[dict[str, str]]) -> dict[str, Any]:
    verdict = source_decision.get("final_material_verdict")
    display_algorithms = {row.get("display_algorithm") for row in t3_rows}
    raw_algorithms = {row.get("display_algorithm") for row in source_raw}
    failures: list[dict[str, Any]] = []
    if verdict != "T3_MATERIAL_READY":
        failures.append({"failure": "source_not_t3_material_ready", "actual": verdict})
    if A0_DISPLAY not in display_algorithms:
        failures.append({"failure": "a0_display_missing_from_t3_table", "expected": A0_DISPLAY})
    if LNS_DISPLAY not in display_algorithms:
        failures.append({"failure": "lns_missing_from_t3_table"})
    if A0_DISPLAY not in raw_algorithms:
        failures.append({"failure": "a0_display_missing_from_raw", "expected": A0_DISPLAY})
    if LNS_DISPLAY not in raw_algorithms:
        failures.append({"failure": "lns_missing_from_raw"})
    if protected_diff():
        failures.append({"failure": "protected_file_diff", "paths": protected_diff()})
    return {
        "schema": "setp-e2-route-compression-preflight.v1",
        "source_final_material_verdict": verdict,
        "a0_display": A0_DISPLAY,
        "source_t3_rows": len(t3_rows),
        "source_raw_rows": len(source_raw),
        "failure_count": len(failures),
        "failures": failures,
        "can_continue": not failures,
    }


def hard_subset_from_table(t3_rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    table: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in t3_rows:
        table[(str(row.get("category")), str(row.get("instance")), str(row.get("display_algorithm")))] = row
    instances = sorted({(row.get("category"), row.get("instance")) for row in t3_rows})
    rows: list[dict[str, Any]] = []
    gaps: list[float] = []
    wins = losses = ties = 0
    for category, instance in instances:
        if not category or not instance:
            continue
        a0 = table.get((category, instance, A0_DISPLAY))
        lns = table.get((category, instance, LNS_DISPLAY))
        if not a0 or not lns:
            continue
        a0_mean = as_float(a0.get("mean_best_cost"))
        lns_mean = as_float(lns.get("mean_best_cost"))
        gap = safe_ratio(lns_mean - a0_mean, lns_mean)
        gaps.append(gap)
        if gap > 1e-12:
            wins += 1
        elif gap < -1e-12:
            losses += 1
            rows.append(
                {
                    "category": category,
                    "instance": instance,
                    "a0_display_algorithm": A0_DISPLAY,
                    "lns_mean_best_cost": lns_mean,
                    "a0_mean_best_cost": a0_mean,
                    "gap_vs_lns": gap,
                    "gap_pct_vs_lns": gap * 100.0,
                    "reason": "A0 loses to LNS in current Tier1 material",
                }
            )
        else:
            ties += 1
    summary = {
        "schema": "setp-e2-route-compression-current-summary.v1",
        "total_instances": len(gaps),
        "alns_wins_vs_lns": wins,
        "alns_losses_vs_lns": losses,
        "alns_ties_vs_lns": ties,
        "mean_gap_vs_lns": mean(gaps),
        "median_gap_vs_lns": median(gaps),
        "hard_subset_count": len(rows),
        "hard_subset_instances": [f"{row['category']}/{row['instance']}" for row in rows],
    }
    return rows, summary


def seed_source_rows(output_dir: Path, source_raw: list[dict[str, str]], hard_subset: list[dict[str, Any]], *, force: bool) -> None:
    hard_keys = {(row["category"], row["instance"]) for row in hard_subset}
    source_keep: list[dict[str, Any]] = []
    for row in source_raw:
        key = (row.get("category"), row.get("instance"))
        display = row.get("display_algorithm")
        if key in hard_keys and display in {LNS_DISPLAY, A0_DISPLAY}:
            copied = dict(row)
            copied["probe_profile"] = PROFILE_BY_DISPLAY[display]
            copied["probe_source"] = "existing_phase_d_tier1"
            source_keep.append(copied)
    raw_path = output_dir / "raw_runs.csv"
    existing = [] if force else fc.read_csv(raw_path)
    by_run_id = {str(row.get("run_id")): row for row in existing if row.get("run_id")}
    for row in source_keep:
        by_run_id[str(row.get("run_id"))] = row
    fc.write_csv(raw_path, fc.sorted_rows(list(by_run_id.values())))


def build_probe_tasks(output_dir: Path, hard_subset: list[dict[str, Any]], seeds: list[int], eval_budget: int) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for row in hard_subset:
        category = str(row["category"])
        instance = str(row["instance"])
        for seed in seeds:
            tasks.append(
                fc.make_task(
                    phase="ROUTE_COMPRESSION_PROBE",
                    phase_dir=output_dir,
                    category=category,
                    instance=instance,
                    algorithm="alns_component_RELAXED_ROUTE_COMPRESSION",
                    seed=int(seed),
                    eval_budget=int(eval_budget),
                    runtime_cap_seconds=fc.runtime_cap_for_instance(instance),
                    scenario_type="formal_goeke80",
                    components=["RELAXED_ROUTE_COMPRESSION"],
                )
            )
            tasks.append(
                fc.make_task(
                    phase="ROUTE_COMPRESSION_PROBE",
                    phase_dir=output_dir,
                    category=category,
                    instance=instance,
                    algorithm="alns_component_stack",
                    seed=int(seed),
                    eval_budget=int(eval_budget),
                    runtime_cap_seconds=fc.runtime_cap_for_instance(instance),
                    scenario_type="formal_goeke80",
                    components=["RELAXED_ROUTE_COMPRESSION", "LOCAL_SEARCH"],
                )
            )
    return tasks


def cost_decomposition(raw_rows: list[dict[str, str]], hard_subset: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hard_keys = {(row["category"], row["instance"]) for row in hard_subset}
    profile_rows: list[dict[str, Any]] = []
    bundle_cache: dict[tuple[str, str], Any] = {}
    for row in raw_rows:
        key = (str(row.get("category")), str(row.get("instance")))
        if key not in hard_keys:
            continue
        profile = PROFILE_BY_DISPLAY.get(str(row.get("display_algorithm")))
        if not profile:
            continue
        profile_rows.append(decomposition_row(row, profile, bundle_cache))

    lns_by_key = {
        (row["category"], row["instance"], int(row["seed"])): row
        for row in profile_rows
        if row["profile"] == "LNS_REFERENCE" and math.isfinite(as_float(row.get("total_cost")))
    }
    out: list[dict[str, Any]] = []
    delta_fields = (
        "total_cost",
        "route_count",
        "cost_fix",
        "cost_km",
        "cost_fuel",
        "cost_elec",
        "cost_occ",
        "cost_carbon",
        "E_total",
        "distance_total",
        "electricity_kwh",
    )
    for row in profile_rows:
        paired = lns_by_key.get((row["category"], row["instance"], int(row["seed"])))
        enriched = dict(row)
        if paired:
            for field in delta_fields:
                enriched[f"delta_vs_lns_{field}"] = as_float(row.get(field)) - as_float(paired.get(field))
            enriched["gap_vs_lns"] = safe_ratio(as_float(paired.get("total_cost")) - as_float(row.get("total_cost")), as_float(paired.get("total_cost")))
        out.append(enriched)
    return fc.sorted_rows(out)


def decomposition_row(row: dict[str, str], profile: str, bundle_cache: dict[tuple[str, str], Any]) -> dict[str, Any]:
    category = str(row.get("category"))
    instance = str(row.get("instance"))
    key = (category, instance)
    if key not in bundle_cache:
        bundle_cache[key] = load_search_bundle(INSTANCE_ROOT / category / instance)
    bundle = bundle_cache[key]
    base = {
        "category": category,
        "instance": instance,
        "profile": profile,
        "algorithm": row.get("algorithm", ""),
        "display_algorithm": row.get("display_algorithm", ""),
        "seed": int(as_float(row.get("seed"), 0)),
        "run_id": row.get("run_id", ""),
        "status": row.get("status", ""),
        "gate_status": row.get("gate_status", ""),
        "eval_budget": int(as_float(row.get("eval_budget"), 0)),
        "actual_evals": int(as_float(row.get("actual_evals"), 0)),
        "raw_best_cost": as_float(row.get("best_cost")),
        "raw_route_count": int(as_float(row.get("route_count"), 0)),
        "raw_feasible": row.get("feasible", ""),
        "identity_cluster_class": row.get("identity_cluster_class", ""),
    }
    if not row.get("solution_json"):
        return {**base, "replay_status": "MISSING_SOLUTION_JSON", "replay_violation_count": -1}
    try:
        solution = solution_from_dict(json.loads(str(row.get("solution_json"))))
        violations = check_solution(solution, bundle.instance, DEFAULT_PRICES)
        metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, DEFAULT_PRICES)
    except Exception as exc:
        return {**base, "replay_status": "REPLAY_EXCEPTION", "replay_error": repr(exc), "replay_violation_count": -1}
    out = {
        **base,
        "replay_status": "OK" if not violations else "REPLAY_INFEASIBLE",
        "replay_violation_count": len(violations),
        "total_cost": metrics["total_cost"],
        "best_cost_abs_diff": abs(metrics["total_cost"] - as_float(row.get("best_cost"))),
        "route_count": len(solution.routes),
        "cv_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv"),
        "ev_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev"),
    }
    for field in (
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
    ):
        out[field] = metrics.get(field, math.nan)
    return out


def enrich_hard_subset_with_root_cause(hard_subset: list[dict[str, Any]], cost_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_instance: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in cost_rows:
        if row.get("profile") == "A0_CURRENT":
            by_instance.setdefault((row["category"], row["instance"]), []).append(row)
    out: list[dict[str, Any]] = []
    for row in hard_subset:
        enriched = dict(row)
        rows = by_instance.get((row["category"], row["instance"]), [])
        for field in ("total_cost", "route_count", "cost_fix", "cost_km", "cost_fuel", "cost_elec", "cost_carbon", "E_total", "distance_total", "electricity_kwh"):
            values = [as_float(item.get(f"delta_vs_lns_{field}")) for item in rows if math.isfinite(as_float(item.get(f"delta_vs_lns_{field}")))]
            enriched[f"a0_mean_delta_vs_lns_{field}"] = mean(values)
        out.append(enriched)
    return out


def root_cause_summary(cost_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in cost_rows if row.get("profile") == "A0_CURRENT"]
    total = mean_delta(rows, "total_cost")
    fixed = mean_delta(rows, "cost_fix")
    route_count = mean_delta(rows, "route_count")
    return {
        "schema": "setp-e2-route-compression-root-cause.v1",
        "a0_rows": len(rows),
        "mean_loss_delta_total": total,
        "mean_loss_delta_route_count": route_count,
        "mean_loss_delta_cost_fix": fixed,
        "mean_loss_delta_cost_km": mean_delta(rows, "cost_km"),
        "mean_loss_delta_cost_fuel": mean_delta(rows, "cost_fuel"),
        "mean_loss_delta_cost_elec": mean_delta(rows, "cost_elec"),
        "mean_loss_delta_cost_carbon": mean_delta(rows, "cost_carbon"),
        "mean_loss_delta_E_total": mean_delta(rows, "E_total"),
        "mean_loss_delta_distance_total": mean_delta(rows, "distance_total"),
        "mean_loss_delta_electricity_kwh": mean_delta(rows, "electricity_kwh"),
        "route_fixed_cost_supported": route_count > 0 and fixed > 0 and total > 0 and fixed >= 0.8 * total,
    }


def profile_summary(cost_rows: list[dict[str, Any]], *, anchors: dict[str, Any], root_cause: dict[str, Any]) -> list[dict[str, Any]]:
    lns_means = instance_means(cost_rows, "LNS_REFERENCE")
    a0_means = instance_means(cost_rows, "A0_CURRENT")
    rows: list[dict[str, Any]] = []
    anchor_ok = bool(anchors.get("parity_ok")) if anchors else False
    for profile in ALNS_PROFILES:
        profile_rows = [row for row in cost_rows if row.get("profile") == profile]
        inst_means = instance_means(cost_rows, profile)
        gaps: list[float] = []
        route_deltas_vs_lns: list[float] = []
        route_deltas_vs_a0: list[float] = []
        cost_fix_deltas_vs_lns: list[float] = []
        total_deltas_vs_lns: list[float] = []
        wins = losses = ties = 0
        for key, item in inst_means.items():
            paired = lns_means.get(key)
            if not paired:
                continue
            gap = safe_ratio(paired["total_cost"] - item["total_cost"], paired["total_cost"])
            gaps.append(gap)
            if gap > 1e-12:
                wins += 1
            elif gap < -1e-12:
                losses += 1
            else:
                ties += 1
            route_deltas_vs_lns.append(item["route_count"] - paired["route_count"])
            cost_fix_deltas_vs_lns.append(item["cost_fix"] - paired["cost_fix"])
            total_deltas_vs_lns.append(item["total_cost"] - paired["total_cost"])
            if key in a0_means:
                route_deltas_vs_a0.append(item["route_count"] - a0_means[key]["route_count"])
        infeasible_rows = sum(1 for row in profile_rows if is_infeasible(row))
        under_eval_rows = sum(1 for row in profile_rows if is_under_eval(row))
        identity_halt_rows = sum(1 for row in profile_rows if is_identity_halt(row))
        mean_route_count = mean([as_float(row.get("route_count")) for row in profile_rows])
        a0_mean_route_count = mean([as_float(row.get("route_count")) for row in cost_rows if row.get("profile") == "A0_CURRENT"])
        route_count_not_higher_than_a0 = profile == "A0_CURRENT" or mean_route_count <= a0_mean_route_count + 1e-12
        eligible = (
            profile in {"A1_RELAXED_ROUTE_COMPRESSION", "A2_RELAXED_ROUTE_COMPRESSION_LOCAL_SEARCH"}
            and mean(gaps) > 0
            and wins >= losses
            and infeasible_rows == 0
            and under_eval_rows == 0
            and identity_halt_rows == 0
            and route_count_not_higher_than_a0
            and anchor_ok
        )
        rows.append(
            {
                "profile": profile,
                "rows": len(profile_rows),
                "ok_rows": sum(1 for row in profile_rows if row.get("gate_status") == "OK"),
                "instance_count": len(inst_means),
                "wins_vs_lns": wins,
                "losses_vs_lns": losses,
                "ties_vs_lns": ties,
                "mean_gap_vs_lns": mean(gaps),
                "median_gap_vs_lns": median(gaps),
                "mean_total_delta_vs_lns": mean(total_deltas_vs_lns),
                "mean_cost_fix_delta_vs_lns": mean(cost_fix_deltas_vs_lns),
                "mean_route_count": mean_route_count,
                "mean_route_count_delta_vs_lns": mean(route_deltas_vs_lns),
                "mean_route_count_delta_vs_a0": mean(route_deltas_vs_a0),
                "infeasible_rows": infeasible_rows,
                "under_eval_rows": under_eval_rows,
                "identity_halt_rows": identity_halt_rows,
                "route_count_not_higher_than_a0": route_count_not_higher_than_a0,
                "anchor_parity_ok": anchor_ok,
                "eligible_for_support": eligible,
                "root_cause_route_fixed_supported": root_cause.get("route_fixed_cost_supported", ""),
            }
        )
    return rows


def instance_means(cost_rows: list[dict[str, Any]], profile: str) -> dict[tuple[str, str], dict[str, float]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in cost_rows:
        if row.get("profile") == profile and row.get("replay_status") == "OK":
            grouped.setdefault((row["category"], row["instance"]), []).append(row)
    out: dict[tuple[str, str], dict[str, float]] = {}
    for key, rows in grouped.items():
        out[key] = {
            "total_cost": mean([as_float(row.get("total_cost")) for row in rows]),
            "route_count": mean([as_float(row.get("route_count")) for row in rows]),
            "cost_fix": mean([as_float(row.get("cost_fix")) for row in rows]),
        }
    return out


def run_anchor_parity() -> dict[str, Any]:
    started = time.perf_counter()
    rows = [run_current_goeke_anchor(), run_current_threeshift_anchor()]
    return {
        "schema": "setp-e2-route-compression-anchor-parity.v1",
        "head": fc.git_head(),
        "anchors": rows,
        "parity_ok": all(bool(row.get("parity_ok")) for row in rows),
        "elapsed_seconds": time.perf_counter() - started,
    }


def run_current_goeke_anchor() -> dict[str, Any]:
    result = run_winner_kernel(GOEKE_BUNDLE, config=WinnerKernelConfig(seed=2, eval_budget=16000, max_runtime_seconds=900.0))
    return anchor_row("goeke80_100_01_seed2_current_q3650", result, EXPECTED_GO_EKE_CURRENT_COST)


def run_current_threeshift_anchor() -> dict[str, Any]:
    prices = replace(DEFAULT_PRICES, B_battery_kwh=DIAGNOSTIC_BATTERY_KWH, carbon_price=CARBON_PRICE)
    result = run_e2_alns_throughput(
        THREESHIFT_BUNDLE,
        config=WinnerKernelConfig(seed=1, eval_budget=2000, max_runtime_seconds=900.0),
        prices=prices,
    )
    return anchor_row("threeshift_150c_01_seed1_B280_eval2000", result, EXPECTED_THREESHIFT_280_COST)


def anchor_row(name: str, result: dict[str, Any], expected_cost: float) -> dict[str, Any]:
    cost = float(result["best_cost"])
    solution = result["best_solution"]
    return {
        "anchor": name,
        "best_cost": cost,
        "expected_best_cost": float(expected_cost),
        "abs_diff": abs(cost - float(expected_cost)),
        "parity_ok": abs(cost - float(expected_cost)) <= 1e-9 and bool(result["feasible"]) and int(result["violation_count"]) == 0,
        "feasible": bool(result["feasible"]),
        "violation_count": int(result["violation_count"]),
        "evaluations": int(result["evaluations"]),
        "route_count": len(solution.routes),
        "solution_hash": hash_payload(solution_to_dict(solution)),
        "operator_counts_without_timing_hash": hash_payload(strip_timing(result.get("operator_counts", {}))),
    }


def decide(
    metadata: dict[str, Any],
    preflight: dict[str, Any],
    current_summary: dict[str, Any],
    hard_subset: list[dict[str, Any]],
    cost_rows: list[dict[str, Any]],
    profile_rows: list[dict[str, Any]],
    root_cause: dict[str, Any],
    anchors: dict[str, Any],
) -> dict[str, Any]:
    protected = protected_diff()
    collection_failures = collection_failures_for(cost_rows, profile_rows)
    supported = [row for row in profile_rows if truthy(row.get("eligible_for_support"))]
    if protected:
        verdict = "HALT_PROTECTED_DIFF"
        plain = "保护文件出现 diff；本探针停止。"
    elif not preflight.get("can_continue"):
        verdict = "HALT_PREFLIGHT"
        plain = "现有 Tier1 素材入口不满足预设条件；本探针停止。"
    elif not root_cause.get("route_fixed_cost_supported"):
        verdict = "HALT_ROOT_CAUSE_NOT_ROUTE_COMPRESSION"
        plain = "A0 输给 LNS 的现有成本分解不支持路线数/固定派车成本是主因。"
    elif anchors and not anchors.get("parity_ok"):
        verdict = "HALT_ANCHOR_DRIFT"
        plain = "两个独立 ALNS 锚点至少一个漂移；停止并回查实现改动。"
    elif any(row.get("failure_bucket") == "under_eval" for row in collection_failures):
        verdict = "HALT_UNDER_EVAL"
        plain = "至少一个新 profile 未跑满 16000 eval；停止，不做支持性结论。"
    elif any(row.get("failure_bucket") == "identity_halt" for row in collection_failures):
        verdict = "HALT_T3_HOMOGENIZATION"
        plain = "探针 profile 触发 identity/homogenization halt；停止。"
    elif supported:
        verdict = "ROUTE_COMPRESSION_FIX_SUPPORTED"
        plain = "hard subset 上至少一个显式路线压缩 profile 过预注册支持门槛；这只支持升级为候选，不等于正式 T3 胜利。"
    else:
        verdict = "ROUTE_COMPRESSION_FIX_NOT_SUPPORTED"
        plain = "显式路线压缩 profile 未同时满足 mean gap、wins/losses、可行性、闭合、路线数和锚点门槛。"
    return {
        "schema": "setp-e2-route-compression-probe-decision.v1",
        "verdict": verdict,
        "plain": plain,
        "head": metadata.get("head"),
        "source_final_material_verdict": preflight.get("source_final_material_verdict"),
        "current_alns_vs_lns": current_summary,
        "hard_subset_count": len(hard_subset),
        "root_cause": root_cause,
        "profile_summary": profile_rows,
        "supported_profiles": [row.get("profile") for row in supported],
        "anchor_parity_ok": anchors.get("parity_ok") if anchors else None,
        "anchor_parity": anchors,
        "collection_failure_count": len(collection_failures),
        "collection_failures": collection_failures[:20],
        "protected_diff": protected,
        "not_formal_t3": True,
        "formal_t3_unfrozen": verdict == "ROUTE_COMPRESSION_FIX_SUPPORTED",
        "algorithm_win_loss_claim": False,
        "paper_text_claim_allowed": False,
    }


def halt_root_cause_decision(
    metadata: dict[str, Any],
    preflight: dict[str, Any],
    current_summary: dict[str, Any],
    hard_subset: list[dict[str, Any]],
    cost_rows: list[dict[str, Any]],
    profile_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    root_cause = root_cause_summary(cost_rows)
    verdict = "HALT_PREFLIGHT" if not preflight.get("can_continue") else "HALT_ROOT_CAUSE_NOT_ROUTE_COMPRESSION"
    return {
        "schema": "setp-e2-route-compression-probe-decision.v1",
        "verdict": verdict,
        "plain": "前置证据或 root-cause 门未闭合；不运行 A1/A2。",
        "head": metadata.get("head"),
        "source_final_material_verdict": preflight.get("source_final_material_verdict"),
        "current_alns_vs_lns": current_summary,
        "hard_subset_count": len(hard_subset),
        "root_cause": root_cause,
        "profile_summary": profile_rows,
        "protected_diff": protected_diff(),
        "not_formal_t3": True,
        "algorithm_win_loss_claim": False,
        "paper_text_claim_allowed": False,
    }


def collection_failures_for(cost_rows: list[dict[str, Any]], profile_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for row in profile_rows:
        profile = row.get("profile")
        if profile in {"A1_RELAXED_ROUTE_COMPRESSION", "A2_RELAXED_ROUTE_COMPRESSION_LOCAL_SEARCH"}:
            if int(as_float(row.get("rows"), 0)) != 48:
                failures.append({"failure_bucket": "missing_rows", "profile": profile, "actual": row.get("rows"), "expected": 48})
            if int(as_float(row.get("infeasible_rows"), 0)) > 0:
                failures.append({"failure_bucket": "infeasible", "profile": profile, "count": row.get("infeasible_rows")})
            if int(as_float(row.get("under_eval_rows"), 0)) > 0:
                failures.append({"failure_bucket": "under_eval", "profile": profile, "count": row.get("under_eval_rows")})
            if int(as_float(row.get("identity_halt_rows"), 0)) > 0:
                failures.append({"failure_bucket": "identity_halt", "profile": profile, "count": row.get("identity_halt_rows")})
    mismatches = [
        row
        for row in cost_rows
        if row.get("replay_status") == "OK" and as_float(row.get("best_cost_abs_diff")) > 1e-6
    ]
    if mismatches:
        failures.append({"failure_bucket": "replay_cost_mismatch", "count": len(mismatches), "sample": [row.get("run_id") for row in mismatches[:5]]})
    return failures


def write_report(
    output_dir: Path,
    metadata: dict[str, Any],
    decision: dict[str, Any],
    current_summary: dict[str, Any],
    hard_subset: list[dict[str, Any]],
    profile_rows: list[dict[str, Any]],
) -> None:
    root = decision.get("root_cause") or {}
    lines = [
        "# E2 Route Compression Probe",
        "",
        "本探针只验证 hard subset 上的显式路线压缩组件，不是正式 T3，不写 TeX。",
        "",
        f"Verdict: `{decision.get('verdict')}`",
        "",
        "## Current A0 vs LNS",
        "",
        f"- instances: `{current_summary.get('total_instances')}`",
        f"- A0 wins/losses/ties vs LNS: `{current_summary.get('alns_wins_vs_lns')}/{current_summary.get('alns_losses_vs_lns')}/{current_summary.get('alns_ties_vs_lns')}`",
        f"- mean gap: `{current_summary.get('mean_gap_vs_lns')}`",
        f"- median gap: `{current_summary.get('median_gap_vs_lns')}`",
        f"- hard subset count: `{len(hard_subset)}`",
        "",
        "## Root Cause Replay",
        "",
        f"- mean total delta A0-LNS: `{root.get('mean_loss_delta_total')}`",
        f"- mean route count delta A0-LNS: `{root.get('mean_loss_delta_route_count')}`",
        f"- mean fixed cost delta A0-LNS: `{root.get('mean_loss_delta_cost_fix')}`",
        f"- route/fixed supported: `{root.get('route_fixed_cost_supported')}`",
        "",
        "## Profile Summary",
        "",
        "| profile | wins | losses | mean gap | route delta vs A0 | infeasible | under-eval | eligible |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in profile_rows:
        lines.append(
            "| {profile} | {wins_vs_lns} | {losses_vs_lns} | {mean_gap_vs_lns} | {mean_route_count_delta_vs_a0} | {infeasible_rows} | {under_eval_rows} | {eligible_for_support} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "## Anchors",
            "",
            f"- parity ok: `{decision.get('anchor_parity_ok')}`",
            "",
            "## Artifacts",
            "",
            f"- Data dir: `{metadata.get('output_dir')}`",
            "- `decision.json`",
            "- `report.md`",
            "- `hard_subset_instances.csv`",
            "- `profile_summary.csv`",
            "- `raw_runs.csv`",
            "- `cost_decomposition.csv`",
            "- `anchor_parity.json`",
            "- `metadata.json`",
            "- `artifact_hashes.json`",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def protected_diff() -> list[str]:
    proc = subprocess.run(["git", "diff", "--name-only", "HEAD", "--", *USER_PROTECTED_PATHS], cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def clean_artifact_dir(output_dir: Path) -> None:
    if not output_dir.exists():
        return
    for path in sorted(output_dir.rglob("*"), reverse=True):
        if path.name.startswith("._") or path.name in HASH_EXCLUDE_PARTS:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)


def write_hashes(output_dir: Path) -> None:
    clean_artifact_dir(output_dir)
    files: list[dict[str, str]] = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name in HASH_EXCLUDE_NAMES or path.name.startswith("._"):
            continue
        if any(part in HASH_EXCLUDE_PARTS for part in path.parts):
            continue
        files.append({"path": fc.rel(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    fc.write_json(output_dir / "artifact_hashes.json", {"schema": "setp-e2-route-compression-artifact-hashes.v1", "root": fc.rel(output_dir), "file_count": len(files), "files": files})
    clean_artifact_dir(output_dir)


def is_infeasible(row: dict[str, Any]) -> bool:
    return row.get("replay_status") != "OK" or int(as_float(row.get("replay_violation_count"), 0)) > 0 or str(row.get("gate_status")) == "HALT_INFEASIBLE"


def is_under_eval(row: dict[str, Any]) -> bool:
    status = str(row.get("status", "")) + " " + str(row.get("gate_status", ""))
    return "UNDER_EVAL" in status or int(as_float(row.get("actual_evals"), 0)) < int(as_float(row.get("eval_budget"), 0))


def is_identity_halt(row: dict[str, Any]) -> bool:
    text = " ".join(str(row.get(key, "")) for key in ("status", "gate_status", "identity_cluster_class"))
    return "HALT_T3_HOMOGENIZATION" in text or "IDENTITY_HALT" in text


def mean_delta(rows: list[dict[str, Any]], field: str) -> float:
    return mean([as_float(row.get(f"delta_vs_lns_{field}")) for row in rows if math.isfinite(as_float(row.get(f"delta_vs_lns_{field}")))])


def mean(values: list[float]) -> float:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    return statistics.fmean(finite) if finite else math.nan


def median(values: list[float]) -> float:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    return statistics.median(finite) if finite else math.nan


def safe_ratio(num: float, denom: float) -> float:
    if not math.isfinite(num) or not math.isfinite(denom) or abs(denom) <= 1e-12:
        return math.nan
    return float(num) / float(denom)


def as_float(value: Any, default: float = math.nan) -> float:
    try:
        if value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def parse_seeds(text: str) -> list[int]:
    return [int(item.strip()) for item in str(text).split(",") if item.strip()]


def hash_payload(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def strip_timing(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: strip_timing(val) for key, val in sorted(value.items()) if key != "timing"}
    if isinstance(value, list):
        return [strip_timing(item) for item in value]
    if isinstance(value, tuple):
        return [strip_timing(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
