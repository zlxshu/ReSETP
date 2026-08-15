#!/opt/anaconda3/bin/python3.13
"""XA2: preregistered 200-customer component ablation for paper Section 4.3.

This runner reuses the already executed XA implementation without modifying
the preserved XA directory.  It changes only the fixed instance and task
manifest, then adds the required discriminability and solution-structure
checks for the 30-run ablation rerun.
"""

from __future__ import annotations

import argparse
import concurrent.futures.process as futures_process
import csv
import json
import multiprocessing as mp
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from baselines.china_e3_e7.formal_algorithm_20260802 import (  # noqa: E402
    run_xa_formal as base,
)


SCHEMA = "resetp.xa2-formal-ablation-200c.v1"
TASK_ID = "XA2"
INSTANCE_ID = "cn-prd-200c-01-V2-LOCATIONS"
SEEDS = tuple(range(2026080201, 2026080211))
EXPECTED_RUNS = 30
PRIOR_XA = REPO / "baselines/china_e3_e7/formal_algorithm_20260802"
PROTECTED_BOUNDARY_FILES = (
    REPO / "docs/paper_submission_final/RETIRED_paper_main.tex",
    REPO / "solver/src/setp_solver/check.py",
    REPO / "solver/src/setp_solver/search/evaluation.py",
)


def _configure_base() -> None:
    base.OUT = OUT
    base.INSTANCE_ID = INSTANCE_ID
    base.SCHEMA = SCHEMA
    base.SEEDS = SEEDS
    base.GROUP1_ARMS = ()
    base.GROUP2_ARMS = (
        ("MV_HGS_SP_FULL", "MV-HGS-SP", "mv_sp"),
        (
            "HGS_M_SP_NO_MULTIVIEW",
            "HGS-M-SP (-multi-view)",
            "single_sp",
        ),
        (
            "MV_HGS_NO_SP",
            "MV-HGS (-timed MIP route-pool recombination)",
            "mv_no_sp",
        ),
    )
    extra_fields = ("solution_structure_sha256", "search_trace_path")
    base.RAW_FIELDS = tuple(
        [*base.RAW_FIELDS, *[x for x in extra_fields if x not in base.RAW_FIELDS]]
    )


_configure_base()


def _task_specs() -> list[dict[str, Any]]:
    return base._task_specs()


def _tree_manifest_sha256(root: Path) -> str:
    rows: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if path.name.startswith("._"):
            continue
        if "__pycache__" in relative.parts or ".pytest_cache" in relative.parts:
            continue
        if any(part.startswith(".experiment-monitor") for part in relative.parts):
            continue
        rows.append(f"{relative}\t{base._sha256_path(path)}")
    return base._sha256_bytes(("\n".join(rows) + "\n").encode("utf-8"))


def _source_hashes(bundle: Any) -> dict[str, str]:
    paths = [
        path
        for path in base._source_paths(bundle)
        if not path.name.startswith("._") and "__pycache__" not in path.parts
    ]
    paths.append(Path(__file__).resolve())
    return {
        base._relative(path): base._sha256_path(path)
        for path in sorted({path.resolve() for path in paths})
    }


def _authority_certification() -> list[dict[str, str]]:
    path = base.FLEET_EVIDENCE / "raw_runs.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row["instance_id"] == INSTANCE_ID
        ]
    expected_levels = {"0", "25", "50", "75", "100"}
    actual_levels = {row["target_ev_percent"] for row in rows}
    if len(rows) != 5 or actual_levels != expected_levels:
        raise RuntimeError("authority v3 does not contain the five fixed levels")
    if any(row["status"] != "CERTIFIED" for row in rows):
        raise RuntimeError("authority v3 selected-instance certification failed")
    if any(int(row["violation_count"]) != 0 for row in rows):
        raise RuntimeError("authority v3 selected-instance violation is nonzero")
    if any(row["route_search_executed"].lower() != "false" for row in rows):
        raise RuntimeError("authority v3 certification unexpectedly ran search")
    return rows


