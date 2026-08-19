#!/usr/bin/env python3
"""E3 cumulative ablation on the frozen 280 kWh staged-hybrid contract."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import concurrent.futures
import csv
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
from setp_solver.algorithms.resetp_alns.kernel.winner import WinnerKernelConfig, run_staged_alns_lns_hybrid, run_tvci_alns, run_tvci_carbon_schedule_pair
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.profit import calculate_depot_profits, infer_customer_home_depots
from setp_solver.search.bundle import load_search_bundle
from baselines.e3_ablation._legacy_subbundle import (
    _subinstance_for_depot,
    _write_subbundle,
)
from setp_solver.search.fleet import normalize_solution_vehicle_trips
from setp_solver.search.formal_runner import _derive_carbon_profile
from setp_solver.solution import ChargingAction, CrossSiteService, Route, Solution


OUTPUT_DIR = REPO_ROOT / "baselines/e3_ablation/e3_submission_20260711"
E2_RAW = REPO_ROOT / "baselines/e2_alns/e2_submission_20260711/carbon_280/raw_runs.csv"
INSTANCE = "L-main-threeshift-200c-01"
VARIANTS = ("M0", "M1", "M2", "M3", "M4", "M5")


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
        task = closure.read_json(Path(args.task_json))
        closure.write_json(Path(args.task_output_json), run_task(task))
        return 0

    phase_dir = Path(args.output_dir).resolve() / args.phase
    phase_dir.mkdir(parents=True, exist_ok=True)
    budget = min(400, int(args.eval_budget)) if args.phase == "preflight" else int(args.eval_budget)
    seeds = [1] if args.phase == "preflight" else [1, 2, 3, 4, 5]
    source_bundle = closure._resolve_bundle_dir("threeshift", INSTANCE)  # noqa: SLF001
    derived = write_derived_bundles(source_bundle, phase_dir / "derived_bundles")
    metadata = {
        "schema": "setp-e3-cumulative-ablation.v1",
        "phase": args.phase,
        "head": closure.git_head(),
        "frozen_e2_tag": "e2-submission-20260711",
        "frozen_e2_commit": "0124623e347cd2a6a5548e07e0af66e16d3b634b",
        "algorithm": "staged ALNS-LNS hybrid + registered charging schedule",
        "scenario": "280 kWh modern-distribution main scenario",
        "instance": INSTANCE,
        "seeds": seeds,
        "eval_budget_per_variant": budget,
        "m0_budget_rule": "total budget split equally across the two independent depot subproblems",
        "variant_contract": variant_contract(),
        "protected_paths": list(closure.PROTECTED_PATHS),
    }
    closure.write_json(phase_dir / "metadata.json", metadata)

    m0_tasks = [make_task(phase_dir, derived, "M0", seed, budget) for seed in seeds]
    m0_rows = run_tasks(phase_dir, m0_tasks, workers=min(len(m0_tasks), max(1, int(args.workers))))
    cooperative_tasks = [make_task(phase_dir, derived, code, seed, budget) for seed in seeds for code in VARIANTS[1:]]
    cooperative_rows = run_tasks(phase_dir, cooperative_tasks, workers=min(len(cooperative_tasks), max(1, int(args.workers))))
    tasks = [*m0_tasks, *cooperative_tasks]
    rows = sorted([*m0_rows, *cooperative_rows], key=lambda row: (int(row["seed"]), str(row["variant"])))
    rows = enrich_full_model_profit_ratios(rows, phase_dir)
    closure.write_csv(phase_dir / "task_manifest.csv", tasks)
    closure.write_csv(phase_dir / "raw_runs.csv", rows)
    export_solutions(phase_dir, rows)
    decision = decide(rows, seeds, budget, args.phase)
    closure.write_json(phase_dir / "decision.json", decision)
    write_report(phase_dir, decision)
    closure.write_hashes(phase_dir)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision["verdict"] in {"E3_PREFLIGHT_READY", "E3_MECHANISM_SUPPORTED", "E3_PARTIAL_MECHANISM_SUPPORT"} else 2


def variant_contract() -> dict[str, Any]:
    return {
        "M0": "independent depots; zero EV grid carbon; no carbon trading; no fairness",
        "M1": "cooperative routing; zero EV grid carbon; no carbon trading; no fairness",
        "M2": "M1 plus daily-mean grid carbon accounting; naive charging",
        "M3": "M2 plus actual 48-slot grid carbon and carbon-aware charging; no carbon trading",
        "M4": "M3 plus bidirectional carbon trading with CE=0.8*E2 no-quota emissions",
        "M5": "M4 plus theta=1.0 depot-profit fairness",
    }


def write_derived_bundles(source_dir: Path, target_root: Path) -> dict[str, str]:
    source = load_search_bundle(source_dir)
    result: dict[str, str] = {}
    for mode in ("zero_gamma", "mean_gamma", "actual_gamma"):
        target = target_root / mode
        target.mkdir(parents=True, exist_ok=True)
        for name in ("instance.json", "distance_matrix.npy", "scenario_manifest.json"):
            (target / name).write_bytes((source_dir / name).read_bytes())
        profile = _derive_carbon_profile(source.carbon_profile, mode)
        fields = list(profile[0])
        with (target / "carbon_profile.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(profile)
        result[mode] = str(target.relative_to(REPO_ROOT))
    return result


def make_task(phase_dir: Path, derived: dict[str, str], variant: str, seed: int, budget: int) -> dict[str, Any]:
    mode = "zero_gamma" if variant in {"M0", "M1"} else "mean_gamma" if variant == "M2" else "actual_gamma"
    run_id = f"E3__280__{INSTANCE}__{variant}__seed{seed}__eval{budget}"
    return {
        "run_id": run_id,
        "variant": variant,
        "seed": seed,
        "eval_budget": budget,
        "runtime_cap_seconds": 900.0,
        "bundle_dir": derived[mode],
        "phase_dir": str(phase_dir.relative_to(REPO_ROOT)),
        "row_path": str((phase_dir / "tasks" / f"{run_id}.json").relative_to(REPO_ROOT)),
    }


def run_tasks(phase_dir: Path, tasks: list[dict[str, Any]], *, workers: int) -> list[dict[str, Any]]:
    input_dir = phase_dir / "task_inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    pending: list[tuple[dict[str, Any], Path, list[str]]] = []
    for task in tasks:
        output = REPO_ROOT / str(task["row_path"])
        if output.exists():
            continue
        task_path = input_dir / f"{task['run_id']}.json"
        closure.write_json(task_path, task)
        pending.append((task, output, [sys.executable, str(Path(__file__).resolve()), "--task-json", str(task_path), "--task-output-json", str(output)]))

    def launch(item: tuple[dict[str, Any], Path, list[str]]) -> None:
        task, output, command = item
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, timeout=960)
            if completed.returncode != 0 or not output.exists():
                closure.write_json(output, failure_row(task, "HALT_WORKER", (completed.stderr or completed.stdout)[-2000:]))
        except subprocess.TimeoutExpired as exc:
            closure.write_json(output, failure_row(task, "HALT_TIMEOUT", str(exc)))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(launch, pending))
    return [closure.read_json(REPO_ROOT / str(task["row_path"])) for task in tasks]


def run_task(task: dict[str, Any]) -> dict[str, Any]:
    return run_m0(task) if task["variant"] == "M0" else run_cooperative(task)


def run_m0(task: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    bundle_dir = REPO_ROOT / str(task["bundle_dir"])
    bundle = load_search_bundle(bundle_dir)
    owners = infer_customer_home_depots(bundle.instance)
    depots = sorted(node.node_id for node in bundle.instance.nodes if node.node_type.lower() == "d")
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0, carbon_price=0.0)
    per_budget = int(task["eval_budget"]) // len(depots)
    routes: list[Route] = []
    actions: list[ChargingAction] = []
    actual_evals = 0
    for depot_index, depot_id in enumerate(depots):
        subdir = REPO_ROOT / str(task["phase_dir"]) / "independent_subbundles" / f"seed{task['seed']}" / depot_id
        subinstance = _subinstance_for_depot(bundle.instance, depot_id, owners)
        _write_subbundle(subdir, subinstance, bundle_dir, depot_id)
        budget = per_budget if depot_index < len(depots) - 1 else int(task["eval_budget"]) - actual_evals
        result = run_staged_alns_lns_hybrid(
            subdir,
            config=WinnerKernelConfig(seed=int(task["seed"]), eval_budget=budget, max_runtime_seconds=float(task["runtime_cap_seconds"]) / len(depots)),
            prices=prices,
            carbon_weight=0.0,
        )
        if not result["feasible"] or int(result["evaluations"]) != budget:
            return failure_row(task, "HALT_M0_DEPOT", f"{depot_id}: feasible={result['feasible']}; evals={result['evaluations']}/{budget}")
        actual_evals += int(result["evaluations"])
        solution = result["best_solution"]
        id_map: dict[str, str] = {}
        for route in solution.routes:
            new_id = f"{depot_id}_{route.vehicle_id}"
            id_map[route.vehicle_id] = new_id
            routes.append(replace(route, vehicle_id=new_id))
        actions.extend(replace(action, vehicle_id=id_map.get(action.vehicle_id, f"{depot_id}_{action.vehicle_id}")) for action in solution.charging_actions)
    try:
        solution = normalize_solution_vehicle_trips(
            Solution(routes=routes, charging_actions=actions),
            bundle.instance,
            max_cv=int(bundle.instance.num_cv),
            max_ev=int(bundle.instance.num_ev),
        )
    except ValueError as exc:
        return failure_row(task, "HALT_M0_PACKING", repr(exc))
    return build_row(task, solution, bundle, prices, quota=0.0, actual_evals=actual_evals, started=started, fairness_enabled=False, independent_profit=None)


def run_cooperative(task: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    variant = str(task["variant"])
    bundle = load_search_bundle(REPO_ROOT / str(task["bundle_dir"]))
    m0_task = make_task(REPO_ROOT / str(task["phase_dir"]), derived_for_phase(task), "M0", int(task["seed"]), int(task["eval_budget"]))
    m0_row = closure.read_json(REPO_ROOT / str(m0_task["row_path"]))
    if m0_row.get("status") != "OK":
        return failure_row(task, "HALT_M0_DEPENDENCY", str(m0_row.get("reason", "")))
    initial = solution_from_dict(json.loads(str(m0_row["solution_json"])))
    owners = infer_customer_home_depots(bundle.instance)
    quota = 0.0 if variant in {"M1", "M2", "M3"} else e2_quota(int(task["seed"]))
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0, carbon_price=0.0 if variant in {"M1", "M2", "M3"} else DEFAULT_PRICES.carbon_price)
    fairness_enabled = variant == "M5"
    independent_profit = independent_profit_for_solution(initial, bundle, prices, owners, quota) if fairness_enabled else None
    strategy = "naive" if variant in {"M1", "M2"} else "aware"
    try:
        runner = run_tvci_carbon_schedule_pair if variant in {"M3", "M4", "M5"} else run_tvci_alns
        runner_kwargs = {
            "config": WinnerKernelConfig(seed=int(task["seed"]), eval_budget=int(task["eval_budget"]), max_runtime_seconds=float(task["runtime_cap_seconds"])),
            "initial_solution": initial,
            "prices": prices,
            "carbon_weight": 1.0,
            "carbon_quota_kg": quota,
            "fairness_enabled": fairness_enabled,
            "independent_profit": independent_profit,
            "fairness_theta": 1.0 if fairness_enabled else None,
            "customer_home_depot": owners,
        }
        if variant in {"M1", "M2"}:
            runner_kwargs["charging_strategy"] = strategy
        result = runner(
            bundle.bundle_dir,
            **runner_kwargs,
        )
    except Exception as exc:
        return failure_row(task, "HALT_SEARCH_EXCEPTION", repr(exc))
    if not result["feasible"] or int(result["evaluations"]) != int(task["eval_budget"]):
        return failure_row(task, "HALT_SEARCH_CONTRACT", f"feasible={result['feasible']}; evals={result['evaluations']}/{task['eval_budget']}; violations={result['violation_count']}")
    naive_metrics = None
    naive_result = result.get("charging_ablation_result")
    if isinstance(naive_result, dict) and naive_result.get("best_solution") is not None:
        naive_metrics = evaluate(naive_result["best_solution"], bundle.instance, bundle.carbon_profile, prices, carbon_quota_kg=quota)
    return build_row(
        task,
        result["best_solution"],
        bundle,
        prices,
        quota=quota,
        actual_evals=int(result["evaluations"]),
        started=started,
        fairness_enabled=fairness_enabled,
        independent_profit=independent_profit,
        naive_metrics=naive_metrics,
        charging_actions_moved=int(result.get("charging_actions_moved_from_search_output", 0)),
    )


def derived_for_phase(task: dict[str, Any]) -> dict[str, str]:
    root = REPO_ROOT / str(task["phase_dir"]) / "derived_bundles"
    return {mode: str((root / mode).relative_to(REPO_ROOT)) for mode in ("zero_gamma", "mean_gamma", "actual_gamma")}


def build_row(
    task: dict[str, Any],
    solution: Solution,
    bundle: Any,
    prices: Any,
    *,
    quota: float,
    actual_evals: int,
    started: float,
    fairness_enabled: bool,
    independent_profit: dict[str, float] | None,
    naive_metrics: dict[str, Any] | None = None,
    charging_actions_moved: int = 0,
) -> dict[str, Any]:
    owners = infer_customer_home_depots(bundle.instance)
    solution = annotate_cross_site(solution, bundle.instance, owners) if task["variant"] != "M0" else replace(solution, cross_site_services=[])
    breakdowns = calculate_depot_profits(solution, bundle.instance, bundle.carbon_profile, prices, customer_home_depot=owners, carbon_quota_kg=quota)
    ratios = {
        depot_id: breakdowns[depot_id].profit / baseline
        for depot_id, baseline in (independent_profit or {}).items()
        if abs(baseline) > 1e-12
    }
    metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices, carbon_quota_kg=quota)
    violations = check_solution(solution, bundle.instance, prices)
    solution_json = json.dumps(solution_to_dict(solution), ensure_ascii=False, sort_keys=True)
    component_sum = sum(float(metrics[key]) for key in ("cost_fix", "cost_km", "cost_fuel", "cost_elec", "cost_occ", "cost_transship", "cost_carbon"))
    return {
        "run_id": task["run_id"], "instance": INSTANCE, "seed": int(task["seed"]), "variant": task["variant"],
        "status": "OK" if not violations and actual_evals == int(task["eval_budget"]) and (not fairness_enabled or min(ratios.values(), default=0.0) >= 1.0 - 1e-9) else "HALT_CONTRACT",
        "reason": "", "eval_budget": int(task["eval_budget"]), "actual_evals": actual_evals,
        "elapsed_seconds": time.perf_counter() - started, "battery_kwh": 280.0, "carbon_quota_kg": quota,
        "violation_count": len(violations), "route_count": len(solution.routes),
        "cv_route_count": sum(route.vehicle_type.lower() == "cv" for route in solution.routes),
        "ev_route_count": sum(route.vehicle_type.lower() == "ev" for route in solution.routes),
        "charging_action_count": len(solution.charging_actions), "cross_site_customer_count": len(solution.cross_site_services),
        "min_profit_ratio": min(ratios.values(), default=""),
        "naive_same_route_E_ev_indirect": "" if naive_metrics is None else naive_metrics["E_ev_indirect"],
        "naive_same_route_electricity_kwh": "" if naive_metrics is None else naive_metrics["electricity_kwh"],
        "charging_actions_moved": charging_actions_moved,
        "route_structure_signature": route_signature(solution),
        "cost_component_error": abs(component_sum - float(metrics["total_cost"])),
        **{key: metrics[key] for key in ("total_cost", "cost_fix", "cost_km", "cost_fuel", "cost_elec", "cost_occ", "cost_transship", "cost_carbon", "E_total", "E_cv_direct", "E_ev_indirect", "electricity_kwh", "distance_total")},
        "solution_json": solution_json, "head": closure.git_head(),
    }


def annotate_cross_site(solution: Solution, instance: Any, owners: dict[str, str]) -> Solution:
    lookup = {node.node_id: node for node in instance.nodes}
    services = [
        CrossSiteService(customer_id=node_id, served_by_depot_id=route.home_depot_id)
        for route in solution.routes
        for node_id in route.node_sequence
        if node_id in lookup and lookup[node_id].node_type.lower() == "c" and owners.get(node_id) != route.home_depot_id
    ]
    return replace(solution, cross_site_services=services)


def independent_profit_for_solution(solution: Solution, bundle: Any, prices: Any, owners: dict[str, str], quota: float) -> dict[str, float]:
    rows = calculate_depot_profits(solution, bundle.instance, bundle.carbon_profile, prices, customer_home_depot=owners, carbon_quota_kg=quota)
    return {depot_id: float(row.profit) for depot_id, row in rows.items()}


def enrich_full_model_profit_ratios(rows: list[dict[str, Any]], phase_dir: Path) -> list[dict[str, Any]]:
    """Recompute M4/M5 ratios against the same seed-specific M0 reference."""

    bundle = load_search_bundle(phase_dir / "derived_bundles" / "actual_gamma")
    owners = infer_customer_home_depots(bundle.instance)
    prices = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
    by_key = {(int(row["seed"]), str(row["variant"])): row for row in rows}
    for seed in sorted({int(row["seed"]) for row in rows}):
        m0_row = by_key.get((seed, "M0"))
        if not m0_row or not m0_row.get("solution_json"):
            continue
        m0 = solution_from_dict(json.loads(str(m0_row["solution_json"])))
        quota = e2_quota(seed)
        baseline = independent_profit_for_solution(m0, bundle, prices, owners, quota)
        for variant in ("M4", "M5"):
            row = by_key.get((seed, variant))
            if not row or not row.get("solution_json"):
                continue
            solution = solution_from_dict(json.loads(str(row["solution_json"])))
            profits = independent_profit_for_solution(solution, bundle, prices, owners, quota)
            ratios = {depot_id: profits[depot_id] / value for depot_id, value in baseline.items() if abs(value) > 1e-12}
            row["min_profit_ratio"] = min(ratios.values(), default="")
            row["profit_ratios_json"] = json.dumps(ratios, ensure_ascii=False, sort_keys=True)
    return rows


def e2_quota(seed: int) -> float:
    rows = closure.read_csv(E2_RAW)
    row = next(item for item in rows if item["instance"] == INSTANCE and item["algorithm"] == "staged_hybrid_carbon_aware" and int(item["seed"]) == seed)
    return 0.8 * float(row["E_total"])


def route_signature(solution: Solution) -> str:
    payload = sorted((route.vehicle_type.lower(), route.home_depot_id, tuple(route.node_sequence)) for route in solution.routes)
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()


def solution_to_dict(solution: Solution) -> dict[str, Any]:
    return {
        "routes": [asdict(route) for route in solution.routes],
        "charging_actions": [asdict(action) for action in solution.charging_actions],
        "cross_site_services": [asdict(service) for service in solution.cross_site_services],
    }


def solution_from_dict(data: dict[str, Any]) -> Solution:
    return Solution(
        routes=[Route(**row) for row in data.get("routes", [])],
        charging_actions=[ChargingAction(**row) for row in data.get("charging_actions", [])],
        cross_site_services=[CrossSiteService(**row) for row in data.get("cross_site_services", [])],
    )


def failure_row(task: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    return {
        "run_id": task["run_id"], "instance": INSTANCE, "seed": int(task["seed"]), "variant": task["variant"],
        "status": status, "reason": reason, "eval_budget": int(task["eval_budget"]), "actual_evals": 0,
        "elapsed_seconds": 0.0, "battery_kwh": 280.0, "violation_count": "", "solution_json": "", "head": closure.git_head(),
    }


def decide(rows: list[dict[str, Any]], seeds: list[int], budget: int, phase: str) -> dict[str, Any]:
    expected = len(seeds) * len(VARIANTS)
    ok = [row for row in rows if row.get("status") == "OK"]
    contract = (
        len(rows) == expected
        and len(ok) == expected
        and all(int(row["actual_evals"]) == budget and int(row["violation_count"]) == 0 for row in ok)
        and all(float(row["cost_component_error"]) <= 1e-7 for row in ok)
    )
    by_key = {(int(row["seed"]), str(row["variant"])): row for row in rows}
    cooperation_signal = sum(int(by_key[(seed, "M1")].get("cross_site_customer_count", 0)) > 0 for seed in seeds if by_key.get((seed, "M1"), {}).get("status") == "OK")
    carbon_signal = sum(
        float(by_key[(seed, "M3")]["E_ev_indirect"]) < float(by_key[(seed, "M3")]["naive_same_route_E_ev_indirect"]) - 1e-9
        for seed in seeds
        if by_key.get((seed, "M3"), {}).get("status") == "OK" and by_key[(seed, "M3")].get("naive_same_route_E_ev_indirect") not in (None, "")
    )
    fairness_signal = sum(float(by_key[(seed, "M5")]["min_profit_ratio"]) >= 1.0 - 1e-9 for seed in seeds if by_key.get((seed, "M5"), {}).get("status") == "OK")
    fairness_binding = sum(
        float(by_key[(seed, "M4")]["min_profit_ratio"]) < 1.0 - 1e-9
        and float(by_key[(seed, "M5")]["min_profit_ratio"]) >= 1.0 - 1e-9
        for seed in seeds
        if by_key.get((seed, "M4"), {}).get("status") == "OK" and by_key.get((seed, "M5"), {}).get("status") == "OK"
    )
    if not contract:
        verdict = "HALT_E3_CONTRACT"
    elif phase == "preflight":
        verdict = "E3_PREFLIGHT_READY"
    elif cooperation_signal >= math.ceil(len(seeds) / 2) and carbon_signal == len(seeds) and fairness_binding > 0 and fairness_signal == len(seeds):
        verdict = "E3_MECHANISM_SUPPORTED"
    else:
        verdict = "E3_PARTIAL_MECHANISM_SUPPORT"
    return {
        "schema": "setp-e3-cumulative-ablation-decision.v1", "verdict": verdict, "phase": phase,
        "expected_rows": expected, "ok_rows": len(ok), "all_eval_closed": contract,
        "cooperation_signal_seeds": cooperation_signal, "time_varying_carbon_reduction_seeds": carbon_signal,
        "fairness_feasible_seeds": fairness_signal,
        "fairness_binding_seeds": fairness_binding,
        "claim_boundary": "M4 quota is a linear accounting constant; quota changes alone are not claimed to alter routes. M0 uses the same total evaluation budget split across depots. Fairness feasibility is not counted as a binding effect when the corresponding M4 solution already satisfies theta=1.0.",
    }


def export_solutions(phase_dir: Path, rows: list[dict[str, Any]]) -> None:
    out = phase_dir / "solutions"
    out.mkdir(parents=True, exist_ok=True)
    for row in rows:
        if row.get("solution_json"):
            closure.write_json(out / f"{row['run_id']}.json", {"schema": "setp-e3-solution.v1", "run_id": row["run_id"], "solution": json.loads(row["solution_json"])})


def write_report(phase_dir: Path, decision: dict[str, Any]) -> None:
    lines = [
        "# E3 cumulative ablation gate", "", f"Verdict: `{decision['verdict']}`.", "",
        f"Rows OK: {decision['ok_rows']}/{decision['expected_rows']}; cooperation signal seeds: {decision['cooperation_signal_seeds']}; time-varying carbon reduction seeds: {decision['time_varying_carbon_reduction_seeds']}; fairness-feasible/binding seeds: {decision['fairness_feasible_seeds']}/{decision['fairness_binding_seeds']}.",
        "", decision["claim_boundary"],
    ]
    (phase_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
