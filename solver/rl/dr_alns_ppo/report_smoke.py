from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_algorithm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_algorithm[str(row["algorithm"])].append(row)

    medians = {
        algorithm: statistics.median(float(row["best_obj"]) for row in alg_rows)
        for algorithm, alg_rows in by_algorithm.items()
        if alg_rows
    }
    paired_random = _paired_gaps(rows, "ppo_full", "random_full")
    paired_alpha = _paired_gaps(rows, "ppo_full", "alpha_ucb_env")
    gate_vs_random = _gate_median(medians, "ppo_full", "random_full", pass_label="PASS_RANDOM", fail_label="HALT_RANDOM")
    if "alpha_ucb_env" in medians and "ppo_full" in medians:
        gate_vs_alpha = (
            "PASS_ALPHA_UCB"
            if _median_better(medians, "ppo_full", "alpha_ucb_env")
            else "FUTURE_WORK"
        )
    else:
        gate_vs_alpha = "NOT_RUN"

    actual_evals = [int(row["actual_evals"]) for row in rows]
    under_budget = [row for row in rows if _budget_delta(row) < 0]
    over_budget = [row for row in rows if _budget_delta(row) > 0]
    budget_mismatches = [row for row in rows if _budget_delta(row) != 0]
    if _has_budget_mismatch_for(rows, {"ppo_full", "random_full"}):
        gate_vs_random = "HALT_RANDOM"
    if gate_vs_alpha != "NOT_RUN" and _has_budget_mismatch_for(rows, {"ppo_full", "alpha_ucb_env"}):
        gate_vs_alpha = "FUTURE_WORK"

    return {
        "schema_version": "dr-alns-ppo-v2-smoke-summary.v1",
        "rows": len(rows),
        "median_best_obj": medians,
        "paired_gap_vs_random": paired_random,
        "paired_gap_vs_alpha_ucb_env": paired_alpha,
        "actual_evals_min": min(actual_evals) if actual_evals else 0,
        "actual_evals_max": max(actual_evals) if actual_evals else 0,
        "under_budget_runs": [
            {"algorithm": row["algorithm"], "bundle": row["bundle"], "seed": int(row["seed"]), "actual_evals": int(row["actual_evals"])}
            for row in under_budget
        ],
        "over_budget_runs": [
            {"algorithm": row["algorithm"], "bundle": row["bundle"], "seed": int(row["seed"]), "actual_evals": int(row["actual_evals"])}
            for row in over_budget
        ],
        "budget_mismatch_runs": [
            {
                "algorithm": row["algorithm"],
                "bundle": row["bundle"],
                "seed": int(row["seed"]),
                "eval_budget": int(row.get("eval_budget") or 0),
                "actual_evals": int(row["actual_evals"]),
            }
            for row in budget_mismatches
        ],
        "budget_matched": not budget_mismatches,
        "feasibility_rate": _feasibility_rate(rows),
        "operator_base_id_ok": _operator_base_id_ok(rows),
        "zero_violation": all(int(row.get("violation_count", 0) or 0) == 0 for row in rows),
        "q_ratio_distribution": _merged_counter(rows, "q_ratio_counts"),
        "destroy_operator_usage": _merged_counter(rows, "destroy_counts"),
        "repair_operator_usage": _merged_counter(rows, "repair_counts"),
        "gate_vs_random": gate_vs_random,
        "gate_vs_alpha_ucb_env": gate_vs_alpha,
    }


def write_summary(summary: dict[str, Any], output_dir: str | Path) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "smoke_100k_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out / "smoke_100k_summary.md").write_text(_summary_markdown(summary), encoding="utf-8")


