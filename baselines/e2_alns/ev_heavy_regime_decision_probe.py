"""09y EV-heavy feasibility and regime-decision probe.

This is a diagnostic runner, not a formal T3 harness.  It keeps the solver
semantics frozen and only varies battery capacity through in-memory
PriceParameters overrides.
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
import statistics
import subprocess
import sys
import time
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTANCE_ROOT = REPO_ROOT / "models/data_bundle/generated_instances/e2_benchmark"
GOLD_PYTHON = "/opt/anaconda3/bin/python3.13"
GOLD_NUMPY = "2.3.5"
CARBON_PRICE = 0.05034
BASELINE_EV_SHARE = 0.05734336969969154
PROBE_LEVEL = "PROBE / 非正式 T3"

REPRESENTATIVE_BIG = (
    ("vanilla", "e2-vanilla-150c-01", 150),
    ("vanilla", "e2-vanilla-200c-01", 200),
    ("multidepot", "e2-multidepot-150c-01", 150),
    ("multidepot", "e2-multidepot-200c-01", 200),
    ("threeshift", "e2-threeshift-150c-01", 150),
)
SMOKE_INSTANCES = (
    ("vanilla", "e2-vanilla-150c-01", 150),
)
VANILLA_MULTIDEPOT_SIZES = (10, 15, 20, 25, 50, 75, 100, 150, 200)
THREESHIFT_SIZES = (50, 75, 100, 150, 200)
STAGE1_ALGORITHMS = ("alns_e2_carbon", "LNS")
STAGE2_ALGORITHMS = ("alns_e2_carbon", "alns_e2_carbon_ablation", "LNS", "GA", "PSO", "VNS", "GA-VNS")
STAGE0_VERDICTS = {
    "X_SEARCH_MISSED_FEASIBLE_EV",
    "Y_EV_FEASIBLE_BUT_EXPENSIVE",
    "Z_EV_PHYSICALLY_UNSUPPORTED_80KWH",
    "HALT_STAGE0_CONSTRUCTION_BROKEN",
}
STAGE1_VERDICTS = {
    "A_SEARCH_GAP_CONFIRMED",
    "A_EV_SEED_COLLAPSES_BACK",
    "A_EV_RETAINED_BUT_ALNS_TIES",
    "HALT_COLLECTION_COST",
    "SKIPPED_NO_STAGE0_X",
}
STAGE2_VERDICTS = {
    "B_MODERN_REGIME_WORKS",
    "B_MECHANISM_BUT_TIE",
    "B_NO_MIX_ANYWHERE",
    "B_CAP_BOUNDED",
    "HALT_COLLECTION_COST",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="stage", required=True)

    s0 = sub.add_parser("stage0")
    s0.add_argument("--smoke", action="store_true")
    s0.add_argument("--instances", choices=("representative_big", "gradient01_75_200"), default="representative_big")
    s0.add_argument("--battery-kwh", type=float, default=80.0)
    s0.add_argument("--output-dir", required=True)
    s0.add_argument("--report-path", required=True)

    s1 = sub.add_parser("stage1")
    s1.add_argument("--instances", choices=("gradient01_75_200",), default="gradient01_75_200")
    s1.add_argument("--seeds", default="1-3")
    s1.add_argument("--workers", type=int, default=2)
    s1.add_argument("--output-dir", required=True)
    s1.add_argument("--report-path", required=True)
    s1.add_argument("--retry-failures", action="store_true")
    s1.add_argument("--stage0-dir", default="baselines/e2_alns/ev_heavy_regime_stage0_data")

    s2 = sub.add_parser("stage2")
    s2.add_argument("--battery-kwh", type=float, default=280.0)
    s2.add_argument("--instances", choices=("representative_big",), default="representative_big")
    s2.add_argument("--seeds", default="1-3")
    s2.add_argument("--workers", type=int, default=2)
    s2.add_argument("--algorithms", default=",".join(STAGE2_ALGORITHMS))
    s2.add_argument("--output-dir", required=True)
    s2.add_argument("--report-path", required=True)
    s2.add_argument("--retry-failures", action="store_true")
    s2.add_argument("--stage0-dir", default="baselines/e2_alns/ev_heavy_regime_stage0_data")

    syn = sub.add_parser("synthesis")
    syn.add_argument("--stage0-dir", default="baselines/e2_alns/ev_heavy_regime_stage0_data")
    syn.add_argument("--stage1-dir", default="baselines/e2_alns/ev_seeded_search_stage1_data")
    syn.add_argument("--stage2-dir", default="baselines/e2_alns/modern_battery_regime_stage2_data")
    syn.add_argument("--report-path", default="baselines/e2_alns/ev_heavy_regime_synthesis.md")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.stage == "stage0":
        run_stage0(args)
    elif args.stage == "stage1":
        run_stage1(args)
    elif args.stage == "stage2":
        run_stage2(args)
    elif args.stage == "synthesis":
        run_synthesis(args)
    else:
        raise ValueError(args.stage)


def run_stage0(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    report_path = Path(args.report_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "ev_maximal_solutions").mkdir(exist_ok=True)
    metadata = build_metadata(output_dir, report_path, "stage0", battery_kwh=float(args.battery_kwh))
    write_json(output_dir / "metadata.json", metadata)
    phase0 = phase0_audit(float(args.battery_kwh))
    write_json(output_dir / "phase0_audit.json", phase0)

    instances = list(SMOKE_INSTANCES if args.smoke else select_instances(args.instances))
    baseline_rows: list[dict[str, Any]] = []
    attempt_rows: list[dict[str, Any]] = []
    ev_rows: list[dict[str, Any]] = []
    for category, instance_name, size in instances:
        result = stage0_instance(category, instance_name, size, float(args.battery_kwh), output_dir)
        baseline_rows.append(result["baseline_row"])
        attempt_rows.extend(result["attempt_rows"])
        ev_rows.append(result["ev_row"])

    write_csv(output_dir / "baseline_rows.csv", baseline_rows)
    write_csv(output_dir / "conversion_attempts.csv", attempt_rows)
    write_csv(output_dir / "ev_maximal_rows.csv", ev_rows)
    failure_summary = summarize_failures(attempt_rows)
    write_csv(output_dir / "failure_reason_summary.csv", failure_summary)
    decision = stage0_decision(phase0, ev_rows, attempt_rows)
    write_json(output_dir / "stage0_decision.json", decision)
    report_path.write_text(render_stage0_report(metadata, phase0, decision, ev_rows, failure_summary), encoding="utf-8")
    write_json(output_dir / "artifact_hashes.json", artifact_hashes(output_dir, report_path))
    return decision


def stage0_instance(category: str, instance_name: str, size: int, battery_kwh: float, output_dir: Path) -> dict[str, Any]:
    from setp_solver.check import check_solution
    from setp_solver.cost import evaluate
    from setp_solver.prices import DEFAULT_PRICES
    from setp_solver.search.bundle import load_search_bundle
    from setp_solver.search.carbon_operators import low_carbon_charging_share
    from setp_solver.search.metaheuristic_baselines import solution_to_dict

    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(battery_kwh), carbon_price=CARBON_PRICE)
    bundle_dir = bundle_path(category, instance_name)
    bundle = load_search_bundle(bundle_dir)
    baseline, source = load_baseline_solution(bundle, instance_name, prices)
    baseline_violations = check_solution(baseline, bundle.instance, prices)
    if baseline_violations:
        raise RuntimeError(f"baseline infeasible for {instance_name}: {baseline_violations[:3]}")
    baseline_metrics = evaluate(baseline, bundle.instance, bundle.carbon_profile, prices)
    baseline_row = solution_row("baseline", category, instance_name, size, battery_kwh, baseline, bundle, prices, baseline_metrics)
    baseline_row["baseline_source"] = source

    ev_solution, attempt_rows = build_ev_maximal_solution(baseline, bundle, prices, category, instance_name, size, battery_kwh)
    ev_violations = check_solution(ev_solution, bundle.instance, prices)
    ev_metrics = evaluate(ev_solution, bundle.instance, bundle.carbon_profile, prices) if not ev_violations else {}
    ev_row = solution_row("ev_maximal", category, instance_name, size, battery_kwh, ev_solution, bundle, prices, ev_metrics)
    ev_row["baseline_source"] = source
    ev_row["baseline_cost"] = baseline_row["total_cost"]
    ev_row["baseline_E_total"] = baseline_row["E_total"]
    ev_row["cost_gap_pct_vs_baseline"] = pct_gap(ev_row["total_cost"], baseline_row["total_cost"])
    ev_row["E_total_gap_pct_vs_baseline"] = pct_gap(ev_row["E_total"], baseline_row["E_total"])
    ev_row["accepted_conversions"] = sum(1 for row in attempt_rows if row["accepted"])
    ev_row["attempted_conversions"] = len(attempt_rows)
    ev_row["dominant_failure_reason"] = dominant_failure(attempt_rows)
    ev_row["instance_verdict"] = classify_stage0_instance(ev_row, attempt_rows)
    solution_path = output_dir / "ev_maximal_solutions" / f"{instance_name}__B{battery_kwh:g}.json"
    write_json(solution_path, {"solution": solution_to_dict(ev_solution), "instance": instance_name, "battery_kwh": battery_kwh})
    ev_row["solution_path"] = str(solution_path)
    ev_row["low_carbon_charging_share"] = low_carbon_charging_share(ev_solution, bundle.instance, bundle.carbon_profile, prices)
    baseline_row["low_carbon_charging_share"] = low_carbon_charging_share(baseline, bundle.instance, bundle.carbon_profile, prices)
    return {"baseline_row": baseline_row, "attempt_rows": attempt_rows, "ev_row": ev_row}


def build_ev_maximal_solution(solution: Any, bundle: Any, prices: Any, category: str, instance_name: str, size: int, battery_kwh: float) -> tuple[Any, list[dict[str, Any]]]:
    from dataclasses import replace as dc_replace

    from setp_solver.check import check_solution
    from setp_solver.cost import evaluate, ev_arc_energy_kwh
    from setp_solver.search.charging import repair_route_charging
    from setp_solver.search.fleet import infer_fleet_limits, normalize_solution_vehicle_trips
    from setp_solver.solution import Solution, physical_vehicle_id

    current = solution
    rows: list[dict[str, Any]] = []
    node_lookup = {node.node_id: node for node in bundle.instance.nodes}
    limits = infer_fleet_limits(bundle.bundle_dir)

    def route_key(route: Any) -> tuple[float, float, str]:
        customers = [node_id for node_id in route.node_sequence if node_lookup[node_id].node_type.lower() == "c"]
        demand = sum(float(node_lookup[node_id].demand) for node_id in customers)
        distance = sum(bundle.instance.distance(a, b) for a, b in zip(route.node_sequence, route.node_sequence[1:]))
        return (-demand, -distance, route.vehicle_id)

    route_ids = [route.vehicle_id for route in sorted(current.routes, key=route_key) if route.vehicle_type.lower() == "cv"]
    for order, original_route_id in enumerate(route_ids, start=1):
        route = next((item for item in current.routes if item.vehicle_id == original_route_id and item.vehicle_type.lower() == "cv"), None)
        if route is None:
            continue
        before_metrics = evaluate(current, bundle.instance, bundle.carbon_profile, prices)
        ev_count = len({physical_vehicle_id(item.vehicle_id) for item in current.routes if item.vehicle_type.lower() == "ev"})
        row = {
            "category": category,
            "instance": instance_name,
            "size": size,
            "battery_kwh": battery_kwh,
            "attempt_order": order,
            "route_id": route.vehicle_id,
            "route_customer_count": sum(1 for node_id in route.node_sequence if node_lookup[node_id].node_type.lower() == "c"),
            "ev_physical_vehicle_count_before": ev_count,
            "ev_fleet_limit": int(limits.ev),
            "accepted": False,
            "failure_reason": "",
            "failure_detail": "",
            "cost_before": float(before_metrics.get("total_cost", math.inf)),
            "cost_after": math.inf,
        }
        if int(limits.ev) <= 0:
            row["failure_reason"] = "FLEET_HEADROOM_EXHAUSTED"
            row["failure_detail"] = "num_ev<=0"
            rows.append(row)
            continue
        try:
            ev_route = dc_replace(route, vehicle_id=f"EV_CONV_{order}", vehicle_type="ev")
            repaired_route, actions = repair_route_charging(ev_route, bundle.instance, bundle.carbon_profile, prices)
            candidate_routes = [repaired_route if item.vehicle_id == route.vehicle_id else item for item in current.routes]
            kept_actions = [action for action in current.charging_actions if action.vehicle_id != route.vehicle_id and action.vehicle_id != ev_route.vehicle_id]
            candidate = Solution(routes=candidate_routes, charging_actions=[*kept_actions, *actions], cross_site_services=current.cross_site_services)
            candidate = normalize_solution_vehicle_trips(candidate, bundle.instance)
            violations = check_solution(candidate, bundle.instance, prices)
            if violations:
                row["failure_reason"] = classify_violation(violations)
                row["failure_detail"] = "; ".join(f"{v.type}:{v.vehicle_id}:{v.location}:{v.detail}" for v in violations[:6])
                rows.append(row)
                continue
            after_metrics = evaluate(candidate, bundle.instance, bundle.carbon_profile, prices)
            row["accepted"] = True
            row["cost_after"] = float(after_metrics.get("total_cost", math.inf))
            row["failure_reason"] = "ACCEPTED"
            current = candidate
        except Exception as exc:
            row["failure_reason"] = classify_exception(exc)
            row["failure_detail"] = str(exc)
        rows.append(row)
    return current, rows


def run_stage1(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    report_path = Path(args.report_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "ev_maximal_solutions").mkdir(exist_ok=True)
    metadata = build_metadata(output_dir, report_path, "stage1", battery_kwh=80.0)
    write_json(output_dir / "metadata.json", metadata)
    stage0 = read_json(Path(args.stage0_dir) / "stage0_decision.json")
    if not any(row.get("instance_verdict") == "X_SEARCH_MISSED_FEASIBLE_EV" for row in stage0.get("instance_rows", [])):
        decision = {"verdict": "SKIPPED_NO_STAGE0_X", "plain": "Stage 0 没有 X 类实例；不烧 EV-seeded 搜索。", "rows": 0, "collection_failure_count": 0}
        write_json(output_dir / "stage1_decision.json", decision)
        report_path.write_text(render_stage1_report(metadata, decision, [], []), encoding="utf-8")
        write_json(output_dir / "artifact_hashes.json", artifact_hashes(output_dir, report_path))
        return decision

    tasks = []
    seeds = parse_seeds(args.seeds)
    for category, instance_name, size in select_instances(args.instances):
        for seed in seeds:
            for algorithm in STAGE1_ALGORITHMS:
                tasks.append(build_search_task("stage1", output_dir, category, instance_name, size, seed, algorithm, 80.0, args.stage0_dir))
    rows = run_search_tasks(tasks, workers=int(args.workers))
    write_csv(output_dir / "raw_runs.csv", rows)
    pairs = pair_rows(rows, "alns_e2_carbon", "LNS")
    write_csv(output_dir / "paired_summary.csv", pairs)
    decision = stage1_decision(rows, pairs)
    write_json(output_dir / "stage1_decision.json", decision)
    report_path.write_text(render_stage1_report(metadata, decision, rows, pairs), encoding="utf-8")
    write_json(output_dir / "artifact_hashes.json", artifact_hashes(output_dir, report_path))
    return decision


def run_stage2(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    report_path = Path(args.report_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = build_metadata(output_dir, report_path, "stage2", battery_kwh=float(args.battery_kwh))
    write_json(output_dir / "metadata.json", metadata)
    headroom = headroom_audit(select_instances(args.instances), float(args.battery_kwh))
    write_csv(output_dir / "headroom_audit.csv", headroom)

    construction_rows: list[dict[str, Any]] = []
    for category, instance_name, size in select_instances(args.instances):
        construction_rows.append(stage0_instance(category, instance_name, size, float(args.battery_kwh), output_dir)["ev_row"])
    write_csv(output_dir / "ev_maximal_280_rows.csv", construction_rows)

    if majority_cap_bounded(headroom):
        decision = {"verdict": "B_CAP_BOUNDED", "plain": "多数大实例 physical EV headroom 不足 20%；这说明 regime 被 fleet headroom 限住，不写算法失败。", "rows": 0, "collection_failure_count": 0}
        write_json(output_dir / "stage2_decision.json", decision)
        report_path.write_text(render_stage2_report(metadata, decision, headroom, construction_rows, [], []), encoding="utf-8")
        write_json(output_dir / "artifact_hashes.json", artifact_hashes(output_dir, report_path))
        return decision

    nondegenerate = [row for row in construction_rows if 0.20 <= as_float(row.get("ev_route_share")) <= 0.80]
    if not nondegenerate:
        decision = {"verdict": "B_NO_MIX_ANYWHERE", "plain": "280kWh 构造后仍没有非退化混合 EV regime；不烧算法大对比。", "rows": 0, "collection_failure_count": 0}
        write_json(output_dir / "stage2_decision.json", decision)
        report_path.write_text(render_stage2_report(metadata, decision, headroom, construction_rows, [], []), encoding="utf-8")
        write_json(output_dir / "artifact_hashes.json", artifact_hashes(output_dir, report_path))
        return decision

    algorithms = tuple(item.strip() for item in str(args.algorithms).split(",") if item.strip())
    tasks = []
    for category, instance_name, size in select_instances(args.instances):
        for seed in parse_seeds(args.seeds):
            for algorithm in algorithms:
                tasks.append(build_search_task("stage2", output_dir, category, instance_name, size, seed, algorithm, float(args.battery_kwh), str(output_dir)))
    rows = run_search_tasks(tasks, workers=int(args.workers))
    write_csv(output_dir / "raw_runs.csv", rows)
    pairs_lns = pair_rows(rows, "alns_e2_carbon", "LNS")
    pairs_ablation = pair_rows(rows, "alns_e2_carbon", "alns_e2_carbon_ablation")
    write_csv(output_dir / "paired_vs_lns.csv", pairs_lns)
    write_csv(output_dir / "paired_vs_ablation.csv", pairs_ablation)
    decision = stage2_decision(rows, pairs_lns, pairs_ablation)
    write_json(output_dir / "stage2_decision.json", decision)
    report_path.write_text(render_stage2_report(metadata, decision, headroom, construction_rows, rows, pairs_lns + pairs_ablation), encoding="utf-8")
    write_json(output_dir / "artifact_hashes.json", artifact_hashes(output_dir, report_path))
    return decision


def build_search_task(stage: str, output_dir: Path, category: str, instance_name: str, size: int, seed: int, algorithm: str, battery_kwh: float, seed_dir: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "repo_root": str(REPO_ROOT),
        "output_dir": str(output_dir),
        "category": category,
        "instance": instance_name,
        "size": size,
        "seed": int(seed),
        "algorithm": algorithm,
        "battery_kwh": float(battery_kwh),
        "bundle_dir": str(bundle_path(category, instance_name).relative_to(REPO_ROOT)),
        "eval_budget": 16_000,
        "runtime_cap_seconds": runtime_cap(size),
        "seed_dir": seed_dir,
    }


def run_search_tasks(tasks: list[dict[str, Any]], *, workers: int) -> list[dict[str, Any]]:
    if workers <= 1:
        return [run_search_task(task) for task in tasks]
    from concurrent.futures import ProcessPoolExecutor, as_completed

    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=int(workers)) as pool:
        future_map = {pool.submit(run_search_task, task): task for task in tasks}
        for future in as_completed(future_map):
            rows.append(future.result())
    return sorted(rows, key=lambda row: (row.get("instance", ""), int(row.get("seed", 0)), row.get("algorithm", "")))


def run_search_task(task: dict[str, Any]) -> dict[str, Any]:
    from setp_solver.check import check_solution
    from setp_solver.cost import evaluate
    from setp_solver.prices import DEFAULT_PRICES
    from setp_solver.search.bundle import load_search_bundle
    from setp_solver.search.carbon_operators import low_carbon_charging_share
    from setp_solver.search.metaheuristic_baselines import run_metaheuristic_baseline
    from setp_solver.search.winner_operators import WinnerKernelConfig, run_e2_alns_carbon

    started = time.perf_counter()
    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(task["battery_kwh"]), carbon_price=CARBON_PRICE)
    bundle = load_search_bundle(Path(task["repo_root"]) / task["bundle_dir"])
    initial_solution, seed_source = load_or_build_seed_for_search(task, bundle, prices)
    algorithm = str(task["algorithm"])
    operator_counts: dict[str, Any] = {}
    status = "OK"
    failure_reason = ""
    try:
        if algorithm in {"alns_e2_carbon", "alns_e2_carbon_ablation"}:
            result = run_e2_alns_carbon(
                bundle.bundle_dir,
                config=WinnerKernelConfig(seed=int(task["seed"]), eval_budget=int(task["eval_budget"]), max_runtime_seconds=float(task["runtime_cap_seconds"])),
                initial_solution=initial_solution,
                prices=prices,
                carbon_bias_weight=0.0 if algorithm.endswith("ablation") else 1.0,
                variant_id=algorithm,
            )
            solution = result["best_solution"]
            best_cost = float(result["best_cost"])
            actual_evals = int(result["evaluations"])
            violation_count = int(result["violation_count"])
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
            violation_count = int(result.violation_count)
            status = result.status
            failure_reason = result.failure_reason
    except Exception as exc:
        return task_failure_row(task, started, "HALT_WORKER_EXCEPTION", repr(exc))

    violations = check_solution(solution, bundle.instance, prices) if solution is not None else []
    metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices) if solution is not None and not violations else {}
    if violations:
        status = "HALT_INFEASIBLE"
        failure_reason = "; ".join(str(item) for item in violations[:3])
    elif actual_evals < int(task["eval_budget"]):
        status = "HALT_RUNTIME_UNDER_EVAL"
        failure_reason = failure_reason or f"Stopped at {actual_evals}/{task['eval_budget']} evals"
    return search_row(task, status, failure_reason, started, solution, metrics, best_cost, actual_evals, len(violations), operator_counts, seed_source, low_carbon_charging_share(solution, bundle.instance, bundle.carbon_profile, prices) if solution is not None else 0.0)


def load_or_build_seed_for_search(task: dict[str, Any], bundle: Any, prices: Any) -> tuple[Any, str]:
    from setp_solver.search.candidates import make_shared_initial_solution
    from setp_solver.search.metaheuristic_baselines import solution_from_dict

    if task["stage"] == "stage1":
        path = Path(task["seed_dir"]) / "ev_maximal_solutions" / f"{task['instance']}__B80.json"
    else:
        path = Path(task["seed_dir"]) / "ev_maximal_solutions" / f"{task['instance']}__B{float(task['battery_kwh']):g}.json"
    if path.exists():
        payload = read_json(path)
        return solution_from_dict(payload["solution"]), str(path)
    baseline, source = load_baseline_solution(bundle, str(task["instance"]), prices)
    seed, _attempts = build_ev_maximal_solution(baseline, bundle, prices, str(task["category"]), str(task["instance"]), int(task["size"]), float(task["battery_kwh"]))
    return seed, f"rebuilt_ev_maximal_from:{source}"


def search_row(task: dict[str, Any], status: str, failure_reason: str, started: float, solution: Any, metrics: dict[str, Any], best_cost: float, actual_evals: int, violation_count: int, operator_counts: dict[str, Any], seed_source: str, low_carbon_share: float) -> dict[str, Any]:
    route_count = len(solution.routes) if solution is not None else 0
    ev_routes = sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev") if solution is not None else 0
    return {
        **{key: task[key] for key in ("stage", "category", "instance", "size", "seed", "algorithm", "battery_kwh")},
        "status": status,
        "gate_status": "OK" if status == "OK" and violation_count == 0 else status,
        "failure_reason": failure_reason,
        "best_cost": best_cost,
        "actual_evals": actual_evals,
        "elapsed_seconds": max(0.0, time.perf_counter() - started),
        "violation_count": violation_count,
        "route_count": route_count,
        "ev_route_count": ev_routes,
        "cv_route_count": route_count - ev_routes,
        "ev_route_share": ev_routes / route_count if route_count else 0.0,
        "charging_action_count": len(solution.charging_actions) if solution is not None else 0,
        "low_carbon_charging_share": float(low_carbon_share),
        "E_total": as_float(metrics.get("E_total")),
        "cost_carbon": as_float(metrics.get("cost_carbon")),
        "seed_source": seed_source,
        "python": sys.executable,
        "numpy": numpy_version(),
        "carbon_best_improvements": carbon_best_improvements(operator_counts),
        "operator_counts": json.dumps(operator_counts, ensure_ascii=False, sort_keys=True),
    }


def task_failure_row(task: dict[str, Any], started: float, status: str, reason: str) -> dict[str, Any]:
    return {
        **{key: task[key] for key in ("stage", "category", "instance", "size", "seed", "algorithm", "battery_kwh")},
        "status": status,
        "gate_status": status,
        "failure_reason": reason,
        "best_cost": math.inf,
        "actual_evals": 0,
        "elapsed_seconds": max(0.0, time.perf_counter() - started),
        "violation_count": 99,
        "route_count": 0,
        "ev_route_count": 0,
        "cv_route_count": 0,
        "ev_route_share": 0.0,
        "charging_action_count": 0,
        "low_carbon_charging_share": 0.0,
        "E_total": math.inf,
        "cost_carbon": math.inf,
        "seed_source": "",
        "python": sys.executable,
        "numpy": numpy_version(),
        "carbon_best_improvements": 0,
        "operator_counts": "{}",
    }


def load_baseline_solution(bundle: Any, instance_name: str, prices: Any) -> tuple[Any, str]:
    from setp_solver.search.candidates import make_shared_initial_solution
    from setp_solver.search.metaheuristic_baselines import solution_from_dict

    candidates = [
        REPO_ROOT / "baselines/e2_alns/high_tension_separation_probe_09w_stage_a_data/checkpoints/wc80" / f"{instance_name}__alns_e2_throughput__seed1.json",
        REPO_ROOT / "baselines/e2_alns/carbon_aware_operator_probe_data/checkpoints/wc80" / f"{instance_name}__alns_e2_throughput__seed1.json",
    ]
    for path in candidates:
        if path.exists():
            payload = read_json(path)
            return solution_from_dict(payload["solution"]), str(path.relative_to(REPO_ROOT))
    return make_shared_initial_solution(bundle, prices=prices), "rebuilt_make_shared_initial_solution"


def solution_row(label: str, category: str, instance_name: str, size: int, battery_kwh: float, solution: Any, bundle: Any, prices: Any, metrics: dict[str, Any]) -> dict[str, Any]:
    from setp_solver.check import check_solution
    from setp_solver.solution import physical_vehicle_id

    violations = check_solution(solution, bundle.instance, prices)
    route_count = len(solution.routes)
    ev_routes = sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev")
    cv_routes = route_count - ev_routes
    ev_phys = len({physical_vehicle_id(route.vehicle_id) for route in solution.routes if route.vehicle_type.lower() == "ev"})
    cv_phys = len({physical_vehicle_id(route.vehicle_id) for route in solution.routes if route.vehicle_type.lower() == "cv"})
    return {
        "row_type": label,
        "category": category,
        "instance": instance_name,
        "size": size,
        "battery_kwh": float(battery_kwh),
        "status": "OK" if not violations else "HALT_INFEASIBLE",
        "violation_count": len(violations),
        "route_count": route_count,
        "cv_route_count": cv_routes,
        "ev_route_count": ev_routes,
        "ev_route_share": ev_routes / route_count if route_count else 0.0,
        "cv_physical_vehicle_count": cv_phys,
        "ev_physical_vehicle_count": ev_phys,
        "charging_action_count": len(solution.charging_actions),
        "total_cost": as_float(metrics.get("total_cost")),
        "E_total": as_float(metrics.get("E_total")),
        "E_cv_direct": as_float(metrics.get("E_cv_direct")),
        "E_ev_indirect": as_float(metrics.get("E_ev_indirect")),
        "cost_carbon": as_float(metrics.get("cost_carbon")),
    }


def classify_stage0_instance(row: dict[str, Any], attempts: list[dict[str, Any]]) -> str:
    accepted = int(row.get("accepted_conversions", 0))
    if accepted > 0:
        ev_gain = as_float(row.get("ev_route_share")) - BASELINE_EV_SHARE
        if ev_gain < 0.10:
            dominant = dominant_failure(attempts)
            if dominant in {"RANGE_BATTERY_80KWH", "CHARGING_TIME_WINDOW_DETOUR", "STATION_OR_DEPOT_CAPACITY"}:
                return "Z_EV_PHYSICALLY_UNSUPPORTED_80KWH"
            return "HALT_STAGE0_CONSTRUCTION_BROKEN"
        cost_ok = as_float(row.get("cost_gap_pct_vs_baseline")) <= 2.0
        carbon_ok = as_float(row.get("E_total_gap_pct_vs_baseline")) <= 2.0
        if cost_ok and carbon_ok:
            return "X_SEARCH_MISSED_FEASIBLE_EV"
        return "Y_EV_FEASIBLE_BUT_EXPENSIVE"
    dominant = dominant_failure(attempts)
    if dominant in {"RANGE_BATTERY_80KWH", "CHARGING_TIME_WINDOW_DETOUR"}:
        return "Z_EV_PHYSICALLY_UNSUPPORTED_80KWH"
    return "HALT_STAGE0_CONSTRUCTION_BROKEN"


def stage0_decision(phase0: dict[str, Any], ev_rows: list[dict[str, Any]], attempts: list[dict[str, Any]]) -> dict[str, Any]:
    if not phase0.get("phase0_ok"):
        verdict = "HALT_STAGE0_CONSTRUCTION_BROKEN"
        plain = "环境或默认物理参数锚漂移；不解释 EV-heavy 可行性。"
    else:
        verdicts = [str(row.get("instance_verdict")) for row in ev_rows]
        if any(item == "X_SEARCH_MISSED_FEASIBLE_EV" for item in verdicts):
            verdict = "X_SEARCH_MISSED_FEASIBLE_EV"
            plain = "至少一个大实例能构造出成本/碳不劣的 EV-heavy 解；下一步只对这些 X 信号做 EV-seeded 搜索验证。"
        elif any(item == "Y_EV_FEASIBLE_BUT_EXPENSIVE" for item in verdicts):
            verdict = "Y_EV_FEASIBLE_BUT_EXPENSIVE"
            plain = "EV-heavy 可构造，但相对 incumbent 明显更贵或碳不占优；Goeke80 下更像经济性不足。"
        elif all(item == "Z_EV_PHYSICALLY_UNSUPPORTED_80KWH" for item in verdicts):
            verdict = "Z_EV_PHYSICALLY_UNSUPPORTED_80KWH"
            plain = "代表大实例多数 CV→EV 失败来自续航或时间窗，80kWh 物理/时间窗不支持 EV-heavy。"
        else:
            verdict = "HALT_STAGE0_CONSTRUCTION_BROKEN"
            plain = "EV-maximal 构造没有形成可解释的 X/Y/Z 结论，先回查失败分类。"
    assert verdict in STAGE0_VERDICTS
    return {
        "verdict": verdict,
        "plain": plain,
        "instance_rows": ev_rows,
        "failure_reason_summary": summarize_failures(attempts),
        "stage1_recommended": verdict == "X_SEARCH_MISSED_FEASIBLE_EV",
        "stage2_recommended": verdict in {"Y_EV_FEASIBLE_BUT_EXPENSIVE", "Z_EV_PHYSICALLY_UNSUPPORTED_80KWH"},
        "collection_failure_count": 0 if verdict != "HALT_STAGE0_CONSTRUCTION_BROKEN" else 1,
    }


def stage1_decision(rows: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> dict[str, Any]:
    failures = collection_failures(rows)
    if failures:
        verdict = "HALT_COLLECTION_COST"
        plain = "Stage 1 数据未闭合或出现违约/环境漂移，不能下搜索结论。"
    else:
        winner_rows = [row for row in rows if str(row.get("algorithm")) == "alns_e2_carbon"]
        mean_ev = safe_mean(as_float(row.get("ev_route_share")) for row in winner_rows)
        mean_charge = safe_mean(as_float(row.get("charging_action_count")) for row in winner_rows)
        p = wilcoxon_or_sign([as_float(row.get("gap_pct_left_minus_right")) for row in pairs])["p_value_less"]
        wins = sum(1 for row in pairs if as_float(row.get("gap_pct_left_minus_right")) < -1e-9)
        losses = sum(1 for row in pairs if as_float(row.get("gap_pct_left_minus_right")) > 1e-9)
        retained = mean_ev >= BASELINE_EV_SHARE + 0.10 and mean_charge >= 1.0
        if retained and wins > losses and p < 0.05:
            verdict = "A_SEARCH_GAP_CONFIRMED"
            plain = "EV-seeded 搜索留住 EV 头寸，且 ALNS 相对 LNS 出现统计分离。"
        elif not retained:
            verdict = "A_EV_SEED_COLLAPSES_BACK"
            plain = "EV-seeded 起点在搜索后塌回默认近全-CV/低充电头寸；默认搜索锚仍压回 Goeke80 结构。"
        else:
            verdict = "A_EV_RETAINED_BUT_ALNS_TIES"
            plain = "EV 头寸留住了，但 vanilla carbon-aware ALNS 仍未相对 LNS 分离；算法贡献应转 DR-ALNS 或更强机制。"
    assert verdict in STAGE1_VERDICTS
    return {
        "verdict": verdict,
        "plain": plain,
        "rows": len(rows),
        "paired_rows": len(pairs),
        "collection_failure_count": len(failures),
        "failure_sample": failures[:10],
        "mean_alns_ev_route_share": safe_mean(as_float(row.get("ev_route_share")) for row in rows if str(row.get("algorithm")) == "alns_e2_carbon"),
        "mean_alns_charging_action_count": safe_mean(as_float(row.get("charging_action_count")) for row in rows if str(row.get("algorithm")) == "alns_e2_carbon"),
        "mean_carbon_best_improvements": safe_mean(as_float(row.get("carbon_best_improvements")) for row in rows if str(row.get("algorithm")) == "alns_e2_carbon"),
    }


def stage2_decision(rows: list[dict[str, Any]], pairs_lns: list[dict[str, Any]], pairs_ablation: list[dict[str, Any]]) -> dict[str, Any]:
    failures = collection_failures(rows)
    if failures:
        verdict = "HALT_COLLECTION_COST"
        plain = "Stage 2 算法对比数据未闭合或有违约，不能解释 modern regime。"
    else:
        lns_stats = wilcoxon_or_sign([as_float(row.get("gap_pct_left_minus_right")) for row in pairs_lns])
        ablation_stats = wilcoxon_or_sign([as_float(row.get("gap_pct_left_minus_right")) for row in pairs_ablation])
        wins_lns = sum(1 for row in pairs_lns if as_float(row.get("gap_pct_left_minus_right")) < -1e-9)
        losses_lns = sum(1 for row in pairs_lns if as_float(row.get("gap_pct_left_minus_right")) > 1e-9)
        carbon_on = lns_stats["p_value_less"] < 0.05 and wins_lns > losses_lns
        ablation_sig = ablation_stats["p_value_less"] < 0.05
        if carbon_on and ablation_sig:
            verdict = "B_MODERN_REGIME_WORKS"
            plain = "280kWh modern regime 下 ALNS 分离且碳消融显著，值得另起正式化 T3。"
        else:
            verdict = "B_MECHANISM_BUT_TIE"
            plain = "280kWh 让 EV/充电机制进场，但 vanilla ALNS 或碳消融仍未显著分离；算法贡献转 DR-ALNS。"
    assert verdict in STAGE2_VERDICTS
    return {"verdict": verdict, "plain": plain, "rows": len(rows), "paired_vs_lns": len(pairs_lns), "paired_vs_ablation": len(pairs_ablation), "collection_failure_count": len(failures), "failure_sample": failures[:10]}


def headroom_audit(instances: list[tuple[str, str, int]], battery_kwh: float) -> list[dict[str, Any]]:
    from setp_solver.prices import DEFAULT_PRICES
    from setp_solver.search.bundle import load_search_bundle
    from setp_solver.search.fleet import infer_fleet_limits

    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(battery_kwh), carbon_price=CARBON_PRICE)
    rows = []
    for category, instance_name, size in instances:
        bundle = load_search_bundle(bundle_path(category, instance_name))
        limits = infer_fleet_limits(bundle.bundle_dir)
        demand = sum(float(node.demand) for node in bundle.instance.nodes if node.node_type.lower() == "c")
        route_lb = max(1, math.ceil(demand / float(prices.Q_capacity)))
        ev_one_trip_share = min(1.0, float(limits.ev) / route_lb)
        ev_two_trip_share = min(1.0, float(limits.ev) * 2.0 / route_lb)
        rows.append({
            "category": category,
            "instance": instance_name,
            "size": size,
            "battery_kwh": battery_kwh,
            "num_cv": int(limits.cv),
            "num_ev": int(limits.ev),
            "total_demand": demand,
            "Q_capacity": float(prices.Q_capacity),
            "demand_route_lower_bound": route_lb,
            "physical_ev_share_one_trip_lb": ev_one_trip_share,
            "physical_ev_share_two_trip_lb": ev_two_trip_share,
            "headroom_ge_20pct_two_trip": ev_two_trip_share >= 0.20,
        })
    return rows


def majority_cap_bounded(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    bounded = sum(1 for row in rows if not boolish(row.get("headroom_ge_20pct_two_trip")))
    return bounded / len(rows) > 0.5


def run_synthesis(args: argparse.Namespace) -> None:
    stage0 = read_json(Path(args.stage0_dir) / "stage0_decision.json") if (Path(args.stage0_dir) / "stage0_decision.json").exists() else {}
    stage1 = read_json(Path(args.stage1_dir) / "stage1_decision.json") if (Path(args.stage1_dir) / "stage1_decision.json").exists() else {}
    stage2 = read_json(Path(args.stage2_dir) / "stage2_decision.json") if (Path(args.stage2_dir) / "stage2_decision.json").exists() else {}
    report = render_synthesis(stage0, stage1, stage2)
    path = Path(args.report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")


def select_instances(mode: str) -> list[tuple[str, str, int]]:
    if mode == "representative_big":
        return list(REPRESENTATIVE_BIG)
    if mode == "gradient01_75_200":
        rows: list[tuple[str, str, int]] = []
        for category, sizes in (("vanilla", VANILLA_MULTIDEPOT_SIZES), ("multidepot", VANILLA_MULTIDEPOT_SIZES), ("threeshift", THREESHIFT_SIZES)):
            for size in sizes:
                if size >= 75:
                    rows.append((category, f"e2-{category}-{size}c-01", size))
        return rows
    raise ValueError(mode)


def bundle_path(category: str, instance_name: str) -> Path:
    return INSTANCE_ROOT / category / instance_name


def phase0_audit(battery_kwh: float) -> dict[str, Any]:
    from setp_solver.prices import DEFAULT_PRICES

    default_probe = {
        "Q": float(DEFAULT_PRICES.Q_capacity),
        "B": float(DEFAULT_PRICES.B_battery_kwh),
        "v": float(DEFAULT_PRICES.v_speed_ms),
        "carbon": float(DEFAULT_PRICES.carbon_price),
        "python": sys.executable,
        "numpy": numpy_version(),
    }
    ok = (
        abs(default_probe["Q"] - 3650.0) <= 1e-9
        and abs(default_probe["B"] - 80.0) <= 1e-9
        and abs(default_probe["v"] - 25.0) <= 1e-9
        and abs(default_probe["carbon"] - CARBON_PRICE) <= 1e-12
        and str(Path(sys.executable)) == GOLD_PYTHON
        and default_probe["numpy"] == GOLD_NUMPY
    )
    return {"phase0_ok": ok, "default_probe": default_probe, "diagnostic_battery_kwh": float(battery_kwh)}


def classify_exception(exc: Exception) -> str:
    text = str(exc).lower()
    if "requires" in text and "b=" in text or "battery below" in text:
        return "RANGE_BATTERY_80KWH"
    if "window" in text or "due" in text or "time" in text:
        return "CHARGING_TIME_WINDOW_DETOUR"
    if "station" in text or "charging" in text:
        return "STATION_OR_DEPOT_CAPACITY"
    if "fleet" in text:
        return "FLEET_HEADROOM_EXHAUSTED"
    return "OTHER_CHECK_VIOLATION"


def classify_violation(violations: list[Any]) -> str:
    text = " ".join(f"{v.type} {v.detail}" for v in violations).lower()
    if "battery" in text or "soc" in text or "energy" in text:
        return "RANGE_BATTERY_80KWH"
    if "time" in text or "window" in text or "due" in text:
        return "CHARGING_TIME_WINDOW_DETOUR"
    if "station" in text or "charger" in text or "capacity" in text:
        return "STATION_OR_DEPOT_CAPACITY"
    if "fleet" in text:
        return "FLEET_HEADROOM_EXHAUSTED"
    return "OTHER_CHECK_VIOLATION"


def summarize_failures(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (str(row.get("instance", "")), str(row.get("failure_reason", "")))
        counts[key] = counts.get(key, 0) + 1
    return [{"instance": key[0], "failure_reason": key[1], "count": count} for key, count in sorted(counts.items())]


def dominant_failure(rows: list[dict[str, Any]]) -> str:
    failures = [str(row.get("failure_reason")) for row in rows if str(row.get("failure_reason")) != "ACCEPTED"]
    if not failures:
        return "NONE"
    return max(sorted(set(failures)), key=failures.count)


def pair_rows(rows: list[dict[str, Any]], left: str, right: str) -> list[dict[str, Any]]:
    keyed = {(row["instance"], int(row["seed"]), row["algorithm"]): row for row in rows if row.get("gate_status") == "OK"}
    pairs = []
    for instance, seed, algorithm in sorted(keyed):
        if algorithm != left:
            continue
        lrow = keyed.get((instance, seed, left))
        rrow = keyed.get((instance, seed, right))
        if not lrow or not rrow:
            continue
        lcost = as_float(lrow.get("best_cost"))
        rcost = as_float(rrow.get("best_cost"))
        pairs.append({
            "instance": instance,
            "seed": seed,
            "left_algorithm": left,
            "right_algorithm": right,
            "left_cost": lcost,
            "right_cost": rcost,
            "gap_pct_left_minus_right": pct_gap(lcost, rcost),
            "left_ev_route_share": as_float(lrow.get("ev_route_share")),
            "right_ev_route_share": as_float(rrow.get("ev_route_share")),
            "left_charging_action_count": int(as_float(lrow.get("charging_action_count"))),
            "right_charging_action_count": int(as_float(rrow.get("charging_action_count"))),
        })
    return pairs


def wilcoxon_or_sign(values: list[float]) -> dict[str, Any]:
    clean = [float(value) for value in values if math.isfinite(float(value)) and abs(float(value)) > 1e-12]
    if not clean:
        return {"method": "all_zero", "p_value_less": 1.0, "nonzero_pairs": 0}
    try:
        from scipy.stats import wilcoxon

        return {"method": "scipy_wilcoxon_less", "p_value_less": float(wilcoxon(clean, alternative="less").pvalue), "nonzero_pairs": len(clean)}
    except Exception:
        wins = sum(1 for value in clean if value < 0.0)
        n = len(clean)
        p = sum(math.comb(n, k) for k in range(wins, n + 1)) / (2**n)
        return {"method": "sign_test_less", "p_value_less": float(p), "nonzero_pairs": n}


def collection_failures(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    for row in rows:
        if str(row.get("gate_status")) != "OK":
            failures.append(row | {"failure_bucket": "status_not_ok"})
        elif int(as_float(row.get("violation_count"))) != 0:
            failures.append(row | {"failure_bucket": "nonzero_violation"})
        elif str(row.get("python")) != GOLD_PYTHON:
            failures.append(row | {"failure_bucket": "python_mismatch"})
        elif str(row.get("numpy")) != GOLD_NUMPY:
            failures.append(row | {"failure_bucket": "numpy_mismatch"})
    return failures


def carbon_best_improvements(operator_counts: dict[str, Any]) -> int:
    total = 0
    for group in ("destroy", "repair"):
        for name, counts in dict(operator_counts.get(group, {})).items():
            if "carbon" not in name:
                continue
            try:
                total += int(counts[0])
            except Exception:
                pass
    return total


def runtime_cap(size: int) -> float:
    if size <= 25:
        return 300.0
    if size <= 50:
        return 600.0
    return 900.0


def parse_seeds(text: str) -> list[int]:
    if "-" in str(text):
        start, end = str(text).split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(item.strip()) for item in str(text).split(",") if item.strip()]


def build_metadata(output_dir: Path, report_path: Path, stage: str, *, battery_kwh: float) -> dict[str, Any]:
    return {
        "schema": "setp-09y-ev-heavy-regime-probe.v1",
        "stage": stage,
        "evidence_level": PROBE_LEVEL,
        "repo_root": str(REPO_ROOT),
        "output_dir": str(output_dir),
        "report_path": str(report_path),
        "head": git_head(),
        "battery_kwh": float(battery_kwh),
        "carbon_price": CARBON_PRICE,
        "started_at_epoch": time.time(),
    }


def artifact_hashes(output_dir: Path, report_path: Path) -> dict[str, Any]:
    files = []
    for path in sorted(output_dir.glob("*.csv")) + sorted(output_dir.glob("*.json")) + [report_path]:
        if path.exists() and path.name != "artifact_hashes.json":
            files.append({"path": str(path), "sha256": sha256_file(path)})
    return {"schema": "setp-09y-artifact-hashes.v1", "files": files}


def render_stage0_report(metadata: dict[str, Any], phase0: dict[str, Any], decision: dict[str, Any], rows: list[dict[str, Any]], failures: list[dict[str, Any]]) -> str:
    lines = [
        "# 09y EV-heavy Feasibility Stage 0",
        "",
        f"Evidence level: **{PROBE_LEVEL}**. This report does not claim formal T3 dominance.",
        "",
        f"Verdict: `{decision['verdict']}`",
        "",
        "## Plain Reading",
        "",
        str(decision.get("plain", "")),
        "",
        "本阶段只做构造与 referee 复评，不做搜索；目标是判断 Goeke80 大实例 EV-heavy 是搜索没找到、经济性差，还是物理/时间窗不支持。",
        "",
        "## Phase 0",
        "",
        f"- Phase0 OK: `{phase0.get('phase0_ok')}`",
        f"- Defaults probe: `{json.dumps(phase0.get('default_probe', {}), sort_keys=True)}`",
        f"- HEAD: `{metadata.get('head')}`",
        "",
        "## Instance Summary",
        "",
        "| instance | EV share | charging_action_count | cost gap % | E_total gap % | accepted | verdict | dominant failure |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append("| {instance} | {ev:.4f} | {charge} | {cost:.4f} | {carbon:.4f} | {accepted} | {verdict} | {failure} |".format(
            instance=row.get("instance"),
            ev=as_float(row.get("ev_route_share")),
            charge=int(as_float(row.get("charging_action_count"))),
            cost=as_float(row.get("cost_gap_pct_vs_baseline")),
            carbon=as_float(row.get("E_total_gap_pct_vs_baseline")),
            accepted=int(as_float(row.get("accepted_conversions"))),
            verdict=row.get("instance_verdict"),
            failure=row.get("dominant_failure_reason"),
        ))
    lines.extend([
        "",
        "## Failure Reasons",
        "",
        "| instance | failure_reason | count |",
        "|---|---|---:|",
    ])
    for row in failures:
        lines.append(f"| {row.get('instance')} | {row.get('failure_reason')} | {row.get('count')} |")
    lines.extend(common_artifact_lines(metadata))
    return "\n".join(lines).rstrip() + "\n"


def render_stage1_report(metadata: dict[str, Any], decision: dict[str, Any], rows: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> str:
    stats = wilcoxon_or_sign([as_float(row.get("gap_pct_left_minus_right")) for row in pairs])
    lines = [
        "# 09y EV-seeded Search Stage 1",
        "",
        f"Evidence level: **{PROBE_LEVEL}**. This report does not claim formal T3 dominance.",
        "",
        f"Verdict: `{decision['verdict']}`",
        "",
        "## Plain Reading",
        "",
        str(decision.get("plain", "")),
        "",
        "## Summary",
        "",
        f"- Rows: `{decision.get('rows', len(rows))}`",
        f"- Paired rows: `{decision.get('paired_rows', len(pairs))}`",
        f"- Mean ALNS EV route share: `{decision.get('mean_alns_ev_route_share', 0)}`",
        f"- Mean ALNS charging_action_count: `{decision.get('mean_alns_charging_action_count', 0)}`",
        f"- Mean carbon best improvements: `{decision.get('mean_carbon_best_improvements', 0)}`",
        f"- Wilcoxon/sign method: `{stats['method']}`, p_less=`{stats['p_value_less']}`",
    ]
    lines.extend(common_artifact_lines(metadata))
    return "\n".join(lines).rstrip() + "\n"


def render_stage2_report(metadata: dict[str, Any], decision: dict[str, Any], headroom: list[dict[str, Any]], construction: list[dict[str, Any]], rows: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> str:
    lines = [
        "# 09y Modern Battery Regime Stage 2",
        "",
        f"Evidence level: **{PROBE_LEVEL}**. Modern battery is diagnostic override only.",
        "",
        f"Verdict: `{decision['verdict']}`",
        "",
        "## Plain Reading",
        "",
        str(decision.get("plain", "")),
        "",
        "## Headroom",
        "",
        "| instance | num_ev | route lower bound | EV share two-trip lb | ge 20% |",
        "|---|---:|---:|---:|---|",
    ]
    for row in headroom:
        lines.append(f"| {row.get('instance')} | {row.get('num_ev')} | {row.get('demand_route_lower_bound')} | {as_float(row.get('physical_ev_share_two_trip_lb')):.4f} | {row.get('headroom_ge_20pct_two_trip')} |")
    lines.extend([
        "",
        "## Construction",
        "",
        "| instance | EV share | charging_action_count | cost gap % | verdict |",
        "|---|---:|---:|---:|---|",
    ])
    for row in construction:
        lines.append(f"| {row.get('instance')} | {as_float(row.get('ev_route_share')):.4f} | {int(as_float(row.get('charging_action_count')))} | {as_float(row.get('cost_gap_pct_vs_baseline')):.4f} | {row.get('instance_verdict')} |")
    lines.extend(common_artifact_lines(metadata))
    return "\n".join(lines).rstrip() + "\n"


def render_synthesis(stage0: dict[str, Any], stage1: dict[str, Any], stage2: dict[str, Any]) -> str:
    recommendation = "vanilla ALNS=强基线非碾压者；算法创新主线=DR-ALNS；混合故事限于受约束或现代电池场景"
    if stage1.get("verdict") == "A_SEARCH_GAP_CONFIRMED":
        recommendation = "Goeke80 EV-heavy 可由暖启动救活；下一步把 EV-seeded regime 独立正式化后再做 T3。"
    elif stage2.get("verdict") == "B_MODERN_REGIME_WORKS":
        recommendation = "混合故事的家在 modern battery regime；下一步走 TeX/prices/bib/来源正式化门，再做正式 T3。"
    elif stage0.get("verdict") == "Z_EV_PHYSICALLY_UNSUPPORTED_80KWH" and stage2.get("verdict") == "HALT_COLLECTION_COST":
        recommendation = (
            "Goeke80 代表大实例转不出 EV-heavy：80kWh 下多数 CV→EV 被充电时间窗或插站约束拦住。"
            "280kWh 诊断已在 threeshift-150c 构造出非退化且更优的混合解，但算法大对比未按墙钟帽闭合，"
            "所以只能说 modern battery 场景有机制头寸，不能说 vanilla ALNS 已赢。下一步若继续 modern regime，"
            "先修 Stage 2 单任务硬超时和增量落盘，再重跑算法对比；否则算法创新主线转 DR-ALNS。"
        )
    return "\n".join([
        "# 09y EV-heavy Regime Synthesis",
        "",
        f"Evidence level: **{PROBE_LEVEL}**.",
        "",
        "## Plain Reading",
        "",
        recommendation,
        "",
        "## Verdicts",
        "",
        f"- Stage 0: `{stage0.get('verdict', 'MISSING')}`",
        f"- Stage 1: `{stage1.get('verdict', 'MISSING')}`",
        f"- Stage 2: `{stage2.get('verdict', 'MISSING')}`",
        "",
    ])


def common_artifact_lines(metadata: dict[str, Any]) -> list[str]:
    return [
        "",
        "## Artifacts",
        "",
        f"- Data dir: `{metadata.get('output_dir')}`",
        f"- Report: `{metadata.get('report_path')}`",
        f"- HEAD at run start: `{metadata.get('head')}`",
        "- Carbon price fixed at `0.05034`; protected solver semantics unchanged.",
    ]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields or ["empty"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def pct_gap(left: Any, right: Any) -> float:
    left_f = as_float(left)
    right_f = as_float(right)
    if not math.isfinite(left_f) or not math.isfinite(right_f) or abs(right_f) <= 1e-12:
        return math.inf
    return (left_f - right_f) / abs(right_f) * 100.0


def safe_mean(values: Iterable[float]) -> float:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    return statistics.fmean(clean) if clean else 0.0


def as_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return math.nan


def boolish(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def numpy_version() -> str:
    try:
        import numpy as np

        return str(np.__version__)
    except Exception:
        return "unknown"


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:
        return "unknown"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


if __name__ == "__main__":
    main()
