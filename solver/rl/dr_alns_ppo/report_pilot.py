from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any

from .report_smoke import load_comparison


SYSTEM_WORKER_PYTHON = "/opt/anaconda3/bin/python3.13"
CLOSE_TO_ALPHA_RELATIVE_GAP = 0.05
REWARD_IMPROVEMENT_RATIO = 0.05


def build_pilot_report(
    *,
    monitor_rows: list[dict[str, Any]],
    train_rows: list[dict[str, Any]],
    formal_10001_rows: list[dict[str, Any]],
    held_out_rows: list[dict[str, Any]],
    system_worker_python: str = SYSTEM_WORKER_PYTHON,
) -> dict[str, Any]:
    reward = reward_trend(monitor_rows)
    train = comparison_summary(train_rows, system_worker_python=system_worker_python)
    formal_10001 = comparison_summary(formal_10001_rows, system_worker_python=system_worker_python)
    held_out = comparison_summary(held_out_rows, system_worker_python=system_worker_python)
    integrity = integrity_summary(
        [*train_rows, *formal_10001_rows, *held_out_rows],
        system_worker_python=system_worker_python,
    )
    verdict = classify_pilot(
        reward_up=bool(reward["reward_up"]),
        train_close_alpha=bool(train["ppo_close_to_alpha"]),
        train_beats_random=bool(train["ppo_beats_random"]),
        formal_10001_close_alpha=bool(formal_10001["ppo_close_to_alpha"]),
        integrity_ok=bool(integrity["ok"]),
    )
    result = {
        "schema_version": "dr-alns-ppo-v2-real3-pilot-report.v1",
        "verdict": verdict["verdict"],
        "reason": verdict["reason"],
        "system_worker_python": system_worker_python,
        "reward_trend": reward,
        "train_summary": train,
        "formal_10001_summary": formal_10001,
        "held_out_summary": held_out,
        "integrity": integrity,
    }
    return result