def prepare() -> None:
    metadata_path = OUT / "metadata.json"
    if metadata_path.exists():
        raise FileExistsError("metadata already exists; preregistration is immutable")
    if not (PRIOR_XA / "done.json").is_file():
        raise RuntimeError("preserved XA predecessor is missing its completion marker")
    prior_decision = json.loads((PRIOR_XA / "decision.json").read_text(encoding="utf-8"))
    if prior_decision.get("status") != "XA_ALGORITHM_FORMAL_COMPLETE":
        raise RuntimeError("preserved XA predecessor is not complete")

    with base.model_config_scope(base.MODEL_CONFIG):
        bundle = base._bundle()
        common = base._common_initial(bundle)
        completion = base.complete_china81_route_skeleton(common, bundle)
        physicalized, certificate = base._physicalize_multitrip_solution(
            completion.solution,
            bundle,
        )
        objective, _, violations = base.exact_china81_score(physicalized, bundle)
    customer_count = sum(
        node.node_type.lower() == "c" for node in bundle.instance.nodes
    )
    if customer_count != 200:
        raise RuntimeError("selected instance does not have exactly 200 customers")
    if violations:
        raise RuntimeError("fixed common initial solution failed complete verification")
    if abs(float(bundle.prices.vehicle_fixed_cost) - 170.0) > 1e-9:
        raise RuntimeError("active fixed cost is not c_fix=170")
    if any(
        str(row.get("depot_charger_capacity_mode", "")).upper()
        not in {"", "UNBOUNDED"}
        for row in bundle.fleet_caps_by_depot.values()
    ):
        raise RuntimeError("fleet authority is not depot-unbounded")
    certification_rows = _authority_certification()

    initial_payload = {
        "solution": base._solution_dict(physicalized),
        "multitrip_certificate": certificate.as_dict(),
        "objective_cny": objective,
    }
    initial_solution_hash = base._sha256_bytes(
        base._json_bytes(initial_payload["solution"])
    )
    initial_skeleton_hash = base._solution_semantic_sha256(common)
    dirty = base._git("status", "--porcelain=v1")
    protected_boundary_hashes = {
        base._relative(path): base._sha256_path(path)
        for path in PROTECTED_BOUNDARY_FILES
    }
    falsification = {
        "broad_section_component_claim": (
            "If either deletion arm has a non-positive seed-paired mean cost "
            "difference relative to full MV-HGS-SP, this experiment does not "
            "support the broad claim that every tested component contributes."
        ),
        "multiview_contribution": (
            "If mean paired cost HGS-M-SP minus full MV-HGS-SP is non-positive, "
            "the experiment does not support a positive multi-view contribution."
        ),
        "timed_mip_route_pool_contribution": (
            "If mean paired cost MV-HGS minus full MV-HGS-SP is non-positive, "
            "the experiment does not support a positive timed-MIP route-pool "
            "recombination contribution."
        ),
        "all_tie_interpretation": (
            "If all 30 terminal objective values are identical, report exactly "
            "that the components produce no measurable difference at the "
            "largest currently available China81 scale; do not change the "
            "instance, seeds, iteration budget, evaluation budget, or stopping rule."
        ),
        "protocol_validity": (
            "Any source drift, missing task, substituted seed, budget excess, "
            "wall-clock safety trigger, missing full solution, solution hash "
            "mismatch, or protected-boundary drift causes technical HALT rather "
            "than a scientific claim."
        ),
        "immutability": (
            "This object is written before formal search and must not be changed."
        ),
    }
    metadata = {
        "schema_version": SCHEMA,
        "task_id": TASK_ID,
        "metadata_status": "PREREGISTERED_BEFORE_FORMAL_SEARCH",
        "preregistration_locked": True,
        "created_at_utc": base._utc_now(),
        "formal_search_started_at_metadata_creation": False,
        "git": {
            "commit": base._git("rev-parse", "HEAD"),
            "branch": base._git("branch", "--show-current"),
            "worktree_dirty": bool(dirty),
            "status_porcelain_sha256": base._sha256_bytes(
                dirty.encode("utf-8")
            ),
            "status_porcelain": dirty.splitlines(),
        },
        "source_sha256": _source_hashes(bundle),
        "protected_boundary_sha256": protected_boundary_hashes,
        "preserved_predecessor": {
            "path": base._relative(PRIOR_XA),
            "status": prior_decision["status"],
            "tree_manifest_sha256_before_xa2": _tree_manifest_sha256(PRIOR_XA),
            "preservation_rule": "read-only; no delete, move, edit, or overwrite",
            "prior_ablation_unique_objective": 3621.569907766804,
            "prior_ablation_terminal_runs": 30,
        },
        "selected_instance": {
            "instance_id": INSTANCE_ID,
            "customer_count": customer_count,
            "fixed_before_search": True,
            "only_instance_run": True,
            "selection_reason": (
                "Use the PRD family and canonical -01 formal replicate from "
                "the preserved 100-customer XA run while changing only the "
                "registered scale to China81's current maximum of 200 customers. "
                "The -01 suffix is fixed before search, so -02/-03 cannot be "
                "screened and selected after observing results. Authority v3 "
                "already provides five zero-search certified fleet witnesses."
            ),
            "rejected_posthoc_selection": (
                "No run is permitted on cn-prd-200c-02, cn-prd-200c-03, or any "
                "other instance in this task."
            ),
            "authority_v3_certification_rows": [
                {
                    "record_id": row["record_id"],
                    "target_ev_percent": int(row["target_ev_percent"]),
                    "status": row["status"],
                    "violation_count": int(row["violation_count"]),
                    "route_search_executed": False,
                }
                for row in certification_rows
            ],
            "active_depot_caps": {
                depot_id: dict(caps)
                for depot_id, caps in bundle.fleet_caps_by_depot.items()
            },
            "common_initial_solution_sha256": initial_solution_hash,
            "common_initial_route_skeleton_sha256": initial_skeleton_hash,
            "common_initial_route_skeleton_source": (
                "fleet authority v3 25-percent witness; route groups and order "
                "only, re-completed, physicalized, and checked by the shared "
                "evaluator before any formal search"
            ),
            "common_initial_objective_cny_preflight_only": objective,
            "common_initial_route_count": len(physicalized.routes),
            "common_initial_physical_vehicle_count": sum(
                certificate.vehicle_counts.values()
            ),
            "common_initial_violation_count": len(violations),
        },
        "shared_model_contract": {
            **base.MODEL_CONFIG.as_metadata(),
            "multi_trip": "ON_EXPLICIT",
            "fixed_cost_cny": 170.0,
            "fixed_cost_billing_basis": "distinct physical vehicle ids",
            "model_change_registration": "MC-W1-F2-DEPOT-CONCURRENCY-01",
            "depot_charging_concurrency": "UNBOUNDED",
            "public_station_concurrency": "INSTANCE_FINITE",
            "fleet_authority_version": "fleet_authority_v3_20260802",
            "fleet_authority_runtime_path": base._relative(base.FLEET_AUTHORITY),
            "fleet_authority_evidence_path": base._relative(base.FLEET_EVIDENCE),
            "china81_total_fleet_authority": 943,
            "selected_instance_total_fleet_cap": sum(
                int(caps["total_fleet_cap"])
                for caps in bundle.fleet_caps_by_depot.values()
            ),
            "superseded_rule_forbidden": "num_ev=max(1,ceil(0.25R_d))",
        },
        "shared_protocol": {
            "same_batch": True,
            "same_machine": True,
            "same_initial_solution_per_seed_and_arm": True,
            "same_seed_set": list(SEEDS),
            "maximum_hgs_iterations_total_per_run": base.MAX_HGS_ITERATIONS,
            "no_improvement_limit_per_active_hgs_population": (
                base.MAX_NO_IMPROVEMENT
            ),
            "stopping_rule": (
                "Each run stops at the first of 2000 total registered HGS "
                "iterations or 150 consecutive no-improvement iterations in "
                "each active population. Multi-view allocations are fixed at "
                "600/600/800 and sum to 2000. The 7200-second per-view guard is "
                "technical safety only; a trigger is HALT, never a result."
            ),
            "complete_search_evaluation_budget_max": (
                base.MAX_COMPLETE_SEARCH_EVALUATIONS
            ),
            "complete_evaluation_budget_is_identical": True,
            "budget_counting_rule": (
                "Count every common decoder invocation presented to search; "
                "post-search independent certification is recorded separately."
            ),
            "full_arm": {
                "implementation": "mv_sp",
                "iterations_by_view": base.MV_ITERATIONS,
                "maximum_complete_evaluations": 100,
            },
            "minus_multiview_arm": {
                "implementation": "single_sp",
                "active_view": "mechanism_ev",
                "iterations": 2000,
                "maximum_complete_evaluations": 100,
                "retained_components": [
                    "timed MIP route-pool recombination",
                    "shared complete evaluation",
                    "independent verification",
                ],
            },
            "minus_timed_mip_route_pool_arm": {
                "implementation": "mv_no_sp",
                "iterations_by_view": base.MV_ITERATIONS,
                "maximum_complete_evaluations": 100,
                "retained_components": [
                    "three-view generation",
                    "shared complete evaluation",
                    "independent verification",
                ],
            },
            "route_pool_mip_time_limit_seconds": base.SP_TIME_LIMIT_SECONDS,
            "maximum_parallel_workers": base.MAX_WORKERS,
            "adverse_results_policy": (
                "Retain all terminal runs; no rerun, seed replacement, rescue "
                "tuning, instance switching, budget increase, or result filtering."
            ),
        },
        "group_4_3": {
            "runs": EXPECTED_RUNS,
            "arms": [item[1] for item in base.GROUP2_ARMS],
            "one_factor_rule": (
                "Only multi-view generation or timed-MIP route-pool "
                "recombination is removed; every other registered setting is fixed."
            ),
            "table_fields": [
                "algorithm arm",
                "Best",
                "Avg",
                "stability Gap=100*(Avg-Best)/Best",
                "paired mean cost difference and percent from full arm",
                "CPU minutes",
                "feasible count",
            ],
        },
        "preregistered_falsification_criteria": falsification,
        "literature_protocol_sources": [
            "陈婉茹等 (2023), p.3331 Table 8: three-arm deletion ablation",
            "陈婉茹等 (2023), p.3328: 10 runs and 2000/150 stopping",
        ],
        "preflight_verification": {
            "selected_instance_complete_preflight_violation_count": 0,
            "selected_instance_customer_count": 200,
            "selected_instance_depot_count": len(bundle.fleet_caps_by_depot),
            "selected_instance_total_fleet_cap": sum(
                int(caps["total_fleet_cap"])
                for caps in bundle.fleet_caps_by_depot.values()
            ),
            "predecessor_runner_reused_without_edit": base._relative(
                Path(base.__file__).resolve()
            ),
        },
        "task_manifest": _task_specs(),
        "task_count": EXPECTED_RUNS,
        "hardware": base._hardware(),
    }
    base._write_json_new(metadata_path, metadata)
    base._write_json_new(
        OUT / "preflight_common_initial_solution.json", initial_payload
    )
    print(
        json.dumps(
            {
                "status": "PREREGISTERED",
                "task_id": TASK_ID,
                "instance_id": INSTANCE_ID,
                "metadata": str(metadata_path),
            },
            ensure_ascii=False,
        )
    )


