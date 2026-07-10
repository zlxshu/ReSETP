"""Three-scale gate for the bounded-reward chain-continuity selector."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys
from dataclasses import replace


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO_ROOT / "solver/src"
for _path in (REPO_ROOT, SOLVER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from baselines.e2_alns.m1_fair_selector_probe import INSTANCES, _run_alns, _run_lns
from baselines.e2_alns.m1_joint_repack_fleet_headroom import _cv_start, _sha256, _write_csv, evidence_files
from setp_solver.prices import DEFAULT_PRICES
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.instance_registry import assert_formal_benchmark_ready, instance_abs_dir


DEFAULT_OUTPUT_DIR = Path("baselines/e2_alns/m1_chain_selector_20260710")
LNS_REFERENCE = Path("baselines/e2_alns/m1_fair_selector_20260710/raw_runs.csv")


def classify(rows: list[dict[str, object]]) -> str:
    if not rows or not all(bool(row["clean"]) for row in rows):
        return "CHAIN_UCB_400_NOT_SUPPORTED"
    wins = sum(float(row["gain_vs_lns_pct"]) >= 5.0 for row in rows)
    mean_gain = sum(float(row["gain_vs_lns_pct"]) for row in rows) / len(rows)
    mean_time = sum(float(row["runtime_delta_vs_lns"]) for row in rows) / len(rows)
    if wins >= math.ceil(2.0 * len(rows) / 3.0) and mean_gain >= 5.0 and mean_time < 0:
        return "CHAIN_UCB_400_SUPPORTED"
    return "CHAIN_UCB_400_NOT_SUPPORTED"


def run_probe(args: argparse.Namespace) -> dict[str, object]:
    repo_root = Path(args.repo_root).resolve()
    assert_formal_benchmark_ready(repo_root)
    output_dir = repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    prices = replace(DEFAULT_PRICES, B_battery_kwh=float(args.battery_kwh))
    seeds = [int(value) for value in str(args.seeds).split(",") if value.strip()]
    scales = {value.strip() for value in str(args.scales).split(",") if value.strip()}
    with (repo_root / args.lns_reference).open(newline="", encoding="utf-8") as handle:
        lns = {
            (str(row["scale"]), int(row["seed"])): row
            for row in csv.DictReader(handle)
            if row["algorithm"] == "LNS"
        }
    selected_instances = (
        ((str(args.instance_scale), str(args.instance)),)
        if str(args.instance).strip()
        else INSTANCES
    )
    raw_rows: list[dict[str, object]] = []
    fresh_lns_rows: list[dict[str, object]] = []
    comparisons: list[dict[str, object]] = []
    for scale, instance_name in selected_instances:
        if not str(args.instance).strip() and scale not in scales:
            continue
        bundle = load_search_bundle(instance_abs_dir(repo_root, instance_name))
        start = _cv_start(bundle, prices)
        for seed in seeds:
            row, _solution = _run_alns(
                bundle,
                prices,
                start,
                "CHAIN_UCB",
                seed,
                int(args.eval_budget),
                float(args.max_runtime_seconds),
            )
            row.update({"scale": scale, "instance": instance_name})
            raw_rows.append(row)
            if bool(args.fresh_lns) or (scale, seed) not in lns:
                baseline, _baseline_solution = _run_lns(
                    bundle,
                    prices,
                    start,
                    seed,
                    int(args.eval_budget),
                    float(args.max_runtime_seconds),
                )
                baseline.update({"scale": scale, "instance": instance_name})
                fresh_lns_rows.append(baseline)
                _write_csv(output_dir / "lns_runs.csv", fresh_lns_rows)
            else:
                baseline = lns[(scale, seed)]
            gain = (float(baseline["best_cost"]) - float(row["best_cost"])) / float(baseline["best_cost"]) * 100.0
            comparisons.append(
                {
                    "scale": scale,
                    "seed": seed,
                    "chain_cost": row["best_cost"],
                    "lns_cost": float(baseline["best_cost"]),
                    "gain_vs_lns_pct": gain,
                    "chain_seconds": row["elapsed_seconds"],
                    "lns_seconds": float(baseline["elapsed_seconds"]),
                    "runtime_delta_vs_lns": float(row["elapsed_seconds"]) - float(baseline["elapsed_seconds"]),
                    "clean": bool(row["feasible"]) and int(row["actual_evaluations"]) == int(args.eval_budget),
                }
            )
            _write_csv(output_dir / "raw_runs.csv", raw_rows)
            _write_csv(output_dir / "comparisons.csv", comparisons)
    verdict = classify(comparisons)
    decision = {
        "schema_version": "setp-m1-chain-selector.v1",
        "verdict": verdict,
        "diagnostic_only": True,
        "formal_t3": False,
        "algorithm_win_loss_claim": False,
        "comparison_count": len(comparisons),
        "five_percent_wins": sum(float(row["gain_vs_lns_pct"]) >= 5.0 for row in comparisons),
        "mean_gain_vs_lns_pct": sum(float(row["gain_vs_lns_pct"]) for row in comparisons) / len(comparisons),
        "runtime_wins": sum(float(row["runtime_delta_vs_lns"]) < 0 for row in comparisons),
        "mean_runtime_delta_vs_lns": sum(float(row["runtime_delta_vs_lns"]) for row in comparisons) / len(comparisons),
    }
    (output_dir / "decision.json").write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "metadata.json").write_text(
        json.dumps({**decision, "lns_reference": str(args.lns_reference), "fresh_lns": bool(args.fresh_lns), "eval_budget": int(args.eval_budget), "seeds": seeds, "scales": sorted(scales), "instance": str(args.instance)}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(
        f"# M1 chain selector probe\n\nVerdict: `{verdict}`. This reuses the same-start LNS rows only as a quick gate; it is not a formal same-commit benchmark.\n",
        encoding="utf-8",
    )
    sources = [Path(__file__).resolve(), repo_root / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py"]
    hashes = {str(path.relative_to(repo_root)): _sha256(path) for path in [*evidence_files(output_dir), *sources] if path.is_file()}
    (output_dir / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--lns-reference", type=Path, default=LNS_REFERENCE)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--eval-budget", type=int, default=400)
    parser.add_argument("--max-runtime-seconds", type=float, default=180.0)
    parser.add_argument("--battery-kwh", type=float, default=280.0)
    parser.add_argument("--scales", default="small,medium,large")
    parser.add_argument("--instance", default="")
    parser.add_argument("--instance-scale", default="hardest")
    parser.add_argument("--fresh-lns", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_probe(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
