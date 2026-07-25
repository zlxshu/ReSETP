#!/usr/bin/env python3
"""Run frozen G1 after the registered real-bundle decoder wiring repair."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[2]
AMENDMENT = PACKAGE / "g1_micro_preregistration_v5_decoder_repair.json"
BASE_V3 = PACKAGE / "g1_micro_preregistration_v3.json"
BASE_V4 = PACKAGE / "g1_micro_preregistration_v4_mechanical.json"
G0_V2_REGISTRATION = PACKAGE / "g0_real_bundle_preregistration_v2.json"
G0_V2_GATE = PACKAGE / "g0_real_bundle_gate_v2"
WORKER_PROBE_V2 = PACKAGE / "g1_six_worker_resource_probe_v2"
MECHANICAL_GATE = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724/"
    "mechanical_release_gate_v1"
)

if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

import run_g0_real_bundle_preflight_v2 as g0_v2  # noqa: E402
import run_g1_micro_gate_v4_mechanical as mechanical  # noqa: E402


frozen = mechanical.frozen


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_preregistration_v5() -> dict[str, Any]:
    amendment = read_json(AMENDMENT)
    if (
        amendment.get("schema")
        != "resetp.coop-hgs-rr-g1-preregistration-amendment.v5"
    ):
        raise RuntimeError("unexpected G1 v5 amendment schema")
    if amendment.get("status") != "FROZEN_BEFORE_G1_V5_RESULTS":
        raise RuntimeError("G1 v5 amendment status drift")
    for path, field in (
        (BASE_V3, "base_v3_sha256"),
        (BASE_V4, "base_v4_sha256"),
        (G0_V2_REGISTRATION, "g0_v2_registration_sha256"),
    ):
        if frozen.sha256(path) != amendment[field]:
            raise RuntimeError(f"G1 v5 registered evidence drift: {path.name}")
    for relative, expected in amendment["execution_source_hashes"].items():
        path = REPO / relative
        if not path.is_file():
            raise RuntimeError(f"G1 v5 source missing: {relative}")
        actual = frozen.sha256(path)
        if actual != expected:
            raise RuntimeError(
                f"G1 v5 source drift: {relative}:{expected}:{actual}"
            )

    merged = mechanical.load_preregistration_v4()
    merged["source_hashes"] = dict(amendment["execution_source_hashes"])
    merged["required_g0_decision"] = amendment["required_g0_decision"]
    configuration = deepcopy(merged["frozen_configuration"])
    configuration["worker_selection"] = deepcopy(
        amendment["worker_selection_v2"]
    )
    merged["frozen_configuration"] = configuration
    merged["decoder_repair_amendment"] = {
        "approval_id": amendment["approval_id"],
        "g0_v2_registration_sha256": amendment[
            "g0_v2_registration_sha256"
        ],
        "repair_scope": amendment["repair_scope"],
        "unchanged_scientific_contract": amendment[
            "unchanged_scientific_contract"
        ],
    }
    merged["claim_boundary"] = amendment["claim_boundary"]
    return merged


frozen.PREREGISTRATION = AMENDMENT
frozen.G0_PREREGISTRATION = G0_V2_REGISTRATION
frozen.G0_GATE = G0_V2_GATE
frozen.WORKER_PROBE = WORKER_PROBE_V2
frozen.WORK = PACKAGE / "g1_micro_work_v5_decoder_repair"
frozen.OUT = PACKAGE / "g1_micro_gate_v5_decoder_repair"
frozen.RELEASE_DECISION = MECHANICAL_GATE / "decision.json"
frozen.RELEASE_VERDICT = "PASS_E2_V7_MECHANICAL_INTEGRITY_RELEASE"
frozen.real_bundle_gate = g0_v2.frozen
frozen.load_preregistration = load_preregistration_v5


def write_done() -> None:
    decision = read_json(frozen.OUT / "decision.json")
    frozen.write_json(
        frozen.OUT / "done.json",
        {
            "schema": "resetp.coop-hgs-rr-g1-done.v5",
            "decision": decision["decision"],
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "task_count": 9,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-contract", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.check_contract:
        return frozen.check_contract()
    frozen.require_worker_count(args.workers)
    result = frozen.execute(args.workers)
    write_done()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
