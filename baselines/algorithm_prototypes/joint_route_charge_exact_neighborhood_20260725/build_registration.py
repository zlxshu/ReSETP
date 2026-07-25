"""Build the immutable G0 registration without running objective search."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .common import (
    CONTRACT,
    FLEET_ROOT,
    FORMAL_ROOT,
    PACKAGE,
    REPO,
    REGISTRATION,
    ROAD_ROOT,
    RUNTIME_ROOT,
    STATIC_ROOT,
    sha256,
    write_json,
)


INSTANCE_IDS = (
    "cn-cy-25c-01-V2-LOCATIONS",
    "cn-prd-75c-03-V2-LOCATIONS",
    "cn-jjj-150c-03-V2-LOCATIONS",
)
SOURCE_NAMES = (
    "__init__.py",
    "common.py",
    "exact_neighborhood.py",
    "build_registration.py",
    "worker_entry.py",
    "run_engineering_gate.py",
    "run_g0.py",
    "independent_replay.py",
)


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(REPO.resolve()))


def formal_rows() -> list[dict[str, str]]:
    with (FORMAL_ROOT / "raw_runs.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        return list(csv.DictReader(handle))


def build() -> dict[str, Any]:
    rows = formal_rows()
    tasks: list[dict[str, Any]] = []
    protected: list[Path] = [
        CONTRACT,
        FORMAL_ROOT / "raw_runs.csv",
        FORMAL_ROOT / "decision.json",
        STATIC_ROOT / "artifact_hashes.json",
        ROAD_ROOT / "artifact_hashes.json",
        RUNTIME_ROOT / "artifact_hashes.json",
        FLEET_ROOT / "artifact_hashes.json",
        REPO / "solver/src/setp_solver/cost.py",
        REPO / "solver/src/setp_solver/check.py",
        REPO / "solver/src/setp_solver/china81_completion.py",
        REPO / "solver/src/setp_solver/prices.py",
        REPO
        / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724"
        / "fleet_assignment_dp.py",
        REPO
        / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724"
        / "decoder_cache.py",
        REPO
        / "baselines/algorithm_prototypes/genuine_hgs_rr_20260724"
        / "reference_decoder.py",
    ]
    protected.extend(PACKAGE / name for name in SOURCE_NAMES)

    for instance_id in INSTANCE_IDS:
        candidates = [
            row for row in rows if row["instance_id"] == instance_id
        ]
        if len(candidates) != 5:
            raise RuntimeError(
                f"{instance_id}: expected five sealed rows, got {len(candidates)}"
            )
        best = min(
            candidates,
            key=lambda row: (
                float(row["MV-HGS-SP_cost"]),
                int(row["seed"]),
            ),
        )
        witness = (
            FORMAL_ROOT
            / "tasks"
            / best["task_id"]
            / "solution_witnesses.json"
        )
        construction = (
            FLEET_ROOT / "witnesses" / f"{instance_id}.json"
        )
        protected.extend((witness, construction))
        for arm in ("B_EXACT_NH", "AB_HGS_EXACT_NH"):
            tasks.append(
                {
                    "task_id": f"JRC-G0__{instance_id}__{arm}",
                    "instance_id": instance_id,
                    "arm": arm,
                    "hgs_seed": int(best["seed"]),
                    "hgs_expected_cost": float(
                        best["MV-HGS-SP_cost"]
                    ),
                    "hgs_witness": relative(witness),
                    "construction_witness": relative(construction),
                }
            )

    for path in protected:
        if not path.is_file():
            raise RuntimeError(f"protected input missing: {path}")
    protected_sha256 = {
        relative(path): sha256(path)
        for path in sorted(set(protected))
    }
    payload = {
        "schema": "resetp.jrc-exact-nh-g0.v1",
        "contract_id": "E2-JRC-EXACT-NH-001",
        "created_date": "2026-07-25",
        "selection_rule": (
            "result-blind SHA-256 minimum unused instance in each of "
            "the frozen 25/75/150-customer layers"
        ),
        "instances": list(INSTANCE_IDS),
        "tasks": tasks,
        "limits": {
            "workers": 6,
            "threads_per_worker": 1,
            "selected_customers": 8,
            "time_limit_seconds": 30.0,
            "new_complete_candidate_scores_per_task": 1,
            "aggregate_rss_mib": 4096,
        },
        "pass_rules": {
            "all_tasks_exact_feasible_replayed": True,
            "b_improves_count_min": 2,
            "ab_improves_count_min": 2,
            "ab_loss_count_max": 0,
            "ab_one_improvement_pct_min": 0.05,
            "ab_beats_a_and_b_count_min": 2,
            "ab_adjacency_change_min": 3,
            "ab_resource_change_min": 1,
        },
        "protected_fallback": {
            "name": "MV-HGS-SP",
            "status": "IMMUTABLE_FALLBACK",
            "formal_root": relative(FORMAL_ROOT),
        },
        "protected_sha256": protected_sha256,
    }
    write_json(REGISTRATION, payload)
    return payload


if __name__ == "__main__":
    registration = build()
    print(
        f"registered {len(registration['tasks'])} tasks at {REGISTRATION}"
    )