def _run_unit(spec: dict[str, Any], expected_initial_hash: str) -> dict[str, Any]:
    _configure_base()
    result = base._run_unit(spec, expected_initial_hash)
    solution_path_text = str(result.get("solution_path", ""))
    if solution_path_text:
        solution_path = REPO / solution_path_text
        solution_bytes = solution_path.read_bytes()
        if base._sha256_bytes(solution_bytes) != result.get("solution_sha256"):
            raise RuntimeError("saved full-solution byte hash mismatch")
        payload = json.loads(solution_bytes)
        result["solution_structure_sha256"] = base._sha256_bytes(
            base._json_bytes(payload["solution"])
        )
    else:
        result["solution_structure_sha256"] = ""
    result_path = OUT / "units" / spec["task_id"] / "result.json"
    base._write_json_replace(result_path, result)
    return result


def _arm_rows(results: list[dict[str, Any]], arm_id: str) -> list[dict[str, Any]]:
    return [row for row in results if row["arm_id"] == arm_id]


def _stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": float(statistics.fmean(values)),
    }


def _pairwise_costs(
    results: list[dict[str, Any]],
    left_arm: str,
    right_arm: str,
) -> dict[str, Any]:
    left = {
        int(row["seed"]): float(row["objective_cny"])
        for row in _arm_rows(results, left_arm)
        if bool(row["feasible"])
    }
    right = {
        int(row["seed"]): float(row["objective_cny"])
        for row in _arm_rows(results, right_arm)
        if bool(row["feasible"])
    }
    seeds = sorted(set(left) & set(right))
    diffs = [left[seed] - right[seed] for seed in seeds]
    pcts = [100.0 * (left[seed] - right[seed]) / right[seed] for seed in seeds]
    return {
        "left_arm": left_arm,
        "right_arm": right_arm,
        "paired_seed_count": len(seeds),
        "mean_left_minus_right_cny": (
            float(statistics.fmean(diffs)) if diffs else None
        ),
        "mean_left_minus_right_percent": (
            float(statistics.fmean(pcts)) if pcts else None
        ),
        "left_lower_count": sum(diff < 0.0 for diff in diffs),
        "exact_tie_count": sum(diff == 0.0 for diff in diffs),
        "left_higher_count": sum(diff > 0.0 for diff in diffs),
        "nonzero_count": sum(diff != 0.0 for diff in diffs),
        "differences_cny_by_seed": {
            str(seed): left[seed] - right[seed] for seed in seeds
        },
    }


