"""Run the one-shot old-three-instance strength gate for the bounded archive."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
from statistics import median
import subprocess
import sys
import time
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LEGACY = (
    REPO
    / "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718"
)
for path in (
    REPO / "solver/src",
    REPO / "models/src",
    HERE,
    LEGACY,
    REPO,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import bounded_dual_view_archive_solver as solver  # noqa: E402
import run_bounded_dual_view_archive_behavior_gate as behaviour  # noqa: E402
from initial_pool import solution_signature_hash  # noqa: E402
from prototype import independent_cost  # noqa: E402
from setp_solver.algorithms.resetp_alns.support.construction import (  # noqa: E402
    build_initial_solution,
)
from setp_solver.check import check_solution  # noqa: E402
from setp_solver.prices import DEFAULT_PRICES  # noqa: E402
from setp_solver.profit import infer_customer_home_depots  # noqa: E402
from setp_solver.search.bundle import load_search_bundle  # noqa: E402
from setp_solver.solution import (  # noqa: E402
    ChargingAction,
    CrossSiteService,
    Route,
    Solution,
)
from v7_responsibility_solver import (  # noqa: E402
    annotate_cross_site_services,
)


ARCHIVE = (
    REPO
    / "models/data_bundle/generated_instances/"
    "L-main_size_preserving_v2_archive_20260710"
)
INSTANCES = (
    "L-main-threeshift-20c-01",
    "L-main-threeshift-25c-01",
    "L-main-threeshift-50c-01",
)
ARMS = ("control", "candidate")
SEED = 1
BUDGET = 100
PRICES = replace(DEFAULT_PRICES, B_battery_kwh=280.0)
TOL = 1.0e-9
BEHAVIOUR_DIR = HERE / "bounded_dual_view_archive_behavior_gate"
WORKER_SENTINEL = "RESET_BOUNDED_ARCHIVE_P1_WORKER="
OUTPUT_FILES = (
    "metadata.json",
    "raw_runs.csv",
    "comparisons.json",
    "decision.json",
    "archive_candidates.json",
    "solution_witnesses.json",
    "report.md",
)
PROTECTED_FILES = (
    "solver/src/setp_solver/cost.py",
    "solver/src/setp_solver/check.py",
    "solver/src/setp_solver/search/evaluation.py",
)
SOURCE_FILES = (
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "run_bounded_dual_view_archive_p1_training_gate.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "bounded_dual_view_archive_solver.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "run_bounded_dual_view_archive_behavior_gate.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "test_bounded_dual_view_archive_solver.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "fast_mechanism_completion.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "terminal_completion.py",
    "baselines/algorithm_prototypes/unified_mechanism_alns_20260719/"
    "initial_pool.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/"
    "prototype.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/"
    "v4_mechanism_alns_solver.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/"
    "v5_carbon_retiming_solver.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/"
    "v6_monotone_mechanism_solver.py",
    "baselines/algorithm_prototypes/mechanism_hgs_alns_20260718/"
    "v7_responsibility_solver.py",
    "solver/src/setp_solver/algorithms/resetp_alns/kernel/winner.py",
    "solver/src/setp_solver/algorithms/resetp_alns/support/"
    "construction.py",
    "solver/src/setp_solver/algorithms/resetp_alns/runtime/"
    "budgeted_scoring.py",
    "solver/src/setp_solver/search/e3_multitrip_runtime.py",
    "docs/handoff/bounded_dual_view_archive_contract_20260719.md",
)
FIXED_ENVIRONMENT = {
    "PYTHONHASHSEED": "0",
    "SETP_E3_STRICT_MULTITRIP": "0",
    "SETP_ALNS_CRUSH_TRACE_DIAGNOSTIC": "0",
    "SETP_E2_ALNS_CHECKPOINT_PATH": "",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=HERE / "bounded_dual_view_archive_p1_training_gate",
    )
    parser.add_argument(
        "--worker",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    _freeze_environment()
    if args.worker:
        return _worker_main()

    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"P1 output directory exists: {output_dir}")
    behaviour_preflight = _verify_behaviour_gate()
    _require_clean_sources()
    source_hashes_before = {
        path: _sha256(REPO / path) for path in SOURCE_FILES
    }
    protected_hashes_before = {
        path: _sha256(REPO / path) for path in PROTECTED_FILES
    }
    input_hashes_before = _input_hashes(
        tuple(ARCHIVE / instance for instance in INSTANCES)
    )
    shared_starts = {
        instance: _shared_start(ARCHIVE / instance)
        for instance in INSTANCES
    }
    run_order = sorted(
        (
            (instance, arm)
            for instance in INSTANCES
            for arm in ARMS
        ),
        key=lambda item: _sha_text(
            f"{item[0]}:{item[1]}:seed={SEED}:B={BUDGET}:bounded"
        ),
    )
    started = time.perf_counter()
    payloads: dict[tuple[str, str], dict[str, Any]] = {}
    for instance, arm in run_order:
        payloads[(instance, arm)] = _invoke_worker(
            {
                "bundle": str((ARCHIVE / instance).resolve()),
                "instance": instance,
                "arm": arm,
                "shared_start": asdict(shared_starts[instance]),
            }
        )

    rows: list[dict[str, Any]] = []
    witnesses: dict[str, Any] = {}
    archive_candidates: dict[str, Any] = {}
    for instance in INSTANCES:
        _add_witness(
            witnesses,
            shared_starts[instance],
            {
                "kind": "shared_start",
                "instance": instance,
                "used_by": list(ARMS),
            },
        )
        for arm in ARMS:
            payload = payloads[(instance, arm)]
            parent_audit = behaviour._parent_archive_audit(
                ARCHIVE / instance,
                payload,
            )
            row, final = _normalize_payload(
                ARCHIVE / instance,
                payload,
                parent_audit=parent_audit,
            )
            rows.append(row)
            _add_witness(
                witnesses,
                final,
                {
                    "kind": "final",
                    "instance": instance,
                    "arm": arm,
                },
            )
            activity = dict(payload["activity"])
            archive_candidates[f"{instance}:{arm}"] = {
                "prescore_rows": activity.get("prescore_rows", []),
                "archive_entries": activity.get("archive_entries", []),
                "parent_audit": parent_audit,
            }
            for index, entry in enumerate(
                activity.get("archive_entries", [])
            ):
                _add_witness(
                    witnesses,
                    _solution_from_payload(
                        entry["raw_solution_snapshot"]
                    ),
                    {
                        "kind": "archive_raw",
                        "instance": instance,
                        "arm": arm,
                        "entry_index": index,
                    },
                )
            for index, entry in enumerate(
                activity.get("prescore_rows", [])
            ):
                _add_witness(
                    witnesses,
                    _solution_from_payload(
                        entry["raw_solution_snapshot"]
                    ),
                    {
                        "kind": "prescore_raw",
                        "instance": instance,
                        "arm": arm,
                        "entry_index": index,
                    },
                )
                _add_witness(
                    witnesses,
                    _solution_from_payload(
                        entry["fast_completed_solution_snapshot"]
                    ),
                    {
                        "kind": "prescore_fast_completed",
                        "instance": instance,
                        "arm": arm,
                        "entry_index": index,
                    },
                )
                _add_witness(
                    witnesses,
                    _solution_from_payload(
                        entry["completed_solution_snapshot"]
                    ),
                    {
                        "kind": "archive_completed",
                        "instance": instance,
                        "arm": arm,
                        "entry_index": index,
                    },
                )

    comparisons = _comparisons(rows)
    drift_failures = _drift_failures(
        source_hashes_before,
        protected_hashes_before,
        input_hashes_before,
    )
    decision = _decision(
        rows,
        comparisons,
        behaviour_preflight=behaviour_preflight,
        drift_failures=drift_failures,
    )
    metadata = {
        "schema_version": "resetp.bounded-dual-view-archive-p1.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_short": _git("status", "--short"),
        "instances": list(INSTANCES),
        "arms": list(ARMS),
        "seed": SEED,
        "complete_candidate_budget_per_arm": BUDGET,
        "prescore_capacity": solver.PRESCORE_CAPACITY,
        "archive_capacity": solver.ARCHIVE_CAPACITY,
        "run_order": [
            {"instance": instance, "arm": arm}
            for instance, arm in run_order
        ],
        "fixed_environment": dict(FIXED_ENVIRONMENT),
        "prices": asdict(PRICES),
        "elapsed_seconds": time.perf_counter() - started,
        "python": sys.version,
        "platform": platform.platform(),
        "behaviour_preflight": behaviour_preflight,
        "source_hashes": source_hashes_before,
        "protected_file_hashes": protected_hashes_before,
        "input_hashes": input_hashes_before,
        "claim_boundary": (
            "Previously burned 20/25/50-customer, one-seed development "
            "training gate only. No fresh-instance, HGS, external ALNS, "
            "formal-performance, or stage-two claim."
        ),
        "formal_search_allowed": False,
        "stage2_activated": False,
    }

    output_dir.mkdir(parents=True, exist_ok=False)
    _write_csv(output_dir / "raw_runs.csv", rows)
    _write_json(output_dir / "comparisons.json", comparisons)
    _write_json(output_dir / "decision.json", decision)
    _write_json(
        output_dir / "archive_candidates.json",
        archive_candidates,
    )
    _write_json(output_dir / "solution_witnesses.json", witnesses)
    _write_json(output_dir / "metadata.json", metadata)
    _atomic_text(
        output_dir / "report.md",
        _report(comparisons, decision),
    )
    _write_json(
        output_dir / "artifact_hashes.json",
        {
            name: _sha256(output_dir / name)
            for name in OUTPUT_FILES
        },
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0 if not drift_failures else 2


def _worker_main() -> int:
    request = json.loads(sys.stdin.read())
    bundle_dir = Path(request["bundle"])
    instance = str(request["instance"])
    arm = str(request["arm"])
    if arm not in ARMS or instance not in INSTANCES:
        raise ValueError(f"unknown P1 request: {instance}:{arm}")
    start = _solution_from_payload(request["shared_start"])
    start_cost = independent_cost(bundle_dir, start, PRICES)
    worker_started = time.perf_counter()
    result = solver.run_bounded_dual_view_archive_alns(
        bundle_dir,
        seed=SEED,
        config=solver.BoundedDualViewArchiveConfig(
            total_eval_budget=BUDGET,
            enable_archive=arm == "candidate",
            runtime_cap_seconds=3600.0,
        ),
        prices=PRICES,
        initial_solution=start,
    )
    worker_solver_elapsed = time.perf_counter() - worker_started
    loaded = load_search_bundle(bundle_dir)
    recomputed = independent_cost(
        bundle_dir,
        result.best_solution,
        PRICES,
    )
    _require_finite(
        "p1_worker_cost",
        start_cost,
        result.best_cost,
        recomputed,
        result.elapsed_seconds,
        worker_solver_elapsed,
    )
    violations = check_solution(
        result.best_solution,
        loaded.instance,
        PRICES,
    )
    payload = {
        "instance": instance,
        "arm": arm,
        "budget": BUDGET,
        "enabled": arm == "candidate",
        "start_algorithm_signature": solution_signature_hash(start),
        "start_exact_signature": solver._exact_solution_hash(start),
        "start_cost": float(start_cost),
        "start_solution": asdict(start),
        "algorithm": result.algorithm,
        "evaluations": int(result.evaluations),
        "total_solver_elapsed_seconds": float(result.elapsed_seconds),
        "worker_solver_elapsed_seconds": float(worker_solver_elapsed),
        "claimed_final_cost": float(result.best_cost),
        "worker_recomputed_cost": float(recomputed),
        "worker_feasible": bool(result.feasible and not violations),
        "worker_violation_count": len(violations),
        "final_algorithm_signature": solution_signature_hash(
            result.best_solution
        ),
        "final_exact_signature": solver._exact_solution_hash(
            result.best_solution
        ),
        "final_solution": asdict(result.best_solution),
        "activity": result.mechanism_activity,
    }
    print(
        WORKER_SENTINEL
        + json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            default=_json_default,
        )
    )
    return 0


def _normalize_payload(
    bundle_dir: Path,
    payload: dict[str, Any],
    *,
    parent_audit: dict[str, Any],
) -> tuple[dict[str, Any], Solution]:
    final = _solution_from_payload(payload["final_solution"])
    loaded = load_search_bundle(bundle_dir)
    parent_cost = independent_cost(bundle_dir, final, PRICES)
    violations = check_solution(final, loaded.instance, PRICES)
    activity = dict(payload["activity"])
    score_counts = dict(activity["score_counts"])
    candidate_channel_sum = sum(
        int(value)
        for key, value in score_counts.items()
        if str(key).startswith("candidate_channel:")
    )
    prescore_rows = list(activity.get("prescore_rows", []))
    archive_entries = list(activity.get("archive_entries", []))
    skeletons = [
        str(entry["skeleton_signature"]) for entry in archive_entries
    ]
    candidate_ledger_closed = (
        int(payload["evaluations"])
        == int(activity["complete_search_candidate_evaluations"])
        == int(activity["candidate_scores"])
        == int(activity["actual_moves"])
        == int(activity["generic_candidate_evaluations"])
        == int(score_counts.get("candidate", 0))
        == int(candidate_channel_sum)
        == BUDGET
        and int(activity["mechanism_candidate_evaluations"]) == 0
    )
    terminal_replays = sum(
        int(
            entry["activity"].get(
                "full_solution_replays",
                0,
            )
        )
        for entry in archive_entries
    )
    reference_ledger_closed = (
        int(activity["prescore_candidate_count"])
        == int(activity["prescore_reference_replays"])
        == len(prescore_rows)
        and int(activity["archive_entry_count"])
        == int(activity["archive_completion_call_count"])
        == len(archive_entries)
        and int(activity["archive_completion_reference_replays"])
        == terminal_replays
        and int(activity["raw_search_independent_replays"]) == 1
        and int(activity["selected_final_independent_replays"]) == 1
        and int(activity["independent_final_replays"]) == 2
        and
        int(activity["post_search_full_solution_replays"])
        == int(activity["prescore_reference_replays"])
        + int(activity["archive_completion_reference_replays"])
        + int(activity["independent_final_replays"])
    )
    route_exact = sum(
        int(
            entry["activity"].get(
                "route_local_exact_evaluations",
                0,
            )
        )
        for entry in archive_entries
    )
    route_proxy = sum(
        int(entry["activity"].get("route_proxy_evaluations", 0))
        for entry in archive_entries
    ) + sum(
        int(
            entry["fast_activity"].get(
                "route_proxy_evaluations",
                0,
            )
        )
        for entry in prescore_rows
    )
    route_schedule = sum(
        int(
            entry["activity"].get(
                "route_local_schedule_evaluations",
                0,
            )
        )
        for entry in archive_entries
    ) + sum(
        int(
            entry["fast_activity"].get(
                "route_local_schedule_evaluations",
                0,
            )
        )
        for entry in prescore_rows
    )
    feasibility_checks = sum(
        int(
            entry["activity"].get(
                "full_feasibility_checks",
                0,
            )
        )
        for entry in archive_entries
    ) + sum(
        int(
            entry["fast_activity"].get(
                "full_feasibility_checks",
                0,
            )
        )
        for entry in prescore_rows
    )
    local_ledger_closed = (
        route_exact
        == int(activity["route_local_exact_evaluations"])
        and route_proxy == int(activity["route_proxy_evaluations"])
        and route_schedule
        == int(activity["route_local_schedule_evaluations"])
        and feasibility_checks
        == int(activity["mechanism_feasibility_checks"])
    )
    _require_finite(
        "p1_parent_costs",
        payload["start_cost"],
        activity["raw_search_cost"],
        activity["ordinary_final_completed_cost"],
        activity["selected_completed_cost"],
        payload["claimed_final_cost"],
        payload["worker_recomputed_cost"],
        parent_cost,
        payload["total_solver_elapsed_seconds"],
        payload["worker_solver_elapsed_seconds"],
    )
    return (
        {
            "instance": str(payload["instance"]),
            "arm": str(payload["arm"]),
            "algorithm": str(payload["algorithm"]),
            "seed": SEED,
            "budget": BUDGET,
            "start_algorithm_signature": str(
                payload["start_algorithm_signature"]
            ),
            "start_exact_signature": str(
                payload["start_exact_signature"]
            ),
            "start_cost": float(payload["start_cost"]),
            "evaluations": int(payload["evaluations"]),
            "candidate_scores": int(activity["candidate_scores"]),
            "actual_moves": int(activity["actual_moves"]),
            "generic_candidate_evaluations": int(
                activity["generic_candidate_evaluations"]
            ),
            "mechanism_candidate_evaluations": int(
                activity["mechanism_candidate_evaluations"]
            ),
            "candidate_channel_sum": int(candidate_channel_sum),
            "raw_search_reference_replays": int(
                activity["raw_search_reference_replays"]
            ),
            "prescore_candidate_count": int(
                activity["prescore_candidate_count"]
            ),
            "prescore_reference_replays": int(
                activity["prescore_reference_replays"]
            ),
            "archive_entry_count": int(
                activity["archive_entry_count"]
            ),
            "archive_completion_call_count": int(
                activity["archive_completion_call_count"]
            ),
            "archive_completion_reference_replays": int(
                activity["archive_completion_reference_replays"]
            ),
            "post_search_full_solution_replays": int(
                activity["post_search_full_solution_replays"]
            ),
            "independent_final_replays": int(
                activity["independent_final_replays"]
            ),
            "raw_search_independent_replays": int(
                activity["raw_search_independent_replays"]
            ),
            "selected_final_independent_replays": int(
                activity["selected_final_independent_replays"]
            ),
            "route_local_exact_evaluations": int(
                activity["route_local_exact_evaluations"]
            ),
            "route_proxy_evaluations": int(
                activity["route_proxy_evaluations"]
            ),
            "route_local_schedule_evaluations": int(
                activity["route_local_schedule_evaluations"]
            ),
            "mechanism_feasibility_checks": int(
                activity["mechanism_feasibility_checks"]
            ),
            "archive_feedback_into_search": bool(
                activity["archive_feedback_into_search"]
            ),
            "second_route_search_started": bool(
                activity["second_route_search_started"]
            ),
            "candidate_budget_equalized": bool(
                activity["candidate_budget_equalized"]
            ),
            "post_search_reference_work_equalized": bool(
                activity["post_search_reference_work_equalized"]
            ),
            "raw_search_cost": float(activity["raw_search_cost"]),
            "raw_search_algorithm_signature": str(
                activity["raw_search_signature"]
            ),
            "raw_search_exact_signature": str(
                activity["raw_search_exact_signature"]
            ),
            "raw_search_skeleton_signature": str(
                activity["raw_search_skeleton_signature"]
            ),
            "history_fingerprint": str(
                activity["main_search_history_fingerprint"]
            ),
            "operator_fingerprint": str(
                activity["main_search_operator_fingerprint"]
            ),
            "main_rng_fingerprint": str(
                activity["main_rng_final_state_sha256"]
            ),
            "selector_rng_fingerprint": str(
                activity["selector_rng_final_state_sha256"]
            ),
            "ordinary_final_forced": bool(
                activity["ordinary_final_forced"]
            ),
            "ordinary_final_completed_cost": float(
                activity["ordinary_final_completed_cost"]
            ),
            "ordinary_final_completed_exact_signature": str(
                activity[
                    "ordinary_final_completed_exact_signature"
                ]
            ),
            "archive_contributed": bool(
                activity["archive_contributed"]
            ),
            "archive_gain_percent": float(
                activity["archive_gain_over_ordinary_final_percent"]
            ),
            "archive_skeleton_count": len(set(skeletons)),
            "claimed_final_cost": float(payload["claimed_final_cost"]),
            "worker_recomputed_cost": float(
                payload["worker_recomputed_cost"]
            ),
            "parent_recomputed_cost": float(parent_cost),
            "final_algorithm_signature": str(
                payload["final_algorithm_signature"]
            ),
            "final_exact_signature": str(
                payload["final_exact_signature"]
            ),
            "worker_feasible": bool(payload["worker_feasible"]),
            "parent_feasible": not violations,
            "parent_violation_count": len(violations),
            "objective_match": (
                abs(
                    float(payload["claimed_final_cost"])
                    - float(payload["worker_recomputed_cost"])
                )
                <= 1.0e-7
                and abs(
                    float(payload["claimed_final_cost"])
                    - float(parent_cost)
                )
                <= 1.0e-7
            ),
            "candidate_ledger_closed": bool(
                candidate_ledger_closed
            ),
            "reference_ledger_closed": bool(
                reference_ledger_closed
            ),
            "local_ledger_closed": bool(local_ledger_closed),
            "parent_archive_audit_passed": bool(
                parent_audit.get("passed")
            ),
            "parent_archive_audit_failure_count": len(
                parent_audit.get("failures", [])
            ),
            "total_solver_elapsed_seconds": float(
                payload["total_solver_elapsed_seconds"]
            ),
            "worker_solver_elapsed_seconds": float(
                payload["worker_solver_elapsed_seconds"]
            ),
        },
        final,
    )


def _comparisons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = {
        (str(row["instance"]), str(row["arm"])): row for row in rows
    }
    comparisons: list[dict[str, Any]] = []
    for instance in INSTANCES:
        control = indexed[(instance, "control")]
        candidate = indexed[(instance, "candidate")]
        control_cost = float(control["parent_recomputed_cost"])
        candidate_cost = float(candidate["parent_recomputed_cost"])
        control_elapsed = float(
            control["total_solver_elapsed_seconds"]
        )
        candidate_elapsed = float(
            candidate["total_solver_elapsed_seconds"]
        )
        _require_finite(
            f"comparison:{instance}",
            control_cost,
            candidate_cost,
            control_elapsed,
            candidate_elapsed,
        )
        if control_cost <= 0.0 or control_elapsed <= 0.0:
            raise RuntimeError(
                f"comparison:{instance} has a non-positive denominator"
            )
        delta = candidate_cost - control_cost
        improvement = (
            100.0 * (control_cost - candidate_cost) / control_cost
        )
        comparisons.append(
            {
                "instance": instance,
                "same_start": (
                    control["start_exact_signature"]
                    == candidate["start_exact_signature"]
                    and abs(
                        float(control["start_cost"])
                        - float(candidate["start_cost"])
                    )
                    <= TOL
                ),
                "same_raw_search": all(
                    control[field] == candidate[field]
                    for field in (
                        "raw_search_cost",
                        "raw_search_exact_signature",
                        "raw_search_skeleton_signature",
                        "history_fingerprint",
                        "operator_fingerprint",
                        "main_rng_fingerprint",
                        "selector_rng_fingerprint",
                    )
                ),
                "same_ordinary_terminal": (
                    control["final_exact_signature"]
                    == candidate[
                        "ordinary_final_completed_exact_signature"
                    ]
                    and abs(
                        control_cost
                        - float(
                            candidate[
                                "ordinary_final_completed_cost"
                            ]
                        )
                    )
                    <= 1.0e-7
                ),
                "control_raw_search_cost": float(
                    control["raw_search_cost"]
                ),
                "candidate_raw_search_cost": float(
                    candidate["raw_search_cost"]
                ),
                "control_final_cost": control_cost,
                "candidate_ordinary_final_cost": float(
                    candidate["ordinary_final_completed_cost"]
                ),
                "candidate_final_cost": candidate_cost,
                "candidate_minus_control": float(delta),
                "improvement_percent": float(improvement),
                "strict_win": bool(delta < -TOL),
                "nonloss": bool(delta <= TOL),
                "regression_percent": max(0.0, -float(improvement)),
                "archive_contributed": bool(
                    candidate["archive_contributed"]
                ),
                "archive_gain_percent": float(
                    candidate["archive_gain_percent"]
                ),
                "control_elapsed_seconds": float(
                    control_elapsed
                ),
                "candidate_elapsed_seconds": float(
                    candidate_elapsed
                ),
                "wall_time_ratio": candidate_elapsed / control_elapsed,
            }
        )
    return comparisons


def _decision(
    rows: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    *,
    behaviour_preflight: dict[str, Any],
    drift_failures: list[str],
) -> dict[str, Any]:
    failures = list(drift_failures)
    if not bool(behaviour_preflight.get("passed")):
        failures.append("behaviour_preflight_failed")
    if len(rows) != 6:
        failures.append(f"raw_row_count:{len(rows)}")
    for row in rows:
        tag = f"{row['instance']}:{row['arm']}"
        if not bool(row["candidate_ledger_closed"]):
            failures.append(f"{tag}:candidate_ledger")
        if not bool(row["reference_ledger_closed"]):
            failures.append(f"{tag}:reference_ledger")
        if not bool(row["local_ledger_closed"]):
            failures.append(f"{tag}:local_ledger")
        if not bool(row["parent_archive_audit_passed"]):
            failures.append(f"{tag}:parent_archive_audit")
        if (
            not bool(row["worker_feasible"])
            or not bool(row["parent_feasible"])
            or not bool(row["objective_match"])
        ):
            failures.append(f"{tag}:replay_or_feasibility")
        if bool(row["archive_feedback_into_search"]):
            failures.append(f"{tag}:archive_feedback")
        if bool(row["second_route_search_started"]):
            failures.append(f"{tag}:second_route_search")
        if not _all_finite(
            row["start_cost"],
            row["raw_search_cost"],
            row["ordinary_final_completed_cost"],
            row["claimed_final_cost"],
            row["worker_recomputed_cost"],
            row["parent_recomputed_cost"],
            row["total_solver_elapsed_seconds"],
            row["worker_solver_elapsed_seconds"],
        ):
            failures.append(f"{tag}:nonfinite")
        if int(row["mechanism_candidate_evaluations"]) != 0:
            failures.append(f"{tag}:hidden_mechanism_candidate")
        if int(row["prescore_candidate_count"]) > solver.PRESCORE_CAPACITY:
            failures.append(f"{tag}:prescore_capacity")
        if int(row["archive_entry_count"]) > solver.ARCHIVE_CAPACITY:
            failures.append(f"{tag}:archive_capacity")
        if int(row["archive_skeleton_count"]) != int(
            row["archive_entry_count"]
        ):
            failures.append(f"{tag}:duplicate_skeleton")
        if not bool(row["ordinary_final_forced"]):
            failures.append(f"{tag}:ordinary_final_missing")
        if row["arm"] == "control":
            if int(row["prescore_candidate_count"]) != 0:
                failures.append(f"{tag}:control_prescore")
            if int(row["archive_entry_count"]) != 1:
                failures.append(f"{tag}:control_archive_size")
            if bool(row["archive_contributed"]):
                failures.append(f"{tag}:control_archive_contribution")

    for item in comparisons:
        tag = str(item["instance"])
        if not bool(item["same_start"]):
            failures.append(f"{tag}:start_mismatch")
        if not bool(item["same_raw_search"]):
            failures.append(f"{tag}:raw_search_drift")
        if not bool(item["same_ordinary_terminal"]):
            failures.append(f"{tag}:ordinary_terminal_drift")
        if abs(
            float(item["control_final_cost"])
            - float(item["candidate_ordinary_final_cost"])
        ) > 1.0e-7:
            failures.append(f"{tag}:ordinary_branch_drift")
        if (
            float(item["candidate_final_cost"])
            > float(item["candidate_ordinary_final_cost"]) + TOL
        ):
            failures.append(f"{tag}:monotone_envelope")
        if not _all_finite(
            item["control_final_cost"],
            item["candidate_ordinary_final_cost"],
            item["candidate_final_cost"],
            item["candidate_minus_control"],
            item["improvement_percent"],
            item["regression_percent"],
            item["control_elapsed_seconds"],
            item["candidate_elapsed_seconds"],
            item["wall_time_ratio"],
        ):
            failures.append(f"{tag}:comparison_nonfinite")

    wins = sum(int(item["strict_win"]) for item in comparisons)
    nonlosses = sum(int(item["nonloss"]) for item in comparisons)
    active = sum(
        int(item["archive_contributed"]) for item in comparisons
    )
    improvements = [
        float(item["improvement_percent"]) for item in comparisons
    ]
    regressions = [
        float(item["regression_percent"]) for item in comparisons
    ]
    wall_ratios = [
        float(item["wall_time_ratio"]) for item in comparisons
    ]
    if not _all_finite(*improvements, *regressions, *wall_ratios):
        failures.append("aggregate_nonfinite")
    median_improvement = float(median(improvements))
    max_regression = max(regressions)
    median_wall = float(median(wall_ratios))
    max_wall = max(wall_ratios)
    gate_checks = {
        "three_of_three_nonloss": nonlosses == 3,
        "strict_wins_at_least_two": wins >= 2,
        "median_improvement_at_least_one_percent": (
            median_improvement >= 1.0
        ),
        "maximum_regression_at_most_one_percent": (
            max_regression <= 1.0
        ),
        "archive_contributed_on_at_least_two_instances": active >= 2,
        "median_wall_ratio_at_most_1_25": median_wall <= 1.25,
        "maximum_wall_ratio_at_most_1_50": max_wall <= 1.50,
    }
    passed = not failures and all(gate_checks.values())
    return {
        "verdict": (
            "PASS_BOUNDED_ARCHIVE_P1_OLD_THREE_INSTANCE_GATE"
            if passed
            else "STOP_BOUNDED_ARCHIVE_P1_OLD_THREE_INSTANCE_GATE"
        ),
        "passed": bool(passed),
        "execution_failures": failures,
        "gate_checks": gate_checks,
        "strict_win_count": wins,
        "nonloss_count": nonlosses,
        "archive_contributed_instance_count": active,
        "median_improvement_percent": median_improvement,
        "maximum_regression_percent": max_regression,
        "median_wall_time_ratio": median_wall,
        "maximum_wall_time_ratio": max_wall,
        "next_allowed_step": (
            "lock_candidate_and_run_fresh_D3_minigate"
            if passed
            else "stop_bounded_archive_without_capacity_or_ranking_tuning"
        ),
        "fresh_d3_allowed": bool(passed),
        "formal_search_allowed": False,
        "stage2_allowed": False,
    }


def _verify_behaviour_gate() -> dict[str, Any]:
    decision_path = BEHAVIOUR_DIR / "decision.json"
    hashes_path = BEHAVIOUR_DIR / "artifact_hashes.json"
    if not decision_path.is_file() or not hashes_path.is_file():
        return {"passed": False, "reason": "missing_behaviour_evidence"}
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    expected_hashes = json.loads(hashes_path.read_text(encoding="utf-8"))
    appledouble_contamination = behaviour._appledouble_paths(
        (BEHAVIOUR_DIR,)
    )
    mismatches = [
        name
        for name, expected in expected_hashes.items()
        if not (BEHAVIOUR_DIR / name).is_file()
        or _sha256(BEHAVIOUR_DIR / name) != expected
    ]
    metadata = json.loads(
        (BEHAVIOUR_DIR / "metadata.json").read_text(encoding="utf-8")
    )
    source_commit = str(metadata.get("git_head", ""))
    ancestor = bool(
        source_commit
        and subprocess.run(
            ["git", "merge-base", "--is-ancestor", source_commit, "HEAD"],
            cwd=REPO,
            check=False,
        ).returncode
        == 0
    )
    evidence_tracked = (
        subprocess.run(
            [
                "git",
                "ls-files",
                "--error-unmatch",
                "--",
                str(decision_path.relative_to(REPO)),
            ],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )
    evidence_clean = not subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--",
            str(BEHAVIOUR_DIR.relative_to(REPO)),
        ],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    ).stdout.strip()
    return {
        "passed": bool(
            decision.get("passed")
            and not mismatches
            and not appledouble_contamination
            and ancestor
            and evidence_tracked
            and evidence_clean
        ),
        "verdict": decision.get("verdict"),
        "artifact_hash_mismatches": mismatches,
        "appledouble_contamination": appledouble_contamination,
        "source_commit": source_commit,
        "source_commit_is_ancestor": ancestor,
        "evidence_tracked": evidence_tracked,
        "evidence_clean": evidence_clean,
    }


def _shared_start(bundle_dir: Path) -> Solution:
    bundle = load_search_bundle(bundle_dir)
    start = build_initial_solution(
        bundle.instance,
        bundle.carbon_profile,
        PRICES,
        introduce_ev=False,
        require_charging_signal=False,
    )
    start = annotate_cross_site_services(
        start,
        infer_customer_home_depots(bundle.instance),
    )
    violations = check_solution(start, bundle.instance, PRICES)
    if violations:
        raise RuntimeError(
            f"shared P1 start is infeasible for {bundle_dir.name}: "
            f"{violations[:8]}"
        )
    independent_cost(bundle_dir, start, PRICES)
    return start


def _invoke_worker(request: dict[str, Any]) -> dict[str, Any]:
    environment = dict(os.environ)
    environment.update(FIXED_ENVIRONMENT)
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker"],
        cwd=REPO,
        env=environment,
        input=json.dumps(request, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "bounded archive P1 worker failed: "
            f"rc={completed.returncode}\n{completed.stderr[-4000:]}"
        )
    lines = [
        row
        for row in completed.stdout.splitlines()
        if row.startswith(WORKER_SENTINEL)
    ]
    if len(lines) != 1:
        raise RuntimeError(
            "bounded archive P1 worker must emit exactly one sentinel: "
            f"{len(lines)}"
        )
    return json.loads(lines[0][len(WORKER_SENTINEL) :])


def _report(
    comparisons: list[dict[str, Any]],
    decision: dict[str, Any],
) -> str:
    lines = [
        "# 有界双视图档案旧三题强度门",
        "",
        f"判定：`{decision['verdict']}`",
        "",
        "这只是已经使用过的 20/25/50 客户、单种子开发门，不是新鲜验证或"
        "正式实验。",
        "",
        "| 实例 | 控制终局 | 候选普通终局 | 候选最终 | 改善 | 档案贡献 | 墙钟比 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in comparisons:
        lines.append(
            "| {instance} | {control_final_cost:.9f} | "
            "{candidate_ordinary_final_cost:.9f} | "
            "{candidate_final_cost:.9f} | "
            "{improvement_percent:.6f}% | {archive_contributed} | "
            "{wall_time_ratio:.4f} |".format(**row)
        )
    lines.extend(
        [
            "",
            f"严格胜：{decision['strict_win_count']}/3；"
            f"不倒退：{decision['nonloss_count']}/3；"
            f"档案真实贡献："
            f"{decision['archive_contributed_instance_count']}/3。",
            "",
            f"中位改善：{decision['median_improvement_percent']:.6f}%；"
            f"最大倒退：{decision['maximum_regression_percent']:.6f}%；"
            f"中位墙钟比：{decision['median_wall_time_ratio']:.4f}；"
            f"最大墙钟比：{decision['maximum_wall_time_ratio']:.4f}。",
            "",
            "无论 PASS 或 STOP，均不得直接进入阶段二或正式全量实验。",
        ]
    )
    if decision["execution_failures"]:
        lines.extend(["", "执行失败项："])
        lines.extend(
            f"- `{failure}`"
            for failure in decision["execution_failures"]
        )
    return "\n".join(lines) + "\n"


def _require_clean_sources() -> None:
    failures: list[str] = []
    for path in SOURCE_FILES:
        if not (REPO / path).is_file():
            failures.append(f"missing:{path}")
            continue
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", path],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        ).returncode == 0
        if not tracked:
            failures.append(f"untracked:{path}")
            continue
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--", path],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        ).stdout.strip()
        if status:
            failures.append(f"dirty:{path}")
    if failures:
        raise RuntimeError(
            "P1 sources must be committed first: " + ", ".join(failures)
        )


def _drift_failures(
    source_hashes: dict[str, str],
    protected_hashes: dict[str, str],
    input_hashes: dict[str, str],
) -> list[str]:
    failures: list[str] = []
    for path, expected in source_hashes.items():
        if _sha256(REPO / path) != expected:
            failures.append(f"source_drift:{path}")
    for path, expected in protected_hashes.items():
        if _sha256(REPO / path) != expected:
            failures.append(f"protected_drift:{path}")
    if _input_hashes(
        tuple(ARCHIVE / instance for instance in INSTANCES)
    ) != input_hashes:
        failures.append("input_drift")
    return failures


def _input_hashes(bundle_dirs: tuple[Path, ...]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for bundle_dir in bundle_dirs:
        for path in sorted(
            item for item in bundle_dir.rglob("*") if item.is_file()
        ):
            hashes[_relative(path)] = _sha256(path)
    return hashes


def _add_witness(
    witnesses: dict[str, Any],
    solution: Solution,
    metadata: dict[str, Any],
) -> None:
    exact = solver._exact_solution_hash(solution)
    snapshot = asdict(solution)
    if exact in witnesses and witnesses[exact]["solution"] != snapshot:
        raise RuntimeError(
            "full-content witness hash collision with unequal payloads"
        )
    row = witnesses.setdefault(
        exact,
        {
            "full_content_sha256": exact,
            "algorithm_signature": solution_signature_hash(solution),
            "solution": snapshot,
            "uses": [],
        },
    )
    row["uses"].append(metadata)


def _solution_from_payload(payload: dict[str, Any]) -> Solution:
    return Solution(
        routes=[
            Route(
                str(row["vehicle_id"]),
                str(row["vehicle_type"]),
                str(row["home_depot_id"]),
                [str(node) for node in row["node_sequence"]],
            )
            for row in payload.get("routes", [])
        ],
        charging_actions=[
            ChargingAction(
                str(row["vehicle_id"]),
                str(row["station_id"]),
                float(row["energy_kwh"]),
                float(row["occupancy_minutes"]),
                float(row["charge_start_second"]),
                int(row.get("charge_day_offset", 0)),
            )
            for row in payload.get("charging_actions", [])
        ],
        cross_site_services=[
            CrossSiteService(
                str(row["customer_id"]),
                str(row["served_by_depot_id"]),
            )
            for row in payload.get("cross_site_services", [])
        ],
    )


def _freeze_environment() -> None:
    for key, value in FIXED_ENVIRONMENT.items():
        os.environ[key] = value


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("refusing to write empty P1 CSV")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    _atomic_text(
        path,
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n",
    )


def _atomic_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(REPO.resolve()))


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _all_finite(*values: Any) -> bool:
    try:
        return all(math.isfinite(float(value)) for value in values)
    except (TypeError, ValueError):
        return False


def _require_finite(label: str, *values: Any) -> None:
    if not _all_finite(*values):
        raise RuntimeError(f"{label} contains a non-finite value: {values}")


if __name__ == "__main__":
    raise SystemExit(main())
