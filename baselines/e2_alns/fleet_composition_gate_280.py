"""280kWh fleet-composition gate before the next formal E1-E7 rerun.

This runner is intentionally diagnostic. It keeps the promoted default
parameters untouched and checks whether the 280kWh battery update creates a
new all-EV/EV-heavy degeneration before the broader formal rerun is allowed to
reuse "mixed fleet" wording.

It does not modify generated bundles, prices.py, cost.py, check.py,
evaluation.py, or solver semantics.
"""

from __future__ import annotations

import argparse
import csv
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Iterable

import numpy as np

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.alns_wouda import SearchPolicy, run_alns_wouda
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.winner_operators import e2_alns_throughput_flags


BENCHMARK_ROOT = Path("models/data_bundle/generated_instances/e2_benchmark")
DEFAULT_OUTPUT_DIR = Path("baselines/e2_alns/280kwh_fleet_composition_gate_data")
DEFAULT_REPORT = Path("baselines/e2_alns/280kwh_fleet_composition_gate.md")

REPRESENTATIVE_INSTANCES = (
    "vanilla/e2-vanilla-25c-01",
    "vanilla/e2-vanilla-50c-01",
    "vanilla/e2-vanilla-75c-01",
    "vanilla/e2-vanilla-100c-01",
    "vanilla/e2-vanilla-150c-01",
    "vanilla/e2-vanilla-200c-01",
    "multidepot/e2-multidepot-25c-01",
    "multidepot/e2-multidepot-50c-01",
    "multidepot/e2-multidepot-75c-01",
    "multidepot/e2-multidepot-100c-01",
    "multidepot/e2-multidepot-150c-01",
    "multidepot/e2-multidepot-200c-01",
    "threeshift/e2-threeshift-50c-01",
    "threeshift/e2-threeshift-75c-01",
    "threeshift/e2-threeshift-100c-01",
    "threeshift/e2-threeshift-150c-01",
    "threeshift/e2-threeshift-200c-01",
)

SMOKE_INSTANCES = (
    "vanilla/e2-vanilla-25c-01",
    "multidepot/e2-multidepot-100c-01",
    "threeshift/e2-threeshift-200c-01",
)

