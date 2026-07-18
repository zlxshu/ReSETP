#!/usr/bin/env python3
"""Run the dependent G1-independent road pipeline with phase checkpoints."""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
BASE = REPO / "data/ChinaInstances/china_stage2_local_osrm_graphs_20260718"
CY = REPO / "data/ChinaInstances/china_stage2_chengyu_merged_osm_v1_20260718"
MATRICES = REPO / "data/ChinaInstances/china81_local_directed_matrices_v1_20260718"
STATUS = REPO / "data/ChinaInstances/china81_stage2_road_pipeline_status_20260718.json"


def update(phase: str, state: str, detail: str) -> None:
    temporary = STATUS.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({
        "schema": "resetp.china81-stage2-road-pipeline.status.v1",
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "phase": phase, "state": state, "detail": detail,
        "search_evaluations": 0, "formal_search_allowed": False,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(STATUS)


def run(command: list[str], phase: str) -> None:
    update(phase, "RUNNING", " ".join(command))
    subprocess.run(command, cwd=REPO, check=True)
    update(phase, "PASS", "completed")


def main() -> int:
    update("base_graphs", "WAITING", "waiting for ten frozen single-region graphs")
    deadline = time.monotonic() + 12 * 3600
    while not (BASE / "LOCAL_OSRM_GRAPHS_COMPLETE.json").is_file():
        if time.monotonic() > deadline:
            raise RuntimeError("base graph build did not finish within 12 hours")
        time.sleep(30)
    run(["python3", "baselines/china_instances/build_chengyu_merged_osrm_graphs_20260718.py"],
        "chengyu_graphs")
    run(["python3", "baselines/china_instances/build_china81_directed_matrices_20260718.py",
         "--workers", "24", "--router-threads", "6"], "china81_matrices")
    run(["python3", "baselines/china_instances/finalize_china81_g1_independent_package_20260718.py"],
        "china81_zero_search_audit")
    run(["python3", "baselines/china_instances/audit_china_stage2_g1_independent_readiness_20260718.py"],
        "readiness_refresh")
    update("complete", "PASS", "all G1-independent road inputs complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
