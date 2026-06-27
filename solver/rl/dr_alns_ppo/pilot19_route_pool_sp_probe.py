from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from setp_solver.check import check_solution
from setp_solver.cost import evaluate
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.construction import build_initial_solution
from setp_solver.search.evaluation import EvalBudget, EvaluationContext, score_reference
from setp_solver.search.route_pool_sp import (
    RebuildResult,
    RoutePoolBuildResult,
    SpSolveResult,
    build_route_pool,
    rebuild_solution_from_entries,
    solve_route_pool_sp,
)
from setp_solver.search.winner_operators import WinnerOperatorAction, WinnerOperatorSet, apply_winner_action

from .schemas import BlockDecodedAction
from .solution_json import solution_from_json, solution_to_json
from .worker_client import WorkerClient


PILOT19_DIR = Path("solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot19")
ALLSCALE_MANIFEST = Path(
    "solver/reports/dr_alns_ppo_v3_block_dr_alns/async_pilot/pilot14b/training_manifest_three_shift_allscale.json"
)
DEFAULT_WORKER = r"C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe"
REQUIRED_NUMPY = "2.3.5"
BEST_STATIC_META = (0.40, 0.0025, 0.15)
DEFAULT_SCALES = (50, 75, 100)
ALL_SCALES = (50, 75, 100, 150, 200)
DEFAULT_SEEDS = tuple(range(1, 13))

SCALE_FIELDS = [
    "scale",
    "bundle",
    "bundle_id",
    "seed_count",
    "best_single",
    "best_single_seed",
    "mean_single",
    "sp_cost",
    "headroom_sp_pct",
    "verdict",
    "sp_feasible",
    "sp_violation_count",
    "milp_status",
    "milp_success",
    "milp_gap",
    "milp_runtime_seconds",
    "milp_fallback_used",
    "selected_route_count",
    "pool_entry_count",
    "pool_raw_entry_count",
    "pool_fallback_added_count",
    "pool_fallback_failed_customers",
    "extra_harvest_solution_count",
    "station_capacity_constraint_count",
    "cover_constraint_count",
    "runtime_seconds",
    "worker_python",
    "worker_numpy",
]

POOL_FIELDS = [
    "scale",
    "bundle_id",
    "raw_entry_count",
    "dedup_entry_count",
    "alternate_entry_count",
    "duplicate_signature_count",
    "skipped_empty_route_count",
    "fallback_added_count",
    "extra_harvest_solution_count",
    "fallback_failed_customer_count",
    "fallback_failed_customers",
]

RUN_FIELDS = [
    "scale",
    "bundle_id",
    "seed",
    "best_obj",
    "actual_evals",
    "feasible",
    "violation_count",
    "elapsed_seconds",
    "wall_clock_capped",
    "harvested_solution_count",
    "worker_python_executable",
    "worker_numpy_version",
]


