"""Autopsy the unstable default selector on one hard current-v3 instance."""

from __future__ import annotations

import argparse
import copy
from collections import Counter, defaultdict
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO_ROOT / "solver/src"
for _path in (REPO_ROOT, SOLVER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from baselines.e2_alns.m1_joint_repack_fleet_headroom import _cv_start, _sha256, _write_csv, evidence_files
from setp_solver.algorithms.resetp_alns.kernel.winner import (
    SOFTMAX_SELECTOR_FLAG,
    TRACE_DIAGNOSTIC_FLAG,
    WinnerKernelConfig,
    _run_winner_kernel_loop,
    e2_alns_throughput_flags,
)
from setp_solver.check import check_solution
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.evaluation import EvaluationContext, model_cost
from setp_solver.search.instance_registry import assert_formal_benchmark_ready, instance_abs_dir


DEFAULT_OUTPUT_DIR = Path("baselines/e2_alns/m1_dominant_pair_autopsy_20260710")
INSTANCE = "L-main-threeshift-100c-01"


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo_root, check=True, capture_output=True, text=True).stdout.strip()


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    assert_formal_benchmark_ready(repo_root)
    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(args.battery_kwh))
    bundle = load_search_bundle(instance_abs_dir(repo_root, INSTANCE))
    start = _cv_start(bundle, prices)
    flags = e2_alns_throughput_flags()
    flags["SETP_ALNS_CRUSH_LOCAL_SEARCH"] = "0"
    flags[TRACE_DIAGNOSTIC_FLAG] = "1"
    flags[SOFTMAX_SELECTOR_FLAG] = "0"

    raw_rows: list[dict[str, Any]] = []
    trace_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    timing_rows: list[dict[str, Any]] = []
    for seed in [int(value) for value in str(args.seeds).split(",") if value.strip()]:
        started = time.perf_counter()
        run = _run_winner_kernel_loop(
            copy.deepcopy(start),
            bundle.instance,
            bundle.carbon_profile,
            config=WinnerKernelConfig(seed=seed, eval_budget=int(args.eval_budget), max_runtime_seconds=float(args.max_runtime_seconds)),
            prices=prices,
            variant_flags=flags,
        )
        elapsed = time.perf_counter() - started
        rows = list(run.operator_counts.get("candidate_trace", []))
        for row in rows:
            trace_rows.append({"seed": seed, **row})
        selected: Counter[tuple[str, str]] = Counter()
        changed: Counter[tuple[str, str]] = Counter()
        feasible: Counter[tuple[str, str]] = Counter()
        accepted: Counter[tuple[str, str]] = Counter()
        best: Counter[tuple[str, str]] = Counter()
        first_eval: dict[tuple[str, str], int] = {}
        best_gain: defaultdict[tuple[str, str], float] = defaultdict(float)
        for row in rows:
            pair = (str(row.get("destroy_id", "")), str(row.get("repair_id", "")))
            selected[pair] += 1
            first_eval.setdefault(pair, int(row.get("eval", 0)))
            changed[pair] += int(bool(row.get("changed")))
            feasible[pair] += int(int(row.get("hard_violation_count", 0)) == 0 and bool(row.get("changed")))
            accepted[pair] += int(bool(row.get("accepted")))
            best[pair] += int(bool(row.get("best_improved")))
            if bool(row.get("best_improved")):
                best_gain[pair] += max(0.0, float(row.get("previous_best_obj", 0.0)) - float(row.get("outcome_candidate_obj", 0.0)))
        for pair, attempts in selected.most_common():
            pair_rows.append(
                {
                    "seed": seed,
                    "destroy_id": pair[0],
                    "repair_id": pair[1],
                    "attempts": attempts,
                    "share": attempts / max(1, len(rows)),
                    "first_eval": first_eval[pair],
                    "changed": changed[pair],
                    "feasible_changed": feasible[pair],
                    "accepted": accepted[pair],
                    "best_improved": best[pair],
                    "total_best_gain": best_gain[pair],
                }
            )
        for label, values in dict(run.operator_counts.get("timing", {})).items():
            timing_rows.append({"seed": seed, "label": label, **values})
        context = EvaluationContext(bundle.instance, bundle.carbon_profile, prices=prices)
        violations = check_solution(run.best_solution, bundle.instance, prices)
        raw_rows.append(
            {
                "seed": seed,
                "actual_evaluations": int(run.evaluations),
                "elapsed_seconds": elapsed,
                "best_cost": float(model_cost(run.best_solution, context)),
                "best_routes": len(run.best_solution.routes),
                "best_ev_routes": sum(route.vehicle_type.lower() == "ev" for route in run.best_solution.routes),
                "violation_count": len(violations),
                "trace_rows": len(rows),
                "pair_count": len(selected),
                "dominant_pair_share": selected.most_common(1)[0][1] / max(1, len(rows)),
            }
        )
        _write_csv(output_dir / "raw_runs.csv", raw_rows)
        _write_csv(output_dir / "candidate_trace.csv", trace_rows)
        _write_csv(output_dir / "pair_summary.csv", pair_rows)
        _write_csv(output_dir / "timing.csv", timing_rows)

    decision = {
        "schema_version": "setp-m1-dominant-pair-autopsy.v1",
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "instance": INSTANCE,
        "seed_count": len(raw_rows),
        "exact_budget": all(row["actual_evaluations"] == int(args.eval_budget) for row in raw_rows),
        "all_feasible": all(row["violation_count"] == 0 for row in raw_rows),
    }
    metadata = {
        **decision,
        "repo_commit": _git(repo_root, "rev-parse", "HEAD"),
        "repo_dirty_at_run": bool(_git(repo_root, "status", "--porcelain")),
        "battery_kwh": float(args.battery_kwh),
        "eval_budget": int(args.eval_budget),
        "seeds": [int(value) for value in str(args.seeds).split(",") if value.strip()],
    }
    (output_dir / "decision.json").write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "report.md").write_text(
        "# M1 dominant-pair autopsy\n\n"
        "Diagnostic-only replay of the default selector on the current-v3 221-customer instance. "
        "Every complete candidate is charged to the 400-evaluation budget; local search is disabled.\n",
        encoding="utf-8",
    )
    sources = [Path(__file__).resolve(), repo_root / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py"]
    hashes = {str(path.relative_to(repo_root)): _sha256(path) for path in [*evidence_files(output_dir), *sources]}
    (output_dir / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--eval-budget", type=int, default=400)
    parser.add_argument("--max-runtime-seconds", type=float, default=180.0)
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    args = parser.parse_args()
    print(json.dumps(run_probe(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
