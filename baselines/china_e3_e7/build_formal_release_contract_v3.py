#!/usr/bin/env python3
"""Build the post-D6, still-GO-gated China E3 release contract.

The corrected private E2 and representative reruns are permanently bound to
the v2 contract.  This builder never edits v2: it creates a child contract for
the final E3 release package so status/evidence updates cannot invalidate the
completed rerun source hashes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
SOURCE = (
    REPO
    / "data/ChinaInstances/"
    "china_e3_formal_release_contract_v2_20260723.json"
)
OUT = (
    REPO
    / "data/ChinaInstances/"
    "china_e3_formal_release_contract_v3_20260723.json"
)
EXPECTED_SOURCE_SHA256 = (
    "ff2e10c51a9b617d43b5d29dde44e7009a344d92fba0fa59bbf3f353a0ff3c07"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build() -> dict[str, Any]:
    source_hash = sha256(SOURCE)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(
            "HALT_V2_PARENT_CONTRACT_DRIFT:"
            f"{source_hash}!={EXPECTED_SOURCE_SHA256}"
        )
    contract = json.loads(SOURCE.read_text(encoding="utf-8"))
    contract["schema"] = (
        "resetp.china.e3-e7-formal-release-contract.v3"
    )
    contract["contract_id"] = "CHINA-E3-FORMAL-RELEASE-001-V3"
    contract["experiment_id"] = "CHINA-E3-FORMAL-RELEASE-001"
    contract["status"] = "RELEASE_CANDIDATE_GO_GATED"
    contract["formal_search_allowed"] = False
    contract["search_evaluations"] = 0
    contract["lineage"] = {
        "parent_contract": str(SOURCE.relative_to(REPO)),
        "parent_contract_sha256": source_hash,
        "parent_scope": (
            "frozen corrected private E2 and S3 rerun input contract"
        ),
        "child_scope": "pre-GO E3 release protocol and evidence references",
        "parent_mutation_allowed": False,
    }
    contract["formal_execution"]["budget_pilot"].update(
        {
            "status": "PREREGISTERED_RERUN_REQUIRED_BEFORE_GO",
            "evidence": (
                "baselines/china_e3_e7/e3_budget_pilot_v2_20260723/"
                "decision.json"
            ),
            "search_evaluations": 0,
        }
    )
    contract["paper_mapping"]["e2_policy"] = (
        "The corrected private China81 E2 and S3--S5 exhibits must be "
        "fully rerun in the registered new directories before GO; historical "
        "artifacts remain immutable. Public P1 is retained through no-search "
        "sealed-ledger replay only."
    )
    contract["source_contracts"]["calendar_panel"] = (
        "data/ChinaInstances/"
        "china81_runtime_parameter_authority_v4_20260723/"
        "tariff_carbon_48slot_calendar.csv"
    )
    contract["source_contracts"]["budget_pilot"] = (
        "baselines/china_e3_e7/"
        "e3_budget_pilot_v2_20260723/decision.json"
    )
    contract["source_contracts"]["formal_environment"] = (
        "baselines/china_e3_e7/"
        "e3_environment_authority_20260723/decision.json"
    )
    contract["source_contracts"]["public_p1_no_search_replay"] = (
        "baselines/e2_final_campaign_20260720/"
        "corrected_china81_rerun_20260723/"
        "public_p1_no_search_replay/decision.json"
    )
    contract["release_evidence_roots"] = {
        "corrected_private_e2": (
            "baselines/e2_final_campaign_20260720/"
            "corrected_china81_rerun_20260723/full_gate"
        ),
        "corrected_s3": (
            "baselines/e2_final_campaign_20260720/"
            "corrected_china81_rerun_20260723/representative_gate"
        ),
        "corrected_s3_trajectories": (
            "baselines/e2_final_campaign_20260720/"
            "corrected_china81_rerun_20260723/"
            "representative_gate/trajectories"
        ),
        "corrected_s4": (
            "baselines/e2_final_campaign_20260720/"
            "corrected_china81_rerun_20260723/table4_gate"
        ),
        "corrected_s5": (
            "baselines/e2_final_campaign_20260720/"
            "corrected_china81_rerun_20260723/artifacts"
        ),
        "full_witness_replay": (
            "baselines/e2_final_campaign_20260720/"
            "corrected_china81_rerun_20260723/full_witness_replay"
        ),
        "public_p1_no_search_replay": (
            "baselines/e2_final_campaign_20260720/"
            "corrected_china81_rerun_20260723/public_p1_no_search_replay"
        ),
    }
    write_json(OUT, contract)
    return {
        "path": str(OUT.relative_to(REPO)),
        "sha256": sha256(OUT),
        "parent_sha256": source_hash,
        "formal_search_allowed": contract["formal_search_allowed"],
        "status": contract["status"],
    }


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, sort_keys=True))
