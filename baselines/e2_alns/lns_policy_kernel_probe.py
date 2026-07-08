"""Diagnostic-only A13 LNS policy-kernel parity probe."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import os
from pathlib import Path
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

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search import lns_policy_kernel
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.candidates import make_shared_initial_solution, solution_signature_hash
from setp_solver.search.metaheuristic_baselines import run_metaheuristic_baseline

from baselines.e2_alns import e2_final_closure as fc
from baselines.e2_alns import selector_sprint_probe as sprint


OUTPUT_DIR = REPO_ROOT / "baselines/e2_alns/lns_policy_kernel_probe_20260708"
HARD_SUBSET_PATH = REPO_ROOT / "baselines/e2_alns/route_compression_probe_20260705/hard_subset_instances.csv"
REACHABILITY_DECISION = REPO_ROOT / "baselines/e2_alns/route_packing_reachability_audit_20260708/decision.json"
RUNTIME_CAP_SECONDS = {4000: 900.0, 8000: 1800.0, 16000: 3600.0}
LNS_PROFILE = "LNS_REFERENCE"
A13_PROFILE = "A13_LNS_POLICY_KERNEL"
PROFILES = (LNS_PROFILE, A13_PROFILE)
HASH_EXCLUDE_NAMES = {"artifact_hashes.json", ".DS_Store"}
HASH_EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".tasks"}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = fc.repo_path(Path(args.output_dir))
    if output_dir.exists() and args.force:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logs = output_dir / "logs/full_run.log"
    logs.parent.mkdir(parents=True, exist_ok=True)

    budgets = sprint.parse_ints(args.budgets)
    seeds = sprint.parse_ints(args.seeds)
    hard_subset = load_hard_subset(HARD_SUBSET_PATH)
    if int(args.limit_instances) > 0:
        hard_subset = hard_subset[: int(args.limit_instances)]
    metadata = build_metadata(args, budgets, seeds, hard_subset)
    fc.write_json(output_dir / "metadata.json", metadata)

    issues = preflight_issues(hard_subset)
    if issues:
        decision = build_decision(metadata, [], [], expected_rows=0, issues=issues)
        write_outputs(output_dir, metadata, [], [], [], decision)
        return 2

    all_raw_rows: list[dict[str, Any]] = []
    all_path_rows: list[dict[str, Any]] = []
    all_gate_rows: list[dict[str, Any]] = []
    expected_rows = 0
    for budget in budgets:
        tasks = build_stage_tasks(output_dir, hard_subset, seeds=seeds, budget=int(budget))
        expected_rows += len(tasks)
        rows = collect_existing_rows(output_dir, tasks)
        if not args.skip_runs:
            rows = run_tasks(output_dir, tasks, workers=int(args.workers), force=bool(args.force), logs=logs)
        raw_rows = raw_run_rows(rows)
        path_rows = path_distribution_rows(rows, budget=int(budget))
        gate_row = gate_row_for_budget(raw_rows, path_rows, budget=int(budget), protected=sprint.protected_diff())
        all_raw_rows.extend(raw_rows)
        all_path_rows.extend(path_rows)
        all_gate_rows.append(gate_row)
        fc.write_csv(output_dir / f"raw_runs_{int(budget)}.csv", raw_rows)
        fc.write_csv(output_dir / f"path_distribution_comparison_{int(budget)}.csv", path_rows)
        fc.write_csv(output_dir / f"parity_summary_{int(budget)}.csv", [gate_row])
        sprint.log_event(logs, "budget_complete", budget=int(budget), rows=len(rows), pass_gate=gate_row.get("pass_gate"))
        if not sprint.truthy(gate_row.get("pass_gate")):
            break

    decision = build_decision(metadata, all_raw_rows, all_gate_rows, expected_rows=expected_rows, issues=[])
    write_outputs(output_dir, metadata, all_raw_rows, all_path_rows, all_gate_rows, decision)
    print(json.dumps({"phase": "lns_policy_kernel_probe_complete", "verdict": decision["verdict"], "rows": f"{len(all_raw_rows)}/{expected_rows}"}, ensure_ascii=False))
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


def load_hard_subset(path: Path) -> list[dict[str, str]]:
    return [dict(row) for row in fc.read_csv(path)]


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
    reachability = fc.read_json(REACHABILITY_DECISION)
    if reachability.get("verdict") != "ROUTE_PACKING_REACHABILITY_SUPPORTED":
        issues.append(f"REACHABILITY_NOT_SUPPORTED:{reachability.get('verdict')}")
    issues.extend([f"PROTECTED_DIFF:{path}" for path in sprint.protected_diff()])
    return issues


def build_stage_tasks(output_dir: Path, hard_subset: list[dict[str, str]], *, seeds: list[int], budget: int) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for item in hard_subset:
        category = str(item["category"])
        instance = str(item["instance"])
        for seed in seeds:
            for profile in PROFILES:
                run_id = sprint.sanitize_run_id(f"LNS_POLICY_KERNEL__b{int(budget)}__{category}__{instance}__{profile}__seed{int(seed)}")
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
                        "algorithm": "LNS" if profile == LNS_PROFILE else "A13_LNS_POLICY_KERNEL",
                        "seed": int(seed),
                        "eval_budget": int(budget),
                        "runtime_cap_seconds": float(RUNTIME_CAP_SECONDS.get(int(budget), 900.0)),
                        "scenario_type": "formal_goeke80",
                        "checkpoint_path": str(output_dir / "checkpoints" / f"{run_id}.json"),
                        "head": fc.git_head(),
                    }
                )
    return tasks


def run_tasks(output_dir: Path, tasks: list[dict[str, Any]], *, workers: int, force: bool, logs: Path) -> list[dict[str, Any]]:
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
        if task["profile"] == LNS_PROFILE:
            result = run_metaheuristic_baseline(
                "LNS",
                bundle_dir,
                seed=int(task["seed"]),
                eval_budget=int(task["eval_budget"]),
                max_runtime_seconds=float(task["runtime_cap_seconds"]),
                initial_solution=warm,
                prices=prices,
                common_flip_preprocess=False,
            )
        else:
            result = lns_policy_kernel.run_lns_policy_baseline(
                str(bundle_dir),
                seed=int(task["seed"]),
                eval_budget=int(task["eval_budget"]),
                max_runtime_seconds=float(task["runtime_cap_seconds"]),
                initial_solution=warm,
                prices=prices,
            )
        solution = result.best_solution
        return result_row(task, started, solution, float(result.best_cost), int(result.evals), list(result.trace), list(result.history), dict(result.operator_counts), bundle, prices)
    except Exception as exc:  # pragma: no cover - serialized for diagnostic workers.
        return {**task, "status": "HALT_WORKER_ERROR", "failure_reason": repr(exc), "elapsed_seconds": time.perf_counter() - started}
    finally:
        if old_checkpoint is None:
            os.environ.pop("SETP_E2_ALNS_CHECKPOINT_PATH", None)
        else:
            os.environ["SETP_E2_ALNS_CHECKPOINT_PATH"] = old_checkpoint


def result_row(
    task: dict[str, Any],
    started: float,
    solution: Any,
    best_cost: float,
    actual_evals: int,
    trace: list[dict[str, Any]],
    history: list[dict[str, Any]],
    operator_counts: dict[str, Any],
    bundle: Any,
    prices: Any,
) -> dict[str, Any]:
    violations = check_solution(solution, bundle.instance, prices) if solution is not None else ["missing_solution"]
    status = "OK"
    failure_reason = ""
    if violations:
        status = "HALT_INFEASIBLE"
        failure_reason = "; ".join(str(item) for item in violations[:3])
    elif actual_evals < int(task["eval_budget"]):
        status = "HALT_UNDER_EVAL"
        failure_reason = f"Stopped at {actual_evals}/{task['eval_budget']} evaluations."
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
        "actual_evals": int(actual_evals),
        "runtime_cap_seconds": float(task["runtime_cap_seconds"]),
        "elapsed_seconds": time.perf_counter() - started,
        "evals_per_second": sprint.safe_ratio(actual_evals, time.perf_counter() - started),
        "best_cost": best_cost,
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
        "trace": trace,
        "history": history,
        "operator_counts": operator_counts,
        "head": task.get("head", ""),
    }


def raw_run_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    excluded = {"trace", "history", "operator_counts"}
    return [{key: value for key, value in row.items() if key not in excluded} for row in rows]


def path_distribution_rows(rows: list[dict[str, Any]], *, budget: int) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str, str, int, str], int] = {}
    totals: dict[tuple[str, str, str, int], int] = {}
    for row in rows:
        key_base = (str(row.get("category")), str(row.get("instance")), str(row.get("profile")), sprint.as_int(row.get("seed")))
        for trace_row in row.get("trace", []):
            path = str(trace_row.get("trace_path", trace_row.get("operator", "UNKNOWN")))
            counts[(*key_base, path)] = counts.get((*key_base, path), 0) + 1
            totals[key_base] = totals.get(key_base, 0) + 1
    out: list[dict[str, Any]] = []
    for (category, instance, profile, seed, path), count in sorted(counts.items()):
        total = totals.get((category, instance, profile, seed), 0)
        out.append({"budget": int(budget), "category": category, "instance": instance, "profile": profile, "seed": int(seed), "trace_path": path, "count": count, "share": count / total if total else 0.0})
    return out


def gate_row_for_budget(raw_rows: list[dict[str, Any]], path_rows: list[dict[str, Any]], *, budget: int, protected: list[str]) -> dict[str, Any]:
    pairs = paired_rows(raw_rows)
    gaps: list[float] = []
    route_deltas: list[int] = []
    fixed_deltas: list[float] = []
    wins = losses = ties = 0
    for lns, a13 in pairs:
        lns_cost = sprint.as_float(lns.get("best_cost"))
        a13_cost = sprint.as_float(a13.get("best_cost"))
        if abs(a13_cost - lns_cost) <= 1e-9:
            ties += 1
        elif a13_cost < lns_cost:
            wins += 1
        else:
            losses += 1
        gaps.append((lns_cost - a13_cost) / lns_cost if lns_cost else float("nan"))
        route_deltas.append(sprint.as_int(a13.get("route_count")) - sprint.as_int(lns.get("route_count")))
        fixed_deltas.append(sprint.as_float(a13.get("cost_fix")) - sprint.as_float(lns.get("cost_fix")))
    path_delta = max_path_share_delta(path_rows)
    fail_rows = [row for row in raw_rows if row.get("status") != "OK"]
    mean_gap = sum(gaps) / len(gaps) if gaps else float("nan")
    mean_route_delta = sum(route_deltas) / len(route_deltas) if route_deltas else float("nan")
    mean_fixed_delta = sum(fixed_deltas) / len(fixed_deltas) if fixed_deltas else float("nan")
    pass_gate = (
        not fail_rows
        and not protected
        and abs(mean_gap) <= 0.002
        and abs(mean_route_delta) <= 0.10
        and abs(mean_fixed_delta) <= 8.0
        and path_delta <= 0.05
    )
    return {
        "budget": int(budget),
        "pairs": len(pairs),
        "ok_rows": len(raw_rows) - len(fail_rows),
        "fail_rows": len(fail_rows),
        "wins_vs_lns": wins,
        "losses_vs_lns": losses,
        "ties_vs_lns": ties,
        "mean_gap_vs_lns": mean_gap,
        "mean_route_count_delta_vs_lns": mean_route_delta,
        "mean_cost_fix_delta_vs_lns": mean_fixed_delta,
        "max_path_share_delta": path_delta,
        "gap_gate": abs(mean_gap) <= 0.002,
        "route_gate": abs(mean_route_delta) <= 0.10,
        "fixed_gate": abs(mean_fixed_delta) <= 8.0,
        "path_gate": path_delta <= 0.05,
        "clean_gate": not fail_rows and not protected,
        "pass_gate": pass_gate,
    }


def paired_rows(raw_rows: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    grouped: dict[tuple[str, str, int], dict[str, dict[str, Any]]] = {}
    for row in raw_rows:
        key = (str(row.get("category")), str(row.get("instance")), sprint.as_int(row.get("seed")))
        grouped.setdefault(key, {})[str(row.get("profile"))] = row
    return [(profiles[LNS_PROFILE], profiles[A13_PROFILE]) for _, profiles in sorted(grouped.items()) if LNS_PROFILE in profiles and A13_PROFILE in profiles]


def max_path_share_delta(path_rows: list[dict[str, Any]]) -> float:
    grouped: dict[tuple[str, str, int, str], dict[str, float]] = {}
    for row in path_rows:
        key = (str(row.get("category")), str(row.get("instance")), sprint.as_int(row.get("seed")), str(row.get("trace_path")))
        grouped.setdefault(key, {})[str(row.get("profile"))] = sprint.as_float(row.get("share"))
    deltas = [abs(values.get(A13_PROFILE, 0.0) - values.get(LNS_PROFILE, 0.0)) for values in grouped.values()]
    return max(deltas) if deltas else 0.0


def build_decision(
    metadata: dict[str, Any],
    raw_rows: list[dict[str, Any]],
    gate_rows: list[dict[str, Any]],
    *,
    expected_rows: int,
    issues: list[str],
) -> dict[str, Any]:
    if issues:
        verdict = "HALT_A13_POLICY_KERNEL_PREFLIGHT"
        halt = True
    elif not gate_rows or len(raw_rows) != expected_rows:
        verdict = "HALT_A13_POLICY_KERNEL_INCOMPLETE"
        halt = True
    elif all(sprint.truthy(row.get("pass_gate")) for row in gate_rows):
        verdict = "A13_PARITY_SUPPORTED" if metadata.get("full_gate") else "A13_PARITY_SMOKE_SUPPORTED"
        halt = False
    else:
        verdict = "A13_PARITY_FAILED"
        halt = True
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
        "gate_rows": gate_rows,
        "full_gate": bool(metadata.get("full_gate")),
        "next_stage_allowed": "A14_ADAPTIVE_LNS_KERNEL_ALNS" if verdict == "A13_PARITY_SUPPORTED" else "",
    }


def write_outputs(
    output_dir: Path,
    metadata: dict[str, Any],
    raw_rows: list[dict[str, Any]],
    path_rows: list[dict[str, Any]],
    gate_rows: list[dict[str, Any]],
    decision: dict[str, Any],
) -> None:
    fc.write_json(output_dir / "metadata.json", metadata)
    fc.write_csv(output_dir / "raw_runs.csv", raw_rows)
    fc.write_csv(output_dir / "path_distribution_comparison.csv", path_rows)
    fc.write_csv(output_dir / "parity_summary_by_budget.csv", gate_rows)
    fc.write_json(output_dir / "decision.json", decision)
    (output_dir / "diagnosis.md").write_text(write_diagnosis(decision), encoding="utf-8")
    (output_dir / "next_action.md").write_text(write_next_action(decision), encoding="utf-8")
    if decision["verdict"] == "A13_PARITY_FAILED":
        (output_dir / "parity_failure_report.md").write_text(write_diagnosis(decision), encoding="utf-8")
    sprint.write_hashes(output_dir)


def write_diagnosis(decision: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# A13 LNS Policy Kernel Diagnosis",
            "",
            f"verdict -> `{decision.get('verdict')}`",
            f"rows -> {decision.get('rows')}/{decision.get('expected_rows')}",
            "Boundary: diagnostic-only parity evidence; no A14/hybrid implementation is authorized unless full A13 parity passes.",
            "",
        ]
    )


def write_next_action(decision: dict[str, Any]) -> str:
    if decision.get("verdict") == "A13_PARITY_SUPPORTED":
        remedy = "implement A14 macro-adaptive LNS kernel"
    elif decision.get("verdict") == "A13_PARITY_SMOKE_SUPPORTED":
        remedy = "run the full A13 parity gate before any A14 implementation"
    else:
        remedy = "stop and inspect parity_failure_report.md; do not implement A14"
    return "\n".join(["# Next Action", "", f"minimal_remedy -> {remedy}", ""])


def collect_existing_rows(output_dir: Path, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in tasks:
        path = task_row_path(output_dir, task["run_id"])
        if path.exists():
            rows.append(fc.read_json(path))
    return rows


def task_row_path(output_dir: Path, run_id: str) -> Path:
    return output_dir / ".tasks" / f"{run_id}.json"


if __name__ == "__main__":
    raise SystemExit(main())
