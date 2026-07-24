#!/usr/bin/env python3
"""Formal corrected China81 rerun for the frozen staged portfolio.

The runner keeps the prior corrected China81 authorities and independent
full-model checks, but replaces the historical 5,000-iteration/80-check
algorithm with the separately preregistered two-stage portfolio that passed
the fresh seed-18 confirmation.  It is resumable at the (instance, seed)
task level and never prints objective values before the full batch closes.
"""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import os
import platform
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
CAMPAIGN_ROOT = REPO / "baselines/e2_final_campaign_20260720"
PROTOTYPE = (
    REPO
    / "baselines/algorithm_prototypes/"
    "china81_mechanism_hybrid_20260720"
)
CAMPAIGN_NAME = os.environ.get(
    "RESET_D6_CAMPAIGN_NAME",
    "corrected_china81_rerun_v5_staged_portfolio_20260724",
)
if not CAMPAIGN_NAME.startswith("corrected_china81_rerun_"):
    raise RuntimeError(f"invalid campaign name: {CAMPAIGN_NAME!r}")
os.environ["RESET_D6_CAMPAIGN_NAME"] = CAMPAIGN_NAME
for path in (CAMPAIGN_ROOT, REPO / "solver/src", PROTOTYPE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_corrected_china81_d6 as corrected_base  # noqa: E402
import scipy  # noqa: E402
from staged_checkpoint_hgs_sp import (  # noqa: E402
    VIEW_ORDER,
    run_staged_checkpoint_hgs_sp,
)
from setp_solver.china81 import load_china81_bundle  # noqa: E402
from setp_solver.china81_completion import (  # noqa: E402
    annotate_cross_site_services,
    complete_china81_route_skeleton,
    exact_china81_score,
)
from setp_solver.solution import Solution  # noqa: E402


OUT = CAMPAIGN_ROOT / CAMPAIGN_NAME / "full_gate"
PREREGISTRATION = (
    CAMPAIGN_ROOT
    / CAMPAIGN_NAME
    / "formal_preregistration_v2.json"
)
STOP_RECORD = (
    CAMPAIGN_ROOT
    / "algorithm_repair_diagnostic_20260724/"
    "STOP_ROUTE_FUSION_SUPERADDITIVITY_20260724.json"
)
CONFIRMATION_DECISION = (
    CAMPAIGN_ROOT
    / "algorithm_repair_diagnostic_20260724/"
    "multiview_portfolio_confirmation/decision.json"
)
SEEDS = (1, 2, 3, 4, 5)
ARM_BY_VIEW = {
    "cv_only": "HGS-F",
    "naive_ev": "HGS-E",
    "mechanism_ev": "HGS-M",
}
STAGE_1_ITERATIONS = 5_000
STAGE_2_ITERATIONS = 20_000
TOTAL_ITERATIONS_PER_VIEW = 25_000
MIP_SECONDS_PER_STAGE = 30.0
COMPLETE_CANDIDATE_BUDGET = 280
HISTORICAL_SNAPSHOTS_PER_STAGE = 20
EXPECTED_TOTAL_HISTORICAL_SNAPSHOTS = 120
EPS = 1.0e-9
REQUIRED_THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}


def _source_paths() -> tuple[Path, ...]:
    return (
        PREREGISTRATION,
        STOP_RECORD,
        CONFIRMATION_DECISION,
        PROTOTYPE / "pyvrp_adapter.py",
        PROTOTYPE / "epochal_hgs.py",
        PROTOTYPE / "route_pool_sp.py",
        PROTOTYPE / "staged_checkpoint_hgs_sp.py",
        CAMPAIGN_ROOT / "run_corrected_china81_d6.py",
        Path(__file__).resolve(),
        REPO / "solver/src/setp_solver/china81.py",
        REPO / "solver/src/setp_solver/china81_completion.py",
        REPO / "solver/src/setp_solver/prices.py",
        REPO / "solver/src/setp_solver/charging_curve.py",
        REPO / "solver/src/setp_solver/cost.py",
        REPO / "solver/src/setp_solver/check.py",
    )


def _source_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(REPO)): corrected_base.file_sha256(path)
        for path in _source_paths()
    }


def _task_id(instance_id: str, seed: int) -> str:
    return f"D6-E2-STAGED__{instance_id}__seed{seed}"


