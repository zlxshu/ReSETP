#!/usr/bin/env python3
"""Run the six-worker zero-search probe against G0 v3 wiring."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724"
REGISTRATION = PACKAGE / "g1_six_worker_resource_probe_registration_v3.json"
OUT = PACKAGE / "g1_six_worker_resource_probe_v3"

for path in (REPO, PACKAGE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_g1_six_worker_resource_probe as frozen  # noqa: E402
import run_g0_real_bundle_preflight_v3 as g0_v3  # noqa: E402


def verify_registration_v3() -> dict[str, Any]:
    registration = frozen.read_json(REGISTRATION)
    if (
        registration.get("schema")
        != "resetp.genuine-hybrid-g1-worker-probe-registration.v3"
    ):
        raise RuntimeError("unexpected worker-probe v3 registration schema")
    if registration.get("status") != "FROZEN_BEFORE_RESOURCE_PROBE_V3":
        raise RuntimeError("worker-probe v3 registration status drift")
    for relative, expected in registration["source_hashes"].items():
        path = REPO / str(relative)
        if not path.is_file():
            raise RuntimeError(f"worker-probe v3 source missing: {relative}")
        actual = frozen.sha256(path)
        if actual != expected:
            raise RuntimeError(
                f"worker-probe v3 source hash mismatch: "
                f"{relative}:{expected}:{actual}"
            )
    g0_root = PACKAGE / "g0_real_bundle_gate_v3"
    upstream = registration["upstream_g0_v3"]
    for name, field in (
        ("decision.json", "decision_sha256"),
        ("artifact_hashes.json", "artifact_hashes_sha256"),
        ("done.json", "done_sha256"),
    ):
        path = g0_root / name
        if not path.is_file() or frozen.sha256(path) != upstream[field]:
            raise RuntimeError(f"worker-probe v3 G0 evidence drift: {name}")
    decision = frozen.read_json(g0_root / "decision.json")
    if decision.get("decision") != upstream["decision"]:
        raise RuntimeError("worker-probe v3 requires G0 v3 PASS")
    return registration


def run_probe_task_v3(spec: dict[str, Any]) -> dict[str, Any]:
    registration = g0_v3.load_preregistration_v3()
    registered = next(
        row
        for row in registration["instances"]
        if row["instance_id"] == spec["instance_id"]
    )
    started = frozen.perf_counter()
    row = g0_v3.frozen.run_instance(registered, registration)
    return {
        "task_id": spec["task_id"],
        "instance_id": spec["instance_id"],
        "replicate": spec["replicate"],
        "status": row["status"],
        "elapsed_seconds": frozen.perf_counter() - started,
        "peak_rss_mb": frozen.peak_rss_mb(),
        "detail": row["detail"],
    }


frozen.REGISTRATION = REGISTRATION
frozen.OUT = OUT
frozen.verify_registration = verify_registration_v3
frozen.run_probe_task = run_probe_task_v3


def main() -> int:
    result = frozen.execute()
    decision = json.loads((OUT / "decision.json").read_text(encoding="utf-8"))
    frozen.write_json(
        OUT / "done.json",
        {
            "schema": "resetp.genuine-hybrid-g1-worker-probe-done.v3",
            "decision": decision["decision"],
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "search_iterations": 0,
        },
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