def reward_trend(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rewards = [float(row["r"]) for row in rows if "r" in row]
    if not rewards:
        return {
            "episode_count": 0,
            "first_third_mean": None,
            "last_third_mean": None,
            "slope": None,
            "reward_up": False,
        }
    n = len(rewards)
    third = max(1, n // 3)
    first = rewards[:third]
    last = rewards[-third:]
    first_mean = statistics.fmean(first)
    last_mean = statistics.fmean(last)
    slope = _linear_slope(rewards)
    reward_up = slope > 0.0 and last_mean >= first_mean * (1.0 + REWARD_IMPROVEMENT_RATIO)
    return {
        "episode_count": n,
        "first_third_mean": first_mean,
        "last_third_mean": last_mean,
        "slope": slope,
        "reward_up": reward_up,
    }


def comparison_summary(rows: list[dict[str, Any]], *, system_worker_python: str = SYSTEM_WORKER_PYTHON) -> dict[str, Any]:
    by_algorithm: dict[str, list[float]] = {}
    for row in rows:
        by_algorithm.setdefault(str(row["algorithm"]), []).append(float(row["best_obj"]))
    medians = {
        algorithm: statistics.median(values)
        for algorithm, values in sorted(by_algorithm.items())
        if values
    }
    means = {
        algorithm: statistics.fmean(values)
        for algorithm, values in sorted(by_algorithm.items())
        if values
    }
    ppo = medians.get("ppo_full")
    alpha = medians.get("alpha_ucb_env")
    random = medians.get("random_full")
    ppo_alpha_relative_gap = None
    if ppo is not None and alpha is not None:
        ppo_alpha_relative_gap = (ppo - alpha) / max(abs(alpha), 1.0)
    return {
        "row_count": len(rows),
        "median_best_obj": medians,
        "mean_best_obj": means,
        "ppo_alpha_relative_gap": ppo_alpha_relative_gap,
        "ppo_close_to_alpha": (
            ppo_alpha_relative_gap is not None
            and ppo_alpha_relative_gap <= CLOSE_TO_ALPHA_RELATIVE_GAP
        ),
        "ppo_beats_alpha": ppo is not None and alpha is not None and ppo < alpha,
        "ppo_beats_random": ppo is not None and random is not None and ppo < random,
        "integrity": integrity_summary(rows, system_worker_python=system_worker_python),
    }


def integrity_summary(rows: list[dict[str, Any]], *, system_worker_python: str = SYSTEM_WORKER_PYTHON) -> dict[str, Any]:
    budget_mismatches = [
        _row_id(row)
        for row in rows
        if int(row.get("actual_evals") or 0) != int(row.get("eval_budget") or 0)
    ]
    violations = [
        _row_id(row)
        for row in rows
        if int(row.get("violation_count") or 0) != 0
    ]
    non_system_worker = [
        _row_id(row)
        for row in rows
        if str(row.get("worker_python_executable", "")) != system_worker_python
    ]
    return {
        "ok": not budget_mismatches and not violations and not non_system_worker,
        "row_count": len(rows),
        "budget_mismatches": budget_mismatches,
        "violations": violations,
        "non_system_worker": non_system_worker,
    }


def classify_pilot(
    *,
    reward_up: bool,
    train_close_alpha: bool,
    train_beats_random: bool,
    formal_10001_close_alpha: bool,
    integrity_ok: bool,
) -> dict[str, str]:
    if not integrity_ok:
        return {
            "verdict": "HALT_INTEGRITY",
            "reason": "At least one evaluation row has a budget mismatch, nonzero violation, or non-system worker.",
        }
    if reward_up and formal_10001_close_alpha:
        return {
            "verdict": "PROMISING",
            "reason": "Reward increased and PPO is within 5% of AlphaUCB on the unseen 100-01 formal check.",
        }
    if reward_up and train_close_alpha:
        return {
            "verdict": "DATA_LIMITED",
            "reason": "PPO learns on the real3 training set but does not yet generalize to 100-01.",
        }
    if reward_up and train_beats_random:
        return {
            "verdict": "WEAK",
            "reason": "Reward improved and PPO beats random on train, but it is not close to AlphaUCB on train.",
        }
    return {
        "verdict": "WEAK",
        "reason": "The medium pilot did not show a convincing reward trend plus training-set AlphaUCB proximity.",
    }


def load_monitor(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        filtered = (line for line in handle if not line.startswith("#"))
        for row in csv.DictReader(filtered):
            rows.append(dict(row))
    return rows


def write_report(report: dict[str, Any], output_dir: str | Path) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "pilot_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out / "pilot_report.md").write_text(_markdown(report), encoding="utf-8")


def _linear_slope(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    x_mean = (len(values) - 1) / 2.0
    y_mean = statistics.fmean(values)
    numerator = sum((idx - x_mean) * (value - y_mean) for idx, value in enumerate(values))
    denominator = sum((idx - x_mean) ** 2 for idx in range(len(values)))
    return numerator / denominator if denominator else 0.0


def _row_id(row: dict[str, Any]) -> str:
    return f"{row.get('algorithm')}|{row.get('bundle')}|seed{row.get('seed')}"


def _markdown(report: dict[str, Any]) -> str:
    reward = report["reward_trend"]
    train = report["train_summary"]
    formal = report["formal_10001_summary"]
    held = report["held_out_summary"]
    return "\n".join(
        [
            "# DR-ALNS-PPO Real3 Pilot",
            "",
            f"- verdict: `{report['verdict']}`",
            f"- reason: {report['reason']}",
            f"- system_worker_python: `{report['system_worker_python']}`",
            f"- reward_up: `{reward['reward_up']}`",
            f"- episode_count: {reward['episode_count']}",
            f"- first_third_mean_reward: {reward['first_third_mean']}",
            f"- last_third_mean_reward: {reward['last_third_mean']}",
            f"- reward_slope: {reward['slope']}",
            "",
            "## Median Cost By Split",
            "",
            f"- train: `{json.dumps(train['median_best_obj'], ensure_ascii=False, sort_keys=True)}`",
            f"- 100-01: `{json.dumps(formal['median_best_obj'], ensure_ascii=False, sort_keys=True)}`",
            f"- held_out: `{json.dumps(held['median_best_obj'], ensure_ascii=False, sort_keys=True)}`",
            "",
            "## Integrity",
            "",
            f"- ok: `{report['integrity']['ok']}`",
            f"- budget_mismatches: {len(report['integrity']['budget_mismatches'])}",
            f"- violations: {len(report['integrity']['violations'])}",
            f"- non_system_worker: {len(report['integrity']['non_system_worker'])}",
        ]
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize the DR-ALNS-PPO real3 medium pilot.")
    parser.add_argument("--monitor", required=True)
    parser.add_argument("--train-comparison", required=True)
    parser.add_argument("--formal-10001-comparison", required=True)
    parser.add_argument("--held-out-comparison", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--system-worker-python", default=SYSTEM_WORKER_PYTHON)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_pilot_report(
        monitor_rows=load_monitor(args.monitor),
        train_rows=load_comparison(args.train_comparison),
        formal_10001_rows=load_comparison(args.formal_10001_comparison),
        held_out_rows=load_comparison(args.held_out_comparison),
        system_worker_python=args.system_worker_python,
    )
    write_report(report, args.output_dir)
    print(f"DR_ALNS_PPO_PILOT_REPORT_OK verdict={report['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