def run_all(args: argparse.Namespace) -> dict[str, Any]:
    ensure_environment()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    bundles = select_bundles(load_allscale_bundles(args.manifest), args.scales)

    scale_rows = load_csv_rows(output_dir / "pilot19_scale_rows.csv") if args.resume else []
    pool_rows = load_csv_rows(output_dir / "pilot19_pool_stats.csv") if args.resume else []
    run_rows = load_csv_rows(output_dir / "pilot19_winner_run_rows.csv") if args.resume else []
    completed_scales = {int(row["scale"]) for row in scale_rows if str(row.get("status", "")) != "HALT_RUN"}

    for bundle in bundles:
        scale = scale_from_bundle(bundle)
        if args.resume and scale in completed_scales:
            continue
        scale_started = time.perf_counter()
        result = run_scale(bundle, args)
        result["scale_row"]["runtime_seconds"] = time.perf_counter() - scale_started
        scale_rows = [row for row in scale_rows if int(row.get("scale", -1)) != scale]
        pool_rows = [row for row in pool_rows if int(row.get("scale", -1)) != scale]
        run_rows = [row for row in run_rows if int(row.get("scale", -1)) != scale]
        scale_rows.append(result["scale_row"])
        pool_rows.append(result["pool_row"])
        run_rows.extend(result["run_rows"])
        write_csv(output_dir / "pilot19_scale_rows.csv", sorted(scale_rows, key=lambda row: int(row["scale"])), SCALE_FIELDS)
        write_csv(output_dir / "pilot19_pool_stats.csv", sorted(pool_rows, key=lambda row: int(row["scale"])), POOL_FIELDS)
        write_csv(output_dir / "pilot19_winner_run_rows.csv", sorted(run_rows, key=lambda row: (int(row["scale"]), int(row["seed"]))), RUN_FIELDS)
        solution_path = output_dir / f"pilot19_best_solution_{Path(bundle).name}.json"
        write_json(solution_path, result["solution_json"])

    scale_rows = sorted(load_csv_rows(output_dir / "pilot19_scale_rows.csv"), key=lambda row: int(row["scale"]))
    summary = {
        "schema_version": "resetp-pilot19-route-pool-sp.v1",
        "status": overall_verdict(scale_rows),
        "scales": [int(row["scale"]) for row in scale_rows],
        "seeds": list(args.seeds),
        "eval_budget": int(args.eval_budget),
        "block_size": int(args.block_size),
        "best_static_meta": {
            "q_ratio": BEST_STATIC_META[0],
            "threshold_ratio": BEST_STATIC_META[1],
            "exploration_ratio": BEST_STATIC_META[2],
        },
        "worker_python": DEFAULT_WORKER,
        "required_numpy": REQUIRED_NUMPY,
        "scale_rows": scale_rows,
        "same_machine_note": "All values are x86 same-machine relative measurements; no M1 absolute-number comparison is made.",
        "training_note": "Pilot19 is post-processing only. It does not train PPO or change cost/check/evaluation/winner semantics.",
    }
    write_json(output_dir / "pilot19_route_pool_sp_report.json", summary)
    write_text(output_dir / "pilot19_route_pool_sp_report.md", report_markdown(summary))
    return summary


def run_scale(bundle: str, args: argparse.Namespace) -> dict[str, Any]:
    bundle_data = load_search_bundle(bundle)
    harvested: list[tuple[Any, str]] = []
    extra_harvested: list[tuple[Any, str]] = []
    run_rows: list[dict[str, Any]] = []
    for seed in args.seeds:
        row, solutions = run_static_meta_harvest(
            bundle,
            seed=int(seed),
            eval_budget=int(args.eval_budget),
            block_size=int(args.block_size),
            max_runtime_seconds=float(args.max_runtime_seconds),
        )
        run_rows.append(row)
        harvested.extend(solutions)
    pool = build_route_pool(harvested, bundle_data.instance, bundle_data.carbon_profile, DEFAULT_PRICES, include_fallback=True)
    min_pool_size = int(args.min_pool_factor * len([node for node in bundle_data.instance.nodes if node.node_type.lower() == "c"]))
    if len(pool.entries) < min_pool_size and args.extra_harvest_evals > 0:
        extra_harvested = run_lightweight_harvest(
            bundle_data,
            seeds=args.seeds,
            target_pool_size=min_pool_size,
            existing_solutions=harvested,
            eval_budget=int(args.extra_harvest_evals),
            max_runtime_seconds=float(args.extra_harvest_max_seconds),
        )
        if extra_harvested:
            pool = build_route_pool([*harvested, *extra_harvested], bundle_data.instance, bundle_data.carbon_profile, DEFAULT_PRICES, include_fallback=True)
    milp_time_limit = args.milp_time_limit if args.milp_time_limit is not None else (300.0 if scale_from_bundle(bundle) >= 150 else 180.0)
    sp = solve_route_pool_sp(pool.entries, bundle_data.instance, milp_time_limit_seconds=float(milp_time_limit))
    rebuild = rebuild_solution_from_entries(pool.entries, sp.selected_indices, bundle_data.instance, bundle_data.carbon_profile, DEFAULT_PRICES)

    feasible_runs = [row for row in run_rows if bool(row["feasible"]) and math.isfinite(float(row["best_obj"]))]
    if not feasible_runs:
        raise RuntimeError(f"HALT_PILOT19_NO_FEASIBLE_BASELINE: bundle={bundle}")
    best_row = min(feasible_runs, key=lambda row: float(row["best_obj"]))
    best_single = float(best_row["best_obj"])
    sp_cost = float(rebuild.metrics["total_cost"]) if rebuild.feasible else math.inf
    headroom = (best_single - sp_cost) / best_single * 100.0 if rebuild.feasible and abs(best_single) > 1e-12 else math.nan
    verdict = classify_scale(headroom, rebuild)
    return {
        "scale_row": scale_row(bundle, run_rows, pool, sp, rebuild, best_single, int(best_row["seed"]), headroom, verdict, len(extra_harvested)),
        "pool_row": pool_row(bundle, pool, len(extra_harvested)),
        "run_rows": run_rows,
        "solution_json": {
            "bundle": bundle,
            "scale": scale_from_bundle(bundle),
            "status": verdict,
            "metrics": rebuild.metrics,
            "violations": [violation_to_dict(item) for item in rebuild.violations],
            "selected_entry_ids": list(rebuild.selected_entry_ids),
            "solution": solution_to_json(rebuild.solution),
        },
    }


