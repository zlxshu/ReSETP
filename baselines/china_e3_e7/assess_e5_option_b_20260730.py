#!/usr/bin/env python3
"""Blindly assess E5 option B without approving or activating it."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "baselines/china_e3_e7/e5_option_b_assessment_20260730"
SOURCE = ROOT / "baselines/china_e3_e7/e5_nonlinear_20260729/pilot"
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path = [entry for entry in sys.path if Path(entry or ".").resolve() != SCRIPT_DIR]
for path in (ROOT / "solver/src", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from baselines.china_e3_e7.mechanism_foundation import (  # noqa: E402
    blind_search_convergence,
    select_result_blind_budget,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty assessment directory: {OUT}")
    OUT.mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    source_hashes: dict[str, str] = {}
    for folder in sorted(SOURCE.glob("budget-*"), key=lambda path: int(path.name.split("-")[1])):
        budget = int(folder.name.split("-")[1])
        for path in sorted(
            candidate
            for candidate in (folder / "tasks").glob("*.json")
            if not candidate.name.startswith("._")
        ):
            source_hashes[str(path.relative_to(ROOT))] = sha256(path)
            source = json.loads(path.read_text(encoding="utf-8"))
            convergence = blind_search_convergence(source["strict_improvement_flags_without_objectives"])
            rows.append(
                {
                    "instance_id": source["instance_id"],
                    "sample_role": source["sample_role"],
                    "seed": source["seed"],
                    "arm": source["arm"],
                    "budget": budget,
                    **convergence,
                    "source_task_sha256": source_hashes[str(path.relative_to(ROOT))],
                    "objective_or_between_arm_difference_read": False,
                    "status": "PASS_BLIND_RECLASSIFICATION",
                }
            )
    decision = select_result_blind_budget(
        rows,
        expected_units_by_arm={"L100_control": 15, "NL90_mild": 15},
    )
    decision.update(
        {
            "verdict": "OPTION_B_CONSTRUCTIBLE_HIGHER_BLIND_PILOT_REQUIRED",
            "option_b_approved": False,
            "option_b_active": False,
            "formal_search_allowed": False,
            "scientific_result_claim_allowed": False,
            "objective_or_between_arm_difference_read": False,
        }
    )
    write_csv(OUT / "raw_runs.csv", rows)
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_task_hashes": source_hashes,
            "source_hashes": {
                str(Path(__file__).resolve().relative_to(ROOT)): sha256(Path(__file__).resolve()),
                "baselines/china_e3_e7/mechanism_foundation.py": sha256(ROOT / "baselines/china_e3_e7/mechanism_foundation.py"),
            },
            "search_evaluations": 0,
        },
    )
    counts = {
        budget: {
            arm: sum(
                row["search_starved_L_over_S_gt_0_5"]
                for row in rows
                if row["budget"] == budget and row["arm"] == arm
            )
            for arm in ("L100_control", "NL90_mild")
        }
        for budget in sorted({row["budget"] for row in rows})
    }
    write_json(OUT / "blind_counts.json", counts)
    (OUT / "report.md").write_text(
        "# E5 方案 B 结果盲技术复判\n\n"
        "结论：`OPTION_B_CONSTRUCTIBLE_HIGHER_BLIND_PILOT_REQUIRED`。"
        "本包只读取 150 条严格改进布尔序列，不读取目标值或臂间差异；方案 B 未获批准、未启用。\n\n"
        f"按搜索窗口复判的五档饥饿数为 `{counts}`。240 档仍为两臂各 5/15，超过 20%，"
        "所以即使用户选择 B，也必须从 320 档继续结果盲 pilot，不能直接进入正式实验。\n",
        encoding="utf-8",
    )
    artifacts = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.iterdir())
        if path.is_file()
        and path.name != "artifact_hashes.json"
        and not path.name.startswith("._")
    }
    write_json(OUT / "artifact_hashes.json", {"schema": "resetp.artifact-hashes.v1", "artifacts": artifacts})
    print(decision["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
