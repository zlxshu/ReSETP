#!/usr/bin/env python3
"""Verify and refresh the completed G1-independent China81 road pipeline.

This entrypoint is deliberately fail-closed.  It never rebuilds an older graph
or matrix version: the expensive road artifacts are immutable inputs here.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
BASE = REPO / "data/ChinaInstances/china_stage2_sparse_connected_osrm_graphs_v5_20260718"
MATRICES = REPO / "data/ChinaInstances/china81_local_directed_matrices_v9_20260718"
DIAGNOSTICS = REPO / "data/ChinaInstances/china81_matrix_diagnostics_v1_20260718"
FROZEN = REPO / "data/ChinaInstances/china81_g1_independent_frozen_v2_20260718"
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


def require(path: Path, phase: str) -> None:
    if not path.is_file():
        update(phase, "HALT", f"missing immutable prerequisite: {path.relative_to(REPO)}")
        raise FileNotFoundError(path)


def main() -> int:
    require(BASE / "SPARSE_CONNECTED_OSRM_GRAPHS_COMPLETE.json", "base_graphs")
    require(MATRICES / "decision.json", "china81_matrices")
    update("immutable_road_inputs", "PASS", "v5 graphs and v9 matrices present")
    run(["python3", "baselines/china_instances/audit_china81_matrix_diagnostics_20260718.py"],
        "matrix_diagnostics")
    run(["python3", "baselines/china_instances/finalize_china81_g1_independent_package_20260718.py"],
        "china81_zero_search_audit")
    run(["python3", "baselines/china_instances/audit_china_stage2_g1_independent_readiness_20260718.py"],
        "readiness_refresh")
    require(DIAGNOSTICS / "decision.json", "matrix_diagnostics")
    require(FROZEN / "decision.json", "china81_zero_search_audit")
    update(
        "complete",
        "PASS_FORMAL_ACCEPTANCE_HELD",
        "all G1-independent road inputs complete; G1 merge remains held by design",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