def run_lightweight_harvest(
    bundle_data: Any,
    *,
    seeds: tuple[int, ...],
    target_pool_size: int,
    existing_solutions: list[tuple[Any, str]],
    eval_budget: int,
    max_runtime_seconds: float,
) -> list[tuple[Any, str]]:
    """Use public winner operators to collect candidate routes when the pool is thin."""

    started = time.perf_counter()
    harvested: list[tuple[Any, str]] = []
    pool = build_route_pool(existing_solutions, bundle_data.instance, bundle_data.carbon_profile, DEFAULT_PRICES, include_fallback=True)
    if len(pool.entries) >= int(target_pool_size):
        return harvested
    operator_set = WinnerOperatorSet.create()
    q_values = (0.10, 0.16, 0.23, 0.30, 0.40)
    for seed in seeds:
        if time.perf_counter() - started >= float(max_runtime_seconds):
            break
        rng = np.random.default_rng(int(seed) + 190_000)
        context = EvaluationContext(
            bundle_data.instance,
            bundle_data.carbon_profile,
            budget=EvalBudget(limit=int(eval_budget), target=int(eval_budget)),
            repair_delta_mode="fast",
        )
        current = build_initial_solution(
            bundle_data.instance,
            bundle_data.carbon_profile,
            introduce_ev=False,
            require_charging_signal=False,
        )
        current_obj = score_reference(current, context)
        while not context.budget.reached_target:
            if time.perf_counter() - started >= float(max_runtime_seconds):
                break
            destroy_idx = int(rng.integers(0, len(operator_set.destroy_ops)))
            repair_idx = int(rng.integers(0, len(operator_set.repair_ops)))
            q_idx = int(rng.integers(0, len(q_values)))
            action = WinnerOperatorAction(
                destroy_op_id=operator_set.destroy_ops[destroy_idx][0],
                repair_op_id=operator_set.repair_ops[repair_idx][0],
                remove_fraction=float(q_values[q_idx]),
                raw_action=(destroy_idx, repair_idx, q_idx, -1),
            )
            result = apply_winner_action(
                current,
                action,
                context,
                rng=rng,
                operator_set=operator_set,
                current_obj=current_obj,
                progress=min(1.0, float(context.budget.count) / max(1.0, float(eval_budget))),
            )
            candidate = result["candidate_solution"]
            candidate_obj = float(result["candidate_obj"])
            if int(result.get("hard_violation_count", 1)) == 0:
                harvested.append((candidate, f"extra_seed{seed}:eval{context.budget.count}"))
                if candidate_obj <= current_obj * (1.0 + BEST_STATIC_META[1]):
                    current = candidate
                    current_obj = candidate_obj
            if len(harvested) % 20 == 0 and harvested:
                pool = build_route_pool([*existing_solutions, *harvested], bundle_data.instance, bundle_data.carbon_profile, DEFAULT_PRICES, include_fallback=True)
                if len(pool.entries) >= int(target_pool_size):
                    return harvested
    return harvested


