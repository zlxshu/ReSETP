#!/usr/bin/env python3
"""Run frozen genuine-hybrid G0/probe/G1 after mechanical E2 release.

This wrapper reuses the registered v2 chain implementation. It changes only
the upstream prerequisite from the interim HGS-family paper-strength release
to the separately registered mechanical-integrity release and routes G1
through the corresponding v4 prerequisite amendment.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724"
REGISTRATION = PACKAGE / "g0_g1_mechanical_release_registration_v1.json"
OUT = PACKAGE / "g0_g1_mechanical_release_chain_v1"
MECHANICAL_GATE = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724/"
    "mechanical_release_gate_v1"
)
G1_RUNNER = PACKAGE / "run_g1_micro_gate_v4_mechanical.py"
G1_GATE = PACKAGE / "g1_micro_gate_v4_mechanical"

for path in (
    REPO / "baselines/e2_final_campaign_20260720",
    PACKAGE,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_genuine_hybrid_g0_g1_release_chain_v2 as frozen  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_registration() -> dict[str, Any]:
    registration = read_json(REGISTRATION)
    if (
        registration.get("schema")
        != "resetp.genuine-hybrid-g0-g1-mechanical-release-registration.v1"
    ):
        raise RuntimeError("unexpected mechanical G0/G1 registration schema")
    if registration.get("status") != "FROZEN_BEFORE_G0_AND_G1_RESULTS":
        raise RuntimeError("mechanical G0/G1 registration status drift")
    sources = registration.get("source_hashes")
    if not isinstance(sources, dict) or not sources:
        raise RuntimeError("mechanical G0/G1 registration has no source hashes")
    for relative, expected in sources.items():
        path = REPO / str(relative)
        if not path.is_file():
            raise RuntimeError(f"registered source missing: {relative}")
        actual = frozen.sha256(path)
        if actual != str(expected):
            raise RuntimeError(
                f"registered source drift: {relative}:{expected}:{actual}"
            )
    return registration


frozen.REGISTRATION = REGISTRATION
frozen.OUT = OUT
frozen.PROGRESS = OUT / "progress.json"
frozen.RELEASE_DECISION = MECHANICAL_GATE / "decision.json"
frozen.G1_RUNNER = G1_RUNNER
frozen.G1_GATE = G1_GATE
frozen.verify_registration = verify_registration


if __name__ == "__main__":
    raise SystemExit(frozen.main())
