"""Diagnostic-only A13 LNS policy-kernel parity probe."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import os
import shutil
import sys
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO_ROOT / "solver/src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))

from baselines.e2_alns import e2_final_closure as fc
from baselines.e2_alns import selector_sprint_probe as sprint
from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.search import lns_policy_kernel
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution, solution_signature_hash
from setp_solver.search.metaheuristic_baselines import run_metaheuristic_baseline

OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/lns_policy_kernel_probe_20260708"
HARD_SUBSET_PATH = REPO_ROOT / "baselines/e2_alns/route_compression_probe_20260705/hard_subset_instances.csv"
REACHABILITY_DECISION = REPO_ROOT / "baselines/e2_alns/route_packing_reachability_audit_20260708/decision.json"

RUNTIME_CAP_SECONDS = {4000: 900.0, 8000: 1800.0, 16000: 3600.0}

LNS_NO_COMMON_FLIP = "LNS_NO_COMMON_FLIP"
A13_NO_COMMON_FLIP = "A13_NO_COMMON_FLIP"
LNS_FORMAL_COMMON_FLIP = "LNS_FORMAL_COMMON_FLIP"
A13_COMMON_FLIP = "A13_COMMON_FLIP"

PROFILES_BY_GROUP = {
    "POLICY_PARITY_NO_COMMON_FLIP": (LNS_NO_COMMON_FLIP, A13_NO_COMMON_FLIP),
    "FORMAL_PARITY_COMMON_FLIP": (LNS_FORMAL_COMMON_FLIP, A13_COMMON_FLIP),
}
GROUP_ORDER = ("POLICY_PARITY_NO_COMMON_FLIP", "FORMAL_PARITY_COMMON_FLIP")

COMMON_FLIP_BY_PROFILE = {
    LNS_NO_COMMON_FLIP: False,
    A13_NO_COMMON_FLIP: False,
    LNS_FORMAL_COMMON_FLIP: True,
    A13_COMMON_FLIP: True,
}
ALGORITHM_BY_PROFILE = {
    LNS_NO_COMMON_FLIP: "LNS",
    A13_NO_COMMON_FLIP: "A13_LNS_POLICY_KERNEL",
    LNS_FORMAL_COMMON_FLIP: "LNS",
    A13_COMMON_FLIP: "A13_LNS_POLICY_KERNEL",
}

GATE_THRESHOLD_GAP = 0.002
GATE_THRESHOLD_ROUTE = 0.10
GATE_THRESHOLD_FIXED = 8.0
GATE_THRESHOLD_PATH = 0.05


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = fc.repo_path(Path(args.output_dir))
    if output_dir.exists() and args.force:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    budgets = sprint.parse_ints(args.budgets)
    seeds = sprint.parse_ints(args.seeds)
    hard_subset = load_hard_subset()
    if int(args.limit_instances) > 0:
        hard_subset = hard_subset[: int(args.limit_instances)]

    metadata = build_metadata(args, budgets, seeds, hard_subset)
    issues = preflight_issues(hard_subset)
    protected = sprint.protected_diff()
    if issues:
        decision = build_decision(metadata, [], [], {}, issues=issues, expected_rows=0)
        write_outputs(output_dir, metadata, [], [], [], decision)
        return 2

    fc.write_json(output_dir / "metadata.json", metadata)

    all_raw_rows: list[dict[str, Any]] = []
    all_path_rows: list[dict[str, Any]] = []
    all_gate_rows: list[dict[str, Any]] = []
    expected_rows = 0
    group_results: dict[str, list[dict[str, Any]]] = {name: [] for name in PROFILES_BY_GROUP.keys()}
    halt = False

    for budget in budgets:
        if halt:
            break
        budget = int(budget)
        budget_raw_rows: list[dict[str, Any]] = []
        budget_path_rows: list[dict[str, Any]] = []

        for group_name in GROUP_ORDER:
            lns_profile, a13_profile = PROFILES_BY_GROUP[group_name]
            tasks = build_stage_tasks(output_dir, hard_subset, seeds=seeds, budget=budget, profiles=(lns_profile, a13_profile))
            expected_rows += len(tasks)

            rows = collect_existing_rows(output_dir, tasks)
            if not args.skip_runs:
                rows = run_tasks(output_dir, tasks, workers=int(args.workers), force=bool(args.force), logs=output_dir / "logs/full_run.log")
                for row in rows:
                    fc.write_json(task_row_path(output_dir, str(row.get("run_id", ""))), row)

            raw_rows = [dict(row) for row in raw_run_rows(rows)]
            path_rows = path_distribution_rows(rows, budget=budget)
            budget_raw_rows.extend(raw_rows)
            budget_path_rows.extend(path_rows)

            gate = group_gate_row_for_budget(
                raw_rows=raw_rows,
                path_rows=path_rows,
                budget=budget,
                lns_profile=lns_profile,
                a13_profile=a13_profile,
                protected=protected,
            )
            all_gate_rows.append(gate)
            group_results[group_name].append(gate)
            if not gate["pass_gate"]:
                halt = True
                break

        fc.write_csv(output_dir / f"raw_runs_{int(budget)}.csv", budget_raw_rows)
        all_raw_rows.extend(budget_raw_rows)
        all_path_rows.extend(budget_path_rows)
        if halt:
            break

    formal_vs_naked_rows = formal_vs_naked_comparison_rows(
        all_raw_rows,
        profile_naked=(LNS_NO_COMMON_FLIP, A13_NO_COMMON_FLIP),
        profile_common=(LNS_FORMAL_COMMON_FLIP, A13_COMMON_FLIP),
    )

    all_path_rows = sorted(
        all_path_rows,
        key=lambda row: (
            sprint.as_int(row.get("budget")),
            str(row.get("category")),
            str(row.get("instance")),
            sprint.as_int(row.get("seed")),
            str(row.get("profile")),
            str(row.get("trace_path")),
        ),
    )

    decision = build_decision(
        metadata,
        all_raw_rows,
        all_gate_rows,
        group_results,
        all_path_rows,
        expected_rows=expected_rows,
        issues=[],
    )

    fc.write_csv(output_dir / "raw_runs.csv", all_raw_rows)
    fc.write_csv(output_dir / "path_distribution_comparison.csv", all_path_rows)
    fc.write_csv(output_dir / "formal_vs_naked_comparison.csv", formal_vs_naked_rows)
    fc.write_csv(output_dir / "parity_summary_by_budget.csv", all_gate_rows)
    write_outputs(output_dir, metadata, all_raw_rows, all_path_rows, all_gate_rows, decision)
    print(_json_dump({"phase": "lns_policy_kernel_probe_complete", "verdict": decision["verdict"], "rows": f"{len(all_raw_rows)}/{expected_rows}"}))
    return 0 if not decision.get("halt") else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--budgets", default="4000,8000,16000")
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--limit-instances", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-runs", action="store_true")
    return parser.parse_args(argv)


def load_hard_subset() -> list[dict[str, str]]:
    return [dict(row) for row in fc.read_csv(HARD_SUBSET_PATH)]


def build_metadata(args: argparse.Namespace, budgets: list[int], seeds: list[int], hard_subset: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "schema": "setp-e2-lns-policy-kernel-metadata.v1",
        "head": fc.git_head(),
        "budgets": budgets,
        "seeds": seeds,
        "hard_subset_count": len(hard_subset),
        "limit_instances": int(args.limit_instances),
        "full_gate": budgets == [4000, 8000, 16000] and int(args.limit_instances) == 0 and seeds == [1, 2, 3],
        "reachability_decision": fc.rel(REACHABILITY_DECISION),
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
    }


def preflight_issues(hard_subset: list[dict[str, str]]) -> list[str]:
    issues: list[str] = []
    if not hard_subset:
        issues.append(f"MISSING:{fc.rel(HARD_SUBSET_PATH)}")
    try:
        decision = fc.read_json(REACHABILITY_DECISION)
        if decision.get("verdict") != "ROUTE_PACKING_REACHABILITY_SUPPORTED":
            issues.append(f"REACHABILITY_NOT_SUPPORTED:{decision.get('verdict')}")
    except FileNotFoundError:
        issues.append(f"REACHABILITY_MISSING:{fc.rel(REACHABILITY_DECISION)}")
    issues.extend([f"PROTECTED_DIFF:{path}" for path in sprint.protected_diff()])
    return issues


def build_stage_tasks(
    output_dir: Path,
    hard_subset: list[dict[str, str]],
    *,
    seeds: list[int],
    budget: int,
    profiles: tuple[str, str],
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for item in hard_subset:
        category = str(item["category"])
        instance = str(item["instance"])
        for seed in seeds:
            for profile in profiles:
                run_id = sprint.sanitize_run_id(
                    f"LNS_POLICY_KERNEL__b{int(budget)}__{category}__{instance}__{profile}__seed{int(seed)}"
                )
                tasks.append(
                    {
                        "schema": "setp-e2-lns-policy-kernel-task.v1",
                        "phase": f"LNS_POLICY_KERNEL_{int(budget)}",
                        "budget": int(budget),
                        "run_id": run_id,
                        "category": category,
                        "instance": instance,
                        "bundle_dir": str(Path("models/data_bundle/generated_instances/e2_benchmark") / category / instance),
                        "profile": profile,
                        "seed": int(seed),
                        "eval_budget": int(budget),
                        "runtime_cap_seconds": float(RUNTIME_CAP_SECONDS.get(int(budget), 900.0)),
                        "scenario_type": "formal_goeke80",
                        "algorithm": ALGORITHM_BY_PROFILE[profile],
                        "checkpoint_path": str(output_dir / "checkpoints" / f"{run_id}.json"),
                        "head": fc.git_head(),
                    }
                )
    return tasks


def run_tasks(output_dir: Path, tasks: list[dict[str, Any]], *, workers: int, force: bool, logs: Path) -> list[dict[str, Any]]:
    logs.parent.mkdir(parents=True, exist_ok=True)
    existing = {str(row.get("run_id")): row for row in collect_existing_rows(output_dir, tasks)}
    todo = [task for task in tasks if force or task["run_id"] not in existing]
    if workers <= 1:
        for task in todo:
            row = run_task(task)
            existing[str(row.get("run_id", task["run_id"]))] = row
            fc.write_json(task_row_path(output_dir, str(row.get("run_id", task["run_id"]))), row)
            sprint.log_event(logs, "task_complete", run_id=task["run_id"], status=row.get("status"))
    else:
        with ProcessPoolExecutor(max_workers=int(workers)) as pool:
            futures = {pool.submit(run_task, task): task for task in todo}
            for future in as_completed(futures):
                task = futures[future]
                row = future.result()
                existing[str(row.get("run_id", task["run_id"]))] = row
                fc.write_json(task_row_path(output_dir, str(row.get("run_id", task["run_id"]))), row)
                sprint.log_event(logs, "task_complete", run_id=task["run_id"], status=row.get("status"))
    return [existing[task["run_id"]] for task in tasks if task["run_id"] in existing]


def run_task(task: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    old_checkpoint = os.environ.get("SETP_E2_ALNS_CHECKPOINT_PATH")
    os.environ["SETP_E2_ALNS_CHECKPOINT_PATH"] = str(fc.repo_path(Path(task["checkpoint_path"])))
    try:
        bundle_dir = REPO_ROOT / str(task["bundle_dir"])
        bundle = load_search_bundle(bundle_dir)
        prices = fc.prices_for_scenario(str(task["scenario_type"]))
        warm = make_shared_initial_solution(bundle, prices=prices)
        common_flip = COMMON_FLIP_BY_PROFILE[task["profile"]]
        if task["profile"].startswith("LNS_"):
            result = run_metaheuristic_baseline(
                "LNS",
                bundle_dir,
                seed=int(task["seed"]),
                eval_budget=int(task["eval_budget"]),
                max_runtime_seconds=float(task["runtime_cap_seconds"]),
                initial_solution=warm,
                prices=prices,
                common_flip_preprocess=bool(common_flip),
            )
        else:
            result = lns_policy_kernel.run_lns_policy_baseline(
                str(bundle_dir),
                seed=int(task["seed"]),
                eval_budget=int(task["eval_budget"]),
                max_runtime_seconds=float(task["runtime_cap_seconds"]),
                initial_solution=warm,
                prices=prices,
                common_flip_preprocess=bool(common_flip),
            )
        return result_row(task, started, result)
    except Exception as exc:
        return {
            **task,
            "status": "HALT_WORKER_ERROR",
            "failure_reason": repr(exc),
            "elapsed_seconds": time.perf_counter() - started,
        }
    finally:
        if old_checkpoint is None:
            os.environ.pop("SETP_E2_ALNS_CHECKPOINT_PATH", None)
        else:
            os.environ["SETP_E2_ALNS_CHECKPOINT_PATH"] = old_checkpoint


def result_row(task: dict[str, Any], started: float, result: Any) -> dict[str, Any]:
    solution = result.best_solution
    bundle_dir = REPO_ROOT / str(task["bundle_dir"])
    bundle = load_search_bundle(bundle_dir)
    prices = fc.prices_for_scenario(str(task["scenario_type"]))
    violations = check_solution(solution, bundle.instance, prices) if solution is not None else ["missing_solution"]
    status = "OK"
    failure_reason = ""
    if violations:
        status = "HALT_INFEASIBLE"
        failure_reason = "; ".join(str(item) for item in violations[:3])
    elif int(result.evals) < int(task["eval_budget"]):
        status = "HALT_UNDER_EVAL"
        failure_reason = f"Stopped at {result.evals}/{task['eval_budget']} evaluations."
    metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, prices) if solution is not None else {}
    return {
        "schema": "setp-e2-lns-policy-kernel-row.v1",
        "run_id": task["run_id"],
        "phase": task["phase"],
        "budget": int(task["budget"]),
        "category": task["category"],
        "instance": task["instance"],
        "profile": task["profile"],
        "algorithm": task["algorithm"],
        "seed": int(task["seed"]),
        "status": status,
        "failure_reason": failure_reason,
        "eval_budget": int(task["eval_budget"]),
        "actual_evals": int(result.evals),
        "runtime_cap_seconds": float(task["runtime_cap_seconds"]),
        "elapsed_seconds": time.perf_counter() - started,
        "evals_per_second": sprint.safe_ratio(float(result.evals), time.perf_counter() - started),
        "best_cost": float(result.best_cost),
        "best_signature": solution_signature_hash(solution) if solution is not None else "",
        "feasible": solution is not None and not violations,
        "violation_count": len(violations),
        "route_count": len(solution.routes) if solution is not None else 0,
        "cv_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv") if solution is not None else 0,
        "ev_route_count": sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev") if solution is not None else 0,
        "charging_action_count": len(solution.charging_actions) if solution is not None else 0,
        "E_total": metrics.get("E_total", float("nan")),
        "cost_fix": metrics.get("cost_fix", float("nan")),
        "cost_km": metrics.get("cost_km", float("nan")),
        "cost_carbon": metrics.get("cost_carbon", float("nan")),
        "cost_fuel": metrics.get("cost_fuel", float("nan")),
        "cost_elec": metrics.get("cost_elec", float("nan")),
        "cost_occ": metrics.get("cost_occ", float("nan")),
        "cost_transship": metrics.get("cost_transship", float("nan")),
        "checkpoint_path": task["checkpoint_path"],
        "trace": list(result.trace),
        "history": list(result.history),
        "operator_counts": dict(result.operator_counts),
        "head": task.get("head", ""),
        "common_flip_preprocess": bool(COMMON_FLIP_BY_PROFILE.get(task["profile"], False)),
    }


def raw_run_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    excluded = {"trace", "history", "operator_counts"}
    return [{key: value for key, value in row.items() if key not in excluded} for row in rows]


def path_distribution_rows(rows: list[dict[str, Any]], *, budget: int) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str, int, str, str], int] = {}
    totals: dict[tuple[str, str, int, str], int] = {}
    for row in rows:
        key_base = (str(row.get("category")), str(row.get("instance")), sprint.as_int(row.get("seed")), str(row.get("profile")))
        for trace_row in row.get("trace", []):
            path = str(trace_row.get("trace_path", trace_row.get("operator", "UNKNOWN")))
            counts[(*key_base, path)] = counts.get((*key_base, path), 0) + 1
            totals[key_base] = totals.get(key_base, 0) + 1
    out: list[dict[str, Any]] = []
    for (category, instance, seed, profile, path), count in sorted(counts.items()):
        total = totals.get((category, instance, seed, profile), 0)
        out.append(
            {
                "budget": int(budget),
                "category": category,
                "instance": instance,
                "seed": int(seed),
                "profile": profile,
                "trace_path": path,
                "count": count,
                "share": count / total if total else 0.0,
            }
        )
    return out


def group_gate_row_for_budget(
    *,
    raw_rows: list[dict[str, Any]],
    path_rows: list[dict[str, Any]],
    budget: int,
    lns_profile: str,
    a13_profile: str,
    protected: list[str],
) -> dict[str, Any]:
    pairs = pair_rows(raw_rows, lns_profile=lns_profile, a13_profile=a13_profile)
    gaps: list[float] = []
    route_deltas: list[float] = []
    fixed_deltas: list[float] = []
    wins = losses = ties = 0
    for lns_row, a13_row in pairs:
        lns_cost = sprint.as_float(lns_row.get("best_cost"))
        a13_cost = sprint.as_float(a13_row.get("best_cost"))
        if abs(a13_cost - lns_cost) <= 1e-9:
            ties += 1
        elif a13_cost < lns_cost:
            wins += 1
        else:
            losses += 1
        gaps.append((lns_cost - a13_cost) / lns_cost if lns_cost else float("nan"))
        route_deltas.append(sprint.as_int(a13_row.get("route_count")) - sprint.as_int(lns_row.get("route_count")))
        fixed_deltas.append(sprint.as_float(a13_row.get("cost_fix")) - sprint.as_float(lns_row.get("cost_fix")))

    infeasible_rows = [row for row in raw_rows if str(row.get("status")) == "HALT_INFEASIBLE" or sprint.as_int(row.get("violation_count")) > 0]
    under_eval_rows = [row for row in raw_rows if str(row.get("status")) == "HALT_UNDER_EVAL" or sprint.as_int(row.get("actual_evals")) < sprint.as_int(row.get("eval_budget"))]
    fail_rows = [row for row in raw_rows if str(row.get("status")) != "OK"]
    path_delta = max_path_share_delta(path_rows=path_rows, lns_profile=lns_profile, a13_profile=a13_profile)
    mean_gap = sum(gaps) / len(gaps) if gaps else float("nan")
    mean_route_delta = sum(route_deltas) / len(route_deltas) if route_deltas else float("nan")
    mean_fixed_delta = sum(fixed_deltas) / len(fixed_deltas) if fixed_deltas else float("nan")
    gate_ok = (
        not fail_rows
        and not protected
        and len(infeasible_rows) == 0
        and len(under_eval_rows) == 0
        and abs(mean_gap) <= GATE_THRESHOLD_GAP
        and abs(mean_route_delta) <= GATE_THRESHOLD_ROUTE
        and abs(mean_fixed_delta) <= GATE_THRESHOLD_FIXED
        and path_delta <= GATE_THRESHOLD_PATH
    )
    return {
        "group": _group_for_profiles(lns_profile=lns_profile, a13_profile=a13_profile),
        "budget": int(budget),
        "lns_profile": lns_profile,
        "a13_profile": a13_profile,
        "pairs": len(pairs),
        "ok_rows": len(raw_rows) - len(fail_rows),
        "fail_rows": len(fail_rows),
        "infeasible_rows": len(infeasible_rows),
        "under_eval_rows": len(under_eval_rows),
        "wins_vs_lns": wins,
        "losses_vs_lns": losses,
        "ties_vs_lns": ties,
        "mean_gap_vs_lns": mean_gap,
        "mean_route_count_delta_vs_lns": mean_route_delta,
        "mean_cost_fix_delta_vs_lns": mean_fixed_delta,
        "max_path_share_delta": path_delta,
        "gap_gate": abs(mean_gap) <= GATE_THRESHOLD_GAP,
        "route_gate": abs(mean_route_delta) <= GATE_THRESHOLD_ROUTE,
        "fixed_gate": abs(mean_fixed_delta) <= GATE_THRESHOLD_FIXED,
        "path_gate": path_delta <= GATE_THRESHOLD_PATH,
        "clean_gate": not fail_rows and not protected and len(infeasible_rows) == 0 and len(under_eval_rows) == 0,
        "protected_diff_empty": not protected,
        "pass_gate": gate_ok,
    }


def pair_rows(raw_rows: list[dict[str, Any]], *, lns_profile: str, a13_profile: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    grouped: dict[tuple[str, str, int], dict[str, dict[str, Any]]] = {}
    for row in raw_rows:
        key = (str(row.get("category")), str(row.get("instance")), sprint.as_int(row.get("seed")))
        grouped.setdefault(key, {})[str(row.get("profile"))] = row
    return [
        (rowset[lns_profile], rowset[a13_profile])
        for rowset in grouped.values()
        if lns_profile in rowset and a13_profile in rowset
    ]


def max_path_share_delta(*, path_rows: list[dict[str, Any]], lns_profile: str, a13_profile: str) -> float:
    grouped: dict[tuple[str, str, int, str], dict[str, float]] = {}
    for row in path_rows:
        key = (str(row.get("category")), str(row.get("instance")), sprint.as_int(row.get("seed")), str(row.get("trace_path")))
        grouped.setdefault(key, {})[str(row.get("profile"))] = sprint.as_float(row.get("share"))
    deltas = [abs(values.get(a13_profile, 0.0) - values.get(lns_profile, 0.0)) for values in grouped.values()]
    return max(deltas) if deltas else 0.0


def formal_vs_naked_comparison_rows(
    rows: list[dict[str, Any]],
    *,
    profile_naked: tuple[str, str],
    profile_common: tuple[str, str],
) -> list[dict[str, Any]]:
    by_key: dict[tuple[int, str, str, int], dict[str, dict[str, Any]]] = {}
    for row in rows:
        key = (int(row.get("budget")), str(row.get("category")), str(row.get("instance")), sprint.as_int(row.get("seed")))
        by_key.setdefault(key, {})[str(row.get("profile"))] = row
    out: list[dict[str, Any]] = []
    naked_lns, naked_a13 = profile_naked
    common_lns, common_a13 = profile_common
    for (budget, category, instance, seed), group in sorted(by_key.items()):
        r_naked_lns = group.get(naked_lns)
        r_naked_a13 = group.get(naked_a13)
        r_common_lns = group.get(common_lns)
        r_common_a13 = group.get(common_a13)
        if not (r_naked_lns and r_naked_a13 and r_common_lns and r_common_a13):
            continue
        out.append(
            {
                "budget": int(budget),
                "category": category,
                "instance": instance,
                "seed": int(seed),
                "lns_best_cost_naked": sprint.as_float(r_naked_lns.get("best_cost")),
                "lns_best_cost_common": sprint.as_float(r_common_lns.get("best_cost")),
                "lns_cost_delta_common_minus_naked": sprint.as_float(r_common_lns.get("best_cost")) - sprint.as_float(r_naked_lns.get("best_cost")),
                "lns_route_count_delta_common_minus_naked": sprint.as_int(r_common_lns.get("route_count")) - sprint.as_int(r_naked_lns.get("route_count")),
                "lns_cost_fix_delta_common_minus_naked": sprint.as_float(r_common_lns.get("cost_fix")) - sprint.as_float(r_naked_lns.get("cost_fix")),
                "a13_best_cost_naked": sprint.as_float(r_naked_a13.get("best_cost")),
                "a13_best_cost_common": sprint.as_float(r_common_a13.get("best_cost")),
                "a13_cost_delta_common_minus_naked": sprint.as_float(r_common_a13.get("best_cost")) - sprint.as_float(r_naked_a13.get("best_cost")),
                "a13_route_count_delta_common_minus_naked": sprint.as_int(r_common_a13.get("route_count")) - sprint.as_int(r_naked_a13.get("route_count")),
                "a13_cost_fix_delta_common_minus_naked": sprint.as_float(r_common_a13.get("cost_fix")) - sprint.as_float(r_naked_a13.get("cost_fix")),
            }
        )
    return out


def build_decision(
    metadata: dict[str, Any],
    raw_rows: list[dict[str, Any]],
    all_gate_rows: list[dict[str, Any]],
    group_results: dict[str, list[dict[str, Any]]],
    path_rows: list[dict[str, Any]],
    *,
    expected_rows: int,
    issues: list[str],
) -> dict[str, Any]:
    policy = group_results["POLICY_PARITY_NO_COMMON_FLIP"]
    formal = group_results["FORMAL_PARITY_COMMON_FLIP"]
    policy_pass = bool(policy) and all(sprint.truthy(row.get("pass_gate")) for row in policy)
    formal_pass = bool(formal) and all(sprint.truthy(row.get("pass_gate")) for row in formal)
    if issues:
        verdict = "HALT_A13_POLICY_KERNEL_PREFLIGHT"
        halt = True
    elif not all_rows_complete(len(raw_rows), expected_rows, group_results, metadata["budgets"]):
        verdict = "HALT_A13_POLICY_KERNEL_INCOMPLETE"
        halt = True
    elif policy_pass and formal_pass and len(raw_rows) == expected_rows:
        verdict = "A13_PARITY_SUPPORTED" if metadata.get("full_gate") else "A13_PARITY_SMOKE_SUPPORTED"
        halt = False
    else:
        verdict = "A13_PARITY_FAILED"
        halt = True
    policy_report = _summarize_group("POLICY_PARITY_NO_COMMON_FLIP", policy, metadata["budgets"])
    formal_report = _summarize_group("FORMAL_PARITY_COMMON_FLIP", formal, metadata["budgets"])
    return {
        "schema": "setp-e2-lns-policy-kernel-decision.v1",
        "verdict": verdict,
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "head": metadata.get("head", ""),
        "halt": halt,
        "issues": issues,
        "rows": len(raw_rows),
        "expected_rows": expected_rows,
        "path_rows": len(path_rows),
        "full_gate": bool(metadata.get("full_gate")),
        "POLICY_PARITY_NO_COMMON_FLIP": policy_report,
        "FORMAL_PARITY_COMMON_FLIP": formal_report,
        "next_stage_allowed": "A14_ADAPTIVE_LNS_KERNEL_ALNS" if verdict == "A13_PARITY_SUPPORTED" else "",
        "gate_rows": all_gate_rows,
    }


def all_rows_complete(
    observed_rows: int,
    expected_rows: int,
    group_results: dict[str, list[dict[str, Any]]],
    budgets: list[int],
) -> bool:
    return (
        bool(group_results["POLICY_PARITY_NO_COMMON_FLIP"])
        and bool(group_results["FORMAL_PARITY_COMMON_FLIP"])
        and len(group_results["POLICY_PARITY_NO_COMMON_FLIP"]) == len(budgets)
        and len(group_results["FORMAL_PARITY_COMMON_FLIP"]) == len(budgets)
        and observed_rows == expected_rows
    )


def _summarize_group(group_name: str, rows: list[dict[str, Any]], budgets: list[int]) -> dict[str, Any]:
    return {
        "group": group_name,
        "profiles": list(PROFILES_BY_GROUP[group_name]),
        "budgets_run": [sprint.as_int(row.get("budget")) for row in rows],
        "expected_budgets": budgets,
        "pass_all": bool(rows) and all(sprint.truthy(row.get("pass_gate")) for row in rows),
        "verdict": "PASS" if bool(rows) and all(sprint.truthy(row.get("pass_gate")) for row in rows) else "INCOMPLETE_OR_FAIL",
        "rows": rows,
    }


def _group_for_profiles(lns_profile: str, a13_profile: str) -> str:
    for group_name, profile_pair in PROFILES_BY_GROUP.items():
        if profile_pair == (lns_profile, a13_profile):
            return group_name
    return "UNKNOWN"


def write_outputs(
    output_dir: Path,
    metadata: dict[str, Any],
    raw_rows: list[dict[str, Any]],
    path_rows: list[dict[str, Any]],
    gate_rows: list[dict[str, Any]],
    decision: dict[str, Any],
) -> None:
    fc.write_json(output_dir / "metadata.json", metadata)
    fc.write_json(output_dir / "decision.json", decision)
    fc.write_csv(output_dir / "raw_runs.csv", raw_rows)
    fc.write_csv(output_dir / "path_distribution_comparison.csv", path_rows)
    fc.write_csv(output_dir / "parity_summary_by_budget.csv", gate_rows)
    (output_dir / "diagnosis.md").write_text(write_diagnosis(decision), encoding="utf-8")
    (output_dir / "next_action.md").write_text(write_next_action(decision), encoding="utf-8")
    if decision["verdict"] != "A13_PARITY_SUPPORTED":
        (output_dir / "parity_failure_report.md").write_text(write_diagnosis(decision), encoding="utf-8")
    sprint.write_hashes(output_dir)


def write_diagnosis(decision: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# A13 LNS Policy Kernel Diagnosis",
            "",
            f"verdict -> `{decision.get('verdict')}`",
            f"rows -> {decision.get('rows')}/{decision.get('expected_rows')}",
            "",
            f"policy-parity -> {decision.get('POLICY_PARITY_NO_COMMON_FLIP', {}).get('verdict', 'UNKNOWN')}",
            f"formal-parity -> {decision.get('FORMAL_PARITY_COMMON_FLIP', {}).get('verdict', 'UNKNOWN')}",
            "Boundary: diagnostic-only parity evidence; no A14/hybrid implementation in this phase.",
            "",
        ]
    )


def write_next_action(decision: dict[str, Any]) -> str:
    if decision.get("verdict") == "A13_PARITY_SUPPORTED":
        remedy = "implement A14_ADAPTIVE_LNS_KERNEL_ALNS"
    else:
        remedy = "inspect parity_failure_report.md; do not implement A14/hybrid"
    return "\n".join(["# Next Action", "", f"minimal_remedy -> {remedy}", ""])


def collect_existing_rows(output_dir: Path, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in tasks:
        path = task_row_path(output_dir, task["run_id"])
        if path.exists():
            rows.append(fc.read_json(path))
    return rows


def task_row_path(output_dir: Path, run_id: str) -> Path:
    return output_dir / ".tasks" / f"{sprint.sanitize_run_id(run_id)}.json"


def _json_dump(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


if __name__ == "__main__":
    raise SystemExit(main())
