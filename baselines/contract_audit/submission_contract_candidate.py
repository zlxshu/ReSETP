#!/usr/bin/env python3
"""Build the proposed E1--E7 contract and deterministic customer-owner manifest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from setp_solver.profit import infer_customer_home_depots
from setp_solver.search.bundle import load_search_bundle
from setp_solver.search.instance_registry import FORMAL_INSTANCE_ORDER, assert_formal_benchmark_ready, iter_formal_bundles
from setp_solver.search.submission_contract import (
    E2_LANE,
    FROZEN_STATUS,
    FULL_MODEL_LANE,
    OWNER_SCHEMA_VERSION,
    SCHEMA_VERSION,
    SubmissionContractError,
    load_submission_contract,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def artifact_hashes(output: Path) -> dict[str, str]:
    return {
        str(path.relative_to(output)): sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "artifact_hashes.json" and not path.name.startswith("._")
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    assert_formal_benchmark_ready(root)

    rows: list[dict[str, str]] = []
    bundle_hashes: dict[str, dict[str, str]] = {}
    for instance_name, bundle_dir in iter_formal_bundles(root):
        bundle = load_search_bundle(bundle_dir)
        owners = infer_customer_home_depots(bundle.instance)
        rows.extend(
            {"instance": instance_name, "customer_id": customer_id, "home_depot_id": depot_id}
            for customer_id, depot_id in sorted(owners.items())
        )
        bundle_hashes[instance_name] = {
            name: sha256(bundle_dir / name)
            for name in ("instance.json", "nodes.csv", "distance_matrix.npy", "three_shift_manifest.json")
        }
    owner_csv = output / "customer_owner_rows.csv"
    with owner_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["instance", "customer_id", "home_depot_id"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    owner_manifest = {
        "schema_version": OWNER_SCHEMA_VERSION,
        "rule": "nearest_depot_by_bundle_distance",
        "formal_instances": list(FORMAL_INSTANCE_ORDER),
        "customer_count": len(rows),
        "owner_rows_path": str(owner_csv.relative_to(root)),
        "owner_rows_sha256": sha256(owner_csv),
        "bundle_hashes": bundle_hashes,
    }
    owner_manifest_path = output / "customer_owner_manifest.json"
    write_json(owner_manifest_path, owner_manifest)

    contract = {
        "schema_version": SCHEMA_VERSION,
        "contract_id": "resetp-e1-e7-submission-20260713-v3",
        "algorithm_core_e2": {
            "status": FROZEN_STATUS,
            "reuse_frozen_e2_rows": True,
            "freeze_tag": "e2-submission-20260711",
            "eval_budget": 4000,
            "independent_runs_per_instance": 10,
            "seeds": list(range(1, 11)),
            "algorithms": [
                "staged_hybrid_carbon_aware",
                "GA",
                "PSO",
                "VNS",
                "ACO",
                "GA-VNS",
                "LNS",
                "GWO",
                "IWD",
            ],
            "scope": "core_algorithm_benchmark_10seed_extension",
            "main_battery_kwh": 280.0,
            "robustness_battery_kwh": [80.0],
            "formal_instance_order": list(FORMAL_INSTANCE_ORDER),
            "formal_instance_hashes": bundle_hashes,
            "fairness_enabled": False,
            "cross_site_fee_gbp_per_customer": 0.0,
            "reference_solution_reporting": {
                "self_instance_bks_gap_table": False,
                "current_outputs": ["ten_run_mean", "standard_deviation", "best", "runtime", "feasibility", "pairwise_statistics"],
                "standard_benchmark_status": "deferred_post_e2",
                "planned_reference_solver": "unmodified_Goeke_algorithm",
                "planned_standard_outputs": ["BKS", "AVG", "Gap%"],
                "boundary": "The unmodified Goeke algorithm is not a competitor in the current self-created-instance E2 table.",
            },
        },
        "full_model": {
            "status": FROZEN_STATUS,
            "main_battery_kwh": 280.0,
            "robustness_battery_kwh": [80.0],
            "customer_ownership": {
                "rule": "nearest_depot_by_bundle_distance",
                "decision_role": "synthetic_independent_operations_baseline",
                "research_status": "user_approved_for_e3_e7_contract",
                "manifest_path": str(owner_manifest_path.relative_to(root)),
                "manifest_sha256": sha256(owner_manifest_path),
            },
            "cross_site_fee": {
                "shared_baseline_gbp_per_customer": 0.0,
                "sensitivity_gbp_per_customer": [0.0, 10.0, 25.0, 50.0, 95.0],
                "unit": "GBP_per_customer_service",
                "claim_boundary": "0 is the fully shared main baseline; nonzero values are uncalibrated proxy friction sensitivities only, with 95 as a historical stress point.",
                "research_status": "user_approved_proxy_sensitivity_only",
            },
            "fairness": {
                "global_default": "off",
                "enabled_during_search_when_required": True,
                "required_experiments": [
                    "E3_full_model",
                    "E3_friction_axis",
                    "E4_carbon_price_reoptimization",
                    "E6",
                    "E7_all_arms",
                ],
                "disabled_experiments": [
                    "E2_frozen_algorithm_benchmark",
                    "E3_mechanism_isolation_layers_0_to_4",
                ],
                "theta_selection": "calibrate_around_natural_binding_range",
            },
            "carbon_quota": {
                "default_quota_kg": 0.0,
                "baseline_factor": 0.8,
                "claim_role": "accounting_only",
                "research_status": "user_approved_full_accounting_default",
            },
        },
    }
    contract_path = output / "submission_contract.proposed.json"
    write_json(contract_path, contract)
    proposal_valid = True
    try:
        load_submission_contract(contract_path, repo_root=root, require_frozen=True, lane=E2_LANE)
    except SubmissionContractError:
        proposal_valid = False
    formal_gate_blocked = False
    try:
        load_submission_contract(contract_path, repo_root=root, require_frozen=True, lane=FULL_MODEL_LANE)
    except SubmissionContractError:
        formal_gate_blocked = True
    decision = {
        "verdict": "E1_E7_CONTRACT_FROZEN_BY_USER",
        "proposal_structurally_valid": proposal_valid,
        "formal_gate_correctly_blocked": formal_gate_blocked,
        "full_model_gate_passes": not formal_gate_blocked,
        "formal_instance_count": len(FORMAL_INSTANCE_ORDER),
        "customer_owner_row_count": len(rows),
        "zero_search": True,
        "next_action": "Run only the WP0 E0 wiring check and the approved E3 short gate next; do not start E3-E7 formal search in this WP0 task. Keep unmodified-Goeke public-benchmark BKS/AVG/Gap% deferred until after the self-created-instance E2 table.",
    }
    metadata = {
        "schema_version": "resetp.submission-contract-candidate-evidence.v1",
        "execution_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "generator": "baselines/contract_audit/submission_contract_candidate.py",
        "zero_search": True,
        "source_hashes": {
            relative: sha256(root / relative)
            for relative in (
                "baselines/contract_audit/submission_contract_candidate.py",
                "solver/src/setp_solver/search/submission_contract.py",
                "solver/tests/test_submission_contract_gate.py",
            )
        },
    }
    write_json(output / "metadata.json", metadata)
    write_json(output / "decision.json", decision)
    (output / "raw_runs.csv").write_text(
        "check,ok\ne2_contract_frozen,true\nfull_model_gate_passes,true\n",
        encoding="utf-8",
    )
    (output / "report.md").write_text(
        "# E1--E7投稿合同机器闸门\n\n"
        "大白话：E2算法比赛规则和E3-E7完整模型投稿口径已经按用户拍板冻结。"
        "主场景是280 kWh，最近车场映射是合成独立经营基线，跨场费0是主值，非零档位只是无现实标定的摩擦代理。"
        "公平在E3完整模型、摩擦扫描、E4碳价重优化、E6和E7全部方案中从搜索阶段启用；E2封存比赛和E3前五层机制隔离保持关闭。"
        "配额默认0且只作会计项。"
        "这一步没有运行E3-E7求解器；它只把后续实验的开关固定下来。BKS、AVG、Gap%仍留到E2后的公开Goeke标准算例补实验。\n\n",
        encoding="utf-8",
    )
    write_json(output / "artifact_hashes.json", artifact_hashes(output))
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    if not proposal_valid or formal_gate_blocked:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