def _discriminability(results: list[dict[str, Any]]) -> dict[str, Any]:
    arm_ids = [item[0] for item in base.GROUP2_ARMS]
    feasible_rows = [row for row in results if bool(row["feasible"])]
    all_costs = [float(row["objective_cny"]) for row in feasible_rows]
    per_seed: dict[str, dict[str, Any]] = {}
    all_same_cost_seed_count = 0
    all_same_structure_seed_count = 0
    exact_same_iteration_seed_count = 0
    paired_iteration_spreads: list[float] = []
    for seed in SEEDS:
        rows = {
            row["arm_id"]: row
            for row in results
            if int(row["seed"]) == seed and row["arm_id"] in arm_ids
        }
        costs = [
            float(rows[arm]["objective_cny"])
            for arm in arm_ids
            if arm in rows and bool(rows[arm]["feasible"])
        ]
        hashes = [
            str(rows[arm].get("solution_structure_sha256", ""))
            for arm in arm_ids
            if arm in rows and rows[arm].get("solution_structure_sha256")
        ]
        iterations = [
            int(rows[arm]["hgs_iterations_actual"])
            for arm in arm_ids
            if arm in rows and rows[arm].get("hgs_iterations_actual") != ""
        ]
        same_cost = len(costs) == 3 and len(set(costs)) == 1
        same_structure = len(hashes) == 3 and len(set(hashes)) == 1
        same_iterations = len(iterations) == 3 and len(set(iterations)) == 1
        if same_cost:
            all_same_cost_seed_count += 1
        if same_structure:
            all_same_structure_seed_count += 1
        if same_iterations:
            exact_same_iteration_seed_count += 1
        if len(iterations) == 3:
            paired_iteration_spreads.append(float(max(iterations) - min(iterations)))
        per_seed[str(seed)] = {
            "three_arm_costs_identical": same_cost,
            "three_arm_solution_structures_bytewise_identical": same_structure,
            "three_arm_hgs_iterations_identical": same_iterations,
            "iteration_spread": (
                max(iterations) - min(iterations) if len(iterations) == 3 else None
            ),
        }
    pairs = {
        "minus_multiview_vs_full": _pairwise_costs(
            results, "HGS_M_SP_NO_MULTIVIEW", "MV_HGS_SP_FULL"
        ),
        "minus_timed_mip_route_pool_vs_full": _pairwise_costs(
            results, "MV_HGS_NO_SP", "MV_HGS_SP_FULL"
        ),
        "minus_multiview_vs_minus_timed_mip_route_pool": _pairwise_costs(
            results, "HGS_M_SP_NO_MULTIVIEW", "MV_HGS_NO_SP"
        ),
    }
    arm_process: dict[str, Any] = {}
    ranges: list[tuple[float, float]] = []
    for arm_id in arm_ids:
        rows = _arm_rows(results, arm_id)
        iteration_stats = _stats(
            [float(row["hgs_iterations_actual"]) for row in rows]
        )
        if iteration_stats["min"] is not None and iteration_stats["max"] is not None:
            ranges.append(
                (float(iteration_stats["min"]), float(iteration_stats["max"]))
            )
        arm_process[arm_id] = {
            "hgs_iterations": iteration_stats,
            "complete_search_evaluations": _stats(
                [float(row["complete_search_evaluations_actual"]) for row in rows]
            ),
            "cpu_minutes": _stats([float(row["cpu_minutes"]) for row in rows]),
            "feasible_runs": sum(bool(row["feasible"]) for row in rows),
            "terminal_runs": len(rows),
        }
    ranges_overlap = bool(
        len(ranges) == 3 and max(low for low, _ in ranges) <= min(high for _, high in ranges)
    )
    any_nonzero = any(pair["nonzero_count"] > 0 for pair in pairs.values())
    return {
        "question": "Do the three arms show any nonzero paired objective difference?",
        "answer": "YES" if any_nonzero else "NO",
        "any_nonzero_paired_cost_difference": any_nonzero,
        "feasible_objective_count": len(all_costs),
        "unique_feasible_objective_count": len(set(all_costs)),
        "all_30_objectives_identical": len(all_costs) == 30 and len(set(all_costs)) == 1,
        "three_arm_costs_identical_seed_count": all_same_cost_seed_count,
        "three_arm_solution_structures_bytewise_identical_seed_count": (
            all_same_structure_seed_count
        ),
        "three_arm_hgs_iterations_exactly_identical_seed_count": (
            exact_same_iteration_seed_count
        ),
        "arm_iteration_ranges_overlap": ranges_overlap,
        "paired_iteration_spread": _stats(paired_iteration_spreads),
        "pairwise_cost_checks": pairs,
        "arm_process_evidence": arm_process,
        "per_seed_checks": per_seed,
    }


