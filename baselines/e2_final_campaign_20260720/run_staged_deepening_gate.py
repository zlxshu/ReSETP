#!/usr/bin/env python3
"""Result-blind gate for the two-stage deepened MV-HGS-SP candidate."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import multiprocessing
import os
import platform
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
for path in (REPO / "solver/src", PROTOTYPE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from staged_checkpoint_hgs_sp import (  # noqa: E402
    VIEW_ORDER,
    run_staged_checkpoint_hgs_sp,
)
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    complete_china81_route_skeleton,
    exact_china81_score,
)
from setp_solver.solution import Route, Solution  # noqa: E402


OUT = (
    REPO
    / "baselines/e2_final_campaign_20260720/"
    "algorithm_repair_diagnostic_20260724/"
    "staged_deepening_v2_gate"
)
PREREGISTRATION = (
    OUT.parent / "staged_deepening_v2_preregistration.json"
)
FLEET = (
    REPO
    / "data/ChinaInstances/"
    "china81_finite_fleet_authority_v1_20260723"
)
PANEL = (
    ("cn-cy-100c-01-V2-LOCATIONS", 13),
    ("cn-jjj-100c-01-V2-LOCATIONS", 13),
    ("cn-prd-100c-01-V2-LOCATIONS", 13),
    ("cn-cy-150c-01-V2-LOCATIONS", 13),
    ("cn-jjj-150c-01-V2-LOCATIONS", 13),
    ("cn-prd-150c-01-V2-LOCATIONS", 13),
)
ARM_BY_VIEW = {
    "cv_only": "HGS-F",
    "naive_ev": "HGS-E",
    "mechanism_ev": "HGS-M",
}
MAXIMUM_BUDGET = 280
MIP_SECONDS_PER_STAGE = 5.0
COLLECT_HISTORICAL_POPULATION_ARCHIVE = False
EPS = 1.0e-9


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def task_source_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(REPO)): sha256(path)
        for path in (
            PREREGISTRATION,
            PROTOTYPE / "epochal_hgs.py",
            PROTOTYPE / "route_pool_sp.py",
            PROTOTYPE / "staged_checkpoint_hgs_sp.py",
            Path(__file__).resolve(),
        )
    }


def validate_completed_task(task_dir: Path) -> dict[str, Any]:
    decision_path = task_dir / "decision.json"
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    if payload.get("verdict") != "PASS_STAGED_DEEPENING_V2_TASK":
        raise RuntimeError(
            f"existing task is not PASS: {task_dir.name}"
        )
    manifest = json.loads(
        (task_dir / "artifact_hashes.json").read_text(
            encoding="utf-8"
        )
    )
    for relative, expected in manifest["artifacts"].items():
        artifact = task_dir / relative
        if not artifact.is_file() or sha256(artifact) != expected:
            raise RuntimeError(
                f"completed task hash mismatch: {artifact}"
            )
    metadata = json.loads(
        (task_dir / "metadata.json").read_text(encoding="utf-8")
    )
    if metadata.get("preregistration_sha256") != sha256(
        PREREGISTRATION
    ):
        raise RuntimeError(
            f"completed task preregistration mismatch: {task_dir.name}"
        )
    if metadata.get("source_hashes") != task_source_hashes():
        raise RuntimeError(
            f"completed task source mismatch: {task_dir.name}"
        )
    rows = list(
        csv.DictReader(
            (task_dir / "raw_runs.csv").open(
                newline="",
                encoding="utf-8",
            )
        )
    )
    if len(rows) != 1:
        raise RuntimeError(
            f"completed task row count mismatch: {task_dir.name}"
        )
    raw_row = dict(payload["raw_row"])
    if {
        key: ("" if value is None else str(value))
        for key, value in raw_row.items()
    } != rows[0]:
        raise RuntimeError(
            f"completed task decision/CSV mismatch: {task_dir.name}"
        )
    return raw_row


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write empty CSV")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_initial(instance_id: str) -> Solution:
    payload = json.loads(
        (FLEET / "witnesses" / f"{instance_id}.json").read_text(
            encoding="utf-8"
        )
    )
    return Solution(
        routes=[
            Route(
                vehicle_id=str(route["vehicle_id"]),
                vehicle_type=str(route["vehicle_type"]),
                home_depot_id=str(route["home_depot_id"]),
                node_sequence=[
                    str(node) for node in route["node_sequence"]
                ],
            )
            for route in payload["routes"]
        ]
    )


def exact_cost(solution: Solution, bundle: Any) -> float:
    objective, _, violations = exact_china81_score(solution, bundle)
    if violations:
        raise RuntimeError(
            "independent exact check failed: "
            + "; ".join(str(item) for item in violations[:3])
        )
    return float(objective)


def running_curve_counts(
    initial_cost: float,
    observations: list[tuple[float, float]],
    final_cost: float,
) -> tuple[int, int]:
    best = float(initial_cost)
    points = 1
    decreases = 0
    for _, value in sorted(observations):
        if value < best - EPS:
            best = value
            points += 1
            decreases += 1
    if final_cost < best - EPS:
        points += 1
        decreases += 1
    elif final_cost > best + EPS:
        raise RuntimeError(
            f"final {final_cost} is worse than known incumbent {best}"
        )
    return points, decreases


def passed_observations(
    epoch: Any,
    *,
    offset: float,
) -> list[tuple[float, float]]:
    return [
        (
            offset + float(item["elapsed_seconds"]),
            float(item["complete_objective"]),
        )
        for item in epoch.stats["exact_checkpoint_observations"]
        if (
            item["status"] == "PASS"
            and item["complete_objective"] is not None
        )
    ]


def run_one(instance_id: str, seed: int) -> dict[str, Any]:
    task_id = f"{instance_id}__seed{seed}"
    task_dir = OUT / "tasks" / task_id
    task_decision = task_dir / "decision.json"
    if task_decision.is_file():
        return validate_completed_task(task_dir)
    bundle = load_china81_bundle(REPO, instance_id)
    initial = load_initial(instance_id)
    customer_count = sum(
        node.node_type.lower() == "c"
        for node in bundle.instance.nodes
    )
    safety_seconds = max(600.0, 6.0 * customer_count)
    initial_completion = complete_china81_route_skeleton(initial, bundle)
    run = run_staged_checkpoint_hgs_sp(
        bundle,
        initial,
        seed=seed,
        mip_seconds_per_stage=MIP_SECONDS_PER_STAGE,
        collect_historical_population_archive=(
            COLLECT_HISTORICAL_POPULATION_ARCHIVE
        ),
        wallclock_safety_seconds_per_stage=safety_seconds,
    )
    if run.stats["wallclock_safety_triggered"]:
        raise RuntimeError("wallclock safety cap triggered")
    actual_attempts = int(
        run.stats["complete_candidate_evaluation_attempts"]
    )
    if actual_attempts > MAXIMUM_BUDGET:
        raise RuntimeError("complete-evaluation budget cap exceeded")
    base_cost = exact_cost(run.base_completion.solution, bundle)
    final_cost = exact_cost(run.solution, bundle)
    if final_cost > base_cost + EPS:
        raise RuntimeError("protected stage-1 result was overwritten")
    view_costs = {
        mode: exact_cost(completion.solution, bundle)
        for mode, completion in run.view_completions.items()
    }
    best_current_single_view = min(view_costs.values())
    if any(final_cost > value + EPS for value in view_costs.values()):
        raise RuntimeError("main method lost to an own single view")
    warm_route_types_preserved = all(
        bool(stage.stats["warm_route_type_preserved"])
        for stage_pair in run.stages.values()
        for stage in stage_pair
    )
    if not warm_route_types_preserved:
        raise RuntimeError("warm-start vehicle route types changed")
    history_archive_enabled = all(
        bool(
            stage.stats[
                "historical_population_archive_enabled"
            ]
        )
        for stage_pair in run.stages.values()
        for stage in stage_pair
    )
    history_snapshot_count = sum(
        int(stage.stats["historical_population_snapshot_count"])
        for stage_pair in run.stages.values()
        for stage in stage_pair
    )
    history_reference_count = sum(
        int(
            stage.stats[
                "historical_population_candidate_references"
            ]
        )
        for stage_pair in run.stages.values()
        for stage in stage_pair
    )
    history_diversity_selected_count = sum(
        int(stage.stats["archive_diversity_selected_count"])
        for stage_pair in run.stages.values()
        for stage in stage_pair
    )
    history_stage_snapshot_gate = all(
        int(stage.stats["historical_population_snapshot_count"])
        == 20
        for stage_pair in run.stages.values()
        for stage in stage_pair
    )
    history_stage_archive_use_gate = all(
        int(
            stage.stats[
                "historical_population_candidate_references"
            ]
        )
        > 0
        and int(stage.stats["archive_diversity_selected_count"])
        > 0
        for stage_pair in run.stages.values()
        for stage in stage_pair
    )

    curve_by_view: dict[str, tuple[int, int]] = {}
    for mode in VIEW_ORDER:
        stage_1, stage_2 = run.stages[mode]
        observations = [
            *passed_observations(stage_1, offset=0.0),
            *passed_observations(
                stage_2,
                offset=float(stage_1.elapsed_seconds),
            ),
        ]
        curve_by_view[mode] = running_curve_counts(
            float(initial_completion.objective),
            observations,
            view_costs[mode],
        )

    main_observations: list[tuple[float, float]] = []
    offset = 0.0
    for mode in VIEW_ORDER:
        stage_1 = run.stages[mode][0]
        main_observations.extend(
            passed_observations(stage_1, offset=offset)
        )
        offset += float(stage_1.elapsed_seconds)
    main_observations.append((offset, base_cost))
    offset = float(run.stats["base_phase_elapsed_seconds"])
    for mode in VIEW_ORDER:
        stage_2 = run.stages[mode][1]
        main_observations.extend(
            passed_observations(stage_2, offset=offset)
        )
        offset += float(stage_2.elapsed_seconds)
    main_curve = running_curve_counts(
        float(initial_completion.objective),
        main_observations,
        final_cost,
    )
    e_win = final_cost < view_costs["naive_ev"] - EPS
    m_win = final_cost < view_costs["mechanism_ev"] - EPS
    row = {
        "instance_id": instance_id,
        "seed": seed,
        "customer_count": customer_count,
        "protected_stage_1_cost": base_cost,
        "candidate_final_cost": final_cost,
        "candidate_minus_stage_1": final_cost - base_cost,
        "strict_improvement_over_stage_1": (
            final_cost < base_cost - EPS
        ),
        "HGS-F_cost": view_costs["cv_only"],
        "HGS-E_cost": view_costs["naive_ev"],
        "HGS-M_cost": view_costs["mechanism_ev"],
        "best_current_single_view_cost": best_current_single_view,
        "candidate_minus_best_current_single_view": (
            final_cost - best_current_single_view
        ),
        "strict_route_fusion_improvement": (
            final_cost < best_current_single_view - EPS
        ),
        "strict_win_over_HGS-E": e_win,
        "strict_win_over_HGS-M": m_win,
        "zero_loss_to_all_views": True,
        "warm_route_types_preserved": warm_route_types_preserved,
        "historical_population_archive_enabled": (
            history_archive_enabled
        ),
        "historical_population_snapshot_count": (
            history_snapshot_count
        ),
        "historical_population_candidate_references": (
            history_reference_count
        ),
        "historical_diversity_selected_count": (
            history_diversity_selected_count
        ),
        "historical_stage_snapshot_gate": (
            history_stage_snapshot_gate
        ),
        "historical_stage_archive_use_gate": (
            history_stage_archive_use_gate
        ),
        "complete_candidate_attempts": actual_attempts,
        "base_route_pool_size": int(
            run.stats["base_route_pool_size"]
        ),
        "expanded_route_pool_size": int(
            run.stats["expanded_route_pool_size"]
        ),
        "selected_source": run.stats["selected_source"],
        "base_source": run.stats["base_source"],
        "base_mip_status": run.stats["base_route_pool_mip"][
            "status_class"
        ],
        "base_mip_dual_bound": run.stats["base_route_pool_mip"][
            "dual_bound"
        ],
        "base_mip_gap": run.stats["base_route_pool_mip"]["mip_gap"],
        "expanded_mip_status": run.stats["expanded_route_pool_mip"][
            "status_class"
        ],
        "expanded_mip_dual_bound": run.stats[
            "expanded_route_pool_mip"
        ]["dual_bound"],
        "expanded_mip_gap": run.stats["expanded_route_pool_mip"][
            "mip_gap"
        ],
        "elapsed_seconds": float(run.elapsed_seconds),
        "HGS-F_curve_points": curve_by_view["cv_only"][0],
        "HGS-F_strict_decreases": curve_by_view["cv_only"][1],
        "HGS-E_curve_points": curve_by_view["naive_ev"][0],
        "HGS-E_strict_decreases": curve_by_view["naive_ev"][1],
        "HGS-M_curve_points": curve_by_view["mechanism_ev"][0],
        "HGS-M_strict_decreases": curve_by_view["mechanism_ev"][1],
        "MV-HGS-SP_curve_points": main_curve[0],
        "MV-HGS-SP_strict_decreases": main_curve[1],
        "main_curve_gate": (
            main_curve[0] >= 12 and main_curve[1] >= 10
        ),
        "all_independently_feasible": True,
        "status": "PASS",
    }
    task_dir.mkdir(parents=True, exist_ok=True)
    write_csv(task_dir / "raw_runs.csv", [row])
    write_json(
        task_dir / "metadata.json",
        {
            "schema": "resetp.staged-deepening-v2-task.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "task_id": task_id,
            "preregistration_sha256": sha256(PREREGISTRATION),
            "source_hashes": task_source_hashes(),
        },
    )
    (task_dir / "report.md").write_text(
        "# Staged deepening v2 task\n\n"
        f"Instance `{instance_id}`, seed `{seed}` completed with "
        f"{actual_attempts} complete-candidate evaluations under the "
        f"registered cap of {MAXIMUM_BUDGET}.\n",
        encoding="utf-8",
    )
    task_artifacts = {
        path.name: sha256(path)
        for path in sorted(task_dir.iterdir())
        if (
            path.is_file()
            and path.name not in {
                "artifact_hashes.json",
                "decision.json",
            }
            and not path.name.startswith("._")
        )
    }
    write_json(
        task_dir / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "artifacts": task_artifacts,
        },
    )
    write_json(
        task_decision,
        {
            "schema": "resetp.staged-deepening-v2-task.decision.v1",
            "verdict": "PASS_STAGED_DEEPENING_V2_TASK",
            "raw_row": row,
        },
    )
    return row


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if not PREREGISTRATION.is_file():
        raise FileNotFoundError(PREREGISTRATION)
    workers = min(int(os.environ.get("RESET_WORKERS", "3")), len(PANEL))
    rows: list[dict[str, Any]] = []
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=context,
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
            rows.append(row)
            print(
                "[STAGED-DEEPENING-V2] "
                f"{instance_id} seed={seed} "
                f"delta={row['candidate_minus_stage_1']:.9f} "
                f"curve={row['MV-HGS-SP_curve_points']}/"
                f"{row['MV-HGS-SP_strict_decreases']} "
                f"elapsed={row['elapsed_seconds']:.1f}s",
                flush=True,
            )
    rows.sort(key=lambda row: (row["instance_id"], row["seed"]))
    write_csv(OUT / "raw_runs.csv", rows)
    strict_improvements = sum(
        bool(row["strict_improvement_over_stage_1"])
        for row in rows
    )
    wins_e = sum(bool(row["strict_win_over_HGS-E"]) for row in rows)
    wins_m = sum(bool(row["strict_win_over_HGS-M"]) for row in rows)
    curve_passes = sum(bool(row["main_curve_gate"]) for row in rows)
    invariant_pass = bool(
        len(rows) == 6
        and all(row["status"] == "PASS" for row in rows)
        and all(row["all_independently_feasible"] for row in rows)
        and all(row["zero_loss_to_all_views"] for row in rows)
        and all(
            row["complete_candidate_attempts"] <= MAXIMUM_BUDGET
            for row in rows
        )
        and all(
            row["candidate_minus_stage_1"] <= EPS for row in rows
        )
    )
    passed = bool(
        invariant_pass
        and strict_improvements >= 3
        and wins_e >= 3
        and wins_m >= 3
        and curve_passes >= 5
    )
    verdict = (
        "PASS_STAGED_DEEPENING_DEVELOPMENT_GATE"
        if passed
        else "HALT_STAGED_DEEPENING_DEVELOPMENT_GATE"
    )
    decision = {
        "schema": "resetp.staged-deepening-development.decision.v2",
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
        "main_curve_gate_passes": curve_passes,
        "required_main_curve_gate_passes": 5,
        "panel_size": len(rows),
        "preregistration_sha256": sha256(PREREGISTRATION),
        "claim_boundary": (
            "development only; no paper or formal experiment claim"
        ),
    }
    write_json(OUT / "decision.json", decision)
    write_json(
        OUT / "metadata.json",
        {
            "schema": (
                "resetp.staged-deepening-development.metadata.v2"
            ),
            "created_at_utc": datetime.now(UTC).isoformat(),
            "python": sys.version,
            "platform": platform.platform(),
            "workers": workers,
            "source_hashes": task_source_hashes(),
        },
    )
    (OUT / "report.md").write_text(
        "# Staged deepening development gate\n\n"
        f"Decision: `{verdict}`.\n\n"
        f"The fresh seed-13 panel produced {strict_improvements}/6 strict "
        "improvements over the protected 5000-iteration stage, "
        f"{wins_e}/6 strict wins over HGS-E, {wins_m}/6 strict wins over "
        f"HGS-M, and {curve_passes}/6 genuine main-method curves meeting "
        "the registered point/decrease gate. Every task remained feasible, "
        "never overwrote the protected stage-1 answer with a worse answer, "
        "and stayed at or below the registered cap of 280 complete "
        "evaluations; actual counts are retained in raw_runs.csv.\n",
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
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
