#!/usr/bin/env python3
"""C1-R2 native-channel autopsy probe for the E2 5174 plateau.

This is a PROBE / non-formal T3 runner.  It freezes solver semantics and varies
only runner-side instrumentation plus the registered TRUE_REPAIR A/B switch.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
import csv
from dataclasses import dataclass, replace
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any, Callable, Iterator


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO_ROOT / "solver/src"
MODELS_SRC = REPO_ROOT / "models/src"
for _path in (str(SOLVER_SRC), str(MODELS_SRC), str(REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution, solution_signature_hash
from setp_solver.search.charging import repair_route_charging
from setp_solver.search.fleet import normalize_solution_vehicle_trips
from setp_solver.search import metaheuristic_baselines as mb
from setp_solver.search import order_decoder
from setp_solver.search.metaheuristic_baselines import run_metaheuristic_baseline, solution_to_dict
from setp_solver.solution import Route, Solution


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
DEFAULT_OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/native_channel_autopsy_data"
DEFAULT_REPORT_PATH = REPO_ROOT / "baselines/e2_alns/native_channel_autopsy.md"
HASH_EXCLUDE_DIRS = {"__pycache__", ".pytest_cache"}
HASH_EXCLUDE_NAMES = {"artifact_hashes.json"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--eval-budget", type=int, default=2000)
    parser.add_argument("--runtime-cap-seconds", type=float, default=600.0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--skip-runs", action="store_true", help="write metadata/static checks only")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    report_path = Path(args.report_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    clean_appledouble(output_dir)

    metadata = build_metadata(output_dir, report_path, args)
    write_json(output_dir / "metadata.json", metadata)
    static_checks = static_fact_checks()
    write_json(output_dir / "static_fact_checks.json", static_checks)
    phase0 = phase0_audit()
    write_json(output_dir / "phase0_audit.json", phase0)

    raw_rows: list[dict[str, Any]] = []
    decode_rows: list[dict[str, Any]] = []
    trajectory_rows: list[dict[str, Any]] = []
    closure_rows: list[dict[str, Any]] = []

    if not phase0["phase0_ok"] or not all(row["pass"] for row in static_checks.values()) or args.skip_runs:
        decision = halt_decision("HALT_COLLECTION_COST", "环境或静态核验未闭合；未启动 probe runs。", raw_rows, decode_rows, closure_rows, phase0, static_checks)
    else:
        task_specs = [
            {"phase": "B1", "algorithm": "LNS", "condition": "true_repair_forced_0_current", "seed": int(args.seed)},
            {"phase": "B1", "algorithm": "LNS", "condition": "true_repair_probe_1_no_downgrade", "seed": int(args.seed)},
            {"phase": "B2", "algorithm": "GA", "condition": "decode_probe_current", "seed": int(args.seed)},
            {"phase": "B2", "algorithm": "PSO", "condition": "decode_probe_current", "seed": int(args.seed)},
        ]
        for spec in task_specs:
            row, candidates, decodes, trajectory = run_baseline_probe(
                algorithm=str(spec["algorithm"]),
                condition=str(spec["condition"]),
                phase=str(spec["phase"]),
                seed=int(spec["seed"]),
                eval_budget=int(args.eval_budget),
                runtime_cap_seconds=float(args.runtime_cap_seconds),
            )
            raw_rows.extend(candidates)
            decode_rows.extend(decodes)
            trajectory_rows.extend(trajectory)
            raw_rows.append(row)
            write_csv(output_dir / "raw_runs.csv", raw_rows)
            write_csv(output_dir / "decode_events.csv", decode_rows)
            write_csv(output_dir / "best_trajectory.csv", trajectory_rows)

        closure_rows = run_flip_closure(seed=int(args.seed), runtime_cap_seconds=float(args.runtime_cap_seconds))
        write_csv(output_dir / "flip_closure.csv", closure_rows)
        decision = decide(raw_rows, decode_rows, closure_rows, phase0, static_checks, expected_task_count=len(task_specs))

    write_csv(output_dir / "raw_runs.csv", raw_rows)
    write_csv(output_dir / "decode_events.csv", decode_rows)
    write_csv(output_dir / "best_trajectory.csv", trajectory_rows)
    write_csv(output_dir / "flip_closure.csv", closure_rows)
    write_json(output_dir / "decision.json", decision)
    report_path.write_text(render_report(metadata, phase0, static_checks, decision, raw_rows, decode_rows, closure_rows), encoding="utf-8")
    clean_appledouble(output_dir)
    write_json(output_dir / "artifact_hashes.json", artifact_hashes(output_dir, report_path))
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))


def bundle_dir() -> Path:
    return INSTANCE_ROOT / INSTANCE_CATEGORY / INSTANCE_NAME


def make_probe_prices() -> Any:
    return replace(DEFAULT_PRICES, B_battery_kwh=BATTERY_KWH, carbon_price=CARBON_PRICE)


def build_metadata(output_dir: Path, report_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema": "setp-c1-r2-native-channel-autopsy.v1",
        "evidence_level": PROBE_LEVEL,
        "task": "C1-R2 native channel autopsy",
        "repo_root": str(REPO_ROOT),
        "output_dir": str(output_dir),
        "report_path": str(report_path),
        "head": git_head(),
        "python": sys.executable,
        "numpy": numpy_version(),
        "instance": INSTANCE_NAME,
        "category": INSTANCE_CATEGORY,
        "size": INSTANCE_SIZE,
        "seed": int(args.seed),
        "eval_budget": int(args.eval_budget),
        "runtime_cap_seconds": float(args.runtime_cap_seconds),
        "battery_kwh": BATTERY_KWH,
        "carbon_price": CARBON_PRICE,
        "platform_cost": PLATFORM_COST,
        "seed_source": "rebuilt_make_shared_initial_solution",
        "protected_semantics": ["cost.py", "check.py", "search/evaluation.py", "prices.py defaults", "TeX"],
        "started_at_epoch": time.time(),
    }


def phase0_audit() -> dict[str, Any]:
    default_probe = {
        "Q": float(DEFAULT_PRICES.Q_capacity),
        "B": float(DEFAULT_PRICES.B_battery_kwh),
        "v": float(DEFAULT_PRICES.v_speed_ms),
        "carbon": float(DEFAULT_PRICES.carbon_price),
        "python": sys.executable,
        "numpy": numpy_version(),
    }
    ok = (
        str(Path(sys.executable)) == GOLD_PYTHON
        and default_probe["numpy"] == GOLD_NUMPY
        and abs(default_probe["B"] - 80.0) <= 1e-9
        and abs(default_probe["carbon"] - CARBON_PRICE) <= 1e-12
    )
    return {
        "phase0_ok": ok,
        "default_probe": default_probe,
        "diagnostic_override": {"B_battery_kwh": BATTERY_KWH, "carbon_price": CARBON_PRICE},
    }


def static_fact_checks() -> dict[str, dict[str, Any]]:
    source_fast_flags = inspect.getsource(mb._baseline_fast_repair_flags)
    source_repair = inspect.getsource(__import__("setp_solver.search.repair_scoring", fromlist=["route_model_cost_delta"]).route_model_cost_delta)
    source_winner_flags = inspect.getsource(__import__("setp_solver.search.winner_operators", fromlist=["e2_alns_variant_flags"]).e2_alns_variant_flags)
    # The decoder implementation was extracted into a shared module.  Inspect
    # the implementation rather than the thin compatibility wrappers in
    # metaheuristic_baselines.
    source_decode = inspect.getsource(
        order_decoder.decode_order_like_random_key
    )
    source_route_plan = inspect.getsource(
        order_decoder.route_customer_plan_feasible_cached
    )
    source_check = inspect.getsource(check_solution)
    checks = {
        "A1_baseline_no_longer_forces_true_repair_zero": {
            "pass": not ("SETP_ALNS_CRUSH_TRUE_REPAIR" in source_fast_flags and '"0"' in source_fast_flags),
            "evidence": "metaheuristic_baselines._baseline_fast_repair_flags no longer forces SETP_ALNS_CRUSH_TRUE_REPAIR to 0 after C1-R1d alignment",
        },
        "A2_route_scoring_downgrades_to_distance": {
            "pass": "SETP_ALNS_CRUSH_TRUE_REPAIR" in source_repair and "_route_distance_delta" in source_repair,
            "evidence": "repair_scoring.route_model_cost_delta returns _route_distance_delta when TRUE_REPAIR is disabled",
        },
        "A3_e2_alns_uses_true_repair_one": {
            "pass": '"SETP_ALNS_CRUSH_TRUE_REPAIR": "1"' in source_winner_flags,
            "evidence": "winner_operators.e2_alns_variant_flags sets TRUE_REPAIR to 1",
        },
        "A4_decode_fallback_to_all_cv_on_violations": {
            "pass": "if check_solution(solution" in source_decode and "all_cv_solution_for_order" in source_decode and "return violations" in source_check,
            "evidence": "check_solution returns a violation list; order_decoder.decode_order_like_random_key falls back to the shared all-CV decoder when violations are present",
        },
        "A5_route_plan_feasible_uses_cv_temp_route": {
            "pass": 'Route("TMP", "cv"' in source_route_plan and "route_node_schedule" in source_route_plan,
            "evidence": "_route_customer_plan_feasible_cached checks a temporary CV route schedule",
        },
    }
    return checks


@dataclass
class NativeProbeTracer:
    run_id: str
    phase: str
    algorithm: str
    condition: str
    seed: int
    candidate_rows: list[dict[str, Any]]
    decode_rows: list[dict[str, Any]]
    trajectory_rows: list[dict[str, Any]]
    order_stack: list[dict[str, Any]]
    candidate_index: int = 0
    decode_index: int = 0

    def native_operator(self, operator: str) -> bool:
        if "vehicle_type" in operator or operator == "shared_warm_start":
            return False
        if operator in {"lns_scan_initial", "ga_vehicle_type_initialization", "pso_initial_particle"}:
            return False
        return True


@contextmanager
def instrument_baseline(tracer: NativeProbeTracer, *, force_true_repair_one: bool = False) -> Iterator[None]:
    original_score = mb._SearchSession.score
    original_order_to_solution = mb._order_to_solution
    original_decode = mb._decode_order_like_random_key
    original_all_cv = mb._all_cv_solution_for_session
    original_flags = mb._baseline_fast_repair_flags
    old_env = os.environ.get("SETP_ALNS_CRUSH_TRUE_REPAIR")

    def score_wrapper(session: Any, solution: Any, *, operator: str) -> Any:
        before_best_obj = float(session.best.objective)
        before_best_cost = float(session.best.cost)
        before_eval = int(session.evals)
        scored = original_score(session, solution, operator=operator)
        if scored is not None:
            tracer.candidate_index += 1
            best_updated = bool(session.best.objective < before_best_obj - 1e-9)
            row = candidate_event_row(
                tracer,
                session,
                scored,
                operator,
                before_eval,
                before_best_cost,
                best_updated,
            )
            tracer.candidate_rows.append(row)
            if best_updated:
                tracer.trajectory_rows.append(best_trajectory_row(tracer, session, scored, operator, before_best_cost))
        return scored

    def order_to_solution_wrapper(order: list[str], session: Any, *, type_hints: dict[str, float] | None = None, ev_threshold: float = 0.82) -> Any:
        ordered = mb._complete_order_for_session(order, session)
        hints = type_hints or mb._route_type_hints(session.current.solution, session.context.instance)
        type_key = tuple((customer_id, float(hints.get(customer_id, 0.05))) for customer_id in ordered)
        cache_key = (tuple(ordered), type_key, float(ev_threshold))
        event = {
            "run_id": tracer.run_id,
            "phase": tracer.phase,
            "algorithm": tracer.algorithm,
            "condition": tracer.condition,
            "seed": tracer.seed,
            "decode_event": tracer.decode_index + 1,
            "eval_before": int(session.evals),
            "cache_hit": cache_key in session.decode_cache,
            "decode_called": False,
            "fallback_called": False,
            "order_len": len(ordered),
            "ev_threshold": float(ev_threshold),
            "max_type_key": max((float(value) for _, value in type_key), default=0.0),
            "mean_type_key": statistics.fmean(float(value) for _, value in type_key) if type_key else 0.0,
        }
        tracer.order_stack.append(event)
        try:
            solution = original_order_to_solution(order, session, type_hints=type_hints, ev_threshold=ev_threshold)
        finally:
            tracer.order_stack.pop()
        tracer.decode_index += 1
        event.update(solution_metrics(solution, session.context.instance, session.context.carbon_profile, session.context.prices))
        tracer.decode_rows.append(event)
        return solution

    def decode_wrapper(ordered: list[str], session: Any, type_keys: dict[str, float], *, ev_threshold: float) -> Any:
        if tracer.order_stack:
            tracer.order_stack[-1]["decode_called"] = True
        return original_decode(ordered, session, type_keys, ev_threshold=ev_threshold)

    def all_cv_wrapper(ordered: list[str], session: Any) -> Any:
        if tracer.order_stack:
            tracer.order_stack[-1]["fallback_called"] = True
        return original_all_cv(ordered, session)

    try:
        mb._SearchSession.score = score_wrapper
        mb._order_to_solution = order_to_solution_wrapper
        mb._decode_order_like_random_key = decode_wrapper
        mb._all_cv_solution_for_session = all_cv_wrapper
        if force_true_repair_one:
            os.environ["SETP_ALNS_CRUSH_TRUE_REPAIR"] = "1"
            mb._baseline_fast_repair_flags = lambda: nullcontext()
        yield
    finally:
        mb._SearchSession.score = original_score
        mb._order_to_solution = original_order_to_solution
        mb._decode_order_like_random_key = original_decode
        mb._all_cv_solution_for_session = original_all_cv
        mb._baseline_fast_repair_flags = original_flags
        if old_env is None:
            os.environ.pop("SETP_ALNS_CRUSH_TRUE_REPAIR", None)
        else:
            os.environ["SETP_ALNS_CRUSH_TRUE_REPAIR"] = old_env


def run_baseline_probe(
    *,
    algorithm: str,
    condition: str,
    phase: str,
    seed: int,
    eval_budget: int,
    runtime_cap_seconds: float,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    prices = make_probe_prices()
    bundle = load_search_bundle(bundle_dir())
    initial_solution = make_shared_initial_solution(bundle, prices=prices)
    initial_metrics = evaluate(initial_solution, bundle.instance, bundle.carbon_profile, prices)
    run_id = f"{phase}_{algorithm}_{condition}_seed{seed}"
    tracer = NativeProbeTracer(
        run_id=run_id,
        phase=phase,
        algorithm=algorithm,
        condition=condition,
        seed=int(seed),
        candidate_rows=[],
        decode_rows=[],
        trajectory_rows=[],
        order_stack=[],
    )
    started = time.perf_counter()
    force_true_repair_one = condition == "true_repair_probe_1_no_downgrade"
    try:
        with instrument_baseline(tracer, force_true_repair_one=force_true_repair_one):
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
        row = task_failure_row(phase, algorithm, condition, seed, eval_budget, runtime_cap_seconds, started, "HALT_WORKER_EXCEPTION", repr(exc))
        return row, tracer.candidate_rows, tracer.decode_rows, tracer.trajectory_rows

    solution = result.best_solution
    violations = check_solution(solution, bundle.instance, prices) if solution is not None else []
    final_metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices) if solution is not None and not violations else {}
    status = result.status
    failure_reason = result.failure_reason
    if violations:
        status = "HALT_INFEASIBLE"
        failure_reason = "; ".join(str(item) for item in violations[:3])
    row = {
        "row_type": "run_summary",
        "run_id": run_id,
        "phase": phase,
        "category": INSTANCE_CATEGORY,
        "instance": INSTANCE_NAME,
        "size": INSTANCE_SIZE,
        "seed": int(seed),
        "algorithm": algorithm,
        "condition": condition,
        "battery_kwh": BATTERY_KWH,
        "status": status,
        "gate_status": "OK" if status == "OK" and not violations else status,
        "failure_reason": failure_reason,
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
        "candidate_feasible_count": sum(1 for item in tracer.candidate_rows if boolish(item.get("candidate_feasible"))),
        "candidate_feasible_rate": safe_ratio(sum(1 for item in tracer.candidate_rows if boolish(item.get("candidate_feasible"))), len(tracer.candidate_rows)),
        "candidate_cost_min": finite_min(item.get("candidate_cost") for item in tracer.candidate_rows),
        "candidate_cost_p50": finite_p50(item.get("candidate_cost") for item in tracer.candidate_rows),
        "native_best_updates": sum(1 for item in tracer.candidate_rows if boolish(item.get("best_updated")) and boolish(item.get("native_operator"))),
        "native_feasible_candidate_min": finite_min(item.get("candidate_cost") for item in tracer.candidate_rows if boolish(item.get("native_operator")) and boolish(item.get("candidate_feasible"))),
        "best_signature": solution_signature_hash(solution) if solution is not None else "",
        "best_route_count": len(solution.routes) if solution is not None else 0,
        "best_ev_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev") if solution is not None else 0,
        "best_charging_action_count": len(solution.charging_actions) if solution is not None else 0,
        "decode_events": len(tracer.decode_rows),
        "decode_fallback_rate": safe_ratio(sum(1 for item in tracer.decode_rows if boolish(item.get("fallback_called"))), len(tracer.decode_rows)),
        "decode_cache_hit_rate": safe_ratio(sum(1 for item in tracer.decode_rows if boolish(item.get("cache_hit"))), len(tracer.decode_rows)),
        "decode_cost_lt_platform_count": sum(1 for item in tracer.decode_rows if as_float(item.get("decoded_cost")) < PLATFORM_COST - 1e-9),
        "decode_cost_lt_platform_rate": safe_ratio(sum(1 for item in tracer.decode_rows if as_float(item.get("decoded_cost")) < PLATFORM_COST - 1e-9), len(tracer.decode_rows)),
        "history_json": json.dumps(result.history, ensure_ascii=False, sort_keys=True),
        "operator_counts": json.dumps(result.operator_counts, ensure_ascii=False, sort_keys=True),
        "python": sys.executable,
        "numpy": numpy_version(),
    }
    return row, tracer.candidate_rows, tracer.decode_rows, tracer.trajectory_rows


def candidate_event_row(tracer: NativeProbeTracer, session: Any, scored: Any, operator: str, before_eval: int, before_best_cost: float, best_updated: bool) -> dict[str, Any]:
    return {
        "row_type": "candidate",
        "run_id": tracer.run_id,
        "phase": tracer.phase,
        "algorithm": tracer.algorithm,
        "condition": tracer.condition,
        "seed": int(tracer.seed),
        "candidate_index": int(tracer.candidate_index),
        "eval_before": int(before_eval),
        "eval_after": int(session.evals),
        "operator": operator,
        "native_operator": tracer.native_operator(operator),
        "candidate_feasible": bool(scored.feasible),
        "candidate_cost": float(scored.cost) if scored.feasible else math.inf,
        "candidate_objective": float(scored.objective),
        "candidate_signature": str(scored.signature),
        "best_updated": bool(best_updated),
        "best_cost_before": float(before_best_cost),
        "best_cost_after": float(session.best.cost),
        "route_count": len(scored.solution.routes),
        "ev_route_count": sum(1 for route in scored.solution.routes if route.vehicle_type.lower() == "ev"),
        "charging_action_count": len(scored.solution.charging_actions),
    }


def best_trajectory_row(tracer: NativeProbeTracer, session: Any, scored: Any, operator: str, before_best_cost: float) -> dict[str, Any]:
    return {
        "run_id": tracer.run_id,
        "phase": tracer.phase,
        "algorithm": tracer.algorithm,
        "condition": tracer.condition,
        "seed": int(tracer.seed),
        "eval": int(session.evals),
        "operator": operator,
        "native_operator": tracer.native_operator(operator),
        "best_cost_before": float(before_best_cost),
        "best_cost": float(scored.cost),
        "best_signature": str(scored.signature),
    }


def solution_metrics(solution: Any, instance: Any, carbon_profile: Any, prices: Any) -> dict[str, Any]:
    violations = check_solution(solution, instance, prices)
    metrics = evaluate(solution, instance, carbon_profile, prices) if not violations else {}
    route_count = len(solution.routes)
    ev_routes = sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev")
    return {
        "decoded_feasible": len(violations) == 0,
        "decoded_violation_count": len(violations),
        "decoded_cost": as_float(metrics.get("total_cost")),
        "decoded_signature": solution_signature_hash(solution),
        "decoded_route_count": route_count,
        "decoded_ev_route_count": ev_routes,
        "decoded_ev_route_share": ev_routes / route_count if route_count else 0.0,
        "decoded_charging_action_count": len(solution.charging_actions),
        "decoded_cost_lt_platform": as_float(metrics.get("total_cost")) < PLATFORM_COST - 1e-9,
    }


def run_flip_closure(*, seed: int, runtime_cap_seconds: float) -> list[dict[str, Any]]:
    prices = make_probe_prices()
    bundle = load_search_bundle(bundle_dir())
    warm = make_shared_initial_solution(bundle, prices=prices)
    rows: list[dict[str, Any]] = []
    for closure_seed in (int(seed), int(seed) + 1):
        rows.append(random_flip_closure(bundle, prices, warm, closure_seed, runtime_cap_seconds))
    rows.append(deterministic_flip_closure(bundle, prices, warm))
    return rows


def random_flip_closure(bundle: Any, prices: Any, warm: Any, seed: int, runtime_cap_seconds: float) -> dict[str, Any]:
    session = mb._SearchSession("LNS", bundle, seed, 10_000, runtime_cap_seconds, warm, prices=prices)
    current = warm
    current_cost = model_total_cost(current, bundle, prices)
    started = time.perf_counter()
    accepted = 0
    attempts = 0
    stale = 0
    while attempts < 500 and stale < max(40, len(current.routes) * 3) and (time.perf_counter() - started) < runtime_cap_seconds:
        attempts += 1
        candidate = mb._vehicle_type_mutation(current, session, attempts=max(1, len(current.routes)))
        candidate_cost = model_total_cost(candidate, bundle, prices)
        if candidate_cost < current_cost - 1e-9:
            current = candidate
            current_cost = candidate_cost
            accepted += 1
            stale = 0
        else:
            stale += 1
    return closure_row("random_seeded_flip", seed, attempts, accepted, current, current_cost, bundle, prices)


def deterministic_flip_closure(bundle: Any, prices: Any, warm: Any) -> dict[str, Any]:
    current = warm
    current_cost = model_total_cost(current, bundle, prices)
    accepted = 0
    attempts = 0
    while attempts < 500:
        best_candidate = None
        best_cost = current_cost
        for idx, _route in enumerate(list(current.routes)):
            attempts += 1
            candidate = flip_route_at_index(current, idx, bundle, prices)
            if candidate is None:
                continue
            cost = model_total_cost(candidate, bundle, prices)
            if cost < best_cost - 1e-9:
                best_candidate = candidate
                best_cost = cost
        if best_candidate is None:
            break
        current = best_candidate
        current_cost = best_cost
        accepted += 1
    return closure_row("deterministic_best_improvement_flip", 0, attempts, accepted, current, current_cost, bundle, prices)


def flip_route_at_index(solution: Any, idx: int, bundle: Any, prices: Any) -> Any | None:
    route = solution.routes[idx]
    target_type = "ev" if route.vehicle_type.lower() == "cv" else "cv"
    new_route = Route(f"{target_type.upper()}CLOSURE_{idx + 1}", target_type, route.home_depot_id, list(route.node_sequence))
    new_actions = [action for action in solution.charging_actions if action.vehicle_id != route.vehicle_id]
    if target_type == "ev":
        try:
            new_route, route_actions = repair_route_charging(new_route, bundle.instance, bundle.carbon_profile, prices)
        except ValueError:
            return None
        new_actions.extend(route_actions)
    routes = list(solution.routes)
    routes[idx] = new_route
    candidate = normalize_solution_vehicle_trips(
        Solution(routes=routes, charging_actions=new_actions, cross_site_services=solution.cross_site_services),
        bundle.instance,
    )
    if check_solution(candidate, bundle.instance, prices):
        return None
    return candidate


def closure_row(closure_type: str, seed: int, attempts: int, accepted: int, solution: Any, cost: float, bundle: Any, prices: Any) -> dict[str, Any]:
    metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices)
    violations = check_solution(solution, bundle.instance, prices)
    route_count = len(solution.routes)
    ev_routes = sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev")
    return {
        "closure_type": closure_type,
        "seed": int(seed),
        "attempts": int(attempts),
        "accepted_flips": int(accepted),
        "status": "OK" if not violations else "HALT_INFEASIBLE",
        "violation_count": len(violations),
        "closure_cost": float(metrics["total_cost"]) if not violations else math.inf,
        "matches_5174_platform": abs(float(metrics["total_cost"]) - PLATFORM_COST) <= 1e-9 if not violations else False,
        "signature": solution_signature_hash(solution),
        "route_count": route_count,
        "ev_route_count": ev_routes,
        "ev_route_share": ev_routes / route_count if route_count else 0.0,
        "charging_action_count": len(solution.charging_actions),
        "solution_json": json.dumps(solution_to_dict(solution), ensure_ascii=False, sort_keys=True),
    }


def model_total_cost(solution: Any, bundle: Any, prices: Any) -> float:
    violations = check_solution(solution, bundle.instance, prices)
    if violations:
        return math.inf
    return float(evaluate(solution, bundle.instance, bundle.carbon_profile, prices)["total_cost"])


def decide(
    rows: list[dict[str, Any]],
    decode_rows: list[dict[str, Any]],
    closure_rows: list[dict[str, Any]],
    phase0: dict[str, Any],
    static_checks: dict[str, dict[str, Any]],
    *,
    expected_task_count: int,
) -> dict[str, Any]:
    failures = collection_failures(rows, decode_rows, closure_rows, phase0, static_checks, expected_task_count=expected_task_count)
    summaries = [row for row in rows if row.get("row_type") == "run_summary"]
    lns0 = next((row for row in summaries if row.get("condition") == "true_repair_forced_0_current"), None)
    lns1 = next((row for row in summaries if row.get("condition") == "true_repair_probe_1_no_downgrade"), None)
    ga = next((row for row in summaries if row.get("algorithm") == "GA"), None)
    pso = next((row for row in summaries if row.get("algorithm") == "PSO"), None)
    h1 = h1_decision(lns0, lns1)
    h2 = h2_decision(ga, pso)
    refuted = (
        lns0 is not None
        and ga is not None
        and pso is not None
        and int(as_float(lns0.get("native_best_updates"))) > 0
        and int(as_float(ga.get("decode_cost_lt_platform_count"))) > 0
        and int(as_float(pso.get("decode_cost_lt_platform_count"))) > 0
    )
    if failures:
        verdict = "HALT_COLLECTION_COST"
        plain = "采集不闭合或环境/trace/hash 门槛未过；本 probe 不能做完整 H1/H2 裁决。"
    elif h1 == "H1_CONFIRMED" and h2 == "H2_CONFIRMED":
        verdict = "NATIVE_CHANNEL_DEAD_CONFIRMED"
        plain = "LNS TRUE_REPAIR A/B 与 GA/PSO 解码计量同时支持原生通道死亡假设；这仍只是 C1-R2 PROBE，不是算法胜负。"
    elif refuted:
        verdict = "HYPOTHESES_REFUTED"
        plain = "现状 LNS 有 native 改进且 GA/PSO 都能解码出低于 5174 的排列候选；同质化另有原因，不应自行发明修复。"
    else:
        verdict = "PARTIAL_OR_WEAK_SUPPORT"
        plain = "H1/H2 没有同时达到预注册确认门槛；只按分项事实报告，不推进正式 T3。"
    return {
        "verdict": verdict,
        "plain": plain,
        "h1_decision": h1,
        "h2_decision": h2,
        "rows": len(rows),
        "run_summary_rows": len(summaries),
        "expected_run_summary_rows": expected_task_count,
        "decode_rows": len(decode_rows),
        "closure_rows": len(closure_rows),
        "collection_failure_count": len(failures),
        "failure_sample": failures[:20],
        "lns_current_native_best_updates": int(as_float(lns0.get("native_best_updates"))) if lns0 else None,
        "lns_true_repair_native_best_updates": int(as_float(lns1.get("native_best_updates"))) if lns1 else None,
        "ga_decode_fallback_rate": as_float(ga.get("decode_fallback_rate")) if ga else math.nan,
        "pso_decode_fallback_rate": as_float(pso.get("decode_fallback_rate")) if pso else math.nan,
        "ga_decode_lt_platform_rate": as_float(ga.get("decode_cost_lt_platform_rate")) if ga else math.nan,
        "pso_decode_lt_platform_rate": as_float(pso.get("decode_cost_lt_platform_rate")) if pso else math.nan,
        "flip_closure_platform_matches": all(boolish(row.get("matches_5174_platform")) for row in closure_rows if row.get("status") == "OK"),
    }


def h1_decision(lns0: dict[str, Any] | None, lns1: dict[str, Any] | None) -> str:
    if not lns0 or not lns1:
        return "H1_UNRESOLVED"
    current_updates = int(as_float(lns0.get("native_best_updates")))
    probe_updates = int(as_float(lns1.get("native_best_updates")))
    current_min = as_float(lns0.get("native_feasible_candidate_min"))
    probe_min = as_float(lns1.get("native_feasible_candidate_min"))
    if probe_updates > 0 and current_updates == 0:
        return "H1_CONFIRMED"
    if current_updates > 0 and probe_updates >= 3 * current_updates and probe_min < current_min - 1e-9:
        return "H1_CONFIRMED"
    return "H1_WEAK_OR_UNRESOLVED"


def h2_decision(ga: dict[str, Any] | None, pso: dict[str, Any] | None) -> str:
    if not ga or not pso:
        return "H2_UNRESOLVED"
    ga_fallback = as_float(ga.get("decode_fallback_rate"))
    pso_fallback = as_float(pso.get("decode_fallback_rate"))
    ga_lt = as_float(ga.get("decode_cost_lt_platform_rate"))
    pso_lt = as_float(pso.get("decode_cost_lt_platform_rate"))
    if ga_fallback > 0.30 or pso_fallback > 0.30:
        return "H2_CONFIRMED"
    if ga_lt <= 0.01 and pso_lt <= 0.01:
        return "H2_CONFIRMED"
    return "H2_WEAK_OR_UNRESOLVED"


def collection_failures(
    rows: list[dict[str, Any]],
    decode_rows: list[dict[str, Any]],
    closure_rows: list[dict[str, Any]],
    phase0: dict[str, Any],
    static_checks: dict[str, dict[str, Any]],
    *,
    expected_task_count: int,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    if not phase0.get("phase0_ok"):
        failures.append({"failure_bucket": "phase0_not_ok", "phase0": phase0})
    for name, check in static_checks.items():
        if not check.get("pass"):
            failures.append({"failure_bucket": "static_fact_mismatch", "check": name, "evidence": check.get("evidence")})
    summaries = [row for row in rows if row.get("row_type") == "run_summary"]
    if len(summaries) != expected_task_count:
        failures.append({"failure_bucket": "missing_run_summary_rows", "actual": len(summaries), "expected": expected_task_count})
    for row in summaries:
        if row.get("gate_status") != "OK":
            failures.append({"failure_bucket": "run_status_not_ok", "run_id": row.get("run_id"), "status": row.get("status")})
        if int(as_float(row.get("actual_evals"))) < int(as_float(row.get("eval_budget"))):
            failures.append({"failure_bucket": "under_eval", "run_id": row.get("run_id"), "actual_evals": row.get("actual_evals")})
        if row.get("python") != GOLD_PYTHON or row.get("numpy") != GOLD_NUMPY:
            failures.append({"failure_bucket": "env_mismatch", "run_id": row.get("run_id"), "python": row.get("python"), "numpy": row.get("numpy")})
    if not any(row.get("row_type") == "candidate" for row in rows):
        failures.append({"failure_bucket": "candidate_trace_missing"})
    if not decode_rows:
        failures.append({"failure_bucket": "decode_trace_missing"})
    if len(closure_rows) < 3:
        failures.append({"failure_bucket": "flip_closure_missing", "rows": len(closure_rows)})
    for row in closure_rows:
        if row.get("status") != "OK":
            failures.append({"failure_bucket": "closure_status_not_ok", "closure_type": row.get("closure_type"), "status": row.get("status")})
    return failures


def halt_decision(
    verdict: str,
    plain: str,
    rows: list[dict[str, Any]],
    decode_rows: list[dict[str, Any]],
    closure_rows: list[dict[str, Any]],
    phase0: dict[str, Any],
    static_checks: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "plain": plain,
        "h1_decision": "H1_UNRESOLVED",
        "h2_decision": "H2_UNRESOLVED",
        "rows": len(rows),
        "decode_rows": len(decode_rows),
        "closure_rows": len(closure_rows),
        "collection_failure_count": 1,
        "phase0": phase0,
        "static_checks": static_checks,
    }


def task_failure_row(
    phase: str,
    algorithm: str,
    condition: str,
    seed: int,
    eval_budget: int,
    runtime_cap_seconds: float,
    started: float,
    status: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "row_type": "run_summary",
        "run_id": f"{phase}_{algorithm}_{condition}_seed{seed}",
        "phase": phase,
        "category": INSTANCE_CATEGORY,
        "instance": INSTANCE_NAME,
        "size": INSTANCE_SIZE,
        "seed": int(seed),
        "algorithm": algorithm,
        "condition": condition,
        "battery_kwh": BATTERY_KWH,
        "status": status,
        "gate_status": status,
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
    phase0: dict[str, Any],
    static_checks: dict[str, dict[str, Any]],
    decision: dict[str, Any],
    rows: list[dict[str, Any]],
    decode_rows: list[dict[str, Any]],
    closure_rows: list[dict[str, Any]],
) -> str:
    summaries = [row for row in rows if row.get("row_type") == "run_summary"]
    lines = [
        "# C1-R2 Native Channel Autopsy Probe",
        "",
        "本步目标：证实或证伪两个代码级假设，回答“四基线原生搜索为何 15958 eval 零改进”。",
        "",
        f"Evidence level: **{PROBE_LEVEL}**. 本报告不得写成算法胜负或正式 T3 证据。",
        "",
        f"Verdict: `{decision.get('verdict')}`",
        "",
        "## Plain Reading",
        "",
        str(decision.get("plain", "")),
        "",
        "## Gate",
        "",
        f"- H1 decision: `{decision.get('h1_decision')}`",
        f"- H2 decision: `{decision.get('h2_decision')}`",
        f"- Collection failures: `{decision.get('collection_failure_count')}`",
        f"- HEAD: `{metadata.get('head')}`",
        f"- Python/numpy: `{phase0.get('default_probe', {}).get('python')}` / `{phase0.get('default_probe', {}).get('numpy')}`",
        "- Battery override only in memory: `dataclasses.replace(DEFAULT_PRICES, B_battery_kwh=280.0, carbon_price=0.05034)`.",
        "",
        "## Static Facts",
        "",
        "| check | pass | evidence |",
        "|---|---:|---|",
    ]
    for name, check in static_checks.items():
        lines.append(f"| {name} | {check.get('pass')} | {check.get('evidence')} |")
    lines.extend([
        "",
        "## Run Summaries",
        "",
        "| phase | algorithm | condition | status | evals | best cost | native best updates | feasible rate | decode fallback | decode <5174 |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    for row in summaries:
        lines.append(
            "| {phase} | {algorithm} | {condition} | {status} | {evals} | {cost:.12f} | {native} | {feasible:.4f} | {fallback:.4f} | {lt:.4f} |".format(
                phase=row.get("phase"),
                algorithm=row.get("algorithm"),
                condition=row.get("condition"),
                status=row.get("status"),
                evals=int(as_float(row.get("actual_evals"))),
                cost=as_float(row.get("best_cost")),
                native=int(as_float(row.get("native_best_updates"))),
                feasible=as_float(row.get("candidate_feasible_rate")),
                fallback=as_float(row.get("decode_fallback_rate")),
                lt=as_float(row.get("decode_cost_lt_platform_rate")),
            )
        )
    lines.extend([
        "",
        "## Flip Closure",
        "",
        "| closure | seed | status | cost | matches 5174 | accepted flips | EV share |",
        "|---|---:|---|---:|---|---:|---:|",
    ])
    for row in closure_rows:
        lines.append(
            "| {closure} | {seed} | {status} | {cost:.12f} | {match} | {accepted} | {ev:.4f} |".format(
                closure=row.get("closure_type"),
                seed=int(as_float(row.get("seed"))),
                status=row.get("status"),
                cost=as_float(row.get("closure_cost")),
                match=row.get("matches_5174_platform"),
                accepted=int(as_float(row.get("accepted_flips"))),
                ev=as_float(row.get("ev_route_share")),
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
        f"- Best trajectory: `{metadata.get('output_dir')}/best_trajectory.csv`",
        f"- Flip closure: `{metadata.get('output_dir')}/flip_closure.csv`",
        f"- Decision: `{metadata.get('output_dir')}/decision.json`",
        "",
    ])
    return "\n".join(lines).rstrip() + "\n"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
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
    return {"schema": "setp-c1-r2-artifact-hashes.v1", "files": files}


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


def finite_min(values: Any) -> float:
    clean = finite_values(values)
    return min(clean) if clean else math.nan


def finite_p50(values: Any) -> float:
    clean = finite_values(values)
    return statistics.median(clean) if clean else math.nan


def safe_ratio(num: int, den: int) -> float:
    return float(num) / float(den) if den else 0.0


if __name__ == "__main__":
    main()
