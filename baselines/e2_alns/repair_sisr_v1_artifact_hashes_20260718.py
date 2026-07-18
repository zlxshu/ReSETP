#!/usr/bin/env python3
"""Repair the superseded SISR-v1 evidence hash ledger after AppleDouble cleanup."""

from __future__ import annotations

from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from baselines.e2_alns.run_homberger_g1_sisr_20260718 import (  # noqa: E402
    atomic_json,
    clean_generated_appledouble,
    sha256,
)


OUTPUT = REPO / "baselines/e2_alns/homberger_g1_sisr_micro_20260718"
ABORTED = (
    REPO
    / "baselines/e2_alns"
    / "homberger_g1_sisr_micro_v2_20260718_aborted_path_bug"
)


def main() -> int:
    clean_generated_appledouble(OUTPUT)
    clean_generated_appledouble(ABORTED)
    fixed_sources = [
        REPO / "docs/handoff/e2_alns_g1_sisr_task_card_20260718.md",
        REPO
        / "solver/src/setp_solver/algorithms/resetp_alns/operators"
        / "sisr_string_removal.py",
        REPO
        / "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
        REPO / "baselines/e2_alns/run_homberger_g1_sisr_20260718.py",
        Path(__file__).resolve(),
    ]
    evidence = [
        OUTPUT / name
        for name in (
            "metadata.json",
            "task_contract.json",
            "raw_runs.csv",
            "paired_results.json",
            "decision.json",
            "report.md",
            "audit_correction.json",
        )
    ]
    solutions = sorted((OUTPUT / "solutions").glob("*.json"))
    paths = fixed_sources + evidence + solutions
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "missing SISR-v1 evidence: "
            + ", ".join(str(path.relative_to(REPO)) for path in missing)
        )
    hashes = {
        str(path.relative_to(REPO)): sha256(path)
        for path in paths
    }
    atomic_json(OUTPUT / "artifact_hashes.json", hashes)
    clean_generated_appledouble(OUTPUT)
    clean_generated_appledouble(ABORTED)
    print(
        {
            "verdict": "REPAIRED_SUPERSEDED_EVIDENCE_LEDGER",
            "hash_count": len(hashes),
            "appledouble_remaining": len(
                list(OUTPUT.rglob("._*")) + list(ABORTED.rglob("._*"))
            ),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
