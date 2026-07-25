#!/usr/bin/env python3
"""Blind gate for a history-expanded, quality-diverse HGS route pool."""

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
    "history_diverse_route_pool_gate"
)
PREREGISTRATION = (
    OUT.parent / "history_diverse_route_pool_preregistration.json"
)
PANEL = (
    ("cn-cy-100c-02-V2-LOCATIONS", 17),
    ("cn-jjj-100c-02-V2-LOCATIONS", 17),
    ("cn-prd-100c-02-V2-LOCATIONS", 17),
    ("cn-cy-200c-02-V2-LOCATIONS", 17),
    ("cn-jjj-200c-02-V2-LOCATIONS", 17),
    ("cn-prd-200c-02-V2-LOCATIONS", 17),
)
MAXIMUM_BUDGET = 280
MIP_SECONDS_PER_STAGE = 30.0
EPS = 1.0e-9
USABLE_MIP_STATUSES = frozenset({"OPTIMAL", "LIMIT_WITH_INCUMBENT"})


def source_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(REPO)): development.sha256(path)
        for path in (
            PREREGISTRATION,
            PROTOTYPE / "pyvrp_adapter.py",
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
    development.MIP_SECONDS_PER_STAGE = MIP_SECONDS_PER_STAGE
    development.COLLECT_HISTORICAL_POPULATION_ARCHIVE = True
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
    errors: list[dict[str, Any]] = []
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
            try:
                row = future.result()
            except Exception as exc:
                errors.append(
                    {
                        "instance_id": instance_id,
                        "seed": seed,
                        "failure_type": type(exc).__name__,
                        "failure": str(exc),
                    }
                )
                print(
                    "[HISTORY-DIVERSE-ROUTE-POOL] "
                    f"{instance_id} seed={seed} ERROR {exc}",
                    flush=True,
                )
                continue
            rows.append(row)
            print(
                "[HISTORY-DIVERSE-ROUTE-POOL] "
                f"{instance_id} seed={seed} "
                f"delta={row['candidate_minus_stage_1']:.9f} "
                "fusion_delta="
                f"{row['candidate_minus_best_current_single_view']:.9f} "
                f"history={row['historical_population_snapshot_count']}/"
                f"{row['historical_diversity_selected_count']} "
                f"mip={row['expanded_mip_status']} "
                f"curve={row['MV-HGS-SP_curve_points']}/"
                f"{row['MV-HGS-SP_strict_decreases']} "
                f"elapsed={row['elapsed_seconds']:.1f}s",
                flush=True,
            )
    rows.sort(key=lambda row: (row["instance_id"], row["seed"]))
    raw_rows: list[dict[str, Any]] = []
    if rows:
        raw_fields = [*rows[0], "failure_type", "failure"]
        raw_rows.extend(
            {
                **row,
                "failure_type": "",
                "failure": "",
            }
            for row in rows
        )
        for error in errors:
            error_row = {field: "" for field in raw_fields}
            error_row.update(error)
            error_row["status"] = "ERROR"
            raw_rows.append(error_row)
    else:
        raw_rows.extend(
            {**error, "status": "ERROR"} for error in errors
        )
    raw_rows.sort(
        key=lambda row: (str(row["instance_id"]), int(row["seed"]))
    )
    development.write_csv(OUT / "raw_runs.csv", raw_rows)
    development.write_json(OUT / "errors.json", errors)
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
    expanded_mip_incumbents = sum(
        row["expanded_mip_status"] in USABLE_MIP_STATUSES
        for row in rows
    )
    history_gate_passes = sum(
        bool(row["historical_population_archive_enabled"])
        and bool(row["historical_stage_snapshot_gate"])
        and bool(row["historical_stage_archive_use_gate"])
        and int(row["historical_population_snapshot_count"]) == 120
        for row in rows
    )
    invariant_pass = bool(
        len(rows) == 6
        and not errors
        and expanded_mip_incumbents == 6
        and history_gate_passes == 6
        and all(row["status"] == "PASS" for row in rows)
        and all(row["all_independently_feasible"] for row in rows)
        and all(row["zero_loss_to_all_views"] for row in rows)
        and all(row["warm_route_types_preserved"] for row in rows)
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
        "PASS_HISTORY_DIVERSE_ROUTE_POOL_DEVELOPMENT_GATE"
        if passed
        else "HALT_HISTORY_DIVERSE_ROUTE_POOL_DEVELOPMENT_GATE"
    )
    decision = {
        "schema": (
            "resetp.history-diverse-route-pool-development.decision.v1"
        ),
        "verdict": verdict,
        "formal_evidence": False,
        "invariant_pass": invariant_pass,
        "completed_tasks": len(rows),
        "error_tasks": len(errors),
        "history_archive_gate_passes": history_gate_passes,
        "required_history_archive_gate_passes": 6,
        "expanded_mip_checked_incumbents": expanded_mip_incumbents,
        "required_expanded_mip_checked_incumbents": 6,
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
        "panel_size": len(PANEL),
        "preregistration_sha256": development.sha256(
            PREREGISTRATION
        ),
        "claim_boundary": (
            "development only; no paper or formal experiment claim"
        ),
    }
    development.write_json(OUT / "decision.json", decision)
    development.write_json(
        OUT / "metadata.json",
        {
            "schema": (
                "resetp.history-diverse-route-pool-development."
                "metadata.v1"
            ),
            "created_at_utc": datetime.now(UTC).isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "workers": workers,
            "mip_time_limit_seconds_per_stage": (
                MIP_SECONDS_PER_STAGE
            ),
            "source_hashes": source_hashes(),
        },
    )
    (OUT / "report.md").write_text(
        "# History-diverse route-pool development gate\n\n"
        f"Decision: `{verdict}`.\n\n"
        f"The fresh seed-17 panel completed {len(rows)}/6 tasks with "
        f"{len(errors)} errors, {history_gate_passes}/6 complete history "
        "archive ledgers, and "
        f"{expanded_mip_incumbents}/6 checked expanded-pool MIP "
        "incumbents. It produced "
        f"{strict_improvements}/6 strict improvements over protected "
        f"stage 1, {wins_e}/6 strict wins over HGS-E, {wins_m}/6 strict "
        f"wins over HGS-M, {fusion_wins}/6 strict route-fusion "
        "improvements over the best current single view, and "
        f"{curve_passes}/6 trajectories meeting the registered shape "
        "gate. The complete-candidate evaluation cap remains 280.\n",
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
