#!/usr/bin/env python3
"""Check whether the four frozen E7 stops are caused by the 400-evaluation budget."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from baselines.e7_dynamic import e7_formal_dynamic_value_20260714 as formal


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "baselines/e7_dynamic/e7_v2_20260714/preflight/failed_stage_budget_800"
TASKS = (
    ("independent", 2, 11),
    ("cooperative", 3, 24),
    ("independent", 3, 24),
    ("independent", 5, 20),
)


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["status"])
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evaluations", type=int, default=800)
    parser.add_argument("--workers", type=int, choices=(1, 2, 3, 4), default=4)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for old in output.iterdir():
        if old.is_file():
            old.unlink()
    jobs = [
        (arm, seed, args.evaluations, stage, "event")
        for arm, seed, stage in TASKS
    ]
    if args.workers == 1:
        captured = [formal.run_session_captured(job) for job in jobs]
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            captured = list(executor.map(formal.run_session_captured, jobs))
    rows: list[dict[str, Any]] = []
    for (arm, seed, target_stage), result in zip(TASKS, captured):
        session = result["session"]
        failure = result["failure"]
        if session is not None:
            target = session["stage_rows"][-1]
            rows.append(
                {
                    "arm": arm,
                    "stream_seed": seed,
                    "target_stage": target_stage,
                    "status": "PASS",
                    "completed_stage_count": session["stages"],
                    "evaluations_per_stage": args.evaluations,
                    "initial_continuation_feasible_at_target": target["initial_continuation_feasible"],
                    "executable_candidates_at_target": target["executable_candidate_count"],
                    "accepted_candidates_at_target": target["accepted_candidate_count"],
                    "error": "",
                }
            )
        else:
            rows.append(
                {
                    "arm": arm,
                    "stream_seed": seed,
                    "target_stage": target_stage,
                    "status": "HALT",
                    "completed_stage_count": failure["completed_stage_count"],
                    "evaluations_per_stage": args.evaluations,
                    "initial_continuation_feasible_at_target": "",
                    "executable_candidates_at_target": 0,
                    "accepted_candidates_at_target": 0,
                    "error": failure["error"],
                }
            )
    write_csv(output / "raw_runs.csv", rows)
    passed = all(row["status"] == "PASS" for row in rows)
    formal.write_json(
        output / "metadata.json",
        {
            "contract_id": "E7_FAILED_STAGE_BUDGET_PROBE_V1",
            "scope": "preflight_only",
            "source_commit": formal.source_commit(),
            "evaluations_per_stage": args.evaluations,
            "workers": args.workers,
            "frozen_tasks": [
                {"arm": arm, "stream_seed": seed, "target_stage": stage}
                for arm, seed, stage in TASKS
            ],
            "interpretation_limit": "This probe only tests whether 800 evaluations can reach the four previously failed stages.",
        },
    )
    verdict = "E7_800_BUDGET_PROBE_PASS" if passed else "HALT_E7_800_BUDGET_PROBE"
    formal.write_json(
        output / "decision.json",
        {
            "verdict": verdict,
            "passed": passed,
            "passed_task_count": sum(row["status"] == "PASS" for row in rows),
            "task_count": len(rows),
            "formal_result": False,
        },
    )
    (output / "report.md").write_text(
        "\n".join(
            [
                "# E7停止位置的计算量检查",
                "",
                f"判决：`{verdict}`。",
                "",
                "只重跑400次正式批中停止的四个位置，每阶段提高到800次；订单流、车辆、时间、电量和客户归属均不变。",
                f"{sum(row['status'] == 'PASS' for row in rows)}/{len(rows)}个位置走到原停止阶段。该结果只决定是否值得用800次重跑完整五流，不形成论文结论。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    artifacts = [
        {
            "path": str(path.relative_to(ROOT)),
            "sha256": formal.sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(output.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    ]
    formal.write_json(
        output / "artifact_hashes.json",
        {"algorithm": "sha256", "excluded": ["artifact_hashes.json", "._*"], "artifacts": artifacts},
    )


if __name__ == "__main__":
    main()
