#!/usr/bin/env python3
"""C1-R1b bridge-side repair validation.

This is a baseline-health probe, not a formal T3 experiment. It instruments the
baseline destroy/repair bridge around ``repair_removed_customers`` and validates
that any bridge-side fix leaves the independent ALNS anchors unchanged.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import random
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
from setp_solver.search import candidates as candidate_module
from setp_solver.search import feasible_repair as fr
from setp_solver.search import metaheuristic_baselines as mb
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution, solution_signature_hash
from setp_solver.search.evaluation import EvalBudget, EvaluationContext, fairness_context_for_solution
from setp_solver.search.feasible_repair import enumerate_feasible_insertions, repair_removed_customers, route_customers
from setp_solver.search.fleet import normalize_solution_vehicle_trips
from setp_solver.search.metaheuristic_baselines import run_metaheuristic_baseline, solution_from_dict, solution_to_dict
from setp_solver.search.winner_operators import WinnerKernelConfig, _run_winner_variant, run_e2_alns_throughput, run_winner_kernel
from setp_solver.solution import Route, Solution

from baselines.e2_alns import native_channel_autopsy as c1r2


GOLD_PYTHON = "/opt/anaconda3/bin/python3.13"
GOLD_NUMPY = "2.3.5"
CARBON_PRICE = 0.05034
BATTERY_KWH = 280.0
PLATFORM_COST = 5174.345121253789
INSTANCE_CATEGORY = "threeshift"
INSTANCE_NAME = "e2-threeshift-150c-01"
INSTANCE_ROOT = REPO_ROOT / "models/data_bundle/generated_instances/e2_benchmark"
THREESHIFT_BUNDLE = INSTANCE_ROOT / INSTANCE_CATEGORY / INSTANCE_NAME
GOEKE_BUNDLE = REPO_ROOT / "models/data_bundle/generated_instances/E-UK100_01__d2_s3_seed1_24h_20251113"
OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/bridge_fix_validation_data"
REPORT_PATH = OUTPUT_DIR / "report.md"
FLIP_CLOSURE_CSV = REPO_ROOT / "baselines/e2_alns/native_channel_autopsy_data/flip_closure.csv"
INDEPENDENCE_PRE = REPO_ROOT / "baselines/e2_alns/alns_independence_migration_data/pre_migration_anchor.json"
INDEPENDENCE_POST = REPO_ROOT / "baselines/e2_alns/alns_independence_migration_data/post_migration_anchor.json"
HASH_EXCLUDE_NAMES = {"artifact_hashes.json"}
HASH_EXCLUDE_PARTS = {"__pycache__", ".pytest_cache"}
DESTROY_OPS = [
    "random_customer_removal",
    "shaw_related_removal",
    "worst_customer_removal",
    "whole_route_removal",
    "route_segment_removal",
]
REPAIR_OPS = ["greedy_insert_repair", "regret2_insert_repair", "regret3_insert_repair"]
MODE_BY_REPAIR = {
    "greedy_insert_repair": "greedy",
    "regret2_insert_repair": "regret2",
    "regret3_insert_repair": "regret3",
}
EXPECTED_GO_EKE_CURRENT_COST = 2677.7953638343815
EXPECTED_THREESHIFT_280_COST = 3561.080964207054


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--trials", type=int, default=200)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--eval-budget", type=int, default=2000)
    parser.add_argument("--runtime-cap-seconds", type=float, default=600.0)
    parser.add_argument("--skip-lns", action="store_true")
    parser.add_argument("--skip-anchors", action="store_true")
    parser.add_argument("--skip-legacy", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = repo_path(Path(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    clean_artifact_dir(output_dir)

    metadata = build_metadata(args, output_dir)
    write_json(output_dir / "metadata.json", metadata)
    write_json(output_dir / "preflight.json", preflight())

    phase_a_rows = run_phase_a_bridge_exit_autopsy(trials=int(args.trials), seed=int(args.seed))
    write_csv(output_dir / "phase_a_bridge_exit_autopsy.csv", phase_a_rows)

    convention_rows = call_convention_diff()
    write_csv(output_dir / "call_convention_diff.csv", convention_rows)

    selected_case = select_regression_case(phase_a_rows)
    write_json(output_dir / "selected_regression_case.json", selected_case)

    lns_rows: list[dict[str, Any]] = []
    if not args.skip_lns:
        lns_rows = run_lns_b1_probe(seed=int(args.seed), eval_budget=int(args.eval_budget), runtime_cap_seconds=float(args.runtime_cap_seconds))
    write_csv(output_dir / "lns_b1_raw_runs.csv", lns_rows)

    anchor_parity = {} if args.skip_anchors else run_anchor_parity()
    write_json(output_dir / "anchor_parity.json", anchor_parity)

    legacy_anchor = {} if args.skip_legacy else run_legacy_q1600_anchor()
    write_json(output_dir / "legacy_q1600_anchor.json", legacy_anchor)

    decision = decide(metadata, phase_a_rows, selected_case, lns_rows, anchor_parity, legacy_anchor)
    write_json(output_dir / "decision.json", decision)
    REPORT_PATH.write_text(render_report(metadata, decision, phase_a_rows, convention_rows, selected_case, lns_rows, anchor_parity, legacy_anchor), encoding="utf-8")

    clean_artifact_dir(output_dir)
    write_json(output_dir / "artifact_hashes.json", artifact_hashes(output_dir))
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision["verdict"] in {"BRIDGE_FIXED", "BRIDGE_CAUSE_DEEPER"} else 2


def build_metadata(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    return {
        "schema": "setp-c1-r1b-bridge-fix-validation.v1",
        "task": "C1-R1b bridge-side destroy/repair fix",
        "objective": (
            "让 baseline 的 destroy/repair 桥在 5174 平台解上能产出可行邻居，"
            "同时不改变 ALNS 主算法任何行为。"
        ),
        "boundary": "baseline health repair only; not formal T3; no algorithm win/loss claim",
        "head": git_head(),
        "python": sys.executable,
        "numpy": numpy_version(),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", ""),
        "output_dir": str(output_dir.relative_to(REPO_ROOT)),
        "instance": INSTANCE_NAME,
        "seed": int(args.seed),
        "trials": int(args.trials),
        "eval_budget": int(args.eval_budget),
        "runtime_cap_seconds": float(args.runtime_cap_seconds),
        "battery_override": "dataclasses.replace(DEFAULT_PRICES, B_battery_kwh=280.0, carbon_price=0.05034)",
        "protected_files": [
            "cost.py",
            "check.py",
            "search/evaluation.py",
            "prices.py defaults",
            "TeX",
            "feasible_repair.py",
            "resetp_alns/",
            "ALNS main path",
        ],
        "started_at_epoch": time.time(),
    }


def preflight() -> dict[str, Any]:
    return {
        "env_ok": sys.executable == GOLD_PYTHON and numpy_version() == GOLD_NUMPY and os.environ.get("PYTHONHASHSEED") == "0",
        "python": sys.executable,
        "numpy": numpy_version(),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", ""),
        "flip_closure_exists": FLIP_CLOSURE_CSV.exists(),
        "independence_pre_exists": INDEPENDENCE_PRE.exists(),
        "independence_post_exists": INDEPENDENCE_POST.exists(),
        "protected_diff": protected_diff(),
    }


def run_phase_a_bridge_exit_autopsy(*, trials: int, seed: int) -> list[dict[str, Any]]:
    prices = make_probe_prices()
    bundle = load_search_bundle(THREESHIFT_BUNDLE)
    context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices, budget=EvalBudget(limit=trials * 3, target=trials))
    platform = load_platform_solution()
    combos = [(destroy, repair) for destroy in DESTROY_OPS for repair in REPAIR_OPS]
    rng = random.Random(int(seed))
    rows: list[dict[str, Any]] = []
    for trial in range(1, int(trials) + 1):
        destroy, repair = combos[(trial - 1) % len(combos)]
        removed = candidate_module._strong_destroy_customer_ids(platform, context, rng, destroy)
        partial_routes = candidate_module._routes_without_customers(platform.routes, set(removed), context.instance)
        partial = Solution(routes=partial_routes, charging_actions=candidate_module._actions_for_routes(platform, partial_routes), cross_site_services=platform.cross_site_services)
        for policy_name, policy in bridge_policies(context).items():
            trace = trace_repair_removed(partial, list(removed), context, policy, mode=MODE_BY_REPAIR[repair], allow_new_route=True)
            rows.append(phase_a_row(trial, seed, destroy, repair, policy_name, policy, removed, partial, trace, platform))
    return rows


def bridge_policies(context: EvaluationContext) -> dict[str, Any]:
    return {
        "bridge_thin_current": candidate_module._ThinPolicy(),
        "alns_real_fleet_caps": candidate_module._ThinPolicy(
            require_charging_signal=False,
            max_cv=_instance_limit(context.instance, "num_cv"),
            max_ev=_instance_limit(context.instance, "num_ev"),
        ),
    }


def trace_repair_removed(
    partial_solution: Solution,
    removed_customers: list[str],
    context: EvaluationContext,
    policy: Any,
    *,
    mode: str,
    allow_new_route: bool,
) -> dict[str, Any]:
    pending = list(dict.fromkeys(removed_customers))
    current = partial_solution
    steps: list[dict[str, Any]] = []
    while pending:
        scored: list[tuple[float, float, str, Solution]] = []
        option_counts: dict[str, int] = {}
        opened_new_counts: dict[str, int] = {}
        vehicle_option_counts: dict[str, int] = {}
        for customer_id in pending:
            options = enumerate_feasible_insertions(current, customer_id, context, policy, allow_new_route=allow_new_route)
            option_counts[customer_id] = len(options)
            opened_new_counts[customer_id] = sum(1 for option in options if bool(option.opened_new_route))
            for option in options:
                key = f"{option.vehicle_type}:{'new' if option.opened_new_route else 'existing'}"
                vehicle_option_counts[key] = vehicle_option_counts.get(key, 0) + 1
            if not options:
                continue
            best = options[0]
            ordered = [option.score for option in options]
            if mode == "regret3":
                comparison = ordered[2] if len(ordered) > 2 else ordered[-1]
                primary = -(comparison - best.score)
            elif mode == "regret2":
                comparison = ordered[1] if len(ordered) > 1 else ordered[0]
                primary = -(comparison - best.score)
            elif mode == "greedy":
                primary = best.score
            else:
                raise ValueError(f"unknown feasible repair mode: {mode}")
            scored.append((primary, best.score, customer_id, best.solution))
        steps.append(
            {
                "pending_count": len(pending),
                "option_counts": option_counts,
                "opened_new_counts": opened_new_counts,
                "vehicle_option_counts": vehicle_option_counts,
                "zero_option_customers": [customer for customer, count in option_counts.items() if count == 0],
            }
        )
        if not scored:
            return {
                "produced_solution": current,
                "repair_result": None,
                "none_exit": "INSERT_LOOP_EXHAUSTED",
                "insert_loop_step": len(steps),
                "pending_customers": pending,
                "steps": steps,
                "final_violations": [],
                "fallback_violations": [],
                "fallback_available": False,
                "fallback_feasible": False,
            }
        _, _, chosen_customer, current = min(scored, key=lambda item: (item[0], item[1], item[2]))
        pending.remove(chosen_customer)

    final_solution, final_violations, final_normalize_error = normalize_and_check(current, context, policy)
    if final_solution is not None and not final_violations and final_normalize_error == "":
        return {
            "produced_solution": final_solution,
            "repair_result": final_solution,
            "none_exit": "REPAIRED_FEASIBLE",
            "insert_loop_step": len(steps),
            "pending_customers": [],
            "steps": steps,
            "final_violations": [],
            "fallback_violations": [],
            "fallback_available": False,
            "fallback_feasible": False,
        }

    fallback = fr._all_cv_fallback(current, context, policy)
    fallback_solution, fallback_violations, fallback_normalize_error = normalize_and_check(fallback, context, policy) if fallback is not None else (None, [], "")
    fallback_feasible = fallback_solution is not None and not fallback_violations and fallback_normalize_error == ""
    if fallback_feasible:
        return {
            "produced_solution": fallback_solution,
            "repair_result": fallback_solution,
            "none_exit": "FALLBACK_FEASIBLE",
            "insert_loop_step": len(steps),
            "pending_customers": [],
            "steps": steps,
            "final_violations": final_violations,
            "final_normalize_error": final_normalize_error,
            "fallback_violations": [],
            "fallback_available": True,
            "fallback_feasible": True,
        }
    return {
        "produced_solution": final_solution or current,
        "repair_result": None,
        "none_exit": "FINAL_CHECK_FAILED",
        "insert_loop_step": len(steps),
        "pending_customers": [],
        "steps": steps,
        "final_violations": final_violations,
        "final_normalize_error": final_normalize_error,
        "fallback_violations": fallback_violations,
        "fallback_normalize_error": fallback_normalize_error,
        "fallback_available": fallback is not None,
        "fallback_feasible": False,
    }


def normalize_and_check(solution: Solution | None, context: EvaluationContext, policy: Any) -> tuple[Solution | None, list[Any], str]:
    if solution is None:
        return None, [], ""
    try:
        normalized = normalize_solution_vehicle_trips(
            solution,
            context.instance,
            max_cv=int(getattr(policy, "max_cv", getattr(context.instance, "num_cv", 10**9) or 10**9)),
            max_ev=int(getattr(policy, "max_ev", getattr(context.instance, "num_ev", 10**9) or 10**9)),
        )
    except ValueError as exc:
        return None, [], str(exc)
    violations = check_solution(
        normalized,
        context.instance,
        context.prices,
        fairness_context=fairness_context_for_solution(normalized, context),
        fairness_enabled=context.fairness_enabled,
    )
    return normalized, violations, ""


def phase_a_row(
    trial: int,
    seed: int,
    destroy: str,
    repair: str,
    policy_name: str,
    policy: Any,
    removed: list[str],
    partial: Solution,
    trace: dict[str, Any],
    platform: Solution,
) -> dict[str, Any]:
    produced = trace["produced_solution"]
    final_counts = violation_type_counts(trace.get("final_violations", []))
    fallback_counts = violation_type_counts(trace.get("fallback_violations", []))
    first_zero_customer = ""
    for step in trace.get("steps", []):
        zeroes = step.get("zero_option_customers", [])
        if zeroes:
            first_zero_customer = str(zeroes[0])
            break
    return {
        "trial": int(trial),
        "seed": int(seed),
        "destroy": destroy,
        "repair": repair,
        "policy_name": policy_name,
        "policy_max_cv": int(getattr(policy, "max_cv", 10**9)),
        "policy_max_ev": int(getattr(policy, "max_ev", 10**9)),
        "require_charging_signal": bool(getattr(policy, "require_charging_signal", False)),
        "removed_count": len(removed),
        "partial_route_count": len(partial.routes),
        "partial_cv_route_count": sum(1 for route in partial.routes if route.vehicle_type.lower() == "cv"),
        "partial_ev_route_count": sum(1 for route in partial.routes if route.vehicle_type.lower() == "ev"),
        "partial_action_count": len(partial.charging_actions),
        "none_exit": trace.get("none_exit"),
        "insert_loop_step": trace.get("insert_loop_step"),
        "first_zero_option_customer": first_zero_customer,
        "produced": trace.get("repair_result") is not None,
        "feasible": trace.get("repair_result") is not None,
        "changed": solution_signature_hash(produced) != solution_signature_hash(platform) if produced is not None else False,
        "candidate_signature": solution_signature_hash(produced) if produced is not None else "",
        "candidate_route_count": len(produced.routes) if produced is not None else 0,
        "candidate_cv_route_count": sum(1 for route in produced.routes if route.vehicle_type.lower() == "cv") if produced is not None else 0,
        "candidate_ev_route_count": sum(1 for route in produced.routes if route.vehicle_type.lower() == "ev") if produced is not None else 0,
        "candidate_action_count": len(produced.charging_actions) if produced is not None else 0,
        "final_violation_count": sum(final_counts.values()),
        "final_violation_type_histogram": json.dumps(final_counts, ensure_ascii=False, sort_keys=True),
        "final_normalize_error": trace.get("final_normalize_error", ""),
        "fallback_available": bool(trace.get("fallback_available")),
        "fallback_feasible": bool(trace.get("fallback_feasible")),
        "fallback_violation_count": sum(fallback_counts.values()),
        "fallback_violation_type_histogram": json.dumps(fallback_counts, ensure_ascii=False, sort_keys=True),
        "fallback_normalize_error": trace.get("fallback_normalize_error", ""),
        "pending_count_on_failure": len(trace.get("pending_customers", [])),
        "steps_json": json.dumps(trace.get("steps", []), ensure_ascii=False, sort_keys=True),
    }


def call_convention_diff() -> list[dict[str, Any]]:
    return [
        {
            "field": "policy.max_cv/max_ev",
            "baseline_bridge": "_ThinPolicy(max_cv=1e9, max_ev=1e9)",
            "main_alns": "SearchPolicy(max_cv=instance.num_cv, max_ev=instance.num_ev)",
            "risk": "bridge may enumerate routes that can only fail at final fleet-cap check",
        },
        {
            "field": "partial solution",
            "baseline_bridge": "_routes_without_customers + _actions_for_routes",
            "main_alns": "_remove_customers removes empty routes and keeps actions for kept vehicles/stations",
            "risk": "mostly equivalent; Phase A records partial route/action counts",
        },
        {
            "field": "allow_new_route",
            "baseline_bridge": "always True",
            "main_alns": "True except route_elimination_removal forces False",
            "risk": "not a direct mismatch for the five bridge destroy operators",
        },
        {
            "field": "None handling",
            "baseline_bridge": "returns infeasible _OperatorOutcome detail=strong_repair_failed",
            "main_alns": "returns source_solution/current state and continues",
            "risk": "baseline LNS falls back to decoder path after bridge failure",
        },
        {
            "field": "shared repair function",
            "baseline_bridge": "repair_removed_customers from feasible_repair.py",
            "main_alns": "same function",
            "risk": "fix must be bridge-side call convention, not shared repair semantics",
        },
    ]


def select_regression_case(rows: list[dict[str, Any]]) -> dict[str, Any]:
    real_policy = [row for row in rows if row.get("policy_name") == "alns_real_fleet_caps"]
    feasible = [row for row in real_policy if boolish(row.get("feasible")) and boolish(row.get("changed"))]
    if feasible:
        chosen = feasible[0]
        reason = "first real-fleet policy trace that already produces a feasible changed repair"
    else:
        final_failed = [row for row in real_policy if row.get("none_exit") == "FINAL_CHECK_FAILED"]
        if final_failed:
            chosen = final_failed[0]
            reason = "first FINAL_CHECK_FAILED under real-fleet policy"
        else:
            exhausted = [row for row in real_policy if row.get("none_exit") == "INSERT_LOOP_EXHAUSTED"]
            chosen = exhausted[0] if exhausted else (real_policy[0] if real_policy else rows[0])
            reason = "first INSERT_LOOP_EXHAUSTED or first available row"
    return {
        "trial": int(chosen["trial"]),
        "seed": int(chosen["seed"]),
        "destroy": chosen["destroy"],
        "repair": chosen["repair"],
        "policy_name": chosen["policy_name"],
        "none_exit": chosen["none_exit"],
        "reason": reason,
        "fix_path": "bridge_policy_real_fleet_caps" if feasible else "unresolved_after_phase_a",
    }


def run_lns_b1_probe(*, seed: int, eval_budget: int, runtime_cap_seconds: float) -> list[dict[str, Any]]:
    prices = make_probe_prices()
    bundle = load_search_bundle(THREESHIFT_BUNDLE)
    initial_solution = make_shared_initial_solution(bundle, prices=prices)
    run_id = f"D1_LNS_bridge_fix_seed{seed}"
    tracer = c1r2.NativeProbeTracer(
        run_id=run_id,
        phase="D1",
        algorithm="LNS",
        condition="bridge_fix_current_true_repair_0",
        seed=int(seed),
        candidate_rows=[],
        decode_rows=[],
        trajectory_rows=[],
        order_stack=[],
    )
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    try:
        with c1r2.instrument_baseline(tracer, force_true_repair_one=False):
            result = run_metaheuristic_baseline(
                "LNS",
                bundle.bundle_dir,
                seed=int(seed),
                eval_budget=int(eval_budget),
                max_runtime_seconds=float(runtime_cap_seconds),
                initial_solution=initial_solution,
                prices=prices,
            )
        rows.extend(tracer.candidate_rows)
        rows.append(
            {
                "row_type": "run_summary",
                "run_id": run_id,
                "phase": "D1",
                "algorithm": "LNS",
                "condition": "bridge_fix_current_true_repair_0",
                "seed": int(seed),
                "status": result.status,
                "gate_status": "OK" if result.status == "OK" else result.status,
                "actual_evals": int(result.evals),
                "eval_budget": int(eval_budget),
                "elapsed_seconds": time.perf_counter() - started,
                "best_cost": float(result.best_cost) if result.best_cost is not None else math.inf,
                "native_best_updates": sum(1 for row in tracer.candidate_rows if boolish(row.get("best_updated")) and boolish(row.get("native_operator"))),
                "bridge_feasible_route_20_40_count": sum(
                    1
                    for row in tracer.candidate_rows
                    if boolish(row.get("native_operator"))
                    and boolish(row.get("candidate_feasible"))
                    and 20 <= int(as_float(row.get("route_count"))) <= 40
                ),
                "python": sys.executable,
                "numpy": numpy_version(),
            }
        )
    except Exception as exc:
        rows.append(
            {
                "row_type": "run_summary",
                "run_id": run_id,
                "phase": "D1",
                "algorithm": "LNS",
                "condition": "bridge_fix_current_true_repair_0",
                "seed": int(seed),
                "status": "HALT_WORKER_EXCEPTION",
                "gate_status": "HALT_WORKER_EXCEPTION",
                "failure_reason": repr(exc),
                "actual_evals": 0,
                "eval_budget": int(eval_budget),
                "elapsed_seconds": time.perf_counter() - started,
                "python": sys.executable,
                "numpy": numpy_version(),
            }
        )
    return rows


def run_anchor_parity() -> dict[str, Any]:
    started = time.perf_counter()
    goeke = run_current_goeke_anchor()
    threeshift = run_current_threeshift_anchor()
    anchors = [goeke, threeshift]
    return {
        "schema": "setp-c1-r1b-anchor-parity.v1",
        "head": git_head(),
        "elapsed_seconds": time.perf_counter() - started,
        "anchors": anchors,
        "parity_ok": all(row.get("parity_ok") for row in anchors),
    }


def run_current_goeke_anchor() -> dict[str, Any]:
    result = run_winner_kernel(GOEKE_BUNDLE, config=WinnerKernelConfig(seed=2, eval_budget=16000, max_runtime_seconds=900.0))
    return anchor_row("goeke80_100_01_seed2_current_q3650", result, EXPECTED_GO_EKE_CURRENT_COST)


def run_current_threeshift_anchor() -> dict[str, Any]:
    prices = make_probe_prices()
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


def run_legacy_q1600_anchor() -> dict[str, Any]:
    started = time.perf_counter()
    prices = replace(DEFAULT_PRICES, Q_capacity=1600.0)
    try:
        result = _run_winner_variant(
            GOEKE_BUNDLE,
            WinnerKernelConfig(seed=2, eval_budget=16000, max_runtime_seconds=900.0),
            initial_solution=None,
            prices=prices,
        )
        cost = float(result["best_cost"])
        within_scale = 4300.0 <= cost <= 5400.0
        status = "OK" if within_scale else "LEGACY_ANCHOR_UNEXPLAINED"
        failure_reason = "" if within_scale else "Q_capacity=1600.0 rerun did not reproduce the 4878 legacy scale"
    except TypeError:
        status = "LEGACY_ANCHOR_UNEXPLAINED"
        failure_reason = "run_winner_kernel does not accept prices override on this branch"
        result = None
        cost = math.nan
    except Exception as exc:
        status = "LEGACY_ANCHOR_UNEXPLAINED"
        failure_reason = repr(exc)
        result = None
        cost = math.nan
    return {
        "schema": "setp-c1-r1b-legacy-q1600-anchor.v1",
        "anchor": "goeke80_100_01_seed2_Q1600_in_memory_override",
        "status": status,
        "best_cost": cost,
        "target_legacy_scale": 4878.331796187524,
        "within_legacy_scale": math.isfinite(cost) and 4300.0 <= cost <= 5400.0,
        "failure_reason": failure_reason,
        "elapsed_seconds": time.perf_counter() - started,
        "note": "D4 is explanatory and does not block BRIDGE_FIXED.",
    }


def decide(
    metadata: dict[str, Any],
    phase_a_rows: list[dict[str, Any]],
    selected_case: dict[str, Any],
    lns_rows: list[dict[str, Any]],
    anchor_parity: dict[str, Any],
    legacy_anchor: dict[str, Any],
) -> dict[str, Any]:
    failures = collection_failures(metadata, phase_a_rows, lns_rows, anchor_parity)
    if anchor_parity and not anchor_parity.get("parity_ok"):
        verdict = "HALT_PARITY_DRIFT"
        plain = "独立 ALNS 锚点漂移；桥修复必须回滚并停止 E2 调试。"
    elif failures:
        verdict = "HALT_COLLECTION_COST"
        plain = "环境、采集、trace 或 hash 前置门未闭合；停止。"
    else:
        lns_summary = next((row for row in lns_rows if row.get("row_type") == "run_summary"), {})
        bridge_alive = int(as_float(lns_summary.get("bridge_feasible_route_20_40_count"), 0.0)) > 0
        phase_a_feasible = any(
            row.get("policy_name") == "alns_real_fleet_caps"
            and boolish(row.get("feasible"))
            and boolish(row.get("changed"))
            for row in phase_a_rows
        )
        if bridge_alive:
            verdict = "BRIDGE_FIXED"
            plain = "baseline destroy/repair 桥已能产出 20-40 路线级可行邻居；本结论只说明 baseline health。"
        elif phase_a_feasible and not lns_rows:
            verdict = "BRIDGE_FIXED"
            plain = "Phase A 已证明桥侧真实 fleet policy 能产出可行邻居；D1 被跳过，不能写正式 liveness。"
        else:
            verdict = "BRIDGE_CAUSE_DEEPER"
            plain = "A/B 完整但 D1 未出现可行桥邻居；按预注册停下，不加料硬修。"
    return {
        "schema": "setp-c1-r1b-decision.v1",
        "verdict": verdict,
        "plain": plain,
        "head": metadata.get("head"),
        "collection_failure_count": len(failures),
        "failure_sample": failures[:20],
        "phase_a_rows": len(phase_a_rows),
        "phase_a_histogram": phase_a_histogram_json(phase_a_rows),
        "selected_regression_case": selected_case,
        "lns_rows": len(lns_rows),
        "anchor_parity_ok": anchor_parity.get("parity_ok") if anchor_parity else None,
        "legacy_anchor_status": legacy_anchor.get("status") if legacy_anchor else "SKIPPED",
        "not_formal_t3": True,
        "algorithm_win_loss_claim": False,
    }


def collection_failures(
    metadata: dict[str, Any],
    phase_a_rows: list[dict[str, Any]],
    lns_rows: list[dict[str, Any]],
    anchor_parity: dict[str, Any],
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    if metadata.get("python") != GOLD_PYTHON or metadata.get("numpy") != GOLD_NUMPY or metadata.get("pythonhashseed") != "0":
        failures.append({"failure_bucket": "environment_mismatch", "python": metadata.get("python"), "numpy": metadata.get("numpy"), "pythonhashseed": metadata.get("pythonhashseed")})
    if not phase_a_rows:
        failures.append({"failure_bucket": "phase_a_trace_missing"})
    if phase_a_rows and len(phase_a_rows) != 400:
        failures.append({"failure_bucket": "phase_a_under_rows", "actual": len(phase_a_rows), "expected": 400})
    summaries = [row for row in lns_rows if row.get("row_type") == "run_summary"]
    if lns_rows and len(summaries) != 1:
        failures.append({"failure_bucket": "lns_summary_missing_or_duplicate", "actual": len(summaries)})
    for row in summaries:
        if row.get("gate_status") != "OK":
            failures.append({"failure_bucket": "lns_gate_not_ok", "status": row.get("gate_status"), "reason": row.get("failure_reason", "")})
        if int(as_float(row.get("actual_evals"))) < 2000:
            failures.append({"failure_bucket": "lns_under_eval", "actual": row.get("actual_evals"), "expected": 2000})
    if anchor_parity and not anchor_parity.get("parity_ok"):
        failures.append({"failure_bucket": "anchor_parity_failed", "anchor_parity": anchor_parity})
    if protected_diff():
        failures.append({"failure_bucket": "protected_file_diff", "paths": protected_diff()})
    return failures


def render_report(
    metadata: dict[str, Any],
    decision: dict[str, Any],
    phase_a_rows: list[dict[str, Any]],
    convention_rows: list[dict[str, Any]],
    selected_case: dict[str, Any],
    lns_rows: list[dict[str, Any]],
    anchor_parity: dict[str, Any],
    legacy_anchor: dict[str, Any],
) -> str:
    lns_summary = next((row for row in lns_rows if row.get("row_type") == "run_summary"), {})
    lines = [
        "# C1-R1b Bridge-Side Repair Validation",
        "",
        "本步目标：让 baseline 的 destroy/repair 桥在 5174 平台解上能产出可行邻居，同时不改变 ALNS 主算法任何行为。",
        "",
        "Evidence level: **PROBE / baseline health整改**。这不是正式 T3，不得写算法胜负。",
        "",
        "边界：只允许修 `candidates.py` 桥侧调用约定；不改 `feasible_repair.py`、独立 ALNS 后端、成本、约束、价格默认值或 TeX。",
        "",
        f"Verdict: `{decision.get('verdict')}`",
        "",
        "## Plain Reading",
        "",
        str(decision.get("plain", "")),
        "",
        "## Phase A None Exit",
        "",
        "| policy | none exit | count |",
        "|---|---|---:|",
    ]
    for (policy, none_exit), count in sorted(phase_a_histogram(phase_a_rows).items()):
        lines.append(f"| {policy} | {none_exit} | {count} |")
    lines.extend([
        "",
        "## Call Convention Diff",
        "",
        "| field | baseline bridge | main ALNS | risk |",
        "|---|---|---|---|",
    ])
    for row in convention_rows:
        lines.append(f"| {row['field']} | {row['baseline_bridge']} | {row['main_alns']} | {row['risk']} |")
    lines.extend([
        "",
        "## Selected Regression Case",
        "",
        "```json",
        json.dumps(selected_case, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "## D1 LNS Probe",
        "",
        f"- status: `{lns_summary.get('gate_status', 'SKIPPED')}`",
        f"- evals: `{lns_summary.get('actual_evals', 'SKIPPED')}`",
        f"- best cost: `{lns_summary.get('best_cost', 'SKIPPED')}`",
        f"- feasible native 20-40 route candidates: `{lns_summary.get('bridge_feasible_route_20_40_count', 'SKIPPED')}`",
        f"- native best updates: `{lns_summary.get('native_best_updates', 'SKIPPED')}`",
        "",
        "## D2 Anchors",
        "",
    ])
    if anchor_parity:
        for row in anchor_parity.get("anchors", []):
            lines.append(f"- {row['anchor']}: cost `{row['best_cost']}`, expected `{row['expected_best_cost']}`, parity `{row['parity_ok']}`.")
    else:
        lines.append("- skipped")
    lines.extend([
        "",
        "## D4 Legacy Anchor",
        "",
        "```json",
        json.dumps(legacy_anchor or {"status": "SKIPPED"}, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
    ])
    if decision.get("failure_sample"):
        lines.extend(["", "## Failure Sample", "", "```json", json.dumps(decision["failure_sample"], ensure_ascii=False, indent=2), "```"])
    lines.extend([
        "",
        "## Artifacts",
        "",
        f"- Data dir: `{metadata.get('output_dir')}`",
        "- `phase_a_bridge_exit_autopsy.csv`",
        "- `call_convention_diff.csv`",
        "- `selected_regression_case.json`",
        "- `lns_b1_raw_runs.csv`",
        "- `anchor_parity.json`",
        "- `legacy_q1600_anchor.json`",
        "- `decision.json`",
        "- `artifact_hashes.json`",
        "",
    ])
    return "\n".join(lines)


def phase_a_histogram(rows: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    histogram: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (str(row.get("policy_name")), str(row.get("none_exit")))
        histogram[key] = histogram.get(key, 0) + 1
    return histogram


def phase_a_histogram_json(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {f"{policy}|{none_exit}": count for (policy, none_exit), count in phase_a_histogram(rows).items()}


def make_probe_prices() -> Any:
    return replace(DEFAULT_PRICES, B_battery_kwh=BATTERY_KWH, carbon_price=CARBON_PRICE)


def load_platform_solution() -> Solution:
    rows = read_csv(FLIP_CLOSURE_CSV)
    for row in rows:
        if row.get("closure_type") == "random_seeded_flip" and str(row.get("seed")) == "1":
            return solution_from_dict(json.loads(row["solution_json"]))
    if rows:
        return solution_from_dict(json.loads(rows[0]["solution_json"]))
    raise RuntimeError(f"no platform solution found in {FLIP_CLOSURE_CSV}")


def _instance_limit(instance: Any, attr: str) -> int:
    value = getattr(instance, attr, None)
    if value is None:
        return 10**9
    return int(float(value))


def violation_type_counts(violations: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for violation in violations:
        key = str(getattr(violation, "type", "UNKNOWN"))
        counts[key] = counts.get(key, 0) + 1
    return counts


def protected_diff() -> list[str]:
    cmd = [
        "git",
        "diff",
        "--name-only",
        "HEAD",
        "--",
        "solver/src/setp_solver/cost.py",
        "solver/src/setp_solver/check.py",
        "solver/src/setp_solver/search/evaluation.py",
        "solver/src/setp_solver/prices.py",
        "docs/paper_submission_final/paper_main.tex",
        "solver/src/setp_solver/search/feasible_repair.py",
        "solver/src/setp_solver/search/resetp_alns",
        "solver/src/setp_solver/search/alns_wouda.py",
        "solver/src/setp_solver/search/winner_operators.py",
        "solver/src/setp_solver/search/carbon_operators.py",
    ]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False, text=True, capture_output=True)
    return [line for line in proc.stdout.splitlines() if line.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def artifact_hashes(output_dir: Path) -> dict[str, Any]:
    entries: dict[str, str] = {}
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name in HASH_EXCLUDE_NAMES or path.name.startswith("._"):
            continue
        if any(part in HASH_EXCLUDE_PARTS for part in path.parts):
            continue
        entries[str(path.relative_to(output_dir))] = sha256_file(path)
    return {"schema": "setp-c1-r1b-artifact-hashes.v1", "files": entries}


def clean_artifact_dir(output_dir: Path) -> None:
    for path in list(output_dir.rglob("._*")):
        if path.is_file():
            path.unlink()
    for path in list(output_dir.rglob("__pycache__")) + list(output_dir.rglob(".pytest_cache")):
        if path.is_dir():
            shutil.rmtree(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()


def numpy_version() -> str:
    try:
        import numpy as np

        return str(np.__version__)
    except Exception:
        return "UNKNOWN"


def as_float(value: Any, default: float = math.nan) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


if __name__ == "__main__":
    raise SystemExit(main())
