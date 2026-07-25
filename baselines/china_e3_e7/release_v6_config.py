"""Single source of truth for the post-audit E3 release paths.

This module deliberately contains no fallback to an older campaign.  Every
consumer must fail closed until the corrected E2 v4 evidence and the matching
E3 zero-search gates exist.
"""

from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
RELEASE_CONFIG = Path(__file__).resolve()
E2_CAMPAIGN_NAME = "corrected_china81_rerun_v4_20260724"
E2_CAMPAIGN = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / E2_CAMPAIGN_NAME
)

E2_FULL = E2_CAMPAIGN / "full_gate"
E2_REPLAY = E2_CAMPAIGN / "full_witness_replay"
E2_RESULT_PREREGISTRATION = (
    E2_CAMPAIGN / "e2_result_release_preregistration_v1_20260724.json"
)
E2_RESULT_AUDIT = E2_CAMPAIGN / "result_strength_gate"
S3_REPRESENTATIVE = E2_CAMPAIGN / "representative_gate"
S3_MECHANISM_CASE = E2_CAMPAIGN / "mechanism_case_gate"
S3_MECHANISM_TRAJECTORIES = S3_MECHANISM_CASE / "trajectories"
S4_ROUTE_DETAIL = E2_CAMPAIGN / "table4_gate"
S5_ARTIFACTS = E2_CAMPAIGN / "artifacts"

PUBLIC_P1_REPLAY = (
    REPO
    / "baselines/e2_final_campaign_20260720"
    / "corrected_china81_rerun_20260723"
    / "public_p1_no_search_replay"
)

CONTRACT = (
    REPO
    / "data/ChinaInstances"
    / "china_e3_formal_release_contract_v6_20260724.json"
)
CONTRACT_BUILDER = (
    REPO
    / "baselines/china_e3_e7"
    / "build_formal_release_contract_v6.py"
)

E3_BASE = REPO / "baselines/china_e3_e7"
E3_ARM_GATE = E3_BASE / "e3_arm_semantics_gate_v5_20260724"
E3_BUDGET_PILOT = E3_BASE / "e3_budget_pilot_v4_20260724"
E3_PARAMETER_GATE = (
    E3_BASE / "e3_parameter_coherence_gate_v3_20260724"
)
E3_RELEASE_REGRESSION = (
    E3_BASE / "e3_release_regression_v2_20260724"
)
E3_GO_GATE = E3_BASE / "e3_go_gate_v2_20260724"
E3_FORMAL = E3_BASE / "e3_formal_v2_20260724"
E3_AGGREGATE = E3_BASE / "e3_aggregate_v2_20260724"
E3_RESULT_AUDIT = E3_BASE / "e3_result_audit_v2_20260724"
E3_TABLES = E3_BASE / "e3_paper_tables_v2_20260724"
E3_FIGURES = E3_BASE / "e3_paper_figures_v2_20260724"
E3_RESULT_PREREGISTRATION = (
    E3_BASE / "e3_result_release_preregistration_v1_20260724.json"
)

E2_EXPECTED_TASKS = 81 * 5
E2_EXPECTED_SOLUTIONS = E2_EXPECTED_TASKS * 4
E3_EXPECTED_TASKS = 81 * 5 * 2
COMPLETE_CANDIDATE_BUDGET = 80


def required_pre_go_decisions() -> dict[str, Path]:
    """Return every decision file required before the E3 GO gate."""

    return {
        "e2_full": E2_FULL / "decision.json",
        "e2_full_replay": E2_REPLAY / "decision.json",
        "e2_result_strength": E2_RESULT_AUDIT / "decision.json",
        "s3_representative": S3_REPRESENTATIVE / "decision.json",
        "s3_mechanism_case": S3_MECHANISM_CASE / "decision.json",
        "s3_mechanism_trajectories": (
            S3_MECHANISM_TRAJECTORIES / "decision.json"
        ),
        "s4_route_detail": S4_ROUTE_DETAIL / "decision.json",
        "s5_artifacts": S5_ARTIFACTS / "decision.json",
        "public_p1_no_search_replay": (
            PUBLIC_P1_REPLAY / "decision.json"
        ),
        "e3_arm_semantics": E3_ARM_GATE / "decision.json",
        "e3_budget_pilot": E3_BUDGET_PILOT / "decision.json",
        "e3_parameter_coherence": E3_PARAMETER_GATE / "decision.json",
        "e3_release_regression": (
            E3_RELEASE_REGRESSION / "decision.json"
        ),
    }