def _read_single_csv(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1:
        raise RuntimeError(f"expected one row in {path}, found {len(rows)}")
    return rows[0]


def _validate_completed_task(task_dir: Path) -> dict[str, Any]:
    decision_path = task_dir / "decision.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    if decision.get("verdict") != "PASS_D6_E2_STAGED_PORTFOLIO_TASK":
        raise RuntimeError(f"existing task is not PASS: {task_dir.name}")
    manifest = json.loads(
        (task_dir / "artifact_hashes.json").read_text(encoding="utf-8")
    )
    for relative, expected in manifest["artifacts"].items():
        artifact = task_dir / relative
        if (
            not artifact.is_file()
            or corrected_base.file_sha256(artifact) != expected
        ):
            raise RuntimeError(f"completed task hash mismatch: {artifact}")
    metadata = json.loads(
        (task_dir / "metadata.json").read_text(encoding="utf-8")
    )
    if metadata.get("preregistration_sha256") != (
        corrected_base.file_sha256(PREREGISTRATION)
    ):
        raise RuntimeError(
            f"completed task preregistration mismatch: {task_dir.name}"
        )
    if metadata.get("source_hashes") != _source_hashes():
        raise RuntimeError(
            f"completed task source mismatch: {task_dir.name}"
        )
    csv_row = _read_single_csv(task_dir / "raw_runs.csv")
    raw_row = dict(decision["raw_row"])
    normalized = {
        key: "" if value is None else str(value)
        for key, value in raw_row.items()
    }
    if normalized != csv_row:
        raise RuntimeError(
            f"completed task decision/CSV mismatch: {task_dir.name}"
        )
    return raw_row


def _passed_observations(
    epoch: Any,
    *,
    offset: float,
    phase: str,
    view: str,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for item in epoch.stats["exact_checkpoint_observations"]:
        if (
            item["status"] != "PASS"
            or item["complete_objective"] is None
        ):
            continue
        observations.append(
            {
                "elapsed_seconds": (
                    offset + float(item["elapsed_seconds"])
                ),
                "objective": float(item["complete_objective"]),
                "phase": phase,
                "view": view,
                "source": "online_complete_checkpoint",
            }
        )
    return observations


def _strict_curve_counts(
    initial_cost: float,
    observations: list[dict[str, Any]],
    final_cost: float,
) -> tuple[int, int]:
    best = float(initial_cost)
    points = 1
    decreases = 0
    for item in sorted(
        observations,
        key=lambda row: float(row["elapsed_seconds"]),
    ):
        objective = float(item["objective"])
        if objective < best - EPS:
            best = objective
            points += 1
            decreases += 1
    if final_cost < best - EPS:
        points += 1
        decreases += 1
    elif final_cost > best + EPS:
        raise RuntimeError(
            f"final {final_cost} is worse than retained incumbent {best}"
        )
    return points, decreases


def _trajectory_payload(
    run: Any,
    *,
    initial_cost: float,
    view_costs: dict[str, float],
    final_cost: float,
) -> tuple[dict[str, Any], dict[str, tuple[int, int]]]:
    trajectories: dict[str, list[dict[str, Any]]] = {}
    counts: dict[str, tuple[int, int]] = {}
    for mode in VIEW_ORDER:
        stage_1, stage_2 = run.stages[mode]
        observations = [
            *_passed_observations(
                stage_1,
                offset=0.0,
                phase="stage_1",
                view=mode,
            ),
            *_passed_observations(
                stage_2,
                offset=float(stage_1.elapsed_seconds),
                phase="stage_2",
                view=mode,
            ),
        ]
        endpoint_time = (
            float(stage_1.elapsed_seconds)
            + float(stage_2.elapsed_seconds)
        )
        observations.append(
            {
                "elapsed_seconds": endpoint_time,
                "objective": float(view_costs[mode]),
                "phase": "final",
                "view": mode,
                "source": "returned_single_view_solution",
            }
        )
        trajectories[ARM_BY_VIEW[mode]] = observations
        counts[ARM_BY_VIEW[mode]] = _strict_curve_counts(
            initial_cost,
            observations,
            view_costs[mode],
        )

    main_observations: list[dict[str, Any]] = []
    offset = 0.0
    for mode in VIEW_ORDER:
        stage_1 = run.stages[mode][0]
        main_observations.extend(
            _passed_observations(
                stage_1,
                offset=offset,
                phase="stage_1",
                view=mode,
            )
        )
        offset += float(stage_1.elapsed_seconds)
    main_observations.append(
        {
            "elapsed_seconds": float(
                run.stats["base_phase_elapsed_seconds"]
            ),
            "objective": float(run.base_completion.objective),
            "phase": "stage_1_pool",
            "view": "all",
            "source": str(run.stats["base_source"]),
        }
    )
    offset = float(run.stats["base_phase_elapsed_seconds"])
    for mode in VIEW_ORDER:
        stage_2 = run.stages[mode][1]
        main_observations.extend(
            _passed_observations(
                stage_2,
                offset=offset,
                phase="stage_2",
                view=mode,
            )
        )
        offset += float(stage_2.elapsed_seconds)
    main_observations.append(
        {
            "elapsed_seconds": float(run.elapsed_seconds),
            "objective": float(final_cost),
            "phase": "final",
            "view": "all",
            "source": str(run.stats["selected_source"]),
        }
    )
    trajectories["MV-HGS-SP"] = main_observations
    counts["MV-HGS-SP"] = _strict_curve_counts(
        initial_cost,
        main_observations,
        final_cost,
    )
    return (
        {
            "schema": "resetp.d6-e2-staged-trajectories.v1",
            "initial_objective": float(initial_cost),
            "curves": trajectories,
            "definition": (
                "complete-model checkpoint observations in actual execution "
                "order; no interpolation, smoothing, or offline discarded "
                "candidate substitution"
            ),
        },
        counts,
    )


def _history_integrity(run: Any) -> dict[str, Any]:
    stages = [
        stage
        for stage_pair in run.stages.values()
        for stage in stage_pair
    ]
    snapshot_count = sum(
        int(stage.stats["historical_population_snapshot_count"])
        for stage in stages
    )
    reference_count = sum(
        int(stage.stats["historical_population_candidate_references"])
        for stage in stages
    )
    diversity_count = sum(
        int(stage.stats["archive_diversity_selected_count"])
        for stage in stages
    )
    quality_count = sum(
        int(stage.stats["archive_quality_selected_count"])
        for stage in stages
    )
    return {
        "enabled": all(
            bool(stage.stats["historical_population_archive_enabled"])
            for stage in stages
        ),
        "snapshot_count": snapshot_count,
        "reference_count": reference_count,
        "diversity_selected_count": diversity_count,
        "quality_selected_count": quality_count,
        "snapshot_gate": all(
            int(stage.stats["historical_population_snapshot_count"])
            == HISTORICAL_SNAPSHOTS_PER_STAGE
            for stage in stages
        ),
        "archive_use_gate": all(
            int(
                stage.stats[
                    "historical_population_candidate_references"
                ]
            )
            > 0
            and int(stage.stats["archive_diversity_selected_count"]) > 0
            and int(stage.stats["archive_quality_selected_count"]) > 0
            for stage in stages
        ),
    }


def _run_unit(instance_id: str, seed: int) -> dict[str, Any]:
    task_id = _task_id(instance_id, seed)
    task_dir = OUT / "tasks" / task_id
    if (task_dir / "decision.json").is_file():
        return _validate_completed_task(task_dir)

    bundle = load_china81_bundle(REPO, instance_id)
    initial = corrected_base._load_initial(instance_id)
    initial_completion = complete_china81_route_skeleton(initial, bundle)
    customer_count = sum(
        node.node_type.lower() == "c"
        for node in bundle.instance.nodes
    )
    safety_seconds = max(900.0, 6.0 * customer_count)
    run = run_staged_checkpoint_hgs_sp(
        bundle,
        initial,
        seed=int(seed),
        stage_1_iterations=STAGE_1_ITERATIONS,
        stage_2_iterations=STAGE_2_ITERATIONS,
        mip_seconds_per_stage=MIP_SECONDS_PER_STAGE,
        collect_historical_population_archive=True,
        wallclock_safety_seconds_per_stage=safety_seconds,
    )
    if bool(run.stats["wallclock_safety_triggered"]):
        raise RuntimeError(f"HALT_SAFETY_WALLCLOCK:{task_id}")
    actual_attempts = int(
        run.stats["complete_candidate_evaluation_attempts"]
    )
    if (
        actual_attempts != COMPLETE_CANDIDATE_BUDGET
        or not bool(
            run.stats["complete_candidate_budget_exactly_consumed"]
        )
    ):
        raise RuntimeError(
            f"HALT_COMPLETE_BUDGET:{task_id}:{actual_attempts}"
        )
    if any(
        int(stage.stats["hgs_iterations"])
        not in {STAGE_1_ITERATIONS, STAGE_2_ITERATIONS}
        for stage_pair in run.stages.values()
        for stage in stage_pair
    ):
        raise RuntimeError(f"HALT_HGS_ITERATION_COUNT:{task_id}")
    if not all(
        bool(stage.stats["warm_route_type_preserved"])
        for stage_pair in run.stages.values()
        for stage in stage_pair
    ):
        raise RuntimeError(f"HALT_WARM_ROUTE_TYPE_DRIFT:{task_id}")
    history = _history_integrity(run)
    if (
        not history["enabled"]
        or not history["snapshot_gate"]
        or not history["archive_use_gate"]
        or history["snapshot_count"]
        != EXPECTED_TOTAL_HISTORICAL_SNAPSHOTS
    ):
        raise RuntimeError(f"HALT_HISTORY_ARCHIVE_LEDGER:{task_id}")

    solutions: dict[str, Solution] = {}
    costs: dict[str, float] = {}
    elapsed_by_arm: dict[str, float] = {}
    for mode in VIEW_ORDER:
        label = ARM_BY_VIEW[mode]
        completion = run.view_completions[mode]
        solutions[label] = annotate_cross_site_services(
            completion.solution,
            bundle.customer_home_depot,
        )
        costs[label] = float(completion.objective)
        stage_1, stage_2 = run.stages[mode]
        elapsed_by_arm[label] = (
            float(stage_1.elapsed_seconds)
            + float(stage_2.elapsed_seconds)
        )
    solutions["MV-HGS-SP"] = annotate_cross_site_services(
        run.solution,
        bundle.customer_home_depot,
    )
    costs["MV-HGS-SP"] = float(run.completion.objective)
    elapsed_by_arm["MV-HGS-SP"] = float(run.elapsed_seconds)

    breakdowns: dict[str, dict[str, float]] = {}
    for label, solution in solutions.items():
        corrected_base._require_same_day_charging(solution, bundle)
        corrected_base._require_depot_fleet_caps(solution, bundle)
        objective, breakdown, violations = exact_china81_score(
            solution,
            bundle,
        )
        if violations or abs(objective - costs[label]) > EPS:
            raise RuntimeError(
                f"HALT_D6_E2_RECHECK:{task_id}:{label}"
            )
        breakdowns[label] = breakdown
    if any(
        costs["MV-HGS-SP"] > costs[label] + EPS
        for label in ARM_BY_VIEW.values()
    ):
        raise RuntimeError(f"HALT_PORTFOLIO_LOST_OWN_VIEW:{task_id}")

    witnesses = {
        label: corrected_base._solution_payload(solution)
        for label, solution in solutions.items()
    }
    task_dir.mkdir(parents=True, exist_ok=True)
    witness_path = task_dir / "solution_witnesses.json"
    corrected_base.write_json(witness_path, witnesses)
    trajectory_payload, curve_counts = _trajectory_payload(
        run,
        initial_cost=float(initial_completion.objective),
        view_costs={
            mode: costs[ARM_BY_VIEW[mode]]
            for mode in VIEW_ORDER
        },
        final_cost=costs["MV-HGS-SP"],
    )
    trajectory_path = task_dir / "trajectory_observations.json"
    corrected_base.write_json(trajectory_path, trajectory_payload)

    base_mip = run.stats["base_route_pool_mip"]
    expanded_mip = run.stats["expanded_route_pool_mip"]
    best_single = min(costs[label] for label in ARM_BY_VIEW.values())
    raw_row = {
        "task_id": task_id,
        "instance_id": instance_id,
        "region": bundle.region,
        "tier": customer_count,
        "seed": int(seed),
        "HGS-F_cost": costs["HGS-F"],
        "HGS-F_cpu_seconds": elapsed_by_arm["HGS-F"],
        "HGS-E_cost": costs["HGS-E"],
        "HGS-E_cpu_seconds": elapsed_by_arm["HGS-E"],
        "HGS-M_cost": costs["HGS-M"],
        "HGS-M_cpu_seconds": elapsed_by_arm["HGS-M"],
        "MV-HGS-SP_cost": costs["MV-HGS-SP"],
        "MV-HGS-SP_cpu_seconds": elapsed_by_arm["MV-HGS-SP"],
        "HGS-F_emissions_kg": breakdowns["HGS-F"]["E_total"],
        "HGS-E_emissions_kg": breakdowns["HGS-E"]["E_total"],
        "HGS-M_emissions_kg": breakdowns["HGS-M"]["E_total"],
        "MV-HGS-SP_emissions_kg": (
            breakdowns["MV-HGS-SP"]["E_total"]
        ),
        "protected_stage_1_cost": float(
            run.base_completion.objective
        ),
        "improvement_over_protected_stage_1": (
            float(run.base_completion.objective)
            - costs["MV-HGS-SP"]
        ),
        "best_current_single_view_cost": best_single,
        "route_fusion_incremental_improvement": (
            best_single - costs["MV-HGS-SP"]
        ),
        "selected_source": str(run.stats["selected_source"]),
        "base_source": str(run.stats["base_source"]),
        "stage_1_iterations_per_view": STAGE_1_ITERATIONS,
        "stage_2_iterations_per_view": STAGE_2_ITERATIONS,
        "total_iterations_per_view": TOTAL_ITERATIONS_PER_VIEW,
        "complete_candidate_attempts": actual_attempts,
        "historical_population_snapshot_count": history[
            "snapshot_count"
        ],
        "historical_population_candidate_references": history[
            "reference_count"
        ],
        "historical_quality_selected_count": history[
            "quality_selected_count"
        ],
        "historical_diversity_selected_count": history[
            "diversity_selected_count"
        ],
        "base_route_pool_size": int(run.stats["base_route_pool_size"]),
        "expanded_route_pool_size": int(
            run.stats["expanded_route_pool_size"]
        ),
        "base_mip_status": base_mip["status_class"],
        "base_mip_incumbent_available": base_mip[
            "incumbent_available"
        ],
        "base_mip_objective": base_mip["objective"],
        "base_mip_dual_bound": base_mip["dual_bound"],
        "base_mip_gap": base_mip["mip_gap"],
        "expanded_mip_status": expanded_mip["status_class"],
        "expanded_mip_incumbent_available": expanded_mip[
            "incumbent_available"
        ],
        "expanded_mip_objective": expanded_mip["objective"],
        "expanded_mip_dual_bound": expanded_mip["dual_bound"],
        "expanded_mip_gap": expanded_mip["mip_gap"],
        "mip_time_limit_seconds_per_stage": MIP_SECONDS_PER_STAGE,
        "HGS-F_curve_points": curve_counts["HGS-F"][0],
        "HGS-F_strict_decreases": curve_counts["HGS-F"][1],
        "HGS-E_curve_points": curve_counts["HGS-E"][0],
        "HGS-E_strict_decreases": curve_counts["HGS-E"][1],
        "HGS-M_curve_points": curve_counts["HGS-M"][0],
        "HGS-M_strict_decreases": curve_counts["HGS-M"][1],
        "MV-HGS-SP_curve_points": curve_counts["MV-HGS-SP"][0],
        "MV-HGS-SP_strict_decreases": curve_counts[
            "MV-HGS-SP"
        ][1],
        "wallclock_safety_triggered": False,
        "all_charging_on_registered_date": True,
        "all_depot_charging_finishes_before_departure": True,
        "all_depot_fleet_caps_respected": True,
        "warm_route_types_preserved": True,
        "history_archive_ledger_complete": True,
        "all_independently_feasible": True,
        "witness_sha256": corrected_base.file_sha256(witness_path),
        "trajectory_sha256": corrected_base.file_sha256(
            trajectory_path
        ),
        "input_manifest_sha256": (
            corrected_base.payload_sha256(dict(bundle.source_paths))
        ),
        "responsibility_map_sha256": (
            corrected_base.payload_sha256(
                dict(bundle.customer_home_depot)
            )
        ),
        "status": "PASS",
    }
    corrected_base.write_csv(task_dir / "raw_runs.csv", [raw_row])
    corrected_base.write_json(
        task_dir / "metadata.json",
        {
            "schema": (
                "resetp.d6-e2-staged-portfolio-task.metadata.v1"
            ),
            "created_at_utc": datetime.now(UTC).isoformat(),
            "task_id": task_id,
            "campaign_name": CAMPAIGN_NAME,
            "python": sys.version,
            "platform": platform.platform(),
            "pyvrp_version": version("pyvrp"),
            "scipy_version": scipy.__version__,
            "preregistration_sha256": (
                corrected_base.file_sha256(PREREGISTRATION)
            ),
            "source_hashes": _source_hashes(),
            "thread_environment": {
                key: os.environ.get(key)
                for key in REQUIRED_THREAD_ENV
            },
        },
    )
    (task_dir / "report.md").write_text(
        f"# Staged portfolio task {task_id}\n\n"
        "The three single-view searches and the final multi-view portfolio "
        "used the frozen two-stage settings, corrected China81 authorities, "
        "finite fleet, common seed, common initial witness and complete "
        "evaluator. All four returned solutions passed the independent "
        "full-model checks. The main method uses more computation than one "
        "single view; no equal-compute claim is permitted.\n",
        encoding="utf-8",
    )
    corrected_base.write_json(
        task_dir / "decision.json",
        {
            "schema": (
                "resetp.d6-e2-staged-portfolio-task.decision.v1"
            ),
            "verdict": "PASS_D6_E2_STAGED_PORTFOLIO_TASK",
            "raw_row": raw_row,
        },
    )
    artifacts = {
        path.name: corrected_base.file_sha256(path)
        for path in sorted(task_dir.iterdir())
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    corrected_base.write_json(
        task_dir / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": artifacts,
        },
    )
    return raw_row


def _all_tasks() -> list[tuple[str, int]]:
    return [
        (instance_id, seed)
        for instance_id in corrected_base._instance_ids()
        for seed in SEEDS
    ]


def _completed_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for instance_id, seed in _all_tasks():
        task_dir = OUT / "tasks" / _task_id(instance_id, seed)
        if (task_dir / "decision.json").is_file():
            rows.append(_validate_completed_task(task_dir))
    return rows


def _write_progress(
    *,
    completed: int,
    running: int,
    status: str,
    last_task_id: str | None = None,
    failure: str | None = None,
) -> None:
    corrected_base.write_json(
        OUT / "progress.json",
        {
            "schema": "resetp.d6-e2-staged-progress.v1",
            "updated_at_utc": datetime.now(UTC).isoformat(),
            "campaign_name": CAMPAIGN_NAME,
            "expected_tasks": len(_all_tasks()),
            "completed_tasks": int(completed),
            "running_or_queued_tasks": int(running),
            "status": status,
            "last_task_id": last_task_id,
            "failure": failure,
        },
    )


def _finalize() -> dict[str, Any]:
    rows = _completed_rows()
    expected = len(_all_tasks())
    if len(rows) != expected:
        raise RuntimeError(
            f"formal rerun incomplete: expected {expected}, found {len(rows)}"
        )
    rows.sort(key=lambda row: (row["instance_id"], int(row["seed"])))
    if len({row["task_id"] for row in rows}) != expected:
        raise RuntimeError("duplicate formal task identifiers")
    if any(row["status"] != "PASS" for row in rows):
        raise RuntimeError("formal rerun contains non-PASS tasks")
    corrected_base.write_csv(OUT / "raw_runs.csv", rows)
    decision = {
        "schema": "resetp.d6-e2-staged-portfolio.decision.v1",
        "verdict": "PASS_D6_CORRECTED_CHINA81_E2_STAGED_RAW",
        "campaign_name": CAMPAIGN_NAME,
        "instance_count": len(corrected_base._instance_ids()),
        "seed_count": len(SEEDS),
        "task_count": len(rows),
        "returned_solution_count": len(rows) * 4,
        "full_model_feasible_solution_count": len(rows) * 4,
        "complete_candidate_attempts_per_task": (
            COMPLETE_CANDIDATE_BUDGET
        ),
        "total_iterations_per_view": TOTAL_ITERATIONS_PER_VIEW,
        "mip_time_limit_seconds_per_stage": MIP_SECONDS_PER_STAGE,
        "protected_historical_e2_artifacts_overwritten": False,
        "route_fusion_superadditivity_claim_allowed": False,
        "claim_boundary": (
            "multi-view best-incumbent portfolio with auxiliary checked "
            "time-limited MIP recombination; no equal-compute, stable "
            "route-fusion superadditivity, or universal optimality claim"
        ),
        "next_gate": (
            "independent replay of all 1,620 witnesses, followed by the "
            "result-blind strength gate"
        ),
    }
    corrected_base.write_json(OUT / "decision.json", decision)
    corrected_base.write_json(
        OUT / "metadata.json",
        {
            "schema": "resetp.d6-e2-staged-portfolio.metadata.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "campaign_name": CAMPAIGN_NAME,
            "preregistration_sha256": (
                corrected_base.file_sha256(PREREGISTRATION)
            ),
            "source_hashes": _source_hashes(),
            "thread_environment": REQUIRED_THREAD_ENV,
        },
    )
    (OUT / "report.md").write_text(
        "# Corrected China81 staged-portfolio E2 rerun\n\n"
        "All 81 instances x 5 seeds completed under the frozen staged "
        "portfolio and corrected China81 authorities. Each task returned "
        "four full-model-feasible witnesses, exact online trajectory "
        "observations, fixed search iterations, exactly 280 complete "
        "candidate checks and two disclosed 30-second MIP caps. This file "
        "does not report comparative outcomes; those remain sealed until "
        "the independent witness replay and preregistered strength gate.\n",
        encoding="utf-8",
    )
    artifacts = {
        str(path.relative_to(OUT)): corrected_base.file_sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name not in {
                "artifact_hashes.json",
                "progress.json",
                "done.json",
            }
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
            and ".pytest_cache" not in path.parts
        )
    }
    corrected_base.write_json(
        OUT / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "progress.json",
                "done.json",
                "._*",
                "__pycache__",
                ".pytest_cache",
                "*.tmp",
            ],
            "artifacts": artifacts,
        },
    )
    corrected_base.write_json(
        OUT / "done.json",
        {
            "schema": "resetp.d6-e2-staged-done.v1",
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "verdict": decision["verdict"],
            "task_count": expected,
            "decision_sha256": corrected_base.file_sha256(
                OUT / "decision.json"
            ),
            "raw_runs_sha256": corrected_base.file_sha256(
                OUT / "raw_runs.csv"
            ),
        },
    )
    _write_progress(
        completed=expected,
        running=0,
        status="COMPLETED",
    )
    return decision


