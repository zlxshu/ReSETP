#!/usr/bin/env python3
"""Run the unique MPILS-MVNS-C2 G1 B-group second fire."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import run_g1_b_first_fire as first


REPO = Path(__file__).resolve().parents[3]
OUTPUT = (
    REPO
    / "baselines/algorithm_foundation/"
    "mpils_mvns_c2_g1_b_second_fire_20260720"
)
CONTRACT = (
    REPO
    / "docs/handoff/"
    "mpils_mvns_c2_g1_b_second_fire_contract_20260720.md"
)
WORKER = Path(__file__).resolve().parent / "run_g1_worker.py"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    first.OUTPUT = OUTPUT
    first.CONTRACT = CONTRACT
    first_result = first.main()

    decision_path = OUTPUT / "decision.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    passed = first_result == 0
    decision["verdict"] = (
        "PASS_G1_B_SECOND_FIRE_ZERO_LOSS_AT_LEAST_ONE_WIN"
        if passed
        else "STOP_MPILS_MVNS_C2_REPLACEMENT_LINE_AFTER_SECOND_FIRE"
    )
    decision["a_group_diagnosis_automatically_authorized"] = False
    decision["second_b_group_fire_used"] = True
    decision["g2_authorized"] = False
    decision["further_constant_revision_authorized"] = False
    write_json(decision_path, decision)

    metadata_path = OUTPUT / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["contract"] = "MPILS-MVNS-C2-G1-B-SECOND-FIRE"
    metadata["contract_path"] = CONTRACT.relative_to(REPO).as_posix()
    metadata["contract_sha256"] = sha256_file(CONTRACT)
    metadata["single_revision"] = {
        "trigger_after_before": 128,
        "cooldown_before": 128,
        "trigger_after_after": 1666,
        "cooldown_after": 1666,
        "worker_sha256": sha256_file(WORKER),
        "strength_rule_changed": False,
    }
    write_json(metadata_path, metadata)

    report_path = OUTPUT / "report.md"
    report = report_path.read_text(encoding="utf-8")
    report = report.replace(
        "# MPILS-MVNS-C2 G1 B组首发",
        "# MPILS-MVNS-C2 G1 B组唯一第二发",
    ).replace(
        "FAIL_G1_B_FIRST_FIRE__DIAGNOSIS_REQUIRED",
        str(decision["verdict"]),
    ).replace(
        "PASS_G1_B_FIRST_FIRE_ZERO_LOSS_AT_LEAST_ONE_WIN",
        str(decision["verdict"]),
    ).replace(
        "本门只是一种子、三道未被第一候选看过的开发题。",
        "本门是两发协议允许的唯一第二发。",
    ).replace(
        "失败则先做死因判断，不得直接救援。",
        "第二发失败即终止当前替换式扰动路线。",
    )
    report += (
        "\n唯一修订为停滞门和冷却期从128改为1666；其余算法与判据不变。"
        "第二发不通过即终止替换式扰动路线。\n"
    )
    report_path.write_text(report, encoding="utf-8")

    write_json(
        OUTPUT / "artifact_hashes.json",
        first.build_hash_manifest(OUTPUT),
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 3


if __name__ == "__main__":
    raise SystemExit(main())
