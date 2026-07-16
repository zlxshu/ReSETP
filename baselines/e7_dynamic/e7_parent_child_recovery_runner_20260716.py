#!/usr/bin/env python3
"""Evidence-preserving recovery for the authorized E7 exact-trigger fix.

The original 102 checkpoints remain bound to the parent contract and are never
rewritten.  Only the 18 missing tasks are executed under the patched child
contract in a separate checkpoint directory.  Final evidence is assembled in
the original formal output with an explicit task-by-task lineage manifest.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baselines.e7_dynamic import e7_formal_resumable_runner_20260715 as formal


PARENT_OUTPUT = ROOT / "baselines/e7_dynamic/e7_multinetwork_formal_20260715"
CHILD_OUTPUT = (
    ROOT
    / "baselines/e7_dynamic/e7_multinetwork_formal_recovery_child_20260716"
)
PARENT_CONTRACT_SHA256 = (
    "bffdc512b8b39fe5c11bb80b63204a39f2a529d7810741354c401644cc3be16f"
)
CHILD_CONTRACT_SHA256 = (
    "b703492d88d5a4db69f4302c709767871a8743ddef853e7be1d8b4ca956c0721"
)
PARENT_SCHEDULER_SHA256 = (
    "0212c344024f95c9d13f7226f7b9ac7cfaab11f9e4244577d8191d37b5a629ed"
)
CHILD_SCHEDULER_SHA256 = (
    "8b2de29659a1460020f3be4ad50cf34baa0b4badc340fbe31ceb98b6c288959f"
)
SCHEDULER_RELATIVE = (
    "baselines/e7_dynamic/e7_full_mechanism_probe_20260714.py"
)
EXPECTED_PARENT_TASKS = 102
EXPECTED_CHILD_TASKS = 18
AUTHORIZED_CHILD_TASK_IDS = {
    "N322__geographic__stream5__no_cooperation",
    "N322__historical_mixed__stream1__no_participation",
    "N322__historical_mixed__stream2__full",
    "N322__historical_mixed__stream2__no_cooperation",
    "N322__historical_mixed__stream2__no_participation",
    "N322__historical_mixed__stream2__simple_insertion",
    "N322__historical_mixed__stream3__full",
    "N322__historical_mixed__stream3__no_cooperation",
    "N322__historical_mixed__stream3__no_participation",
    "N322__historical_mixed__stream3__simple_insertion",
    "N322__historical_mixed__stream4__full",
    "N322__historical_mixed__stream4__no_cooperation",
    "N322__historical_mixed__stream4__no_participation",
    "N322__historical_mixed__stream4__simple_insertion",
    "N322__historical_mixed__stream5__full",
    "N322__historical_mixed__stream5__no_cooperation",
    "N322__historical_mixed__stream5__no_participation",
    "N322__historical_mixed__stream5__simple_insertion",
}
ORIGINAL_FAILURE_TASK_ID = (
    "N322__historical_mixed__stream1__no_participation"
)
FINAL_FILES = {
    "RUN_FINISHED.json",
    "artifact_hashes.json",
    "decision.json",
    "metadata.json",
    "raw_runs.csv",
    "report.md",
    "sessions.json",
    "recovery_contract.json",
    "recovery_lineage.json",
    "task_lineage.csv",
}


class RecoveryContractError(RuntimeError):
    """Raised when parent/child evidence cannot be kept in separate lineages."""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RecoveryContractError(f"JSON object required: {path}")
    return value


def task_path(output: Path, task: Mapping[str, Any]) -> Path:
    return output / ".tasks" / f"{task['task_id']}.json"


def checkpoint_hashes(paths: Sequence[Path], base: Path) -> dict[str, str]:
    return {
        str(path.relative_to(base)): formal.sha256(path)
        for path in sorted(paths)
    }


def contract_without_source_hashes(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in contract.items()
        if key not in {"contract_sha256", "source_file_hashes", "source_commit_at_start"}
    }


def validate_parent_child_contracts(
    parent: Mapping[str, Any], child: Mapping[str, Any]
) -> None:
    if parent.get("contract_sha256") != PARENT_CONTRACT_SHA256:
        raise RecoveryContractError("parent contract hash differs")
    if child.get("contract_sha256") != CHILD_CONTRACT_SHA256:
        raise RecoveryContractError("child contract hash differs")
    if contract_without_source_hashes(parent) != contract_without_source_hashes(child):
        raise RecoveryContractError(
            "parent and child differ outside source hashes"
        )
    parent_sources = dict(parent.get("source_file_hashes", {}))
    child_sources = dict(child.get("source_file_hashes", {}))
    differing = {
        key
        for key in set(parent_sources) | set(child_sources)
        if parent_sources.get(key) != child_sources.get(key)
    }
    if differing != {SCHEDULER_RELATIVE}:
        raise RecoveryContractError(
            f"unexpected parent-child source differences: {sorted(differing)}"
        )
    if parent_sources.get(SCHEDULER_RELATIVE) != PARENT_SCHEDULER_SHA256:
        raise RecoveryContractError("parent scheduler hash differs")
    if child_sources.get(SCHEDULER_RELATIVE) != CHILD_SCHEDULER_SHA256:
        raise RecoveryContractError("child scheduler hash differs")


def load_parent_partition(
    tasks: Sequence[Mapping[str, Any]], parent: Mapping[str, Any]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    payloads: dict[str, dict[str, Any]] = {}
    missing: list[dict[str, Any]] = []
    present_paths: list[Path] = []
    for raw_task in tasks:
        task = dict(raw_task)
        path = task_path(PARENT_OUTPUT, task)
        if path.is_file():
            payloads[str(task["task_id"])] = formal._load_task_checkpoint(
                path, str(parent["contract_sha256"]), task
            )
            present_paths.append(path)
        else:
            missing.append(task)
    if len(payloads) != EXPECTED_PARENT_TASKS or len(missing) != EXPECTED_CHILD_TASKS:
        raise RecoveryContractError(
            f"expected 102 parent and 18 child tasks, got {len(payloads)} and {len(missing)}"
        )
    missing_ids = {str(task["task_id"]) for task in missing}
    if missing_ids != AUTHORIZED_CHILD_TASK_IDS:
        raise RecoveryContractError(
            "missing tasks differ from the explicitly authorized 18-task set: "
            f"missing={sorted(AUTHORIZED_CHILD_TASK_IDS - missing_ids)}, "
            f"extra={sorted(missing_ids - AUTHORIZED_CHILD_TASK_IDS)}"
        )
    return payloads, missing, checkpoint_hashes(present_paths, PARENT_OUTPUT)


def ensure_child_contract(
    child: Mapping[str, Any], missing: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    CHILD_OUTPUT.mkdir(parents=True, exist_ok=True)
    path = CHILD_OUTPUT / "contract.json"
    expected = {
        **dict(child),
        "source_commit_at_start": formal.git_head(),
        "recovery_schema": "setp.e7.parent_child_recovery.v1",
        "parent_contract_sha256": PARENT_CONTRACT_SHA256,
        "authorized_fix": "exact_trigger_charge_start_boundary",
        "recovery_task_ids": sorted(str(task["task_id"]) for task in missing),
    }
    if path.is_file():
        stored = read_json(path)
        comparable_stored = {
            key: value for key, value in stored.items() if key != "source_commit_at_start"
        }
        comparable_expected = {
            key: value for key, value in expected.items() if key != "source_commit_at_start"
        }
        if comparable_stored != comparable_expected:
            raise RecoveryContractError("existing child contract differs")
        return stored
    visible = [
        item
        for item in CHILD_OUTPUT.iterdir()
        if not item.name.startswith("._") and ".tmp-" not in item.name
    ]
    if visible:
        raise RecoveryContractError(
            f"child output is non-empty without a contract: {visible}"
        )
    formal.atomic_write_json(path, expected)
    return expected


def load_child_payloads(
    missing: Sequence[Mapping[str, Any]], child_hash: str
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    expected_ids = {str(task["task_id"]) for task in missing}
    task_dir = CHILD_OUTPUT / ".tasks"
    if task_dir.exists():
        unexpected = {
            path.stem
            for path in task_dir.glob("*.json")
            if not path.name.startswith("._") and path.stem not in expected_ids
        }
        if unexpected:
            raise RecoveryContractError(
                f"unexpected child checkpoints: {sorted(unexpected)}"
            )
    payloads: dict[str, dict[str, Any]] = {}
    pending: list[dict[str, Any]] = []
    for raw_task in missing:
        task = dict(raw_task)
        path = task_path(CHILD_OUTPUT, task)
        if path.is_file():
            payloads[str(task["task_id"])] = formal._load_task_checkpoint(
                path, child_hash, task
            )
        else:
            pending.append(task)
    return payloads, pending


def run_child_tasks(
    tasks: Sequence[Mapping[str, Any]], child_hash: str, workers: int
) -> dict[str, dict[str, Any]]:
    if not tasks:
        return {}
    results: dict[str, dict[str, Any]] = {}
    pool = ProcessPoolExecutor(max_workers=min(workers, len(tasks)))
    futures = {pool.submit(formal._run_task, dict(task)): dict(task) for task in tasks}
    try:
        for future in as_completed(futures):
            task = futures[future]
            payload = future.result()
            failures = formal.validate_task_payload(task, payload)
            formal._save_task_checkpoint(
                task_path(CHILD_OUTPUT, task), child_hash, task, payload
            )
            if failures:
                raise RecoveryContractError("; ".join(failures))
            results[str(task["task_id"])] = payload
    except BaseException:
        for future in futures:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        pool.shutdown(wait=True)
    return results


def assert_parent_unchanged(before: Mapping[str, str]) -> None:
    after_paths = [PARENT_OUTPUT / relative for relative in before]
    after = checkpoint_hashes(after_paths, PARENT_OUTPUT)
    if dict(before) != after:
        changed = sorted(
            key
            for key in set(before) | set(after)
            if before.get(key) != after.get(key)
        )
        raise RecoveryContractError(
            f"parent checkpoints changed during child recovery: {changed}"
        )


def assemble_final_evidence(
    *,
    parent_contract: Mapping[str, Any],
    child_contract: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
    parent_payloads: Mapping[str, Mapping[str, Any]],
    child_payloads: Mapping[str, Mapping[str, Any]],
    parent_hashes: Mapping[str, str],
    evaluations: int,
    workers: int,
    started_at_utc: str,
    elapsed_seconds: float,
) -> dict[str, Any]:
    child_paths = [
        task_path(CHILD_OUTPUT, task)
        for task in tasks
        if str(task["task_id"]) in child_payloads
    ]
    child_hashes = checkpoint_hashes(child_paths, CHILD_OUTPUT)
    runner_path = Path(__file__).resolve()
    proposal_path = ROOT / "docs/handoff/e7_exact_trigger_boundary_fix_proposal_20260716.md"
    anomaly_path = ROOT / "docs/handoff/e7_non_timing_anomaly_20260716.md"
    recovery_body = {
        "schema": "setp.e7.parent_child_recovery.contract.v1",
        "authorized_fix": "exact_trigger_charge_start_boundary",
        "parent_contract_sha256": str(parent_contract["contract_sha256"]),
        "child_contract_sha256": str(child_contract["contract_sha256"]),
        "parent_scheduler_sha256": PARENT_SCHEDULER_SHA256,
        "child_scheduler_sha256": CHILD_SCHEDULER_SHA256,
        "recovery_runner_sha256": formal.sha256(runner_path),
        "fix_proposal_sha256": formal.sha256(proposal_path),
        "anomaly_report_sha256": formal.sha256(anomaly_path),
        "authorized_child_task_ids": sorted(AUTHORIZED_CHILD_TASK_IDS),
        "parent_task_ids": sorted(parent_payloads),
        "evaluations": evaluations,
        "workers": workers,
        "result_direction_used_for_inclusion": False,
        "parent_tasks_may_be_rerun": False,
    }
    recovery_sha256 = formal.canonical_sha256(recovery_body)
    recovery_contract = {
        **recovery_body,
        "recovery_contract_sha256": recovery_sha256,
    }
    formal.atomic_write_json(PARENT_OUTPUT / "recovery_contract.json", recovery_contract)
    task_lineage_rows: list[dict[str, Any]] = []
    for task in tasks:
        task_id = str(task["task_id"])
        is_parent = task_id in parent_payloads
        payload = parent_payloads.get(task_id) or child_payloads[task_id]
        checkpoint = task_path(PARENT_OUTPUT if is_parent else CHILD_OUTPUT, task)
        task_lineage_rows.append(
            {
                "task_id": task_id,
                "network": task["network"],
                "condition": task["condition"],
                "stream": task["stream"],
                "arm": task["arm"],
                "lineage": "parent" if is_parent else "child",
                "source_contract_sha256": (
                    parent_contract["contract_sha256"]
                    if is_parent
                    else child_contract["contract_sha256"]
                ),
                "checkpoint_path": str(checkpoint.relative_to(ROOT)),
                "checkpoint_sha256": formal.sha256(checkpoint),
                "payload_sha256": formal.canonical_sha256(payload),
                "selection_reason": (
                    "present_before_preserved_anomaly"
                    if is_parent
                    else "missing_at_preserved_anomaly"
                ),
            }
        )
    lineage_body = {
        "schema": "setp.e7.parent_child_recovery.lineage.v1",
        "recovery_contract_sha256": recovery_sha256,
        "parent_contract_sha256": str(parent_contract["contract_sha256"]),
        "child_contract_sha256": str(child_contract["contract_sha256"]),
        "parent_checkpoint_count": len(parent_payloads),
        "child_checkpoint_count": len(child_payloads),
        "parent_checkpoint_hashes": dict(parent_hashes),
        "child_checkpoint_hashes": child_hashes,
        "task_lineage_sha256": formal.canonical_sha256(task_lineage_rows),
        "result_direction_used_for_inclusion": False,
    }
    formal.atomic_write_json(PARENT_OUTPUT / "recovery_lineage.json", lineage_body)
    formal.atomic_write_csv(PARENT_OUTPUT / "task_lineage.csv", task_lineage_rows)
    ordered = [
        dict(parent_payloads.get(str(task["task_id"])) or child_payloads[str(task["task_id"])])
        for task in tasks
    ]
    failures = formal.validate_complete_matrix(ordered, evaluations)
    successful = [item for item in ordered if item.get("execution_status") == "PASS"]
    halted = [
        item
        for item in ordered
        if item.get("execution_status") == "HALT_NO_EXECUTABLE_CONTINUATION"
    ]
    stage_rows = [row for item in successful for row in item["rows"]]
    session_rows = formal.build_session_summaries(successful)
    group_rows = formal.build_group_summaries(session_rows)
    policy_rows = formal.build_policy_comparisons(session_rows)
    comparison_rows = formal.build_comparison_summaries(policy_rows)
    verdict = (
        (
            "E7_FORMAL_EVIDENCE_COMPLETE_WITH_ARM_FAILURES"
            if halted
            else "E7_FORMAL_EVIDENCE_COMPLETE"
        )
        if not failures
        else "HALT_E7_FORMAL_EVIDENCE"
    )
    metadata = {
        "schema": formal.RUN_SCHEMA,
        "lineage_schema": "setp.e7.formal.parent_child.v1",
        "parent_contract_sha256": parent_contract["contract_sha256"],
        "child_contract_sha256": child_contract["contract_sha256"],
        "recovery_contract_sha256": recovery_sha256,
        "source_commit_at_parent_start": parent_contract.get("source_commit_at_start"),
        "source_commit_at_child_finish": formal.git_head(),
        "started_at_utc": started_at_utc,
        "finished_at_utc": now_utc(),
        "elapsed_seconds": elapsed_seconds,
        "workers": workers,
        "evaluations_per_search_call": evaluations,
        "task_count": len(ordered),
        "parent_task_count": len(parent_payloads),
        "child_task_count": len(child_payloads),
        "executable_task_count": len(successful),
        "no_executable_continuation_task_count": len(halted),
        "stage_row_count": len(stage_rows),
        "networks": list(formal.NETWORKS),
        "conditions": list(formal.CONDITIONS),
        "streams": list(formal.STREAMS),
        "arms": list(formal.ARMS),
        "physical_rules": child_contract["physical_rules"],
        "input_file_hashes": child_contract["input_file_hashes"],
        "source_file_hashes_by_contract": {
            "parent": parent_contract["source_file_hashes"],
            "child": child_contract["source_file_hashes"],
        },
        "recovery_lineage": {
            "path": "recovery_lineage.json",
            "sha256": formal.sha256(PARENT_OUTPUT / "recovery_lineage.json"),
            "task_lineage_path": "task_lineage.csv",
            "task_lineage_sha256": formal.sha256(PARENT_OUTPUT / "task_lineage.csv"),
        },
        "interpretation_boundary": (
            "The 102 parent checkpoints are preserved byte-for-byte and the 18 "
            "previously missing tasks are bound to the exact-trigger child contract. "
            "All frozen tasks and controlled failures remain in the evidence package."
        ),
    }
    decision = {
        "verdict": verdict,
        "failures": failures,
        "parent_contract_sha256": parent_contract["contract_sha256"],
        "child_contract_sha256": child_contract["contract_sha256"],
        "recovery_contract_sha256": recovery_sha256,
        "parent_task_count": len(parent_payloads),
        "child_task_count": len(child_payloads),
        "result_direction_used_for_inclusion": False,
        "scientific_interpretation_status": "PENDING_INDEPENDENT_AUDIT",
        "controlled_arm_failures": [
            {
                "network": item["network"],
                "responsibility_condition": item["responsibility_condition"],
                "stream_seed": item["stream_seed"],
                "arm": item["arm"],
                "failed_stage": item["failed_stage"],
                "failed_trigger_second": item["failed_trigger_second"],
                "failure_error": item["failure_error"],
            }
            for item in halted
        ],
    }
    formal.atomic_write_csv(PARENT_OUTPUT / "raw_runs.csv", stage_rows)
    formal.atomic_write_json(PARENT_OUTPUT / "sessions.json", ordered)
    formal.atomic_write_csv(PARENT_OUTPUT / "session_summary.csv", session_rows)
    if halted:
        formal.atomic_write_csv(
            PARENT_OUTPUT / "task_failures.csv",
            [
                {
                    "network": item["network"],
                    "responsibility_condition": item["responsibility_condition"],
                    "stream_seed": item["stream_seed"],
                    "arm": item["arm"],
                    "completed_stage_count": item["stages"],
                    "available_stage_count": item["available_stages"],
                    "failed_stage": item["failed_stage"],
                    "failed_trigger_second": item["failed_trigger_second"],
                    "evaluations": item["evaluations"],
                    "failure_error": item["failure_error"],
                }
                for item in halted
            ],
        )
    formal.atomic_write_csv(PARENT_OUTPUT / "summary_by_condition_arm.csv", group_rows)
    formal.atomic_write_csv(PARENT_OUTPUT / "paired_policy_comparisons.csv", policy_rows)
    formal.atomic_write_csv(
        PARENT_OUTPUT / "paired_policy_comparison_summary.csv", comparison_rows
    )
    formal.atomic_write_json(PARENT_OUTPUT / "metadata.json", metadata)
    formal.atomic_write_json(PARENT_OUTPUT / "decision.json", decision)
    report = [
        "# E7正式运行父—子谱系证据包",
        "",
        f"运行状态：`{verdict}`。",
        "",
        "原102个合法断点保持父合同和文件哈希不变；原异常时缺失的18个任务在恰逢触发边界修复后的子合同中执行。逐任务来源、载荷与断点哈希见`task_lineage.csv`，恢复授权和两份科学合同见`recovery_contract.json`。",
        "",
        f"120个冻结任务中，{len(successful)}个完成全日执行，{len(halted)}个在封闭预算下无可执行延续。所有任务和失败均原样进入汇总，不按结果方向筛选。",
        "",
        "本报告只确认父—子谱系与正式证据完整性；经济、时效、充电重放及论文结论仍等待独立审计。",
    ]
    if failures:
        report.extend(["", "未通过项：" + "；".join(failures)])
    formal._atomic_write_text(PARENT_OUTPUT / "report.md", "\n".join(report) + "\n")
    marker = {
        "schema": "setp.e7.formal.lineaged.finished.v1",
        "parent_contract_sha256": parent_contract["contract_sha256"],
        "child_contract_sha256": child_contract["contract_sha256"],
        "recovery_contract_sha256": recovery_sha256,
        "verdict": verdict,
        "finished_at_utc": now_utc(),
        "parent_task_count": len(parent_payloads),
        "child_task_count": len(child_payloads),
        "task_count": len(ordered),
    }
    formal.atomic_write_json(PARENT_OUTPUT / "RUN_FINISHED.json", marker)
    formal.atomic_write_json(
        PARENT_OUTPUT / "artifact_hashes.json",
        formal._artifact_hashes(PARENT_OUTPUT),
    )
    return decision


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluations", type=int, default=50)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--first-task-only", action="store_true")
    args = parser.parse_args(argv)
    if args.evaluations != 50:
        parser.error("authorized recovery requires exactly 50 evaluations")
    if args.workers != 6:
        parser.error("authorized recovery requires exactly 6 workers")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    started_at_utc = now_utc()
    started = time.perf_counter()
    parent_contract = read_json(PARENT_OUTPUT / "contract.json")
    child_contract = formal.build_contract(args.evaluations)
    validate_parent_child_contracts(parent_contract, child_contract)
    tasks = formal._expected_tasks(args.evaluations)
    parent_payloads, missing, parent_hashes = load_parent_partition(
        tasks, parent_contract
    )
    ensure_child_contract(child_contract, missing)
    child_payloads, pending = load_child_payloads(
        missing, str(child_contract["contract_sha256"])
    )
    if args.first_task_only:
        target = next(
            task for task in missing if str(task["task_id"]) == ORIGINAL_FAILURE_TASK_ID
        )
        if str(target["task_id"]) not in child_payloads:
            child_payloads.update(
                run_child_tasks([target], str(child_contract["contract_sha256"]), 1)
            )
        assert_parent_unchanged(parent_hashes)
        status = {
            "verdict": "PASS_ORIGINAL_FAILURE_TASK_RECOVERED",
            "task_id": ORIGINAL_FAILURE_TASK_ID,
            "parent_checkpoint_count": len(parent_payloads),
            "child_checkpoint_count": len(child_payloads),
            "remaining_child_tasks": EXPECTED_CHILD_TASKS - len(child_payloads),
            "parent_checkpoints_unchanged": True,
            "child_contract_sha256": child_contract["contract_sha256"],
        }
        formal.atomic_write_json(CHILD_OUTPUT / "recovery_status.json", status)
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0
    if pending:
        child_payloads.update(
            run_child_tasks(
                pending, str(child_contract["contract_sha256"]), args.workers
            )
        )
    if len(child_payloads) != EXPECTED_CHILD_TASKS:
        raise RecoveryContractError(
            f"child recovery is incomplete: {len(child_payloads)}/{EXPECTED_CHILD_TASKS}"
        )
    assert_parent_unchanged(parent_hashes)
    for name in FINAL_FILES:
        path = PARENT_OUTPUT / name
        if path.exists():
            raise RecoveryContractError(
                f"final evidence already exists; refusing overwrite: {path}"
            )
    decision = assemble_final_evidence(
        parent_contract=parent_contract,
        child_contract=child_contract,
        tasks=tasks,
        parent_payloads=parent_payloads,
        child_payloads=child_payloads,
        parent_hashes=parent_hashes,
        evaluations=args.evaluations,
        workers=args.workers,
        started_at_utc=started_at_utc,
        elapsed_seconds=time.perf_counter() - started,
    )
    assert_parent_unchanged(parent_hashes)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if not decision.get("failures") else 2


if __name__ == "__main__":
    raise SystemExit(main())
