#!/usr/bin/env python3
"""Fail-closed China81-only private-performance gate preflight.

This file deliberately imports no solver.  It may arm a future China81 run
only after both the authoritative China acceptance guard and the public hybrid
development prerequisite pass.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = HERE / "china81_private_fair_gate_preflight"
GUARD_PATH = (
    REPO
    / "baselines/china_instances/"
    "china_formal_acceptance_guard_20260718.py"
)
PUBLIC_CANDIDATES = (
    HERE / "public_bks_alns_warm_hgs_gate/decision.json",
    HERE / "public_bks_dual_elite_hgs_gate/decision.json",
)
FINAL_CHINA81 = REPO / "data/ChinaInstances/China81_FINAL/decision.json"
CONTRACT = REPO / (
    "docs/handoff/outcome_first_multiengine_hybrid_contract_20260719.md"
)
SOURCES = (
    Path(__file__).resolve(),
    GUARD_PATH,
    CONTRACT,
)


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite: {OUT}")
    source_hashes = _hash_map(SOURCES)
    guard = _load_guard()
    public = [
        {
            "path": str(path.relative_to(REPO)),
            "sha256": _sha(path),
            "decision": _read_json(path),
        }
        for path in PUBLIC_CANDIDATES
    ]
    public_winner = next(
        (
            item
            for item in public
            if item["decision"].get("strong_positive") is True
        ),
        None,
    )
    blockers = list(guard.get("blockers", []))
    if public_winner is None:
        blockers.append("NO_PUBLIC_HYBRID_STRONG_POSITIVE")
    if not FINAL_CHINA81.is_file():
        blockers.append("CHINA81_FINAL_DIRECTORY_NOT_PRESENT")
    allowed = not blockers
    if allowed:
        raise RuntimeError(
            "preflight unexpectedly armed; formal runner is intentionally "
            "not implemented in phase 1"
        )

    rows = [
        {
            "check": "china_formal_acceptance_guard",
            "passed": bool(guard.get("allowed")),
            "detail": ";".join(guard.get("blockers", [])),
            "search_evaluations": 0,
        },
        {
            "check": "public_hybrid_strong_positive",
            "passed": public_winner is not None,
            "detail": (
                str(public_winner["path"])
                if public_winner is not None
                else "both frozen public hybrid candidates stopped"
            ),
            "search_evaluations": 0,
        },
        {
            "check": "china81_final_freeze",
            "passed": FINAL_CHINA81.is_file(),
            "detail": str(FINAL_CHINA81.relative_to(REPO)),
            "search_evaluations": 0,
        },
    ]
    decision = {
        "verdict": "HALT_CHINA81_PRIVATE_GATE_NOT_ARMED",
        "allowed": False,
        "formal_search_allowed": False,
        "search_evaluations": 0,
        "blockers": blockers,
        "china_guard": guard,
        "public_candidate_verdicts": {
            item["path"]: item["decision"].get("verdict")
            for item in public
        },
        "planned_scope": {
            "private_instances": "China81 only",
            "other_private_instances_allowed": False,
            "planned_arms": [
                "final_mechanism_hybrid",
                "pure_pyvrp_hgs_with_common_resetp_completion",
                "pure_project_alns",
            ],
            "fairness": (
                "same frozen China81, seeds, complete-model checker, "
                "completion adapter, complete-evaluation ledger and wall time"
            ),
        },
        "next_action": (
            "user_review_public_hybrid_failure; do not run China81 or stage2"
        ),
        "stage2_allowed": False,
    }
    metadata = {
        "schema_version": "resetp.china81-private-fair-gate-preflight.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_short": _git("status", "--short"),
        "source_hashes": source_hashes,
        "guard_path": str(GUARD_PATH.relative_to(REPO)),
        "public_candidate_paths": [
            str(path.relative_to(REPO))
            for path in PUBLIC_CANDIDATES
        ],
        "solver_imported": False,
        "search_evaluations": 0,
        "claim_boundary": (
            "Fail-closed infrastructure proof only. No China81 instance was "
            "loaded and no solver, completion adapter or search was called."
        ),
    }
    report = "\n".join(
        [
            "# China81 私有公平门预检",
            "",
            f"- 判决：`{decision['verdict']}`",
            "- 搜索评价：`0`。",
            "- 私有性能范围只允许 China81；没有加载任何其他私有算例。",
            "- 当前 China 正式门未开放，且两个公开混合候选均未取得强阳性。",
            "- 因此运行器在导入求解器之前停止；没有启动 China81 或阶段二。",
            "",
            "阻断：",
            "",
            *[f"- `{item}`" for item in blockers],
            "",
        ]
    )
    OUT.mkdir(parents=True)
    _write_csv(OUT / "raw_runs.csv", rows)
    _write_json(OUT / "metadata.json", metadata)
    _write_json(OUT / "decision.json", decision)
    (OUT / "report.md").write_text(
        report.rstrip() + "\n",
        encoding="utf-8",
    )
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
    return 0


def _load_guard() -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location(
        "china_formal_acceptance_guard_for_hybrid_preflight",
        GUARD_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {GUARD_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.evaluate()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _hash_map(paths: tuple[Path, ...]) -> dict[str, str]:
    return {
        str(path.relative_to(REPO)): _sha(path)
        for path in paths
    }


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=REPO,
        text=True,
    ).strip()


if __name__ == "__main__":
    raise SystemExit(main())