def load_comparison(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [_parse_row(row) for row in csv.DictReader(handle)]


def _summary_markdown(summary: dict[str, Any]) -> str:
    gate_random = summary["gate_vs_random"]
    gate_alpha = summary["gate_vs_alpha_ucb_env"]
    return f"""# DR-ALNS-PPO v2 100k Smoke

This smoke does not modify the formal runner or manuscript.

Each `env.step()` performs one full candidate solution scoring. The reported
`actual_evals` values come from the shared evaluator budget counter, not from
PPO inference calls.

Gate versus random: `{gate_random}`.
Gate versus AlphaUCB-in-env: `{gate_alpha}`.

If the 100k smoke does not beat random on held-out bundles, this lane remains a
wiring/debug task. If the 1-2M pilot does not beat AlphaUCB-in-env on the same
winner operators and 16000-eval budget, the result is a learnable alternative
rather than evidence that DRL scheduling significantly improves the kernel.
"""


def _parse_row(row: dict[str, str]) -> dict[str, Any]:
    parsed: dict[str, Any] = dict(row)
    for key in ("seed", "eval_budget", "actual_evals", "candidate_scores", "repair_delta_count"):
        parsed[key] = int(parsed[key])
    parsed["best_obj"] = float(parsed["best_obj"])
    parsed["feasible"] = str(parsed["feasible"]).lower() in {"1", "true", "yes"}
    parsed["violation_count"] = int(parsed.get("violation_count") or 0)
    for key in ("operator_counts", "destroy_counts", "repair_counts", "q_ratio_counts"):
        parsed[key] = json.loads(parsed[key]) if parsed.get(key) else {}
    return parsed


def _budget_delta(row: dict[str, Any]) -> int:
    budget = int(row.get("eval_budget") or 0)
    if budget <= 0:
        return 0
    actual = int(row["actual_evals"])
    if actual < budget:
        return -1
    if actual > budget:
        return 1
    return 0


def _has_budget_mismatch_for(rows: list[dict[str, Any]], algorithms: set[str]) -> bool:
    return any(str(row["algorithm"]) in algorithms and _budget_delta(row) != 0 for row in rows)


def _median_better(medians: dict[str, float], left: str, right: str) -> bool:
    return left in medians and right in medians and float(medians[left]) < float(medians[right])


def _gate_median(medians: dict[str, float], left: str, right: str, *, pass_label: str, fail_label: str) -> str:
    if left not in medians or right not in medians:
        return "NOT_RUN"
    return pass_label if _median_better(medians, left, right) else fail_label


def _operator_base_id_ok(rows: list[dict[str, Any]]) -> bool:
    winner_algorithms = {"ppo_full", "ppo_operator_only", "random_full", "alpha_ucb_env", "official_winner_kernel"}
    for row in rows:
        if str(row.get("algorithm")) not in winner_algorithms:
            continue
        if str(row.get("operator_base_id", "")) != "winner_kernel_v1":
            return False
    return True


def _paired_gaps(rows: list[dict[str, Any]], left: str, right: str) -> list[dict[str, Any]]:
    index = {(row["algorithm"], row["bundle"], int(row["seed"])): row for row in rows}
    gaps = []
    for key, left_row in sorted(index.items(), key=lambda item: (item[0][1], item[0][2], item[0][0])):
        algorithm, bundle, seed = key
        if algorithm != left:
            continue
        right_row = index.get((right, bundle, seed))
        if right_row is None:
            continue
        left_obj = float(left_row["best_obj"])
        right_obj = float(right_row["best_obj"])
        gaps.append(
            {
                "bundle": bundle,
                "seed": seed,
                "left": left,
                "right": right,
                "best_obj_delta": left_obj - right_obj,
                "relative_gap": (left_obj - right_obj) / max(abs(right_obj), 1.0),
            }
        )
    return gaps


def _feasibility_rate(rows: list[dict[str, Any]]) -> dict[str, float]:
    grouped: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        grouped[str(row["algorithm"])].append(bool(row["feasible"]))
    return {
        algorithm: sum(values) / max(len(values), 1)
        for algorithm, values in grouped.items()
    }


def _merged_counter(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        for key, value in (row.get(field) or {}).items():
            counter[str(key)] += _count_value(value)
    return dict(sorted(counter.items()))


def _count_value(value: Any) -> int:
    if isinstance(value, list):
        return sum(_count_value(item) for item in value)
    if isinstance(value, dict):
        return sum(_count_value(item) for item in value.values())
    return int(value)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize the DR-ALNS-PPO 100k smoke comparison.")
    parser.add_argument("--comparison", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_summary(load_comparison(args.comparison))
    write_summary(summary, args.output_dir)
    print(f"DR_ALNS_PPO_SMOKE_REPORT_OK gate_vs_random={summary['gate_vs_random']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
