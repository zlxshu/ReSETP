#!/usr/bin/env python3
"""Build the archive-route-reuse and dual-case E3 release contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from baselines.china_e3_e7.release_v6_config import (
    CONTRACT,
    E2_CAMPAIGN,
    E2_FULL,
    E2_REPLAY,
    E2_RESULT_AUDIT,
    E2_RESULT_PREREGISTRATION,
    E3_ARM_GATE,
    E3_BUDGET_PILOT,
    E3_PARAMETER_GATE,
    E3_RELEASE_REGRESSION,
    E3_RESULT_PREREGISTRATION,
    PUBLIC_P1_REPLAY,
    REPO,
    S3_MECHANISM_CASE,
    S3_MECHANISM_TRAJECTORIES,
    S3_REPRESENTATIVE,
    S4_ROUTE_DETAIL,
    S5_ARTIFACTS,
)


PARENT = (
    REPO
    / "data/ChinaInstances"
    / "china_e3_formal_release_contract_v5_20260724.json"
)
APPROVAL_REGISTER = (
    REPO
    / "docs/handoff"
    / "model_change_approval_register_20260718.md"
)
FORMAL_PREREGISTRATION = E2_CAMPAIGN / "formal_preregistration.json"
MECHANISM_CASE_PREREGISTRATION = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / "algorithm_repair_diagnostic_20260724"
    / "chen_style_mechanism_case_preregistration.json"
)
TRAJECTORY_SHAPE_PREREGISTRATION = (
    E2_CAMPAIGN / "trajectory_shape_preregistration.json"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(REPO))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def require_verdict(path: Path, expected: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"missing prerequisite decision: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    observed = payload.get("verdict")
    if observed != expected:
        raise RuntimeError(
            f"prerequisite verdict mismatch: {path}: "
            f"observed={observed!r}, expected={expected!r}"
        )


def build() -> dict[str, Any]:
    if CONTRACT.exists():
        raise RuntimeError(f"refusing to overwrite v6 contract: {CONTRACT}")
    if not PARENT.is_file():
        raise RuntimeError(f"missing parent contract: {PARENT}")
    if not FORMAL_PREREGISTRATION.is_file():
        raise RuntimeError(
            f"missing corrected E2 preregistration: {FORMAL_PREREGISTRATION}"
        )
    if not MECHANISM_CASE_PREREGISTRATION.is_file():
        raise RuntimeError(
            "missing mechanism-case preregistration: "
            f"{MECHANISM_CASE_PREREGISTRATION}"
        )
    if not TRAJECTORY_SHAPE_PREREGISTRATION.is_file():
        raise RuntimeError(
            "missing trajectory shape preregistration: "
            f"{TRAJECTORY_SHAPE_PREREGISTRATION}"
        )
    if not E2_RESULT_PREREGISTRATION.is_file():
        raise RuntimeError(
            "missing E2 result release preregistration: "
            f"{E2_RESULT_PREREGISTRATION}"
        )
    if not E3_RESULT_PREREGISTRATION.is_file():
        raise RuntimeError(
            "missing E3 result release preregistration: "
            f"{E3_RESULT_PREREGISTRATION}"
        )
    mechanism_preregistration = json.loads(
        MECHANISM_CASE_PREREGISTRATION.read_text(encoding="utf-8")
    )
    approval_text = APPROVAL_REGISTER.read_text(encoding="utf-8")
    approval_id = "E2-ALGORITHM-REPAIR-ARCHIVE-ROUTE-001"
    if approval_id not in approval_text:
        raise RuntimeError(f"missing approval registration: {approval_id}")
    prerequisite_verdicts = {
        E2_FULL / "decision.json": (
            "PASS_D6_CORRECTED_CHINA81_E2_RAW"
        ),
        E2_REPLAY / "decision.json": (
            "PASS_D6_CORRECTED_FULL_WITNESS_REPLAY"
        ),
        E2_RESULT_AUDIT / "decision.json": (
            "PASS_E2_CORRECTED_PAPER_STRENGTH"
        ),
        S3_REPRESENTATIVE / "decision.json": (
            "PASS_D6_CORRECTED_S3_REPRESENTATIVE"
        ),
        S3_MECHANISM_CASE / "decision.json": (
            "PASS_D6_CORRECTED_S3_MECHANISM_CASE"
        ),
        S3_MECHANISM_TRAJECTORIES / "decision.json": (
            "PASS_D6_CORRECTED_S3_TRAJECTORIES"
        ),
        S4_ROUTE_DETAIL / "decision.json": (
            "PASS_D6_CORRECTED_S4_ROUTE_DETAIL"
        ),
        S5_ARTIFACTS / "decision.json": (
            "PASS_D6_CORRECTED_S5_ARTIFACTS"
        ),
        PUBLIC_P1_REPLAY / "decision.json": (
            "PASS_PUBLIC_P1_PRESERVATION_NO_SEARCH"
        ),
    }
    for path, expected in prerequisite_verdicts.items():
        require_verdict(path, expected)

    payload = json.loads(PARENT.read_text(encoding="utf-8"))
    payload["schema"] = (
        "resetp.china.e3-e7-formal-release-contract.v6"
    )
    payload["contract_id"] = "CHINA-E3-FORMAL-RELEASE-001-V6"
    payload["purpose"] = (
        "Post-audit E3 release contract bound to the fresh corrected E2 "
        "archive-route-reuse campaign, independent witness replay, two "
        "pre-registered S3 case roles, and fresh zero-search E3 gates. "
        "Formal E3 search remains fail-closed until the matching GO package."
    )
    payload["lineage"] = {
        "parent_contract": relative(PARENT),
        "parent_contract_sha256": sha256(PARENT),
        "parent_mutation_allowed": False,
        "parent_scope": (
            "v5 fleet and predeparture consistent release contract"
        ),
        "child_scope": (
            "fresh archive-route-reuse E2 evidence, independent 1620-solution "
            "replay, dual S3 case roles and version-matched E3 gates"
        ),
    }
    payload["algorithm_repair"] = {
        "approval_id": approval_id,
        "mechanism": (
            "all already complete-model-scored archive candidates contribute "
            "routes to the bounded MIP route pool; single-view returned "
            "solutions continue to use the eight exact elites"
        ),
        "unchanged": [
            "three route proxy views",
            "5000 HGS iterations per view",
            "80 complete candidate evaluation attempts per task",
            "5 second MIP safety limit",
            "seeds 1 through 5",
            "complete evaluator and independent checker",
        ],
        "development_gate": "2 strict wins, 4 ties, 0 losses",
        "formal_result_selection_forbidden": True,
        "formal_preregistration": relative(FORMAL_PREREGISTRATION),
        "formal_preregistration_sha256": sha256(
            FORMAL_PREREGISTRATION
        ),
    }
    payload["e2_result_release_gate"] = {
        "preregistration": relative(E2_RESULT_PREREGISTRATION),
        "preregistration_sha256": sha256(
            E2_RESULT_PREREGISTRATION
        ),
        "evidence": relative(E2_RESULT_AUDIT),
        "decision_sha256": sha256(
            E2_RESULT_AUDIT / "decision.json"
        ),
        "required_verdict": "PASS_E2_CORRECTED_PAPER_STRENGTH",
        "post_result_threshold_changes_allowed": False,
    }
    payload["s3_case_roles"] = {
        "input_feature_representative": {
            "instance_id": "cn-prd-50c-01-V2-LOCATIONS",
            "evidence_root": relative(S3_REPRESENTATIVE),
            "uses": [
                "simulation instance data table",
                "best route detail table",
            ],
            "selection_rule": (
                "result-blind nearest-to-median five-feature rule"
            ),
        },
        "mechanism_illustration": {
            "instance_id": "cn-cy-100c-01-V2-LOCATIONS",
            "evidence_root": relative(S3_MECHANISM_CASE),
            "trajectory_root": relative(S3_MECHANISM_TRAJECTORIES),
            "uses": [
                "four-method detailed comparison",
                "different-algorithm iteration figure",
            ],
            "claim_boundary": (
                "pre-registered mechanism illustration; not representative "
                "and not a substitute for the full China81 matrix"
            ),
            "selection_disclosure": mechanism_preregistration[
                "selection_disclosure"
            ],
            "original_endpoint_gate": mechanism_preregistration[
                "endpoint_gate"
            ],
            "preregistration": relative(
                MECHANISM_CASE_PREREGISTRATION
            ),
            "preregistration_sha256": sha256(
                MECHANISM_CASE_PREREGISTRATION
            ),
            "trajectory_shape_preregistration": relative(
                TRAJECTORY_SHAPE_PREREGISTRATION
            ),
            "trajectory_shape_preregistration_sha256": sha256(
                TRAJECTORY_SHAPE_PREREGISTRATION
            ),
        },
    }
    payload["figure4_protocol"] = {
        "source": (
            "complete-model-scored incumbent observations from the "
            "pre-registered mechanism-illustration case"
        ),
        "reference_target": (
            "Chen 2025-like readable multi-algorithm descent: each curve "
            "must be formed by genuine recorded improvements and the main "
            "method must finish below all three single-view methods under "
            "the pre-registered endpoint gate"
        ),
        "drawing": "ordinary straight line segments between observations",
        "shape_gate": json.loads(
            TRAJECTORY_SHAPE_PREREGISTRATION.read_text(
                encoding="utf-8"
            )
        )["hard_gates"],
        "axes": {
            "x": "时间(min)",
            "y": "成本(元)",
            "reference_basis": (
                "Chen 2025 states that algorithms have different iteration "
                "counts and therefore uses time in minutes as the horizontal "
                "axis"
            ),
        },
        "forbidden": [
            "smoothing",
            "interpolation that creates observations",
            "broken axes",
            "seed replacement",
            "case replacement after observing results",
            "using visual resemblance alone to override a failed endpoint "
            "or evidence gate",
        ],
    }
    payload["e3_result_release_gate"] = {
        "preregistration": relative(E3_RESULT_PREREGISTRATION),
        "preregistration_sha256": sha256(
            E3_RESULT_PREREGISTRATION
        ),
        "gate": json.loads(
            E3_RESULT_PREREGISTRATION.read_text(encoding="utf-8")
        ),
    }

    payload["source_contracts"]["budget_pilot"] = relative(
        E3_BUDGET_PILOT / "decision.json"
    )
    payload["source_contracts"]["e3_arm_semantics"] = relative(
        E3_ARM_GATE / "decision.json"
    )
    payload["source_contracts"]["e3_parameter_coherence"] = relative(
        E3_PARAMETER_GATE / "decision.json"
    )
    payload["source_contracts"]["e3_release_regression"] = relative(
        E3_RELEASE_REGRESSION / "decision.json"
    )
    payload["source_contracts"]["algorithm_repair_approval"] = relative(
        APPROVAL_REGISTER
    )
    payload["source_contracts"]["e2_formal_preregistration"] = relative(
        FORMAL_PREREGISTRATION
    )
    payload["source_contracts"][
        "s3_mechanism_case_preregistration"
    ] = relative(MECHANISM_CASE_PREREGISTRATION)
    payload["source_contracts"][
        "s3_trajectory_shape_preregistration"
    ] = relative(TRAJECTORY_SHAPE_PREREGISTRATION)
    payload["source_contracts"][
        "e2_result_release_preregistration"
    ] = relative(E2_RESULT_PREREGISTRATION)
    payload["source_contracts"][
        "e3_result_release_preregistration"
    ] = relative(E3_RESULT_PREREGISTRATION)
    payload["release_evidence_roots"] = {
        "corrected_private_e2": relative(E2_FULL),
        "full_witness_replay": relative(E2_REPLAY),
        "corrected_e2_result_strength": relative(E2_RESULT_AUDIT),
        "corrected_s3_representative": relative(S3_REPRESENTATIVE),
        "corrected_s3_mechanism_case": relative(S3_MECHANISM_CASE),
        "corrected_s3_trajectories": relative(
            S3_MECHANISM_TRAJECTORIES
        ),
        "corrected_s4": relative(S4_ROUTE_DETAIL),
        "corrected_s5": relative(S5_ARTIFACTS),
        "public_p1_no_search_replay": relative(PUBLIC_P1_REPLAY),
    }
    payload["formal_execution"]["budget_pilot"] = {
        "arms": [
            "status_quo_responsibility",
            "optimized_responsibility_cooperation",
        ],
        "evidence": relative(E3_BUDGET_PILOT / "decision.json"),
        "instances": [
            "cn-prd-10c-01-V2-LOCATIONS",
            "cn-prd-75c-01-V2-LOCATIONS",
            "cn-prd-200c-01-V2-LOCATIONS",
        ],
        "objective_values_visible_to_selector": False,
        "search_evaluations": 0,
        "seed": 1,
        "status": "FRESH_RESULT_BLIND_RERUN_REQUIRED_BEFORE_GO",
    }
    payload["rerun_boundary"] = {
        "historical_artifacts_overwrite_allowed": False,
        "private_china81_e2": (
            "fresh full rerun in corrected_china81_rerun_v4_20260724 "
            "after the registered archive-route reuse repair"
        ),
        "public_p1": "NO_SEARCH_SEALED_WITNESS_REPLAY_ONLY",
        "s3_to_s5": (
            "fresh extensions and rebuild in "
            "corrected_china81_rerun_v4_20260724"
        ),
    }
    payload["formal_search_allowed"] = False
    payload["search_evaluations"] = 0
    CONTRACT.parent.mkdir(parents=True, exist_ok=True)
    write_json(CONTRACT, payload)
    return payload


if __name__ == "__main__":
    result = build()
    print(
        json.dumps(
            {
                "contract_id": result["contract_id"],
                "formal_search_allowed": result[
                    "formal_search_allowed"
                ],
                "sha256": sha256(CONTRACT),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
