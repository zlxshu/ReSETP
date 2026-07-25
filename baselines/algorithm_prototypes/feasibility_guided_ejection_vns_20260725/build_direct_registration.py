#!/usr/bin/env python3
"""Freeze the direct-improvement behavior gate after G0 PASS."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
G0_REGISTRATION = PACKAGE / "g0_registration_v1.json"
G0_DECISION = PACKAGE / "g0_gate_v1/decision.json"
G0_HASHES = PACKAGE / "g0_gate_v1/artifact_hashes.json"
OUTPUT = PACKAGE / "direct_improvement_registration_v1.json"
SOURCE_PATHS = (
    "baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/__init__.py",
    "baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/ejection_rebuild.py",
    "baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/feasible_moves.py",
    "baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/fge_vnd.py",
    "baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/run_direct_improvement_gate.py",
    "baselines/algorithm_prototypes/feasibility_guided_ejection_vns_20260725/test_feasible_moves.py",
    "baselines/algorithm_prototypes/tailored_dp_vns_20260725/neighborhoods.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/contracts.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/decoder_cache.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/evaluation.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/fleet_assignment_dp.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/reference_decoder.py",
    "docs/handoff/e2_feasibility_guided_vns_contract_20260725.md",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/china81.py",
    "solver/src/setp_solver/china81_completion.py",
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/prices.py",
    "solver/src/setp_solver/search/evaluation.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"registration already exists: {OUTPUT}")
    g0_registration = read_json(G0_REGISTRATION)
    g0_decision = read_json(G0_DECISION)
    if (
        g0_decision.get("verdict")
        != "PASS_FGE_VNS_G0_ZERO_OBJECTIVE_WIRING"
        or not g0_decision.get("passed")
    ):
        raise RuntimeError("direct behavior gate requires exact G0 PASS")
    payload = {
        "schema": "resetp.fge-vns-direct-registration.v1",
        "status": "FROZEN_BEFORE_EXECUTION",
        "registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "approval_id": "E2-FEASIBILITY-GUIDED-VNS-011",
        "contract_id": "E2-FEASIBILITY-GUIDED-VNS-001",
        "g0_evidence": {
            "decision_path": G0_DECISION.relative_to(REPO).as_posix(),
            "decision_sha256": sha256(G0_DECISION),
            "artifact_hashes_path": G0_HASHES.relative_to(REPO).as_posix(),
            "artifact_hashes_sha256": sha256(G0_HASHES),
        },
        "config": {
            **g0_registration["config"],
            "complete_evaluation_limit_per_instance": 120,
            "assignment_candidates_per_structure": 2,
            "assignment_beam_per_state": 2,
            "improvement_tolerance": 1.0e-9,
            "required_improved_instances": 2,
            "duplicate_fraction_limit": 0.20,
            "large_neighborhoods": [
                "two_opt_star",
                "ejection_rebuild",
            ],
        },
        "inputs": g0_registration["inputs"],
        "source_hashes": {
            relative: sha256(REPO / relative)
            for relative in SOURCE_PATHS
        },
        "authority_registration": g0_registration[
            "authority_registration"
        ],
        "prohibitions": [
            "No HGS or MIP run",
            "No change to frozen instances, witnesses, budgets, or gates",
            "No change to cost, checker, evaluator, prices, model, paper, v7, G1 v6, or first failed candidate",
            "No tuning, replacement, rerun, or gate reduction after results",
        ],
        "claim_boundary": (
            "Direct improvement behavior evidence only. PASS authorizes "
            "a separately preregistered unseen-instance A/B/A+B micro gate; "
            "it does not authorize E3, formal China81, BKS, SOTA, or paper claims."
        ),
    }
    write_json(OUTPUT, payload)
    print(
        "FROZEN_BEFORE_EXECUTION",
        len(payload["inputs"]),
        len(payload["source_hashes"]),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

