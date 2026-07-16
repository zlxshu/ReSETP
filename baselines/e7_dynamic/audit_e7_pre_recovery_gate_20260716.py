#!/usr/bin/env python3
"""Read-only gate for the interrupted E7 formal run.

This audit never runs an E7 task and never edits the formal output.  It checks
the frozen files, the stored run contract, every visible task checkpoint, the
declared command contract, and the evidence-preserving boundary for an
approved scheduler bug fix.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "solver/src", ROOT / "models/src", ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from baselines.e7_dynamic import e7_formal_resumable_runner_20260715 as runner


FORMAL_OUT = ROOT / "baselines/e7_dynamic/e7_multinetwork_formal_20260715"
AUDIT_OUT = ROOT / "baselines/e7_dynamic/e7_pre_recovery_gate_20260716"
MONITOR_CONFIG = (
    ROOT
    / "baselines/e7_dynamic/monitor_configs/e7_multinetwork_formal_50_v2.json"
)
SHADOW_SCHEDULER = Path("/private/tmp/e7_full_mechanism_probe_shadow_20260716.py")
EXPECTED_PRESENT = 102
EXPECTED_MISSING = 18
EXPECTED_EVALUATIONS = 50
EXPECTED_WORKERS = 6

EXPECTED_PROTECTED_HASHES = {
    "baselines/e7_dynamic/e7_formal_dynamic_value_20260714.py":
        "579b7f3e8c2d34d102bae8a64ae007571fdc41383a4113e6e447a4b1c542d80f",
    "baselines/e7_dynamic/e7_formal_resumable_runner_20260715.py":
        "cebfc355a07d51cc5f98f3f4a41f606383c23031d9254dc1b94445e751b01a15",
    "baselines/e7_dynamic/e7_full_mechanism_probe_20260714.py":
        "0212c344024f95c9d13f7226f7b9ac7cfaab11f9e4244577d8191d37b5a629ed",
    "baselines/e7_dynamic/e7_multiday_zero_search_replay_20260715.py":
        "33b92d4c160c51f87bbd188a81b1c8086167faac0e4eb60ef506c083c2413dac",
    "baselines/e7_dynamic/e7_multinetwork_event_streams_v4_20260715/artifact_hashes.json":
        "a1c9bb2b39e66e5a545780f0323611cbd6dce6743d596b2beffb94b215b9e00e",
    "baselines/e7_dynamic/e7_multinetwork_event_streams_v4_20260715/metadata.json":
        "dbc1099bf69a2bb84137de0d0aac7add8762eef16edbc4f0b35d128f01adc210",
    "baselines/e7_dynamic/e7_multinetwork_event_streams_v4_20260715/responsibility_maps.csv":
        "6c17f0b1fcfcdf4bae6fb33399826afa94043b2886d478f75de9696022324c16",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    AUDIT_OUT.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "passed": passed, "detail": detail})
        if not passed:
            failures.append(f"{name}: {detail}")

    config = json.loads(MONITOR_CONFIG.read_text(encoding="utf-8"))
    contract_path = FORMAL_OUT / "contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract_sha = str(contract.get("contract_sha256", ""))

    protected_rows: list[dict[str, Any]] = []
    for relative, expected in EXPECTED_PROTECTED_HASHES.items():
        path = ROOT / relative
        actual = sha256(path) if path.is_file() else "MISSING"
        passed = actual == expected
        protected_rows.append(
            {"path": relative, "expected_sha256": expected, "actual_sha256": actual,
             "passed": passed}
        )
        record(f"protected_hash::{relative}", passed, actual)

    stored_body = {
        key: value
        for key, value in contract.items()
        if key not in {"contract_sha256", "source_commit_at_start"}
    }
    record(
        "stored_contract_hash",
        canonical_sha256(stored_body) == contract_sha,
        f"stored={contract_sha}; recomputed={canonical_sha256(stored_body)}",
    )
    record(
        "evaluations",
        int(contract.get("evaluations_per_search_call", -1)) == EXPECTED_EVALUATIONS,
        str(contract.get("evaluations_per_search_call")),
    )
    expected_matrix = (
        len(contract.get("networks", []))
        * len(contract.get("conditions", []))
        * len(contract.get("streams", []))
        * len(contract.get("arms", []))
    )
    record("matrix_size", expected_matrix == 120, str(expected_matrix))

    source_drift: list[str] = []
    for relative, expected in contract.get("source_file_hashes", {}).items():
        path = ROOT / relative
        actual = sha256(path) if path.is_file() else "MISSING"
        if actual != expected:
            source_drift.append(f"{relative}: {expected} -> {actual}")
    record("all_contract_sources", not source_drift, "; ".join(source_drift) or "match")

    input_drift: list[str] = []
    for relative, expected in contract.get("input_file_hashes", {}).items():
        path = ROOT / relative
        actual = sha256(path) if path.is_file() else "MISSING"
        if actual != expected:
            input_drift.append(f"{relative}: {expected} -> {actual}")
    record("all_contract_inputs", not input_drift, "; ".join(input_drift) or "match")

    required = set(config.get("required_command_substrings", []))
    required_expected = {
        "e7_formal_resumable_runner_20260715.py",
        "--evaluations", "50", "--workers", "6",
        "e7_multinetwork_formal_20260715",
    }
    record("monitor_command_contract", required_expected <= required, repr(sorted(required)))
    record(
        "monitor_output_directory",
        str(FORMAL_OUT / ".tasks") in config.get("checkpoint_paths", []),
        repr(config.get("checkpoint_paths", [])),
    )

    expected_tasks = runner._expected_tasks(EXPECTED_EVALUATIONS)
    task_rows: list[dict[str, Any]] = []
    present = 0
    missing = 0
    invalid = 0
    for task in expected_tasks:
        path = runner._task_path(FORMAL_OUT, task)
        row = {
            "task_id": task["task_id"],
            "network": task["network"],
            "condition": task["condition"],
            "stream": task["stream"],
            "arm": task["arm"],
            "evaluations": task["evaluations"],
        }
        if not path.is_file():
            row.update({"checkpoint_status": "MISSING", "error": ""})
            missing += 1
        else:
            try:
                payload = runner._load_task_checkpoint(path, contract_sha, task)
            except Exception as exc:  # audit must retain every validation error
                row.update({"checkpoint_status": "INVALID", "error": str(exc)})
                invalid += 1
            else:
                row.update(
                    {
                        "checkpoint_status": "PRESENT_VALID",
                        "error": "",
                        "execution_status": payload.get("execution_status"),
                        "stages": payload.get("stages"),
                    }
                )
                present += 1
        task_rows.append(row)

    visible = {
        path.name
        for path in (FORMAL_OUT / ".tasks").glob("*.json")
        if not path.name.startswith("._")
    }
    expected_names = {f"{task['task_id']}.json" for task in expected_tasks}
    unexpected = sorted(visible - expected_names)
    record("checkpoint_unexpected_files", not unexpected, repr(unexpected))
    record("checkpoint_valid_count", present == EXPECTED_PRESENT, str(present))
    record("checkpoint_missing_count", missing == EXPECTED_MISSING, str(missing))
    record("checkpoint_invalid_count", invalid == 0, str(invalid))

    result_names = ["raw_runs.csv", "decision.json", "artifact_hashes.json", "RUN_FINISHED.json"]
    existing_results = [name for name in result_names if (FORMAL_OUT / name).exists()]
    record("no_false_completion_files", not existing_results, repr(existing_results))

    shadow_hash = sha256(SHADOW_SCHEDULER) if SHADOW_SCHEDULER.is_file() else "MISSING"
    old_scheduler_rel = "baselines/e7_dynamic/e7_full_mechanism_probe_20260714.py"
    child_body = copy.deepcopy(stored_body)
    child_body["source_file_hashes"][old_scheduler_rel] = shadow_hash
    child_contract_sha = canonical_sha256(child_body)
    direct_resume_safe = child_contract_sha == contract_sha
    record(
        "direct_patch_resume_preserves_contract",
        direct_resume_safe,
        f"parent={contract_sha}; patched={child_contract_sha}; shadow={shadow_hash}",
    )

    # The last item is deliberately a recovery-design finding, not scene damage.
    scene_failures = [item for item in failures if not item.startswith(
        "direct_patch_resume_preserves_contract:"
    )]
    if scene_failures:
        verdict = "HALT_PRE_RECOVERY_SCENE_INVALID"
    elif not direct_resume_safe:
        verdict = "PASS_SCENE__HALT_DIRECT_PATCH_RESUME_CONTRACT_MISMATCH"
    else:
        verdict = "PASS_DIRECT_RECOVERY_READY"

    with (AUDIT_OUT / "raw_runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted({key for row in task_rows for key in row}))
        writer.writeheader()
        writer.writerows(task_rows)

    metadata = {
        "schema": "setp.e7.pre_recovery_gate.v1",
        "read_only": True,
        "formal_output": str(FORMAL_OUT.relative_to(ROOT)),
        "monitor_config": str(MONITOR_CONFIG.relative_to(ROOT)),
        "expected_contract_sha256": contract_sha,
        "expected_task_count": 120,
        "expected_present": EXPECTED_PRESENT,
        "expected_missing": EXPECTED_MISSING,
        "expected_evaluations": EXPECTED_EVALUATIONS,
        "expected_workers": EXPECTED_WORKERS,
        "shadow_scheduler_sha256": shadow_hash,
        "derived_patched_contract_sha256": child_contract_sha,
        "checks": checks,
        "protected_files": protected_rows,
    }
    decision = {
        "verdict": verdict,
        "scene_valid": not scene_failures,
        "direct_patch_resume_safe": direct_resume_safe,
        "present_valid_checkpoints": present,
        "missing_checkpoints": missing,
        "invalid_checkpoints": invalid,
        "scene_failures": scene_failures,
        "recovery_design_requirement": (
            "Do not patch and invoke the original runner directly.  An explicitly "
            "authorized parent-child recovery contract must preserve the 102 parent "
            "checkpoints unchanged, bind the 18 new checkpoints to the patched child "
            "contract, and assemble both lineages without rewriting either set."
            if not direct_resume_safe else "none"
        ),
    }
    write_json(AUDIT_OUT / "metadata.json", metadata)
    write_json(AUDIT_OUT / "decision.json", decision)

    report = [
        "# E7恢复前只读闸门（2026-07-16）",
        "",
        f"判决：`{verdict}`。",
        "",
        f"现场共有{present}/120个合法断点、{missing}个缺口、{invalid}个无效断点。"
        "全部正式结果文件仍不存在，因此不能把本次运行视为完成。",
        "",
        "7个保护面、合同列出的全部源码和全部输入均按原合同复核。"
        "本审计没有运行任务，也没有修改正式输出或受保护源码。",
        "",
        "单行边界修复会改变调度器哈希，并进一步改变正式合同哈希。"
        f"旧合同为`{contract_sha}`，影子修复推导出的子合同为"
        f"`{child_contract_sha}`。因此直接修改保护源后调用原runner，必然拒绝"
        "102个旧合同断点；若绕过该拒绝，则会把两套代码语义混成一个合同，同样不可接受。",
        "",
        "下一步必须先由用户授权一份父—子恢复合同：旧102个断点只读保留，"
        "剩余18个任务写入独立子合同断点区，最终汇总同时记录每行来源合同；"
        "不得删除、改写或重新筛选旧断点。",
    ]
    (AUDIT_OUT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    artifact_hashes = {
        path.name: sha256(path)
        for path in sorted(AUDIT_OUT.iterdir())
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }
    write_json(AUDIT_OUT / "artifact_hashes.json", artifact_hashes)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if not scene_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
