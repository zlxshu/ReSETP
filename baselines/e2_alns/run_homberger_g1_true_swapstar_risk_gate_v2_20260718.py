#!/usr/bin/env python3
"""Repeat the R-risk gate after decoupling SWAP* from a changed ALNS proposal."""

from __future__ import annotations

import json
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[2]
SOLVER_SRC = REPO / "solver/src"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(SOLVER_SRC) not in sys.path:
    sys.path.insert(0, str(SOLVER_SRC))

from baselines.e2_alns import (  # noqa: E402
    run_homberger_g1_true_swapstar_risk_gate_20260718 as gate,
)
from baselines.e2_alns.homberger_g1_helpers_20260718 import (  # noqa: E402
    atomic_json,
    clean_generated_appledouble,
    sha256,
)


OUTPUT = (
    REPO
    / "baselines/e2_alns"
    / "homberger_g1_true_swapstar_risk_gate_v2_20260718"
)
RUNNER_SOURCE = Path(__file__).resolve()


def main() -> int:
    gate.OUTPUT = OUTPUT
    result = gate.main()
    metadata_path = OUTPUT / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["schema_version"] = (
        "resetp.e2.homberger-g1-true-swapstar-risk-gate.v2"
    )
    metadata["supersedes"] = (
        "baselines/e2_alns/"
        "homberger_g1_true_swapstar_risk_gate_20260718"
    )
    metadata["correction"] = (
        "late-stage true SWAP* intensification is eligible on a feasible "
        "no-op destroy-repair proposal; stagnation must not suppress rescue"
    )
    atomic_json(metadata_path, metadata)
    contract_path = OUTPUT / "task_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["eligibility_correction"] = (
        "candidate feasibility plus structural due; changed ALNS proposal "
        "is not required"
    )
    atomic_json(contract_path, contract)
    hashes_path = OUTPUT / "artifact_hashes.json"
    hashes = json.loads(hashes_path.read_text(encoding="utf-8"))
    hashes[str(RUNNER_SOURCE.relative_to(REPO))] = sha256(RUNNER_SOURCE)
    hashes[str(metadata_path.relative_to(REPO))] = sha256(metadata_path)
    hashes[str(contract_path.relative_to(REPO))] = sha256(contract_path)
    atomic_json(hashes_path, hashes)
    clean_generated_appledouble(OUTPUT)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