def _run_all(workers: int) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    if not PREREGISTRATION.is_file():
        raise FileNotFoundError(PREREGISTRATION)
    if any(
        os.environ.get(key) != value
        for key, value in REQUIRED_THREAD_ENV.items()
    ):
        raise RuntimeError("single-thread environment is not fully locked")
    completed = len(_completed_rows())
    pending = [
        task
        for task in _all_tasks()
        if not (
            OUT / "tasks" / _task_id(*task) / "decision.json"
        ).is_file()
    ]
    _write_progress(
        completed=completed,
        running=len(pending),
        status="RUNNING",
    )
    if pending:
        context = mp.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
        ) as executor:
            futures = {
                executor.submit(_run_unit, instance_id, seed): (
                    instance_id,
                    seed,
                )
                for instance_id, seed in pending
            }
            try:
                for future in as_completed(futures):
                    instance_id, seed = futures[future]
                    row = future.result()
                    completed += 1
                    _write_progress(
                        completed=completed,
                        running=len(_all_tasks()) - completed,
                        status="RUNNING",
                        last_task_id=str(row["task_id"]),
                    )
                    print(
                        "[D6-E2-STAGED] "
                        f"{instance_id} seed={seed} PASS "
                        f"({completed}/{len(_all_tasks())})",
                        flush=True,
                    )
            except Exception as exc:
                for future in futures:
                    future.cancel()
                _write_progress(
                    completed=completed,
                    running=0,
                    status="HALT",
                    failure=f"{type(exc).__name__}: {exc}",
                )
                raise
    return _finalize()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--finalize-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        raise ValueError("workers must be positive")
    if args.finalize_only:
        decision = _finalize()
    else:
        decision = _run_all(args.workers)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
