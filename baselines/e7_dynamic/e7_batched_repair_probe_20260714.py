#!/usr/bin/env python3
"""Replay the three known batched E7 stops after the asset-aware repair."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import csv
from pathlib import Path
from typing import Any, Mapping, Sequence

from baselines.e7_dynamic import e7_formal_dynamic_value_20260714 as formal


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "baselines/e7_dynamic/e7_v2_20260714/preflight/batched_repair_known_stops"
TASKS = (
    ("cooperative", 1, 400, 4, "batched"),
    ("independent", 1, 800, 2, "batched"),
    ("cooperative", 1, 800, 7, "batched"),
)


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["status"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    output = DEFAULT_OUTPUT.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for old in output.iterdir():
        if old.is_file() and not old.name.startswith("._"):
            old.unlink()
    with ProcessPoolExecutor(max_workers=3) as executor:
        captured = list(executor.map(formal.run_session_captured, TASKS))
    rows: list[dict[str, Any]] = []
    for task, result in zip(TASKS, captured):
        arm, seed, evaluations, target_stage, _ = task
        session = result["session"]
        failure = result["failure"]
        if session is not None:
            target = session["stage_rows"][-1]
            rows.append(
                {
                    "arm": arm,
                    "stream_seed": seed,
                    "target_stage": target_stage,
                    "evaluations_per_stage": evaluations,
                    "status": "PASS",
                    "completed_stage_count": session["stages"],
                    "initial_type_trial_count": target["initial_type_trial_count"],
                    "search_exact_check_count": target["search_exact_check_count"],
                    "executable_candidates_at_target": target["executable_candidate_count"],
                    "customer_accounting_pass": target["customer_accounting_pass"],
                    "error": "",
                }
            )
        else:
            rows.append(
                {
                    "arm": arm,
                    "stream_seed": seed,
                    "target_stage": target_stage,
                    "evaluations_per_stage": evaluations,
                    "status": "HALT",
                    "completed_stage_count": failure["completed_stage_count"],
                    "initial_type_trial_count": "",
                    "search_exact_check_count": "",
                    "executable_candidates_at_target": 0,
                    "customer_accounting_pass": "",
                    "error": failure["error"],
                }
            )
    write_csv(output / "raw_runs.csv", rows)
    passed = all(row["status"] == "PASS" for row in rows)
    formal.write_json(
        output / "metadata.json",
        {
            "contract_id": "E7_BATCHED_ASSET_AWARE_REPAIR_KNOWN_STOPS_V1",
            "scope": "preflight_only",
            "source_commit": formal.source_commit(),
            "workers": 3,
            "tasks": [
                {
                    "arm": arm,
                    "stream_seed": seed,
                    "evaluations_per_stage": evaluations,
                    "target_stage": stage,
                    "trigger_mode": trigger_mode,
                }
                for arm, seed, evaluations, stage, trigger_mode in TASKS
            ],
            "result_direction_used_to_continue": False,
            "interpretation_limit": "Only the three previously observed batched stop positions are tested.",
        },
    )
    verdict = "E7_BATCHED_REPAIR_KNOWN_STOPS_PASS" if passed else "HALT_E7_BATCHED_REPAIR_KNOWN_STOPS"
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
                "# E7已知停止位置修补检查",
                "",
                f"判决：`{verdict}`。",
                "",
                "本轮只复测同一订单流中先前停止的三个位置，不形成论文结论。",
                "只有三处均越过原停止批次、客户账闭合且真实排班检查通过，才允许进入完整订单流。",
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
