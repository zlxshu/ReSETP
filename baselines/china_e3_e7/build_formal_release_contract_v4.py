#!/usr/bin/env python3
"""Derive the fixed-date charging v4 release contract from immutable v3."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
PARENT = (
    REPO
    / "data/ChinaInstances/"
    "china_e3_formal_release_contract_v3_20260723.json"
)
OUT = (
    REPO
    / "data/ChinaInstances/"
    "china_e3_formal_release_contract_v4_20260723.json"
)
OLD_CAMPAIGN = (
    "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_20260723"
)
NEW_CAMPAIGN = (
    "baselines/e2_final_campaign_20260720/"
    "corrected_china81_rerun_v2_20260723"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite v4 contract: {OUT}")
    payload = json.loads(PARENT.read_text(encoding="utf-8"))
    payload["schema"] = "resetp.china.e3-e7-formal-release-contract.v4"
    payload["contract_id"] = "CHINA-E3-FORMAL-RELEASE-001-V4"
    payload["purpose"] = (
        "D1--D6 approved fixed-date implementation contract. China81 depot "
        "energy used by a route is charged on the registered date before "
        "departure. Formal E3 search remains fail-closed until GO."
    )
    payload["lineage"] = {
        "parent_contract": str(PARENT.relative_to(REPO)),
        "parent_contract_sha256": sha256(PARENT),
        "parent_mutation_allowed": False,
        "parent_scope": "v3 pre-GO release protocol",
        "child_scope": (
            "fixed-date same-day predeparture charging and fresh corrected "
            "private E2/S3--S5 evidence"
        ),
    }
    payload["formal_execution"]["charging_time_policy"] = {
        "calendar_date": "2025-02-12",
        "depot_precharge_window": (
            "same registered day from 00:00 until actual route departure"
        ),
        "energy_causality": (
            "every depot charge supplying a route must finish no later than "
            "that route's departure"
        ),
        "cross_date_charging_allowed": False,
        "cyclic_next_day_borrowing_allowed": False,
    }
    payload["spatiotemporal_settlement_key"][
        "charging_time_policy"
    ] = "SAME_REGISTERED_DAY_PREDEPARTURE_FAIL_CLOSED"
    payload["source_contracts"]["budget_pilot"] = (
        "baselines/china_e3_e7/"
        "e3_budget_pilot_v3_20260723/decision.json"
    )
    for key, value in list(payload["release_evidence_roots"].items()):
        if key == "public_p1_no_search_replay":
            continue
        payload["release_evidence_roots"][key] = value.replace(
            OLD_CAMPAIGN,
            NEW_CAMPAIGN,
        )
    payload["rerun_boundary"]["private_china81_e2"] = (
        "full rerun in corrected_china81_rerun_v2_20260723 after fixed-date "
        "charging causality repair"
    )
    payload["rerun_boundary"]["s3_to_s5"] = (
        "full rerun/rebuild in corrected_china81_rerun_v2_20260723"
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
