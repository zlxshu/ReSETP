#!/usr/bin/env python3
"""Create the paper-facing, scope-honest closeout for the completed E2 matrix."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import random
import statistics
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "solver/src", REPO_ROOT / "models/src", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from baselines.e2_alns import e2_final_closure as closure


DEFAULT_PHASE_DIR = REPO_ROOT / "baselines/e2_alns/e2_submission_20260711/carbon_280"
PRIMARY = "staged_hybrid_carbon_aware"
ABLATION = "staged_hybrid_carbon_naive"
BASELINES = ("LNS", "GA", "PSO", "VNS")
ALGORITHMS = (PRIMARY, ABLATION, *BASELINES)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _bootstrap_mean_ci(values: list[float], *, samples: int = 10_000, seed: int = 20260711) -> tuple[float, float]:
    if not values:
        return math.nan, math.nan
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choice(values) for _ in values) for _ in range(samples))
    return means[int(0.025 * samples)], means[min(samples - 1, int(0.975 * samples))]


def build_closeout(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    expected = 9 * 5 * len(ALGORITHMS)
    by_key = {(row["instance"], int(row["seed"]), row["algorithm"]): row for row in rows}
    keys = sorted({(row["instance"], int(row["seed"])) for row in rows})
    counts = {algorithm: sum(row["algorithm"] == algorithm for row in rows) for algorithm in ALGORITHMS}
    matrix_contract = (
        len(rows) == expected
        and len(by_key) == expected
        and all(counts[algorithm] == 45 for algorithm in ALGORITHMS)
        and all(row.get("gate_status") == "OK" for row in rows)
        and all(int(float(row.get("actual_evals", -1))) == 4000 for row in rows)
        and all(int(float(row.get("violation_count", -1))) == 0 for row in rows)
    )

    algorithm_summary: list[dict[str, Any]] = []
    totals: dict[str, float] = {}
    mean_ranks: dict[str, float] = {}
    best_counts = {algorithm: 0 for algorithm in (PRIMARY, *BASELINES)}
    rank_values = {algorithm: [] for algorithm in (PRIMARY, *BASELINES)}
    for key in keys:
        costs = {algorithm: float(by_key[key + (algorithm,)]["best_cost"]) for algorithm in (PRIMARY, *BASELINES)}
        minimum = min(costs.values())
        levels = sorted(set(costs.values()))
        for algorithm, cost in costs.items():
            if abs(cost - minimum) <= 1e-8:
                best_counts[algorithm] += 1
            rank_values[algorithm].append(levels.index(cost) + 1)
    for algorithm in ALGORITHMS:
        group = [row for row in rows if row["algorithm"] == algorithm]
        total = sum(float(row["best_cost"]) for row in group)
        totals[algorithm] = total
        mean_rank = statistics.fmean(rank_values[algorithm]) if algorithm in rank_values else math.nan
        mean_ranks[algorithm] = mean_rank
        algorithm_summary.append(
            {
                "algorithm": algorithm,
                "runs": len(group),
                "benchmark_total_cost": total,
                "mean_runtime_seconds": statistics.fmean(float(row["elapsed_seconds"]) for row in group),
                "total_runtime_seconds": sum(float(row["elapsed_seconds"]) for row in group),
                "mean_rank_excluding_ablation": mean_rank,
                "best_or_tied_count_excluding_ablation": best_counts.get(algorithm, ""),
            }
        )

    paired_summary: list[dict[str, Any]] = []
    for baseline in (ABLATION, *BASELINES):
        gains: list[float] = []
        runtime_gains: list[float] = []
        for key in keys:
            left = by_key[key + (PRIMARY,)]
            right = by_key[key + (baseline,)]
            left_cost = float(left["best_cost"])
            right_cost = float(right["best_cost"])
            gains.append(100.0 * (right_cost - left_cost) / right_cost)
            right_runtime = float(right["elapsed_seconds"])
            runtime_gains.append(100.0 * (right_runtime - float(left["elapsed_seconds"])) / right_runtime if right_runtime else math.nan)
        ci_low, ci_high = _bootstrap_mean_ci(gains)
        paired_summary.append(
            {
                "right_algorithm": baseline,
                "pairs": len(gains),
                "mean_gain_pct": statistics.fmean(gains),
                "median_gain_pct": statistics.median(gains),
                "bootstrap_mean_95ci_low_pct": ci_low,
                "bootstrap_mean_95ci_high_pct": ci_high,
                "wins": sum(value > 1e-9 for value in gains),
                "ties": sum(abs(value) <= 1e-9 for value in gains),
                "losses": sum(value < -1e-9 for value in gains),
                "mean_runtime_gain_pct": statistics.fmean(runtime_gains),
            }
        )

    baseline_totals = {algorithm: totals[algorithm] for algorithm in BASELINES}
    runner_up = min(baseline_totals, key=baseline_totals.get)
    aggregate_gain = 100.0 * (baseline_totals[runner_up] - totals[PRIMARY]) / baseline_totals[runner_up]
    primary_pair = next(row for row in paired_summary if row["right_algorithm"] == runner_up)

    carbon_pairs = []
    for key in keys:
        aware = by_key[key + (PRIMARY,)]
        naive = by_key[key + (ABLATION,)]
        carbon_pairs.append(
            {
                "same_route": aware["route_structure_signature"] == naive["route_structure_signature"],
                "same_energy": abs(float(aware["electricity_kwh"]) - float(naive["electricity_kwh"])) <= 1e-7,
                "reduction": float(naive["E_ev_indirect"]) - float(aware["E_ev_indirect"]),
                "moved": int(float(aware.get("charging_actions_moved_from_search_output", 0))) > 0,
            }
        )
    carbon_contract = all(item["same_route"] and item["same_energy"] for item in carbon_pairs)
    carbon_positive = sum(item["reduction"] > 1e-9 for item in carbon_pairs)

    baseline_runtime_min = min(
        next(row["mean_runtime_seconds"] for row in algorithm_summary if row["algorithm"] == algorithm)
        for algorithm in BASELINES
    )
    primary_runtime = next(row["mean_runtime_seconds"] for row in algorithm_summary if row["algorithm"] == PRIMARY)
    performance_supported = (
        matrix_contract
        and totals[PRIMARY] < min(baseline_totals.values())
        and aggregate_gain >= 5.0
        and mean_ranks[PRIMARY] < min(mean_ranks[algorithm] for algorithm in BASELINES)
        and primary_pair["wins"] > primary_pair["losses"]
        and primary_runtime < baseline_runtime_min
        and carbon_contract
        and carbon_positive > 0
    )
    decision = {
        "schema": "setp-e2-submission-performance-closeout.v1",
        "verdict": "E2_FULL_BENCHMARK_LEAD_SUPPORTED" if performance_supported else "E2_FULL_BENCHMARK_TARGET_NOT_MET",
        "matrix_contract_pass": matrix_contract,
        "primary_algorithm": PRIMARY,
        "runner_up_algorithm": runner_up,
        "primary_benchmark_total_cost": totals[PRIMARY],
        "runner_up_benchmark_total_cost": baseline_totals[runner_up],
        "aggregate_benchmark_gain_pct": aggregate_gain,
        "paired_mean_gain_pct": primary_pair["mean_gain_pct"],
        "paired_median_gain_pct": primary_pair["median_gain_pct"],
        "paired_bootstrap_mean_95ci_pct": [
            primary_pair["bootstrap_mean_95ci_low_pct"],
            primary_pair["bootstrap_mean_95ci_high_pct"],
        ],
        "paired_wins_ties_losses": [primary_pair["wins"], primary_pair["ties"], primary_pair["losses"]],
        "primary_mean_rank": mean_ranks[PRIMARY],
        "runner_up_mean_rank": mean_ranks[runner_up],
        "primary_mean_runtime_seconds": primary_runtime,
        "fastest_baseline_mean_runtime_seconds": baseline_runtime_min,
        "carbon_pair_count": len(carbon_pairs),
        "carbon_same_route_equal_energy_pairs": sum(item["same_route"] and item["same_energy"] for item in carbon_pairs),
        "carbon_positive_reduction_pairs": carbon_positive,
        "carbon_moved_pairs": sum(item["moved"] for item in carbon_pairs),
        "claim_boundaries": {
            "aggregate_benchmark_lead_over_5pct": aggregate_gain >= 5.0,
            "uniform_pairwise_5pct_claim": False,
            "all_instances_win_claim": False,
            "old_coarse_carbon_operators_claim": False,
            "scenario": "280 kWh modern-distribution main scenario; 80 kWh remains a separate robustness baseline",
        },
    }
    return algorithm_summary, paired_summary, decision


def write_closeout(phase_dir: Path) -> dict[str, Any]:
    rows = _read_rows(phase_dir / "raw_runs.csv")
    algorithm_summary, paired_summary, decision = build_closeout(rows)
    closure.write_csv(phase_dir / "algorithm_summary.csv", algorithm_summary)
    closure.write_csv(phase_dir / "paired_algorithm_summary.csv", paired_summary)
    closure.write_json(phase_dir / "performance_decision.json", decision)
    report = [
        "# E2 full-benchmark performance closeout",
        "",
        f"Verdict: `{decision['verdict']}`.",
        "",
        f"The staged hybrid plus carbon-aware charging has total benchmark cost {decision['primary_benchmark_total_cost']:.6f}, versus {decision['runner_up_benchmark_total_cost']:.6f} for runner-up {decision['runner_up_algorithm']}; aggregate lead {decision['aggregate_benchmark_gain_pct']:.3f}%.",
        f"Across the 45 matched instance-seed pairs, the mean/median gains are {decision['paired_mean_gain_pct']:.3f}%/{decision['paired_median_gain_pct']:.3f}%, with W/T/L={decision['paired_wins_ties_losses']} and bootstrap mean 95% CI {decision['paired_bootstrap_mean_95ci_pct']}.",
        f"Mean rank is {decision['primary_mean_rank']:.3f} versus {decision['runner_up_mean_rank']:.3f} for {decision['runner_up_algorithm']}. Mean runtime is {decision['primary_mean_runtime_seconds']:.3f}s; the fastest non-ablation baseline averages {decision['fastest_baseline_mean_runtime_seconds']:.3f}s.",
        f"Carbon scheduling preserves route structure and charged energy for {decision['carbon_same_route_equal_energy_pairs']}/{decision['carbon_pair_count']} pairs; {decision['carbon_positive_reduction_pairs']} pairs reduce indirect EV emissions and {decision['carbon_moved_pairs']} pairs record charging-time moves.",
        "",
        "Claim boundary: the >5% statement applies to the aggregate full-benchmark cost, not every instance or the unweighted mean paired percentage. The full paired statistics must be reported beside it. Historical coarse carbon destroy/repair operators remain excluded.",
    ]
    (phase_dir / "closeout_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    closure.write_hashes(phase_dir)
    return decision


if __name__ == "__main__":
    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_PHASE_DIR
    print(json.dumps(write_closeout(target), ensure_ascii=False, indent=2, sort_keys=True))
