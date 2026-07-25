#!/usr/bin/env python3
"""Independent confirmation for the frozen staged-deepening candidate."""

from __future__ import annotations

import json
import multiprocessing
import os
import platform
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
CAMPAIGN = REPO / "baselines/e2_final_campaign_20260720"
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
for path in (CAMPAIGN, REPO / "solver/src", PROTOTYPE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_staged_deepening_gate as development  # noqa: E402


OUT = (
    CAMPAIGN
    / "algorithm_repair_diagnostic_20260724/"
    "staged_deepening_confirmation_gate"
)
PREREGISTRATION = (
    OUT.parent / "staged_deepening_confirmation_preregistration.json"
)
PANEL = (
    ("cn-cy-75c-02-V2-LOCATIONS", 14),
    ("cn-jjj-75c-02-V2-LOCATIONS", 14),
    ("cn-prd-75c-02-V2-LOCATIONS", 14),
    ("cn-cy-200c-02-V2-LOCATIONS", 14),
    ("cn-jjj-200c-02-V2-LOCATIONS", 14),
    ("cn-prd-200c-02-V2-LOCATIONS", 14),
)
MAXIMUM_BUDGET = 280
EPS = 1.0e-9


def source_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(REPO)): development.sha256(path)
        for path in (
            PREREGISTRATION,
            PROTOTYPE / "epochal_hgs.py",
            PROTOTYPE / "route_pool_sp.py",
            PROTOTYPE / "staged_checkpoint_hgs_sp.py",
            CAMPAIGN / "run_staged_deepening_gate.py",
            Path(__file__).resolve(),
        )
    }


def configure_development_module() -> None:
    development.OUT = OUT
    development.PREREGISTRATION = PREREGISTRATION
    development.PANEL = PANEL
    development.MAXIMUM_BUDGET = MAXIMUM_BUDGET
    development.task_source_hashes = source_hashes


def run_one(instance_id: str, seed: int) -> dict[str, Any]:
    configure_development_module()
    return development.run_one(instance_id, seed)


def main() -> int:
    configure_development_module()
    OUT.mkdir(parents=True, exist_ok=True)
    if not PREREGISTRATION.is_file():
        raise FileNotFoundError(PREREGISTRATION)
    workers = min(int(os.environ.get("RESET_WORKERS", "3")), len(PANEL))
    rows: list[dict[str, Any]] = []
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=context,
        initializer=configure_development_module,
    ) as executor:
        futures = {
            executor.submit(run_one, instance_id, seed): (
                instance_id,
                seed,
            )
            for instance_id, seed in PANEL
        }
        for future in as_completed(futures):
            instance_id, seed = futures[future]
            row = future.result()
            view_best = min(
                float(row["HGS-F_cost"]),
                float(row["HGS-E_cost"]),
                float(row["HGS-M_cost"]),
            )
            row["best_current_single_view_cost"] = view_best
            row["candidate_minus_best_current_single_view"] = (
                float(row["candidate_final_cost"]) - view_best
            )
            row["strict_route_fusion_improvement"] = bool(
                float(row["candidate_final_cost"]) < view_best - EPS
            )
            rows.append(row)
            print(
                "[STAGED-DEEPENING-CONFIRMATION] "
                f"{instance_id} seed={seed} "
                f"delta={row['candidate_minus_stage_1']:.9f} "
                "fusion_delta="
                f"{row['candidate_minus_best_current_single_view']:.9f} "
                f"curve={row['MV-HGS-SP_curve_points']}/"
                f"{row['MV-HGS-SP_strict_decreases']} "
                f"elapsed={row['elapsed_seconds']:.1f}s",
                flush=True,
            )
    rows.sort(key=lambda row: (row["instance_id"], row["seed"]))
    development.write_csv(OUT / "raw_runs.csv", rows)
    strict_improvements = sum(
        bool(row["strict_improvement_over_stage_1"])
        for row in rows
    )
    wins_e = sum(bool(row["strict_win_over_HGS-E"]) for row in rows)
    wins_m = sum(bool(row["strict_win_over_HGS-M"]) for row in rows)
    fusion_wins = sum(
        bool(row["strict_route_fusion_improvement"])
        for row in rows
    )
    curve_passes = sum(bool(row["main_curve_gate"]) for row in rows)
    invariant_pass = bool(
        len(rows) == 6
        and all(row["status"] == "PASS" for row in rows)
        and all(row["all_independently_feasible"] for row in rows)
        and all(row["zero_loss_to_all_views"] for row in rows)
        and all(
            int(row["complete_candidate_attempts"])
            <= MAXIMUM_BUDGET
            for row in rows
        )
        and all(
            float(row["candidate_minus_stage_1"]) <= EPS
            for row in rows
        )
        and all(
            float(row["candidate_minus_best_current_single_view"])
            <= EPS
            for row in rows
        )
    )
    passed = bool(
        invariant_pass
        and strict_improvements >= 3
        and wins_e >= 3
        and wins_m >= 3
        and fusion_wins >= 2
        and curve_passes >= 5
    )
    verdict = (
        "PASS_STAGED_DEEPENING_CONFIRMATION_GATE"
        if passed
        else "HALT_STAGED_DEEPENING_CONFIRMATION_GATE"
    )
    decision = {
        "schema": "resetp.staged-deepening-confirmation.decision.v1",
        "verdict": verdict,
        "formal_evidence": False,
        "invariant_pass": invariant_pass,
        "strict_improvements_over_protected_stage_1": (
            strict_improvements
        ),
        "required_strict_improvements": 3,
        "strict_wins_over_HGS-E": wins_e,
        "strict_wins_over_HGS-M": wins_m,
        "required_strict_wins_per_strong_view": 3,
        "strict_route_fusion_improvements": fusion_wins,
        "required_strict_route_fusion_improvements": 2,
        "main_curve_gate_passes": curve_passes,
        "required_main_curve_gate_passes": 5,
        "panel_size": len(rows),
        "preregistration_sha256": development.sha256(
            PREREGISTRATION
        ),
        "claim_boundary": (
            "confirmation only; no paper or formal experiment claim"
        ),
    }
    development.write_json(OUT / "decision.json", decision)
    development.write_json(
        OUT / "metadata.json",
        {
            "schema": (
                "resetp.staged-deepening-confirmation.metadata.v1"
            ),
            "created_at_utc": datetime.now(UTC).isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "workers": workers,
            "source_hashes": source_hashes(),
        },
    )
    (OUT / "report.md").write_text(
        "# Staged deepening confirmation gate\n\n"
        f"Decision: `{verdict}`.\n\n"
        f"The fresh seed-14 panel produced {strict_improvements}/6 "
        "strict improvements over protected stage 1, "
        f"{wins_e}/6 strict wins over HGS-E, {wins_m}/6 strict wins "
        f"over HGS-M, {fusion_wins}/6 strict route-fusion improvements "
        "over the best current single view, and "
        f"{curve_passes}/6 genuine main-method curves meeting the "
        "registered point/decrease gate. All actual complete-candidate "
        "evaluation counts are retained in raw_runs.csv.\n",
        encoding="utf-8",
    )
    artifacts = {
        str(path.relative_to(OUT)): development.sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    development.write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": artifacts,
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
