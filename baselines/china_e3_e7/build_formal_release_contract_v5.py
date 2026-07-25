#!/usr/bin/env python3
"""Derive the fleet-and-predeparture-consistent v5 release contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
PARENT = (
    REPO
    / "data/ChinaInstances/"
    "china_e3_formal_release_contract_v4_20260723.json"
)
OUT = (
    REPO
    / "data/ChinaInstances/"
    "china_e3_formal_release_contract_v5_20260724.json"
)
OLD_CAMPAIGN = (
    "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v2_20260723"
)
NEW_CAMPAIGN = (
    "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v3_20260724"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite v5 contract: {OUT}")
    payload = json.loads(PARENT.read_text(encoding="utf-8"))
    payload["schema"] = (
        "resetp.china.e3-e7-formal-release-contract.v5"
    )
    payload["contract_id"] = "CHINA-E3-FORMAL-RELEASE-001-V5"
    payload["purpose"] = (
        "D1--D6 approved fixed-date implementation contract with "
        "consistent same-day predeparture charging validation and hard "
        "depot-by-powertrain fleet caps. Formal E3 search remains "
        "fail-closed until GO."
    )
    payload["lineage"] = {
        "parent_contract": str(PARENT.relative_to(REPO)),
        "parent_contract_sha256": sha256(PARENT),
        "parent_mutation_allowed": False,
        "parent_scope": (
            "v4 fixed-date same-day predeparture charging protocol"
        ),
        "child_scope": (
            "checker-compatible predeparture charging, mandatory finite "
            "fleet assignment and fresh private E2/S3--S5 evidence"
        ),
    }
    payload["formal_execution"]["charging_time_policy"][
        "checker_window"
    ] = (
        "a depot action is valid when it finishes before the current "
        "route departure; post-return charging is a distinct multi-day "
        "window and is not used by fixed-date China81"
    )
    payload["formal_execution"]["finite_fleet_policy"] = {
        "scope": "every depot and each of CV/EV separately",
        "mandatory_assignment": (
            "when route count exceeds a depot CV cap, assign enough "
            "complete-model-feasible routes to registered EVs before "
            "optional cost-improving EV conversions"
        ),
        "cap_relaxation_allowed": False,
        "checker_policy": "FAIL_CLOSED",
    }
    payload["finite_fleet_scenario"]["completion_policy"] = (
        "mandatory depot-by-powertrain cap satisfaction before optional "
        "cost-improving EV conversions"
    )
    payload["source_contracts"]["budget_pilot"] = (
        "baselines/china_e3_e7/"
        "e3_budget_pilot_v4_20260724/decision.json"
    )
    for key, value in list(
        payload["release_evidence_roots"].items()
    ):
        if key == "public_p1_no_search_replay":
            continue
        payload["release_evidence_roots"][key] = value.replace(
            OLD_CAMPAIGN,
            NEW_CAMPAIGN,
        )
    payload["rerun_boundary"]["private_china81_e2"] = (
        "full rerun in corrected_china81_rerun_v3_20260724 after "
        "predeparture-checker and depot fleet-cap repair"
    )
    payload["rerun_boundary"]["s3_to_s5"] = (
        "full rerun/rebuild in corrected_china81_rerun_v3_20260724"
    )
    payload["formal_search_allowed"] = False
    payload["search_evaluations"] = 0
    OUT.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
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
                "sha256": sha256(OUT),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
