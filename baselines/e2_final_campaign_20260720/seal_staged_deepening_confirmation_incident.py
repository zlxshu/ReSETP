#!/usr/bin/env python3
"""Seal the interrupted staged-deepening confirmation without rerunning it."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import sys
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
OUT = (
    CAMPAIGN
    / "algorithm_repair_diagnostic_20260724/"
    "staged_deepening_confirmation_gate"
)
PREREGISTRATION = (
    OUT.parent / "staged_deepening_confirmation_preregistration.json"
)
EXPECTED = (
    ("cn-cy-75c-02-V2-LOCATIONS", 14),
    ("cn-jjj-75c-02-V2-LOCATIONS", 14),
    ("cn-prd-75c-02-V2-LOCATIONS", 14),
    ("cn-cy-200c-02-V2-LOCATIONS", 14),
    ("cn-jjj-200c-02-V2-LOCATIONS", 14),
    ("cn-prd-200c-02-V2-LOCATIONS", 14),
)
FAILED = ("cn-prd-200c-02-V2-LOCATIONS", 14)
FAILURE = (
    "stage-2 warm-start projection failed: RuntimeError: "
    "Used more than 12 vehicles of type 4"
)
EPS = 1.0e-9


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    rows: list[dict[str, Any]] = []
    observed: set[tuple[str, int]] = set()
    for task_dir in sorted(
        path for path in (OUT / "tasks").iterdir() if path.is_dir()
    ):
        decision = json.loads(
            (task_dir / "decision.json").read_text(encoding="utf-8")
        )
        if decision["verdict"] != "PASS_STAGED_DEEPENING_V2_TASK":
            raise RuntimeError(f"non-PASS task {task_dir.name}")
        manifest = json.loads(
            (task_dir / "artifact_hashes.json").read_text(
                encoding="utf-8"
            )
        )
        for relative, expected_hash in manifest["artifacts"].items():
            artifact = task_dir / relative
            if (
                not artifact.is_file()
                or sha256(artifact) != expected_hash
            ):
                raise RuntimeError(f"task hash mismatch: {artifact}")
        row = dict(decision["raw_row"])
        key = (str(row["instance_id"]), int(row["seed"]))
        if key in observed:
            raise RuntimeError(f"duplicate completed task {key}")
        observed.add(key)
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
        row["failure"] = ""
        rows.append(row)
    missing = set(EXPECTED) - observed
    if missing != {FAILED}:
        raise RuntimeError(
            f"unexpected completed/missing confirmation tasks: {missing}"
        )
    error_row = {key: "" for key in rows[0]}
    error_row.update(
        {
            "instance_id": FAILED[0],
            "seed": FAILED[1],
            "status": "ERROR",
            "all_independently_feasible": False,
            "failure": FAILURE,
        }
    )
    rows.append(error_row)
    rows.sort(key=lambda row: (str(row["instance_id"]), int(row["seed"])))
    with (OUT / "raw_runs.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    completed = [row for row in rows if row["status"] == "PASS"]
    strict_improvements = sum(
        bool(row["strict_improvement_over_stage_1"])
        for row in completed
    )
    fusion_wins = sum(
        bool(row["strict_route_fusion_improvement"])
        for row in completed
    )
    curve_passes = sum(
        bool(row["main_curve_gate"]) for row in completed
    )
    decision = {
        "schema": (
            "resetp.staged-deepening-confirmation-incident.decision.v1"
        ),
        "verdict": "HALT_STAGED_DEEPENING_CONFIRMATION_EXECUTION",
        "formal_evidence": False,
        "completed_tasks": len(completed),
        "expected_tasks": len(EXPECTED),
        "error_tasks": 1,
        "failed_task": {
            "instance_id": FAILED[0],
            "seed": FAILED[1],
            "failure": FAILURE,
        },
        "completed_strict_improvements_over_stage_1": (
            strict_improvements
        ),
        "completed_strict_route_fusion_improvements": fusion_wins,
        "completed_main_curve_gate_passes": curve_passes,
        "acceptance_evaluated": False,
        "rerun_authorized": False,
        "root_cause": (
            "_project_initial_solution maps every warm-start route to "
            "the depot CV vehicle type, ignoring route.vehicle_type; the "
            "200-customer warm elite exceeded that CV type's finite count"
        ),
        "claim_boundary": (
            "failed confirmation; no paper or formal experiment claim"
        ),
    }
    write_json(OUT / "decision.json", decision)
    source_paths = (
        PREREGISTRATION,
        PROTOTYPE / "pyvrp_adapter.py",
        PROTOTYPE / "epochal_hgs.py",
        PROTOTYPE / "staged_checkpoint_hgs_sp.py",
        CAMPAIGN / "run_staged_deepening_gate.py",
        CAMPAIGN / "run_staged_deepening_confirmation_gate.py",
        Path(__file__).resolve(),
    )
    write_json(
        OUT / "metadata.json",
        {
            "schema": (
                "resetp.staged-deepening-confirmation-incident."
                "metadata.v1"
            ),
            "sealed_at_utc": datetime.now(UTC).isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "source_hashes": {
                str(path.relative_to(REPO)): sha256(path)
                for path in source_paths
            },
        },
    )
    (OUT / "report.md").write_text(
        "# Staged deepening confirmation incident\n\n"
        "Decision: `HALT_STAGED_DEEPENING_CONFIRMATION_EXECUTION`.\n\n"
        "Five of six preregistered tasks completed and remain sealed. "
        "The remaining task, `cn-prd-200c-02-V2-LOCATIONS` seed 14, "
        "failed during stage-2 warm-start projection because more than "
        "12 routes were assigned to PyVRP vehicle type 4. Static review "
        "found that `_project_initial_solution` ignored each route's "
        "CV/EV type and always selected the depot CV type. The failed "
        "panel is not rerun, the incomplete acceptance gate is not "
        "evaluated, and none of these rows is formal evidence.\n\n"
        f"Among the five completed tasks, {strict_improvements} improved "
        "over protected stage 1, "
        f"{fusion_wins} strictly improved over the best current "
        f"single view, and {curve_passes} met the trajectory gate. These "
        "partial counts cannot pass the confirmation.\n",
        encoding="utf-8",
    )
    artifacts = {
        str(path.relative_to(OUT)): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": artifacts,
        },
    )
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