def run_static_meta_harvest(
    bundle: str,
    *,
    seed: int,
    eval_budget: int,
    block_size: int,
    max_runtime_seconds: float,
) -> tuple[dict[str, Any], list[tuple[Any, str]]]:
    started = time.perf_counter()
    client = WorkerClient(bundle, seed=int(seed), max_evals=int(eval_budget))
    harvested: list[tuple[Any, str]] = []
    last_response: dict[str, Any] | None = None
    capped = False
    try:
        reset = checked_response(client.reset())
        harvested.append((solution_from_json(reset.get("solution")), f"seed{seed}:reset"))
        last_response = reset
        while int(last_response.get("actual_evals", 0)) < int(eval_budget):
            if time.perf_counter() - started >= float(max_runtime_seconds):
                capped = True
                break
            response = checked_response(
                client.block_step(
                    BlockDecodedAction(
                        destroy_id="alpha_ucb",
                        repair_id="alpha_ucb",
                        q_ratio=BEST_STATIC_META[0],
                        threshold_ratio=BEST_STATIC_META[1],
                        exploration_ratio=BEST_STATIC_META[2],
                        block_size=int(block_size),
                        raw=(0, 0, 0, 0, 0),
                        control_mode="block_ppo",
                        candidate_generator="default",
                        search_control="continue",
                    )
                )
            )
            last_response = response
            harvested.append((solution_from_json(response.get("solution")), f"seed{seed}:eval{response.get('actual_evals')}"))
        elapsed = time.perf_counter() - started
        trace = dict((last_response or {}).get("trace", {}) or {})
        row = {
            "scale": scale_from_bundle(bundle),
            "bundle_id": Path(bundle).name,
            "seed": int(seed),
            "best_obj": float((last_response or {}).get("best_obj", math.inf)),
            "actual_evals": int((last_response or {}).get("actual_evals", 0)),
            "feasible": int((last_response or {}).get("violation_count", 1)) == 0,
            "violation_count": int((last_response or {}).get("violation_count", 1)),
            "elapsed_seconds": float(elapsed),
            "wall_clock_capped": int(bool(capped)),
            "harvested_solution_count": len(harvested),
            "worker_python_executable": str(trace.get("worker_python_executable", "")),
            "worker_numpy_version": str(trace.get("worker_numpy_version", "")),
        }
        return row, harvested
    finally:
        client.close()


