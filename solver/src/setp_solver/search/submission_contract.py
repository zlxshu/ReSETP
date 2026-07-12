"""Machine-checkable submission contract shared by the E1--E7 formal lanes.

The algorithm benchmark and the later full-model experiments deliberately have
different switches.  A frozen E2 benchmark must therefore not be blocked by a
still-open modelling choice for E4--E7, while a full-model runner must not treat
an E2 approval as approval of customer ownership, cross-depot friction, or
fairness settings.
"""

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
RESEARCH_PENDING_STATUS = "RESEARCH_PENDING"
E2_LANE = "algorithm_core_e2"
FULL_MODEL_LANE = "full_model"


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
    lane: str = FULL_MODEL_LANE,
) -> dict[str, Any]:
    """Load and validate the single contract that a submission run must cite."""

    contract_path = Path(path)
    if not contract_path.is_absolute():
        contract_path = Path(repo_root) / contract_path
    _require(contract_path.is_file(), f"submission contract is missing: {contract_path}")
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    _require(payload.get("schema_version") == SCHEMA_VERSION, "submission contract schema is not v1")
    _require(bool(payload.get("contract_id")), "submission contract_id is missing")
    _require(lane in {E2_LANE, FULL_MODEL_LANE}, f"unknown submission contract lane: {lane}")

    algorithm = dict(payload.get("algorithm_core_e2") or {})
    algorithm_status = str(algorithm.get("status", ""))
    _require(algorithm_status in {PROPOSED_STATUS, FROZEN_STATUS}, f"unknown E2 contract status: {algorithm_status}")
    if require_frozen and lane == E2_LANE:
        _require(algorithm_status == FROZEN_STATUS, "E2 contract is only a proposal; user confirmation is still required")
    _require(algorithm.get("reuse_frozen_e2_rows") is True, "validated E2 rows must be reused rather than silently rerun")
    _require(int(algorithm.get("eval_budget", 0)) > 0, "algorithm comparison budget must be positive")
    _require(int(algorithm.get("independent_runs_per_instance", 0)) == 10, "E2 must use ten independent runs per algorithm and instance")
    seeds = [int(value) for value in algorithm.get("seeds", [])]
    _require(seeds == list(range(1, 11)), "E2 seed manifest must be exactly 1--10")
    algorithms = [str(value) for value in algorithm.get("algorithms", [])]
    _require(len(algorithms) == 9 and len(set(algorithms)) == 9, "E2 must contain the primary algorithm and eight distinct healthy baselines")
    _require("ALNS-Wouda" not in algorithms, "historical ALNS-Wouda must not re-enter the E2 comparison")
    _require("staged_hybrid_carbon_naive" not in algorithms, "charging ablation belongs to E3, not the E2 algorithm table")
    _require(algorithm.get("fairness_enabled") is False, "E2 algorithm benchmark must keep fairness disabled")
    _require(float(algorithm.get("cross_site_fee_gbp_per_customer", -1.0)) == 0.0, "E2 must preserve the frozen frictionless collaboration contract")
    _require(float(algorithm.get("main_battery_kwh", 0.0)) == 280.0, "E2 main benchmark must use the approved 280 kWh scenario")
    formal_hashes = dict(algorithm.get("formal_instance_hashes") or {})
    _require(tuple(algorithm.get("formal_instance_order") or ()) == FORMAL_INSTANCE_ORDER, "E2 formal instance order must match the approved order")
    _require(set(formal_hashes) == set(FORMAL_INSTANCE_ORDER), "E2 formal instance hash registry must cover the approved instances")
    for instance_name, file_hashes in formal_hashes.items():
        _require(isinstance(file_hashes, dict) and bool(file_hashes), f"E2 instance hash registry is empty: {instance_name}")
        bundle_dir = Path(repo_root) / "models/data_bundle/generated_instances/L-main" / instance_name
        for filename, expected_hash in file_hashes.items():
            candidate = bundle_dir / str(filename)
            _require(candidate.is_file(), f"E2 instance file is missing: {candidate}")
            _require(_sha256(candidate) == str(expected_hash), f"E2 instance hash mismatch: {candidate}")
    reference = dict(algorithm.get("reference_solution_reporting") or {})
    _require(reference.get("self_instance_bks_gap_table") is False, "self-created L-main must not be presented as a published-BKS table")
    _require(reference.get("standard_benchmark_status") == "deferred_post_e2", "published-BKS benchmarking must remain a post-E2 task")
    _require(reference.get("planned_reference_solver") == "unmodified_Goeke_algorithm", "the deferred standard benchmark must preserve the unmodified Goeke reference solver")

    if lane == E2_LANE:
        return payload

    model = dict(payload.get("full_model") or {})
    model_status = str(model.get("status", ""))
    _require(model_status in {PROPOSED_STATUS, FROZEN_STATUS, RESEARCH_PENDING_STATUS}, f"unknown full-model contract status: {model_status}")
    if require_frozen:
        _require(model_status == FROZEN_STATUS, "full-model contract still has research or user decisions pending")
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
    _require(fairness.get("global_default") == "off", "fairness must not be silently enabled in every experiment")
    _require(fairness.get("enabled_during_search_when_required") is True, "fairness experiments must enforce fairness during search")
    required_fairness = set(fairness.get("required_experiments") or [])
    disabled_fairness = set(fairness.get("disabled_experiments") or [])
    _require("E3_full_model" in required_fairness, "E3 full-model rows must enforce fairness during search")
    _require("E3_friction_axis" in required_fairness, "E3 friction-axis rows must enforce fairness during search")
    _require(
        "E4_carbon_price_reoptimization" in required_fairness,
        "E4 carbon-price reoptimization rows must enforce fairness during search",
    )
    _require("E6" in required_fairness, "E6 must remain the primary fairness mechanism experiment")
    _require("E7_all_arms" in required_fairness, "all E7 arms must enforce fairness during search")
    _require(
        "E2_frozen_algorithm_benchmark" in disabled_fairness,
        "the frozen E2 algorithm benchmark must remain fairness-off",
    )
    _require(
        "E3_mechanism_isolation_layers_0_to_4" in disabled_fairness,
        "the E3 mechanism-isolation layers must remain fairness-off",
    )
    _require(fairness.get("theta_selection") == "calibrate_around_natural_binding_range", "fairness theta rule is not binding-aware")

    quota = dict(model.get("carbon_quota") or {})
    _require(float(quota.get("default_quota_kg", -1.0)) == 0.0, "default carbon quota must be zero")
    _require(float(quota.get("baseline_factor", 0.0)) > 0.0, "carbon quota baseline factor must be positive")
    _require(quota.get("claim_role") == "accounting_only", "linear quota must not be claimed as a route-changing mechanism")

    return payload
