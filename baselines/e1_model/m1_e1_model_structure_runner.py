#!/usr/bin/env python3
"""Resumable E1 model-structure gate built on the frozen E2 method.

Mixed rows are reused from the accepted E2 matrix.  Only the 200c CV-only
counterfactual is re-optimized.  EV-only construction is audited separately:
failure to construct a feasible warm start is reported as NOT_FOUND, never as
a mathematical infeasibility proof.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "solver/src", REPO_ROOT / "models/src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from baselines.e2_alns import e2_final_closure as closure
from setp_solver.algorithms.resetp_alns.kernel.alns_core import SearchPolicy
from setp_solver.algorithms.resetp_alns.kernel.winner import WinnerKernelConfig, run_staged_carbon_aware_hybrid
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.charging import repair_route_charging
from setp_solver.search.fleet import normalize_solution_vehicle_trips
from setp_solver.solution import ChargingAction, Route, Solution


OUTPUT_DIR = REPO_ROOT / "baselines/e1_model/e1_submission_20260711"
E2_DIR = REPO_ROOT / "baselines/e2_alns/e2_submission_20260711/carbon_280"
FLAGSHIP = "L-main-threeshift-200c-01"
MIXED_INSTANCES = tuple(f"L-main-threeshift-{size}c-01" for size in (50, 100, 150, 200))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("preflight", "formal"), default="preflight")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--eval-budget", type=int, default=4000)
    parser.add_argument("--task-json", default="")
    parser.add_argument("--task-output-json", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.task_json:
        closure.write_json(Path(args.task_output_json), run_counterfactual(closure.read_json(Path(args.task_json))))
        return 0

    phase_dir = Path(args.output_dir).resolve() / args.phase
    phase_dir.mkdir(parents=True, exist_ok=True)
    budget = min(400, int(args.eval_budget)) if args.phase == "preflight" else int(args.eval_budget)
    seeds = [1] if args.phase == "preflight" else [1, 2, 3, 4, 5]
    tasks = [make_task(phase_dir, variant, seed, budget) for seed in seeds for variant in ("cv_only", "ev_only")]
    closure.write_json(
        phase_dir / "metadata.json",
        {
            "schema": "setp-e1-model-structure.v1",
            "phase": args.phase,
            "head": closure.git_head(),
            "frozen_e2_commit": "0124623e347cd2a6a5548e07e0af66e16d3b634b",
            "frozen_e2_tag": "e2-submission-20260711",
            "scenario": "280 kWh modern-distribution main scenario",
            "algorithm": "staged ALNS-LNS hybrid + carbon-aware charging schedule",
            "eval_budget": budget,
            "seeds": seeds,
            "workers": min(max(1, int(args.workers)), len(tasks)),
            "mixed_evidence_source": str(E2_DIR.relative_to(REPO_ROOT)),
            "claim_rule": "EV-only warm-start failure is NOT_FOUND, not proof of mathematical infeasibility.",
            "protected_paths": list(closure.PROTECTED_PATHS),
        },
    )
    closure.write_csv(phase_dir / "task_manifest.csv", tasks)
    counterfactual_rows = run_tasks(phase_dir, tasks, workers=min(max(1, int(args.workers)), len(tasks)))
    mixed_rows = load_frozen_mixed_rows(seeds, instances=(FLAGSHIP,) if args.phase == "preflight" else MIXED_INSTANCES)
    rows = sorted([*mixed_rows, *counterfactual_rows], key=lambda row: (str(row["instance"]), int(row["seed"]), str(row["variant"])))
    closure.write_csv(phase_dir / "raw_runs.csv", rows)
    export_solutions(phase_dir, rows)
    decision = decide(rows, args.phase, seeds, budget)
    closure.write_json(phase_dir / "decision.json", decision)
    write_report(phase_dir, decision, rows)
    closure.write_hashes(phase_dir)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision["verdict"].endswith("READY") or decision["verdict"].endswith("SUPPORTED") else 2


def make_task(phase_dir: Path, variant: str, seed: int, budget: int) -> dict[str, Any]:
    run_id = f"E1__280__{FLAGSHIP}__{variant}__seed{seed}__eval{budget}"
    return {
        "run_id": run_id,
        "variant": variant,
        "instance": FLAGSHIP,
        "seed": seed,
        "eval_budget": budget,
        "runtime_cap_seconds": 900.0,
        "row_path": str((phase_dir / "tasks" / f"{run_id}.json").relative_to(REPO_ROOT)),
    }


def run_tasks(phase_dir: Path, tasks: list[dict[str, Any]], *, workers: int) -> list[dict[str, Any]]:
    task_dir = phase_dir / "task_inputs"
    task_dir.mkdir(parents=True, exist_ok=True)
    commands: list[tuple[dict[str, Any], list[str]]] = []
    for task in tasks:
        output = REPO_ROOT / str(task["row_path"])
        if output.exists():
            continue
        task_path = task_dir / f"{task['run_id']}.json"
        closure.write_json(task_path, task)
        commands.append(
            (
                task,
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--task-json",
                    str(task_path),
                    "--task-output-json",
                    str(output),
                ],
            )
        )

    def launch(item: tuple[dict[str, Any], list[str]]) -> None:
        task, command = item
        output = REPO_ROOT / str(task["row_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, timeout=960)
        if completed.returncode != 0 or not output.exists():
            closure.write_json(
                output,
                failure_row(task, "HALT_WORKER", (completed.stderr or completed.stdout)[-2000:]),
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(launch, commands))
    return [closure.read_json(REPO_ROOT / str(task["row_path"])) for task in tasks]


def run_counterfactual(task: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    variant = str(task["variant"])
    seed = int(task["seed"])
    bundle = load_search_bundle(closure._resolve_bundle_dir("threeshift", FLAGSHIP))  # noqa: SLF001
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
    mixed = frozen_mixed_solution(FLAGSHIP, seed)
    if variant == "cv_only":
        warm, warm_detail = convert_to_cv(mixed, bundle, prices)
        policy = SearchPolicy(require_charging_signal=False, max_cv=int(bundle.instance.num_cv), max_ev=0)
    elif variant == "ev_only":
        warm, warm_detail = convert_to_ev(mixed, bundle, prices)
        policy = SearchPolicy(require_charging_signal=False, max_cv=0, max_ev=int(bundle.instance.num_ev))
        if warm is None:
            return evidence_row(
                task,
                None,
                bundle,
                prices,
                status="NOT_FOUND",
                reason=warm_detail,
                actual_evals=0,
                elapsed=time.perf_counter() - started,
            )
    else:
        return failure_row(task, "HALT_UNKNOWN_VARIANT", variant)
    try:
        result = run_staged_carbon_aware_hybrid(
            bundle.bundle_dir,
            config=WinnerKernelConfig(seed=seed, eval_budget=int(task["eval_budget"]), max_runtime_seconds=float(task["runtime_cap_seconds"])),
            initial_solution=warm,
            prices=prices,
            charging_strategy="aware",
            policy=policy,
        )
    except Exception as exc:
        return failure_row(task, "HALT_SEARCH_EXCEPTION", repr(exc))
    solution = result["best_solution"]
    forbidden = "ev" if variant == "cv_only" else "cv"
    forbidden_count = sum(route.vehicle_type.lower() == forbidden for route in solution.routes)
    violations = check_solution(solution, bundle.instance, prices)
    status = "OK" if not violations and not forbidden_count and int(result["evaluations"]) == int(task["eval_budget"]) else "HALT_CONTRACT"
    reason = warm_detail if status == "OK" else f"violations={len(violations)}; forbidden_{forbidden}_routes={forbidden_count}; evals={result['evaluations']}"
    return evidence_row(
        task,
        solution,
        bundle,
        prices,
        status=status,
        reason=reason,
        actual_evals=int(result["evaluations"]),
        elapsed=time.perf_counter() - started,
    )


def convert_to_cv(solution: Solution, bundle: Any, prices: Any) -> tuple[Solution, str]:
    node_types = {node.node_id: node.node_type.lower() for node in bundle.instance.nodes}
    routes = [
        Route(f"CVX{idx}", "cv", route.home_depot_id, [node for node in route.node_sequence if node_types.get(node) != "f"])
        for idx, route in enumerate(solution.routes, start=1)
    ]
    converted = normalize_solution_vehicle_trips(
        Solution(routes=routes, cross_site_services=solution.cross_site_services),
        bundle.instance,
        max_cv=int(bundle.instance.num_cv),
        max_ev=0,
    )
    violations = check_solution(converted, bundle.instance, prices)
    if violations:
        raise ValueError(f"CV-only conversion failed: {violations[:3]}")
    return converted, "Converted the matching frozen mixed solution to CV-only, then re-optimized under max_ev=0."


def convert_to_ev(solution: Solution, bundle: Any, prices: Any) -> tuple[Solution | None, str]:
    routes: list[Route] = []
    actions: list[ChargingAction] = []
    for idx, route in enumerate(solution.routes, start=1):
        if route.vehicle_type.lower() == "ev":
            routes.append(route)
            actions.extend(action for action in solution.charging_actions if action.vehicle_id == route.vehicle_id)
            continue
        ev_route = Route(f"EVX{idx}", "ev", route.home_depot_id, list(route.node_sequence))
        try:
            repaired, route_actions = repair_route_charging(ev_route, bundle.instance, bundle.carbon_profile, prices)
        except ValueError as exc:
            return None, f"No feasible direct all-EV conversion warm start: {exc}. This is NOT proof that the EV-only model is infeasible."
        routes.append(repaired)
        actions.extend(route_actions)
    try:
        converted = normalize_solution_vehicle_trips(
            Solution(routes=routes, charging_actions=actions, cross_site_services=solution.cross_site_services),
            bundle.instance,
            max_cv=0,
            max_ev=int(bundle.instance.num_ev),
        )
    except ValueError as exc:
        return None, f"All-EV physical-vehicle packing failed: {exc}. This is NOT a mathematical infeasibility proof."
    violations = check_solution(converted, bundle.instance, prices)
    if violations:
        return None, f"All-EV converted warm start has {len(violations)} violations. This is NOT a mathematical infeasibility proof."
    return converted, "Converted the matching frozen mixed solution to EV-only, then re-optimized under max_cv=0."


def load_frozen_mixed_rows(seeds: list[int], *, instances: tuple[str, ...]) -> list[dict[str, Any]]:
    source = closure.read_csv(E2_DIR / "raw_runs.csv")
    selected = [
        row
        for row in source
        if row["algorithm"] == "staged_hybrid_carbon_aware"
        and row["instance"] in instances
        and int(row["seed"]) in seeds
    ]
    return [mixed_evidence_row(row) for row in selected]


def mixed_evidence_row(source: dict[str, Any]) -> dict[str, Any]:
    task = {
        "run_id": f"E1_REUSE__{source['instance']}__mixed__seed{source['seed']}",
        "variant": "mixed",
        "instance": source["instance"],
        "seed": int(source["seed"]),
        "eval_budget": int(source["eval_budget"]),
    }
    bundle = load_search_bundle(closure._resolve_bundle_dir("threeshift", str(source["instance"])))  # noqa: SLF001
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
    solution = solution_from_json(json.loads(str(source["solution_json"])))
    row = evidence_row(
        task,
        solution,
        bundle,
        prices,
        status="OK",
        reason="Reused without alteration from frozen E2 evidence.",
        actual_evals=int(source["actual_evals"]),
        elapsed=float(source["elapsed_seconds"]),
    )
    row["source_run_id"] = source["run_id"]
    row["source_commit"] = source["head"]
    return row


def frozen_mixed_solution(instance: str, seed: int) -> Solution:
    source = closure.read_csv(E2_DIR / "raw_runs.csv")
    row = next(
        item
        for item in source
        if item["algorithm"] == "staged_hybrid_carbon_aware"
        and item["instance"] == instance
        and int(item["seed"]) == seed
    )
    return solution_from_json(json.loads(str(row["solution_json"])))


def solution_from_json(data: dict[str, Any]) -> Solution:
    return Solution(
        routes=[Route(**row) for row in data.get("routes", [])],
        charging_actions=[ChargingAction(**row) for row in data.get("charging_actions", [])],
        cross_site_services=list(data.get("cross_site_services", [])),
    )


def evidence_row(
    task: dict[str, Any],
    solution: Solution | None,
    bundle: Any,
    prices: Any,
    *,
    status: str,
    reason: str,
    actual_evals: int,
    elapsed: float,
) -> dict[str, Any]:
    metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices) if solution is not None else {}
    workload = workload_metrics(solution, bundle.instance) if solution is not None else {}
    solution_json = json.dumps(closure.solution_to_dict(solution), ensure_ascii=False, sort_keys=True) if solution is not None else ""
    row = {
        "run_id": task["run_id"],
        "instance": task["instance"],
        "seed": int(task["seed"]),
        "variant": task["variant"],
        "status": status,
        "reason": reason,
        "eval_budget": int(task["eval_budget"]),
        "actual_evals": actual_evals,
        "elapsed_seconds": elapsed,
        "battery_kwh": 280.0,
        "violation_count": len(check_solution(solution, bundle.instance, prices)) if solution is not None else "",
        "route_count": len(solution.routes) if solution is not None else "",
        "charging_action_count": len(solution.charging_actions) if solution is not None else "",
        "solution_signature": hashlib.sha256(solution_json.encode("utf-8")).hexdigest() if solution_json else "",
        "source_run_id": "",
        "source_commit": closure.git_head(),
        **{key: metrics.get(key, "") for key in (
            "total_cost", "cost_fix", "cost_km", "cost_fuel", "cost_elec", "cost_occ", "cost_transship", "cost_carbon",
            "E_total", "E_cv_direct", "E_ev_indirect", "n_veh_cv", "n_veh_ev", "distance_total", "distance_cv", "distance_ev",
            "fuel_liters", "electricity_kwh", "depot_charging_kwh", "station_charging_kwh",
        )},
        **workload,
        "solution_json": solution_json,
    }
    return row


def workload_metrics(solution: Solution, instance: Any) -> dict[str, Any]:
    lookup = {node.node_id: node for node in instance.nodes}
    totals = {kind: {"customers": 0, "demand": 0.0} for kind in ("cv", "ev")}
    for route in solution.routes:
        kind = route.vehicle_type.lower()
        for node_id in route.node_sequence:
            node = lookup.get(node_id)
            if node is not None and node.node_type.lower() == "c":
                totals[kind]["customers"] += 1
                totals[kind]["demand"] += float(node.demand)
    customer_total = sum(item["customers"] for item in totals.values())
    demand_total = sum(item["demand"] for item in totals.values())
    return {
        "cv_customer_count": totals["cv"]["customers"],
        "ev_customer_count": totals["ev"]["customers"],
        "ev_customer_share": totals["ev"]["customers"] / customer_total if customer_total else 0.0,
        "cv_demand": totals["cv"]["demand"],
        "ev_demand": totals["ev"]["demand"],
        "ev_demand_share": totals["ev"]["demand"] / demand_total if demand_total else 0.0,
    }


def decide(rows: list[dict[str, Any]], phase: str, seeds: list[int], budget: int) -> dict[str, Any]:
    mixed = [row for row in rows if row["variant"] == "mixed"]
    cv = [row for row in rows if row["variant"] == "cv_only"]
    ev = [row for row in rows if row["variant"] == "ev_only"]
    cv_ok = [row for row in cv if row["status"] == "OK"]
    ev_ok = [row for row in ev if row["status"] == "OK"]
    ev_not_found = [row for row in ev if row["status"] == "NOT_FOUND"]
    required_mixed = len(seeds) * (1 if phase == "preflight" else len(MIXED_INSTANCES))
    ready = (
        len(mixed) == required_mixed
        and all(row["status"] == "OK" and int(row["actual_evals"]) == int(row["eval_budget"]) for row in mixed)
        and len(cv_ok) == len(seeds)
        and all(int(row["actual_evals"]) == budget and int(row["violation_count"]) == 0 and int(row["n_veh_ev"]) == 0 for row in cv_ok)
        and len(ev_ok) + len(ev_not_found) == len(seeds)
    )
    verdict = "E1_PREFLIGHT_READY" if ready and phase == "preflight" else "E1_280_STRUCTURE_SUPPORTED" if ready else "HALT_E1_CONTRACT"
    mixed_flagship = [row for row in mixed if row["instance"] == FLAGSHIP]
    paired_gains = []
    for seed in seeds:
        left = next((row for row in mixed_flagship if int(row["seed"]) == seed), None)
        right = next((row for row in cv_ok if int(row["seed"]) == seed), None)
        if left is not None and right is not None:
            paired_gains.append(100.0 * (float(right["total_cost"]) - float(left["total_cost"])) / float(right["total_cost"]))
    component_errors = []
    for row in [*mixed, *cv_ok]:
        component_sum = sum(float(row[key]) for key in ("cost_fix", "cost_km", "cost_fuel", "cost_elec", "cost_occ", "cost_transship", "cost_carbon"))
        component_errors.append(abs(component_sum - float(row["total_cost"])))
    return {
        "schema": "setp-e1-model-structure-decision.v1",
        "verdict": verdict,
        "phase": phase,
        "mixed_rows": len(mixed),
        "cv_only_ok": len(cv_ok),
        "ev_only_ok": len(ev_ok),
        "ev_only_not_found": len(ev_not_found),
        "mixed_flagship_mean_ev_customer_share": mean(row.get("ev_customer_share") for row in mixed_flagship),
        "mixed_flagship_mean_ev_demand_share": mean(row.get("ev_demand_share") for row in mixed_flagship),
        "mixed_flagship_mean_ev_distance_share": mean(
            float(row.get("distance_ev", 0.0)) / float(row.get("distance_total", 1.0)) for row in mixed_flagship
        ),
        "mixed_flagship_mean_charging_actions": mean(row.get("charging_action_count") for row in mixed_flagship),
        "mixed_vs_cv_only_flagship_mean_gain_pct": mean(paired_gains),
        "mixed_vs_cv_only_flagship_wins_ties_losses": [
            sum(value > 1e-9 for value in paired_gains),
            sum(abs(value) <= 1e-9 for value in paired_gains),
            sum(value < -1e-9 for value in paired_gains),
        ],
        "max_cost_component_reconciliation_error": max(component_errors, default=math.nan),
        "claim_boundary": "NOT_FOUND EV-only rows mean no feasible warm start was found by the registered conversion; they do not prove global infeasibility.",
    }


def mean(values: Any) -> float:
    numbers = [float(value) for value in values if value not in (None, "") and math.isfinite(float(value))]
    return sum(numbers) / len(numbers) if numbers else math.nan


def failure_row(task: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    return {
        "run_id": task["run_id"], "instance": task["instance"], "seed": task["seed"], "variant": task["variant"],
        "status": status, "reason": reason, "eval_budget": task["eval_budget"], "actual_evals": 0, "elapsed_seconds": 0.0,
        "battery_kwh": 280.0, "violation_count": "", "route_count": "", "charging_action_count": "", "solution_json": "",
    }


def export_solutions(phase_dir: Path, rows: list[dict[str, Any]]) -> None:
    solution_dir = phase_dir / "solutions"
    solution_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        payload = str(row.get("solution_json", ""))
        if not payload:
            continue
        closure.write_json(
            solution_dir / f"{row['run_id']}.json",
            {
                "schema": "setp-e1-saved-solution.v1",
                "run_id": row["run_id"],
                "instance": row["instance"],
                "seed": int(row["seed"]),
                "variant": row["variant"],
                "source_commit": row.get("source_commit", ""),
                "solution": json.loads(payload),
            },
        )


def write_report(phase_dir: Path, decision: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    lines = [
        "# E1 model-structure gate",
        "",
        f"Verdict: `{decision['verdict']}`.",
        "",
        f"Frozen mixed evidence rows: {decision['mixed_rows']}; CV-only completed: {decision['cv_only_ok']}; EV-only completed/not-found: {decision['ev_only_ok']}/{decision['ev_only_not_found']}.",
        f"On the 200c mixed rows, mean EV shares by customers/demand/distance are {decision['mixed_flagship_mean_ev_customer_share']:.3f}/{decision['mixed_flagship_mean_ev_demand_share']:.3f}/{decision['mixed_flagship_mean_ev_distance_share']:.3f}; mean charging actions are {decision['mixed_flagship_mean_charging_actions']:.1f}.",
        f"Against CV-only on the same five seeds, mixed has mean cost gain {decision['mixed_vs_cv_only_flagship_mean_gain_pct']:.3f}% and W/T/L={decision['mixed_vs_cv_only_flagship_wins_ties_losses']}. Maximum cost-component reconciliation error is {decision['max_cost_component_reconciliation_error']:.3e}.",
        "",
        "EV-only NOT_FOUND is deliberately not labelled infeasible: direct conversion can fail because a route has no feasible depot charging window, but a different route structure may still exist.",
    ]
    (phase_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
