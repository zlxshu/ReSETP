#!/usr/bin/env python3
"""Read-only gate for the authorized E7 parent-child recovery."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baselines.e7_dynamic import e7_formal_resumable_runner_20260715 as formal
from baselines.e7_dynamic import e7_parent_child_recovery_runner_20260716 as recovery


OUT = (
    recovery.ROOT
    / "baselines/e7_dynamic/e7_parent_child_recovery_gate_20260716"
)


def main() -> int:
    parent = recovery.read_json(recovery.PARENT_OUTPUT / "contract.json")
    child = formal.build_contract(50)
    checks: list[dict[str, object]] = []
    try:
        recovery.validate_parent_child_contracts(parent, child)
        checks.append({"check": "parent_child_contract_diff", "passed": True})
        tasks = formal._expected_tasks(50)
        parent_payloads, missing, parent_hashes = recovery.load_parent_partition(
            tasks, parent
        )
        checks.extend(
            [
                {
                    "check": "parent_checkpoint_count",
                    "passed": len(parent_payloads) == 102,
                    "detail": len(parent_payloads),
                },
                {
                    "check": "authorized_missing_task_set",
                    "passed": {
                        str(task["task_id"]) for task in missing
                    }
                    == recovery.AUTHORIZED_CHILD_TASK_IDS,
                    "detail": sorted(str(task["task_id"]) for task in missing),
                },
                {
                    "check": "parent_checkpoint_hash_count",
                    "passed": len(parent_hashes) == 102,
                    "detail": len(parent_hashes),
                },
                {
                    "check": "formal_final_files_absent",
                    "passed": not any(
                        (recovery.PARENT_OUTPUT / name).exists()
                        for name in recovery.FINAL_FILES
                    ),
                },
            ]
        )
    except Exception as exc:
        checks.append(
            {"check": "recovery_gate_exception", "passed": False, "detail": str(exc)}
        )
        parent_payloads, missing, parent_hashes, tasks = {}, [], {}, []
    passed = all(bool(item["passed"]) for item in checks)
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "task_id": task["task_id"],
            "network": task["network"],
            "condition": task["condition"],
            "stream": task["stream"],
            "arm": task["arm"],
            "authorized_lineage": (
                "child"
                if str(task["task_id"]) in recovery.AUTHORIZED_CHILD_TASK_IDS
                else "parent"
            ),
        }
        for task in tasks
    ]
    metadata = {
        "schema": "setp.e7.parent_child_recovery_gate.v1",
        "read_only": True,
        "evaluations": 50,
        "workers": 6,
        "parent_contract_sha256": parent.get("contract_sha256"),
        "child_contract_sha256": child.get("contract_sha256"),
        "parent_checkpoint_hashes": parent_hashes,
        "checks": checks,
    }
    decision = {
        "verdict": (
            "PASS_PARENT_CHILD_RECOVERY_AUTHORIZED"
            if passed
            else "HALT_PARENT_CHILD_RECOVERY_GATE"
        ),
        "parent_task_count": len(parent_payloads),
        "child_task_count": len(missing),
        "authorized_child_task_ids": sorted(recovery.AUTHORIZED_CHILD_TASK_IDS),
        "next_action": (
            "Run only the original failed task under the child contract."
            if passed
            else "Preserve the scene and do not start recovery tasks."
        ),
    }
    formal.atomic_write_json(OUT / "metadata.json", metadata)
    formal.atomic_write_csv(OUT / "raw_runs.csv", rows)
    formal.atomic_write_json(OUT / "decision.json", decision)
    report = [
        "# E7父—子恢复只读闸门",
        "",
        f"判决：`{decision['verdict']}`。",
        "",
        f"父断点{len(parent_payloads)}项，授权子任务{len(missing)}项；父、子科学合同除恰逢触发边界所在调度器哈希外无差异。",
        "",
        "本闸门不运行实验、不改写父断点，也不按结果方向调整任务集合。",
    ]
    formal._atomic_write_text(OUT / "report.md", "\n".join(report) + "\n")
    formal.atomic_write_json(OUT / "artifact_hashes.json", formal._artifact_hashes(OUT))
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
