#!/usr/bin/env python3
"""Reproduce the small-instance history-ledger HALT without formal rerun.

This diagnostic executes the frozen staged search once on the exact failed
unit and records every stage's archive accounting before the formal gate is
applied.  It does not modify the formal V5/V6 campaign directories.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
CAMPAIGN_ROOT = REPO / "baselines/e2_final_campaign_20260720"
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
for path in (CAMPAIGN_ROOT, REPO / "solver/src", PROTOTYPE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_corrected_china81_d6 as corrected_base  # noqa: E402
from staged_checkpoint_hgs_sp import (  # noqa: E402
    VIEW_ORDER,
    run_staged_checkpoint_hgs_sp,
)
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import exact_china81_score  # noqa: E402


OUT = (
    CAMPAIGN_ROOT
    / "algorithm_repair_diagnostic_20260724"
    / "history_archive_small_instance_v1"
)
INSTANCE_ID = "cn-cy-10c-01-V2-LOCATIONS"
SEED = 1
STAGE_1_ITERATIONS = 5_000
STAGE_2_ITERATIONS = 20_000
STAGE_1_CHECKPOINT_INTERVAL = 250
STAGE_2_CHECKPOINT_INTERVAL = 1_000
ARCHIVE_LIMIT = 24
EXPECTED_SNAPSHOTS_PER_STAGE = 20
REQUIRED_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("diagnostic CSV requires at least one row")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    for key, expected in REQUIRED_THREAD_ENV.items():
        actual = os.environ.get(key)
        if actual != expected:
            raise RuntimeError(
                f"thread environment mismatch: {key}={actual!r}, "
                f"expected {expected!r}"
            )

    OUT.mkdir(parents=True, exist_ok=True)
    bundle = load_china81_bundle(REPO, INSTANCE_ID)
    initial = corrected_base._load_initial(INSTANCE_ID)
    run = run_staged_checkpoint_hgs_sp(
        bundle,
        initial,
        seed=SEED,
        stage_1_iterations=STAGE_1_ITERATIONS,
        stage_2_iterations=STAGE_2_ITERATIONS,
        stage_1_checkpoint_interval=STAGE_1_CHECKPOINT_INTERVAL,
        stage_2_checkpoint_interval=STAGE_2_CHECKPOINT_INTERVAL,
        archive_candidates_per_stage=ARCHIVE_LIMIT,
        mip_seconds_per_stage=30.0,
        collect_historical_population_archive=True,
        wallclock_safety_seconds_per_stage=900.0,
    )

    rows: list[dict[str, Any]] = []
    for view in VIEW_ORDER:
        for stage_number, stage in enumerate(run.stages[view], start=1):
            stats = stage.stats
            unique_count = int(stats["archive_unique_native_candidates"])
            quality_count = int(stats["archive_quality_selected_count"])
            diversity_count = int(
                stats["archive_diversity_selected_count"]
            )
            selected_count = quality_count + diversity_count
            expected_selected_count = min(ARCHIVE_LIMIT, unique_count)
            rows.append(
                {
                    "instance_id": INSTANCE_ID,
                    "seed": SEED,
                    "view": view,
                    "stage": stage_number,
                    "hgs_iterations": int(stats["hgs_iterations"]),
                    "snapshot_count": int(
                        stats["historical_population_snapshot_count"]
                    ),
                    "historical_candidate_references": int(
                        stats[
                            "historical_population_candidate_references"
                        ]
                    ),
                    "archive_unique_native_candidates": unique_count,
                    "quality_selected_count": quality_count,
                    "diversity_selected_count": diversity_count,
                    "selected_count": selected_count,
                    "expected_selected_count": expected_selected_count,
                    "snapshot_gate": (
                        int(
                            stats[
                                "historical_population_snapshot_count"
                            ]
                        )
                        == EXPECTED_SNAPSHOTS_PER_STAGE
                    ),
                    "history_referenced_gate": (
                        int(
                            stats[
                                "historical_population_candidate_references"
                            ]
                        )
                        > 0
                    ),
                    "archive_selection_complete_gate": (
                        selected_count == expected_selected_count
                    ),
                    "legacy_diversity_positive_gate": (
                        diversity_count > 0
                    ),
                    "wallclock_safety_triggered": bool(
                        stats["wallclock_safety_triggered"]
                    ),
                }
            )

    returned = {
        **{
            view: run.view_completions[view].solution
            for view in VIEW_ORDER
        },
        "MV-HGS-SP": run.solution,
    }
    exact_rechecks: dict[str, dict[str, Any]] = {}
    for name, solution in returned.items():
        objective, _breakdown, violations = exact_china81_score(
            solution,
            bundle,
        )
        exact_rechecks[name] = {
            "objective": float(objective),
            "violation_count": len(violations),
        }

    only_legacy_gate_failed = (
        all(row["snapshot_gate"] for row in rows)
        and all(row["history_referenced_gate"] for row in rows)
        and all(row["archive_selection_complete_gate"] for row in rows)
        and any(not row["legacy_diversity_positive_gate"] for row in rows)
        and not any(
            check["violation_count"] for check in exact_rechecks.values()
        )
    )
    verdict = (
        "CONFIRM_SMALL_ARCHIVE_LEGACY_GATE_BUG"
        if only_legacy_gate_failed
        else "HALT_DIAGNOSTIC_FOUND_DIFFERENT_FAILURE"
    )

    _write_csv(OUT / "raw_runs.csv", rows)
    _write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.history-archive-small-instance-diagnostic.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "instance_id": INSTANCE_ID,
            "seed": SEED,
            "formal_search": False,
            "formal_v5_v6_artifacts_modified": False,
            "python": sys.version,
            "platform": platform.platform(),
            "thread_environment": REQUIRED_THREAD_ENV,
            "source_hashes": {
                str(path.relative_to(REPO)): _sha256(path)
                for path in (
                    Path(__file__).resolve(),
                    PROTOTYPE / "epochal_hgs.py",
                    PROTOTYPE / "staged_checkpoint_hgs_sp.py",
                    CAMPAIGN_ROOT
                    / "run_corrected_china81_d6_staged_portfolio.py",
                )
            },
        },
    )
    _write_json(
        OUT / "decision.json",
        {
            "verdict": verdict,
            "only_legacy_gate_failed": only_legacy_gate_failed,
            "stage_count": len(rows),
            "stage_rows": rows,
            "returned_solution_exact_rechecks": exact_rechecks,
            "claim_boundary": (
                "Diagnostic reproduction only; no formal result, algorithm "
                "change, seed change, evaluator change, or paper claim."
            ),
        },
    )
    report_lines = [
        "# Small-instance history archive diagnostic",
        "",
        f"- Verdict: `{verdict}`",
        f"- Unit: `{INSTANCE_ID}`, seed `{SEED}`",
        (
            "- Purpose: distinguish a real missing-history failure from the "
            "legacy requirement that every stage must select at least one "
            "extra diversity candidate."
        ),
        (
            "- Formal V5/V6 outputs were not read as resumable input and "
            "were not modified."
        ),
        "",
        "The raw CSV records all six view-stage archive ledgers. A stage is "
        "complete when it records all checkpoints, references historical "
        "population members, and selects every available candidate up to the "
        "frozen archive limit. Requiring a positive diversity remainder is "
        "not meaningful when the unique candidate count does not exceed the "
        "archive capacity.",
        "",
    ]
    (OUT / "report.md").write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )
    artifacts = {
        name: _sha256(OUT / name)
        for name in (
            "metadata.json",
            "raw_runs.csv",
            "decision.json",
            "report.md",
        )
    }
    _write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "excluded": [
                "artifact_hashes.json",
                "._*",
                "__pycache__",
                ".pytest_cache",
            ],
            "artifacts": artifacts,
        },
    )
    print(verdict)


if __name__ == "__main__":
    main()
