#!/usr/bin/env python3
"""Run G0 after narrowing the route-local coverage exception."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[2]
AMENDMENT = PACKAGE / "g0_real_bundle_preregistration_v3.json"
BASE_PREREGISTRATION = PACKAGE / "g0_real_bundle_preregistration_v1.json"

if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

import run_g0_real_bundle_preflight as frozen  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_preregistration_v3() -> dict[str, Any]:
    amendment = read_json(AMENDMENT)
    if (
        amendment.get("schema")
        != "resetp.coop-hgs-rr-g0-real-bundle-amendment.v3"
    ):
        raise RuntimeError("unexpected G0 v3 amendment schema")
    if amendment.get("status") != "FROZEN_BEFORE_G0_V3_EXECUTION":
        raise RuntimeError("G0 v3 amendment status drift")
    if frozen.sha256(BASE_PREREGISTRATION) != amendment[
        "base_preregistration"
    ]["sha256"]:
        raise RuntimeError("G0 v1 preregistration hash drift")
    for relative, expected in amendment["source_hashes"].items():
        path = REPO / str(relative)
        if not path.is_file():
            raise RuntimeError(f"G0 v3 source missing: {relative}")
        actual = frozen.sha256(path)
        if actual != str(expected):
            raise RuntimeError(
                f"G0 v3 source drift: {relative}:{expected}:{actual}"
            )
    base = read_json(BASE_PREREGISTRATION)
    if (
        base.get("schema")
        != "resetp.coop-hgs-rr-g0-real-bundle-preregistration.v1"
    ):
        raise RuntimeError("unexpected G0 v1 preregistration schema")
    merged = dict(base)
    merged["repair_amendment"] = {
        "id": amendment["approval_id"],
        "base_preregistration_sha256": amendment[
            "base_preregistration"
        ]["sha256"],
        "scope": amendment["repair_scope"],
    }
    merged["claim_boundary"] = amendment["claim_boundary"]
    return merged


frozen.PREREGISTRATION = AMENDMENT
frozen.OUT = PACKAGE / "g0_real_bundle_gate_v3"
frozen.load_preregistration = load_preregistration_v3


if __name__ == "__main__":
    raise SystemExit(frozen.main())
