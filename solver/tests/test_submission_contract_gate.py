from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from setp_solver.search.instance_registry import FORMAL_INSTANCE_ORDER
from setp_solver.search.submission_contract import (
    FROZEN_STATUS,
    OWNER_SCHEMA_VERSION,
    PROPOSED_STATUS,
    SCHEMA_VERSION,
    SubmissionContractError,
    load_submission_contract,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _fixture(tmp_path: Path, *, status: str) -> Path:
    owner_path = tmp_path / "owners.json"
    _write_json(
        owner_path,
        {
            "schema_version": OWNER_SCHEMA_VERSION,
            "formal_instances": list(FORMAL_INSTANCE_ORDER),
            "rule": "nearest_depot_by_bundle_distance",
            "rows": [],
        },
    )
    contract_path = tmp_path / "contract.json"
    _write_json(
        contract_path,
        {
            "schema_version": SCHEMA_VERSION,
            "contract_id": "test-contract",
            "status": status,
            "algorithm_core_e2": {"reuse_frozen_e2": True, "eval_budget": 4000},
            "full_model": {
                "main_battery_kwh": 280.0,
                "robustness_battery_kwh": [80.0],
                "customer_ownership": {
                    "rule": "nearest_depot_by_bundle_distance",
                    "manifest_path": "owners.json",
                    "manifest_sha256": hashlib.sha256(owner_path.read_bytes()).hexdigest(),
                },
                "cross_site_fee": {
                    "shared_baseline_gbp_per_customer": 0.0,
                    "sensitivity_gbp_per_customer": [0.0, 10.0, 25.0, 50.0, 95.0],
                },
                "fairness": {
                    "enabled_from_search_start": True,
                    "theta_selection": "calibrate_around_natural_binding_range",
                },
                "carbon_quota": {"baseline_factor": 0.8, "claim_role": "accounting_only"},
            },
        },
    )
    return contract_path


def test_proposed_contract_is_readable_but_cannot_start_formal_run(tmp_path: Path) -> None:
    path = _fixture(tmp_path, status=PROPOSED_STATUS)
    assert load_submission_contract(path, repo_root=tmp_path, require_frozen=False)["status"] == PROPOSED_STATUS
    with pytest.raises(SubmissionContractError, match="only a proposal"):
        load_submission_contract(path, repo_root=tmp_path, require_frozen=True)


def test_frozen_contract_passes_the_formal_gate(tmp_path: Path) -> None:
    path = _fixture(tmp_path, status=FROZEN_STATUS)
    assert load_submission_contract(path, repo_root=tmp_path)["contract_id"] == "test-contract"


def test_owner_manifest_hash_drift_stops_the_run(tmp_path: Path) -> None:
    path = _fixture(tmp_path, status=FROZEN_STATUS)
    (tmp_path / "owners.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SubmissionContractError, match="hash mismatch"):
        load_submission_contract(path, repo_root=tmp_path)


def test_nonbinding_fairness_grid_is_rejected(tmp_path: Path) -> None:
    path = _fixture(tmp_path, status=FROZEN_STATUS)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["full_model"]["fairness"]["theta_selection"] = "fixed_coarse_grid"
    _write_json(path, payload)
    with pytest.raises(SubmissionContractError, match="binding-aware"):
        load_submission_contract(path, repo_root=tmp_path)