VARIANT_ORDER = ("free_mixed", "cv_shell", "ev_shell")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT))
    parser.add_argument("--instance-set", choices=("smoke", "representative", "custom"), default="representative")
    parser.add_argument("--instances", nargs="*", default=[])
    parser.add_argument("--seeds", nargs="*", type=int, default=[1])
    parser.add_argument("--eval-budget", type=int, default=1000)
    parser.add_argument("--runtime-cap-small", type=float, default=60.0)
    parser.add_argument("--runtime-cap-medium", type=float, default=120.0)
    parser.add_argument("--runtime-cap-large", type=float, default=180.0)
    parser.add_argument("--task-timeout-buffer", type=float, default=30.0)
    parser.add_argument("--in-process", action="store_true", help="Run tasks in-process; default uses per-task subprocess timeouts.")
    parser.add_argument("--phase0-only", action="store_true")
    parser.add_argument("--single-run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--single-category", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-instance", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-variant", default="", help=argparse.SUPPRESS)
    parser.add_argument("--single-seed", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--single-eval-budget", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--single-runtime-cap", type=float, default=0.0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    if args.single_run:
        return single_run_cli(repo_root, args)

    output_dir = repo_root / args.output_dir
    report_path = repo_root / args.report_path
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = build_metadata(repo_root, args)
    instances = selected_instances(args)
    phase0_rows = phase0_instance_audit(repo_root, instances)
    write_csv(output_dir / "phase0_instance_audit.csv", phase0_rows)

    raw_rows: list[dict[str, Any]] = []
    winner_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    if not args.phase0_only:
        raw_rows = run_gate(repo_root, instances, args)
        write_csv(output_dir / "raw_runs.csv", raw_rows)
        winner_rows = winner_rows_from_raw(raw_rows)
        write_csv(output_dir / "winners.csv", winner_rows)
        summary_rows = summary_rows_from_winners(winner_rows)
        write_csv(output_dir / "composition_summary.csv", summary_rows)
    else:
        write_csv(output_dir / "raw_runs.csv", raw_rows)
        write_csv(output_dir / "winners.csv", winner_rows)
        write_csv(output_dir / "composition_summary.csv", summary_rows)

    conclusion = summarize_conclusion(metadata, phase0_rows, raw_rows, winner_rows)
    write_json(output_dir / "metadata.json", metadata)
    write_json(output_dir / "conclusion.json", conclusion)
    report_path.write_text(render_report(metadata, phase0_rows, raw_rows, winner_rows, summary_rows, conclusion), encoding="utf-8")

    stdout_summary = {
        "schema_version": "setp-280kwh-fleet-composition-gate.v1",
        "verdict": conclusion["verdict"],
        "evidence_strength": conclusion["evidence_strength"],
        "report": str(args.report_path),
        "output_dir": str(args.output_dir),
        "instances": len(instances),
        "raw_rows": len(raw_rows),
        "winner_rows": len(winner_rows),
    }
    print(json.dumps(stdout_summary, ensure_ascii=False, sort_keys=True))
    return 2 if str(conclusion["verdict"]).startswith("HALT_") else 0


def selected_instances(args: argparse.Namespace) -> list[str]:
    if args.instance_set == "smoke":
        return list(SMOKE_INSTANCES)
    if args.instance_set == "representative":
        return list(REPRESENTATIVE_INSTANCES)
    if not args.instances:
        raise ValueError("--instance-set custom requires --instances")
    return [normalize_instance(value) for value in args.instances]


def normalize_instance(value: str) -> str:
    text = str(value).strip()
    if "/" in text:
        category, instance = text.split("/", 1)
        return f"{category}/{instance}"
    for category in ("vanilla", "multidepot", "threeshift"):
        if text.startswith(f"e2-{category}-"):
            return f"{category}/{text}"
    raise ValueError(f"Cannot infer category for instance {value!r}; use category/instance")


def build_metadata(repo_root: Path, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": "setp-280kwh-fleet-composition-gate.v1",
        "repo_root": str(repo_root),
        "commit_hash": git_output(repo_root, "rev-parse", "HEAD"),
        "git_status_short": git_output(repo_root, "status", "--short", "--untracked-files=all"),
        "python": sys.executable,
        "python_version": sys.version.replace("\n", " "),
        "numpy": np.__version__,
        "command": " ".join([sys.executable, *sys.argv]),
        "B_battery_kwh": float(DEFAULT_PRICES.B_battery_kwh),
        "v_speed_ms": float(DEFAULT_PRICES.v_speed_ms),
        "carbon_price": float(DEFAULT_PRICES.carbon_price),
        "eval_budget": int(args.eval_budget),
        "seeds": list(args.seeds),
        "instance_set": str(args.instance_set),
        "runtime_caps": {
            "small": float(args.runtime_cap_small),
            "medium": float(args.runtime_cap_medium),
            "large": float(args.runtime_cap_large),
        },
        "diagnostic_artifact_commit": "PENDING_COMMIT",
    }


def phase0_instance_audit(repo_root: Path, instances: Iterable[str]) -> list[dict[str, Any]]:
    rows = []
    for item in instances:
        category, instance = item.split("/", 1)
        bundle_dir = repo_root / BENCHMARK_ROOT / category / instance
        rows.append(
            {
                "category": category,
                "instance": instance,
                "bundle_dir": str(bundle_dir.relative_to(repo_root)),
                "exists": bundle_dir.exists(),
                "instance_json_exists": (bundle_dir / "instance.json").exists(),
                "distance_matrix_exists": (bundle_dir / "distance_matrix.npy").exists(),
                "carbon_profile_exists": (bundle_dir / "carbon_profile.csv").exists(),
                "customer_count_from_name": customer_count(instance),
            }
        )
    return rows


def run_gate(repo_root: Path, instances: list[str], args: argparse.Namespace) -> list[dict[str, Any]]:
    flags = e2_alns_throughput_flags(route_cost_cache=True, repair_structure_cache=True, timing_ledger=False)
    rows: list[dict[str, Any]] = []
    for item in instances:
        category, instance = item.split("/", 1)
        bundle_dir = repo_root / BENCHMARK_ROOT / category / instance
        cap = runtime_cap(instance, args)
        for seed in args.seeds:
            for variant in VARIANT_ORDER:
                if args.in_process:
                    row = run_one(repo_root, bundle_dir, category, instance, variant, int(seed), int(args.eval_budget), cap, flags)
                else:
                    row = run_one_subprocess(repo_root, args, category, instance, variant, int(seed), int(args.eval_budget), cap)
                rows.append(row)
                write_csv(repo_root / args.output_dir / "raw_runs.partial.csv", rows)
    return rows


def single_run_cli(repo_root: Path, args: argparse.Namespace) -> int:
    flags = e2_alns_throughput_flags(route_cost_cache=True, repair_structure_cache=True, timing_ledger=False)
    category = str(args.single_category)
    instance = str(args.single_instance)
    bundle_dir = repo_root / BENCHMARK_ROOT / category / instance
    row = run_one(
        repo_root,
        bundle_dir,
        category,
        instance,
        str(args.single_variant),
        int(args.single_seed),
        int(args.single_eval_budget),
        float(args.single_runtime_cap),
        flags,
    )
    print(json.dumps(row, ensure_ascii=False, sort_keys=True))
    return 1 if row.get("status") == "ERROR" else 0


def run_one_subprocess(
    repo_root: Path,
    args: argparse.Namespace,
    category: str,
    instance: str,
    variant: str,
    seed: int,
    eval_budget: int,
    runtime_cap_seconds: float,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--repo-root",
        str(repo_root),
        "--single-run",
        "--single-category",
        category,
        "--single-instance",
        instance,
        "--single-variant",
        variant,
        "--single-seed",
        str(seed),
        "--single-eval-budget",
        str(eval_budget),
        "--single-runtime-cap",
        str(runtime_cap_seconds),
    ]
    started = time.perf_counter()
    timeout = float(runtime_cap_seconds) + float(args.task_timeout_buffer)
    try:
        completed = subprocess.run(
            command,
            cwd=repo_root,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return timeout_row(repo_root, category, instance, variant, seed, eval_budget, runtime_cap_seconds, timeout, time.perf_counter() - started, exc)
    stdout = completed.stdout.strip()
    try:
        payload = json.loads(stdout.splitlines()[-1]) if stdout else {}
    except Exception as exc:  # noqa: BLE001 - diagnostics preserve parse failures.
        return subprocess_error_row(
            repo_root,
            category,
            instance,
            variant,
            seed,
            eval_budget,
            runtime_cap_seconds,
            "JSON_PARSE_ERROR",
            time.perf_counter() - started,
            completed.returncode,
            stdout,
            completed.stderr,
            str(exc),
        )
    if completed.returncode != 0 and payload.get("status") == "OK":
        payload["status"] = "SUBPROCESS_NONZERO"
    payload.setdefault("subprocess_returncode", completed.returncode)
    if completed.stderr:
        payload.setdefault("subprocess_stderr_tail", tail_text(completed.stderr))
    return payload


def timeout_row(
    repo_root: Path,
    category: str,
    instance: str,
    variant: str,
    seed: int,
    eval_budget: int,
    runtime_cap_seconds: float,
    timeout_seconds: float,
    elapsed_seconds: float,
    exc: subprocess.TimeoutExpired,
) -> dict[str, Any]:
    return {
        "commit_hash": git_output(repo_root, "rev-parse", "--short", "HEAD"),
        "category": category,
        "instance": instance,
        "variant": variant,
        "seed": int(seed),
        "eval_budget": int(eval_budget),
        "runtime_cap_seconds": float(runtime_cap_seconds),
        "elapsed_seconds": float(elapsed_seconds),
        "task_timeout_seconds": float(timeout_seconds),
        "B_battery_kwh": float(DEFAULT_PRICES.B_battery_kwh),
        "v_speed_ms": float(DEFAULT_PRICES.v_speed_ms),
        "carbon_price": float(DEFAULT_PRICES.carbon_price),
        "status": "TIMEOUT",
        "actual_evals": 0,
        "violation_count": -1,
        "route_count": 0,
        "cv_route_count": 0,
        "ev_route_count": 0,
        "composition": "timeout",
        "total_cost": float("inf"),
        "subprocess_stdout_tail": tail_text(exc.stdout),
        "subprocess_stderr_tail": tail_text(exc.stderr),
    }


def subprocess_error_row(
    repo_root: Path,
    category: str,
    instance: str,
    variant: str,
    seed: int,
    eval_budget: int,
    runtime_cap_seconds: float,
    status: str,
    elapsed_seconds: float,
    returncode: int,
    stdout: str,
    stderr: str,
    error: str,
) -> dict[str, Any]:
    return {
        "commit_hash": git_output(repo_root, "rev-parse", "--short", "HEAD"),
        "category": category,
        "instance": instance,
        "variant": variant,
        "seed": int(seed),
        "eval_budget": int(eval_budget),
        "runtime_cap_seconds": float(runtime_cap_seconds),
        "elapsed_seconds": float(elapsed_seconds),
        "B_battery_kwh": float(DEFAULT_PRICES.B_battery_kwh),
        "v_speed_ms": float(DEFAULT_PRICES.v_speed_ms),
        "carbon_price": float(DEFAULT_PRICES.carbon_price),
        "status": status,
        "subprocess_returncode": int(returncode),
        "actual_evals": 0,
        "violation_count": -1,
        "route_count": 0,
        "cv_route_count": 0,
        "ev_route_count": 0,
        "composition": "error",
        "total_cost": float("inf"),
        "subprocess_stdout_tail": tail_text(stdout),
        "subprocess_stderr_tail": tail_text(stderr),
        "error": error,
    }



def run_one(
    repo_root: Path,
    bundle_dir: Path,
    category: str,
    instance: str,
    variant: str,
    seed: int,
    eval_budget: int,
    runtime_cap_seconds: float,
    flags: dict[str, str],
) -> dict[str, Any]:
    started = time.perf_counter()
    row: dict[str, Any] = {
        "commit_hash": git_output(repo_root, "rev-parse", "--short", "HEAD"),
        "category": category,
        "instance": instance,
        "variant": variant,
        "seed": int(seed),
        "eval_budget": int(eval_budget),
        "runtime_cap_seconds": float(runtime_cap_seconds),
        "B_battery_kwh": float(DEFAULT_PRICES.B_battery_kwh),
        "v_speed_ms": float(DEFAULT_PRICES.v_speed_ms),
        "carbon_price": float(DEFAULT_PRICES.carbon_price),
        "active_flags": json.dumps(flags, sort_keys=True),
    }
    try:
        policy = policy_for_variant(variant)
        with temporary_env(flags):
            result = run_alns_wouda(
                bundle_dir,
                iterations=None,
                seed=seed,
                eval_budget=eval_budget,
                max_runtime_seconds=runtime_cap_seconds,
                policy=policy,
                prices=DEFAULT_PRICES,
            )
        bundle = load_search_bundle(bundle_dir)
        solution = result.best_solution
        metrics = evaluate(solution, bundle.instance, bundle.carbon_profile, DEFAULT_PRICES)
        violations = check_solution(solution, bundle.instance, DEFAULT_PRICES)
        route_count = len(solution.routes)
        cv_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "cv")
        ev_count = sum(1 for route in solution.routes if route.vehicle_type.lower() == "ev")
        row.update(
            {
                "status": "OK" if not violations else "VIOLATION",
                "elapsed_seconds": time.perf_counter() - started,
                "actual_evals": int(result.evaluations),
                "best_penalized_obj": float(result.best_obj),
                "solver_reported_feasible": bool(result.feasible),
                "violation_count": len(violations),
                "route_count": route_count,
                "cv_route_count": cv_count,
                "ev_route_count": ev_count,
                "composition": classify_composition(cv_count, ev_count),
                "ev_route_share": ev_count / route_count if route_count else 0.0,
                "cv_route_share": cv_count / route_count if route_count else 0.0,
                "total_cost": float(metrics["total_cost"]),
                "cost_fix": float(metrics["cost_fix"]),
                "cost_km": float(metrics["cost_km"]),
                "cost_fuel": float(metrics["cost_fuel"]),
                "cost_elec": float(metrics["cost_elec"]),
                "cost_occ": float(metrics["cost_occ"]),
                "cost_carbon": float(metrics["cost_carbon"]),
                "E_total": float(metrics["E_total"]),
                "E_cv_direct": float(metrics["E_cv_direct"]),
                "E_ev_indirect": float(metrics["E_ev_indirect"]),
                "fuel_liters": float(metrics["fuel_liters"]),
                "ev_drive_kwh": float(metrics["ev_drive_kwh"]),
                "depot_charging_kwh": float(metrics["depot_charging_kwh"]),
                "station_charging_kwh": float(metrics["station_charging_kwh"]),
            }
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics must preserve the failure row.
        row.update(
            {
                "status": "ERROR",
                "elapsed_seconds": time.perf_counter() - started,
                "actual_evals": 0,
                "violation_count": -1,
                "route_count": 0,
                "cv_route_count": 0,
                "ev_route_count": 0,
                "composition": "error",
                "total_cost": float("inf"),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
    return row


def policy_for_variant(variant: str) -> SearchPolicy:
    if variant == "free_mixed":
        return SearchPolicy(require_charging_signal=False)
    if variant == "cv_shell":
        return SearchPolicy(require_charging_signal=False, max_ev=0)
    if variant == "ev_shell":
        return SearchPolicy(require_charging_signal=False, max_cv=0)
    raise ValueError(f"unknown variant: {variant}")


def winner_rows_from_raw(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["category"]), str(row["instance"]), int(row["seed"])), []).append(row)
    winners = []
    for key, candidates in sorted(grouped.items()):
        feasible = [row for row in candidates if row.get("status") == "OK" and int(row.get("violation_count", 999)) == 0]
        if not feasible:
            category, instance, seed = key
            winners.append({"category": category, "instance": instance, "seed": seed, "winner_status": "NO_FEASIBLE_ROW"})
            continue
        best = min(feasible, key=lambda row: float(row["total_cost"]))
        category, instance, seed = key
        winner = {
            "category": category,
            "instance": instance,
            "seed": seed,
            "winner_status": "OK",
            "winner_variant": best["variant"],
            "winner_total_cost": float(best["total_cost"]),
            "winner_composition": best["composition"],
            "winner_route_count": int(best["route_count"]),
            "winner_cv_route_count": int(best["cv_route_count"]),
            "winner_ev_route_count": int(best["ev_route_count"]),
            "winner_ev_route_share": float(best["ev_route_share"]),
        }
        for row in feasible:
            prefix = str(row["variant"])
            winner[f"{prefix}_cost"] = float(row["total_cost"])
            winner[f"{prefix}_composition"] = row["composition"]
            winner[f"{prefix}_cv_routes"] = int(row["cv_route_count"])
            winner[f"{prefix}_ev_routes"] = int(row["ev_route_count"])
        winners.append(winner)
    return winners


def summary_rows_from_winners(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["category"]), str(row["instance"])), []).append(row)
    out = []
    for (category, instance), winners in sorted(grouped.items()):
        ok = [row for row in winners if row.get("winner_status") == "OK"]
        counts: dict[str, int] = {}
        for row in ok:
            counts[str(row["winner_composition"])] = counts.get(str(row["winner_composition"]), 0) + 1
        out.append(
            {
                "category": category,
                "instance": instance,
                "seed_count": len(winners),
                "ok_seed_count": len(ok),
                "all_ev_winner_count": counts.get("all_ev", 0),
                "ev_heavy_winner_count": counts.get("ev_heavy_mixed", 0),
                "balanced_winner_count": counts.get("balanced_mixed", 0),
                "cv_heavy_winner_count": counts.get("cv_heavy_mixed", 0),
                "all_cv_winner_count": counts.get("all_cv", 0),
                "mean_winner_cost": mean(float(row["winner_total_cost"]) for row in ok) if ok else "",
                "mean_winner_ev_share": mean(float(row["winner_ev_route_share"]) for row in ok) if ok else "",
            }
        )
    return out


