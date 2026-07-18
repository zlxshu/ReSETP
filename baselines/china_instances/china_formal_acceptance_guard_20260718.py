#!/usr/bin/env python3
"""Fail closed before any China formal-search launcher is allowed to run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
READINESS = (
    REPO / "data/ChinaInstances/china_stage2_g1_independent_readiness_v1_20260718"
    / "decision.json"
)
PENDING = (
    REPO / "data/ChinaInstances/china_stage2_pending_freezes_v1_20260718.json"
)
G1_FREEZE = REPO / "data/algorithm/G1_FORMAL_FREEZE.json"
FINAL_CHINA81 = REPO / "data/ChinaInstances/China81_FINAL/decision.json"


class GuardError(RuntimeError):
    """Formal China search is not authorized."""


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def evaluate(
    readiness_path: Path = READINESS,
    pending_path: Path = PENDING,
    g1_freeze_path: Path = G1_FREEZE,
    china81_path: Path = FINAL_CHINA81,
) -> dict[str, Any]:
    readiness = load(readiness_path)
    pending = load(pending_path)
    g1 = load(g1_freeze_path)
    china81 = load(china81_path)
    blockers: list[str] = []
    if readiness.get("open_blocker_count") != 0:
        blockers.append("STAGE2_READINESS_HAS_OPEN_BLOCKERS")
    unresolved = [
        row["id"]
        for row in pending.get("decisions", [])
        if row.get("approval_required") is True
    ]
    if unresolved:
        blockers.append("PENDING_USER_FREEZES:" + ",".join(unresolved))
    if g1.get("decision") != "PASS_G1_FORMALLY_FROZEN":
        blockers.append("G1_FORMAL_FREEZE_MISSING")
    if (
        china81.get("decision") != "PASS_CHINA81_FINAL_FROZEN"
        or china81.get("formal_search_allowed") is not True
    ):
        blockers.append("CHINA81_FINAL_FREEZE_MISSING")
    return {
        "schema": "resetp.china.formal-acceptance-guard.v1",
        "allowed": not blockers,
        "formal_search_allowed": not blockers,
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = evaluate()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["allowed"]:
        raise GuardError("formal China search blocked: " + "; ".join(result["blockers"]))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GuardError as error:
        print(f"HALT: {error}")
        raise SystemExit(2) from error
