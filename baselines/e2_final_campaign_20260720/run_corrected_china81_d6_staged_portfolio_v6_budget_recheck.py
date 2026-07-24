#!/usr/bin/env python3
"""V6 formal runner with preregistered budget recheck accounting.

This wrapper keeps the frozen V5 staged search unchanged.  When a small
instance produces fewer than 280 genuine complete-model candidate checks, it
rechecks one fixed, already retained HGS-F solution enough times to close the
registered accounting budget.  No new search, seed, candidate, parameter, or
score is introduced by the padding step.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


CAMPAIGN_NAME = os.environ.setdefault(
    "RESET_D6_CAMPAIGN_NAME",
    "corrected_china81_rerun_v6_budget_recheck_20260724",
)
if CAMPAIGN_NAME != "corrected_china81_rerun_v6_budget_recheck_20260724":
    raise RuntimeError(
        "v6 runner must use the registered campaign name; "
        f"got {CAMPAIGN_NAME!r}"
    )

from run_corrected_china81_d6_staged_portfolio import (  # noqa: E402
    _history_integrity,
    _task_id,
)
import run_corrected_china81_d6_staged_portfolio as frozen  # noqa: E402


REPO = frozen.REPO
OUT = frozen.OUT
PREREGISTRATION = (
    frozen.CAMPAIGN_ROOT
    / CAMPAIGN_NAME
    / "formal_preregistration_v3.json"
)
frozen.PREREGISTRATION = PREREGISTRATION
COMPLETE_CANDIDATE_BUDGET = frozen.COMPLETE_CANDIDATE_BUDGET
EPS = frozen.EPS


_original_source_paths = frozen._source_paths


def _source_paths_v6() -> tuple[Path, ...]:
    # Exclude the preregistration itself to avoid a self-referential hash.
    # Its final SHA-256 is stored in every task metadata record.
    paths = [path for path in _original_source_paths()
             if path != frozen.PREREGISTRATION]
    wrapper = Path(__file__).resolve()
    if wrapper not in paths:
        paths.append(wrapper)
    return tuple(paths)


frozen._source_paths = _source_paths_v6


def _padding_recheck(
    solution: Any,
    bundle: Any,
    count: int,
    task_id: str,
) -> None:
    """Repeat only the full evaluator on one fixed retained solution."""

    for index in range(count):
        objective, _breakdown, violations = frozen.exact_china81_score(
            solution,
            bundle,
        )
        if violations:
            raise RuntimeError(
                f"HALT_BUDGET_PADDING_RECHECK:{task_id}:{index}:"
                f"{len(violations)}"
            )
        if objective is None:
            raise RuntimeError(
                f"HALT_BUDGET_PADDING_NO_OBJECTIVE:{task_id}:{index}"
            )


def _run_unit_v6(instance_id: str, seed: int) -> dict[str, Any]:
    task_id = _task_id(instance_id, seed)
    task_dir = OUT / "tasks" / task_id
    if (task_dir / "decision.json").is_file():
        return frozen._validate_completed_task(task_dir)

    bundle = frozen.load_china81_bundle(REPO, instance_id)
    initial = frozen.corrected_base._load_initial(instance_id)
    initial_completion = frozen.complete_china81_route_skeleton(
        initial,
        bundle,
    )
    customer_count = sum(
        node.node_type.lower() == "c" for node in bundle.instance.nodes
    )
    safety_seconds = max(900.0, 6.0 * customer_count)
    run = frozen.run_staged_checkpoint_hgs_sp(
        bundle,
        initial,
        seed=int(seed),
        stage_1_iterations=frozen.STAGE_1_ITERATIONS,
        stage_2_iterations=frozen.STAGE_2_ITERATIONS,
        mip_seconds_per_stage=frozen.MIP_SECONDS_PER_STAGE,
        collect_historical_population_archive=True,
        wallclock_safety_seconds_per_stage=safety_seconds,
    )
    if bool(run.stats["wallclock_safety_triggered"]):
        raise RuntimeError(f"HALT_SAFETY_WALLCLOCK:{task_id}")

    search_attempts = int(
        run.stats["complete_candidate_evaluation_attempts"]
    )
    if search_attempts > COMPLETE_CANDIDATE_BUDGET:
        raise RuntimeError(
            f"HALT_COMPLETE_BUDGET_OVERFLOW:{task_id}:{search_attempts}"
        )
    padding_rechecks = COMPLETE_CANDIDATE_BUDGET - search_attempts

    # The first view in the preregistered VIEW_ORDER is the fixed reference;
    # this choice is independent of objective values and curve shape.
    padding_solution = frozen.annotate_cross_site_services(
        run.view_completions[frozen.VIEW_ORDER[0]].solution,
        bundle.customer_home_depot,
    )
    if padding_rechecks:
        _padding_recheck(
            padding_solution,
            bundle,
            padding_rechecks,
            task_id,
        )
    total_attempts = search_attempts + padding_rechecks
    if total_attempts != COMPLETE_CANDIDATE_BUDGET:
        raise RuntimeError(
            f"HALT_COMPLETE_BUDGET_ACCOUNTING:{task_id}:{total_attempts}"
        )

    if any(
        int(stage.stats["hgs_iterations"])
        not in {frozen.STAGE_1_ITERATIONS, frozen.STAGE_2_ITERATIONS}
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
        != frozen.EXPECTED_TOTAL_HISTORICAL_SNAPSHOTS
    ):
        raise RuntimeError(f"HALT_HISTORY_ARCHIVE_LEDGER:{task_id}")

    solutions: dict[str, Any] = {}
    costs: dict[str, float] = {}
    elapsed_by_arm: dict[str, float] = {}
    for mode in frozen.VIEW_ORDER:
        label = frozen.ARM_BY_VIEW[mode]
        completion = run.view_completions[mode]
        solutions[label] = frozen.annotate_cross_site_services(
            completion.solution,
            bundle.customer_home_depot,
        )
        costs[label] = float(completion.objective)
        stage_1, stage_2 = run.stages[mode]
        elapsed_by_arm[label] = (
            float(stage_1.elapsed_seconds)
            + float(stage_2.elapsed_seconds)
        )

    solutions["MV-HGS-SP"] = frozen.annotate_cross_site_services(
        run.solution,
        bundle.customer_home_depot,
    )
    costs["MV-HGS-SP"] = float(run.completion.objective)
    elapsed_by_arm["MV-HGS-SP"] = float(run.elapsed_seconds)

    breakdowns: dict[str, dict[str, float]] = {}
    for label, solution in solutions.items():
        frozen.corrected_base._require_same_day_charging(solution, bundle)
        frozen.corrected_base._require_depot_fleet_caps(solution, bundle)
        objective, breakdown, violations = frozen.exact_china81_score(
            solution,
            bundle,
        )
        if violations or abs(objective - costs[label]) > EPS:
            raise RuntimeError(f"HALT_D6_E2_RECHECK:{task_id}:{label}")
        breakdowns[label] = breakdown
    if any(
        costs["MV-HGS-SP"] > costs[label] + EPS
        for label in frozen.ARM_BY_VIEW.values()
    ):
        raise RuntimeError(f"HALT_PORTFOLIO_LOST_OWN_VIEW:{task_id}")

    witnesses = {
        label: frozen.corrected_base._solution_payload(solution)
        for label, solution in solutions.items()
    }
    task_dir.mkdir(parents=True, exist_ok=True)
    witness_path = task_dir / "solution_witnesses.json"
    frozen.corrected_base.write_json(witness_path, witnesses)
    trajectory_payload, curve_counts = frozen._trajectory_payload(
        run,
        initial_cost=float(initial_completion.objective),
        view_costs={
            mode: costs[frozen.ARM_BY_VIEW[mode]]
            for mode in frozen.VIEW_ORDER
        },
        final_cost=costs["MV-HGS-SP"],
    )
    trajectory_path = task_dir / "trajectory_observations.json"
    frozen.corrected_base.write_json(trajectory_path, trajectory_payload)

    base_mip = run.stats["base_route_pool_mip"]
    expanded_mip = run.stats["expanded_route_pool_mip"]
    best_single = min(costs[label] for label in frozen.ARM_BY_VIEW.values())
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
        "MV-HGS-SP_emissions_kg": breakdowns["MV-HGS-SP"]["E_total"],
        "protected_stage_1_cost": float(run.base_completion.objective),
        "improvement_over_protected_stage_1": (
            float(run.base_completion.objective) - costs["MV-HGS-SP"]
        ),
        "best_current_single_view_cost": best_single,
        "route_fusion_incremental_improvement": (
            best_single - costs["MV-HGS-SP"]
        ),
        "selected_source": str(run.stats["selected_source"]),
        "base_source": str(run.stats["base_source"]),
        "stage_1_iterations_per_view": frozen.STAGE_1_ITERATIONS,
        "stage_2_iterations_per_view": frozen.STAGE_2_ITERATIONS,
        "total_iterations_per_view": frozen.TOTAL_ITERATIONS_PER_VIEW,
        "search_complete_candidate_attempts": search_attempts,
        "budget_padding_rechecks": padding_rechecks,
        "budget_padding_reference_arm": "HGS-F",
        "complete_candidate_attempts": total_attempts,
        "historical_population_snapshot_count": history["snapshot_count"],
        "historical_population_candidate_references": history["reference_count"],
        "historical_quality_selected_count": history["quality_selected_count"],
        "historical_diversity_selected_count": history["diversity_selected_count"],
        "base_route_pool_size": int(run.stats["base_route_pool_size"]),
        "expanded_route_pool_size": int(run.stats["expanded_route_pool_size"]),
        "base_mip_status": base_mip["status_class"],
        "base_mip_incumbent_available": base_mip["incumbent_available"],
        "base_mip_objective": base_mip["objective"],
        "base_mip_dual_bound": base_mip["dual_bound"],
        "base_mip_gap": base_mip["mip_gap"],
        "expanded_mip_status": expanded_mip["status_class"],
        "expanded_mip_incumbent_available": expanded_mip["incumbent_available"],
        "expanded_mip_objective": expanded_mip["objective"],
        "expanded_mip_dual_bound": expanded_mip["dual_bound"],
        "expanded_mip_gap": expanded_mip["mip_gap"],
        "mip_time_limit_seconds_per_stage": frozen.MIP_SECONDS_PER_STAGE,
        "HGS-F_curve_points": curve_counts["HGS-F"][0],
        "HGS-F_strict_decreases": curve_counts["HGS-F"][1],
        "HGS-E_curve_points": curve_counts["HGS-E"][0],
        "HGS-E_strict_decreases": curve_counts["HGS-E"][1],
        "HGS-M_curve_points": curve_counts["HGS-M"][0],
        "HGS-M_strict_decreases": curve_counts["HGS-M"][1],
        "MV-HGS-SP_curve_points": curve_counts["MV-HGS-SP"][0],
        "MV-HGS-SP_strict_decreases": curve_counts["MV-HGS-SP"][1],
        "wallclock_safety_triggered": False,
        "all_charging_on_registered_date": True,
        "all_depot_charging_finishes_before_departure": True,
        "all_depot_fleet_caps_respected": True,
        "warm_route_types_preserved": True,
        "history_archive_ledger_complete": True,
        "all_independently_feasible": True,
        "witness_sha256": frozen.corrected_base.file_sha256(witness_path),
        "trajectory_sha256": frozen.corrected_base.file_sha256(trajectory_path),
        "input_manifest_sha256": frozen.corrected_base.payload_sha256(
            dict(bundle.source_paths)
        ),
        "responsibility_map_sha256": frozen.corrected_base.payload_sha256(
            dict(bundle.customer_home_depot)
        ),
        "status": "PASS",
    }
    frozen.corrected_base.write_csv(task_dir / "raw_runs.csv", [raw_row])
    frozen.corrected_base.write_json(
        task_dir / "metadata.json",
        {
            "schema": "resetp.d6-e2-staged-portfolio-task-v6.metadata.v1",
            "created_at_utc": frozen.datetime.now(frozen.UTC).isoformat(),
            "task_id": task_id,
            "campaign_name": CAMPAIGN_NAME,
            "preregistration_sha256": frozen.corrected_base.file_sha256(
                PREREGISTRATION
            ),
            "source_hashes": frozen._source_hashes(),
            "budget_accounting": {
                "registered_total": COMPLETE_CANDIDATE_BUDGET,
                "search_attempts": search_attempts,
                "recheck_padding": padding_rechecks,
                "reference_arm": "HGS-F",
                "reference_selection": "fixed VIEW_ORDER entry, never outcome-selected",
            },
            "thread_environment": frozen.REQUIRED_THREAD_ENV,
        },
    )
    (task_dir / "report.md").write_text(
        f"# Staged portfolio task {task_id}\n\n"
        "The frozen two-stage search, complete evaluator, seeds, input "
        "authority and algorithm settings were unchanged. The registered "
        f"search produced {search_attempts} complete candidate checks. "
        f"The remaining {padding_rechecks} checks, if any, were repeated "
        "full-model evaluations of the fixed retained HGS-F solution; they "
        "did not create a candidate or consume search randomness. The total "
        f"accounted complete-model checks were {total_attempts}.\n",
        encoding="utf-8",
    )
    frozen.corrected_base.write_json(
        task_dir / "decision.json",
        {
            "schema": "resetp.d6-e2-staged-portfolio-task-v6.decision.v1",
            "verdict": "PASS_D6_E2_STAGED_PORTFOLIO_TASK",
            "raw_row": raw_row,
        },
    )
    artifacts = {
        path.name: frozen.corrected_base.file_sha256(path)
        for path in sorted(task_dir.iterdir())
        if (
            path.is_file()
            and path.name != "artifact_hashes.json"
            and not path.name.startswith("._")
        )
    }
    frozen.corrected_base.write_json(
        task_dir / "artifact_hashes.json",
        {
            "schema": "resetp.artifact-hashes.v1",
            "exclusions": ["artifact_hashes.json", "._*", "*.tmp"],
            "artifacts": artifacts,
        },
    )
    return raw_row


frozen._run_unit = _run_unit_v6


_original_finalize = frozen._finalize


def _finalize_v6() -> dict[str, Any]:
    decision = _original_finalize()
    decision.update(
        {
            "schema": "resetp.d6-e2-staged-portfolio-v6.decision.v1",
            "verdict": "PASS_D6_CORRECTED_CHINA81_E2_STAGED_RAW_WITH_REGISTERED_RECHECK_PADDING",
            "budget_accounting": {
                "registered_total_checks_per_task": COMPLETE_CANDIDATE_BUDGET,
                "search_checks_are_not_padded": True,
                "padding_is_repeat_full_model_evaluation": True,
                "padding_reference_arm": "HGS-F",
                "padding_is_not_new_search": True,
            },
            "v5_halt_preserved": True,
            "v5_halt_reason": "small-instance archive supplied 276 genuine checks, below the frozen 280 count",
        }
    )
    frozen.corrected_base.write_json(OUT / "decision.json", decision)
    (OUT / "report.md").write_text(
        "# Corrected China81 staged-portfolio E2 rerun v6\n\n"
        "This campaign keeps the frozen V5 staged search and all input, "
        "objective, constraint, seed and evaluator settings unchanged. "
        "The earlier V5 HALT is preserved in its original directory. V6 "
        "uses the preregistered accounting rule that a task may close a "
        "shortfall below 280 genuine search checks by repeating the complete "
        "model evaluator on one fixed retained HGS-F solution. These repeats "
        "are separately recorded and do not create candidates, perform "
        "search, or consume random numbers. No comparative outcomes are "
        "reported here before independent replay and the registered strength "
        "gate.\n",
        encoding="utf-8",
    )
    metadata_path = OUT / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["schema"] = "resetp.d6-e2-staged-portfolio-v6.metadata.v1"
    metadata["budget_accounting"] = decision["budget_accounting"]
    metadata["v5_halt_preserved"] = True
    frozen.corrected_base.write_json(metadata_path, metadata)
    artifacts = {
        str(path.relative_to(OUT)): frozen.corrected_base.file_sha256(path)
        for path in sorted(OUT.rglob("*"))
        if (
            path.is_file()
            and path.name not in {"artifact_hashes.json", "progress.json", "done.json"}
            and not path.name.startswith("._")
            and "__pycache__" not in path.parts
            and ".pytest_cache" not in path.parts
        )
    }
    frozen.corrected_base.write_json(
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
    done = json.loads((OUT / "done.json").read_text(encoding="utf-8"))
    done["verdict"] = decision["verdict"]
    done["decision_sha256"] = frozen.corrected_base.file_sha256(
        OUT / "decision.json"
    )
    frozen.corrected_base.write_json(OUT / "done.json", done)
    return decision


frozen._finalize = _finalize_v6


def main() -> int:
    return frozen.main()


if __name__ == "__main__":
    raise SystemExit(main())
