#!/usr/bin/env python3
"""Zero-search audit of post-run record synchronization."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
GATE = HERE / "public_bks_microgate"
INDEPENDENT = HERE / "public_bks_microgate_independent_audit"
OUT = HERE / "postrun_record_sync_audit"
MUTABLE_RECORDS = {
    "docs/handoff/hgs_adaptive_elite_alns_contract_20260719.md",
    "docs/handoff/algorithm_source_and_license_register_20260719.md",
    "docs/handoff/model_change_approval_register_20260718.md",
}
HANDOFF = REPO / "HANDOFF.md"
PROJECT_MEMORY = REPO / "docs/handoff/memory/MEMORY.md"
PRD_MEMORY = REPO / "docs/handoff/memory/project-prd-execution-v2.md"
FORENSICS = REPO / (
    "docs/handoff/hgs_aealns_03_forensics_and_next_decision_20260719.md"
)


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite: {OUT}")
    rows: list[dict[str, Any]] = []
    gate_metadata = _json(GATE / "metadata.json")
    gate_decision = _json(GATE / "decision.json")
    audit_decision = _json(INDEPENDENT / "decision.json")

    _check(
        rows,
        "gate_artifacts_unchanged",
        _verify_manifest(GATE),
        str(GATE.relative_to(REPO)),
    )
    _check(
        rows,
        "independent_audit_artifacts_unchanged",
        _verify_manifest(INDEPENDENT),
        str(INDEPENDENT.relative_to(REPO)),
    )
    immutable_sources = {
        relative: digest
        for relative, digest
        in gate_metadata["source_hashes"].items()
        if relative not in MUTABLE_RECORDS
    }
    _check(
        rows,
        "immutable_source_hashes",
        _verify_paths(immutable_sources),
        f"paths={len(immutable_sources)}",
    )
    _check(
        rows,
        "protected_hashes",
        _verify_paths(gate_metadata["protected_hashes"]),
        f"paths={len(gate_metadata['protected_hashes'])}",
    )
    _check(
        rows,
        "input_hashes",
        _verify_paths(gate_metadata["input_hashes"]),
        f"paths={len(gate_metadata['input_hashes'])}",
    )
    contract = (
        REPO
        / "docs/handoff/hgs_adaptive_elite_alns_contract_20260719.md"
    ).read_text(encoding="utf-8")
    approval = (
        REPO
        / "docs/handoff/model_change_approval_register_20260718.md"
    ).read_text(encoding="utf-8")
    sources = (
        REPO
        / "docs/handoff/algorithm_source_and_license_register_20260719.md"
    ).read_text(encoding="utf-8")
    _check(
        rows,
        "contract_finalized",
        "EXECUTED_STOP_HGS_AEALNS_03_ANY_LOSS" in contract
        and "2胜2平2负" in contract,
        "contract terminal status",
    )
    _check(
        rows,
        "approval_finalized",
        "EXECUTED_STOP_HGS_AEALNS_03_ANY_LOSS" in approval
        and "EA-HYBRID-005" in approval,
        "approval terminal status and new-approval boundary",
    )
    _check(
        rows,
        "source_register_finalized",
        "STOP_HGS_AEALNS_03_ANY_LOSS" in sources
        and all(
            token in sources
            for token in (
                "10.1287/opre.1120.1048",
                "10.1287/ijoc.2023.0055",
                "10.1287/trsc.1050.0135",
                "10.1287/ijoc.2023.0106",
                "2506.03172",
            )
        ),
        "result, citations and licenses retained",
    )
    _check(
        rows,
        "handoff_finalized",
        "新一代内嵌混合候选" in HANDOFF.read_text(encoding="utf-8")
        and "STOP_HGS_AEALNS_03_ANY_LOSS"
        in HANDOFF.read_text(encoding="utf-8"),
        str(HANDOFF.relative_to(REPO)),
    )
    _check(
        rows,
        "memory_finalized",
        all(
            "HGS-AEALNS-03 公开最小门"
            in path.read_text(encoding="utf-8")
            for path in (PROJECT_MEMORY, PRD_MEMORY)
        ),
        "both project memory surfaces",
    )
    _check(
        rows,
        "forensics_present",
        FORENSICS.is_file()
        and "时间窗" in FORENSICS.read_text(encoding="utf-8")
        and "固定车辆成本" in FORENSICS.read_text(encoding="utf-8")
        and "EA-HYBRID-005" in FORENSICS.read_text(encoding="utf-8"),
        str(FORENSICS.relative_to(REPO)),
    )
    _check(
        rows,
        "stop_decisions_preserved",
        gate_decision.get("verdict")
        == "STOP_HGS_AEALNS_03_ANY_LOSS"
        and gate_decision.get("strong_positive") is False
        and audit_decision.get("verdict")
        == "PASS_HGS_AEALNS_03_ZERO_SEARCH_AUDIT_STOP_PRESERVED",
        "gate stop and independent audit pass",
    )
    _check(
        rows,
        "scope_closed",
        all(
            gate_decision.get(field) is False
            for field in (
                "additional_public_run_allowed",
                "formal_56_instance_run_allowed",
                "china81_run_allowed",
                "stage2_allowed",
            )
        ),
        "no automatic escalation",
    )

    failures = [row for row in rows if not bool(row["passed"])]
    decision = {
        "verdict": (
            "PASS_HGS_AEALNS_03_POSTRUN_RECORD_SYNC_ZERO_SEARCH"
            if not failures
            else "FAIL_HGS_AEALNS_03_POSTRUN_RECORD_SYNC"
        ),
        "checks": len(rows),
        "passed": len(rows) - len(failures),
        "failed": len(failures),
        "failures": failures,
        "search_evaluations": 0,
        "solver_reruns": 0,
        "candidate_status": "STOP_HGS_AEALNS_03_ANY_LOSS",
        "china81_run_allowed": False,
        "stage2_allowed": False,
    }
    metadata = {
        "schema_version": "resetp.hgs-aealns-03-postrun-sync.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_short": _git("status", "--short"),
        "audit_script_sha256": _sha(Path(__file__).resolve()),
        "gate_metadata_sha256": _sha(GATE / "metadata.json"),
        "gate_decision_sha256": _sha(GATE / "decision.json"),
        "independent_audit_decision_sha256": _sha(
            INDEPENDENT / "decision.json"
        ),
        "intentional_postrun_mutable_records": sorted(MUTABLE_RECORDS),
        "search_evaluations": 0,
        "solver_reruns": 0,
    }
    report = "\n".join(
        [
            "# HGS-AEALNS-03 赛后记录同步审计",
            "",
            f"- 判决：`{decision['verdict']}`",
            f"- 检查：{decision['passed']}/{decision['checks']} 通过。",
            "- 新增搜索/求解器重跑：0/0。",
            "- 算法源码、输入和保护面继续匹配开跑前哈希。",
            "- 合同、审批和来源登记的变化仅用于写入赛后停止结论。",
            "- China81、正式56题和阶段二仍关闭。",
            "",
        ]
    )
    OUT.mkdir(parents=True)
    _write_csv(OUT / "raw_runs.csv", rows)
    _write_json(OUT / "metadata.json", metadata)
    _write_json(OUT / "decision.json", decision)
    (OUT / "report.md").write_text(report, encoding="utf-8")
    _write_json(
        OUT / "artifact_hashes.json",
        {
            path.name: _sha(path)
            for path in sorted(OUT.iterdir())
            if path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if not failures else 1


def _verify_paths(expected: dict[str, str]) -> bool:
    return all(
        (REPO / relative).is_file()
        and _sha(REPO / relative) == digest
        for relative, digest in expected.items()
    )


def _verify_manifest(root: Path) -> bool:
    expected = _json(root / "artifact_hashes.json")
    return all(
        (root / name).is_file()
        and _sha(root / name) == digest
        for name, digest in expected.items()
    )


def _check(
    rows: list[dict[str, Any]],
    check: str,
    passed: bool,
    detail: str,
) -> None:
    rows.append(
        {
            "check": check,
            "passed": bool(passed),
            "detail": detail,
            "search_evaluations": 0,
        }
    )


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=REPO,
        text=True,
    ).strip()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
