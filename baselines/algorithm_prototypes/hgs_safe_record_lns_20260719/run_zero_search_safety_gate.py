#!/usr/bin/env python3
"""Run the pre-registered zero-search safety gate for HGS-SAFE-RECORD-LNS-04."""

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
OUT = HERE / "zero_search_safety_gate"
PYTHON = REPO / "build/python_envs/pyvrp-hgs-0.12.2/bin/python"
WORKER = HERE / "safe_record_lns_worker.py"
TEST = HERE / "test_safe_record_lns.py"
CONTRACT = REPO / "docs/handoff/hgs_safe_record_lns_contract_20260719.md"
SOURCE_REGISTER = REPO / (
    "docs/handoff/algorithm_source_and_license_register_20260719.md"
)
APPROVAL_REGISTER = REPO / (
    "docs/handoff/model_change_approval_register_20260718.md"
)
SOURCES = (
    Path(__file__).resolve(),
    WORKER,
    TEST,
    CONTRACT,
    SOURCE_REGISTER,
    APPROVAL_REGISTER,
)
PROTECTED = (
    REPO / "solver/src/setp_solver/cost.py",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
    REPO
    / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
)


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite: {OUT}")
    source_hashes = _hash_map(SOURCES)
    protected_hashes = _hash_map(PROTECTED)
    completed = subprocess.run(
        [
            str(PYTHON),
            "-m",
            "unittest",
            "-v",
            TEST.name,
        ],
        cwd=HERE,
        capture_output=True,
        text=True,
        timeout=30.0,
        check=False,
    )
    output = completed.stdout + completed.stderr
    source_unchanged = source_hashes == _hash_map(SOURCES)
    protected_unchanged = protected_hashes == _hash_map(PROTECTED)
    six_tests = (
        completed.returncode == 0
        and "Ran 6 tests" in output
        and output.count(" ... ok") == 6
    )
    contract = CONTRACT.read_text(encoding="utf-8")
    contract_locked = all(
        token in contract
        for token in (
            "C105",
            "C204",
            "R108",
            "R207",
            "RC104",
            "RC204",
            "0负且至少2题严格胜",
            "seed2、seed3",
        )
    )
    checks = [
        {
            "check": "six_safety_unit_tests",
            "passed": six_tests,
            "detail": output.strip(),
            "search_evaluations": 0,
        },
        {
            "check": "source_hashes_unchanged",
            "passed": source_unchanged,
            "detail": f"paths={len(SOURCES)}",
            "search_evaluations": 0,
        },
        {
            "check": "protected_hashes_unchanged",
            "passed": protected_unchanged,
            "detail": f"paths={len(PROTECTED)}",
            "search_evaluations": 0,
        },
        {
            "check": "fresh_gate_contract_locked",
            "passed": contract_locked,
            "detail": "six fifth-last holdouts and two-stage rule",
            "search_evaluations": 0,
        },
    ]
    failures = [row for row in checks if not bool(row["passed"])]
    decision = {
        "verdict": (
            "PASS_HGS_SAFE_RECORD_LNS_ZERO_SEARCH_SAFETY"
            if not failures
            else "FAIL_HGS_SAFE_RECORD_LNS_ZERO_SEARCH_SAFETY"
        ),
        "checks": len(checks),
        "passed": len(checks) - len(failures),
        "failed": len(failures),
        "failures": failures,
        "search_evaluations": 0,
        "performance_gate_allowed": not failures,
        "china81_run_allowed": False,
        "stage2_allowed": False,
    }
    metadata = {
        "schema_version": "resetp.hgs-safe-record-lns-zero-search.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_short": _git("status", "--short"),
        "python": str(PYTHON),
        "source_hashes": source_hashes,
        "protected_hashes": protected_hashes,
        "search_evaluations": 0,
        "claim_boundary": (
            "Static and unit safety evidence only. This does not establish "
            "quality, runtime superiority, or any win over pure HGS."
        ),
    }
    report = "\n".join(
        [
            "# HGS-SAFE-RECORD-LNS-04 零搜索安全门",
            "",
            f"- 判决：`{decision['verdict']}`",
            f"- 检查：{decision['passed']}/{decision['checks']} 通过。",
            "- 搜索评价：0。",
            "- 已覆盖时间窗过滤、新车固定费、路线数上限、全局记录门、"
            "禁用路径和独立随机流。",
            "- 通过只允许一次全新原始BKS单种子门，不表示算法已经胜HGS。",
            "",
        ]
    )
    OUT.mkdir(parents=True)
    _write_csv(OUT / "raw_runs.csv", checks)
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


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hash_map(paths: tuple[Path, ...]) -> dict[str, str]:
    return {
        str(path.relative_to(REPO)): _sha(path)
        for path in paths
    }


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
