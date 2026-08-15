#!/usr/bin/env python3
"""C1-R1a/R3 decoder-fix validation and destroy/repair bridge autopsy.

This runner is a baseline-health probe, not a formal T3 experiment. It verifies
that the random-key decoder no longer creates only one-customer routes, then
measures why the strong ALNS destroy/repair bridge fails on the 5174 platform.
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
from setp_solver.instance_loader import Instance, Node
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import SearchBundle, load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution, solution_signature_hash
from setp_solver.search import candidates as candidate_module
from setp_solver.search import metaheuristic_baselines as mb
from setp_solver.search.evaluation import EvalBudget, EvaluationContext
from setp_solver.search.metaheuristic_baselines import run_metaheuristic_baseline, solution_from_dict
from setp_solver.solution import Solution

from baselines.e2_alns import native_channel_autopsy as c1r2


GOLD_PYTHON = "/opt/anaconda3/bin/python3.13"
GOLD_NUMPY = "2.3.5"
CARBON_PRICE = 0.05034
BATTERY_KWH = 280.0
PLATFORM_COST = 5174.345121253789
PROBE_LEVEL = "PROBE / 非正式 T3"
INSTANCE_CATEGORY = "threeshift"
INSTANCE_NAME = "e2-threeshift-150c-01"
INSTANCE_SIZE = 150
INSTANCE_ROOT = REPO_ROOT / "models/data_bundle/generated_instances/e2_benchmark"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/decoder_fix_validation_data"
DEFAULT_REPORT_PATH = REPO_ROOT / "baselines/e2_alns/decoder_fix_validation.md"
PRE_FIX_DECODE_EVENTS = REPO_ROOT / "baselines/e2_alns/native_channel_autopsy_data/decode_events.csv"
FLIP_CLOSURE_CSV = REPO_ROOT / "baselines/e2_alns/native_channel_autopsy_data/flip_closure.csv"
HASH_EXCLUDE_DIRS = {"__pycache__", ".pytest_cache"}
HASH_EXCLUDE_NAMES = {"artifact_hashes.json"}
DESTROY_OPS = [
    "random_customer_removal",
    "shaw_related_removal",
    "worst_customer_removal",
    "whole_route_removal",
    "route_segment_removal",
]
REPAIR_OPS = ["greedy_insert_repair", "regret2_insert_repair", "regret3_insert_repair"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--eval-budget", type=int, default=2000)
    parser.add_argument("--runtime-cap-seconds", type=float, default=600.0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--bridge-trials", type=int, default=200)
    parser.add_argument("--skip-runs", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = repo_path(Path(args.output_dir))
    report_path = repo_path(Path(args.report_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    clean_appledouble(output_dir)

    metadata = build_metadata(output_dir, report_path, args)
    model_audit = model_intent_audit()
    phase0 = phase0_audit()
    micro_check = decoder_micro_check()
    pre_fix_summary = pre_fix_decode_summary()
    write_json(output_dir / "metadata.json", metadata)
    write_json(output_dir / "model_intent_audit.json", model_audit)
    write_json(output_dir / "phase0_audit.json", phase0)
    write_json(output_dir / "decoder_micro_check.json", micro_check)
    write_json(output_dir / "pre_fix_decode_summary.json", pre_fix_summary)

    raw_rows: list[dict[str, Any]] = []
    decode_rows: list[dict[str, Any]] = []
    trajectory_rows: list[dict[str, Any]] = []
    bridge_rows: list[dict[str, Any]] = []
    bridge_summary: list[dict[str, Any]] = []

    if args.skip_runs or not phase0["phase0_ok"] or not model_audit["model_intent_ok"] or not micro_check["decoder_micro_check_ok"]:
        decision = halt_decision(args, phase0, model_audit, micro_check, raw_rows, decode_rows, bridge_rows)
    else:
        for algorithm in ("GA", "PSO"):
            row, candidates, decodes, trajectory = run_decoder_probe(
                algorithm=algorithm,
                seed=int(args.seed),
                eval_budget=int(args.eval_budget),
                runtime_cap_seconds=float(args.runtime_cap_seconds),
            )
            raw_rows.extend(candidates)
            raw_rows.append(row)
            decode_rows.extend(decodes)
            trajectory_rows.extend(trajectory)
            write_csv(output_dir / "raw_runs.csv", raw_rows)
            write_csv(output_dir / "decode_events.csv", decode_rows)
            write_csv(output_dir / "best_trajectory.csv", trajectory_rows)

        if post_decode_still_all_150(decode_rows):
            decision = decide(args, phase0, model_audit, micro_check, pre_fix_summary, raw_rows, decode_rows, bridge_rows, bridge_summary)
        else:
            bridge_rows = run_bridge_autopsy(trials=int(args.bridge_trials), seed=int(args.seed))
            bridge_summary = summarize_bridge(bridge_rows)
            write_csv(output_dir / "bridge_autopsy.csv", bridge_rows)
            write_csv(output_dir / "bridge_summary.csv", bridge_summary)
            decision = decide(args, phase0, model_audit, micro_check, pre_fix_summary, raw_rows, decode_rows, bridge_rows, bridge_summary)

    write_csv(output_dir / "raw_runs.csv", raw_rows)
    write_csv(output_dir / "decode_events.csv", decode_rows)
    write_csv(output_dir / "best_trajectory.csv", trajectory_rows)
    write_csv(output_dir / "bridge_autopsy.csv", bridge_rows)
    write_csv(output_dir / "bridge_summary.csv", bridge_summary)
    write_json(output_dir / "decision.json", decision)
    report_path.write_text(render_report(metadata, model_audit, phase0, micro_check, pre_fix_summary, decision, raw_rows, decode_rows, bridge_summary), encoding="utf-8")
    clean_appledouble(output_dir)
    write_json(output_dir / "artifact_hashes.json", artifact_hashes(output_dir, report_path))
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))


def build_metadata(output_dir: Path, report_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema": "setp-c1-r1a-r3-decoder-fix-validation.v1",
        "task": "C1-R1a/R3 decoder marginal repair and bridge autopsy",
        "evidence_level": PROBE_LEVEL,
        "repo_root": str(REPO_ROOT),
        "output_dir": str(output_dir.relative_to(REPO_ROOT)),
        "report_path": str(report_path.relative_to(REPO_ROOT)),
        "head": git_head(),
        "python": sys.executable,
        "numpy": numpy_version(),
        "instance": INSTANCE_NAME,
        "category": INSTANCE_CATEGORY,
        "size": INSTANCE_SIZE,
        "seed": int(args.seed),
        "eval_budget": int(args.eval_budget),
        "runtime_cap_seconds": float(args.runtime_cap_seconds),
        "bridge_trials": int(args.bridge_trials),
        "battery_kwh": BATTERY_KWH,
        "carbon_price": CARBON_PRICE,
        "platform_cost": PLATFORM_COST,
        "decision_boundary": "baseline health probe; not formal T3; no algorithm win/loss claim",
        "modeling_decision": "不改建模；只修 baseline decoder 实现偏差；固定费仍按每趟/每次派遣口径。",
        "protected_semantics": ["cost.py", "check.py", "search/evaluation.py", "prices.py defaults", "TeX model equations"],
        "started_at_epoch": time.time(),
    }


def phase0_audit() -> dict[str, Any]:
    numpy = numpy_version()
    default_probe = {
        "python": sys.executable,
        "numpy": numpy,
        "default_B_battery_kwh": float(DEFAULT_PRICES.B_battery_kwh),
        "default_carbon_price": float(DEFAULT_PRICES.carbon_price),
        "override_B_battery_kwh": BATTERY_KWH,
        "override_carbon_price": CARBON_PRICE,
    }
    return {
        "phase0_ok": str(Path(sys.executable)) == GOLD_PYTHON and numpy == GOLD_NUMPY and abs(float(DEFAULT_PRICES.B_battery_kwh) - 80.0) <= 1e-9,
        "default_probe": default_probe,
    }


def model_intent_audit() -> dict[str, Any]:
    cost_text = (REPO_ROOT / "solver/src/setp_solver/cost.py").read_text(encoding="utf-8")
    prices_text = (REPO_ROOT / "solver/src/setp_solver/prices.py").read_text(encoding="utf-8")
    tex_text = (REPO_ROOT / "docs/paper_submission_final/RETIRED_paper_main.tex").read_text(encoding="utf-8")
    checks = {
        "cost_has_route_fixed_cost": "cost_fix = len(solution.routes) * _price(prices, \"vehicle_fixed_cost\")" in cost_text,
        "cost_has_km_cost": "cost_km = (distance_total / 1000.0) * _price(prices, \"c_km\")" in cost_text,
        "prices_fixed_cost_per_shift": "vehicle_fixed_cost = 80.0" in prices_text and "£/班次" in prices_text,
        "prices_has_c_km": "c_km = 0.35" in prices_text and "£/km" in prices_text,
        "tex_objective_fixed_and_km": "c_k^{fix}z_k" in tex_text and "c_k^{km}d_{ij}x_{ijk}" in tex_text,
        "tex_fixed_cost_dispatch_text": "车辆固定成本按派遣车辆计费" in tex_text and "£/班次" in tex_text,
    }
    return {
        "model_intent_ok": all(checks.values()),
        "checks": checks,
        "decision": "不改建模；固定费沿用每趟/每次派遣口径，不改为每实体车固定费，不引入 fleet-size-and-mix。",
    }


def decoder_micro_check() -> dict[str, Any]:
    bundle = tiny_two_customer_bundle()
    session = mb._SearchSession("GA", bundle, 1, 8, 120.0, Solution(), prices=DEFAULT_PRICES)
    plans: dict[str, list[list[str]]] = {"D0": []}
    for customer_id in ("C1", "C2"):
        mb._append_customer_to_cached_plan(customer_id, plans, session)
    return {
        "decoder_micro_check_ok": plans["D0"] == [["C1", "C2"]],
        "plans": plans,
        "expected": [["C1", "C2"]],
    }


def tiny_two_customer_bundle() -> SearchBundle:
    nodes = [
        Node("D0", "d", 0.0, 0.0, demand=0.0, ready_time=0.0, due_time=100_000.0, service_time=0.0),
        Node("C1", "c", 1000.0, 100.0, demand=10.0, ready_time=0.0, due_time=100_000.0, service_time=0.0),
        Node("C2", "c", 1100.0, 0.0, demand=10.0, ready_time=0.0, due_time=100_000.0, service_time=0.0),
    ]
    matrix = [
        [0.0, 1004.987562112089, 1100.0],
        [1004.987562112089, 0.0, 141.4213562373095],
        [1100.0, 141.4213562373095, 0.0],
    ]
    return SearchBundle(Path("."), Instance(nodes=nodes, distance_matrix=matrix, num_cv=3, num_ev=0), [])


def pre_fix_decode_summary() -> dict[str, Any]:
    if not PRE_FIX_DECODE_EVENTS.exists():
        return {"available": False, "path": str(PRE_FIX_DECODE_EVENTS.relative_to(REPO_ROOT))}
    rows = read_csv(PRE_FIX_DECODE_EVENTS)
    out: dict[str, Any] = {"available": True, "path": str(PRE_FIX_DECODE_EVENTS.relative_to(REPO_ROOT)), "rows": len(rows), "by_algorithm": {}}
    for algorithm in ("GA", "PSO"):
        subset = [row for row in rows if row.get("algorithm") == algorithm]
        counts = [int(as_float(row.get("decoded_route_count"))) for row in subset if math.isfinite(as_float(row.get("decoded_route_count")))]
        costs = finite_values(row.get("decoded_cost") for row in subset)
        out["by_algorithm"][algorithm] = {
            "rows": len(subset),
            "route_count_min": min(counts) if counts else None,
            "route_count_p50": statistics.median(counts) if counts else None,
            "route_count_max": max(counts) if counts else None,
            "unique_route_counts": sorted(set(counts)),
            "cost_min": min(costs) if costs else None,
            "cost_p50": statistics.median(costs) if costs else None,
        }
    return out


def run_decoder_probe(*, algorithm: str, seed: int, eval_budget: int, runtime_cap_seconds: float) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    prices = make_probe_prices()
    bundle = load_search_bundle(bundle_dir())
    initial_solution = make_shared_initial_solution(bundle, prices=prices)
    initial_metrics = evaluate(initial_solution, bundle.instance, bundle.carbon_profile, prices)
    run_id = f"A4_{algorithm}_post_decoder_fix_seed{seed}"
    tracer = c1r2.NativeProbeTracer(
        run_id=run_id,
        phase="A4",
        algorithm=algorithm,
        condition="post_decoder_fix",
        seed=int(seed),
        candidate_rows=[],
        decode_rows=[],
        trajectory_rows=[],
        order_stack=[],
    )
    started = time.perf_counter()
    try:
        with c1r2.instrument_baseline(tracer):
            result = run_metaheuristic_baseline(
                algorithm,
                bundle.bundle_dir,
                seed=int(seed),
                eval_budget=int(eval_budget),
                max_runtime_seconds=float(runtime_cap_seconds),
                initial_solution=initial_solution,
                prices=prices,
            )
    except Exception as exc:
        return task_failure_row(algorithm, seed, eval_budget, runtime_cap_seconds, started, repr(exc)), tracer.candidate_rows, tracer.decode_rows, tracer.trajectory_rows

    solution = result.best_solution
    violations = check_solution(solution, bundle.instance, prices) if solution is not None else []
    final_metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices) if solution is not None and not violations else {}
    route_counts = [int(as_float(row.get("decoded_route_count"))) for row in tracer.decode_rows if math.isfinite(as_float(row.get("decoded_route_count")))]
    decoded_costs = finite_values(row.get("decoded_cost") for row in tracer.decode_rows)
    row = {
        "row_type": "run_summary",
        "run_id": run_id,
        "phase": "A4",
        "category": INSTANCE_CATEGORY,
        "instance": INSTANCE_NAME,
        "size": INSTANCE_SIZE,
        "seed": int(seed),
        "algorithm": algorithm,
        "condition": "post_decoder_fix",
        "battery_kwh": BATTERY_KWH,
        "status": result.status if not violations else "HALT_INFEASIBLE",
        "gate_status": "OK" if result.status == "OK" and not violations else result.status,
        "failure_reason": result.failure_reason if not violations else "; ".join(str(item) for item in violations[:3]),
        "seed_source": "rebuilt_make_shared_initial_solution",
        "initial_cost": float(initial_metrics["total_cost"]),
        "best_cost": float(result.best_cost) if result.best_cost is not None else math.inf,
        "replay_best_cost": as_float(final_metrics.get("total_cost")),
        "actual_evals": int(result.evals),
        "eval_budget": int(eval_budget),
        "elapsed_seconds": time.perf_counter() - started,
        "runtime_cap_seconds": float(runtime_cap_seconds),
        "violation_count": len(violations),
        "candidate_rows": len(tracer.candidate_rows),
        "decode_events": len(tracer.decode_rows),
        "decode_cache_hit_rate": safe_ratio(sum(1 for item in tracer.decode_rows if boolish(item.get("cache_hit"))), len(tracer.decode_rows)),
        "decode_fallback_rate": safe_ratio(sum(1 for item in tracer.decode_rows if boolish(item.get("fallback_called"))), len(tracer.decode_rows)),
        "decode_cost_lt_platform_count": sum(1 for item in tracer.decode_rows if as_float(item.get("decoded_cost")) < PLATFORM_COST - 1e-9),
        "decode_cost_lt_platform_rate": safe_ratio(sum(1 for item in tracer.decode_rows if as_float(item.get("decoded_cost")) < PLATFORM_COST - 1e-9), len(tracer.decode_rows)),
        "decoded_route_count_min": min(route_counts) if route_counts else math.nan,
        "decoded_route_count_p50": statistics.median(route_counts) if route_counts else math.nan,
        "decoded_route_count_max": max(route_counts) if route_counts else math.nan,
        "decoded_route_count_unique": json.dumps(sorted(set(route_counts)), ensure_ascii=False),
        "decoded_cost_min": min(decoded_costs) if decoded_costs else math.nan,
        "decoded_cost_p50": statistics.median(decoded_costs) if decoded_costs else math.nan,
        "post_fix_all_route_count_150": bool(route_counts) and all(count == INSTANCE_SIZE for count in route_counts),
        "best_signature": solution_signature_hash(solution) if solution is not None else "",
        "best_route_count": len(solution.routes) if solution is not None else 0,
        "best_ev_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev") if solution is not None else 0,
        "best_charging_action_count": len(solution.charging_actions) if solution is not None else 0,
        "history_json": json.dumps(result.history, ensure_ascii=False, sort_keys=True),
        "operator_counts": json.dumps(result.operator_counts, ensure_ascii=False, sort_keys=True),
        "python": sys.executable,
        "numpy": numpy_version(),
    }
    return row, tracer.candidate_rows, tracer.decode_rows, tracer.trajectory_rows


def run_bridge_autopsy(*, trials: int, seed: int) -> list[dict[str, Any]]:
    prices = make_probe_prices()
    bundle = load_search_bundle(bundle_dir())
    context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices, budget=EvalBudget(limit=trials, target=trials))
    platform = load_platform_solution()
    base_signature = solution_signature_hash(platform)
    combos = [(destroy, repair) for destroy in DESTROY_OPS for repair in REPAIR_OPS]
    rng = random.Random(int(seed))
    rows: list[dict[str, Any]] = []
    for trial in range(1, int(trials) + 1):
        destroy, repair = combos[(trial - 1) % len(combos)]
        outcome, final_violations = bridge_call_with_violation_capture(platform, context, rng, destroy, repair)
        violation_types = sorted(violation_type_counts(final_violations).items())
        detail = outcome.detail or ("feasible_changed" if outcome.feasible and outcome.changed else "feasible_unchanged" if outcome.feasible else "produced_infeasible")
        rows.append(
            {
                "trial": trial,
                "seed": int(seed),
                "destroy": destroy,
                "repair": repair,
                "produced": bool(outcome.produced),
                "feasible": bool(outcome.feasible),
                "changed": bool(outcome.changed),
                "detail": detail,
                "failure_bucket": failure_bucket(outcome, final_violations, detail),
                "removed_count": outcome.metadata.get("removed_count", ""),
                "violation_count": len(final_violations) if final_violations else int(outcome.violation_count),
                "violation_type_histogram": json.dumps(dict(violation_types), ensure_ascii=False, sort_keys=True),
                "dominant_violation_type": violation_types[0][0] if len(violation_types) == 1 else "",
                "candidate_signature": solution_signature_hash(outcome.solution),
                "same_as_platform": solution_signature_hash(outcome.solution) == base_signature,
            }
        )
    return rows


def bridge_call_with_violation_capture(solution: Solution, context: EvaluationContext, rng: random.Random, destroy: str, repair: str) -> tuple[Any, list[Any]]:
    captured: list[list[Any]] = []
    original_check = candidate_module.check_solution

    def recording_check(candidate: Solution, instance: Instance, prices: Any = DEFAULT_PRICES, **kwargs: Any) -> list[Any]:
        violations = original_check(candidate, instance, prices, **kwargs)
        captured.append(violations)
        return violations

    try:
        candidate_module.check_solution = recording_check
        outcome = candidate_module._apply_strong_alns_destroy_repair(solution, context, rng, destroy, repair)
    finally:
        candidate_module.check_solution = original_check
    return outcome, captured[-1] if captured else []


def summarize_bridge(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["destroy"]), str(row["repair"])), []).append(row)
    out: list[dict[str, Any]] = []
    for (destroy, repair), subset in sorted(grouped.items()):
        buckets: dict[str, int] = {}
        for row in subset:
            buckets[str(row["failure_bucket"])] = buckets.get(str(row["failure_bucket"]), 0) + 1
        dominant_bucket, dominant_count = max(buckets.items(), key=lambda item: item[1]) if buckets else ("", 0)
        out.append(
            {
                "destroy": destroy,
                "repair": repair,
                "trials": len(subset),
                "produced_count": sum(1 for row in subset if boolish(row.get("produced"))),
                "feasible_count": sum(1 for row in subset if boolish(row.get("feasible"))),
                "changed_count": sum(1 for row in subset if boolish(row.get("changed"))),
                "dominant_failure_bucket": dominant_bucket,
                "dominant_failure_count": dominant_count,
                "dominant_failure_rate": safe_ratio(dominant_count, len(subset)),
                "failure_histogram": json.dumps(buckets, ensure_ascii=False, sort_keys=True),
            }
        )
    return out


def decide(
    args: argparse.Namespace,
    phase0: dict[str, Any],
    model_audit: dict[str, Any],
    micro_check: dict[str, Any],
    pre_fix_summary: dict[str, Any],
    raw_rows: list[dict[str, Any]],
    decode_rows: list[dict[str, Any]],
    bridge_rows: list[dict[str, Any]],
    bridge_summary: list[dict[str, Any]],
) -> dict[str, Any]:
    failures = collection_failures(args, phase0, model_audit, micro_check, raw_rows, decode_rows, bridge_rows)
    decoder_fixed = not failures and not post_decode_still_all_150(decode_rows) and post_route_count_diverse(decode_rows)
    if failures:
        verdict = "HALT_COLLECTION_COST"
        plain = "环境、模型口径、run 闭合、trace 或 hash 前置门未过；停止采集。"
        bridge_decision = "BRIDGE_NOT_RUN"
    elif not decoder_fixed:
        verdict = "DECODER_FIX_INSUFFICIENT"
        plain = "修复后解码候选仍没有摆脱单客路线盆地；按预注册停止，不做加料硬修。"
        bridge_decision = "BRIDGE_NOT_RUN"
    else:
        bridge_decision = bridge_cause_decision(bridge_rows)
        verdict = "DECODER_FIXED_AND_" + bridge_decision
        plain = "解码器已恢复多客户路线候选；桥尸检已完成。本结论只说明 baseline health probe，不是算法胜负。"
    route_counts = [int(as_float(row.get("decoded_route_count"))) for row in decode_rows if math.isfinite(as_float(row.get("decoded_route_count")))]
    costs = finite_values(row.get("decoded_cost") for row in decode_rows)
    return {
        "verdict": verdict,
        "plain": plain,
        "decoder_decision": "DECODER_FIXED" if decoder_fixed else "DECODER_FIX_INSUFFICIENT" if not failures else "DECODER_UNRESOLVED",
        "bridge_decision": bridge_decision,
        "collection_failure_count": len(failures),
        "failure_sample": failures[:20],
        "model_intent_ok": bool(model_audit.get("model_intent_ok")),
        "decoder_micro_check_ok": bool(micro_check.get("decoder_micro_check_ok")),
        "run_summary_rows": len([row for row in raw_rows if row.get("row_type") == "run_summary"]),
        "expected_run_summary_rows": 2,
        "candidate_rows": len([row for row in raw_rows if row.get("row_type") == "candidate"]),
        "decode_rows": len(decode_rows),
        "bridge_rows": len(bridge_rows),
        "decoded_route_count_min": min(route_counts) if route_counts else None,
        "decoded_route_count_p50": statistics.median(route_counts) if route_counts else None,
        "decoded_route_count_max": max(route_counts) if route_counts else None,
        "decoded_route_count_unique_count": len(set(route_counts)),
        "decoded_cost_min": min(costs) if costs else None,
        "decoded_cost_p50": statistics.median(costs) if costs else None,
        "decoded_cost_lt_platform_count": sum(1 for row in decode_rows if as_float(row.get("decoded_cost")) < PLATFORM_COST - 1e-9),
        "decoded_cost_lt_platform_rate": safe_ratio(sum(1 for row in decode_rows if as_float(row.get("decoded_cost")) < PLATFORM_COST - 1e-9), len(decode_rows)),
        "pre_fix_decode_summary": pre_fix_summary,
        "bridge_global_failure_histogram": global_bridge_histogram(bridge_rows),
    }


def collection_failures(
    args: argparse.Namespace,
    phase0: dict[str, Any],
    model_audit: dict[str, Any],
    micro_check: dict[str, Any],
    raw_rows: list[dict[str, Any]],
    decode_rows: list[dict[str, Any]],
    bridge_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    if not phase0.get("phase0_ok"):
        failures.append({"failure_bucket": "phase0_env_mismatch", "phase0": phase0})
    if not model_audit.get("model_intent_ok"):
        failures.append({"failure_bucket": "HALT_MODEL_INTENT_UNRESOLVED", "checks": model_audit.get("checks")})
    if not micro_check.get("decoder_micro_check_ok"):
        failures.append({"failure_bucket": "decoder_micro_check_failed", "micro_check": micro_check})
    summaries = [row for row in raw_rows if row.get("row_type") == "run_summary"]
    if len(summaries) != 2:
        failures.append({"failure_bucket": "missing_run_summary_rows", "actual": len(summaries), "expected": 2})
    for row in summaries:
        if row.get("gate_status") != "OK":
            failures.append({"failure_bucket": "run_status_not_ok", "run_id": row.get("run_id"), "status": row.get("status")})
        if int(as_float(row.get("actual_evals"))) < int(args.eval_budget):
            failures.append({"failure_bucket": "under_eval", "run_id": row.get("run_id"), "actual": row.get("actual_evals"), "expected": args.eval_budget})
        if row.get("python") != GOLD_PYTHON or row.get("numpy") != GOLD_NUMPY:
            failures.append({"failure_bucket": "env_mismatch", "run_id": row.get("run_id"), "python": row.get("python"), "numpy": row.get("numpy")})
    if not any(row.get("row_type") == "candidate" for row in raw_rows):
        failures.append({"failure_bucket": "candidate_trace_missing"})
    if not decode_rows:
        failures.append({"failure_bucket": "decode_trace_missing"})
    if bridge_rows and len(bridge_rows) != int(args.bridge_trials):
        failures.append({"failure_bucket": "bridge_under_trials", "actual": len(bridge_rows), "expected": int(args.bridge_trials)})
    return failures


def bridge_cause_decision(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "BRIDGE_NOT_RUN"
    histogram = global_bridge_histogram(rows)
    if not histogram:
        return "BRIDGE_CAUSE_MIXED_COMPLETE"
    dominant_count = max(histogram.values())
    if safe_ratio(dominant_count, len(rows)) > 0.50:
        return "BRIDGE_CAUSE_LOCATED"
    return "BRIDGE_CAUSE_MIXED_COMPLETE"


def global_bridge_histogram(rows: list[dict[str, Any]]) -> dict[str, int]:
    histogram: dict[str, int] = {}
    for row in rows:
        key = str(row.get("failure_bucket", "UNKNOWN"))
        histogram[key] = histogram.get(key, 0) + 1
    return dict(sorted(histogram.items(), key=lambda item: (-item[1], item[0])))


def post_decode_still_all_150(decode_rows: list[dict[str, Any]]) -> bool:
    counts = [int(as_float(row.get("decoded_route_count"))) for row in decode_rows if math.isfinite(as_float(row.get("decoded_route_count")))]
    return bool(counts) and all(count == INSTANCE_SIZE for count in counts)


def post_route_count_diverse(decode_rows: list[dict[str, Any]]) -> bool:
    counts = [int(as_float(row.get("decoded_route_count"))) for row in decode_rows if math.isfinite(as_float(row.get("decoded_route_count")))]
    return len(set(counts)) > 1 or (bool(counts) and statistics.median(counts) < INSTANCE_SIZE)


def halt_decision(
    args: argparse.Namespace,
    phase0: dict[str, Any],
    model_audit: dict[str, Any],
    micro_check: dict[str, Any],
    raw_rows: list[dict[str, Any]],
    decode_rows: list[dict[str, Any]],
    bridge_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return decide(args, phase0, model_audit, micro_check, {}, raw_rows, decode_rows, bridge_rows, [])


def load_platform_solution() -> Solution:
    rows = read_csv(FLIP_CLOSURE_CSV)
    for row in rows:
        if row.get("closure_type") == "random_seeded_flip" and str(row.get("seed")) == "1":
            return solution_from_dict(json.loads(row["solution_json"]))
    if rows:
        return solution_from_dict(json.loads(rows[0]["solution_json"]))
    raise RuntimeError(f"no platform solution found in {FLIP_CLOSURE_CSV}")


def failure_bucket(outcome: Any, violations: list[Any], detail: str) -> str:
    if detail == "strong_repair_failed":
        return "REPAIR_NONE"
    if not outcome.produced:
        return detail
    if outcome.feasible and outcome.changed:
        return "FEASIBLE_CHANGED"
    if outcome.feasible:
        return "FEASIBLE_UNCHANGED"
    counts = violation_type_counts(violations)
    if counts:
        return max(counts.items(), key=lambda item: item[1])[0]
    return detail or "PRODUCED_INFEASIBLE_UNKNOWN"


def violation_type_counts(violations: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for violation in violations:
        key = str(getattr(violation, "type", "UNKNOWN"))
        counts[key] = counts.get(key, 0) + 1
    return counts


def task_failure_row(algorithm: str, seed: int, eval_budget: int, runtime_cap_seconds: float, started: float, reason: str) -> dict[str, Any]:
    return {
        "row_type": "run_summary",
        "run_id": f"A4_{algorithm}_post_decoder_fix_seed{seed}",
        "phase": "A4",
        "category": INSTANCE_CATEGORY,
        "instance": INSTANCE_NAME,
        "size": INSTANCE_SIZE,
        "seed": int(seed),
        "algorithm": algorithm,
        "condition": "post_decoder_fix",
        "battery_kwh": BATTERY_KWH,
        "status": "HALT_WORKER_EXCEPTION",
        "gate_status": "HALT_WORKER_EXCEPTION",
        "failure_reason": reason,
        "actual_evals": 0,
        "eval_budget": int(eval_budget),
        "elapsed_seconds": time.perf_counter() - started,
        "runtime_cap_seconds": float(runtime_cap_seconds),
        "python": sys.executable,
        "numpy": numpy_version(),
    }


def render_report(
    metadata: dict[str, Any],
    model_audit: dict[str, Any],
    phase0: dict[str, Any],
    micro_check: dict[str, Any],
    pre_fix_summary: dict[str, Any],
    decision: dict[str, Any],
    raw_rows: list[dict[str, Any]],
    decode_rows: list[dict[str, Any]],
    bridge_summary: list[dict[str, Any]],
) -> str:
    summaries = [row for row in raw_rows if row.get("row_type") == "run_summary"]
    lines = [
        "# C1-R1a/R3 Decoder Fix Validation",
        "",
        "本步目标：让基线的两条死通道恢复生命体征：(a) 修复解码器“绝对距离比较”bug，让排列→解码路径能产出多客户路线；(b) 查清 `_apply_strong_alns_destroy_repair` 桥在 5174 平台解上失效的微观死因。",
        "",
        f"Evidence level: **{PROBE_LEVEL}**. 这是 baseline 健康整改探针，不是正式 T3，不得写成算法胜负。",
        "",
        "拍板边界：不改建模，只修 baseline decoder 实现偏差；固定费仍按现有 `£/班次 / 每趟派遣` 口径使用，不改成每实体车固定费，不引入 fleet-size-and-mix。",
        "",
        f"Verdict: `{decision.get('verdict')}`",
        "",
        "## Plain Reading",
        "",
        str(decision.get("plain", "")),
        "",
        "## Gates",
        "",
        f"- Model intent audit: `{model_audit.get('model_intent_ok')}`",
        f"- Phase0 env: `{phase0.get('phase0_ok')}` (`{phase0.get('default_probe', {}).get('python')}` / `{phase0.get('default_probe', {}).get('numpy')}`)",
        f"- Decoder micro check: `{micro_check.get('decoder_micro_check_ok')}`",
        f"- Decoder decision: `{decision.get('decoder_decision')}`",
        f"- Bridge decision: `{decision.get('bridge_decision')}`",
        f"- Collection failures: `{decision.get('collection_failure_count')}`",
        f"- HEAD: `{metadata.get('head')}`",
        "- Battery override only in memory: `dataclasses.replace(DEFAULT_PRICES, B_battery_kwh=280.0, carbon_price=0.05034)`.",
        "",
        "## Model Intent Audit",
        "",
        "| check | pass |",
        "|---|---:|",
    ]
    for name, passed in model_audit.get("checks", {}).items():
        lines.append(f"| {name} | {passed} |")
    lines.extend([
        "",
        "## Decoder Summary",
        "",
        "| algorithm | status | evals | decode rows | route count min/p50/max | decoded cost min/p50 | decode <5174 | best cost |",
        "|---|---|---:|---:|---|---|---:|---:|",
    ])
    for row in summaries:
        lines.append(
            "| {algorithm} | {status} | {evals} | {decode_rows} | {rmin}/{rp50}/{rmax} | {cmin:.3f}/{cp50:.3f} | {lt} | {best:.12f} |".format(
                algorithm=row.get("algorithm"),
                status=row.get("status"),
                evals=int(as_float(row.get("actual_evals"))),
                decode_rows=int(as_float(row.get("decode_events"))),
                rmin=fmt_num(row.get("decoded_route_count_min")),
                rp50=fmt_num(row.get("decoded_route_count_p50")),
                rmax=fmt_num(row.get("decoded_route_count_max")),
                cmin=as_float(row.get("decoded_cost_min")),
                cp50=as_float(row.get("decoded_cost_p50")),
                lt=int(as_float(row.get("decode_cost_lt_platform_count"))),
                best=as_float(row.get("best_cost")),
            )
        )
    lines.extend([
        "",
        "修复前 C1-R2 基线摘要：",
        "",
        "```json",
        json.dumps(pre_fix_summary, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
    ])
    if bridge_summary:
        lines.extend([
            "",
            "## Bridge Autopsy",
            "",
            "| destroy | repair | trials | feasible | changed | dominant bucket | rate |",
            "|---|---|---:|---:|---:|---|---:|",
        ])
        for row in bridge_summary:
            lines.append(
                "| {destroy} | {repair} | {trials} | {feasible} | {changed} | {bucket} | {rate:.4f} |".format(
                    destroy=row.get("destroy"),
                    repair=row.get("repair"),
                    trials=int(as_float(row.get("trials"))),
                    feasible=int(as_float(row.get("feasible_count"))),
                    changed=int(as_float(row.get("changed_count"))),
                    bucket=row.get("dominant_failure_bucket"),
                    rate=as_float(row.get("dominant_failure_rate")),
                )
            )
    if decision.get("failure_sample"):
        lines.extend(["", "## Failure Sample", "", "```json", json.dumps(decision.get("failure_sample"), ensure_ascii=False, indent=2), "```"])
    lines.extend([
        "",
        "## Artifacts",
        "",
        f"- Data dir: `{metadata.get('output_dir')}`",
        f"- Candidate rows: `{metadata.get('output_dir')}/raw_runs.csv`",
        f"- Decode rows: `{metadata.get('output_dir')}/decode_events.csv`",
        f"- Bridge rows: `{metadata.get('output_dir')}/bridge_autopsy.csv`",
        f"- Bridge summary: `{metadata.get('output_dir')}/bridge_summary.csv`",
        f"- Decision: `{metadata.get('output_dir')}/decision.json`",
        "",
    ])
    return "\n".join(lines).rstrip() + "\n"


def bundle_dir() -> Path:
    return INSTANCE_ROOT / INSTANCE_CATEGORY / INSTANCE_NAME


def repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def make_probe_prices() -> Any:
    return replace(DEFAULT_PRICES, B_battery_kwh=BATTERY_KWH, carbon_price=CARBON_PRICE)


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


def artifact_hashes(output_dir: Path, report_path: Path) -> dict[str, Any]:
    files = []
    for path in sorted([*output_dir.rglob("*"), report_path]):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(REPO_ROOT).parts if path.is_relative_to(REPO_ROOT) else path.parts
        if path.name.startswith("._") or path.name in HASH_EXCLUDE_NAMES or any(part in HASH_EXCLUDE_DIRS for part in rel_parts):
            continue
        files.append({"path": str(path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path), "sha256": sha256_file(path)})
    return {"schema": "setp-c1-r1a-r3-artifact-hashes.v1", "files": files}


def clean_appledouble(path: Path) -> None:
    if not path.exists():
        return
    for item in path.rglob("._*"):
        if item.is_file():
            item.unlink()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:
        return "UNKNOWN"


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


def finite_values(values: Any) -> list[float]:
    out = []
    for value in values:
        f = as_float(value)
        if math.isfinite(f):
            out.append(f)
    return out


def safe_ratio(num: int, den: int) -> float:
    return float(num) / float(den) if den else 0.0


def fmt_num(value: Any) -> str:
    f = as_float(value)
    if not math.isfinite(f):
        return "nan"
    if abs(f - round(f)) <= 1e-9:
        return str(int(round(f)))
    return f"{f:.2f}"


if __name__ == "__main__":
    main()
