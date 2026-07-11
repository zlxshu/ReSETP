"""Machine-checkable submission contract shared by the E1--E7 formal lanes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .instance_registry import FORMAL_INSTANCE_ORDER


SCHEMA_VERSION = "resetp.submission-contract.v1"
OWNER_SCHEMA_VERSION = "resetp.customer-owner-manifest.v1"
FROZEN_STATUS = "FROZEN_BY_USER"
PROPOSED_STATUS = "PROPOSED_PENDING_USER_CONFIRMATION"


class SubmissionContractError(RuntimeError):
    """Raised before a formal run when its paper contract is not trustworthy."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SubmissionContractError(message)


def load_submission_contract(
    path: str | Path,
    *,
    repo_root: str | Path,
    require_frozen: bool = True,
) -> dict[str, Any]:
    """Load and validate the single contract that a submission run must cite."""

    contract_path = Path(path)
    if not contract_path.is_absolute():
        contract_path = Path(repo_root) / contract_path
    _require(contract_path.is_file(), f"submission contract is missing: {contract_path}")
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    _require(payload.get("schema_version") == SCHEMA_VERSION, "submission contract schema is not v1")
    _require(bool(payload.get("contract_id")), "submission contract_id is missing")
    status = str(payload.get("status", ""))
    _require(status in {PROPOSED_STATUS, FROZEN_STATUS}, f"unknown submission contract status: {status}")
    if require_frozen:
        _require(status == FROZEN_STATUS, "submission contract is only a proposal; user confirmation is still required")

    algorithm = dict(payload.get("algorithm_core_e2") or {})
    _require(algorithm.get("reuse_frozen_e2") is True, "frozen E2 must be preserved as the core algorithm comparison")
    _require(int(algorithm.get("eval_budget", 0)) > 0, "algorithm comparison budget must be positive")

    model = dict(payload.get("full_model") or {})
    _require(float(model.get("main_battery_kwh", 0.0)) > 0.0, "main battery capacity must be positive")
    robustness = [float(value) for value in model.get("robustness_battery_kwh", [])]
    _require(all(value > 0.0 for value in robustness), "robustness battery capacities must be positive")

    ownership = dict(model.get("customer_ownership") or {})
    _require(ownership.get("rule") == "nearest_depot_by_bundle_distance", "customer ownership rule is not explicit")
    manifest_rel = Path(str(ownership.get("manifest_path", "")))
    _require(bool(str(manifest_rel)), "customer ownership manifest path is missing")
    manifest_path = manifest_rel if manifest_rel.is_absolute() else Path(repo_root) / manifest_rel
    _require(manifest_path.is_file(), f"customer ownership manifest is missing: {manifest_path}")
    _require(_sha256(manifest_path) == ownership.get("manifest_sha256"), "customer ownership manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _require(manifest.get("schema_version") == OWNER_SCHEMA_VERSION, "customer ownership manifest schema mismatch")
    _require(tuple(manifest.get("formal_instances", [])) == FORMAL_INSTANCE_ORDER, "customer ownership instance order mismatch")
    _require(manifest.get("rule") == ownership.get("rule"), "customer ownership rule differs from its manifest")

    cross_site = dict(model.get("cross_site_fee") or {})
    baseline = float(cross_site.get("shared_baseline_gbp_per_customer", -1.0))
    sensitivity = [float(value) for value in cross_site.get("sensitivity_gbp_per_customer", [])]
    _require(baseline >= 0.0, "cross-site shared baseline must be nonnegative")
    _require(baseline in sensitivity, "cross-site sensitivity grid must include the shared baseline")
    _require(all(value >= 0.0 for value in sensitivity), "cross-site sensitivity fees must be nonnegative")

    fairness = dict(model.get("fairness") or {})
    _require(fairness.get("enabled_from_search_start") is True, "full-model fairness must be active during search")
    _require(fairness.get("theta_selection") == "calibrate_around_natural_binding_range", "fairness theta rule is not binding-aware")

    quota = dict(model.get("carbon_quota") or {})
    _require(float(quota.get("baseline_factor", 0.0)) > 0.0, "carbon quota baseline factor must be positive")
    _require(quota.get("claim_role") == "accounting_only", "linear quota must not be claimed as a route-changing mechanism")

    return payload