def _verify_solution_artifacts(results: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for row in results:
        path_text = str(row.get("solution_path", ""))
        if not path_text:
            errors.append(f"{row['task_id']}: missing solution_path")
            continue
        path = REPO / path_text
        if not path.is_file():
            errors.append(f"{row['task_id']}: solution file missing")
            continue
        payload_bytes = path.read_bytes()
        if base._sha256_bytes(payload_bytes) != row.get("solution_sha256"):
            errors.append(f"{row['task_id']}: solution_sha256 mismatch")
            continue
        payload = json.loads(payload_bytes)
        structure_hash = base._sha256_bytes(base._json_bytes(payload["solution"]))
        if structure_hash != row.get("solution_structure_sha256"):
            errors.append(f"{row['task_id']}: solution structure hash mismatch")
    return errors


def _boundary_drift(metadata: dict[str, Any]) -> list[str]:
    drift: list[str] = []
    for relative, expected in metadata["protected_boundary_sha256"].items():
        path = REPO / relative
        actual = base._sha256_path(path) if path.is_file() else "MISSING"
        if actual != expected:
            drift.append(f"{relative}: expected={expected} actual={actual}")
    prior_expected = metadata["preserved_predecessor"][
        "tree_manifest_sha256_before_xa2"
    ]
    prior_actual = _tree_manifest_sha256(PRIOR_XA)
    if prior_actual != prior_expected:
        drift.append(
            "preserved formal_algorithm_20260802 tree changed: "
            f"expected={prior_expected} actual={prior_actual}"
        )
    return drift


def _artifact_hashes() -> None:
    artifacts: dict[str, str] = {}
    for path in sorted(OUT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(OUT)
        if path.name == "artifact_hashes.json" or path.name.startswith("._"):
            continue
        if "__pycache__" in relative.parts or ".pytest_cache" in relative.parts:
            continue
        if any(part.startswith(".experiment-monitor") for part in relative.parts):
            continue
        artifacts[str(relative)] = base._sha256_path(path)
    base._write_json_replace(
        OUT / "artifact_hashes.json",
        {
            "schema_version": "resetp.artifact-hashes.v1",
            "exclusions": [
                "artifact_hashes.json",
                "._*",
                "__pycache__",
                ".pytest_cache",
                ".experiment-monitor*",
            ],
            "artifacts": artifacts,
        },
    )


def _format_float(value: Any, digits: int = 6) -> str:
    if value is None:
        return "NA"
    return f"{float(value):.{digits}f}"


def _finalize(results: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    expected_ids = {item["task_id"] for item in _task_specs()}
    actual_ids = {row["task_id"] for row in results}
    missing = sorted(expected_ids - actual_ids)
    errors = [row for row in results if row["terminal_status"] == "ERROR"]
    halts = [
        row for row in results if str(row["terminal_status"]).startswith("HALT_")
    ]
    solution_errors = _verify_solution_artifacts(results)
    boundary_drift = _boundary_drift(metadata)
    complete = bool(
        len(results) == EXPECTED_RUNS
        and not missing
        and not errors
        and not halts
        and not solution_errors
        and not boundary_drift
    )
    _, table = base._summarise(results) if not missing else ([], [])
    if table:
        base._write_csv(
            OUT / "table_4_3_component_ablation.csv", list(table[0]), table
        )
    discriminability = _discriminability(results) if not missing else {}
    base._write_json_replace(
        OUT / "discriminability_check.json", discriminability
    )

    no_mv = (
        discriminability.get("pairwise_cost_checks", {})
        .get("minus_multiview_vs_full", {})
    )
    no_sp = (
        discriminability.get("pairwise_cost_checks", {})
        .get("minus_timed_mip_route_pool_vs_full", {})
    )
    multiview_supported = bool(
        no_mv.get("mean_left_minus_right_cny") is not None
        and no_mv["mean_left_minus_right_cny"] > 0.0
    )
    sp_supported = bool(
        no_sp.get("mean_left_minus_right_cny") is not None
        and no_sp["mean_left_minus_right_cny"] > 0.0
    )
    any_nonzero = bool(
        discriminability.get("any_nonzero_paired_cost_difference", False)
    )
    if complete and any_nonzero:
        scientific_verdict = "NONZERO_DIFFERENCES_OBSERVED"
        scientific_conclusion = (
            "The three arms show at least one nonzero paired objective difference; "
            "component claims are assessed separately by the preregistered paired means."
        )
    elif complete:
        scientific_verdict = "NO_MEASURABLE_DIFFERENCE_AT_CHINA81_MAX_SCALE"
        scientific_conclusion = (
            "在 China81 现有最大规模下，三部件不产生可测差异"
        )
    else:
        scientific_verdict = "TECHNICAL_INCOMPLETE_NO_SCIENTIFIC_CONCLUSION"
        scientific_conclusion = "Technical completion failed; no scientific conclusion."

    status = "XA2_ABLATION_COMPLETE" if complete else "HALT_XA2_ABLATION_INCOMPLETE"
    decision = {
        "schema_version": SCHEMA,
        "task_id": TASK_ID,
        "status": status,
        "technical_completion": complete,
        "terminal_run_count": len(results),
        "expected_run_count": EXPECTED_RUNS,
        "missing_task_ids": missing,
        "error_task_ids": [row["task_id"] for row in errors],
        "halt_task_ids": [row["task_id"] for row in halts],
        "solution_artifact_errors": solution_errors,
        "protected_boundary_drift": boundary_drift,
        "scientific_verdict": scientific_verdict,
        "scientific_conclusion": scientific_conclusion,
        "scientific_claim_assessment": {
            "multiview_contribution_supported": multiview_supported,
            "timed_mip_route_pool_contribution_supported": sp_supported,
            "broad_every_tested_component_contributes_supported": (
                multiview_supported and sp_supported
            ),
        },
        "discriminability_self_check": discriminability,
        "preregistration_falsification_criteria_sha256": base._sha256_bytes(
            base._json_bytes(metadata["preregistered_falsification_criteria"])
        ),
        "adverse_results_retained": True,
        "rerun_or_instance_switch_after_results": False,
        "created_at_utc": base._utc_now(),
    }
    base._write_json_replace(OUT / "decision.json", decision)

    lines = [
        "# XA2：200 客户组件消融重跑",
        "",
        f"状态：`{status}`。",
        "",
        "## 跑前固定口径",
        "",
        f"唯一算例为 `{INSTANCE_ID}`（200 客户、4 车场）。选择它是因为它与上一轮同属 PRD、同为 `-01` 正式重复项，只把规模提高到 China81 现有最大值；`-02/-03` 从未运行，因而不存在跑后挑题。上一轮 `formal_algorithm_20260802/` 原样保留，树清单哈希在跑前和跑后一致。",
        "",
        "三臂使用相同共同起点、种子 2026080201--2026080210、最多 2000 次 HGS 迭代、连续 150 次无改善停止、最多 100 次完整搜索评价和同一独立验解。严格多趟开启；固定成本按实体车数计费，c_fix=170 元；车场充电并发不设上限；fleet authority v3。",
        "",
        "跑前否定条件已锁定：任一删除臂相对完整臂的配对平均成本差不为正，则不支持该组件有正贡献；任一组件不获支持，则不支持“每个被检验组件都有贡献”的总主张；若 30 个目标值全同，直接报告最大规模仍无可测差异，不换题、不换种子、不加预算。",
        "",
        "## 判别力自检",
        "",
        f"三臂之间是否出现非零配对成本差：**{'是' if any_nonzero else '否'}**。",
        "",
        f"科学判定：`{scientific_verdict}`。{scientific_conclusion}。",
        "",
        "## 4.3 一因素组件消融",
        "",
    ]
    if table:
        lines.extend(
            [
                "|算法臂|Best/元|Avg/元|稳定性 Gap/%|相对完整臂配对成本差/元|配对差/%|CPU 均值/min|可行数|",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in table:
            lines.append(
                "|{}|{}|{}|{}|{}|{}|{}|{}/{}|".format(
                    row["algorithm_arm"],
                    _format_float(row["Best_cny"]),
                    _format_float(row["Avg_cny"]),
                    _format_float(row["stability_Gap_percent"]),
                    _format_float(row["paired_mean_cost_diff_vs_full_cny"]),
                    _format_float(row["paired_mean_cost_diff_vs_full_percent"]),
                    _format_float(row["CPU_minutes_mean"], 4),
                    row["feasible_runs"],
                    row["terminal_runs"],
                )
            )
    if complete:
        lines.extend(["", "## 配对方向", ""])
        for label, pair in discriminability["pairwise_cost_checks"].items():
            lines.append(
                f"- `{label}`：左臂更低/完全相同/左臂更高 = "
                f"{pair['left_lower_count']}/{pair['exact_tie_count']}/"
                f"{pair['left_higher_count']}；配对均值差 "
                f"{_format_float(pair['mean_left_minus_right_cny'])} 元（"
                f"{_format_float(pair['mean_left_minus_right_percent'])}%）。"
            )
    if complete and not any_nonzero:
        lines.extend(["", "## 全平支撑量", ""])
        for arm_id, evidence in discriminability["arm_process_evidence"].items():
            iteration = evidence["hgs_iterations"]
            evaluations = evidence["complete_search_evaluations"]
            cpu = evidence["cpu_minutes"]
            lines.append(
                f"- `{arm_id}`：迭代 {iteration['min']:.0f}--{iteration['max']:.0f}（均值 {iteration['mean']:.1f}）；完整评价 {evaluations['min']:.0f}--{evaluations['max']:.0f}（均值 {evaluations['mean']:.1f}）；CPU {cpu['min']:.4f}--{cpu['max']:.4f} min（均值 {cpu['mean']:.4f}）；可行 {evidence['feasible_runs']}/{evidence['terminal_runs']}。"
            )
        lines.extend(
            [
                "",
                f"三臂迭代区间是否重叠：{'是' if discriminability['arm_iteration_ranges_overlap'] else '否'}；逐种子三臂迭代数完全相同 {discriminability['three_arm_hgs_iterations_exactly_identical_seed_count']}/10；逐种子迭代跨度为 {_format_float(discriminability['paired_iteration_spread']['min'], 0)}--{_format_float(discriminability['paired_iteration_spread']['max'], 0)}。",
                "",
                f"逐种子三臂完整解结构按规范 JSON 逐位相同 {discriminability['three_arm_solution_structures_bytewise_identical_seed_count']}/10；完整的逐种子结构哈希见 `discriminability_check.json` 与 `raw_runs.csv`。",
            ]
        )
    lines.extend(
        [
            "",
            "## 验证与证据",
            "",
            f"30 次终态全部保存完整解并登记 `solution_sha256` 与 `solution_structure_sha256`；解文件复算哈希错误 {len(solution_errors)}，受保护边界漂移 {len(boundary_drift)}。逐次数据见 `raw_runs.csv`，完整解与搜索轨迹见 `units/`，判别力逐种子明细见 `discriminability_check.json`。",
        ]
    )
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _artifact_hashes()
    base._write_json_replace(
        OUT / "done.json",
        {
            "status": status,
            "terminal_run_count": len(results),
            "scientific_verdict": scientific_verdict,
            "completed_at_utc": base._utc_now(),
        },
    )


def run() -> None:
    _configure_base()
    metadata = base._verify_frozen_metadata()
    if metadata.get("task_id") != TASK_ID:
        raise RuntimeError("metadata task id is not XA2")
    if (OUT / "done.json").exists():
        raise FileExistsError("formal experiment already has terminal done.json")
    expected_hash = metadata["selected_instance"]["common_initial_solution_sha256"]
    completed = {row["task_id"] for row in base._all_results()}
    pending = [spec for spec in _task_specs() if spec["task_id"] not in completed]
    base._materialize_raw()
    try:
        os.sysconf("SC_SEM_NSEMS_MAX")
    except PermissionError:
        futures_process._check_system_limits = lambda: None
    context = mp.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=base.MAX_WORKERS,
        mp_context=context,
    ) as pool:
        futures = {
            pool.submit(_run_unit, spec, expected_hash): spec for spec in pending
        }
        for future in as_completed(futures):
            spec = futures[future]
            try:
                result = future.result()
                print(
                    json.dumps(
                        {
                            "task_id": spec["task_id"],
                            "terminal_status": result["terminal_status"],
                            "objective_cny": result.get("objective_cny"),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except BaseException as exc:
                print(
                    json.dumps(
                        {
                            "task_id": spec["task_id"],
                            "executor_error": type(exc).__name__,
                            "message": str(exc),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            base._materialize_raw()
    results = base._materialize_raw()
    _finalize(results, metadata)
    print((OUT / "done.json").read_text(encoding="utf-8"), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "run"))
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    else:
        run()


if __name__ == "__main__":
    main()
