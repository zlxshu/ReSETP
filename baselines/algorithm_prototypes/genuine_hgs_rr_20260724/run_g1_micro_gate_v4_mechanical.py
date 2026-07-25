#!/usr/bin/env python3
"""Run the frozen G1 v3 algorithm under the mechanical-release amendment.

Only the upstream release evidence changes: the corrected E2 campaign and
all witnesses are mechanically valid, while the old HGS-family result-strength
gate held. Algorithms, instances, seeds, budgets, workers, operators, and G1
acceptance gates remain byte-for-byte those registered in v3.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import sys
from typing import Any


PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[2]
AMENDMENT = PACKAGE / "g1_micro_preregistration_v4_mechanical.json"
BASE_PREREGISTRATION = PACKAGE / "g1_micro_preregistration_v3.json"
MECHANICAL_GATE = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v7_small_archive_ledger_20260724/"
    "mechanical_release_gate_v1"
)

if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

import run_g1_micro_gate as frozen  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def unchanged_fields_sha256(payload: dict[str, Any]) -> str:
    unchanged = dict(payload)
    for key in (
        "schema",
        "registered_at",
        "status",
        "supersedes_before_execution",
        "required_v7_release_decision",
    ):
        unchanged.pop(key, None)
    encoded = json.dumps(
        unchanged,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_preregistration_v4() -> dict[str, Any]:
    amendment = read_json(AMENDMENT)
    if (
        amendment.get("schema")
        != "resetp.coop-hgs-rr-g1-preregistration-amendment.v4"
    ):
        raise RuntimeError("unexpected G1 mechanical amendment schema")
    if (
        amendment.get("status")
        != "FROZEN_AFTER_MECHANICAL_RELEASE_BEFORE_G1_RESULTS"
    ):
        raise RuntimeError("G1 mechanical amendment status drift")
    if frozen.sha256(BASE_PREREGISTRATION) != amendment["base_preregistration"][
        "sha256"
    ]:
        raise RuntimeError("G1 v3 base preregistration hash drift")
    for relative, expected in amendment["amendment_source_hashes"].items():
        path = REPO / str(relative)
        if not path.is_file():
            raise RuntimeError(f"G1 amendment source missing: {relative}")
        actual = frozen.sha256(path)
        if actual != str(expected):
            raise RuntimeError(
                f"G1 amendment source drift: {relative}:{expected}:{actual}"
            )
    base = read_json(BASE_PREREGISTRATION)
    if base.get("schema") != "resetp.coop-hgs-rr-g1-preregistration.v3":
        raise RuntimeError("unexpected G1 v3 base schema")
    if unchanged_fields_sha256(base) != amendment["unchanged_fields_sha256"]:
        raise RuntimeError("G1 unchanged scientific fields hash drift")
    merged = dict(base)
    merged["required_v7_release_decision"] = amendment[
        "required_mechanical_release_decision"
    ]
    merged["release_evidence_amendment"] = {
        "base_preregistration_sha256": amendment["base_preregistration"][
            "sha256"
        ],
        "mechanical_registration_sha256": amendment[
            "mechanical_registration_sha256"
        ],
        "unchanged_fields_sha256": amendment["unchanged_fields_sha256"],
    }
    return merged


frozen.PREREGISTRATION = AMENDMENT
frozen.WORK = PACKAGE / "g1_micro_work_v4_mechanical"
frozen.OUT = PACKAGE / "g1_micro_gate_v4_mechanical"
frozen.RELEASE_DECISION = MECHANICAL_GATE / "decision.json"
frozen.RELEASE_VERDICT = "PASS_E2_V7_MECHANICAL_INTEGRITY_RELEASE"
frozen.load_preregistration = load_preregistration_v4


if __name__ == "__main__":
    raise SystemExit(frozen.main())