def ensure_environment() -> None:
    if np.__version__ != REQUIRED_NUMPY:
        raise RuntimeError(f"HALT_ENV: runner NumPy must be {REQUIRED_NUMPY}, got {np.__version__}")
    worker = Path(DEFAULT_WORKER)
    if not worker.is_file():
        raise RuntimeError(f"HALT_ENV: missing worker interpreter {DEFAULT_WORKER}")
    os.environ["SETP_WORKER_PYTHON"] = DEFAULT_WORKER
    probe = subprocess.run(
        [DEFAULT_WORKER, "-c", "import numpy, scipy.optimize as opt; print(numpy.__version__); print(hasattr(opt, 'milp'))"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if probe.returncode != 0:
        raise RuntimeError(f"HALT_ENV: worker probe failed: {probe.stderr[-2000:]}")
    lines = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
    if lines[:2] != [REQUIRED_NUMPY, "True"]:
        raise RuntimeError(f"HALT_ENV: worker probe expected NumPy {REQUIRED_NUMPY} and milp=True, got {lines}")


def load_allscale_bundles(manifest_path: str | Path) -> list[str]:
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    bundles = [str(item) for item in payload.get("train", [])]
    if not bundles:
        raise RuntimeError(f"HALT_MANIFEST: no train bundles in {manifest_path}")
    missing = [bundle for bundle in bundles if not Path(bundle).is_dir()]
    if missing:
        raise FileNotFoundError(f"HALT_MANIFEST: missing bundles: {missing}")
    return sorted(bundles, key=lambda item: (scale_from_bundle(item), item))


def select_bundles(bundles: list[str], scales: tuple[int, ...]) -> list[str]:
    selected: list[str] = []
    for scale in scales:
        candidates = sorted(bundle for bundle in bundles if scale_from_bundle(bundle) == int(scale))
        preferred = [bundle for bundle in candidates if Path(bundle).name.endswith("-03")]
        if not preferred:
            raise RuntimeError(f"HALT_BUNDLE: no -03 representative for scale {scale}")
        selected.append(preferred[0])
    return selected


def scale_from_bundle(bundle: str | Path) -> int:
    match = re.search(r"(\d+)c", str(bundle))
    if not match:
        raise ValueError(f"cannot infer scale from bundle path: {bundle}")
    return int(match.group(1))


def checked_response(response: dict[str, Any]) -> dict[str, Any]:
    if not response.get("ok", False):
        raise RuntimeError(f"DR-ALNS worker error: {response}")
    return response


def classify_scale(headroom: float, rebuild: RebuildResult) -> str:
    if not rebuild.feasible:
        return "SP_RESULT_INFEASIBLE"
    if math.isfinite(headroom) and headroom >= 10.0:
        return "ROOM_CONFIRMED"
    if math.isfinite(headroom) and headroom >= 2.0:
        return "MODEST_ROOM"
    return "NO_ROOM_SP"


def overall_verdict(scale_rows: list[dict[str, Any]]) -> str:
    verdicts = {str(row.get("verdict")) for row in scale_rows}
    if "ROOM_CONFIRMED" in verdicts:
        return "ROOM_CONFIRMED"
    if "SP_RESULT_INFEASIBLE" in verdicts:
        return "SP_RESULT_INFEASIBLE"
    if "MODEST_ROOM" in verdicts:
        return "MODEST_ROOM"
    if verdicts:
        return "NO_ROOM_SP"
    return "NO_RESULT"


def scale_row(
    bundle: str,
    run_rows: list[dict[str, Any]],
    pool: RoutePoolBuildResult,
    sp: SpSolveResult,
    rebuild: RebuildResult,
    best_single: float,
    best_seed: int,
    headroom: float,
    verdict: str,
    extra_harvest_solution_count: int,
) -> dict[str, Any]:
    feasible_objs = [float(row["best_obj"]) for row in run_rows if bool(row["feasible"])]
    return {
        "scale": scale_from_bundle(bundle),
        "bundle": bundle,
        "bundle_id": Path(bundle).name,
        "seed_count": len(run_rows),
        "best_single": best_single,
        "best_single_seed": best_seed,
        "mean_single": float(sum(feasible_objs) / len(feasible_objs)) if feasible_objs else math.nan,
        "sp_cost": float(rebuild.metrics["total_cost"]) if rebuild.feasible else math.inf,
        "headroom_sp_pct": headroom,
        "verdict": verdict,
        "sp_feasible": int(rebuild.feasible),
        "sp_violation_count": len(rebuild.violations),
        "milp_status": sp.status,
        "milp_success": int(bool(sp.success)),
        "milp_gap": "" if sp.mip_gap is None else sp.mip_gap,
        "milp_runtime_seconds": sp.runtime_seconds,
        "milp_fallback_used": int(bool(sp.fallback_used)),
        "selected_route_count": len(sp.selected_indices),
        "pool_entry_count": len(pool.entries),
        "pool_raw_entry_count": pool.raw_entry_count,
        "pool_fallback_added_count": pool.fallback_added_count,
        "pool_fallback_failed_customers": ";".join(pool.fallback_failed_customers),
        "extra_harvest_solution_count": int(extra_harvest_solution_count),
        "station_capacity_constraint_count": sp.station_capacity_constraint_count,
        "cover_constraint_count": sp.cover_constraint_count,
        "runtime_seconds": 0.0,
        "worker_python": DEFAULT_WORKER,
        "worker_numpy": REQUIRED_NUMPY,
    }


def pool_row(bundle: str, pool: RoutePoolBuildResult, extra_harvest_solution_count: int) -> dict[str, Any]:
    alternate_count = sum(len(items) for items in pool.alternates.values())
    return {
        "scale": scale_from_bundle(bundle),
        "bundle_id": Path(bundle).name,
        "raw_entry_count": pool.raw_entry_count,
        "dedup_entry_count": len(pool.entries),
        "alternate_entry_count": alternate_count,
        "duplicate_signature_count": pool.duplicate_signature_count,
        "skipped_empty_route_count": pool.skipped_empty_route_count,
        "fallback_added_count": pool.fallback_added_count,
        "extra_harvest_solution_count": int(extra_harvest_solution_count),
        "fallback_failed_customer_count": len(pool.fallback_failed_customers),
        "fallback_failed_customers": ";".join(pool.fallback_failed_customers),
    }


def report_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Pilot19 Route Pool + Set-Partitioning Headroom Probe",
        "",
        f"Status: `{summary['status']}`.",
        f"Scales: `{summary['scales']}`; seeds: `{summary['seeds']}`.",
        f"Budget: eval_budget=`{summary['eval_budget']}`, block_size=`{summary['block_size']}`.",
        f"Worker: `{summary['worker_python']}`; NumPy: `{summary['required_numpy']}`.",
        "",
        "This is x86 same-machine relative evidence only. Pilot19 does not train PPO and does not change reward, cost, feasibility, evaluation, or winner semantics.",
        "",
        "## Verdict Rules",
        "",
        "`headroom_sp% >= 10` => `ROOM_CONFIRMED`; `2 <= headroom_sp% < 10` => `MODEST_ROOM`; all `< 2` => `NO_ROOM_SP`.",
        "",
        "## Scale Summary",
        "",
        "| scale | bundle | best single | SP cost | headroom % | pool | selected | MILP | feasible | verdict |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |",
    ]
    for row in summary.get("scale_rows", []):
        lines.append(
            f"| {row['scale']} | {row['bundle_id']} | {_fmt(row['best_single'])} | {_fmt(row['sp_cost'])} | "
            f"{_fmt(row['headroom_sp_pct'])} | {row['pool_entry_count']} | {row['selected_route_count']} | "
            f"`{row['milp_status']}` | {row['sp_feasible']} | `{row['verdict']}` |"
        )
    return "\n".join(lines) + "\n"


def violation_to_dict(violation: Any) -> dict[str, Any]:
    return {
        "type": getattr(violation, "type", ""),
        "vehicle_id": getattr(violation, "vehicle_id", ""),
        "location": getattr(violation, "location", ""),
        "detail": getattr(violation, "detail", str(violation)),
    }


def load_csv_rows(path: str | Path) -> list[dict[str, Any]]:
    value = Path(path)
    if not value.is_file():
        return []
    with value.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    value = Path(path)
    value.parent.mkdir(parents=True, exist_ok=True)
    with value.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key, "")) for key in fieldnames})


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    write_text(path, json.dumps(json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_text(path: str | Path, text: str) -> None:
    value = Path(path)
    value.parent.mkdir(parents=True, exist_ok=True)
    value.write_text(text, encoding="utf-8", newline="\n")


def csv_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    return value


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _fmt(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(numeric):
        return ""
    return f"{numeric:.3f}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pilot19 route-pool set-partitioning probe.")
    parser.add_argument("--manifest", default=str(ALLSCALE_MANIFEST))
    parser.add_argument("--output-dir", default=str(PILOT19_DIR))
    parser.add_argument("--scales", default=",".join(str(value) for value in DEFAULT_SCALES))
    parser.add_argument("--seeds", default=",".join(str(value) for value in DEFAULT_SEEDS))
    parser.add_argument("--eval-budget", type=int, default=20)
    parser.add_argument("--block-size", type=int, default=4)
    parser.add_argument("--max-runtime-seconds", type=float, default=1200.0)
    parser.add_argument("--milp-time-limit", type=float, default=None)
    parser.add_argument("--min-pool-factor", type=float, default=3.0)
    parser.add_argument("--extra-harvest-evals", type=int, default=80)
    parser.add_argument("--extra-harvest-max-seconds", type=float, default=300.0)
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    args = parser.parse_args(argv)
    args.scales = tuple(int(part) for part in str(args.scales).split(",") if part.strip())
    args.seeds = tuple(int(part) for part in str(args.seeds).split(",") if part.strip())
    invalid = [scale for scale in args.scales if scale not in ALL_SCALES]
    if invalid:
        raise ValueError(f"unsupported scales: {invalid}; allowed={ALL_SCALES}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = run_all(args)
    except Exception as exc:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "schema_version": "resetp-pilot19-route-pool-sp.v1",
            "status": "HALT_RUN",
            "reason": str(exc),
            "worker_python": DEFAULT_WORKER,
            "required_numpy": REQUIRED_NUMPY,
        }
        write_json(output_dir / "pilot19_route_pool_sp_report.json", summary)
        write_text(output_dir / "pilot19_route_pool_sp_report.md", f"# Pilot19 Route Pool + Set-Partitioning Headroom Probe\n\nStatus: `HALT_RUN`.\nReason: {exc}\n")
        print(f"PILOT19_ROUTE_POOL_SP_DONE status=HALT_RUN output={args.output_dir}")
        return 2
    print(f"PILOT19_ROUTE_POOL_SP_DONE status={summary['status']} output={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
