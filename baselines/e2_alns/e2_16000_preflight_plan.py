#!/usr/bin/env python3
"""Zero-search runtime and sample plan for legacy item 9."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
from typing import Any


RAW = Path("baselines/e2_alns/e2_submission_20260711/carbon_280/raw_runs.csv")
ALGORITHMS = ("staged_hybrid_carbon_aware", "LNS")
PREFLIGHT_PAIRS = (
    ("L-main-threeshift-20c-01", 3, "worst_4000_loss"),
    ("L-main-threeshift-50c-01", 5, "second_worst_4000_loss"),
    ("L-main-threeshift-150c-01", 3, "large_scale_4000_loss"),
    ("L-main-threeshift-200c-01", 4, "slowest_pair_and_strong_win_guard"),
)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(output: Path) -> dict[str, str]:
    return {
        str(path.relative_to(output)): sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader((root / RAW).open(encoding="utf-8", newline="")))
    indexed = {(row["instance"], int(row["seed"]), row["algorithm"]): row for row in rows}

    tasks: list[dict[str, Any]] = []
    for instance, seed, role in PREFLIGHT_PAIRS:
        hybrid = indexed[(instance, seed, ALGORITHMS[0])]
        lns = indexed[(instance, seed, ALGORITHMS[1])]
        gain = (float(lns["best_cost"]) - float(hybrid["best_cost"])) / float(lns["best_cost"]) * 100.0
        for algorithm, row in ((ALGORITHMS[0], hybrid), (ALGORITHMS[1], lns)):
            elapsed_4000 = float(row["elapsed_seconds"])
            tasks.append(
                {
                    "instance": instance,
                    "seed": seed,
                    "algorithm": algorithm,
                    "selection_role": role,
                    "eval_budget": 16000,
                    "4000_cost": float(row["best_cost"]),
                    "4000_pair_hybrid_gain_pct": gain,
                    "4000_elapsed_seconds": elapsed_4000,
                    "linear_16000_seconds": elapsed_4000 * 4.0,
                    "conservative_16000_seconds": elapsed_4000 * 5.0,
                    "status": "PLANNED_NOT_STARTED",
                }
            )
    with (output / "task_manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(tasks[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(tasks)

    formal = [row for row in rows if row["algorithm"] in ALGORITHMS]
    total_4000_seconds = sum(float(row["elapsed_seconds"]) for row in formal)
    preflight_linear = sum(float(row["linear_16000_seconds"]) for row in tasks)
    preflight_conservative = sum(float(row["conservative_16000_seconds"]) for row in tasks)
    full_linear = total_4000_seconds * 4.0
    full_conservative = total_4000_seconds * 5.0
    decision = {
        "verdict": "PROJECT9_PLANNED_NOT_AUTHORIZED",
        "zero_search": True,
        "preflight_task_count": len(tasks),
        "preflight_pair_count": len(PREFLIGHT_PAIRS),
        "full_matrix_task_count_if_promoted": 9 * 5 * 2,
        "preflight_linear_hours_sequential": preflight_linear / 3600.0,
        "preflight_conservative_hours_sequential": preflight_conservative / 3600.0,
        "full_linear_hours_sequential": full_linear / 3600.0,
        "full_conservative_hours_sequential": full_conservative / 3600.0,
        "two_worker_time_is_not_promised": True,
        "authorization_conditions": [
            "projects 4, 5 and 6 have final decisions",
            "one submission contract is frozen",
            "the 16000 runner passes a 2-eval wiring smoke test",
            "two workers improve completed valid evaluations per hour without failures",
        ],
        "promotion_gate": [
            "8/8 runs complete exactly 16000 evaluations with zero violations and valid hashes",
            "aggregate hybrid cost is no worse than aggregate LNS cost on the four pairs",
            "at least two of the three selected 4000-loss hybrid runs improve their own 4000 cost",
            "the 200c strong-win guard remains no worse than LNS",
            "no task exceeds its explicit wall-clock cap or silently truncates evaluations",
        ],
    }
    metadata = {
        "schema_version": "resetp.e2_16000_preflight_plan.v1",
        "execution_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "source_raw": str(RAW),
        "source_raw_sha256": sha256(root / RAW),
        "generator_sha256": sha256(Path(__file__)),
        "elapsed_4000_total_seconds_two_algorithms_90_runs": total_4000_seconds,
        "elapsed_4000_median_seconds": statistics.median(float(row["elapsed_seconds"]) for row in formal),
    }
    write_json(output / "metadata.json", metadata)
    write_json(output / "decision.json", decision)
    (output / "raw_runs.csv").write_text((output / "task_manifest.csv").read_text(encoding="utf-8"), encoding="utf-8")
    (output / "report.md").write_text(
        "# 项目9：16000评价长预算预案（未开跑）\n\n"
        f"从现有4000评价真实耗时推算，8项代表预检顺序执行约{preflight_linear / 3600.0:.2f}小时，保守按5倍约{preflight_conservative / 3600.0:.2f}小时。"
        f"若晋级到九档五种子两算法共90项，顺序执行线性估计约{full_linear / 3600.0:.2f}小时，保守约{full_conservative / 3600.0:.2f}小时。\n\n"
        "大白话：长预算不是现在跑。先用三个典型负例看更长搜索能不能救回来，再用最慢的200c强胜样本防止顾此失彼。"
        "预检过门以后才允许90项全矩阵；仍从2个worker开始，用有效完成量判断是否加并行，不能按CPU占用率硬拉。\n",
        encoding="utf-8",
    )
    write_json(output / "artifact_hashes.json", hashes(output))
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
