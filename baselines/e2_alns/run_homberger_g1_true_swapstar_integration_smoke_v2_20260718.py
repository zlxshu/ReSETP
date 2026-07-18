#!/usr/bin/env python3
"""Repeat the true-SWAP* integration smoke with the standard structural gate."""

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
    run_homberger_g1_true_swapstar_integration_smoke_20260718 as smoke,
)
from baselines.e2_alns.run_homberger_g1_sisr_20260718 import (  # noqa: E402
    atomic_json,
    clean_generated_appledouble,
    sha256,
)


OUTPUT = (
    smoke.REPO
    / "baselines/e2_alns"
    / "homberger_g1_true_swapstar_integration_smoke_v2_20260718"
)
RUNNER_SOURCE = Path(__file__).resolve()


def main() -> int:
    smoke.OUTPUT = OUTPUT
    decision = smoke.execute()
    metadata_path = OUTPUT / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["schema_version"] = (
        "resetp.e2.homberger-g1-true-swapstar-integration-smoke.v2"
    )
    metadata["supersedes"] = (
        "baselines/e2_alns/"
        "homberger_g1_true_swapstar_integration_smoke_20260718"
    )
    metadata["correction"] = (
        "true SWAP* uses the standard one-interval late-stage structural gate; "
        "the legacy SWAP*-lite keeps its three-interval gate"
    )
    atomic_json(metadata_path, metadata)
    contract_path = OUTPUT / "task_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["trigger"] = (
        "late_25_percent_and_one_standard_structural_interval_without_best_improvement"
    )
    contract["budget_change_from_v1"] = 0
    atomic_json(contract_path, contract)
    hashes_path = OUTPUT / "artifact_hashes.json"
    hashes = json.loads(hashes_path.read_text(encoding="utf-8"))
    hashes[str(RUNNER_SOURCE.relative_to(smoke.REPO))] = sha256(RUNNER_SOURCE)
    hashes[str(metadata_path.relative_to(smoke.REPO))] = sha256(metadata_path)
    hashes[str(contract_path.relative_to(smoke.REPO))] = sha256(contract_path)
    atomic_json(hashes_path, hashes)
    clean_generated_appledouble(OUTPUT)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
