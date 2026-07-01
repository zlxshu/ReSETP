"""09z neutral-start EV-heavy findability gate.

This diagnostic runner asks one narrow question: starting from the common
neutral warm start, can the search itself find the EV-heavy headroom that 09y
Stage A constructed?  It does not change the shared referee semantics.
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

from baselines.e2_alns import ev_heavy_regime_decision_probe as regime


REPO_ROOT = regime.REPO_ROOT
CARBON_PRICE = regime.CARBON_PRICE
PROBE_LEVEL = "PROBE / 非正式 T3"
DEFAULT_INSTANCE = ("threeshift", "e2-threeshift-150c-01", 150)
DEFAULT_ALGORITHMS = (
    "alns_e2_carbon",
    "alns_e2_carbon_ablation",
    "alns_e2_throughput",
    "LNS",
    "GA",
    "PSO",
    "VNS",
)
ALNS_ALGORITHMS = {"alns_e2_carbon", "alns_e2_carbon_ablation", "alns_e2_throughput"}
HARD_TIMEOUT_GRACE_SECONDS = 15.0
FIND_COST_CLOSURE_THRESHOLD = 0.25
FIND_EV_GAIN_THRESHOLD = 0.10
NO_FIND_COST_IMPROVEMENT_PCT = 0.1
NO_FIND_EV_GAIN_THRESHOLD = 0.05
VERDICTS = {
    "PASS_ALNS_FIND_SIGNAL",
    "PASS_ALL_FIND_OR_INSTANCE_EASY",
    "HALT_NO_FIND_SIGNAL",
    "HALT_NEIGHBORHOOD_NO_EV_PATH",
    "HALT_SEARCH_CANNOT_USE_EV_PATH",
    "HALT_COLLECTION_COST",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    gate = sub.add_parser("neutral-search-gate")
    add_common_args(gate)
    gate.add_argument("--seeds", default="1-2")
    gate.add_argument("--algorithms", default=",".join(DEFAULT_ALGORITHMS))
    gate.add_argument("--runtime-seconds", type=float, default=600.0)
    gate.add_argument("--eval-budget", type=int, default=16_000)
    gate.add_argument("--workers", type=int, default=2)
    gate.add_argument("--retry-failures", action="store_true")

    audit = sub.add_parser("ev-swap-audit")
    add_common_args(audit)

    phase1 = sub.add_parser("phase1")
    add_common_args(phase1)
    phase1.add_argument("--seeds", default="1-2")
    phase1.add_argument("--algorithms", default=",".join(DEFAULT_ALGORITHMS))
    phase1.add_argument("--runtime-seconds", type=float, default=600.0)
    phase1.add_argument("--eval-budget", type=int, default=16_000)
    phase1.add_argument("--workers", type=int, default=2)
    phase1.add_argument("--retry-failures", action="store_true")

    worker = sub.add_parser("worker-search")
    worker.add_argument("--task-json", required=True)
    worker.add_argument("--output-json", required=True)

    return parser.parse_args()


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--category", default=DEFAULT_INSTANCE[0])
    parser.add_argument("--instance", default=DEFAULT_INSTANCE[1])
    parser.add_argument("--size", type=int, default=DEFAULT_INSTANCE[2])
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    parser.add_argument("--output-dir", default="baselines/e2_alns/ev_heavy_findability_gate_data")
    parser.add_argument("--report-path", default="")


def main() -> None:
    args = parse_args()
    if args.command == "neutral-search-gate":
        run_neutral_search_gate(args)
    elif args.command == "ev-swap-audit":
        run_ev_swap_audit(args)
    elif args.command == "phase1":
        run_phase1(args)
    elif args.command == "worker-search":
        task = regime.read_json(Path(args.task_json))
        row = run_search_task(task)
        Path(args.output_json).write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    else:
        raise ValueError(args.command)


def run_phase1(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    report_path = report_path_from_args(args)
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = build_metadata(args, "phase1")
    regime.write_json(output_dir / "metadata.json", metadata)
    phase0 = regime.phase0_audit(float(args.battery_kwh))
    regime.write_json(output_dir / "phase0_audit.json", phase0)

    audit_rows = ev_swap_audit_instance(str(args.category), str(args.instance), int(args.size), float(args.battery_kwh))
    regime.write_csv(output_dir / "ev_swap_audit_rows.csv", audit_rows)
    regime.write_csv(output_dir / "ev_swap_audit_summary.csv", summarize_audit(audit_rows))

    tasks = build_search_tasks(args, output_dir)
    regime.write_csv(output_dir / "task_queue.csv", [task_queue_row(task) for task in tasks])
    rows = run_search_tasks(tasks, workers=int(args.workers), incremental_csv=output_dir / "raw_runs.csv", retry_failures=bool(args.retry_failures))
    regime.write_csv(output_dir / "raw_runs.csv", rows)

    decision = findability_decision(phase0, rows, audit_rows, expected_rows=len(tasks))
    regime.write_json(output_dir / "findability_decision.json", decision)
    write_optional_report(report_path, metadata, phase0, decision, rows, audit_rows)
    regime.write_json(output_dir / "artifact_hashes.json", artifact_hashes(output_dir, report_path))
    return decision


def run_neutral_search_gate(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    report_path = report_path_from_args(args)
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = build_metadata(args, "neutral-search-gate")
    regime.write_json(output_dir / "metadata.json", metadata)
    phase0 = regime.phase0_audit(float(args.battery_kwh))
    regime.write_json(output_dir / "phase0_audit.json", phase0)

    tasks = build_search_tasks(args, output_dir)
    regime.write_csv(output_dir / "task_queue.csv", [task_queue_row(task) for task in tasks])
    rows = run_search_tasks(tasks, workers=int(args.workers), incremental_csv=output_dir / "raw_runs.csv", retry_failures=bool(args.retry_failures))
    regime.write_csv(output_dir / "raw_runs.csv", rows)

    audit_rows = read_optional_csv(output_dir / "ev_swap_audit_rows.csv")
    decision = findability_decision(phase0, rows, audit_rows, expected_rows=len(tasks))
    regime.write_json(output_dir / "findability_decision.json", decision)
    write_optional_report(report_path, metadata, phase0, decision, rows, audit_rows)
    regime.write_json(output_dir / "artifact_hashes.json", artifact_hashes(output_dir, report_path))
    return decision


def run_ev_swap_audit(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    report_path = report_path_from_args(args)
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = build_metadata(args, "ev-swap-audit")
    regime.write_json(output_dir / "metadata.json", metadata)
    phase0 = regime.phase0_audit(float(args.battery_kwh))
    regime.write_json(output_dir / "phase0_audit.json", phase0)

    rows = ev_swap_audit_instance(str(args.category), str(args.instance), int(args.size), float(args.battery_kwh))
    regime.write_csv(output_dir / "ev_swap_audit_rows.csv", rows)
    regime.write_csv(output_dir / "ev_swap_audit_summary.csv", summarize_audit(rows))
    search_rows = read_optional_csv(output_dir / "raw_runs.csv")
    decision = findability_decision(phase0, search_rows, rows, expected_rows=len(search_rows))
    regime.write_json(output_dir / "findability_decision.json", decision)
    write_optional_report(report_path, metadata, phase0, decision, search_rows, rows)
    regime.write_json(output_dir / "artifact_hashes.json", artifact_hashes(output_dir, report_path))
    return decision


def report_path_from_args(args: argparse.Namespace) -> Path | None:
    raw = str(getattr(args, "report_path", "") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if path.suffix.lower() == ".md":
        raise ValueError("Markdown report files are disabled for this workflow; use CSV/JSON artifacts and chat summaries.")
    return path


def write_optional_report(
    report_path: Path | None,
    metadata: dict[str, Any],
    phase0: dict[str, Any],
    decision: dict[str, Any],
    rows: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
) -> None:
    if report_path is None:
        return
    report_path.write_text(render_report(metadata, phase0, decision, rows, audit_rows), encoding="utf-8")


def build_metadata(args: argparse.Namespace, command: str) -> dict[str, Any]:
    return {
        "schema": "setp-09z-ev-heavy-findability-gate.v1",
        "command": command,
        "evidence_level": PROBE_LEVEL,
        "repo_root": str(REPO_ROOT),
        "output_dir": str(args.output_dir),
        "report_path": str(args.report_path),
        "head": regime.git_head(),
        "category": str(args.category),
        "instance": str(args.instance),
        "size": int(args.size),
        "battery_kwh": float(args.battery_kwh),
        "carbon_price": CARBON_PRICE,
        "started_at_epoch": time.time(),
    }


def build_search_tasks(args: argparse.Namespace, output_dir: Path) -> list[dict[str, Any]]:
    algorithms = [item.strip() for item in str(args.algorithms).split(",") if item.strip()]
    tasks = []
    for seed in regime.parse_seeds(str(args.seeds)):
        for algorithm in algorithms:
            tasks.append({
                "stage": "neutral-search-gate",
                "repo_root": str(REPO_ROOT),
                "output_dir": str(output_dir),
                "category": str(args.category),
                "instance": str(args.instance),
                "size": int(args.size),
                "seed": int(seed),
                "algorithm": algorithm,
                "battery_kwh": float(args.battery_kwh),
                "bundle_dir": str(regime.bundle_path(str(args.category), str(args.instance)).relative_to(REPO_ROOT)),
                "eval_budget": int(args.eval_budget),
                "runtime_cap_seconds": float(args.runtime_seconds),
                "comparison_mode": "wallclock",
                "seed_mode": "neutral",
                "checkpoint_path": str(output_dir / "checkpoints" / "neutral" / f"{args.instance}__{algorithm}__seed{seed}.json"),
            })
    return tasks


def task_queue_row(task: dict[str, Any]) -> dict[str, Any]:
    keys = ("instance", "size", "seed", "algorithm", "battery_kwh", "runtime_cap_seconds", "eval_budget", "seed_mode", "checkpoint_path")
    return {key: task[key] for key in keys}


def run_search_tasks(
    tasks: list[dict[str, Any]],
    *,
    workers: int,
    incremental_csv: Path,
    retry_failures: bool,
) -> list[dict[str, Any]]:
    existing = load_existing_rows(incremental_csv)
    rows: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for task in tasks:
        prior = existing.get(task_key(task))
        if prior is not None:
            prior_status_ok = str(prior.get("status")) == "OK"
            prior_gate_ok = str(prior.get("gate_status")) == "OK"
            if not retry_failures or (prior_status_ok and prior_gate_ok):
                rows.append(prior | {"queue_action": "SKIPPED_EXISTING"})
                continue
        pending.append(task)
    if workers <= 1:
        for task in pending:
            rows.append(execute_search_task_subprocess(task))
            regime.write_csv(incremental_csv, sorted(rows, key=row_sort_key))
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        with ProcessPoolExecutor(max_workers=int(workers)) as pool:
            future_map = {pool.submit(execute_search_task_subprocess, task): task for task in pending}
            for future in as_completed(future_map):
                rows.append(future.result())
                regime.write_csv(incremental_csv, sorted(rows, key=row_sort_key))
    return sorted(rows, key=row_sort_key)


def execute_search_task_subprocess(task: dict[str, Any]) -> dict[str, Any]:
    output_dir = Path(task["output_dir"])
    task_root = output_dir / ".tasks"
    task_root.mkdir(parents=True, exist_ok=True)
    slug = f"{task['instance']}__{task['algorithm']}__seed{task['seed']}"
    task_path = task_root / f"{slug}.json"
    row_path = task_root / f"{slug}_row.json"
    task_path.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    command = [sys.executable, str(Path(__file__).resolve()), "worker-search", "--task-json", str(task_path), "--output-json", str(row_path)]
    env = {**os.environ, "PYTHONPATH": "solver/src:models/src:.", "PYTHONHASHSEED": "0"}
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=float(task["runtime_cap_seconds"]) + HARD_TIMEOUT_GRACE_SECONDS,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return timeout_row(task, time.perf_counter() - started, exc.stdout, exc.stderr)
    if completed.returncode != 0:
        return failure_row(task, "HALT_WORKER_ERROR", f"Worker exited non-zero: {completed.stderr[-1200:]}")
    if not row_path.exists():
        return failure_row(task, "HALT_WORKER_ERROR", "Worker produced no row JSON.")
    return regime.read_json(row_path)


def run_search_task(task: dict[str, Any]) -> dict[str, Any]:
    from setp_solver.check import check_solution
    from setp_solver.cost import evaluate
    from setp_solver.prices import DEFAULT_PRICES
    from setp_solver.search.bundle import load_search_bundle
    from setp_solver.search.candidates import solution_signature_hash
    from setp_solver.search.metaheuristic_baselines import run_metaheuristic_baseline
    from setp_solver.search.winner_operators import WinnerKernelConfig, run_e2_alns_carbon, run_e2_alns_throughput

    started = time.perf_counter()
    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(task["battery_kwh"]), carbon_price=CARBON_PRICE)
    bundle = load_search_bundle(Path(task["repo_root"]) / task["bundle_dir"])
    initial_solution, seed_source = neutral_seed(bundle, prices)
    initial_metrics = evaluate(initial_solution, bundle.instance, bundle.carbon_profile, prices)
    initial_cost = float(initial_metrics["total_cost"])
    initial_ev_share = ev_route_share(initial_solution)
    initial_signature = solution_signature_hash(initial_solution)
    reference_solution, reference_source = ev_maximal_reference(str(task["category"]), str(task["instance"]), int(task["size"]), float(task["battery_kwh"]), bundle, prices, initial_solution)
    reference_metrics = evaluate(reference_solution, bundle.instance, bundle.carbon_profile, prices)
    reference_cost = float(reference_metrics["total_cost"])

    checkpoint_path = str(task.get("checkpoint_path", "")).strip()
    if checkpoint_path:
        os.environ["SETP_E2_ALNS_CHECKPOINT_PATH"] = checkpoint_path

    algorithm = str(task["algorithm"])
    try:
        if algorithm == "alns_e2_carbon":
            result = run_e2_alns_carbon(
                bundle.bundle_dir,
                config=WinnerKernelConfig(seed=int(task["seed"]), eval_budget=int(task["eval_budget"]), max_runtime_seconds=float(task["runtime_cap_seconds"])),
                initial_solution=initial_solution,
                prices=prices,
                carbon_bias_weight=1.0,
                variant_id=algorithm,
            )
            solution = result["best_solution"]
            best_cost = float(result["best_cost"])
            actual_evals = int(result["evaluations"])
            status = "OK"
            failure_reason = ""
            violation_count = int(result["violation_count"])
            history = list(result.get("history", []))
            operator_counts = dict(result.get("operator_counts", {}))
        elif algorithm == "alns_e2_carbon_ablation":
            result = run_e2_alns_carbon(
                bundle.bundle_dir,
                config=WinnerKernelConfig(seed=int(task["seed"]), eval_budget=int(task["eval_budget"]), max_runtime_seconds=float(task["runtime_cap_seconds"])),
                initial_solution=initial_solution,
                prices=prices,
                carbon_bias_weight=0.0,
                variant_id=algorithm,
            )
            solution = result["best_solution"]
            best_cost = float(result["best_cost"])
            actual_evals = int(result["evaluations"])
            status = "OK"
            failure_reason = ""
            violation_count = int(result["violation_count"])
            history = list(result.get("history", []))
            operator_counts = dict(result.get("operator_counts", {}))
        elif algorithm == "alns_e2_throughput":
            result = run_e2_alns_throughput(
                bundle.bundle_dir,
                config=WinnerKernelConfig(seed=int(task["seed"]), eval_budget=int(task["eval_budget"]), max_runtime_seconds=float(task["runtime_cap_seconds"])),
                initial_solution=initial_solution,
                prices=prices,
            )
            solution = result["best_solution"]
            best_cost = float(result["best_cost"])
            actual_evals = int(result["evaluations"])
            status = "OK"
            failure_reason = ""
            violation_count = int(result["violation_count"])
            history = list(result.get("history", []))
            operator_counts = dict(result.get("operator_counts", {}))
        else:
            result = run_metaheuristic_baseline(
                algorithm,
                bundle.bundle_dir,
                seed=int(task["seed"]),
                eval_budget=int(task["eval_budget"]),
                max_runtime_seconds=float(task["runtime_cap_seconds"]),
                initial_solution=initial_solution,
                prices=prices,
            )
            solution = result.best_solution
            best_cost = float(result.best_cost) if result.best_cost is not None else math.inf
            actual_evals = int(result.evals)
            status = result.status
            failure_reason = result.failure_reason
            violation_count = int(result.violation_count)
            history = list(result.history)
            operator_counts = dict(result.operator_counts)
    except Exception as exc:
        return failure_row(task, "HALT_WORKER_EXCEPTION", repr(exc))

    violations = check_solution(solution, bundle.instance, prices) if solution is not None else []
    if violations:
        status = "HALT_INFEASIBLE"
        failure_reason = "; ".join(str(item) for item in violations[:3])
        violation_count = len(violations)
    best_ev_share = ev_route_share(solution) if solution is not None else math.nan
    best_signature = solution_signature_hash(solution) if solution is not None else ""
    best_improvements = best_improvement_count(history)
    first_eval = first_improvement_eval(history)
    closed = closed_gap_fraction(initial_cost, best_cost, reference_cost)
    row = {
        **{key: task[key] for key in ("stage", "category", "instance", "size", "seed", "algorithm", "battery_kwh")},
        "status": status,
        "gate_status": "OK" if status in {"OK", "HALT_RUNTIME_UNDER_EVAL"} and not violations else status,
        "failure_reason": failure_reason,
        "seed_mode": "neutral",
        "seed_source": seed_source,
        "ev_maximal_reference_source": reference_source,
        "initial_cost": initial_cost,
        "best_cost": best_cost,
        "ev_maximal_reference_cost": reference_cost,
        "gap_vs_initial_pct": regime.pct_gap(best_cost, initial_cost),
        "gap_to_ev_maximal_pct": regime.pct_gap(best_cost, reference_cost),
        "closed_gap_fraction": closed,
        "initial_ev_share": initial_ev_share,
        "best_ev_share": best_ev_share,
        "ev_share_gain": best_ev_share - initial_ev_share if math.isfinite(best_ev_share) else math.nan,
        "returned_initial_signature": best_signature == initial_signature,
        "initial_signature": initial_signature,
        "best_signature": best_signature,
        "best_improvement_count": best_improvements,
        "first_improvement_eval": first_eval,
        "actual_evals": actual_evals,
        "elapsed_seconds": time.perf_counter() - started,
        "runtime_cap_seconds": float(task["runtime_cap_seconds"]),
        "eval_budget": int(task["eval_budget"]),
        "violation_count": violation_count,
        "initial_route_count": len(initial_solution.routes),
        "best_route_count": len(solution.routes) if solution is not None else 0,
        "initial_charging_action_count": len(initial_solution.charging_actions),
        "best_charging_action_count": len(solution.charging_actions) if solution is not None else 0,
        "operator_counts": json.dumps(operator_counts, ensure_ascii=False, sort_keys=True),
        "history_json": json.dumps(history, ensure_ascii=False, sort_keys=True),
        "python": sys.executable,
        "numpy": regime.numpy_version(),
    }
    return row


def neutral_seed(bundle: Any, prices: Any) -> tuple[Any, str]:
    from setp_solver.search.candidates import make_shared_initial_solution

    return make_shared_initial_solution(bundle, prices=prices), "rebuilt_make_shared_initial_solution"


def ev_maximal_reference(category: str, instance_name: str, size: int, battery_kwh: float, bundle: Any, prices: Any, neutral_solution: Any) -> tuple[Any, str]:
    from setp_solver.search.metaheuristic_baselines import solution_from_dict

    path = REPO_ROOT / "baselines/e2_alns/threeshift_280_stageA_generalization_data/ev_maximal_solutions" / f"{instance_name}__B{float(battery_kwh):g}.json"
    if path.exists():
        payload = regime.read_json(path)
        return solution_from_dict(payload["solution"]), str(path.relative_to(REPO_ROOT))
    solution, _attempts = regime.build_ev_maximal_solution(neutral_solution, bundle, prices, category, instance_name, size, battery_kwh)
    return solution, "rebuilt_ev_maximal_from_neutral"


def ev_swap_audit_instance(category: str, instance_name: str, size: int, battery_kwh: float) -> list[dict[str, Any]]:
    from setp_solver.check import check_solution
    from setp_solver.cost import evaluate
    from setp_solver.prices import DEFAULT_PRICES
    from setp_solver.search.bundle import load_search_bundle
    from setp_solver.search.charging import repair_route_charging
    from setp_solver.search.fleet import normalize_solution_vehicle_trips
    from setp_solver.solution import Solution

    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(battery_kwh), carbon_price=CARBON_PRICE)
    bundle = load_search_bundle(regime.bundle_path(category, instance_name))
    neutral, seed_source = neutral_seed(bundle, prices)
    before_metrics = evaluate(neutral, bundle.instance, bundle.carbon_profile, prices)
    before_cost = float(before_metrics["total_cost"])
    rows = []
    cv_routes = [route for route in neutral.routes if route.vehicle_type.lower() == "cv"]
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    for order, route in enumerate(cv_routes, start=1):
        row = {
            "category": category,
            "instance": instance_name,
            "size": int(size),
            "battery_kwh": float(battery_kwh),
            "seed_source": seed_source,
            "attempt_order": order,
            "route_id": route.vehicle_id,
            "route_customer_count": sum(1 for node_id in route.node_sequence if node_lookup[node_id].node_type.lower() == "c"),
            "cost_before": before_cost,
            "cost_after": math.inf,
            "cost_delta": math.inf,
            "cost_delta_pct": math.inf,
            "ev_share_before": ev_route_share(neutral),
            "ev_share_after": math.nan,
            "charging_actions_after": 0,
            "feasible": False,
            "accepted": False,
            "failure_reason": "",
            "failure_detail": "",
        }
        try:
            ev_route = replace(route, vehicle_id=f"EV_AUDIT_{order}", vehicle_type="ev")
            repaired_route, actions = repair_route_charging(ev_route, bundle.instance, bundle.carbon_profile, prices)
            candidate_routes = [repaired_route if item.vehicle_id == route.vehicle_id else item for item in neutral.routes]
            kept_actions = [action for action in neutral.charging_actions if action.vehicle_id not in {route.vehicle_id, ev_route.vehicle_id}]
            candidate = Solution(routes=candidate_routes, charging_actions=[*kept_actions, *actions], cross_site_services=neutral.cross_site_services)
            candidate = normalize_solution_vehicle_trips(candidate, bundle.instance)
            violations = check_solution(candidate, bundle.instance, prices)
            if violations:
                row["failure_reason"] = regime.classify_violation(violations)
                row["failure_detail"] = "; ".join(f"{v.type}:{v.vehicle_id}:{v.location}:{v.detail}" for v in violations[:6])
                rows.append(row)
                continue
            after_metrics = evaluate(candidate, bundle.instance, bundle.carbon_profile, prices)
            after_cost = float(after_metrics["total_cost"])
            row["feasible"] = True
            row["cost_after"] = after_cost
            row["cost_delta"] = after_cost - before_cost
            row["cost_delta_pct"] = regime.pct_gap(after_cost, before_cost)
            row["ev_share_after"] = ev_route_share(candidate)
            row["charging_actions_after"] = len(candidate.charging_actions)
            if after_cost <= before_cost + 1e-9:
                row["accepted"] = True
                row["failure_reason"] = "ACCEPTED"
            else:
                row["failure_reason"] = "COST_WORSE"
        except Exception as exc:
            row["failure_reason"] = regime.classify_exception(exc)
            row["failure_detail"] = str(exc)
        rows.append(row)
    return rows


def findability_decision(phase0: dict[str, Any], rows: list[dict[str, Any]], audit_rows: list[dict[str, Any]], *, expected_rows: int) -> dict[str, Any]:
    if not phase0.get("phase0_ok"):
        verdict = "HALT_COLLECTION_COST"
        plain = "环境或默认参数锚漂移，不能解释找到能力。"
    elif expected_rows and len(rows) != expected_rows:
        verdict = "HALT_COLLECTION_COST"
        plain = "搜索行没有完整闭合，不能下找到能力结论。"
    else:
        signals = [row for row in rows if row_has_find_signal(row)]
        alns_signals = [row for row in signals if str(row.get("algorithm")) in ALNS_ALGORITHMS]
        non_alns_signals = [row for row in signals if str(row.get("algorithm")) not in ALNS_ALGORITHMS]
        accepted_audit = [row for row in audit_rows if regime.boolish(row.get("accepted"))]
        no_find = no_find_signal(rows)
        if alns_signals and len(non_alns_signals) >= 2:
            verdict = "PASS_ALL_FIND_OR_INSTANCE_EASY"
            plain = "ALNS 和多个非 ALNS 都能从中性起点接近 EV-heavy；这个实例不适合证明 ALNS 独有优势。"
        elif alns_signals:
            verdict = "PASS_ALNS_FIND_SIGNAL"
            plain = "至少一个 ALNS 变体从中性起点出现找到 EV-heavy 的信号；允许进入单实例长跑复核。"
        elif audit_rows and not accepted_audit:
            verdict = "HALT_NEIGHBORHOOD_NO_EV_PATH"
            plain = "逐条 CV→EV 审计找不到可行且不劣的转换路；当前邻域没有证明具备 Stage A 的构造能力。"
        elif accepted_audit and (no_find or rows):
            verdict = "HALT_SEARCH_CANNOT_USE_EV_PATH"
            plain = "审计能找到可行且不劣的 EV 转换，但搜索没有用上；下一步应设计专门 EV-conversion operator，而不是加时间。"
        elif no_find:
            verdict = "HALT_NO_FIND_SIGNAL"
            plain = "所有搜索都基本原样返回中性起点，没有找到能力信号；不允许扩大到大跑。"
        else:
            verdict = "HALT_COLLECTION_COST"
            plain = "证据不完整或不落入预注册判决，先回查 raw rows。"
    assert verdict in VERDICTS
    return {
        "verdict": verdict,
        "plain": plain,
        "rows": len(rows),
        "expected_rows": int(expected_rows),
        "audit_rows": len(audit_rows),
        "audit_accepted_nonworse": sum(1 for row in audit_rows if regime.boolish(row.get("accepted"))),
        "find_signal_rows": sum(1 for row in rows if row_has_find_signal(row)),
        "alns_find_signal_rows": sum(1 for row in rows if row_has_find_signal(row) and str(row.get("algorithm")) in ALNS_ALGORITHMS),
        "non_alns_find_signal_rows": sum(1 for row in rows if row_has_find_signal(row) and str(row.get("algorithm")) not in ALNS_ALGORITHMS),
        "max_closed_gap_fraction": max([regime.as_float(row.get("closed_gap_fraction")) for row in rows] or [0.0]),
        "max_ev_share_gain": max([regime.as_float(row.get("ev_share_gain")) for row in rows] or [0.0]),
        "returned_initial_count": sum(1 for row in rows if regime.boolish(row.get("returned_initial_signature"))),
        "criteria": "find signal = closes >=25% neutral-to-EV-maximal cost gap and EV share gain >=10pp",
    }


def row_has_find_signal(row: dict[str, Any]) -> bool:
    return (
        regime.as_float(row.get("closed_gap_fraction")) >= FIND_COST_CLOSURE_THRESHOLD
        and regime.as_float(row.get("ev_share_gain")) >= FIND_EV_GAIN_THRESHOLD
        and str(row.get("gate_status")) == "OK"
    )


def no_find_signal(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    max_improvement_pct = max([-regime.as_float(row.get("gap_vs_initial_pct")) for row in rows] or [0.0])
    max_ev_gain = max([regime.as_float(row.get("ev_share_gain")) for row in rows] or [0.0])
    all_returned = all(regime.boolish(row.get("returned_initial_signature")) for row in rows)
    return all_returned or (max_improvement_pct < NO_FIND_COST_IMPROVEMENT_PCT and max_ev_gain < NO_FIND_EV_GAIN_THRESHOLD)


def summarize_audit(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        reason = str(row.get("failure_reason", ""))
        counts[reason] = counts.get(reason, 0) + 1
    return [{"failure_reason": reason, "count": count} for reason, count in sorted(counts.items())]


def render_report(metadata: dict[str, Any], phase0: dict[str, Any], decision: dict[str, Any], rows: list[dict[str, Any]], audit_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# 09z ALNS EV-heavy Findability Gate",
        "",
        f"Evidence level: **{PROBE_LEVEL}**. This is a diagnostic gate, not formal T3.",
        "",
        f"Verdict: `{decision['verdict']}`",
        "",
        "## 人话结论",
        "",
        str(decision.get("plain", "")),
        "",
        "这一步只回答：不给 EV-heavy 答案，搜索能不能自己找到。它不证明正式算法胜负。",
        "",
        "## Phase 0",
        "",
        f"- Phase0 OK: `{phase0.get('phase0_ok')}`",
        f"- Defaults probe: `{json.dumps(phase0.get('default_probe', {}), sort_keys=True)}`",
        f"- Diagnostic battery override: `{phase0.get('diagnostic_battery_kwh')}` kWh",
        f"- HEAD: `{metadata.get('head')}`",
        "",
        "## Search Rows",
        "",
        "| algorithm | seed | initial | best | closed gap | EV gain | evals | returned initial | improvements |",
        "|---|---:|---:|---:|---:|---:|---:|---|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('algorithm')} | {row.get('seed')} | {regime.as_float(row.get('initial_cost')):.6f} | "
            f"{regime.as_float(row.get('best_cost')):.6f} | {regime.as_float(row.get('closed_gap_fraction')):.4f} | "
            f"{regime.as_float(row.get('ev_share_gain')):.4f} | {int(regime.as_float(row.get('actual_evals')))} | "
            f"{row.get('returned_initial_signature')} | {int(regime.as_float(row.get('best_improvement_count')))} |"
        )
    lines.extend([
        "",
        "## EV Swap Audit",
        "",
        f"- Audit rows: `{len(audit_rows)}`",
        f"- Accepted non-worse CV→EV conversions: `{sum(1 for row in audit_rows if regime.boolish(row.get('accepted')))}`",
        "",
        "| failure_reason | count |",
        "|---|---:|",
    ])
    for row in summarize_audit(audit_rows):
        lines.append(f"| {row.get('failure_reason')} | {row.get('count')} |")
    lines.extend([
        "",
        "## Artifacts",
        "",
        f"- Data dir: `{metadata.get('output_dir')}`",
        f"- Report: `{metadata.get('report_path')}`",
        f"- Raw rows: `{metadata.get('output_dir')}/raw_runs.csv`",
        f"- Swap audit rows: `{metadata.get('output_dir')}/ev_swap_audit_rows.csv`",
        "- Protected referee files unchanged: `cost.py`, `check.py`, `evaluation.py`, `prices.py`.",
    ])
    return "\n".join(lines).rstrip() + "\n"


def ev_route_share(solution: Any) -> float:
    routes = list(solution.routes)
    if not routes:
        return 0.0
    return sum(1 for route in routes if route.vehicle_type.lower() == "ev") / len(routes)


def closed_gap_fraction(initial_cost: float, best_cost: float, reference_cost: float) -> float:
    denom = initial_cost - reference_cost
    if denom <= 1e-9 or not math.isfinite(best_cost):
        return 0.0
    return max(0.0, (initial_cost - best_cost) / denom)


def best_improvement_count(history: list[dict[str, Any]]) -> int:
    return max(0, len(history) - 1)


def first_improvement_eval(history: list[dict[str, Any]]) -> int | str:
    if len(history) < 2:
        return ""
    try:
        return int(history[1].get("eval", ""))
    except Exception:
        return ""


def failure_row(task: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    return {
        **{key: task.get(key, "") for key in ("stage", "category", "instance", "size", "seed", "algorithm", "battery_kwh")},
        "status": status,
        "gate_status": status,
        "failure_reason": reason,
        "seed_mode": "neutral",
        "actual_evals": 0,
        "elapsed_seconds": 0.0,
    }


def timeout_row(task: dict[str, Any], elapsed: float, stdout: str | bytes | None, stderr: str | bytes | None) -> dict[str, Any]:
    row = failure_row(task, "HALT_HARD_TIMEOUT", "Worker exceeded runtime cap plus grace.")
    row["elapsed_seconds"] = elapsed
    row["worker_stdout_tail"] = regime.tail_text(stdout)
    row["worker_stderr_tail"] = regime.tail_text(stderr)
    return row


def load_existing_rows(path: Path) -> dict[tuple[str, str, int, str], dict[str, Any]]:
    if not path.exists():
        return {}
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    return {task_key(row): row for row in rows}


def read_optional_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return list(csv.DictReader(path.open(newline="", encoding="utf-8")))


def task_key(row: dict[str, Any]) -> tuple[str, str, int, str]:
    return (str(row.get("stage")), str(row.get("instance")), int(regime.as_float(row.get("seed", 0))), str(row.get("algorithm")))


def row_sort_key(row: dict[str, Any]) -> tuple[str, str, int, str]:
    return task_key(row)


def artifact_hashes(output_dir: Path, report_path: Path | None) -> dict[str, Any]:
    files = []
    paths = sorted(output_dir.glob("*.csv")) + sorted(output_dir.glob("*.json"))
    if report_path is not None:
        paths.append(report_path)
    for path in paths:
        if path.exists() and path.name != "artifact_hashes.json":
            files.append({"path": str(path), "sha256": regime.sha256_file(path)})
    return {"schema": "setp-09z-artifact-hashes.v1", "files": files}


if __name__ == "__main__":
    main()
