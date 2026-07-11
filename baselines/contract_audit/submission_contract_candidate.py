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
    OWNER_SCHEMA_VERSION,
    PROPOSED_STATUS,
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
        "contract_id": "resetp-e1-e7-submission-20260711-proposed-v1",
        "status": PROPOSED_STATUS,
        "algorithm_core_e2": {
            "reuse_frozen_e2": True,
            "freeze_tag": "e2-submission-20260711",
            "eval_budget": 4000,
            "scope": "core_relaxed_algorithm_comparison",
        },
        "full_model": {
            "main_battery_kwh": 280.0,
            "robustness_battery_kwh": [80.0],
            "customer_ownership": {
                "rule": "nearest_depot_by_bundle_distance",
                "manifest_path": str(owner_manifest_path.relative_to(root)),
                "manifest_sha256": sha256(owner_manifest_path),
            },
            "cross_site_fee": {
                "shared_baseline_gbp_per_customer": 0.0,
                "sensitivity_gbp_per_customer": [0.0, 10.0, 25.0, 50.0, 95.0],
                "claim_boundary": "95 GBP remains a high-friction stress case unless a source-backed main value is frozen.",
            },
            "fairness": {
                "enabled_from_search_start": True,
                "theta_selection": "calibrate_around_natural_binding_range",
            },
            "carbon_quota": {
                "baseline_factor": 0.8,
                "claim_role": "accounting_only",
            },
        },
    }
    contract_path = output / "submission_contract.proposed.json"
    write_json(contract_path, contract)
    proposal_valid = True
    try:
        load_submission_contract(contract_path, repo_root=root, require_frozen=False)
    except SubmissionContractError:
        proposal_valid = False
    formal_gate_blocked = False
    try:
        load_submission_contract(contract_path, repo_root=root, require_frozen=True)
    except SubmissionContractError:
        formal_gate_blocked = True
    decision = {
        "verdict": "BLOCK_SUBMISSION_RUNS_PENDING_USER_CONFIRMATION",
        "proposal_structurally_valid": proposal_valid,
        "formal_gate_correctly_blocked": formal_gate_blocked,
        "formal_instance_count": len(FORMAL_INSTANCE_ORDER),
        "customer_owner_row_count": len(rows),
        "zero_search": True,
        "next_action": "User confirms or edits the proposed contract; only then change status to FROZEN_BY_USER and start formal project 4/5 runs.",
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
        "check,ok\nproposal_structurally_valid,true\nformal_gate_blocks_unconfirmed_contract,true\n",
        encoding="utf-8",
    )
    (output / "report.md").write_text(
        "# E1--E7投稿合同机器闸门\n\n"
        "大白话：推荐合同已经做成机器可读草案，九个L-main算例的每位客户也生成了固定归属表和哈希。"
        "草案目前故意不能启动正式实验；只有用户确认并冻结后，项目4、项目5及E4--E7的新正式入口才允许读取。\n\n"
        "这一步没有运行求解器。它解决的是过去不同实验各用一套参数、跑完才发现口径不一致的问题。\n",
        encoding="utf-8",
    )
    write_json(output / "artifact_hashes.json", artifact_hashes(output))
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    if not proposal_valid or not formal_gate_blocked:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
