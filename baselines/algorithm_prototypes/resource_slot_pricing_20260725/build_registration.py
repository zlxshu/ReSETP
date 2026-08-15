#!/usr/bin/env python3
"""Freeze the three matched lane pairs and every executable dependency."""

from __future__ import annotations

import csv
from datetime import datetime, timezone

from common import (
    AUTHORITY,
    PACKAGE,
    REGISTRATION,
    REPO,
    V7_ROOT,
    sha256,
    write_json,
)


INSTANCE_IDS = (
    "cn-cy-25c-02-V2-LOCATIONS",
    "cn-jjj-75c-01-V2-LOCATIONS",
    "cn-jjj-150c-02-V2-LOCATIONS",
)
LANES = ("LOCAL", "RESOURCE-SLOT")
SOURCE_PATHS = (
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/__init__.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/build_registration.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/common.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/independent_replay.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/pricing_core.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/run_engineering_gate.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/run_g0.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/run_release_chain.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/test_engineering.py",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/monitor_engineering.json",
    "baselines/algorithm_prototypes/resource_slot_pricing_20260725/monitor_g0.json",
    "baselines/algorithm_prototypes/dual_guided_resource_order_20260725/lp_duals.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/contracts.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/decoder_cache.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/evaluation.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/fleet_assignment_dp.py",
    "baselines/algorithm_prototypes/genuine_hgs_rr_20260724/reference_decoder.py",
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/china81_columns.py",
    "baselines/algorithm_prototypes/route_column_mip_assembly_20260725/mip_core.py",
    "baselines/algorithm_prototypes/unordered_route_pair_mip_20260725/pair_core.py",
    "baselines/algorithm_prototypes/china81_mechanism_hybrid_20260720/pyvrp_adapter.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/charging.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/china81.py",
    "solver/src/setp_solver/china81_completion.py",
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/prices.py",
    "solver/src/setp_solver/search/evaluation.py",
    "solver/src/setp_solver/solution.py",
)
PROTECTED_PATHS = (
    "docs/handoff/e2_resource_slot_pricing_candidate_review_20260725.md",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/china81_completion.py",
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/prices.py",
    "solver/src/setp_solver/search/evaluation.py",
    "docs/paper_v2/RETIRED_paper_main.tex",
)


def main() -> int:
    if REGISTRATION.exists():
        raise RuntimeError(f"registration already exists: {REGISTRATION}")
    with (V7_ROOT / "raw_runs.csv").open(encoding="utf-8", newline="") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row["instance_id"] in INSTANCE_IDS
        ]
    tasks = []
    inputs = []
    for instance_id in INSTANCE_IDS:
        group = sorted(
            [row for row in rows if row["instance_id"] == instance_id],
            key=lambda row: int(row["seed"]),
        )
        if [int(row["seed"]) for row in group] != [1, 2, 3, 4, 5]:
            raise RuntimeError(f"incomplete v7 HGS-M ledger: {instance_id}")
        start = min(
            group,
            key=lambda row: (float(row["HGS-M_cost"]), int(row["seed"])),
        )
        parents = []
        for row in group:
            witness = (
                V7_ROOT
                / "tasks"
                / row["task_id"]
                / "solution_witnesses.json"
            )
            parents.append(
                {
                    "seed": int(row["seed"]),
                    "task_id": row["task_id"],
                    "expected_hgs_m_objective": float(row["HGS-M_cost"]),
                    "witness_key": "HGS-M",
                    "witness_path": witness.relative_to(REPO).as_posix(),
                    "witness_sha256": sha256(witness),
                }
            )
        base = {
            "instance_id": instance_id,
            "start_seed": int(start["seed"]),
            "start_expected_objective": float(start["HGS-M_cost"]),
            "start_hgs_m_cpu_seconds": float(start["HGS-M_cpu_seconds"]),
            "parents": parents,
        }
        inputs.append(base)
        for lane in LANES:
            tasks.append(
                {
                    **base,
                    "lane": lane,
                    "task_id": f"{instance_id}__{lane}",
                }
            )
    write_json(
        REGISTRATION,
        {
            "schema": "resetp.resource-slot-pricing-g0-registration.v1",
            "status": "FROZEN_BEFORE_ENGINEERING_AND_G0",
            "registered_at_utc": datetime.now(timezone.utc).isoformat(),
            "approval_id": "E2-RESOURCE-SLOT-PRICING-PREREG-027",
            "user_authority": (
                "ZERO_OBJECTIVE_ENGINEERING_THEN_ONE_FROZEN_SIX_TASK_G0"
            ),
            "contract": {
                "path": (
                    "docs/handoff/"
                    "e2_resource_slot_pricing_candidate_review_20260725.md"
                ),
                "sha256": sha256(
                    REPO
                    / "docs/handoff/"
                    "e2_resource_slot_pricing_candidate_review_20260725.md"
                ),
            },
            "authority": {
                "path": AUTHORITY.relative_to(REPO).as_posix(),
                "sha256": sha256(AUTHORITY),
            },
            "config": {
                "workers": 6,
                "ng_rule": "max(8,floor(0.2*n))",
                "new_outgoing_arcs_per_customer": 6,
                "max_label_extensions": 50000,
                "max_generated_routes": 8,
                "complete_candidate_evaluations_per_task": 1,
                "task_wall_seconds": 60.0,
                "mip_time_limit_seconds": 5.0,
                "engineering_max_extensions": 256,
                "engineering_wall_seconds": 30.0,
                "minimum_available_memory_percent": 10.0,
                "maximum_projected_peak_rss_bytes": 4294967296,
            },
            "inputs": inputs,
            "tasks": tasks,
            "source_hashes": {
                relative: sha256(REPO / relative) for relative in SOURCE_PATHS
            },
            "protected_hashes": [
                {"path": relative, "sha256": sha256(REPO / relative)}
                for relative in PROTECTED_PATHS
            ],
            "claim_boundary": (
                "One frozen zero-objective engineering gate and, only after "
                "PASS, one six-task low-cost G0. No broader China81 run, "
                "public benchmark, BKS/SOTA claim, E3, paper claim, rescue, "
                "retuning, instance replacement, or budget expansion."
            ),
        },
    )
    print(REGISTRATION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