def summarize_conclusion(
    metadata: dict[str, Any],
    phase0_rows: list[dict[str, Any]],
    raw_rows: list[dict[str, Any]],
    winner_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    audit_ok = all(bool(row["exists"]) and bool(row["instance_json_exists"]) for row in phase0_rows)
    ok_winners = [row for row in winner_rows if row.get("winner_status") == "OK"]
    failed_runs = [row for row in raw_rows if row.get("status") not in {"OK", "VIOLATION"}]
    if not audit_ok or failed_runs or (raw_rows and not ok_winners):
        verdict = "HALT_COLLECTION_COST"
    elif not raw_rows:
        verdict = "PHASE0_ONLY"
    else:
        total = len(ok_winners)
        all_ev = sum(1 for row in ok_winners if row.get("winner_composition") == "all_ev")
        ev_heavy = sum(1 for row in ok_winners if row.get("winner_composition") == "ev_heavy_mixed")
        balanced = sum(1 for row in ok_winners if row.get("winner_composition") == "balanced_mixed")
        all_cv = sum(1 for row in ok_winners if row.get("winner_composition") == "all_cv")
        if total and all_ev / total >= 0.50:
            verdict = "HALT_ALL_EV"
        elif total and (all_ev + ev_heavy) / total >= 0.50:
            verdict = "HALT_EV_DOMINANT"
        elif total and balanced / total >= 0.50 and all_ev == 0:
            verdict = "PASS_TRUE_MIXED"
        elif total and all_cv / total >= 0.50:
            verdict = "HALT_ALL_CV"
        else:
            verdict = "PROVISIONAL_MIXED_UNRESOLVED"
    seeds = list(metadata.get("seeds", []))
    eval_budget = int(metadata.get("eval_budget", 0))
    evidence_strength = "formal_ready" if len(seeds) >= 3 and eval_budget >= 16000 else "staged_probe"
    return {
        "verdict": verdict,
        "evidence_strength": evidence_strength,
        "raw_run_count": len(raw_rows),
        "winner_count": len(ok_winners),
        "failed_run_count": len(failed_runs),
        "all_ev_winner_count": sum(1 for row in ok_winners if row.get("winner_composition") == "all_ev"),
        "ev_heavy_winner_count": sum(1 for row in ok_winners if row.get("winner_composition") == "ev_heavy_mixed"),
        "balanced_winner_count": sum(1 for row in ok_winners if row.get("winner_composition") == "balanced_mixed"),
        "cv_heavy_winner_count": sum(1 for row in ok_winners if row.get("winner_composition") == "cv_heavy_mixed"),
        "all_cv_winner_count": sum(1 for row in ok_winners if row.get("winner_composition") == "all_cv"),
        "interpretation": interpretation_for(verdict, evidence_strength),
    }


def interpretation_for(verdict: str, evidence_strength: str) -> str:
    if verdict == "HALT_ALL_EV":
        return "Do not claim a true mixed-fleet optimum; the winner set is mostly all-EV under this gate."
    if verdict == "HALT_EV_DOMINANT":
        return "280kWh fixes all-CV pressure but the current winner set is EV-dominant; report composition before broad reruns."
    if verdict == "PASS_TRUE_MIXED":
        suffix = " Still rerun with formal budgets before paper tables." if evidence_strength != "formal_ready" else ""
        return "The gate supports true mixed-fleet wording at the tested scope." + suffix
    if verdict == "PHASE0_ONLY":
        return "Only input auditable state was checked; no optimization rows were run."
    if verdict == "HALT_COLLECTION_COST":
        return "The gate did not collect a complete auditable optimization set."
    return "The tested scope is not enough to decide true mixed versus EV-dominant behavior."


def render_report(
    metadata: dict[str, Any],
    phase0_rows: list[dict[str, Any]],
    raw_rows: list[dict[str, Any]],
    winner_rows: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
    conclusion: dict[str, Any],
) -> str:
    lines = [
        "# 280kWh Fleet-Composition Gate",
        "",
        f"Commit: `{metadata['commit_hash'][:8]}`.",
        f"Python: `{metadata['python']}`; NumPy: `{metadata['numpy']}`.",
        f"Prices: `B_battery_kwh={metadata['B_battery_kwh']}`, `v_speed_ms={metadata['v_speed_ms']}`, `carbon_price={metadata['carbon_price']}`.",
        f"Command: `{metadata['command']}`.",
        "",
        "## Verdict",
        "",
        f"`{conclusion['verdict']}` (`{conclusion['evidence_strength']}`).",
        "",
        conclusion["interpretation"],
        "",
        "This gate is about route-type composition after the 280kWh update. It does not change model parameters or solver semantics.",
        "",
        "## Scope",
        "",
        f"- Instances audited: {len(phase0_rows)}.",
        f"- Raw optimization rows: {len(raw_rows)}.",
        f"- Winner rows: {len(winner_rows)}.",
        f"- Seeds: {', '.join(str(seed) for seed in metadata['seeds'])}.",
        f"- Eval budget per run: {metadata['eval_budget']}.",
        "",
        "Variant labels are search-shell settings only. The composition columns below are based on actual returned `cv_route_count` and `ev_route_count` after independent `evaluate/check` replay.",
        "",
    ]
    if summary_rows:
        lines.extend(["## Instance Summary", ""])
        lines.append("| instance | ok seeds | all-EV | EV-heavy | balanced | CV-heavy | all-CV | mean EV share |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for row in summary_rows:
            mean_ev = row["mean_winner_ev_share"]
            mean_ev_text = f"{float(mean_ev):.3f}" if mean_ev != "" else ""
            lines.append(
                f"| {row['category']}/{row['instance']} | {row['ok_seed_count']} | {row['all_ev_winner_count']} | "
                f"{row['ev_heavy_winner_count']} | {row['balanced_winner_count']} | {row['cv_heavy_winner_count']} | "
                f"{row['all_cv_winner_count']} | {mean_ev_text} |"
            )
        lines.append("")
    if winner_rows:
        lines.extend(["## Winner Rows", ""])
        lines.append("| instance | seed | winner | composition | CV | EV | cost |")
        lines.append("|---|---:|---|---|---:|---:|---:|")
        for row in winner_rows:
            if row.get("winner_status") != "OK":
                lines.append(f"| {row['category']}/{row['instance']} | {row['seed']} | HALT | {row['winner_status']} |  |  |  |")
            else:
                lines.append(
                    f"| {row['category']}/{row['instance']} | {row['seed']} | {row['winner_variant']} | {row['winner_composition']} | "
                    f"{row['winner_cv_route_count']} | {row['winner_ev_route_count']} | {float(row['winner_total_cost']):.3f} |"
                )
        lines.append("")
    lines.extend(
        [
            "## Output Files",
            "",
            "- `baselines/e2_alns/280kwh_fleet_composition_gate_data/metadata.json`",
            "- `baselines/e2_alns/280kwh_fleet_composition_gate_data/phase0_instance_audit.csv`",
            "- `baselines/e2_alns/280kwh_fleet_composition_gate_data/raw_runs.csv`",
            "- `baselines/e2_alns/280kwh_fleet_composition_gate_data/winners.csv`",
            "- `baselines/e2_alns/280kwh_fleet_composition_gate_data/composition_summary.csv`",
            "- `baselines/e2_alns/280kwh_fleet_composition_gate_data/conclusion.json`",
            "",
            "## Next Decision Rule",
            "",
            "If this gate remains `HALT_ALL_EV` or `HALT_EV_DOMINANT` under stronger budgets, the paper should not frame 280kWh as universally producing a balanced mixed fleet. The honest fallback is to report that modern-battery regional instances become EV-dominant, then decide whether a smaller evidence-bound battery scenario is needed for a balanced-mix narrative.",
            "",
        ]
    )
    return "\n".join(lines)


def classify_composition(cv_count: int, ev_count: int) -> str:
    total = int(cv_count) + int(ev_count)
    if total == 0:
        return "empty"
    if ev_count == 0:
        return "all_cv"
    if cv_count == 0:
        return "all_ev"
    ev_share = ev_count / total
    cv_share = cv_count / total
    if ev_share >= 0.80:
        return "ev_heavy_mixed"
    if cv_share >= 0.80:
        return "cv_heavy_mixed"
    return "balanced_mixed"


def customer_count(instance: str) -> int:
    match = re.search(r"-(\d+)c-", instance)
    return int(match.group(1)) if match else 0


def runtime_cap(instance: str, args: argparse.Namespace) -> float:
    n = customer_count(instance)
    if n >= 150:
        return float(args.runtime_cap_large)
    if n >= 100:
        return float(args.runtime_cap_medium)
    return float(args.runtime_cap_small)


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else float("nan")


@contextmanager
def temporary_env(flags: dict[str, str]):
    old = {key: os.environ.get(key) for key in flags}
    try:
        for key, value in flags.items():
            os.environ[key] = str(value)
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(value) for key, value in row.items()})


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def csv_value(value: Any) -> Any:
    if isinstance(value, float):
        if value == float("inf"):
            return "inf"
        if value == float("-inf"):
            return "-inf"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def tail_text(value: str | bytes | None, limit: int = 1000) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    return text[-int(limit) :]


def git_output(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=repo_root, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
