#!/usr/bin/env python3
"""Bounded item-4 gate for the isolated refined carbon operators.

The two arms use the same proportional 10/80/10 staged search, seed, start,
budget, evaluator, and 280 kWh diagnostic scenario.  The only arm difference
is whether the refined charging reconstruction uses the time-varying carbon
signal (weight 1) or earliest-feasible timing (weight 0).
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
from typing import Any

from setp_solver.algorithms.resetp_alns.kernel.winner import WinnerKernelConfig, run_staged_chain_alns
from setp_solver.algorithms.resetp_alns.operators.strong_bridge import solution_signature_hash
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution


INSTANCES = ("L-main-threeshift-25c-01", "L-main-threeshift-50c-01")
ARMS = (("earliest_feasible", 0.0), ("carbon_aware", 1.0))
BATTERY_KWH = 280.0
CARBON_PRICE = 0.05034


def _git_commit(repo_root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True).strip()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _stable_hash(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _route_signature(solution: Any) -> str:
    return _stable_hash(
        [
            {
                "vehicle_id": route.vehicle_id,
                "vehicle_type": route.vehicle_type,
                "home_depot_id": route.home_depot_id,
                "node_sequence": route.node_sequence,
            }
            for route in solution.routes
        ]
    )


def _charging_signature(solution: Any) -> str:
    return _stable_hash(
        sorted(
            (
                action.vehicle_id,
                action.station_id,
                round(float(action.energy_kwh), 9),
                round(float(action.occupancy_minutes), 9),
                round(float(action.charge_start_second), 6),
            )
            for action in solution.charging_actions
        )
    )


def _task(repo_root: str, output_dir: str, instance_name: str, seed: int, arm: str, weight: float, eval_budget: int) -> dict[str, Any]:
    root = Path(repo_root)
    bundle_dir = root / "models/data_bundle/generated_instances/L-main" / instance_name
    bundle = load_search_bundle(bundle_dir)
    prices = replace(DEFAULT_PRICES, B_battery_kwh=BATTERY_KWH, carbon_price=CARBON_PRICE)
    initial = make_shared_initial_solution(bundle, prices=prices)
    config = WinnerKernelConfig(
        seed=int(seed),
        eval_budget=int(eval_budget),
        max_runtime_seconds=300.0,
        refined_carbon_operators=True,
        refined_carbon_weight=float(weight),
    )
    started = time.perf_counter()
    run = run_staged_chain_alns(
        initial,
        bundle.instance,
        bundle.carbon_profile,
        config=config,
        prices=prices,
        carbon_weight=1.0,
        stage_budget_mode="proportional",
    )
    elapsed = time.perf_counter() - started
    violations = check_solution(run.best_solution, bundle.instance, prices)
    breakdown = evaluate(run.best_solution, bundle.instance, bundle.carbon_profile, prices)
    solution_payload = {
        "routes": [asdict(route) for route in run.best_solution.routes],
        "charging_actions": [asdict(action) for action in run.best_solution.charging_actions],
        "cross_site_services": [asdict(item) for item in run.best_solution.cross_site_services],
    }
    filename = f"{instance_name}__seed{seed}__{arm}.json"
    solution_path = Path(output_dir) / "solutions" / filename
    _write_json(solution_path, solution_payload)
    customer_nodes = {node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "c"}
    served = [node_id for route in run.best_solution.routes for node_id in route.node_sequence if node_id in customer_nodes]
    row = {
        "instance": instance_name,
        "seed": int(seed),
        "arm": arm,
        "refined_carbon_weight": float(weight),
        "eval_budget": int(eval_budget),
        "actual_evals": int(run.evaluations),
        "candidate_scores": int(run.candidate_scores),
        "elapsed_seconds": float(elapsed),
        "status": "OK" if not violations and int(run.evaluations) == int(eval_budget) else "HALT",
        "violation_count": len(violations),
        "total_cost": float(breakdown["total_cost"]),
        "E_cv_direct": float(breakdown["E_cv_direct"]),
        "E_ev_indirect": float(breakdown["E_ev_indirect"]),
        "E_total": float(breakdown["E_total"]),
        "electricity_kwh": float(breakdown["electricity_kwh"]),
        "depot_charging_kwh": float(breakdown["depot_charging_kwh"]),
        "station_charging_kwh": float(breakdown["station_charging_kwh"]),
        "route_count": len(run.best_solution.routes),
        "ev_route_count": sum(route.vehicle_type.lower() == "ev" for route in run.best_solution.routes),
        "cv_route_count": sum(route.vehicle_type.lower() == "cv" for route in run.best_solution.routes),
        "charging_action_count": len(run.best_solution.charging_actions),
        "served_customer_count": len(served),
        "unique_served_customer_count": len(set(served)),
        "expected_customer_count": len(customer_nodes),
        "solution_hash": solution_signature_hash(run.best_solution),
        "route_signature": _route_signature(run.best_solution),
        "charging_signature": _charging_signature(run.best_solution),
        "solution_path": str(solution_path.relative_to(root)),
        "phase_budgets": json.dumps(run.operator_counts.get("staged_chain", {}).get("budgets", [])),
        "operator_counts": json.dumps(run.operator_counts, ensure_ascii=False, sort_keys=True),
    }
    task_row = Path(output_dir) / "tasks" / f"{instance_name}__seed{seed}__{arm}.json"
    _write_json(task_row, row)
    return row


def _paired_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = {(row["instance"], int(row["seed"]), row["arm"]): row for row in rows}
    paired: list[dict[str, Any]] = []
    for instance in INSTANCES:
        seeds = sorted({int(row["seed"]) for row in rows if row["instance"] == instance})
        for seed in seeds:
            naive = indexed[(instance, seed, "earliest_feasible")]
            aware = indexed[(instance, seed, "carbon_aware")]
            charging_sample = int(naive["charging_action_count"]) > 0 or int(aware["charging_action_count"]) > 0
            paired.append(
                {
                    "instance": instance,
                    "seed": seed,
                    "charging_sample": charging_sample,
                    "route_changed": naive["route_signature"] != aware["route_signature"],
                    "charging_changed": naive["charging_signature"] != aware["charging_signature"],
                    "naive_total_cost": naive["total_cost"],
                    "aware_total_cost": aware["total_cost"],
                    "cost_delta_aware_minus_naive": float(aware["total_cost"]) - float(naive["total_cost"]),
                    "naive_E_ev_indirect": naive["E_ev_indirect"],
                    "aware_E_ev_indirect": aware["E_ev_indirect"],
                    "ev_carbon_delta_aware_minus_naive": float(aware["E_ev_indirect"]) - float(naive["E_ev_indirect"]),
                    "naive_electricity_kwh": naive["electricity_kwh"],
                    "aware_electricity_kwh": aware["electricity_kwh"],
                    "electricity_delta": float(aware["electricity_kwh"]) - float(naive["electricity_kwh"]),
                    "naive_elapsed_seconds": naive["elapsed_seconds"],
                    "aware_elapsed_seconds": aware["elapsed_seconds"],
                    "same_customer_coverage": (
                        naive["unique_served_customer_count"] == aware["unique_served_customer_count"] == naive["expected_customer_count"]
                    ),
                }
            )
    return paired


def _decision(rows: list[dict[str, Any]], paired: list[dict[str, Any]], eval_budget: int) -> dict[str, Any]:
    complete = len(rows) == len(INSTANCES) * 3 * len(ARMS)
    clean = complete and all(
        row["status"] == "OK"
        and int(row["actual_evals"]) == int(eval_budget)
        and int(row["violation_count"]) == 0
        and int(row["unique_served_customer_count"]) == int(row["expected_customer_count"])
        for row in rows
    )
    charging_pairs = [row for row in paired if row["charging_sample"]]
    changed_pairs = [row for row in charging_pairs if row["charging_changed"] or row["route_changed"]]
    carbon_delta = sum(float(row["ev_carbon_delta_aware_minus_naive"]) for row in charging_pairs)
    majority_changed = bool(charging_pairs) and len(changed_pairs) >= math.ceil(len(charging_pairs) / 2)
    carbon_lower = bool(charging_pairs) and carbon_delta < -1e-9
    same_coverage = all(bool(row["same_customer_coverage"]) for row in paired)
    if not clean or not same_coverage:
        verdict = "HALT_REFINED_CARBON_SHORT_GATE_INVALID"
    elif majority_changed and carbon_lower:
        verdict = "REFINED_CARBON_SHORT_GATE_SUPPORTED"
    else:
        verdict = "REFINED_CARBON_MECHANISM_ONLY"
    return {
        "verdict": verdict,
        "expected_runs": len(INSTANCES) * 3 * len(ARMS),
        "completed_runs": len(rows),
        "all_full_budget_zero_violation": clean,
        "same_customer_coverage": same_coverage,
        "charging_pair_count": len(charging_pairs),
        "changed_charging_or_route_pair_count": len(changed_pairs),
        "majority_changed": majority_changed,
        "summed_ev_indirect_delta_aware_minus_naive_kg": carbon_delta,
        "ev_indirect_carbon_lower": carbon_lower,
        "summed_cost_delta_aware_minus_naive": sum(float(row["cost_delta_aware_minus_naive"]) for row in paired),
        "summed_electricity_delta_kwh": sum(float(row["electricity_delta"]) for row in paired),
        "formal_4000_authorized": False,
        "boundary": "This is a 25c/50c, seeds1-3, 400-evaluation mechanism gate under the 280 kWh diagnostic scenario.",
    }


def _report(decision: dict[str, Any], paired: list[dict[str, Any]]) -> str:
    return "\n".join(
        [
            "# E2 item 4 refined carbon short gate",
            "",
            f"Verdict: `{decision['verdict']}`.",
            "",
            f"Runs: {decision['completed_runs']}/{decision['expected_runs']}; full budget and zero violation: {decision['all_full_budget_zero_violation']}.",
            f"Charging pairs: {decision['charging_pair_count']}; changed route or charging schedule: {decision['changed_charging_or_route_pair_count']}.",
            f"Summed EV indirect-emission delta (aware minus earliest): {decision['summed_ev_indirect_delta_aware_minus_naive_kg']:.6f} kg.",
            f"Summed cost delta (aware minus earliest): {decision['summed_cost_delta_aware_minus_naive']:.6f}.",
            f"Summed electricity delta: {decision['summed_electricity_delta_kwh']:.6f} kWh.",
            "",
            "This gate does not authorize the 4000-evaluation formal ablation. It only decides whether the refined mechanism produces traceable, feasible decisions on real small instances.",
            "",
            "## Pair details",
            "",
            *[
                f"- {row['instance']} seed{row['seed']}: charging={row['charging_sample']}, changed={row['charging_changed'] or row['route_changed']}, EV carbon delta={float(row['ev_carbon_delta_aware_minus_naive']):.6f} kg, cost delta={float(row['cost_delta_aware_minus_naive']):.6f}."
                for row in paired
            ],
            "",
        ]
    )


def _artifact_hashes(output_dir: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file() or path.name == "artifact_hashes.json":
            continue
        result[str(path.relative_to(output_dir))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--eval-budget", type=int, default=400)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if not (1 <= int(args.eval_budget) <= 400):
        raise SystemExit("eval budget must be between 1 and 400 for this short gate")
    repo_root = args.repo_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    execution_commit = _git_commit(repo_root)
    metadata = {
        "schema_version": "resetp.e2.refined_carbon_short_gate.v1",
        "execution_commit": execution_commit,
        "instances": list(INSTANCES),
        "seeds": [1, 2, 3],
        "arms": {name: weight for name, weight in ARMS},
        "eval_budget": int(args.eval_budget),
        "workers": int(args.workers),
        "battery_kwh": BATTERY_KWH,
        "carbon_price": CARBON_PRICE,
        "stage_budget_mode": "proportional_10_80_10",
        "frozen_surfaces_unchanged": ["cost.py", "check.py", "search/evaluation.py", "prices.py", "L-main v3"],
    }
    _write_json(output_dir / "metadata.json", metadata)
    tasks = [
        (str(repo_root), str(output_dir), instance, seed, arm, weight, int(args.eval_budget))
        for instance in INSTANCES
        for seed in (1, 2, 3)
        for arm, weight in ARMS
    ]
    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=max(1, int(args.workers))) as pool:
        futures = [pool.submit(_task, *task) for task in tasks]
        for future in as_completed(futures):
            rows.append(future.result())
    rows.sort(key=lambda row: (row["instance"], int(row["seed"]), row["arm"]))
    paired = _paired_rows(rows)
    decision = _decision(rows, paired, int(args.eval_budget))
    _write_csv(output_dir / "raw_runs.csv", rows)
    _write_csv(output_dir / "paired_comparisons.csv", paired)
    _write_json(output_dir / "decision.json", decision)
    (output_dir / "report.md").write_text(_report(decision, paired), encoding="utf-8")
    _write_json(output_dir / "artifact_hashes.json", _artifact_hashes(output_dir))
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
